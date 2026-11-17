"""cartografia: geometrias. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from collections.abc import Iterable, Sequence
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry import LineString, MultiLineString, Point, box
from movilidad_teide.cartografia.geografia_tipos import GeographicDataError
from movilidad_teide.cartografia.geografia_tipos import DEFAULT_METRIC_CRS


def _read_route_layer(path: Path) -> gpd.GeoDataFrame:
    """Read a GeoJSON or the first suitable line layer of a GPX file."""

    if path.suffix.lower() != ".gpx":
        return gpd.read_file(path)

    layers = gpd.list_layers(path)
    layer_names = layers["name"].tolist()
    for preferred in ("tracks", "routes"):
        if preferred in layer_names:
            frame = gpd.read_file(path, layer=preferred)
            if not frame.empty:
                return frame
    raise GeographicDataError(
        f"El GPX {path} no contiene una capa no vacía 'tracks' o 'routes'."
    )

def _iter_line_parts(geometry: LineString | MultiLineString) -> Iterable[LineString]:
    if isinstance(geometry, LineString):
        yield geometry
    elif isinstance(geometry, MultiLineString):
        yield from geometry.geoms
    else:
        raise GeographicDataError(
            "El trazado solo puede contener geometrías LineString o MultiLineString."
        )

def _combine_ordered_parts(
    geometries: Iterable[LineString | MultiLineString],
    continuity_tolerance_m: float,
) -> LineString:
    """Combine ordered line parts without guessing their order or direction."""

    if continuity_tolerance_m < 0:
        raise ValueError("continuity_tolerance_m debe ser mayor o igual que cero.")

    parts = [part for geometry in geometries for part in _iter_line_parts(geometry)]
    if not parts:
        raise GeographicDataError("El archivo no contiene ninguna línea utilizable.")

    coordinates: list[tuple[float, float]] = []
    previous_end: np.ndarray | None = None
    for index, part in enumerate(parts):
        if part.is_empty or len(part.coords) < 2:
            raise GeographicDataError(f"La parte {index} del trazado está vacía.")
        part_coordinates = [(float(x), float(y)) for x, y, *_ in part.coords]
        current_start = np.asarray(part_coordinates[0], dtype=float)
        if previous_end is not None:
            gap_m = float(np.linalg.norm(current_start - previous_end))
            if gap_m > continuity_tolerance_m:
                raise GeographicDataError(
                    "El trazado no es continuo o sus partes no están en el orden/sentido "
                    f"de circulación: salto de {gap_m:.3f} m antes de la parte {index}."
                )
            if gap_m <= np.finfo(float).eps:
                part_coordinates = part_coordinates[1:]
        coordinates.extend(part_coordinates)
        previous_end = np.asarray(part_coordinates[-1], dtype=float)

    line = LineString(coordinates)
    if line.is_empty or line.length <= 0 or not line.is_valid:
        raise GeographicDataError("La línea combinada está vacía, no es válida o no tiene longitud.")
    return line

def combine_ordered_parts(
    geometries: Iterable[LineString | MultiLineString],
    continuity_tolerance_m: float,
) -> LineString:
    """Combine explicitly ordered line parts after checking endpoint continuity."""

    return _combine_ordered_parts(geometries, continuity_tolerance_m)

def ensure_metric_crs(crs: str | CRS) -> CRS:
    """Validate that a CRS is projected and uses metres on both axes."""

    parsed = CRS.from_user_input(crs)
    axis_units = {axis.unit_name.lower() for axis in parsed.axis_info if axis.unit_name}
    if not parsed.is_projected or axis_units != {"metre"}:
        raise GeographicDataError(
            f"El CRS de cálculo debe ser proyectado y métrico; se recibió {parsed.to_string()}."
        )
    return parsed


def load_route(
    path: str | Path,
    target_crs: str | CRS = DEFAULT_METRIC_CRS,
    continuity_tolerance_m: float = 1.0,
) -> gpd.GeoDataFrame:
    """Load, project and strictly combine an ordered road route.

    The function never infers a missing CRS and never joins disconnected parts.
    The first coordinate remains the origin of travel, so source direction must be
    checked by the analyst.
    """

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Falta el trazado de la carretera: {source}")

    metric_crs = ensure_metric_crs(target_crs)
    frame = _read_route_layer(source)
    if frame.empty:
        raise GeographicDataError(f"El trazado {source} no contiene elementos.")
    if frame.crs is None:
        raise GeographicDataError(
            f"El trazado {source} no declara CRS; debe corregirse en el archivo de origen."
        )
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise GeographicDataError("El trazado contiene geometrías ausentes o vacías.")
    if not frame.geometry.is_valid.all():
        raise GeographicDataError("El trazado contiene geometrías no válidas.")

    source_crs = frame.crs.to_string()
    projected = frame.to_crs(metric_crs)
    line = _combine_ordered_parts(projected.geometry, continuity_tolerance_m)
    route = gpd.GeoDataFrame(
        {"route_id": [source.stem], "geometry": [line]}, crs=metric_crs
    )
    route.attrs["source_crs"] = source_crs
    route.attrs["source_feature_count"] = len(frame)
    return route

def route_validation_table(route: gpd.GeoDataFrame) -> pd.DataFrame:
    """Return explicit geometry and CRS checks for a one-feature route."""

    if len(route) != 1 or route.crs is None:
        raise GeographicDataError("La ruta debe contener una geometría y un CRS declarado.")
    ensure_metric_crs(route.crs)
    line = route.geometry.iloc[0]
    if not isinstance(line, LineString):
        raise GeographicDataError("La ruta proyectada debe ser una LineString.")
    checks = [
        ("CRS proyectado y métrico", True, route.crs.to_string()),
        ("Geometría no vacía", not line.is_empty, None),
        ("Geometría válida", line.is_valid, None),
        ("Longitud positiva", line.length > 0, f"{line.length:.3f} m"),
        (
            "Línea simple (sin autocruces)",
            line.is_simple,
            "Revisar visualmente si no se cumple; no implica por sí solo un error vial.",
        ),
    ]
    return pd.DataFrame(checks, columns=["check", "passed", "detail"])
