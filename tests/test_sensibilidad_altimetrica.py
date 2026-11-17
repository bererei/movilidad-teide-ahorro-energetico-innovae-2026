"""Contratos de sensibilidad con datos sintéticos, independientes del piloto real."""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point

from movilidad_teide.geografia import (
    analyze_sampling_intervals,
    calculate_segments,
    compare_nested_sampling,
    descriptive_slope_distribution,
    file_sha256,
    locate_profile_segments,
    sampling_quality_diagnostics,
)


def test_descriptive_bins_exact_boundaries_tails_and_distance_weights():
    slopes = np.array([-12, -8, -6.01, -6, -2, 0, 2, 6, 6.01, 8, 12.0])
    lengths = np.arange(1, len(slopes)+1, dtype=float)
    sections = pd.DataFrame({'slope_pct': slopes, 'length_m': lengths})
    distribution = descriptive_slope_distribution(sections, [0, 2, 4, 6, 8, 10])
    by_label = distribution.set_index('slope_interval_pct')
    assert by_label.loc['(4, 6]', 'length_m'] == 8
    assert by_label.loc['[-6, -4)', 'length_m'] == 4
    assert by_label.loc['(6, 8]', 'length_m'] == 19
    assert by_label.loc['[-8, -6)', 'length_m'] == 5
    assert by_label.loc['0', 'length_m'] == 6
    assert distribution.length_m.sum() == lengths.sum()
    assert distribution.distance_share_pct.sum() == pytest.approx(100)
    reversed_distribution = descriptive_slope_distribution(
        sections.assign(slope_pct=-slopes), [0, 2, 4, 6, 8, 10]
    )
    np.testing.assert_allclose(distribution.length_m, reversed_distribution.length_m.iloc[::-1])


def test_descriptive_bins_reject_nonfinite_slopes():
    with pytest.raises(ValueError, match='finitas'):
        descriptive_slope_distribution(pd.DataFrame({'slope_pct': [np.nan], 'length_m': [100]}), [0, 6])


def test_segment_location_keeps_bends_and_reverse_chainages():
    route = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (100, 0), (100, 100)])], crs=4083)
    profile = pd.DataFrame({'distance_m': [0, 150, 200], 'elevation_m': [10, 25, 24]})
    sections = calculate_segments(profile)
    forward = locate_profile_segments(route, sections)
    assert list(forward.geometry.iloc[0].coords) == [(0, 0), (100, 0), (100, 50)]
    assert forward.geometry.length.sum() == pytest.approx(200)
    backward = locate_profile_segments(route, sections, reverse=True)
    assert backward.forward_start_m.tolist() == [50, 0]
    assert backward.forward_end_m.tolist() == [200, 50]
    assert backward.geometry.iloc[0].coords[0] == (100, 100)


@pytest.fixture
def dem(tmp_path):
    path = tmp_path / 'test_dem.tif'
    heights = np.tile(np.array([0, 3, 9, 12, 20, 25, 30], dtype='float32'), (5, 1))
    with rasterio.open(path, 'w', driver='GTiff', width=7, height=5, count=1,
                       dtype='float32', crs=4083, transform=from_origin(0, 50, 10, 10), nodata=-9999) as ds:
        ds.write(heights, 1)
    return path


def test_nested_scales_preserve_partial_final_segment_and_reverse(dem):
    route = gpd.GeoDataFrame(geometry=[LineString([(5, 25), (60, 25)])], crs=4083)
    results = analyze_sampling_intervals(route, dem, [10, 20, 50], [0, 2, 6, 10])
    assert results[10]['summary'].sample_count.tolist() == [7, 7]
    for interval, result in results.items():
        forward = result['directions']['PK creciente']
        backward = result['directions']['PK decreciente']
        assert forward['profile'].distance_m.iloc[-1] == 55
        assert forward['profile'].elevation_m.iloc[-1] == 30
        assert backward['profile'].elevation_m.iloc[0] == 30
        assert forward['segments'].length_m.iloc[-1] == {10: 5, 20: 15, 50: 5}[interval]
        np.testing.assert_allclose(backward['segments'].slope_pct, -forward['segments'].slope_pct.iloc[::-1])
        np.testing.assert_allclose(result['summary'].length_error_m, 0)
    for step in (20, 50):
        comparison = compare_nested_sampling(results[10], results[step])
        np.testing.assert_allclose(comparison.difference_percentage_points, 0, atol=1e-10)


def test_cell_diagnostics_keep_values_and_mark_local_extremum(dem):
    profile = gpd.GeoDataFrame({
        'sample_id': [0, 1, 2], 'distance_m': [0, 10, 20],
        'elevation_m': [0, 10, 0],
    }, geometry=[Point(5, 25), Point(15, 25), Point(25, 25)], crs=4083)
    before = file_sha256(dem)
    result = sampling_quality_diagnostics(profile, dem, residual_alert_m=5)
    assert result.elevation_m.tolist() == [0, 10, 0]
    assert result.residual_review_flag.tolist() == [False, True, False]
    assert result.local_elevation_extremum.tolist() == [False, True, False]
    assert result.local_chord_residual_m.iloc[1] == 10
    assert result.local_chord_residual_m.iloc[[0, -1]].isna().all()
    assert result.raster_col.tolist() == [0, 1, 2]
    assert result.point_to_cell_center_m.tolist() == [0, 0, 0]
    assert result.neighborhood_range_m.iloc[1] == 9
    assert file_sha256(dem) == before
