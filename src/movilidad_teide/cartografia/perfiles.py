"""cartografia: perfiles. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry import LineString, MultiLineString, Point, box
from shapely.ops import substring
from movilidad_teide.cartografia.geografia_tipos import GeographicDataError
from movilidad_teide.cartografia.geografia_tipos import SEGMENT_COLUMNS
from movilidad_teide.cartografia.geografia_tipos import DEFAULT_SLOPE_CLASSES


def make_sampling_distances(
    total_length_m: float, interval_m: float, *, station_offset_m: float = 0.0
) -> np.ndarray:
    """Keep exact endpoints and interior stations offset + k * interval.

    Phase zero retains the historical station rule. A positive phase introduces
    short boundary segments, not an offset of the route geometry.
    """

    if not np.isfinite(total_length_m) or total_length_m <= 0:
        raise ValueError("total_length_m debe ser finita y positiva.")
    if not np.isfinite(interval_m) or interval_m <= 0:
        raise ValueError("interval_m debe ser finito y positivo.")
    if not np.isfinite(station_offset_m) or not 0 <= station_offset_m < interval_m:
        raise ValueError("station_offset_m debe cumplir 0 <= fase < intervalo.")
    if station_offset_m > 0:
        interior = np.arange(station_offset_m, total_length_m, interval_m, dtype=float)
        return np.r_[0.0, interior, total_length_m]
    distances = np.arange(0.0, total_length_m, interval_m, dtype=float)
    if distances.size == 0 or not np.isclose(distances[-1], total_length_m):
        distances = np.append(distances, total_length_m)
    else:
        distances[-1] = total_length_m
    return distances


def sample_elevation_profile(
    route: gpd.GeoDataFrame,
    dem_path: str | Path,
    interval_m: float = 200.0,
    *,
    assumed_raster_crs: str | CRS | None = None,
    method: str = "cell",
    station_offset_m: float = 0.0,
) -> gpd.GeoDataFrame:
    """Sample elevations from a DEM along a metric route.

    If ``assumed_raster_crs`` is supplied, raster coordinates are interpreted in
    that CRS without changing the original file. This explicit escape hatch is
    intended for documented metadata discrepancies, not silent CRS correction.
    """
    from movilidad_teide.cartografia.geometrias import ensure_metric_crs
    from movilidad_teide.cartografia.terreno import sample_dem_points
    from movilidad_teide.cartografia.terreno import validate_dem_coverage

    if len(route) != 1 or route.crs is None:
        raise GeographicDataError("La ruta debe contener una geometría y un CRS declarado.")
    ensure_metric_crs(route.crs)
    validate_dem_coverage(
        route,
        dem_path,
        assumed_raster_crs=assumed_raster_crs,
    )

    line = route.geometry.iloc[0]
    distances = make_sampling_distances(float(line.length), interval_m, station_offset_m=station_offset_m)
    profile = gpd.GeoDataFrame(
        {
            "sample_id": np.arange(len(distances), dtype=int),
            "distance_m": distances,
            "geometry": [line.interpolate(distance) for distance in distances],
        },
        crs=route.crs,
    )

    profile = sample_dem_points(profile, dem_path, method=method, assumed_raster_crs=assumed_raster_crs)
    profile["station_offset_m"] = station_offset_m
    return profile

def reverse_profile(profile: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reverse a sampled profile and restart accumulated distance at zero."""

    required = {"sample_id", "distance_m", "elevation_m", "geometry"}
    missing = required.difference(profile.columns)
    if missing:
        raise KeyError(f"Faltan columnas del perfil: {sorted(missing)}")
    if profile.empty or profile.crs is None:
        raise GeographicDataError("El perfil debe contener muestras y un CRS declarado.")
    distances = profile["distance_m"].to_numpy(dtype=float)
    if not np.isfinite(distances).all() or np.any(np.diff(distances) <= 0):
        raise GeographicDataError("Las distancias del perfil deben ser finitas y crecientes.")

    reversed_profile = profile.iloc[::-1].copy().reset_index(drop=True)
    reversed_profile["sample_id"] = np.arange(len(reversed_profile), dtype=int)
    reversed_profile["distance_m"] = float(distances[-1]) - distances[::-1]
    return reversed_profile


def calculate_segments(profile: pd.DataFrame) -> pd.DataFrame:
    """Calculate longitudinal slopes between consecutive profile samples."""

    required = {"distance_m", "elevation_m"}
    missing = required.difference(profile.columns)
    if missing:
        raise KeyError(f"Faltan columnas del perfil: {sorted(missing)}")
    if len(profile) < 2:
        raise GeographicDataError("Se necesitan al menos dos puntos para calcular tramos.")

    distances = profile["distance_m"].to_numpy(dtype=float)
    elevations = profile["elevation_m"].to_numpy(dtype=float)
    if not np.isfinite(distances).all() or not np.isfinite(elevations).all():
        raise GeographicDataError("Distancias y elevaciones deben ser finitas.")
    lengths = np.diff(distances)
    if np.any(lengths <= 0):
        raise GeographicDataError("Las distancias del perfil deben ser estrictamente crecientes.")
    elevation_changes = np.diff(elevations)
    slopes = 100.0 * elevation_changes / lengths
    return pd.DataFrame(
        {
            "segment_id": np.arange(1, len(profile), dtype=int),
            "distance_start_m": distances[:-1],
            "distance_end_m": distances[1:],
            "length_m": lengths,
            "elevation_start_m": elevations[:-1],
            "elevation_end_m": elevations[1:],
            "elevation_change_m": elevation_changes,
            "slope_pct": slopes,
        },
        columns=SEGMENT_COLUMNS,
    )

def reverse_segments(segments: pd.DataFrame) -> pd.DataFrame:
    """Reverse segment order and slope sign for the opposite travel direction."""

    missing = set(SEGMENT_COLUMNS).difference(segments.columns)
    if missing:
        raise KeyError(f"Faltan columnas de tramos: {sorted(missing)}")
    reversed_source = segments.iloc[::-1].reset_index(drop=True)
    lengths = reversed_source["length_m"].to_numpy(dtype=float)
    distance_ends = np.cumsum(lengths)
    distance_starts = np.concatenate(([0.0], distance_ends[:-1]))
    return pd.DataFrame(
        {
            "segment_id": np.arange(1, len(reversed_source) + 1, dtype=int),
            "distance_start_m": distance_starts,
            "distance_end_m": distance_ends,
            "length_m": lengths,
            "elevation_start_m": reversed_source["elevation_end_m"].to_numpy(float),
            "elevation_end_m": reversed_source["elevation_start_m"].to_numpy(float),
            "elevation_change_m": -reversed_source["elevation_change_m"].to_numpy(float),
            "slope_pct": -reversed_source["slope_pct"].to_numpy(float),
        },
        columns=SEGMENT_COLUMNS,
    )

def _validated_classes(classes: Sequence[float]) -> np.ndarray:
    values = np.asarray(classes, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("Las clases de pendiente deben ser una secuencia finita de al menos dos valores.")
    if np.any(np.diff(values) <= 0):
        raise ValueError("Las clases de pendiente deben estar estrictamente ordenadas.")
    return values


def classify_slopes(
    segments: pd.DataFrame,
    classes: Sequence[float] = DEFAULT_SLOPE_CLASSES,
) -> pd.DataFrame:
    """Assign the nearest configured slope class within the admitted range.

    Slopes outside the minimum and maximum configured classes are left unclassified
    and marked for methodological treatment; they are never clipped.
    """

    if "slope_pct" not in segments or "length_m" not in segments:
        raise KeyError("Se requieren las columnas 'slope_pct' y 'length_m'.")
    class_values = _validated_classes(classes)
    result = segments.copy()
    slopes = result["slope_pct"].to_numpy(dtype=float)
    if not np.isfinite(slopes).all():
        raise GeographicDataError("Las pendientes deben ser finitas para clasificarlas.")

    within = (slopes >= class_values[0]) & (slopes <= class_values[-1])
    nearest_indices = np.abs(slopes[:, None] - class_values[None, :]).argmin(axis=1)
    assigned = np.full(len(slopes), np.nan, dtype=float)
    assigned[within] = class_values[nearest_indices[within]]
    status = np.full(len(slopes), "classified", dtype=object)
    status[slopes < class_values[0]] = "below_minimum"
    status[slopes > class_values[-1]] = "above_maximum"

    result["slope_class_pct"] = pd.array(assigned, dtype="Float64")
    result["classification_status"] = status
    result["requires_methodological_treatment"] = ~within
    return result

def slope_distribution(
    classified_segments: pd.DataFrame,
    direction: str,
    classes: Sequence[float] = DEFAULT_SLOPE_CLASSES,
) -> pd.DataFrame:
    """Aggregate segment length by slope class and out-of-range status."""

    required = {"length_m", "slope_class_pct", "classification_status"}
    missing = required.difference(classified_segments.columns)
    if missing:
        raise KeyError(f"Faltan columnas clasificadas: {sorted(missing)}")
    class_values = _validated_classes(classes)
    rows: list[dict[str, Any]] = []
    for slope_class in class_values:
        selected = classified_segments[
            (classified_segments["classification_status"] == "classified")
            & (classified_segments["slope_class_pct"] == slope_class)
        ]
        rows.append(
            {
                "direction": direction,
                "classification_status": "classified",
                "slope_class_pct": slope_class,
                "length_m": float(selected["length_m"].sum()),
                "segment_count": int(len(selected)),
            }
        )
    for status in ("below_minimum", "above_maximum"):
        selected = classified_segments[
            classified_segments["classification_status"] == status
        ]
        rows.append(
            {
                "direction": direction,
                "classification_status": status,
                "slope_class_pct": pd.NA,
                "length_m": float(selected["length_m"].sum()),
                "segment_count": int(len(selected)),
            }
        )
    distribution = pd.DataFrame(rows)
    distribution["slope_class_pct"] = distribution["slope_class_pct"].astype("Float64")
    distribution["length_km"] = distribution["length_m"] / 1_000.0
    return distribution

def route_summary(profile: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    """Summarize distance, endpoint elevations and accumulated elevation changes."""

    if profile.empty or segments.empty:
        raise GeographicDataError("El perfil y los tramos no pueden estar vacíos.")
    changes = segments["elevation_change_m"].to_numpy(dtype=float)
    initial_elevation = float(profile["elevation_m"].iloc[0])
    final_elevation = float(profile["elevation_m"].iloc[-1])
    values = {
        "total_distance_km": float(segments["length_m"].sum()) / 1_000.0,
        "initial_elevation_m": initial_elevation,
        "final_elevation_m": final_elevation,
        "net_elevation_change_m": final_elevation - initial_elevation,
        "cumulative_ascent_m": float(changes[changes > 0].sum()),
        "cumulative_descent_m": float(-changes[changes < 0].sum()),
        "minimum_slope_pct": float(segments["slope_pct"].min()),
        "maximum_slope_pct": float(segments["slope_pct"].max()),
        "sample_count": int(len(profile)),
        "segment_count": int(len(segments)),
    }
    return pd.DataFrame([values])

def validate_length_conservation(
    route_length_m: float,
    segments: pd.DataFrame,
    absolute_tolerance_m: float = 1e-6,
) -> float:
    """Return length error and raise if segment and route lengths do not agree."""

    if absolute_tolerance_m < 0:
        raise ValueError("absolute_tolerance_m no puede ser negativa.")
    segment_length_m = float(segments["length_m"].sum())
    error_m = segment_length_m - float(route_length_m)
    if not np.isclose(segment_length_m, route_length_m, rtol=0.0, atol=absolute_tolerance_m):
        raise GeographicDataError(
            f"Los tramos suman {segment_length_m:.9f} m y la ruta {route_length_m:.9f} m "
            f"(diferencia {error_m:.9f} m)."
        )
    return error_m

def profile_quality_table(
    profile: pd.DataFrame,
    segments: pd.DataFrame,
    anomalous_absolute_slope_pct: float,
) -> pd.DataFrame:
    """Report missing values, station order and a configurable slope alert."""

    if anomalous_absolute_slope_pct <= 0:
        raise ValueError("anomalous_absolute_slope_pct debe ser positiva.")
    distances = profile["distance_m"].to_numpy(dtype=float)
    anomalous = segments["slope_pct"].abs() > anomalous_absolute_slope_pct
    checks = [
        ("Elevaciones ausentes", int(profile["elevation_m"].isna().sum()), 0),
        ("Distancias no crecientes", int(np.sum(np.diff(distances) <= 0)), 0),
        (
            f"Tramos con |pendiente| > {anomalous_absolute_slope_pct:g} %",
            int(anomalous.sum()),
            0,
        ),
    ]
    result = pd.DataFrame(checks, columns=["check", "observed_count", "expected_count"])
    result["passed"] = result["observed_count"] == result["expected_count"]
    return result

def extreme_slope_table(
    segments: pd.DataFrame,
    top_n: int = 10,
    anomalous_absolute_slope_pct: float = 20.0,
) -> pd.DataFrame:
    """Return the steepest sampled segments and flag a configurable alert threshold."""

    required = set(SEGMENT_COLUMNS)
    missing = required.difference(segments.columns)
    if missing:
        raise KeyError(f"Faltan columnas de tramos: {sorted(missing)}")
    if top_n <= 0:
        raise ValueError("top_n debe ser positivo.")
    if anomalous_absolute_slope_pct <= 0:
        raise ValueError("anomalous_absolute_slope_pct debe ser positiva.")

    result = segments.copy()
    result["absolute_slope_pct"] = result["slope_pct"].abs()
    result = result.sort_values(
        ["absolute_slope_pct", "segment_id"], ascending=[False, True]
    ).head(top_n)
    result["review_rank"] = np.arange(1, len(result) + 1, dtype=int)
    result["exceeds_alert_threshold"] = (
        result["absolute_slope_pct"] > anomalous_absolute_slope_pct
    )
    result["review_status"] = np.where(
        result["exceeds_alert_threshold"],
        "possible_anomaly",
        "extreme_for_visual_review",
    )
    return result[
        [
            "review_rank",
            *SEGMENT_COLUMNS,
            "absolute_slope_pct",
            "exceeds_alert_threshold",
            "review_status",
        ]
    ].reset_index(drop=True)

def descriptive_slope_distribution(
    segments: pd.DataFrame,
    absolute_edges_pct: Sequence[float],
) -> pd.DataFrame:
    """Distance-weighted descriptive bins, symmetric in sign; never COPERT classes.

    Magnitudes use (a,b], with an explicit zero bin and an unbounded tail.
    Thus exactly +6 and -6 are NOT counted in the tails beyond +/-6.
    """

    edges = _validated_classes(absolute_edges_pct)
    if edges[0] != 0:
        raise ValueError("Los límites absolutos deben empezar en cero.")
    slopes = segments["slope_pct"].to_numpy(float)
    lengths = segments["length_m"].to_numpy(float)
    if not len(slopes) or not np.isfinite(slopes).all():
        raise GeographicDataError("Las pendientes deben ser finitas y no estar vacías.")
    if not np.isfinite(lengths).all() or np.any(lengths <= 0):
        raise GeographicDataError("Las longitudes deben ser finitas y positivas.")
    rows = []
    bounds = [*zip(edges[:-1], edges[1:]), (edges[-1], np.inf)]
    for sign in (-1, 0, 1):
        if sign == 0:
            intervals = [(0.0, 0.0)]
        else:
            intervals = bounds[::-1] if sign < 0 else bounds
        for low, high in intervals:
            if sign == 0:
                mask = slopes == 0
                label = "0"
            else:
                mask = (np.sign(slopes) == sign) & (np.abs(slopes) > low) & (np.abs(slopes) <= high)
                if sign > 0:
                    label = f"({low:g}, {high:g}]" if np.isfinite(high) else f"> {low:g}"
                else:
                    label = f"[{-high:g}, {-low:g})" if np.isfinite(high) else f"< {-low:g}"
            rows.append({
                "bin_order": len(rows), "slope_interval_pct": label,
                "sign": sign, "absolute_lower_pct": low,
                "absolute_upper_pct": high, "segment_count": int(mask.sum()),
                "length_m": float(lengths[mask].sum()),
            })
    result = pd.DataFrame(rows)
    result["length_km"] = result["length_m"] / 1000.0
    result["distance_share_pct"] = 100.0 * result["length_m"] / lengths.sum()
    validate_length_conservation(float(lengths.sum()), result)
    return result

def locate_profile_segments(
    route: gpd.GeoDataFrame, segments: pd.DataFrame, *, reverse: bool = False
) -> gpd.GeoDataFrame:
    """Cut exact portions of the official axis; retain canonical forward chainages."""
    from movilidad_teide.cartografia.geometrias import route_validation_table

    route_validation_table(route)
    line = route.geometry.iloc[0]
    total = float(line.length)
    directed_line = LineString(list(line.coords)[::-1]) if reverse else line
    starts = segments["distance_start_m"].to_numpy(float)
    ends = segments["distance_end_m"].to_numpy(float)
    if (not np.isfinite(starts).all() or not np.isfinite(ends).all()
            or np.any(starts < 0) or np.any(ends > total) or np.any(ends <= starts)):
        raise GeographicDataError("Los tramos deben estar dentro del eje y tener longitud positiva.")
    result = gpd.GeoDataFrame(segments.copy(), geometry=[
        substring(directed_line, float(start), float(end))
        for start, end in zip(starts, ends, strict=True)
    ], crs=route.crs)
    if not np.allclose(result.geometry.length, result["length_m"], atol=1e-6, rtol=0):
        raise GeographicDataError("La geometría de los tramos no conserva su longitud.")
    result["forward_start_m"] = total - ends if reverse else starts
    result["forward_end_m"] = total - starts if reverse else ends
    midpoints = result.geometry.interpolate(0.5, normalized=True)
    result["midpoint_easting_m"] = midpoints.x
    result["midpoint_northing_m"] = midpoints.y
    geographic = midpoints.to_crs("EPSG:4326")
    result["midpoint_longitude"] = geographic.x
    result["midpoint_latitude"] = geographic.y
    result["chord_length_m"] = [
        np.linalg.norm(np.asarray(g.coords[-1])[:2] - np.asarray(g.coords[0])[:2])
        for g in result.geometry
    ]
    # A low ratio indicates a curved portion; it does not identify a road defect.
    result["chord_to_axis_ratio"] = result["chord_length_m"] / result["length_m"]
    return result
