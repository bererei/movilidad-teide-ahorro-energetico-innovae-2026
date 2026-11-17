"""cartografia: geografia tipos. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations


class GeographicDataError(ValueError):
    """Raised when an input does not satisfy the geographic data contract."""

DEFAULT_METRIC_CRS = "EPSG:4083"  # REGCAN95 / UTM zone 28N

DEFAULT_SLOPE_CLASSES = (-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0)

SEGMENT_COLUMNS = [
    "segment_id",
    "distance_start_m",
    "distance_end_m",
    "length_m",
    "elevation_start_m",
    "elevation_end_m",
    "elevation_change_m",
    "slope_pct",
]
