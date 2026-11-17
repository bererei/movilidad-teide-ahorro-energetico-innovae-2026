"""cartografia: itinerarios tipos. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from dataclasses import dataclass
import re
import geopandas as gpd
import pandas as pd
from movilidad_teide.cartografia.geografia_tipos import GeographicDataError
from movilidad_teide.cartografia.geometrias import combine_ordered_parts
from movilidad_teide.cartografia.geometrias import ensure_metric_crs
from movilidad_teide.trazabilidad import file_sha256
from movilidad_teide.cartografia.geometrias import route_validation_table


class ItineraryConfigError(ValueError):
    """Raised when itinerary configuration is missing, ambiguous or inconsistent."""

class ItineraryExtractionError(GeographicDataError):
    """Raised when official geometry cannot produce the configured itinerary."""

@dataclass
class ItineraryExtractionResult:
    """Tables generated while extracting one configured itinerary."""

    route: gpd.GeoDataFrame
    anchors: gpd.GeoDataFrame
    lineage: gpd.GeoDataFrame
    validation_points: gpd.GeoDataFrame
    validations: pd.DataFrame
    operations: pd.DataFrame
    sources: pd.DataFrame

CONFIG_SCHEMA_VERSION = "1.4"

IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

ANCHOR_TYPES = {"coordinate", "official_pk", "geometry_reference", "source_point"}

DEFINITION_MODES = {"official_axis_sequence", "existing_geometry"}

VALIDATION_STATUSES = {
    "pending",
    "source_verified",
    "technical_pilot",
    "validated",
    "rejected",
}
