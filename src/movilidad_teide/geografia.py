"""Interfaz compatible; las responsabilidades se organizan en cartografia."""

from movilidad_teide.cartografia.diagnosticos import analyze_sampling_intervals, compare_nested_sampling, compare_profile_configurations, compare_shared_direction_profiles, sample_review_cross_sections, sampling_quality_diagnostics, select_review_stations

from movilidad_teide.cartografia.geografia_tipos import DEFAULT_METRIC_CRS, DEFAULT_SLOPE_CLASSES, GeographicDataError, SEGMENT_COLUMNS

from movilidad_teide.cartografia.geometrias import _combine_ordered_parts, _iter_line_parts, _read_route_layer, combine_ordered_parts, ensure_metric_crs, load_route, route_validation_table

from movilidad_teide.cartografia.mapas import plot_elevation_profile, plot_route, plot_route_on_dem, plot_sampling_comparison, plot_segment_slopes, plot_slope_distribution

from movilidad_teide.cartografia.perfiles import _validated_classes, calculate_segments, classify_slopes, descriptive_slope_distribution, extreme_slope_table, locate_profile_segments, make_sampling_distances, profile_quality_table, reverse_profile, reverse_segments, route_summary, sample_elevation_profile, slope_distribution, validate_length_conservation

from movilidad_teide.cartografia.terreno import _raster_coordinate_crs, _route_in_raster_crs, convert_wcs_arcgrid_response, extend_native_dem, raster_metadata, sample_dem_points, validate_dem_coverage

from movilidad_teide.trazabilidad import file_sha256

__all__ = ['DEFAULT_METRIC_CRS', 'DEFAULT_SLOPE_CLASSES', 'GeographicDataError', 'SEGMENT_COLUMNS', 'analyze_sampling_intervals', 'calculate_segments', 'classify_slopes', 'combine_ordered_parts', 'compare_nested_sampling', 'compare_profile_configurations', 'compare_shared_direction_profiles', 'convert_wcs_arcgrid_response', 'descriptive_slope_distribution', 'ensure_metric_crs', 'extend_native_dem', 'extreme_slope_table', 'file_sha256', 'load_route', 'locate_profile_segments', 'make_sampling_distances', 'plot_elevation_profile', 'plot_route', 'plot_route_on_dem', 'plot_sampling_comparison', 'plot_segment_slopes', 'plot_slope_distribution', 'profile_quality_table', 'raster_metadata', 'reverse_profile', 'reverse_segments', 'route_summary', 'route_validation_table', 'sample_dem_points', 'sample_elevation_profile', 'sample_review_cross_sections', 'sampling_quality_diagnostics', 'select_review_stations', 'slope_distribution', 'validate_dem_coverage', 'validate_length_conservation']
