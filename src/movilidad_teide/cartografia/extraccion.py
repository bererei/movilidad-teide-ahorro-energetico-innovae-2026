"""cartografia: extraccion. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import substring
from movilidad_teide.cartografia.geografia_tipos import GeographicDataError
from movilidad_teide.cartografia.geometrias import combine_ordered_parts
from movilidad_teide.cartografia.geometrias import ensure_metric_crs
from movilidad_teide.trazabilidad import file_sha256
from movilidad_teide.cartografia.geometrias import route_validation_table
from movilidad_teide.cartografia.itinerarios_tipos import ItineraryExtractionError
from movilidad_teide.cartografia.itinerarios_tipos import ItineraryConfigError
from movilidad_teide.cartografia.itinerarios_tipos import ItineraryExtractionResult


def _reverse_line(line: LineString) -> LineString:
    return LineString(list(line.coords)[::-1])


def select_ordered_axis_parts(
    component_frames: Mapping[str, gpd.GeoDataFrame],
    part_specs: Sequence[Mapping[str, Any]],
    target_crs: str | CRS,
    continuity_tolerance_m: float,
    length_tolerance_m: float,
    *,
    clip_anchors: Mapping[str, Point] | None = None,
    anchor_axis_tolerance_m: float = 1.0,
) -> tuple[LineString, gpd.GeoDataFrame, float]:
    """Select, orient and combine an explicit sequence of official line parts."""
    from movilidad_teide.cartografia.fuentes_rutas import select_exact_records

    ensure_metric_crs(target_crs)
    selected_rows: list[dict[str, Any]] = []
    selected_lines: list[LineString] = []
    previous_end: Point | None = None
    maximum_gap_m = 0.0

    for sequence, spec in enumerate(part_specs, start=1):
        source_id = spec["source_id"]
        if source_id not in component_frames:
            raise ItineraryExtractionError(
                f"No se cargaron componentes para la fuente {source_id!r}."
            )
        frame = component_frames[source_id]
        filters = {
            **spec["feature_filters"],
            "component_index": spec["component_index"],
        }
        selected = select_exact_records(frame, filters)
        selected_projected = selected.to_crs(target_crs)
        row = selected_projected.iloc[0]
        line = row.geometry
        if not isinstance(line, LineString):
            raise ItineraryExtractionError("Un componente descompuesto dejó de ser LineString.")
        if spec["reverse"]:
            line = _reverse_line(line)
        full_length_m = float(line.length)
        # Recortar antes de unir permite conexiones en puntos interiores de los ejes.
        if "clip_start_anchor_id" in spec:
            ids = [spec["clip_start_anchor_id"], spec["clip_end_anchor_id"]]
            if clip_anchors is None or any(key not in clip_anchors for key in ids):
                raise ItineraryExtractionError("Faltan anclajes resueltos para recortar el componente.")
            points = [clip_anchors[key] for key in ids]
            if any(line.distance(point) > anchor_axis_tolerance_m for point in points):
                raise ItineraryExtractionError("Un anclaje de recorte está fuera del eje del componente.")
            start, end = [float(line.project(point)) for point in points]
            if spec.get("wrap_ring", False):
                # Un arco positivo puede pasar por el inicio del anillo original, sin invertirlo.
                if not line.is_ring or start - end <= length_tolerance_m:
                    raise ItineraryExtractionError("El arco envolvente requiere anillo simple y anclajes distintos en orden envolvente.")
                tail = substring(line, start, full_length_m)
                coords = list(tail.coords)
                if end > 0:
                    coords.extend(list(substring(line, 0, end).coords)[1:])
                line = LineString(coords)
            else:
                if end - start <= length_tolerance_m:
                    raise ItineraryExtractionError("Anclajes de recorte fuera de orden o tramo vacío.")
                line = substring(line, start, end)

        gap_m = 0.0 if previous_end is None else previous_end.distance(Point(line.coords[0]))
        maximum_gap_m = max(maximum_gap_m, gap_m)
        if gap_m > continuity_tolerance_m:
            raise ItineraryExtractionError(
                f"Discontinuidad de {gap_m:.6f} m antes del componente {sequence}; "
                f"tolerancia {continuity_tolerance_m:.6f} m."
            )
        previous_end = Point(line.coords[-1])
        selected_lines.append(line)
        selected_rows.append(
            {
                "sequence": sequence,
                "source_id": source_id,
                "source_feature_index": row["source_feature_index"],
                "component_id": row["component_id"],
                "component_index": int(row["component_index"]),
                "component_geometry_sha256": row["component_geometry_sha256"],
                "feature_filters_json": json.dumps(
                    spec["feature_filters"], ensure_ascii=False, sort_keys=True
                ),
                "reverse_applied": bool(spec["reverse"]),
                **({"wrap_ring_applied": True} if spec.get("wrap_ring", False) else {}),
                "gap_from_previous_m": gap_m,
                "source_length_m": float(line.length),
                "full_component_length_m": full_length_m,
                "clip_start_anchor_id": spec.get("clip_start_anchor_id"),
                "clip_end_anchor_id": spec.get("clip_end_anchor_id"),
                "geometry": line,
            }
        )

    combined = combine_ordered_parts(selected_lines, continuity_tolerance_m)
    source_length_m = float(sum(line.length for line in selected_lines))
    length_error_m = float(combined.length - source_length_m)
    if abs(length_error_m) > length_tolerance_m:
        raise ItineraryExtractionError(
            "La combinación no conserva la longitud de los componentes: "
            f"error {length_error_m:.9f} m."
        )
    lineage = gpd.GeoDataFrame(selected_rows, geometry="geometry", crs=target_crs)
    return combined, lineage, maximum_gap_m

def resolve_anchor(
    anchor_id: str,
    anchor_spec: Mapping[str, Any],
    source_frames: Mapping[str, gpd.GeoDataFrame],
    target_crs: str | CRS,
    *,
    anchor_specs: Mapping[str, Mapping[str, Any]] | None = None,
    _resolving: frozenset[str] = frozenset(),
) -> gpd.GeoDataFrame:
    """Resolve one coordinate, official PK or unambiguous geometry endpoint."""
    from movilidad_teide.cartografia.fuentes_rutas import select_exact_records

    if anchor_id in _resolving:
        raise ItineraryExtractionError("Dependencia circular al resolver anclajes.")
    _resolving = _resolving | {anchor_id}
    anchor_type = anchor_spec["type"]
    source_id = anchor_spec.get("source_id")
    reference: dict[str, Any]

    if anchor_type == "coordinate":
        point_frame = gpd.GeoDataFrame(
            {"geometry": [Point(anchor_spec["coordinates"])]}, crs=anchor_spec["crs"]
        ).to_crs(target_crs)
        point = point_frame.geometry.iloc[0]
        reference = {
            "coordinates": anchor_spec["coordinates"],
            "crs": anchor_spec["crs"],
        }
    elif anchor_type == "source_point":
        if source_id not in source_frames:
            raise ItineraryExtractionError(f"No se cargó la fuente del punto {anchor_id}.")
        selected = select_exact_records(source_frames[source_id], anchor_spec["feature_filters"]).to_crs(target_crs)
        point = selected.geometry.iloc[0]
        if not isinstance(point, Point) or point.is_empty or not np.isfinite([point.x, point.y]).all():
            raise ItineraryExtractionError(f"{anchor_id}: la referencia debe ser un Point finito y único.")
        reference = {"feature_filters": anchor_spec["feature_filters"], "criterion": "Punto original sin trasladar ni duplicar coordenadas"}
    elif anchor_type == "official_pk":
        if source_id not in source_frames:
            raise ItineraryExtractionError(
                f"No se cargó la fuente del anclaje {anchor_id}: {source_id!r}."
            )
        selected = select_exact_records(
            source_frames[source_id],
            {"via_nombre": anchor_spec["road_name"], "pk_numero": anchor_spec["pk"]},
        ).to_crs(target_crs)
        point = selected.geometry.iloc[0]
        if not isinstance(point, Point):
            raise ItineraryExtractionError(
                f"El PK del anclaje {anchor_id} no tiene geometría Point."
            )
        reference = {"road_name": anchor_spec["road_name"], "pk": anchor_spec["pk"]}
    else:
        if source_id not in source_frames:
            raise ItineraryExtractionError(
                f"No se cargó la fuente del anclaje {anchor_id}: {source_id!r}."
            )
        selected = select_exact_records(
            source_frames[source_id], anchor_spec["feature_filters"]
        ).to_crs(target_crs)
        geometry = selected.geometry.iloc[0]
        if isinstance(geometry, MultiLineString):
            component_index = anchor_spec.get("component_index")
            if component_index is None or not 0 <= component_index < len(geometry.geoms):
                raise ItineraryExtractionError(
                    f"El anclaje {anchor_id} sobre MultiLineString requiere component_index válido."
                )
            geometry = geometry.geoms[component_index]
        if not isinstance(geometry, LineString):
            raise ItineraryExtractionError(
                f"El anclaje {anchor_id} requiere una geometría lineal."
            )
        if anchor_spec["geometry_position"] == "projection":
            reference_id = anchor_spec.get("reference_anchor_id", anchor_spec.get("coordinate_anchor_id"))
            legacy = "coordinate_anchor_id" in anchor_spec
            if anchor_specs is None or reference_id not in anchor_specs or (legacy and anchor_specs[reference_id].get("type") != "coordinate"):
                raise ItineraryExtractionError("La proyección requiere una coordenada maestra existente o referencia maestra válida.")
            original = resolve_anchor(reference_id, anchor_specs[reference_id], source_frames, target_crs,
                                      anchor_specs=anchor_specs, _resolving=_resolving).geometry.iloc[0]
            point = geometry.interpolate(geometry.project(original))
        else:
            coordinate = geometry.coords[0] if anchor_spec["geometry_position"] == "start" else geometry.coords[-1]
            point = Point(coordinate)
        reference = {
            "feature_filters": anchor_spec["feature_filters"],
            "component_index": anchor_spec.get("component_index"),
            "geometry_position": anchor_spec["geometry_position"],
        }
        if anchor_spec["geometry_position"] == "projection":
            reference.update({("coordinate_anchor_id" if "coordinate_anchor_id" in anchor_spec else "reference_anchor_id"): reference_id,
                              "reference_offset_m": float(original.distance(point)),
                              "criterion": "Proyección cartográfica explícita; no conexión física ni traslado de cabecera"})

    return gpd.GeoDataFrame(
        {
            "anchor_id": [anchor_id],
            "label": [anchor_spec["label"]],
            "anchor_type": [anchor_type],
            "source_id": [source_id],
            "source_reference_json": [
                json.dumps(reference, ensure_ascii=False, sort_keys=True)
            ],
            "validation_status": [anchor_spec["validation_status"]],
            "geometry": [point],
        },
        geometry="geometry",
        crs=target_crs,
    )

def orient_clip_and_validate_anchors(
    axis: LineString,
    anchors: gpd.GeoDataFrame,
    anchor_axis_tolerance_m: float,
    length_tolerance_m: float,
) -> tuple[LineString, gpd.GeoDataFrame, bool, float]:
    """Orient an axis origin-to-destination, validate ordered anchors and clip it."""

    if len(anchors) < 2:
        raise ItineraryExtractionError("Se requieren al menos origen y destino.")
    working_axis = axis
    origin = anchors.geometry.iloc[0]
    destination = anchors.geometry.iloc[-1]
    origin_measure = working_axis.project(origin)
    destination_measure = working_axis.project(destination)
    route_reversed = destination_measure < origin_measure
    if route_reversed:
        working_axis = _reverse_line(working_axis)

    resolved = anchors.copy()
    measures: list[float] = []
    offsets: list[float] = []
    snapped_x: list[float] = []
    snapped_y: list[float] = []
    for point in resolved.geometry:
        measure = float(working_axis.project(point))
        snapped = working_axis.interpolate(measure)
        offset = float(point.distance(snapped))
        if offset > anchor_axis_tolerance_m:
            raise ItineraryExtractionError(
                f"Anclaje a {offset:.6f} m del eje; tolerancia {anchor_axis_tolerance_m:.6f} m."
            )
        measures.append(measure)
        offsets.append(offset)
        snapped_x.append(float(snapped.x))
        snapped_y.append(float(snapped.y))

    differences = np.diff(np.asarray(measures))
    if np.any(differences <= length_tolerance_m):
        raise ItineraryExtractionError(
            "Los anclajes no aparecen en orden estricto origen–intermedios–destino."
        )
    clipped = substring(working_axis, measures[0], measures[-1])
    if not isinstance(clipped, LineString) or clipped.is_empty:
        raise ItineraryExtractionError("El recorte no produjo una LineString no vacía.")
    expected_length_m = measures[-1] - measures[0]
    clipping_error_m = float(clipped.length - expected_length_m)
    if abs(clipping_error_m) > length_tolerance_m:
        raise ItineraryExtractionError(
            f"El recorte no conserva la longitud lineal: error {clipping_error_m:.9f} m."
        )

    resolved["axis_measure_m"] = measures
    resolved["itinerary_measure_m"] = np.asarray(measures) - measures[0]
    resolved["axis_offset_m"] = offsets
    resolved["snapped_x_m"] = snapped_x
    resolved["snapped_y_m"] = snapped_y
    return clipped, resolved, route_reversed, clipping_error_m

def _resolve_configured_anchors(
    itinerary: Mapping[str, Any],
    config: Mapping[str, Any],
    source_frames: Mapping[str, gpd.GeoDataFrame],
) -> gpd.GeoDataFrame:
    anchor_sequence = [
        ("origin", itinerary["origin_anchor_id"]),
        *[("waypoint", value) for value in itinerary["waypoint_anchor_ids"]],
        ("destination", itinerary["destination_anchor_id"]),
    ]
    frames: list[gpd.GeoDataFrame] = []
    for sequence, (role, anchor_id) in enumerate(anchor_sequence):
        resolved = resolve_anchor(
            anchor_id,
            config["anchors"][anchor_id],
            source_frames,
            config["metric_crs"],
            anchor_specs=config["anchors"],
        )
        resolved["anchor_sequence"] = sequence
        resolved["anchor_role"] = role
        frames.append(resolved)
    return gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs=config["metric_crs"]
    )

def _validation_points_for_official_pks(
    itinerary: Mapping[str, Any],
    config: Mapping[str, Any],
    source_frames: Mapping[str, gpd.GeoDataFrame],
    route: LineString,
) -> gpd.GeoDataFrame:
    anchor_ids = [itinerary["origin_anchor_id"], itinerary["destination_anchor_id"]]
    anchor_specs = [config["anchors"][anchor_id] for anchor_id in anchor_ids]
    if not all(spec["type"] == "official_pk" for spec in anchor_specs):
        return gpd.GeoDataFrame(
            columns=["via_nombre", "pk_numero", "geometry"],
            geometry="geometry",
            crs=config["metric_crs"],
        )
    if (
        anchor_specs[0]["source_id"] != anchor_specs[1]["source_id"]
        or anchor_specs[0]["road_name"] != anchor_specs[1]["road_name"]
    ):
        return gpd.GeoDataFrame(
            columns=["via_nombre", "pk_numero", "geometry"],
            geometry="geometry",
            crs=config["metric_crs"],
        )

    source_id = anchor_specs[0]["source_id"]
    road_name = anchor_specs[0]["road_name"]
    pk_min, pk_max = sorted([anchor_specs[0]["pk"], anchor_specs[1]["pk"]])
    points = source_frames[source_id]
    increasing_pk = anchor_specs[1]["pk"] > anchor_specs[0]["pk"]
    selected = points[
        points["via_nombre"].eq(road_name)
        & points["pk_numero"].between(pk_min, pk_max, inclusive="both")
    ].copy()
    selected = selected.sort_values("pk_numero", ascending=increasing_pk).to_crs(
        config["metric_crs"]
    )
    selected["route_measure_m"] = selected.geometry.map(route.project)
    selected["route_offset_m"] = selected.geometry.map(
        lambda point: point.distance(route.interpolate(route.project(point)))
    )
    return selected

def _extract_existing_geometry(
    itinerary: Mapping[str, Any],
    config: Mapping[str, Any],
    source_frames: Mapping[str, gpd.GeoDataFrame],
) -> tuple[LineString, gpd.GeoDataFrame, float]:
    from movilidad_teide.cartografia.fuentes_rutas import select_exact_records
    source_id = itinerary["geometry_source_id"]
    filters = itinerary.get("geometry_feature_filters", {})
    if filters:
        selected = select_exact_records(
            source_frames[source_id], filters, require_unique=True
        )
    else:
        selected = source_frames[source_id]
        if len(selected) != 1:
            raise ItineraryExtractionError(
                f"La fuente de geometría contiene {len(selected)} elementos; configure filtros exactos."
            )
    selected = selected.to_crs(config["metric_crs"])
    geometry = selected.geometry.iloc[0]
    if isinstance(geometry, LineString):
        parts = [geometry]
    elif isinstance(geometry, MultiLineString):
        parts = list(geometry.geoms)
    else:
        raise ItineraryExtractionError(
            f"La geometría existente es {geometry.geom_type}; se esperaba una línea."
        )
    line = combine_ordered_parts(
        parts, config["parameters"]["continuity_tolerance_m"]
    )
    rows = []
    for sequence, part in enumerate(parts, start=1):
        rows.append(
            {
                "sequence": sequence,
                "source_id": source_id,
                "source_feature_index": selected.iloc[0]["source_feature_index"],
                "component_id": None,
                "component_index": sequence - 1,
                "component_geometry_sha256": sha256(part.wkb).hexdigest(),
                "feature_filters_json": json.dumps(
                    filters,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "reverse_applied": False,
                "gap_from_previous_m": 0.0,
                "source_length_m": float(part.length),
                "geometry": part,
            }
        )
    lineage = gpd.GeoDataFrame(rows, geometry="geometry", crs=config["metric_crs"])
    return line, lineage, 0.0



def extract_configured_itinerary(
    itinerary_id: str,
    config: Mapping[str, Any],
    project_root: str | Path,
    *,
    config_sha256: str,
    source_inventory: pd.DataFrame | None = None,
    source_frames: dict[str, gpd.GeoDataFrame] | None = None,
    component_frames: dict[str, gpd.GeoDataFrame] | None = None,
) -> ItineraryExtractionResult:
    """Extract one configured itinerary without choosing a route automatically."""
    from movilidad_teide.cartografia.catalogo_rutas import _anchor_dependency_closure
    from movilidad_teide.cartografia.auditoria_rutas import audit_osm_grade_separated_crossings
    from movilidad_teide.cartografia.auditoria_rutas import audit_service_trace_geometry
    from movilidad_teide.cartografia.fuentes_rutas import build_source_inventory
    from movilidad_teide.cartografia.fuentes_rutas import explode_line_components
    from movilidad_teide.cartografia.fuentes_rutas import read_geospatial_source
    from movilidad_teide.cartografia.catalogo_rutas import validate_itinerary_config
    from movilidad_teide.cartografia.fuentes_rutas import verify_source_inventory

    validate_itinerary_config(config)
    if itinerary_id not in config["itineraries"]:
        raise ItineraryConfigError(f"Itinerario inexistente: {itinerary_id!r}.")
    inventory = (
        build_source_inventory(config, project_root)
        if source_inventory is None
        else source_inventory.copy()
    )
    verify_source_inventory(inventory)
    sources = {} if source_frames is None else source_frames
    components = {} if component_frames is None else component_frames

    def get_source(source_id: str) -> gpd.GeoDataFrame:
        if source_id not in sources:
            sources[source_id] = read_geospatial_source(source_id, config, project_root)
        return sources[source_id]

    itinerary = config["itineraries"][itinerary_id]
    # También cargar los anclajes usados para recortar componentes antes de unirlos.
    required_anchor_ids = {itinerary["origin_anchor_id"], *itinerary["waypoint_anchor_ids"], itinerary["destination_anchor_id"]}
    for part in itinerary.get("axis_parts", []):
        required_anchor_ids.update(part[field] for field in ("clip_start_anchor_id", "clip_end_anchor_id") if field in part)
    required_anchor_ids = _anchor_dependency_closure(required_anchor_ids, config["anchors"])
    required_source_ids = {
        config["anchors"][anchor_id].get("source_id")
        for anchor_id in required_anchor_ids
        if config["anchors"][anchor_id].get("source_id") is not None
    }
    for source_id in required_source_ids:
        get_source(source_id)

    if itinerary["definition_mode"] == "official_axis_sequence":
        clip_anchors = {key: resolve_anchor(key, config["anchors"][key], sources, config["metric_crs"],
                                           anchor_specs=config["anchors"]).geometry.iloc[0]
                        for key in required_anchor_ids}
        for part_spec in itinerary["axis_parts"]:
            source_id = part_spec["source_id"]
            if source_id not in components:
                source_hash = inventory.loc[
                    inventory["source_id"].eq(source_id), "actual_sha256"
                ].item()
                components[source_id] = explode_line_components(
                    get_source(source_id), source_id, source_hash
                )
        axis, lineage, maximum_gap_m = select_ordered_axis_parts(
            components,
            itinerary["axis_parts"],
            config["metric_crs"],
            config["parameters"]["continuity_tolerance_m"],
            config["parameters"]["length_tolerance_m"],
            clip_anchors=clip_anchors,
            anchor_axis_tolerance_m=config["parameters"]["anchor_axis_tolerance_m"],
        )
    else:
        get_source(itinerary["geometry_source_id"])
        axis, lineage, maximum_gap_m = _extract_existing_geometry(
            itinerary, config, sources
        )

    anchors = _resolve_configured_anchors(itinerary, config, sources)
    clipped, anchors, route_reversed, clipping_error_m = orient_clip_and_validate_anchors(
        axis,
        anchors,
        config["parameters"]["anchor_axis_tolerance_m"],
        config["parameters"]["length_tolerance_m"],
    )
    anchors.insert(0, "itinerary_id", itinerary_id)
    lineage.insert(0, "itinerary_id", itinerary_id)

    validation_points = _validation_points_for_official_pks(
        itinerary, config, sources, clipped
    )
    if not validation_points.empty:
        validation_points.insert(0, "itinerary_id", itinerary_id)

    length_source_m = float(lineage["source_length_m"].sum())
    combined_length_error_m = float(axis.length - length_source_m)
    pk_offsets_valid = (
        True
        if validation_points.empty
        else bool(
            (
                validation_points["route_offset_m"]
                <= config["parameters"]["anchor_axis_tolerance_m"]
            ).all()
        )
    )
    pk_order_valid = (
        True
        if len(validation_points) < 2
        else bool((validation_points["route_measure_m"].diff().dropna() > 0).all())
    )
    trace_audit = itinerary.get("source_trace_audit")
    trace_ok, trace_observed = (False, None) if trace_audit is None else audit_service_trace_geometry(
        clipped, lineage, trace_audit, config["parameters"]["length_tolerance_m"])
    grade_audit = itinerary.get("osm_grade_separation_audit")
    grade_ok, grade_observed = (False, None) if grade_audit is None else audit_osm_grade_separated_crossings(
        clipped, lineage, itinerary, config, project_root, config["parameters"]["length_tolerance_m"])
    validations = pd.DataFrame(
        [
            {
                "check_id": "source_hashes",
                "passed": True,
                "observed": "Todas las huellas coinciden",
                "limit": None,
                "detail": "Fuentes originales verificadas antes de extraer.",
            },
            {
                "check_id": "component_continuity",
                "passed": maximum_gap_m <= config["parameters"]["continuity_tolerance_m"],
                "observed": maximum_gap_m,
                "limit": config["parameters"]["continuity_tolerance_m"],
                "detail": "Máxima separación entre componentes consecutivos [m].",
            },
            {
                "check_id": "component_length_conservation",
                "passed": abs(combined_length_error_m)
                <= config["parameters"]["length_tolerance_m"],
                "observed": combined_length_error_m,
                "limit": config["parameters"]["length_tolerance_m"],
                "detail": "Longitud combinada menos suma de componentes [m].",
            },
            {
                "check_id": "anchor_axis_distance",
                "passed": bool(
                    (
                        anchors["axis_offset_m"]
                        <= config["parameters"]["anchor_axis_tolerance_m"]
                    ).all()
                ),
                "observed": float(anchors["axis_offset_m"].max()),
                "limit": config["parameters"]["anchor_axis_tolerance_m"],
                "detail": "Máxima distancia de los anclajes al eje [m].",
            },
            {
                "check_id": "anchor_order",
                "passed": bool(
                    (anchors["itinerary_measure_m"].diff().dropna() > 0).all()
                ),
                "observed": "Orden estricto",
                "limit": "origen < intermedios < destino",
                "detail": "Orden tras orientar el eje.",
            },
            {
                "check_id": "clip_length_conservation",
                "passed": abs(clipping_error_m)
                <= config["parameters"]["length_tolerance_m"],
                "observed": clipping_error_m,
                "limit": config["parameters"]["length_tolerance_m"],
                "detail": "Longitud recortada menos diferencia de medidas [m].",
            },
            {
                "check_id": "route_geometry",
                "passed": bool(clipped.is_valid and (clipped.is_simple or trace_ok or grade_ok) and not clipped.is_empty),
                "observed": f"valid={clipped.is_valid}; simple={clipped.is_simple}",
                "limit": ("Cruces OSM a distinto nivel con geometría, fuentes, niveles y nodos auditados" if grade_audit is not None
                          else "LineString válida y no vacía; simple o traza de servicio con huella y autocruces auditados"),
                "detail": "Control geométrico del trazado derivado.",
            },
            {
                "check_id": "official_pk_axis_distance",
                "passed": pk_offsets_valid,
                "observed": (
                    None
                    if validation_points.empty
                    else float(validation_points["route_offset_m"].max())
                ),
                "limit": config["parameters"]["anchor_axis_tolerance_m"],
                "detail": "PK oficiales comprendidos entre los anclajes.",
            },
            {
                "check_id": "official_pk_order",
                "passed": pk_order_valid,
                "observed": (
                    None
                    if validation_points.empty
                    else f"{len(validation_points)} PK en orden creciente"
                ),
                "limit": "Medidas estrictamente crecientes",
                "detail": "Control adicional cuando ambos extremos son PK de la misma vía.",
            },
        ]
    )
    if trace_audit is not None:
        validations.loc[len(validations)] = {"check_id": "source_trace_geometry_audit", "passed": trace_ok,
            "observed": json.dumps(trace_observed, ensure_ascii=False, sort_keys=True),
            "limit": "Huella exacta y todos los autocruces puntuales documentados; sin solapamientos lineales",
            "detail": "La traza se conserva sin simplificar; no valida rasante ni circulación futura."}
    if grade_audit is not None:
        validations.loc[len(validations)] = {"check_id":"osm_grade_separation_audit","passed":grade_ok,
            "observed":json.dumps(grade_observed,ensure_ascii=False,sort_keys=True),
            "limit":"Todos los cruces declarados y contrastados con los originales, sin conexiones añadidas",
            "detail":"Auditoría cartográfica; no confirma circulación, rasante o altura del puente."}
    for column in ("observed", "limit"):
        validations[column] = validations[column].map(
            lambda value: None if value is None else str(value)
        )
    validations.insert(0, "itinerary_id", itinerary_id)
    if not validations["passed"].all():
        failed = validations.loc[~validations["passed"], "check_id"].tolist()
        raise ItineraryExtractionError(
            f"El itinerario {itinerary_id} no supera las validaciones: {failed}."
        )

    route = gpd.GeoDataFrame(
        {
            "itinerary_id": [itinerary_id],
            "name": [itinerary["name"]],
            "purpose": [itinerary["purpose"]],
            "validation_status": [itinerary["validation_status"]],
            "operational_route": [itinerary["operational_route"]],
            "definition_mode": [itinerary["definition_mode"]],
            "direction_forward": [itinerary["direction_labels"]["forward"]],
            "direction_reverse": [itinerary["direction_labels"]["reverse"]],
            "metric_crs": [CRS.from_user_input(config["metric_crs"]).to_string()],
            "length_m": [float(clipped.length)],
            "route_reversed_during_extraction": [route_reversed],
            "config_sha256": [config_sha256],
            "geometry": [clipped],
        },
        geometry="geometry",
        crs=config["metric_crs"],
    )
    route_checks = route_validation_table(route[["itinerary_id", "geometry"]])
    if not route_checks.loc[
        route_checks["check"].ne("Línea simple (sin autocruces)"), "passed"
    ].all():
        raise ItineraryExtractionError("Falló la validación general de la ruta.")

    operations = pd.DataFrame(
        [
            {
                "sequence": 1,
                "operation": "verify_sources",
                "parameters_json": json.dumps(
                    {"config_sha256": config_sha256}, sort_keys=True
                ),
                "result": "ok",
            },
            {
                "sequence": 2,
                "operation": "select_and_order_axis_parts",
                "parameters_json": json.dumps(
                    itinerary.get("axis_parts", []), ensure_ascii=False, sort_keys=True
                ),
                "result": f"{len(lineage)} componentes; {axis.length:.6f} m",
            },
            {
                "sequence": 3,
                "operation": "resolve_anchors",
                "parameters_json": json.dumps(
                    anchors["anchor_id"].tolist(), ensure_ascii=False
                ),
                "result": f"{len(anchors)} anclajes",
            },
            {
                "sequence": 4,
                "operation": "orient_and_clip",
                "parameters_json": json.dumps(
                    {
                        "route_reversed": route_reversed,
                        "anchor_tolerance_m": config["parameters"][
                            "anchor_axis_tolerance_m"
                        ],
                    },
                    sort_keys=True,
                ),
                "result": f"{clipped.length:.6f} m",
            },
            {
                "sequence": 5,
                "operation": "validate",
                "parameters_json": json.dumps(
                    config["parameters"], sort_keys=True
                ),
                "result": f"{len(validations)} controles superados",
            },
        ]
    )
    operations.insert(0, "itinerary_id", itinerary_id)
    inventory.insert(0, "itinerary_id", itinerary_id)
    return ItineraryExtractionResult(
        route=route,
        anchors=anchors,
        lineage=lineage,
        validation_points=validation_points,
        validations=validations,
        operations=operations,
        sources=inventory,
    )

def extract_configured_itineraries(
    config_path: str | Path,
    project_root: str | Path,
    itinerary_ids: Sequence[str] | None = None,
) -> dict[str, ItineraryExtractionResult]:
    """Extract several configured itineraries while caching shared official data."""
    from movilidad_teide.cartografia.fuentes_rutas import build_source_inventory
    from movilidad_teide.cartografia.catalogo_rutas import load_itinerary_config
    from movilidad_teide.cartografia.fuentes_rutas import verify_source_inventory

    config_file = Path(config_path)
    config = load_itinerary_config(config_file)
    config_digest = file_sha256(config_file)
    inventory = build_source_inventory(config, project_root)
    verify_source_inventory(inventory)
    selected_ids = list(config["itineraries"]) if itinerary_ids is None else list(itinerary_ids)
    unknown = [value for value in selected_ids if value not in config["itineraries"]]
    if unknown:
        raise ItineraryConfigError(f"Itinerarios inexistentes: {unknown}.")

    source_frames: dict[str, gpd.GeoDataFrame] = {}
    component_frames: dict[str, gpd.GeoDataFrame] = {}
    results: dict[str, ItineraryExtractionResult] = {}
    for itinerary_id in selected_ids:
        results[itinerary_id] = extract_configured_itinerary(
            itinerary_id,
            config,
            project_root,
            config_sha256=config_digest,
            source_inventory=inventory,
            source_frames=source_frames,
            component_frames=component_frames,
        )
    return results
