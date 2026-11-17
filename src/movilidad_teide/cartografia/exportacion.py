"""cartografia: exportacion. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping, Sequence
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from movilidad_teide.cartografia.itinerarios_tipos import ItineraryExtractionResult


def plot_itinerary_validation(
    result: ItineraryExtractionResult,
) -> tuple[Figure, Axes]:
    """Plot source components, extracted route, official PKs and endpoint anchors."""

    itinerary_id = result.route["itinerary_id"].iloc[0]
    figure, axis = plt.subplots(figsize=(9, 9))
    result.lineage.plot(
        ax=axis,
        color="#a7a7a7",
        linewidth=5,
        label="Componentes oficiales seleccionados",
    )
    result.route.plot(ax=axis, color="#175cd3", linewidth=2.2, label="Itinerario recortado")
    if not result.validation_points.empty:
        result.validation_points.plot(
            ax=axis, color="#d97706", markersize=20, label="PK oficiales"
        )
        for row in result.validation_points.itertuples():
            axis.annotate(
                str(row.pk_numero),
                (row.geometry.x, row.geometry.y),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=7,
            )
    colors = {"origin": "#198754", "waypoint": "#7a5af8", "destination": "#b42318"}
    role_labels = {
        "origin": "Origen",
        "waypoint": "Punto intermedio",
        "destination": "Destino",
    }
    for role, group in result.anchors.groupby("anchor_role", sort=False):
        group.plot(
            ax=axis,
            color=colors[role],
            edgecolor="white",
            markersize=90,
            zorder=5,
            label=role_labels[role],
        )
    axis.set_title(f"Validación del itinerario {itinerary_id}")
    axis.set_xlabel("Este [m] — REGCAN95 / UTM 28N")
    axis.set_ylabel("Norte [m] — REGCAN95 / UTM 28N")
    axis.set_aspect("equal")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    return figure, axis

def export_itinerary_result(
    result: ItineraryExtractionResult,
    silver_root: str | Path,
    figure_root: str | Path,
) -> list[Path]:
    """Export one provisional result to silver and its validation map to outputs."""

    itinerary_id = result.route["itinerary_id"].iloc[0]
    output_dir = Path(silver_root) / itinerary_id
    map_dir = Path(figure_root) / itinerary_id
    output_dir.mkdir(parents=True, exist_ok=True)
    map_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        output_dir / "trazado.parquet": result.route,
        output_dir / "anclajes.parquet": result.anchors,
        output_dir / "componentes_origen.parquet": result.lineage,
        output_dir / "puntos_kilometricos_validacion.parquet": result.validation_points,
        output_dir / "validaciones.parquet": result.validations,
        output_dir / "operaciones.parquet": result.operations,
        output_dir / "fuentes.parquet": result.sources,
    }
    exported: list[Path] = []
    for path, table in outputs.items():
        table.to_parquet(path, index=False)
        exported.append(path)

    figure, _ = plot_itinerary_validation(result)
    map_path = map_dir / "mapa_validacion.png"
    figure.savefig(map_path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    exported.append(map_path)
    return exported

def export_configured_itineraries(
    results: Mapping[str, ItineraryExtractionResult],
    silver_root: str | Path,
    figure_root: str | Path,
) -> list[Path]:
    """Export a batch of itinerary results with the same table contract."""

    exported: list[Path] = []
    for result in results.values():
        exported.extend(export_itinerary_result(result, silver_root, figure_root))
    return exported
