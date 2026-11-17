"""Casos sintéticos de interpolación y soporte espacial; no datos de la TF-21."""

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio import Affine
from shapely.geometry import LineString, Point

from movilidad_teide.geografia import (
    GeographicDataError, analyze_sampling_intervals, compare_profile_configurations,
    file_sha256, make_sampling_distances, sample_dem_points,
    sample_review_cross_sections, select_review_stations,
)


def write_dem(path, values, transform, point=False):
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[1],
                       height=values.shape[0], count=1, dtype='float32', crs=4083,
                       transform=transform, nodata=-9999) as ds:
        ds.write(values.astype('float32'), 1)
        if point:
            ds.update_tags(AREA_OR_POINT='Point')
    return path


def points_at(transform, pixel_coordinates):
    return gpd.GeoDataFrame(geometry=[Point(*(transform @ xy)) for xy in pixel_coordinates], crs=4083)


@pytest.mark.parametrize('point', [False, True])
def test_bilinear_pixel_centres_weights_and_affine_rotation(tmp_path, point):
    transform = Affine(5, 1, 300000, 0.5, -5, 3100000)
    values = np.array([[0, 10, 20], [30, 50, 70], [90, 110, 130]])
    path = write_dem(tmp_path/'dem.tif', values, transform, point)
    # Centre (0.5,0.5) must equal pixel [0,0]; point (0.75,1) uses u=.25,v=.5.
    locations = points_at(transform, [(0.5, 0.5), (0.75, 1.0), (2.5, 2.5)])
    before = file_sha256(path)
    result = sample_dem_points(locations, path, method='bilinear')
    np.testing.assert_allclose(result.elevation_m, [0, 18.75, 130], atol=1e-7)
    np.testing.assert_allclose(result.filter(regex=r'support_\d_weight').iloc[1], [.375, .125, .375, .125], atol=1e-9)
    with rasterio.open(path) as ds:
        assert ds.xy(0, 0) == pytest.approx((locations.geometry.iloc[0].x, locations.geometry.iloc[0].y))
        expected = [value[0] for value in ds.sample([(p.x, p.y) for p in locations.geometry])]
    np.testing.assert_array_equal(sample_dem_points(locations, path).elevation_m, expected)
    assert file_sha256(path) == before


@pytest.mark.parametrize('invalid', [-9999, np.nan, np.inf])
def test_bilinear_rejects_positive_weight_missing_or_nonfinite(tmp_path, invalid):
    transform = Affine(5, 0, 0, 0, -5, 20)
    values = np.array([[1, invalid], [3, 4]])
    path = write_dem(tmp_path/'dem.tif', values, transform)
    with pytest.raises(GeographicDataError, match='NoData o no finito'):
        sample_dem_points(points_at(transform, [(1, 1)]), path, method='bilinear')
    # Invalid neighbour with weight zero cannot invalidate the exact valid centre.
    value = sample_dem_points(points_at(transform, [(.5, .5)]), path, method='bilinear')
    assert value.elevation_m.iloc[0] == 1


def test_bilinear_does_not_extrapolate_or_fall_back_at_edge(tmp_path):
    transform = Affine(5, 0, 0, 0, -5, 20)
    path = write_dem(tmp_path/'dem.tif', np.ones((2, 2)), transform)
    locations = points_at(transform, [(.25, .75)])
    assert sample_dem_points(locations, path, method='cell').elevation_m.iloc[0] == 1
    with pytest.raises(GeographicDataError, match='Soporte bilinear fuera'):
        sample_dem_points(locations, path, method='bilinear')


def test_phase_stations_preserve_exact_endpoints_and_short_boundary_segments():
    np.testing.assert_array_equal(make_sampling_distances(516, 200), [0, 200, 400, 516])
    np.testing.assert_array_equal(make_sampling_distances(516, 200, station_offset_m=100), [0, 100, 300, 500, 516])
    np.testing.assert_array_equal(make_sampling_distances(50, 200, station_offset_m=100), [0, 50])
    with pytest.raises(ValueError, match='fase'):
        make_sampling_distances(516, 200, station_offset_m=200)


def test_method_phase_and_common_support_comparisons(tmp_path):
    transform = Affine(5, 0, 0, 0, -5, 50)
    values = np.tile(np.arange(20, dtype=float)**2, (10, 1))
    path = write_dem(tmp_path/'dem.tif', values, transform)
    route = gpd.GeoDataFrame(geometry=[LineString([(6, 25), (71, 25)])], crs=4083)
    results = {}
    for key, method, phase in [('A', 'cell', 0), ('B', 'bilinear', 0), ('C', 'cell', 10), ('D', 'bilinear', 10)]:
        results[key] = analyze_sampling_intervals(route, path, [20], [0, 2, 6, 10], method=method, station_offset_m=phase)[20]
        result = results[key]
        assert result['summary'].length_error_m.eq(0).all()
        forward = result['directions']['PK creciente']['segments']
        reverse = result['directions']['PK decreciente']['segments']
        np.testing.assert_allclose(reverse.slope_pct, -forward.slope_pct.iloc[::-1])
    method = compare_profile_configurations(route, results['A'], results['B'])
    assert len(method['shared_stations']) == 5
    assert method['shared_stations'].elevation_difference_m.abs().max() > 0
    phase = compare_profile_configurations(route, results['A'], results['C'])
    assert phase['shared_stations'].distance_m.tolist() == [0, 65]
    parts = phase['common_support']
    assert parts.length_m.sum() == pytest.approx(65)
    np.testing.assert_array_equal(parts.distance_start_m, [0, 10, 20, 30, 40, 50, 60])
    assert (parts.distance_start_m >= parts.reference_distance_start_m).all()
    assert (parts.distance_end_m <= parts.reference_distance_end_m).all()
    # Integration recovers each original net elevation change, even when phase differs.
    for side, key in [('reference', 'A'), ('candidate', 'C')]:
        expected = results[key]['summary'].iloc[0].net_elevation_change_m
        assert np.sum(parts[f'{side}_slope_pct']*parts.length_m/100) == pytest.approx(expected)
    method['kind'], phase['kind'] = 'method', 'phase'
    shifted_method = compare_profile_configurations(route, results['C'], results['D'])
    shifted_method['kind'] = 'method'
    critical = select_review_stations(
        results, {'B-A': method, 'D-C': shifted_method, 'C-A': phase},
        mandatory_distances_m=[20], neighborhood_range_alert_m=10000,
        top_elevation_count=1, top_phase_interval_count=1, top_method_interval_count=1,
    )
    assert 20 in critical.distance_m.to_numpy()
    for comparison in (method, shifted_method, phase):
        table = comparison['common_support']
        largest = table.loc[table.slope_difference_pp.abs().idxmax()]
        for side in ('reference', 'candidate'):
            for edge in ('start', 'end'):
                assert largest[f'{side}_distance_{edge}_m'] in critical.distance_m.to_numpy()
    assert critical.max_abs_method_elevation_difference_m.notna().all()


def test_cross_sections_are_diagnostic_and_left_positive(tmp_path):
    transform = Affine(5, 0, 0, 0, -5, 50)
    path = write_dem(tmp_path/'dem.tif', np.tile(np.arange(10)[:, None], (1, 10)), transform)
    route = gpd.GeoDataFrame(geometry=[LineString([(5, 25), (45, 25)])], crs=4083)
    stations = gpd.GeoDataFrame({'review_id': ['R01'], 'distance_m': [20]}, geometry=[Point(25, 25)], crs=4083)
    probes = sample_review_cross_sections(route, stations, path, offsets_m=[-5, 0, 5])
    assert probes.geometry.y.tolist() == [20, 25, 30]
    assert probes.elevation_m.tolist() == [6, 5, 4]
    assert list(route.geometry.iloc[0].coords) == [(5, 25), (45, 25)]
