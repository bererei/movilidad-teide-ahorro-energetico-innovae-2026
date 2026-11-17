"""cartografia: fuentes rutas. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from movilidad_teide.cartografia.geografia_tipos import GeographicDataError
from movilidad_teide.cartografia.geometrias import combine_ordered_parts
from movilidad_teide.cartografia.geometrias import ensure_metric_crs
from movilidad_teide.trazabilidad import file_sha256
from movilidad_teide.cartografia.geometrias import route_validation_table
from movilidad_teide.cartografia.itinerarios_tipos import ItineraryExtractionError
from movilidad_teide.cartografia.itinerarios_tipos import ItineraryConfigError


def build_source_inventory(
    config: Mapping[str, Any], project_root: str | Path
) -> pd.DataFrame:
    """Calculate file existence and SHA-256 agreement for every declared source."""

    root = Path(project_root).resolve()
    rows: list[dict[str, Any]] = []
    for source_id, source in config["sources"].items():
        path = root / source["path"]
        exists = path.is_file()
        actual_sha256 = file_sha256(path) if exists else None
        rows.append(
            {
                "source_id": source_id,
                "kind": source["kind"],
                "path": source["path"],
                "layer": source.get("layer"),
                "provider": source["provider"],
                "source_url": source.get("source_url"),
                "downloaded_on": source.get("downloaded_on"),
                "version": source["version"],
                "license": source.get("license"),
                "limitations": source.get("limitations"),
                "exists": exists,
                "expected_sha256": source["expected_sha256"],
                "actual_sha256": actual_sha256,
                "sha256_matches": exists and actual_sha256 == source["expected_sha256"],
            }
        )
    return pd.DataFrame(rows)


def verify_source_inventory(inventory: pd.DataFrame) -> None:
    """Reject missing or changed sources before any extraction."""

    invalid = inventory[~inventory["exists"] | ~inventory["sha256_matches"]]
    if not invalid.empty:
        details = invalid[
            ["source_id", "path", "exists", "sha256_matches"]
        ].to_dict(orient="records")
        raise ItineraryExtractionError(
            f"Hay fuentes ausentes o con huella distinta de la configurada: {details}."
        )


def _read_osm_axes(path: Path, way_ids) -> gpd.GeoDataFrame:
    """Read explicitly selected OSM ways, preserving original nodes and versions.

    Selecting a sequence remains a catalogue decision. This reader performs no
    routing, snapping, simplification or repair of missing road connections.
    """
    import xml.etree.ElementTree as ET
    if not way_ids or len(set(map(str, way_ids))) != len(way_ids):
        raise ItineraryConfigError('Declare identificadores OSM únicos para la fuente.')
    root = ET.parse(path).getroot()
    nodes = {}
    for node in root.findall('node'):
        ident = node.get('id')
        if ident in nodes:
            raise ItineraryExtractionError('El original OSM contiene nodos duplicados.')
        nodes[ident] = (float(node.get('lon')), float(node.get('lat')))
    selected = set(map(str, way_ids)); found = set(); rows = []
    for way in root.findall('way'):
        ident = way.get('id')
        if ident not in selected:continue
        if ident in found:
            raise ItineraryExtractionError('El original OSM contiene vías duplicadas.')
        found.add(ident)
        tags = {t.get('k'):t.get('v') for t in way.findall('tag')}
        refs = [n.get('ref') for n in way.findall('nd')]
        if 'highway' not in tags or len(refs)<2 or not set(refs)<=set(nodes):
            raise ItineraryExtractionError('Una vía OSM seleccionada no tiene carretera o nodos completos.')
        rows.append({'osm_way_id':ident,'osm_version':way.get('version'),'osm_timestamp':way.get('timestamp'),
            'highway':tags['highway'],'road_ref':tags.get('ref'),'name':tags.get('name'),
            'oneway':tags.get('oneway'),'junction':tags.get('junction'),
            'access':tags.get('access'),'vehicle':tags.get('vehicle'),'motor_vehicle':tags.get('motor_vehicle'),
            'motorcar':tags.get('motorcar'),'conditional_tags_json':json.dumps({k:v for k,v in tags.items() if ':conditional' in k},sort_keys=True),
            'from_node':refs[0],'to_node':refs[-1],
            'source_node_ids_json':json.dumps(refs),'geometry':LineString([nodes[n] for n in refs])})
    if found!=selected:
        raise ItineraryExtractionError('Faltan vías OSM seleccionadas en el original.')
    return gpd.GeoDataFrame(rows,crs='EPSG:4326')

def _read_gtfs_stop_points(path, stop_ids):
    """Leer paradas originales expresamente seleccionadas, sin copiar coordenadas.

    Su ubicación sirve de referencia geográfica; no prueba uso de la línea,
    origen observado, acceso a la instalación o reparto modal del futuro.
    """
    from zipfile import ZipFile
    if not stop_ids or len(set(map(str,stop_ids))) != len(stop_ids):
        raise ItineraryConfigError('Declare identificadores GTFS únicos para las referencias.')
    with ZipFile(path) as archive:
        if archive.namelist().count('stops.txt') != 1:
            raise ItineraryExtractionError('La fuente GTFS debe contener un único stops.txt en su raíz.')
        frame = pd.read_csv(archive.open('stops.txt'),dtype={'stop_id':'string'})
    if not {'stop_id','stop_lon','stop_lat'} <= set(frame):
        raise ItineraryExtractionError('Faltan identificadores o coordenadas GTFS.')
    if frame.stop_id.isna().any() or frame.stop_id.duplicated().any():
        raise ItineraryExtractionError('Las paradas GTFS tienen claves ausentes o repetidas.')
    selected = frame.loc[frame.stop_id.isin(list(map(str,stop_ids)))].copy()
    if set(selected.stop_id) != set(map(str,stop_ids)):
        raise ItineraryExtractionError('Faltan referencias GTFS seleccionadas en el original.')
    try:
        coordinates = selected[['stop_lon','stop_lat']].to_numpy(dtype=float)
    except (ValueError,TypeError) as exc:
        raise ItineraryExtractionError('Coordenadas GTFS no numéricas.') from exc
    if (not np.isfinite(coordinates).all() or not np.all(np.abs(coordinates[:,0])<=180)
            or not np.all(np.abs(coordinates[:,1])<=90)):
        raise ItineraryExtractionError('Coordenadas GTFS ausentes o fuera de rango.')
    return gpd.GeoDataFrame(selected,geometry=gpd.points_from_xy(coordinates[:,0],coordinates[:,1]),crs='EPSG:4326')

def read_geospatial_source(
    source_id: str,
    config: Mapping[str, Any],
    project_root: str | Path,
) -> gpd.GeoDataFrame:
    """Read one explicitly configured geospatial layer without altering it."""

    source = config["sources"].get(source_id)
    if source is None:
        raise ItineraryConfigError(f"Fuente inexistente: {source_id!r}.")
    if source["kind"] not in {"road_axes", "kilometer_points", "route_geometry", "point_references"}:
        raise ItineraryConfigError(f"La fuente {source_id!r} no es geoespacial.")
    path = Path(project_root).resolve() / source["path"]
    if source.get("format") == "osm_xml":
        frame = _read_osm_axes(path, source.get("osm_way_ids"))
    elif source.get("format") == "gtfs_stops":
        frame = _read_gtfs_stop_points(path,source.get("stop_ids"))
    else:
        frame = gpd.read_file(path, layer=source["layer"])
    if frame.empty:
        raise ItineraryExtractionError(f"La fuente {source_id!r} está vacía.")
    if frame.crs is None:
        raise ItineraryExtractionError(f"La fuente {source_id!r} no declara CRS.")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ItineraryExtractionError(
            f"La fuente {source_id!r} contiene geometrías ausentes o vacías."
        )
    if not frame.geometry.is_valid.all():
        raise ItineraryExtractionError(
            f"La fuente {source_id!r} contiene geometrías no válidas."
        )
    frame = frame.copy()
    frame["source_feature_index"] = frame.index.map(str)
    return frame

def select_exact_records(
    frame: gpd.GeoDataFrame,
    filters: Mapping[str, Any],
    *,
    require_unique: bool = True,
) -> gpd.GeoDataFrame:
    """Select records using exact equality and reject absent or ambiguous matches."""

    if not filters:
        raise ItineraryConfigError("La selección exacta requiere al menos un filtro.")
    mask = pd.Series(True, index=frame.index)
    for field, expected in filters.items():
        if field not in frame.columns:
            raise ItineraryExtractionError(f"La fuente no contiene el campo {field!r}.")
        mask &= frame[field].eq(expected)
    selected = frame.loc[mask].copy()
    if selected.empty:
        raise ItineraryExtractionError(
            f"Ningún registro cumple los filtros exactos: {dict(filters)}."
        )
    if require_unique and len(selected) != 1:
        raise ItineraryExtractionError(
            f"Selección ambigua ({len(selected)} registros) para: {dict(filters)}."
        )
    return selected

def explode_line_components(
    frame: gpd.GeoDataFrame,
    source_id: str,
    source_sha256: str,
) -> gpd.GeoDataFrame:
    """Explode line features while retaining attributes and stable provenance."""

    rows: list[dict[str, Any]] = []
    for _, record in frame.iterrows():
        geometry = record.geometry
        if isinstance(geometry, LineString):
            parts = [geometry]
        elif isinstance(geometry, MultiLineString):
            parts = list(geometry.geoms)
        else:
            raise ItineraryExtractionError(
                f"La fuente {source_id!r} contiene una geometría {geometry.geom_type}; se esperaba línea."
            )
        attributes = record.drop(labels=[frame.geometry.name]).to_dict()
        for component_index, part in enumerate(parts):
            geometry_sha256 = sha256(part.wkb).hexdigest()
            rows.append(
                {
                    **attributes,
                    "source_id": source_id,
                    "source_sha256": source_sha256,
                    "source_geometry_type": geometry.geom_type,
                    "component_index": component_index,
                    "component_count": len(parts),
                    "component_geometry_sha256": geometry_sha256,
                    "component_id": (
                        f"{source_id}:{attributes['source_feature_index']}:"
                        f"{component_index}:{geometry_sha256[:16]}"
                    ),
                    "geometry": part,
                }
            )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=frame.crs)
