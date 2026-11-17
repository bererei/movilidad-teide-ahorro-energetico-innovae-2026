"""cartografia: mapas. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from pyproj import CRS
from rasterio.windows import bounds as window_bounds
from rasterio.windows import Window, from_bounds
from movilidad_teide.cartografia.geografia_tipos import GeographicDataError


def plot_sampling_comparison(
    results: dict[float | str, dict[str, Any]],
    reference_pct: float = 6.0,
) -> dict[str, Figure]:
    """Compare unchanged elevations, step slopes and signed distance-weighted bins."""

    colors = ("#1764ab", "#d55e00", "#16803c", "#843c99")
    elevation_fig, elevation_ax = plt.subplots(figsize=(11, 5))
    slope_fig, slope_axes = plt.subplots(len(results), 1, figsize=(11, 3*len(results)), sharex=True, sharey=True, squeeze=False)
    distribution_fig, distribution_axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for index, (interval, result) in enumerate(results.items()):
        color = colors[index % len(colors)]
        label = result["label"] if "label" in result else f"{interval:g} m"
        forward = result["directions"]["PK creciente"]
        points, segments = forward["profile"], forward["segments"]
        elevation_ax.plot(points.distance_m/1000, points.elevation_m, label=label, color=color, linewidth=1.3, alpha=0.85)
        axis = slope_axes[index, 0]
        edges = np.r_[segments.distance_start_m.to_numpy(), segments.distance_end_m.iloc[-1]]/1000
        axis.stairs(segments.slope_pct, edges, baseline=None, color=color, label="PK creciente")
        axis.stairs(-segments.slope_pct, edges, baseline=None, color=color, linestyle="--", alpha=0.7, label="PK decreciente, eje común")
        axis.axhline(0, color="grey", linewidth=0.5)
        for threshold in (-reference_pct, reference_pct):
            axis.axhline(threshold, color="grey", linewidth=0.8, linestyle=":")
        axis.set(title=f"{label} — PROVISIONAL", ylabel="Pendiente [%]")
        axis.grid(alpha=0.2)
        axis.legend(loc="center right", fontsize=8)
        for direction, dax in zip(("PK creciente", "PK decreciente"), distribution_axes, strict=True):
            table = result["distribution"].loc[lambda t: t.direction == direction]
            x = np.arange(len(table))
            width = 0.8/len(results)
            dax.bar(x+(index-(len(results)-1)/2)*width, table.length_km, width=width, label=label, color=color)
            dax.set(title=f"{direction} — PROVISIONAL", ylabel="Longitud [km]")
            dax.set_xticks(x, table.slope_interval_pct, rotation=35, ha="right")
            dax.legend()
    elevation_ax.set(title="TF-21 PK 16–32 — sensibilidad altimétrica PROVISIONAL", xlabel="Distancia desde PK 16 [km]", ylabel="Elevación MDT [m]")
    elevation_ax.grid(alpha=0.2)
    elevation_ax.legend()
    slope_axes[-1, 0].set_xlabel("Distancia desde PK 16 [km]; ambos sentidos sobre el mismo eje físico")
    distribution_axes[-1].set_xlabel("Intervalos descriptivos de pendiente [%], no clases COPERT")
    for figure in (elevation_fig, slope_fig, distribution_fig):
        figure.tight_layout()
    return {"01_elevaciones_comparadas": elevation_fig,
            "02_pendientes_comparadas": slope_fig,
            "03_distribucion_descriptiva": distribution_fig}

def plot_route(
    route: gpd.GeoDataFrame,
    profile: gpd.GeoDataFrame | None = None,
) -> tuple[Figure, Axes]:
    """Plot the route and optional sample points in its projected CRS."""

    figure, axis = plt.subplots(figsize=(8, 8))
    route.plot(ax=axis, color="#1f5f99", linewidth=2.2, label="TF-21")
    if profile is not None:
        profile.plot(ax=axis, color="#d97706", markersize=10, label="Muestras")
        first = profile.geometry.iloc[0]
        last = profile.geometry.iloc[-1]
        axis.scatter([first.x], [first.y], color="#198754", s=55, zorder=3, label="Inicio")
        axis.scatter([last.x], [last.y], color="#b42318", s=55, zorder=3, label="Fin")
    axis.set_title("Itinerario y puntos de muestreo")
    axis.set_xlabel("Este [m]")
    axis.set_ylabel("Norte [m]")
    axis.set_aspect("equal")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    return figure, axis


def plot_route_on_dem(
    route: gpd.GeoDataFrame,
    dem_path: str | Path,
    profile: gpd.GeoDataFrame | None = None,
    *,
    assumed_raster_crs: str | CRS | None = None,
    padding_m: float = 500.0,
    route_color: str = "#8b0000",
) -> tuple[Figure, Axes]:
    """Plot a route and optional samples over the local DEM values."""
    from movilidad_teide.cartografia.terreno import _raster_coordinate_crs
    from movilidad_teide.cartografia.terreno import validate_dem_coverage

    if len(route) != 1 or route.crs is None:
        raise GeographicDataError("La ruta debe contener una geometría y un CRS declarado.")
    if padding_m < 0:
        raise ValueError("padding_m no puede ser negativo.")

    source = Path(dem_path)
    if not source.is_file():
        raise FileNotFoundError(f"Falta el MDT: {source}")
    validate_dem_coverage(
        route,
        source,
        assumed_raster_crs=assumed_raster_crs,
    )

    with rasterio.open(source) as dataset:
        if dataset.crs is None:
            raise GeographicDataError(f"El MDT {source} no declara CRS.")
        raster_crs = _raster_coordinate_crs(dataset.crs, assumed_raster_crs)
        route_in_dem = route.to_crs(raster_crs)
        profile_in_dem = profile.to_crs(raster_crs) if profile is not None else None
        minx, miny, maxx, maxy = route_in_dem.total_bounds
        left = max(float(dataset.bounds.left), float(minx - padding_m))
        bottom = max(float(dataset.bounds.bottom), float(miny - padding_m))
        right = min(float(dataset.bounds.right), float(maxx + padding_m))
        top = min(float(dataset.bounds.top), float(maxy + padding_m))
        window = from_bounds(left, bottom, right, top, dataset.transform)
        # Read full native pixels; do not stretch a fractional window to rounded
        # array dimensions when reviewing alignment with the official axis.
        col0, row0 = int(np.floor(window.col_off)), int(np.floor(window.row_off))
        col1 = min(dataset.width, int(np.ceil(window.col_off + window.width)))
        row1 = min(dataset.height, int(np.ceil(window.row_off + window.height)))
        window = Window(col0, row0, col1-col0, row1-row0)
        elevation = dataset.read(1, window=window, masked=True)
        image_left, image_bottom, image_right, image_top = window_bounds(
            window, dataset.transform
        )

    figure, axis = plt.subplots(figsize=(8, 8))
    image = axis.imshow(
        elevation,
        extent=(image_left, image_right, image_bottom, image_top),
        origin="upper",
        cmap="terrain",
        interpolation="nearest",
    )
    route_in_dem.plot(ax=axis, color=route_color, linewidth=2.2, label="Itinerario")
    if profile_in_dem is not None:
        profile_in_dem.plot(
            ax=axis,
            color="#111827",
            markersize=9,
            label="Muestras",
        )
        first = profile_in_dem.geometry.iloc[0]
        last = profile_in_dem.geometry.iloc[-1]
        axis.scatter([first.x], [first.y], color="#198754", s=55, zorder=3, label="Inicio")
        axis.scatter([last.x], [last.y], color="#b42318", s=55, zorder=3, label="Fin")
    colorbar = figure.colorbar(image, ax=axis, shrink=0.75)
    colorbar.set_label("Elevación MDT [m]")
    axis.set_title("Itinerario y muestras sobre el MDT")
    axis.set_xlabel("Este [m]")
    axis.set_ylabel("Norte [m]")
    axis.set_aspect("equal")
    axis.legend()
    figure.tight_layout()
    return figure, axis

def plot_elevation_profile(profile: pd.DataFrame) -> tuple[Figure, Axes]:
    """Plot elevation against accumulated route distance."""

    figure, axis = plt.subplots(figsize=(11, 4.5))
    distance_km = profile["distance_m"] / 1_000.0
    axis.plot(distance_km, profile["elevation_m"], color="#1f5f99", linewidth=2)
    axis.fill_between(distance_km, profile["elevation_m"], alpha=0.15, color="#1f5f99")
    axis.set(title="Perfil altimétrico", xlabel="Distancia acumulada [km]", ylabel="Elevación [m]")
    axis.grid(alpha=0.3)
    figure.tight_layout()
    return figure, axis

def plot_segment_slopes(
    segments: pd.DataFrame,
    class_limit_pct: float = 6.0,
) -> tuple[Figure, Axes]:
    """Plot segment slope and show a configurable reference threshold without clipping."""

    figure, axis = plt.subplots(figsize=(11, 4.5))
    midpoint_km = (
        (segments["distance_start_m"] + segments["distance_end_m"]) / 2_000.0
    )
    colors = np.where(segments["slope_pct"] >= 0, "#b42318", "#1f5f99")
    axis.bar(midpoint_km, segments["slope_pct"], width=segments["length_m"] / 1_000.0, color=colors)
    axis.axhline(0, color="black", linewidth=0.8)
    axis.axhline(class_limit_pct, color="#d97706", linestyle="--", label="Umbral de revisión")
    axis.axhline(-class_limit_pct, color="#d97706", linestyle="--")
    axis.set(title="Pendiente longitudinal por tramo", xlabel="Distancia acumulada [km]", ylabel="Pendiente [%]")
    axis.grid(axis="y", alpha=0.3)
    axis.legend()
    figure.tight_layout()
    return figure, axis

def plot_slope_distribution(distribution: pd.DataFrame) -> tuple[Figure, Axes]:
    """Plot classified kilometres for one direction; out-of-range rows stay separate."""

    classified = distribution[distribution["classification_status"] == "classified"]
    figure, axis = plt.subplots(figsize=(9, 4.5))
    labels = [f"{value:+g} %" for value in classified["slope_class_pct"]]
    axis.bar(labels, classified["length_km"], color="#4b7f52")
    axis.set(title="Kilómetros por clase preliminar de pendiente", xlabel="Clase", ylabel="Longitud [km]")
    axis.grid(axis="y", alpha=0.3)
    figure.tight_layout()
    return figure, axis
