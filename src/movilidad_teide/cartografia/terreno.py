"""cartografia: terreno. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path
from typing import Any
import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS
from rasterio.io import MemoryFile
from rasterio.coords import BoundingBox
from rasterio.windows import Window, from_bounds
from shapely.geometry import LineString, MultiLineString, Point, box
from movilidad_teide.cartografia.geografia_tipos import GeographicDataError


def raster_metadata(path: str | Path) -> dict[str, Any]:
    """Read reproducibility metadata from a single-band DEM."""
    from movilidad_teide.cartografia.geometrias import ensure_metric_crs

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Falta el MDT: {source}")
    with rasterio.open(source) as dataset:
        if dataset.crs is None:
            raise GeographicDataError(f"El MDT {source} no declara CRS.")
        ensure_metric_crs(CRS.from_user_input(dataset.crs))
        if dataset.count < 1:
            raise GeographicDataError(f"El MDT {source} no contiene bandas.")
        return {
            "path": source.as_posix(),
            "driver": dataset.driver,
            "crs": dataset.crs.to_string(),
            "crs_wkt": dataset.crs.to_wkt(),
            "resolution_x_m": abs(float(dataset.res[0])),
            "resolution_y_m": abs(float(dataset.res[1])),
            "width_pixels": int(dataset.width),
            "height_pixels": int(dataset.height),
            "band_count": int(dataset.count),
            "dtype_band_1": dataset.dtypes[0],
            "nodata_band_1": dataset.nodata,
            "unit_band_1": dataset.units[0],
            "description_band_1": dataset.descriptions[0],
            "bounds": tuple(float(value) for value in dataset.bounds),
            "dataset_tags": dataset.tags(),
            "image_structure_tags": dataset.tags(ns="IMAGE_STRUCTURE"),
            "band_1_tags": dataset.tags(1),
        }

def _route_in_raster_crs(
    route: gpd.GeoDataFrame, raster_crs: CRS
) -> LineString:
    if len(route) != 1 or route.crs is None:
        raise GeographicDataError("La ruta debe contener una geometría y un CRS declarado.")
    transformed = route.to_crs(raster_crs)
    geometry = transformed.geometry.iloc[0]
    if not isinstance(geometry, LineString):
        raise GeographicDataError("La ruta transformada debe ser una LineString.")
    return geometry

def _raster_coordinate_crs(
    embedded_crs: rasterio.crs.CRS,
    assumed_raster_crs: str | CRS | None,
) -> CRS:
    """Return the CRS used to interpret raster coordinates without editing the file."""
    from movilidad_teide.cartografia.geometrias import ensure_metric_crs

    if assumed_raster_crs is None:
        return ensure_metric_crs(CRS.from_user_input(embedded_crs))
    return ensure_metric_crs(assumed_raster_crs)

def validate_dem_coverage(
    route: gpd.GeoDataFrame,
    dem_path: str | Path,
    *,
    assumed_raster_crs: str | CRS | None = None,
) -> BoundingBox:
    """Require the DEM bounding box to cover the complete route.

    ``assumed_raster_crs`` changes only how the numerical raster coordinates are
    interpreted for this operation. It does not alter the raster or claim that its
    embedded CRS is wrong; callers must document the supporting hypothesis.
    """

    source = Path(dem_path)
    if not source.is_file():
        raise FileNotFoundError(f"Falta el MDT: {source}")
    with rasterio.open(source) as dataset:
        if dataset.crs is None:
            raise GeographicDataError(f"El MDT {source} no declara CRS.")
        raster_crs = _raster_coordinate_crs(dataset.crs, assumed_raster_crs)
        route_geometry = _route_in_raster_crs(route, raster_crs)
        raster_extent = box(*dataset.bounds)
        if not raster_extent.covers(route_geometry):
            raise GeographicDataError(
                "El rectángulo de cobertura del MDT no contiene todo el trazado. "
                f"Límites del MDT: {tuple(dataset.bounds)}."
            )
        return dataset.bounds

def sample_dem_points(
    points: gpd.GeoDataFrame, dem_path: str | Path, *,
    method: str = "cell", assumed_raster_crs: str | CRS | None = None,
) -> gpd.GeoDataFrame:
    """Read raw cell values or explicitly interpolate four pixel-centre values.

    Inverse GDAL affine gives pixel *corner* coordinates (column, row). Subtract
    0.5 once to obtain centre indices; GDAL has already handled PixelIsPoint.
    Bilinear weights are (1-u)(1-v), u(1-v), (1-u)v, uv. No reprojection/resampling
    of the DEM occurs. All positive-weight contributors must be inside the DEM,
    finite and unmasked; otherwise raise, never renormalize or fall back to cell.
    Zero-weight contributors are irrelevant (including at the outermost centre).
    Weights, indices and raw supporting values are retained for audit.
    """
    if method not in ("cell", "bilinear"):
        raise ValueError("method debe ser 'cell' o 'bilinear'.")
    if points.empty or points.crs is None or not (points.geom_type == "Point").all():
        raise GeographicDataError("Se requieren puntos no vacíos con CRS.")
    rows = []
    with rasterio.open(dem_path) as ds:
        if ds.crs is None:
            raise GeographicDataError("El MDT no declara CRS.")
        if ds.scales[0] != 1 or ds.offsets[0] != 0:
            raise GeographicDataError("Escala/offset de banda no triviales: requieren tratamiento explícito.")
        raster_crs = _raster_coordinate_crs(ds.crs, assumed_raster_crs)
        for station, point in enumerate(points.to_crs(raster_crs).geometry):
            col_corner, row_corner = (~ds.transform) @ (point.x, point.y)
            if (not np.isfinite([col_corner, row_corner]).all()
                    or not (0 <= col_corner < ds.width and 0 <= row_corner < ds.height)):
                raise GeographicDataError(f"Punto {station} fuera del MDT.")
            record = {"pixel_corner_column": col_corner, "pixel_corner_row": row_corner}
            if method == "cell":
                # Retain Rasterio's original containing-cell selection exactly.
                row, col = ds.index(point.x, point.y)
                support = [(row, col, 1.0)]
            else:
                col_center, row_center = col_corner - 0.5, row_corner - 0.5
                col0, row0 = int(np.floor(col_center)), int(np.floor(row_center))
                u, v = col_center-col0, row_center-row0
                support = [(row0, col0, (1-u)*(1-v)), (row0, col0+1, u*(1-v)),
                           (row0+1, col0, (1-u)*v), (row0+1, col0+1, u*v)]
            elevation = 0.0
            for index, (row, col, weight) in enumerate(support):
                value = np.nan
                if weight > 0:
                    if not (0 <= row < ds.height and 0 <= col < ds.width):
                        raise GeographicDataError(f"Soporte {method} fuera del MDT en punto {station}.")
                    raw = ds.read(1, window=Window(col, row, 1, 1), masked=True)[0, 0]
                    if np.ma.is_masked(raw) or not np.isfinite(raw):
                        raise GeographicDataError(f"NoData o no finito en soporte {method}, punto {station}.")
                    value = float(raw)
                    elevation += weight * value
                record.update({f"support_{index}_row": row, f"support_{index}_col": col,
                               f"support_{index}_weight": weight, f"support_{index}_value_m": value})
            record["elevation_m"] = elevation
            record["support_valid_count"] = sum(weight > 0 for _, _, weight in support)
            rows.append(record)
    result = points.copy()
    for name in rows[0]:
        result[name] = [row[name] for row in rows]
    result["elevation_method"] = method
    return result

def convert_wcs_arcgrid_response(response_path, output_path, *, content_type, expected_crs):
    """Conservar cotas/malla de ArcGrid multipart y su PRJ en un GeoTIFF derivado.

    La respuesta original permanece intacta. No reproyectar, interpolar ni sustituir
    el CRS: debe proceder del PRJ y coincidir con el esperado para esa cobertura.
    """
    from movilidad_teide.cartografia.geometrias import ensure_metric_crs
    source, destination = Path(response_path), Path(output_path)
    if destination.exists():
        raise FileExistsError(f"No se sobrescribe el MDT derivado: {destination}")
    message = BytesParser(policy=email_policy).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + source.read_bytes())
    if not message.is_multipart():
        raise GeographicDataError("La respuesta WCS no es multipart.")
    payloads = [part.get_payload(decode=True) for part in message.iter_parts()]
    grids = [value for value in payloads if value and value.lstrip().lower().startswith(b"ncols")]
    projections = [value for value in payloads if value and value.lstrip().startswith((b"PROJCS[", b"PROJCRS["))]
    if len(grids) != 1 or len(projections) != 1:
        raise GeographicDataError("WCS requiere una única malla ArcGrid y un único PRJ.")
    crs = ensure_metric_crs(CRS.from_wkt(projections[0].decode()))
    if crs != CRS.from_user_input(expected_crs):
        raise GeographicDataError("El CRS del PRJ WCS no coincide con la cobertura esperada.")
    with MemoryFile(grids[0], ext=".asc") as memory:
        with memory.open() as dataset:
            if dataset.count != 1:
                raise GeographicDataError("El MDT WCS debe tener una banda.")
            values = dataset.read(1, masked=True)
            if not np.isfinite(values.compressed()).all():
                raise GeographicDataError("La malla WCS contiene cotas válidas no finitas.")
            profile = {"driver": "GTiff", "width": dataset.width, "height": dataset.height,
                       "count": 1, "dtype": dataset.dtypes[0], "crs": crs,
                       "transform": dataset.transform, "nodata": dataset.nodata,
                       "compress": "deflate", "tiled": True}
            data = dataset.read(1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(destination, "w", **profile) as output:
        output.write(data, 1)

def extend_native_dem(base_path, extension_path, output_path):
    """Ampliar un MDT con celdas de la misma malla, preservando toda la base.

    Exige CRS, resolución, tipo y NoData idénticos y alineación exacta de píxel.
    Los solapes válidos deben coincidir exactamente. La extensión nunca rellena
    NoData de la base; no hay reproyección, remuestreo, suavizado o imputación.
    """
    from movilidad_teide.cartografia.geometrias import ensure_metric_crs
    from movilidad_teide.trazabilidad import file_sha256
    import shutil
    import tempfile
    from rasterio import Affine
    base_path, extension_path, output_path = map(Path,[base_path,extension_path,output_path])
    if output_path.exists() or output_path.resolve() in {base_path.resolve(),extension_path.resolve()}:
        raise GeographicDataError('La ampliación necesita un destino nuevo; no sobrescribe entradas.')
    with rasterio.open(base_path) as base, rasterio.open(extension_path) as extra:
        if (base.crs is None or base.crs!=extra.crs or base.res!=extra.res or base.dtypes!=extra.dtypes
                or base.count!=1 or extra.count!=1
                or not (base.nodata==extra.nodata or (base.nodata is not None and extra.nodata is not None
                        and np.isnan(base.nodata) and np.isnan(extra.nodata)))
                or (base.nodata is not None and np.isinf(base.nodata))
                or any(ds.transform.b!=0 or ds.transform.d!=0 or ds.transform.a<=0 or ds.transform.e>=0
                       or ds.scales!=(1.0,) or ds.offsets!=(0.0,) for ds in [base,extra])):
            raise GeographicDataError('Los MDT nativos no comparten CRS, malla, tipo, NoData o escala.')
        ensure_metric_crs(base.crs)
        col=(extra.transform.c-base.transform.c)/base.transform.a
        row=(extra.transform.f-base.transform.f)/base.transform.e
        if not float(col).is_integer() or not float(row).is_integer():
            raise GeographicDataError('Los MDT no están alineados exactamente en la misma malla.')
        col,row=int(col),int(row)
        left,top=max(0,col),max(0,row);right,bottom=min(base.width,col+extra.width),min(base.height,row+extra.height)
        if right<=left or bottom<=top:
            raise GeographicDataError('La ampliación necesita solape para comprobar sus celdas.')
        a=base.read(1,window=Window(left,top,right-left,bottom-top),masked=True)
        b=extra.read(1,window=Window(left-col,top-row,right-left,bottom-top),masked=True)
        valid=~np.ma.getmaskarray(a)&~np.ma.getmaskarray(b)
        if not valid.any() or not np.array_equal(a.data[valid],b.data[valid]):
            raise GeographicDataError('Las cotas válidas del solape no coinciden exactamente.')
        c0,r0=min(0,col),min(0,row);c1,r1=max(base.width,col+extra.width),max(base.height,row+extra.height)
        if base.nodata is None and np.dtype(base.dtypes[0]).kind!='f':
            raise GeographicDataError('Un MDT entero sin NoData necesita una convención explícita para huecos nuevos.')
        # Los originales sin NoData son completos; solo los huecos nuevos se marcan como NaN.
        output_nodata=np.nan if base.nodata is None else base.nodata
        profile=base.profile.copy();profile.update(driver='GTiff',width=c1-c0,height=r1-r0,nodata=output_nodata,
            transform=base.transform @ Affine.translation(c0,r0),compress='deflate')
        with tempfile.TemporaryDirectory(prefix='teide_mdt_nativo_') as tmp:
            tmp_path=Path(tmp)/'ampliado.tif'
            with rasterio.open(tmp_path,'w',**profile) as dst:
                # Los huecos de la envolvente siguen siendo NoData, nunca terreno inventado.
                for _,w in dst.block_windows(1):
                    dst.write(np.full((int(w.height),int(w.width)),output_nodata,dtype=base.dtypes[0]),1,window=w)
                # Escribir la base al final conserva incluso sus NoData originales en el solape.
                for ds,dc,dr in [(extra,col-c0,row-r0),(base,-c0,-r0)]:
                    for _,w in ds.block_windows(1):
                        dst.write(ds.read(1,window=w),1,window=Window(w.col_off+dc,w.row_off+dr,w.width,w.height))
            with rasterio.open(tmp_path) as dst:
                for _,w in base.block_windows(1):
                    # Comparar bytes conserva también los NaN originales, sin rellenarlos.
                    if base.read(1,window=w).tobytes()!=dst.read(1,window=Window(w.col_off-c0,w.row_off-r0,w.width,w.height)).tobytes():
                        raise GeographicDataError('La ampliación no conserva íntegramente las celdas de la base.')
            output_path.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(tmp_path,output_path)
        return {'base_sha256':file_sha256(base_path),'extension_sha256':file_sha256(extension_path),
            'output_sha256':file_sha256(output_path),'base_cells_preserved':base.width*base.height,
            'overlap_valid_cells':int(valid.sum()),'overlap_max_abs_m':0.0,
            'base_nodata_not_filled':int((np.ma.getmaskarray(a)&~np.ma.getmaskarray(b)).sum()),
            'pixel_shifts_column_row':[col,row],'output_shape':[r1-r0,c1-c0],
            'new_gap_nodata':'NaN' if base.nodata is None or np.isnan(base.nodata) else float(base.nodata),
            'method':'Copiar celdas nativas alineadas; base prioritaria incluso en NoData. Sin remuestreo o relleno.'}
