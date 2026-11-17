"""cartografia: catalogo rutas. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
import numpy as np
from movilidad_teide.cartografia.geografia_tipos import GeographicDataError
from movilidad_teide.cartografia.geometrias import combine_ordered_parts
from movilidad_teide.cartografia.geometrias import ensure_metric_crs
from movilidad_teide.trazabilidad import file_sha256
from movilidad_teide.cartografia.geometrias import route_validation_table
from movilidad_teide.cartografia.itinerarios_tipos import ItineraryConfigError
from movilidad_teide.cartografia.itinerarios_tipos import IDENTIFIER_PATTERN
from movilidad_teide.cartografia.itinerarios_tipos import ANCHOR_TYPES
from movilidad_teide.cartografia.itinerarios_tipos import CONFIG_SCHEMA_VERSION
from movilidad_teide.cartografia.itinerarios_tipos import DEFINITION_MODES
from movilidad_teide.cartografia.itinerarios_tipos import SHA256_PATTERN
from movilidad_teide.cartografia.itinerarios_tipos import VALIDATION_STATUSES


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ItineraryConfigError(f"'{name}' debe ser un objeto JSON.")
    return value


def _require_identifier(identifier: str, context: str) -> None:
    if not isinstance(identifier, str) or not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ItineraryConfigError(
            f"Identificador no válido en {context}: {identifier!r}. Use minúsculas, números y guion bajo."
        )

def _require_positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ItineraryConfigError(f"'{name}' debe ser numérico.")
    numeric = float(value)
    if not np.isfinite(numeric) or numeric <= 0:
        raise ItineraryConfigError(f"'{name}' debe ser finito y positivo.")
    return numeric

def _anchor_dependency_closure(identifiers, anchors):
    resolved, active = set(), set()
    def visit(identifier):
        if identifier in active:
            raise ItineraryConfigError("Dependencia circular entre referencias de anclaje.")
        if identifier in resolved:
            return
        if identifier not in anchors:
            raise ItineraryConfigError("No existe la referencia maestra del anclaje.")
        active.add(identifier)
        spec = anchors[identifier]
        if spec.get("geometry_position") == "projection":
            visit(spec.get("reference_anchor_id", spec.get("coordinate_anchor_id")))
        active.remove(identifier)
        resolved.add(identifier)
    for identifier in identifiers:
        visit(identifier)
    return resolved






def validate_itinerary_config(config: Mapping[str, Any]) -> None:
    """Validate the minimal versioned configuration contract."""

    if config.get("schema_version") not in {"1.0", "1.1", "1.2", "1.3", CONFIG_SCHEMA_VERSION}:
        raise ItineraryConfigError(
            f"schema_version debe ser {CONFIG_SCHEMA_VERSION!r}."
        )
    if "metric_crs" not in config:
        raise ItineraryConfigError("Falta 'metric_crs'.")
    ensure_metric_crs(config["metric_crs"])

    parameters = _require_mapping(config.get("parameters"), "parameters")
    for parameter_name in (
        "continuity_tolerance_m",
        "anchor_axis_tolerance_m",
        "length_tolerance_m",
    ):
        _require_positive_number(parameters.get(parameter_name), f"parameters.{parameter_name}")

    sources = _require_mapping(config.get("sources"), "sources")
    if not sources:
        raise ItineraryConfigError("Debe declararse al menos una fuente.")
    for source_id, source in sources.items():
        _require_identifier(source_id, "sources")
        source = _require_mapping(source, f"sources.{source_id}")
        for field in ("kind", "path", "provider", "version", "expected_sha256"):
            if source.get(field) in (None, ""):
                raise ItineraryConfigError(f"Falta sources.{source_id}.{field}.")
        if source.get("format") not in (None,"osm_xml","gtfs_stops"):
            raise ItineraryConfigError("Formato geográfico no admitido; revisar fuente.")
        source_path = Path(source["path"])
        if source_path.is_absolute() or ".." in source_path.parts:
            raise ItineraryConfigError(
                f"sources.{source_id}.path debe ser relativo al proyecto y no contener '..'."
            )
        if not SHA256_PATTERN.fullmatch(str(source["expected_sha256"])):
            raise ItineraryConfigError(
                f"sources.{source_id}.expected_sha256 no es una huella SHA-256 válida."
            )
        if source["kind"] in {"road_axes", "kilometer_points", "route_geometry"}:
            if source.get("layer") in (None, ""):
                raise ItineraryConfigError(f"Falta sources.{source_id}.layer.")

    anchors = _require_mapping(config.get("anchors"), "anchors")
    for anchor_id, anchor in anchors.items():
        _require_identifier(anchor_id, "anchors")
        anchor = _require_mapping(anchor, f"anchors.{anchor_id}")
        anchor_type = anchor.get("type")
        if anchor_type not in ANCHOR_TYPES:
            raise ItineraryConfigError(
                f"Tipo de anclaje no admitido en {anchor_id}: {anchor_type!r}."
            )
        status = anchor.get("validation_status")
        if status not in VALIDATION_STATUSES:
            raise ItineraryConfigError(
                f"Estado de validación no admitido en {anchor_id}: {status!r}."
            )
        source_id = anchor.get("source_id")
        if source_id is not None and source_id not in sources:
            raise ItineraryConfigError(
                f"El anclaje {anchor_id} referencia una fuente inexistente: {source_id!r}."
            )
        if anchor_type == "official_pk":
            for field in ("source_id", "road_name", "pk"):
                if anchor.get(field) in (None, ""):
                    raise ItineraryConfigError(f"Falta anchors.{anchor_id}.{field}.")
            if isinstance(anchor["pk"], bool) or not isinstance(anchor["pk"], (int, float)):
                raise ItineraryConfigError(f"anchors.{anchor_id}.pk debe ser numérico.")
        elif anchor_type == "source_point":
            # Referenciar el punto original evita otra coordenada editable.
            if not source_id or not isinstance(anchor.get("feature_filters"), Mapping) or not anchor["feature_filters"]:
                raise ItineraryConfigError(f"{anchor_id}: source_point requiere fuente y filtros exactos.")
        elif anchor_type == "coordinate":
            coordinates = anchor.get("coordinates")
            if (
                not isinstance(coordinates, list)
                or len(coordinates) != 2
                or not all(isinstance(value, (int, float)) for value in coordinates)
                or not all(np.isfinite(value) for value in coordinates)
                or anchor.get("crs") in (None, "")
            ):
                raise ItineraryConfigError(
                    f"El anclaje {anchor_id} requiere coordinates=[x, y] y crs."
                )
        else:
            for field in ("source_id", "feature_filters", "geometry_position"):
                if anchor.get(field) in (None, ""):
                    raise ItineraryConfigError(f"Falta anchors.{anchor_id}.{field}.")
            if not isinstance(anchor["feature_filters"], Mapping):
                raise ItineraryConfigError(
                    f"anchors.{anchor_id}.feature_filters debe ser un objeto JSON."
                )
            if anchor["geometry_position"] not in {"start", "end", "projection"}:
                raise ItineraryConfigError(
                    f"anchors.{anchor_id}.geometry_position debe ser start, end o projection."
                )

    # Las proyecciones reutilizan otra referencia; no crean una coordenada editable duplicada.
    for anchor_id, anchor in anchors.items():
        if anchor.get("geometry_position") == "projection":
            legacy = anchor.get("coordinate_anchor_id")
            generic = anchor.get("reference_anchor_id")
            if legacy is not None and generic is not None:
                raise ItineraryConfigError("La proyección debe tener una única referencia maestra.")
            reference_id = generic if generic is not None else legacy
            if reference_id not in anchors or (legacy is not None and anchors[reference_id].get("type") != "coordinate"):
                raise ItineraryConfigError(f"El anclaje {anchor_id} requiere una coordenada maestra existente o referencia maestra válida.")
    # Detectar ciclos antes de leer fuentes o resolver dependencias recursivas.
    _anchor_dependency_closure(set(anchors), anchors)

    itineraries = _require_mapping(config.get("itineraries"), "itineraries")
    if not itineraries:
        raise ItineraryConfigError("Debe declararse al menos un itinerario.")
    for itinerary_id, itinerary in itineraries.items():
        _require_identifier(itinerary_id, "itineraries")
        itinerary = _require_mapping(itinerary, f"itineraries.{itinerary_id}")
        for field in (
            "name",
            "purpose",
            "validation_status",
            "operational_route",
            "definition_mode",
            "origin_anchor_id",
            "destination_anchor_id",
            "waypoint_anchor_ids",
            "direction_labels",
        ):
            if field not in itinerary:
                raise ItineraryConfigError(f"Falta itineraries.{itinerary_id}.{field}.")
        if itinerary["validation_status"] not in VALIDATION_STATUSES:
            raise ItineraryConfigError(
                f"Estado no admitido en {itinerary_id}: {itinerary['validation_status']!r}."
            )
        if not isinstance(itinerary["operational_route"], bool):
            raise ItineraryConfigError(
                f"itineraries.{itinerary_id}.operational_route debe ser booleano."
            )
        if itinerary["definition_mode"] not in DEFINITION_MODES:
            raise ItineraryConfigError(
                f"Modo no admitido en {itinerary_id}: {itinerary['definition_mode']!r}."
            )
        if not isinstance(itinerary["waypoint_anchor_ids"], list):
            raise ItineraryConfigError(
                f"itineraries.{itinerary_id}.waypoint_anchor_ids debe ser una lista."
            )
        anchor_ids = [
            itinerary["origin_anchor_id"],
            *itinerary["waypoint_anchor_ids"],
            itinerary["destination_anchor_id"],
        ]
        if any(anchor_id not in anchors for anchor_id in anchor_ids):
            missing = [anchor_id for anchor_id in anchor_ids if anchor_id not in anchors]
            raise ItineraryConfigError(
                f"El itinerario {itinerary_id} referencia anclajes inexistentes: {missing}."
            )
        if len(set(anchor_ids)) != len(anchor_ids):
            raise ItineraryConfigError(
                f"El itinerario {itinerary_id} repite anclajes en su secuencia."
            )
        directions = _require_mapping(
            itinerary["direction_labels"], f"itineraries.{itinerary_id}.direction_labels"
        )
        if directions.get("forward") in (None, "") or directions.get("reverse") in (None, ""):
            raise ItineraryConfigError(
                f"El itinerario {itinerary_id} requiere etiquetas para ambos sentidos."
            )
        audit = itinerary.get("source_trace_audit")
        if audit is not None:
            audit = _require_mapping(audit, "source_trace_audit")
            if not SHA256_PATTERN.fullmatch(str(audit.get("expected_component_sha256", ""))) or not str(audit.get("reason", "")).strip():
                raise ItineraryConfigError("La traza de servicio requiere huella de componente y motivo documentado.")
            crossings = audit.get("expected_crossings")
            if not isinstance(crossings, list) or not crossings or any(
                not isinstance(xy, list) or len(xy) != 2 or
                any(isinstance(v, bool) or not isinstance(v, (float, int)) or not np.isfinite(v) for v in xy)
                for xy in crossings
            ):
                raise ItineraryConfigError("La traza de servicio requiere sus autocruces puntuales identificados.")
        if itinerary["definition_mode"] == "official_axis_sequence":
            parts = itinerary.get("axis_parts")
            if not isinstance(parts, list) or not parts:
                raise ItineraryConfigError(
                    f"El itinerario {itinerary_id} requiere axis_parts no vacío."
                )
            for index, part in enumerate(parts):
                part = _require_mapping(part, f"{itinerary_id}.axis_parts[{index}]")
                if part.get("source_id") not in sources:
                    raise ItineraryConfigError(
                        f"Fuente inexistente en {itinerary_id}.axis_parts[{index}]."
                    )
                if not isinstance(part.get("feature_filters"), Mapping) or not part["feature_filters"]:
                    raise ItineraryConfigError(
                        f"{itinerary_id}.axis_parts[{index}] requiere filtros exactos."
                    )
                if not isinstance(part.get("component_index"), int) or part["component_index"] < 0:
                    raise ItineraryConfigError(
                        f"{itinerary_id}.axis_parts[{index}].component_index no es válido."
                    )
                for field in ("clip_start_anchor_id", "clip_end_anchor_id"):
                    if field in part and part[field] not in anchors:
                        raise ItineraryConfigError(f"Anclaje de recorte inexistente en {itinerary_id}: {part[field]}.")
                if ("clip_start_anchor_id" in part) != ("clip_end_anchor_id" in part):
                    raise ItineraryConfigError("El recorte de un componente requiere ambos anclajes.")
                if "wrap_ring" in part and (not isinstance(part["wrap_ring"], bool)
                        or "clip_start_anchor_id" not in part):
                    raise ItineraryConfigError("wrap_ring requiere valor booleano y ambos anclajes de recorte.")
                if not isinstance(part.get("reverse"), bool):
                    raise ItineraryConfigError(
                        f"{itinerary_id}.axis_parts[{index}].reverse debe ser booleano."
                    )
        else:
            if itinerary.get("geometry_source_id") not in sources:
                raise ItineraryConfigError(
                    f"El itinerario {itinerary_id} requiere geometry_source_id válido."
                )

def load_itinerary_config(path: str | Path) -> dict[str, Any]:
    """Load and validate a UTF-8 JSON itinerary catalog."""

    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"No existe la configuración: {config_path}")
    with config_path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    validate_itinerary_config(config)
    return config
