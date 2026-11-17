"""cartografia: diagnosticos. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS
from rasterio.windows import Window, from_bounds
from shapely.geometry import LineString, MultiLineString, Point, box
from movilidad_teide.cartografia.geografia_tipos import GeographicDataError


def sampling_quality_diagnostics(
    profile: gpd.GeoDataFrame,
    dem_path: str | Path,
    *,
    assumed_raster_crs: str | CRS | None = None,
    neighborhood_radius_pixels: int = 1,
    residual_alert_m: float = 5.0,
) -> gpd.GeoDataFrame:
    """Inspect containing cells and neighbouring raw values, without changing elevations.

    The local residual compares an interior station with the line joining its two
    neighbours. It is a screening diagnostic, not a corrected elevation or error.
    Endpoints have no two-sided residual. Neighbourhoods are clipped at tile edges.
    """
    from movilidad_teide.cartografia.terreno import _raster_coordinate_crs
    from movilidad_teide.cartografia.perfiles import calculate_segments

    calculate_segments(profile)  # validates finite elevations and ordered stations
    if (not isinstance(neighborhood_radius_pixels, int) or neighborhood_radius_pixels < 1
            or not np.isfinite(residual_alert_m) or residual_alert_m <= 0):
        raise ValueError("Radio entero >=1 y umbral residual finito >0 requeridos.")
    result = profile.copy()
    distance = profile["distance_m"].to_numpy(float)
    z = profile["elevation_m"].to_numpy(float)
    residual = np.full(len(z), np.nan)
    fraction = (distance[1:-1] - distance[:-2]) / (distance[2:] - distance[:-2])
    residual[1:-1] = z[1:-1] - (z[:-2] + fraction * (z[2:] - z[:-2]))
    result["local_chord_residual_m"] = residual
    result["residual_review_flag"] = np.abs(residual) > residual_alert_m
    result["local_elevation_extremum"] = False
    result.loc[result.index[1:-1], "local_elevation_extremum"] = (
        (z[1:-1] - z[:-2]) * (z[2:] - z[1:-1]) < 0
    )
    cells = []
    with rasterio.open(dem_path) as dataset:
        crs = _raster_coordinate_crs(dataset.crs, assumed_raster_crs)
        points = profile.to_crs(crs).geometry
        for point in points:
            row, col = dataset.index(point.x, point.y)
            if not (0 <= row < dataset.height and 0 <= col < dataset.width):
                raise GeographicDataError("Muestra fuera del MDT en diagnóstico de celdas.")
            radius = neighborhood_radius_pixels
            r0, r1 = max(0, row - radius), min(dataset.height, row + radius + 1)
            c0, c1 = max(0, col - radius), min(dataset.width, col + radius + 1)
            values = dataset.read(1, window=Window(c0, r0, c1-c0, r1-r0), masked=True)
            valid = values.compressed()
            valid = valid[np.isfinite(valid)]
            cx, cy = dataset.xy(row, col)
            cells.append({
                "raster_row": row, "raster_col": col,
                "cell_center_easting_m": cx, "cell_center_northing_m": cy,
                "point_to_cell_center_m": float(np.hypot(point.x-cx, point.y-cy)),
                "neighborhood_valid_count": len(valid),
                "neighborhood_missing_count": int(values.size - len(valid)),
                "neighborhood_min_m": float(valid.min()) if len(valid) else np.nan,
                "neighborhood_max_m": float(valid.max()) if len(valid) else np.nan,
                "neighborhood_range_m": float(valid.max()-valid.min()) if len(valid) else np.nan,
            })
    for name in cells[0]:
        result[name] = [cell[name] for cell in cells]
    return result

def analyze_sampling_intervals(
    route: gpd.GeoDataFrame, dem_path: str | Path, intervals_m: Sequence[float],
    absolute_edges_pct: Sequence[float], *, assumed_raster_crs: str | CRS | None = None,
    reference_pct: float = 6.0, anomaly_alert_pct: float = 20.0,
    residual_alert_m: float = 5.0, neighborhood_radius_pixels: int = 1,
    length_tolerance_m: float = 1e-6, extreme_count: int = 10,
    method: str = "cell", station_offset_m: float = 0.0,
) -> dict[float, dict[str, Any]]:
    """One physical station grid per interval, then reverse the same physical segments."""
    from movilidad_teide.cartografia.perfiles import calculate_segments
    from movilidad_teide.cartografia.perfiles import descriptive_slope_distribution
    from movilidad_teide.cartografia.perfiles import extreme_slope_table
    from movilidad_teide.cartografia.perfiles import locate_profile_segments
    from movilidad_teide.cartografia.perfiles import profile_quality_table
    from movilidad_teide.cartografia.perfiles import reverse_profile
    from movilidad_teide.cartografia.perfiles import reverse_segments
    from movilidad_teide.cartografia.perfiles import route_summary
    from movilidad_teide.cartografia.perfiles import sample_elevation_profile
    from movilidad_teide.cartografia.perfiles import validate_length_conservation

    intervals = np.asarray(intervals_m, dtype=float)
    if (intervals.ndim != 1 or not len(intervals) or not np.isfinite(intervals).all()
            or np.any(intervals <= 0) or len(np.unique(intervals)) != len(intervals)):
        raise ValueError("Los intervalos deben ser positivos, finitos y distintos.")
    if not np.isfinite(reference_pct) or reference_pct <= 0:
        raise ValueError("El umbral descriptivo debe ser finito y positivo.")
    total = float(route.geometry.iloc[0].length)
    results: dict[float, dict[str, Any]] = {}
    reference_endpoints = None
    for interval in intervals:
        forward = sample_elevation_profile(
            route, dem_path, float(interval), assumed_raster_crs=assumed_raster_crs,
            method=method, station_offset_m=station_offset_m,
        )
        endpoint_values = forward.iloc[[0, -1]][["distance_m", "elevation_m"]].to_numpy(float)
        if reference_endpoints is None:
            reference_endpoints = endpoint_values
        if not np.array_equal(reference_endpoints, endpoint_values):
            raise GeographicDataError("Los extremos difieren entre intervalos.")
        if (not forward.geometry.iloc[0].equals(route.geometry.iloc[0].interpolate(0))
                or not forward.geometry.iloc[-1].equals(route.geometry.iloc[0].interpolate(total))):
            raise GeographicDataError("Las muestras no conservan exactamente los extremos del eje.")
        backward = reverse_profile(forward)
        forward_segments = calculate_segments(forward)
        backward_segments = reverse_segments(forward_segments)
        independently_reversed = calculate_segments(backward)
        if not np.allclose(backward_segments, independently_reversed, atol=1e-9, rtol=0):
            raise GeographicDataError("La inversión del perfil y los tramos no concuerda.")
        by_direction = {}
        summaries, distributions = [], []
        for direction, points, sections in (
            ("PK creciente", forward, forward_segments),
            ("PK decreciente", backward, backward_segments),
        ):
            length_error = validate_length_conservation(total, sections, length_tolerance_m)
            located = locate_profile_segments(route, sections, reverse=direction == "PK decreciente")
            located["above_positive_reference"] = located.slope_pct > reference_pct
            located["below_negative_reference"] = located.slope_pct < -reference_pct
            distribution = descriptive_slope_distribution(sections, absolute_edges_pct)
            distribution["direction"] = direction
            distribution["sample_interval_m"] = interval
            summary = route_summary(points, sections).iloc[0].to_dict()
            summary.update({
                "direction": direction, "sample_interval_m": interval,
                "elevation_method": method, "station_offset_m": station_offset_m,
                "total_length_m": total, "length_error_m": length_error,
                "net_mean_slope_pct": 100.0 * summary["net_elevation_change_m"] / total,
                "distance_weighted_mean_slope_pct": float(np.average(sections.slope_pct, weights=sections.length_m)),
                "above_reference_length_m": float(located.loc[located.above_positive_reference, "length_m"].sum()),
                "below_reference_length_m": float(located.loc[located.below_negative_reference, "length_m"].sum()),
                "descending_segment_count": int((sections.slope_pct < 0).sum()),
                "last_segment_length_m": float(sections.length_m.iloc[-1]),
            })
            if not np.isclose(summary["net_mean_slope_pct"], summary["distance_weighted_mean_slope_pct"], rtol=0, atol=1e-10):
                raise GeographicDataError("La media ponderada no coincide con la pendiente neta.")
            summaries.append(summary)
            distributions.append(distribution)
            by_direction[direction] = {"profile": points, "segments": located}
        extremes = extreme_slope_table(forward_segments, extreme_count, anomaly_alert_pct)
        minimum_id = int(forward_segments.loc[forward_segments.slope_pct.idxmin(), "segment_id"])
        maximum_id = int(forward_segments.loc[forward_segments.slope_pct.idxmax(), "segment_id"])
        selected = set(extremes.segment_id) | {minimum_id, maximum_id}
        extreme_geometries = by_direction["PK creciente"]["segments"].loc[
            lambda frame: frame.segment_id.isin(selected)
        ].copy()
        extreme_geometries["is_minimum"] = extreme_geometries.segment_id == minimum_id
        extreme_geometries["is_maximum"] = extreme_geometries.segment_id == maximum_id
        extreme_geometries["exceeds_alert_threshold"] = extreme_geometries.slope_pct.abs() > anomaly_alert_pct
        quality = sampling_quality_diagnostics(
            forward, dem_path, assumed_raster_crs=assumed_raster_crs,
            neighborhood_radius_pixels=neighborhood_radius_pixels, residual_alert_m=residual_alert_m,
        )
        results[float(interval)] = {
            "directions": by_direction, "summary": pd.DataFrame(summaries),
            "distribution": pd.concat(distributions, ignore_index=True),
            "extremes": extreme_geometries, "sampling_diagnostics": quality,
            "quality_checks": profile_quality_table(forward, forward_segments, anomaly_alert_pct),
        }
    return results

def compare_profile_configurations(
    route: gpd.GeoDataFrame, reference: dict[str, Any], candidate: dict[str, Any],
    *, reference_pct: float = 6.0,
) -> dict[str, Any]:
    """Compare actual shared stations, and slope representations on common supports.

    For different phases, split both piecewise-constant slope representations at
    the union of their boundaries. Each subinterval inherits its parent's slope:
    it is NOT a newly measured slope or an interpolated DEM elevation. Parent
    bounds/IDs are retained. No direct pairing of differently bounded segments.
    """
    from movilidad_teide.cartografia.perfiles import locate_profile_segments
    from movilidad_teide.cartografia.perfiles import validate_length_conservation
    ref = reference["directions"]["PK creciente"]
    new = candidate["directions"]["PK creciente"]
    rp, cp = ref["profile"].set_index("distance_m"), new["profile"].set_index("distance_m")
    if not np.array_equal(rp.index[[0, -1]], cp.index[[0, -1]]):
        raise GeographicDataError("Los perfiles no cubren las mismas distancias extremas.")
    shared = rp.index.intersection(cp.index).sort_values()
    if not rp.loc[shared].geometry.equals(cp.loc[shared].geometry):
        raise GeographicDataError("Las estaciones coincidentes no tienen la misma geometría.")
    stations = rp.loc[shared, ["geometry"]].copy().reset_index()
    stations["reference_elevation_m"] = rp.loc[shared].elevation_m.to_numpy()
    stations["candidate_elevation_m"] = cp.loc[shared].elevation_m.to_numpy()
    stations["elevation_difference_m"] = stations.candidate_elevation_m - stations.reference_elevation_m
    stations["longitude"] = stations.to_crs(4326).geometry.x
    stations["latitude"] = stations.to_crs(4326).geometry.y
    edges = np.union1d(rp.index.to_numpy(), cp.index.to_numpy())
    midpoint = (edges[:-1] + edges[1:])/2
    rows = pd.DataFrame({"distance_start_m": edges[:-1], "distance_end_m": edges[1:],
                         "length_m": np.diff(edges)})
    for name, original in (("reference", ref["segments"]), ("candidate", new["segments"])):
        indices = np.searchsorted(original.distance_end_m.to_numpy(), midpoint, side="right")
        parent = original.iloc[indices]
        for field in ("segment_id", "distance_start_m", "distance_end_m", "slope_pct"):
            rows[f"{name}_{field}"] = parent[field].to_numpy()
        validate_length_conservation(float(edges[-1]), original)
    rows["slope_difference_pp"] = rows.candidate_slope_pct - rows.reference_slope_pct
    rows["above_reference_disagrees"] = (rows.candidate_slope_pct > reference_pct) != (rows.reference_slope_pct > reference_pct)
    rows["below_reference_disagrees"] = (rows.candidate_slope_pct < -reference_pct) != (rows.reference_slope_pct < -reference_pct)
    located = locate_profile_segments(route, rows)
    validate_length_conservation(float(edges[-1]), located)
    summary = {
        "shared_station_count": len(stations),
        "max_abs_shared_elevation_difference_m": float(stations.elevation_difference_m.abs().max()),
        "max_abs_slope_difference_pp": float(rows.slope_difference_pp.abs().max()),
        "distance_weighted_abs_slope_difference_pp": float(np.average(rows.slope_difference_pp.abs(), weights=rows.length_m)),
        "above_reference_disagreement_km": float(rows.loc[rows.above_reference_disagrees, "length_m"].sum()/1000),
        "below_reference_disagreement_km": float(rows.loc[rows.below_reference_disagrees, "length_m"].sum()/1000),
        "common_support_length_m": float(rows.length_m.sum()),
    }
    return {"shared_stations": stations, "common_support": located, "summary": summary}

def select_review_stations(
    results: dict[str, dict[str, Any]], comparisons: dict[str, dict[str, Any]], *,
    mandatory_distances_m: Sequence[float], neighborhood_range_alert_m: float,
    top_elevation_count: int = 5, top_phase_interval_count: int = 3,
    top_method_interval_count: int = 3,
) -> gpd.GeoDataFrame:
    """Reproducible screening candidates, not errors or confidence intervals.

    Select shared stations with largest method differences, high raw 3x3 ranges,
    and both ORIGINAL parent endpoints of the largest slope discrepancies.
    """
    diagnostics = pd.concat([value["sampling_diagnostics"] for value in results.values()])
    diagnostics = gpd.GeoDataFrame(diagnostics, crs=next(iter(results.values()))["sampling_diagnostics"].crs)
    stations = diagnostics.drop_duplicates("distance_m").set_index("distance_m").sort_index()
    reasons: dict[float, set[str]] = {}
    def flag(distance: float, reason: str) -> None:
        if distance not in stations.index:
            raise GeographicDataError(f"Estación de revisión no muestreada: {distance}.")
        reasons.setdefault(float(distance), set()).add(reason)
    for distance in mandatory_distances_m:
        flag(distance, "revisión solicitada")
    for distance in stations.index[stations.neighborhood_range_m > neighborhood_range_alert_m]:
        flag(distance, "contraste vecindad 3x3")
    largest_deltas: dict[float, float] = {}
    for name, comparison in comparisons.items():
        shared = comparison["shared_stations"]
        if comparison["kind"] == "method":
            for row in shared.itertuples():
                largest_deltas[row.distance_m] = max(largest_deltas.get(row.distance_m, 0), abs(row.elevation_difference_m))
            ranked = shared.assign(magnitude=shared.elevation_difference_m.abs()).sort_values(
                ["magnitude", "distance_m"], ascending=[False, True]).head(top_elevation_count)
            for distance in ranked.distance_m:
                flag(distance, f"diferencia de método {name}")
        if comparison["kind"] in ("method", "phase"):
            count = top_phase_interval_count if comparison["kind"] == "phase" else top_method_interval_count
            kind_label = "fase" if comparison["kind"] == "phase" else "método"
            ranked = comparison["common_support"].assign(
                magnitude=lambda frame: frame.slope_difference_pp.abs()
            ).sort_values(["magnitude", "distance_start_m"], ascending=[False, True]).head(count)
            for row in ranked.itertuples():
                for side in ("reference", "candidate"):
                    for edge in ("start", "end"):
                        flag(getattr(row, f"{side}_distance_{edge}_m"), f"extremo de tramo sensible a {kind_label} {name}")
    result = stations.loc[sorted(reasons)].copy().reset_index()
    result["review_id"] = [f"R{i:02}" for i in range(1, len(result)+1)]
    result["review_reasons"] = ["; ".join(sorted(reasons[d])) for d in result.distance_m]
    result["max_abs_method_elevation_difference_m"] = [largest_deltas.get(d, np.nan) for d in result.distance_m]
    result["longitude"] = result.to_crs(4326).geometry.x
    result["latitude"] = result.to_crs(4326).geometry.y
    result["review_status"] = "pending_official_orthophoto_and_road_elevation_check"
    return result

def sample_review_cross_sections(
    route: gpd.GeoDataFrame, stations: gpd.GeoDataFrame, dem_path: str | Path, *,
    offsets_m: Sequence[float], tangent_half_window_m: float = 5.0,
    assumed_raster_crs: str | CRS | None = None,
) -> gpd.GeoDataFrame:
    """Raw cross-axis probes for review only, never replacements of route elevations.

    Positive offset is left of the oriented local chord. The chord spans +/- the
    configured along-axis window (clipped at endpoints). Offsets do not identify
    lane edges or prove a cutting/embankment; bends can affect the local normal.
    """
    from movilidad_teide.cartografia.geometrias import route_validation_table
    from movilidad_teide.cartografia.terreno import sample_dem_points
    route_validation_table(route)
    if tangent_half_window_m <= 0 or not np.isfinite(tangent_half_window_m):
        raise ValueError("La ventana tangente debe ser finita y positiva.")
    offsets = np.asarray(offsets_m, dtype=float)
    if offsets.ndim != 1 or not len(offsets) or not np.isfinite(offsets).all():
        raise ValueError("Offsets transversales finitos requeridos.")
    line = route.geometry.iloc[0]
    rows = []
    for station in stations.itertuples():
        distance = station.distance_m
        p0 = line.interpolate(max(0, distance-tangent_half_window_m))
        p1 = line.interpolate(min(line.length, distance+tangent_half_window_m))
        delta = np.array([p1.x-p0.x, p1.y-p0.y])
        norm = np.linalg.norm(delta)
        if norm == 0:
            raise GeographicDataError("No se puede definir la normal local.")
        normal = np.array([-delta[1], delta[0]])/norm
        point = line.interpolate(distance)
        for offset in offsets:
            rows.append({"review_id": station.review_id, "distance_m": distance,
                         "cross_offset_m": offset,
                         "geometry": Point(point.x+offset*normal[0], point.y+offset*normal[1])})
    points = gpd.GeoDataFrame(rows, crs=route.crs)
    return sample_dem_points(points, dem_path, method="cell", assumed_raster_crs=assumed_raster_crs)

def compare_nested_sampling(
    fine: dict[str, Any], coarse: dict[str, Any]
) -> pd.DataFrame:
    """Verify a coarser grid against unchanged shared stations and weighted fine slopes."""
    from movilidad_teide.cartografia.perfiles import validate_length_conservation

    fine_forward = fine["directions"]["PK creciente"]
    coarse_forward = coarse["directions"]["PK creciente"]
    fine_profile = fine_forward["profile"].set_index("distance_m")
    coarse_profile = coarse_forward["profile"].set_index("distance_m")
    if not coarse_profile.index.isin(fine_profile.index).all():
        raise GeographicDataError("Las estaciones gruesas no están anidadas en la malla fina.")
    shared = fine_profile.loc[coarse_profile.index, "elevation_m"]
    if not np.array_equal(shared, coarse_profile.elevation_m):
        raise GeographicDataError("Las cotas de estaciones compartidas difieren.")
    fs = fine_forward["segments"]
    rows = []
    for coarse_segment in coarse_forward["segments"].itertuples():
        parts = fs.loc[
            (fs.distance_start_m >= coarse_segment.distance_start_m)
            & (fs.distance_end_m <= coarse_segment.distance_end_m)
        ]
        validate_length_conservation(coarse_segment.length_m, parts)
        weighted = float(np.average(parts.slope_pct, weights=parts.length_m))
        rows.append({
            "segment_id": coarse_segment.segment_id,
            "distance_start_m": coarse_segment.distance_start_m,
            "distance_end_m": coarse_segment.distance_end_m,
            "fine_segment_count": len(parts),
            "coarse_slope_pct": coarse_segment.slope_pct,
            "weighted_fine_slope_pct": weighted,
            "difference_percentage_points": coarse_segment.slope_pct - weighted,
        })
    result = pd.DataFrame(rows)
    if not np.allclose(result.difference_percentage_points, 0, rtol=0, atol=1e-10):
        raise GeographicDataError("La pendiente gruesa no coincide con la media ponderada fina.")
    return result

def compare_shared_direction_profiles(
    forward_profile, backward_profile, forward_segments, backward_segments,
    shared_axis, interval_m, *, tolerance=1e-6,
):
    """Contrastar cotas y pendientes por ubicación en un eje común explícito.

    Los accesos distintos permanecen fuera del contraste. Los perfiles deben
    compartir estaciones en el eje y recorrerlo en sentidos opuestos; no se
    interpolan cotas, se alteran pendientes ni se emparejan números de fila.
    La tolerancia numérica se aplica a metros y puntos porcentuales.
    """
    from movilidad_teide.cartografia.geometrias import ensure_metric_crs
    if (not isinstance(shared_axis, LineString) or not shared_axis.is_simple
            or not np.isfinite(shared_axis.length) or shared_axis.length <= 0
            or not np.isfinite(interval_m) or interval_m <= 0
            or not np.isfinite(tolerance) or tolerance <= 0):
        raise GeographicDataError('Eje común, intervalo o tolerancia no válidos.')
    if forward_profile.crs != backward_profile.crs:
        raise GeographicDataError('Los perfiles deben utilizar el mismo CRS métrico.')
    ensure_metric_crs(forward_profile.crs)
    stations, slopes = [], []
    for direction, profile, segments in [
        ('forward', forward_profile, forward_segments),
        ('backward', backward_profile, backward_segments),
    ]:
        if len(profile) < 2 or len(segments) != len(profile)-1:
            raise GeographicDataError('No coinciden muestras y segmentos del perfil.')
        if (not profile.geometry.geom_type.eq('Point').all()
                or not np.isfinite(profile.elevation_m).all()
                or not np.isfinite(segments.slope_pct).all()):
            raise GeographicDataError('El contraste requiere puntos, cotas y pendientes finitos.')
        # El eje recibido identifica ubicaciones comunes; proximidad al otro perfil no basta.
        inside = profile.geometry.distance(shared_axis).to_numpy() <= tolerance
        chainage = np.array([shared_axis.project(point) for point in profile.geometry])
        projected = chainage[inside]
        sign = 1 if direction == 'forward' else -1
        if len(projected) < 2 or not np.all(sign*np.diff(projected) > tolerance):
            raise GeographicDataError('Estaciones insuficientes o sentido incompatible con el eje común.')
        frame = pd.DataFrame({'station_m':chainage[inside].round(6),
            direction+'_elevation_m':profile.elevation_m.to_numpy()[inside],
            direction+'_x_m':profile.geometry.x.to_numpy()[inside],
            direction+'_y_m':profile.geometry.y.to_numpy()[inside]})
        if frame.station_m.duplicated().any():
            raise GeographicDataError('Estaciones duplicadas en el eje común.')
        stations.append(frame)
        # Asociar cada pendiente ya calculada a sus dos extremos físicos.
        both = inside[:-1] & inside[1:]
        frame = pd.DataFrame({'from_m':np.minimum(chainage[:-1],chainage[1:]).round(6),
            'to_m':np.maximum(chainage[:-1],chainage[1:]).round(6),
            direction+'_slope_pct':segments.slope_pct.to_numpy()})
        slopes.append(frame.loc[both])
    coherent = stations[0].merge(stations[1],on='station_m',validate='one_to_one').sort_values('station_m')
    expected = max(2, int(shared_axis.length // interval_m)+1)
    if (len(coherent) < expected
            or not np.allclose(coherent.forward_x_m,coherent.backward_x_m,atol=tolerance,rtol=0)
            or not np.allclose(coherent.forward_y_m,coherent.backward_y_m,atol=tolerance,rtol=0)
            or not np.allclose(coherent.forward_elevation_m,coherent.backward_elevation_m,atol=tolerance,rtol=0)):
        raise GeographicDataError('No coinciden las cotas y ubicaciones de las estaciones comunes esperadas.')
    opposite = slopes[0].merge(slopes[1],on=['from_m','to_m'],validate='one_to_one')
    if (len(opposite) < expected-1
            or not np.allclose(opposite.forward_slope_pct,-opposite.backward_slope_pct,atol=tolerance,rtol=0)):
        raise GeographicDataError('No son opuestas las pendientes calculadas en los intervalos físicos comunes.')
    return coherent.reset_index(drop=True), opposite.sort_values('from_m').reset_index(drop=True)
