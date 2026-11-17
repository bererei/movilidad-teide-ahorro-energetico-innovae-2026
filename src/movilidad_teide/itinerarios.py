"""Interfaz compatible; las responsabilidades se organizan en cartografia."""

from movilidad_teide.cartografia.auditoria_rutas import audit_osm_car_sequence, audit_osm_grade_separated_crossings, audit_osm_node_connectivity, audit_service_trace_geometry, compare_reference_and_service_chain, partition_itinerary_at_anchor

from movilidad_teide.cartografia.catalogo_rutas import _anchor_dependency_closure, _require_identifier, _require_mapping, _require_positive_number, load_itinerary_config, validate_itinerary_config

from movilidad_teide.cartografia.exportacion import export_configured_itineraries, export_itinerary_result, plot_itinerary_validation

from movilidad_teide.cartografia.extraccion import _extract_existing_geometry, _resolve_configured_anchors, _reverse_line, _validation_points_for_official_pks, extract_configured_itineraries, extract_configured_itinerary, orient_clip_and_validate_anchors, resolve_anchor, select_ordered_axis_parts

from movilidad_teide.cartografia.fuentes_rutas import _read_gtfs_stop_points, _read_osm_axes, build_source_inventory, explode_line_components, read_geospatial_source, select_exact_records, verify_source_inventory

from movilidad_teide.cartografia.itinerarios_tipos import ANCHOR_TYPES, CONFIG_SCHEMA_VERSION, DEFINITION_MODES, IDENTIFIER_PATTERN, ItineraryConfigError, ItineraryExtractionError, ItineraryExtractionResult, SHA256_PATTERN, VALIDATION_STATUSES

__all__ = ['ANCHOR_TYPES', 'CONFIG_SCHEMA_VERSION', 'DEFINITION_MODES', 'IDENTIFIER_PATTERN', 'ItineraryConfigError', 'ItineraryExtractionError', 'ItineraryExtractionResult', 'SHA256_PATTERN', 'VALIDATION_STATUSES', 'audit_osm_car_sequence', 'audit_osm_grade_separated_crossings', 'audit_osm_node_connectivity', 'audit_service_trace_geometry', 'build_source_inventory', 'compare_reference_and_service_chain', 'explode_line_components', 'export_configured_itineraries', 'export_itinerary_result', 'extract_configured_itineraries', 'extract_configured_itinerary', 'load_itinerary_config', 'orient_clip_and_validate_anchors', 'partition_itinerary_at_anchor', 'plot_itinerary_validation', 'read_geospatial_source', 'resolve_anchor', 'select_exact_records', 'select_ordered_axis_parts', 'validate_itinerary_config', 'verify_source_inventory']
