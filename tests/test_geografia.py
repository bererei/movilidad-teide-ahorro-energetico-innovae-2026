"""Pruebas sintéticas de los cálculos geográficos; no representan la TF-21."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import rasterio
from geopandas import GeoDataFrame
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point

from movilidad_teide.geografia import (
    GeographicDataError,
    convert_wcs_arcgrid_response,
    calculate_segments,
    classify_slopes,
    extreme_slope_table,
    load_route,
    make_sampling_distances,
    reverse_profile,
    reverse_segments,
    sample_elevation_profile,
    slope_distribution,
    validate_length_conservation,
)


def synthetic_profile() -> pd.DataFrame:
    """Return a deliberately small, synthetic elevation profile."""

    return pd.DataFrame(
        {
            "distance_m": [0.0, 100.0, 300.0],
            "elevation_m": [1_000.0, 1_004.0, 998.0],
        }
    )


def test_sampling_distances_include_exact_route_end() -> None:
    distances = make_sampling_distances(450.0, 200.0)

    np.testing.assert_allclose(distances, [0.0, 200.0, 400.0, 450.0])


def test_calculate_segments_uses_along_route_station_lengths() -> None:
    segments = calculate_segments(synthetic_profile())

    np.testing.assert_allclose(segments["length_m"], [100.0, 200.0])
    np.testing.assert_allclose(segments["elevation_change_m"], [4.0, -6.0])
    np.testing.assert_allclose(segments["slope_pct"], [4.0, -3.0])
    assert validate_length_conservation(300.0, segments) == pytest.approx(0.0)


def test_reverse_segments_reverses_order_elevations_and_slope_sign() -> None:
    segments = calculate_segments(synthetic_profile())
    reversed_segments = reverse_segments(segments)

    np.testing.assert_allclose(reversed_segments["length_m"], [200.0, 100.0])
    np.testing.assert_allclose(reversed_segments["distance_end_m"], [200.0, 300.0])
    np.testing.assert_allclose(reversed_segments["elevation_start_m"], [998.0, 1_004.0])
    np.testing.assert_allclose(reversed_segments["elevation_end_m"], [1_004.0, 1_000.0])
    np.testing.assert_allclose(reversed_segments["slope_pct"], [3.0, -4.0])


def test_classification_does_not_clip_out_of_range_slopes() -> None:
    segments = pd.DataFrame(
        {
            "slope_pct": [-6.1, -5.0, -0.9, 5.0, 6.1],
            "length_m": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )
    classified = classify_slopes(segments)

    assert classified["classification_status"].tolist() == [
        "below_minimum",
        "classified",
        "classified",
        "classified",
        "above_maximum",
    ]
    assert classified["slope_class_pct"].tolist() == [
        pd.NA,
        -6.0,
        0.0,
        4.0,
        pd.NA,
    ]
    assert classified["requires_methodological_treatment"].tolist() == [
        True,
        False,
        False,
        False,
        True,
    ]


def test_distribution_preserves_total_length_including_unclassified() -> None:
    segments = pd.DataFrame(
        {"slope_pct": [-8.0, -2.1, 1.2, 7.0], "length_m": [10.0, 20.0, 30.0, 40.0]}
    )
    distribution = slope_distribution(classify_slopes(segments), "ascendente")

    assert distribution["length_m"].sum() == pytest.approx(100.0)
    assert distribution.loc[
        distribution["classification_status"] == "below_minimum", "length_m"
    ].item() == pytest.approx(10.0)
    assert distribution.loc[
        distribution["classification_status"] == "above_maximum", "length_m"
    ].item() == pytest.approx(40.0)


def test_sample_elevation_profile_reads_synthetic_raster(tmp_path) -> None:
    """Exercise CRS, coverage, final station and raster sampling together."""

    dem_path = tmp_path / "synthetic_dem.tif"
    elevations = np.arange(100, dtype=np.float32).reshape(10, 10)
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs="EPSG:4083",
        transform=from_origin(0.0, 100.0, 10.0, 10.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevations, 1)

    route = GeoDataFrame(
        {"route_id": ["synthetic"], "geometry": [LineString([(5.0, 95.0), (95.0, 5.0)])]},
        crs="EPSG:4083",
    )
    profile = sample_elevation_profile(route, dem_path, interval_m=40.0)

    assert profile["distance_m"].iloc[0] == pytest.approx(0.0)
    assert profile["distance_m"].iloc[-1] == pytest.approx(route.geometry.iloc[0].length)
    assert np.isfinite(profile["elevation_m"]).all()


def test_sample_elevation_profile_can_use_documented_assumed_raster_crs(tmp_path) -> None:
    """An explicit CRS assumption affects interpretation but never edits the raster."""

    dem_path = tmp_path / "mislabeled_dem.tif"
    elevations = np.arange(100, dtype=np.float32).reshape(10, 10)
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(300_000.0, 3_100_100.0, 10.0, 10.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevations, 1)

    route = GeoDataFrame(
        {
            "route_id": ["synthetic"],
            "geometry": [
                LineString([(300_005.0, 3_100_095.0), (300_095.0, 3_100_005.0)])
            ],
        },
        crs="EPSG:4083",
    )

    with pytest.raises(GeographicDataError, match="no contiene todo el trazado"):
        sample_elevation_profile(route, dem_path, interval_m=40.0)

    profile = sample_elevation_profile(
        route,
        dem_path,
        interval_m=40.0,
        assumed_raster_crs="EPSG:4083",
    )

    assert np.isfinite(profile["elevation_m"]).all()
    with rasterio.open(dem_path) as dataset:
        assert dataset.crs.to_epsg() == 3857


def test_reverse_profile_matches_reversed_segments() -> None:
    profile = GeoDataFrame(
        {
            "sample_id": [0, 1, 2],
            "distance_m": [0.0, 100.0, 300.0],
            "elevation_m": [1_000.0, 1_004.0, 998.0],
            "geometry": [Point(0.0, 0.0), Point(100.0, 0.0), Point(300.0, 0.0)],
        },
        crs="EPSG:4083",
    )

    reversed_profile = reverse_profile(profile)
    recalculated = calculate_segments(reversed_profile)
    expected = reverse_segments(calculate_segments(profile))

    np.testing.assert_allclose(reversed_profile["distance_m"], [0.0, 200.0, 300.0])
    np.testing.assert_allclose(recalculated["length_m"], expected["length_m"])
    np.testing.assert_allclose(recalculated["slope_pct"], expected["slope_pct"])


def test_extreme_slope_table_preserves_values_and_flags_only_threshold_excesses() -> None:
    segments = calculate_segments(synthetic_profile())

    extremes = extreme_slope_table(
        segments,
        top_n=2,
        anomalous_absolute_slope_pct=3.5,
    )

    assert extremes["segment_id"].tolist() == [1, 2]
    np.testing.assert_allclose(extremes["slope_pct"], [4.0, -3.0])
    assert extremes["exceeds_alert_threshold"].tolist() == [True, False]


def test_load_route_preserves_declared_direction_and_projects(tmp_path) -> None:
    route_path = tmp_path / "synthetic_route.geojson"
    source = GeoDataFrame(
        {"name": ["synthetic"], "geometry": [LineString([(-16.5, 28.3), (-16.49, 28.31)])]},
        crs="EPSG:4326",
    )
    source.to_file(route_path, driver="GeoJSON")

    route = load_route(route_path)

    assert route.crs.to_epsg() == 4083
    assert route.attrs["source_crs"] == "EPSG:4326"
    assert route.geometry.iloc[0].coords[0][1] < route.geometry.iloc[0].coords[-1][1]


def multipart_mdt(tmp_path, with_prj=True):
    from pyproj import CRS
    asc = b"ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 5\n1.125 2.25\n3.5 4.75\n"
    parts = [asc]
    if with_prj:
        parts.append(CRS.from_epsg(4083).to_wkt().encode())
    body = b"".join(b"--demo\r\nContent-Type: application/octet-stream\r\n\r\n" + value + b"\r\n" for value in parts) + b"--demo--\r\n"
    source = tmp_path / "respuesta.multipart"
    source.write_bytes(body)
    return source, body


def test_wcs_conversion_preserves_decimal_values_grid_and_original(tmp_path):
    source, original = multipart_mdt(tmp_path)
    output = tmp_path / "derivado.tif"
    convert_wcs_arcgrid_response(source, output, content_type="multipart/related; boundary=demo", expected_crs=4083)
    with rasterio.open(output) as dataset:
        np.testing.assert_array_equal(dataset.read(1), [[1.125, 2.25], [3.5, 4.75]])
        assert dataset.crs.to_epsg() == 4083
        assert dataset.transform == from_origin(0, 10, 5, 5)
    assert source.read_bytes() == original
    with pytest.raises(FileExistsError):
        convert_wcs_arcgrid_response(source, output, content_type="multipart/related; boundary=demo", expected_crs=4083)


def test_wcs_conversion_rejects_missing_prj_without_inventing_crs(tmp_path):
    source, _ = multipart_mdt(tmp_path, with_prj=False)
    output = tmp_path / "derivado.tif"
    with pytest.raises(GeographicDataError, match="PRJ"):
        convert_wcs_arcgrid_response(source, output, content_type="multipart/related; boundary=demo", expected_crs=4083)
    assert not output.exists()


def test_wcs_conversion_rejects_different_native_crs(tmp_path):
    source, _ = multipart_mdt(tmp_path)
    output = tmp_path / "derivado.tif"
    with pytest.raises(GeographicDataError, match="CRS"):
        convert_wcs_arcgrid_response(source, output, content_type="multipart/related; boundary=demo", expected_crs=25828)
    assert not output.exists()


def profiles_with_different_accesses():
    """Accesos de 100/200 m y un tramo compartido de 400 m; ejemplo sintético."""
    forward = GeoDataFrame({'distance_m':[0.,100.,300.,500.], 'elevation_m':[0.,100.,120.,140.],
        'geometry':[Point(-100,0),Point(0,0),Point(0,200),Point(0,400)]},crs=4083)
    backward = GeoDataFrame({'distance_m':[0.,200.,400.,600.], 'elevation_m':[140.,120.,100.,0.],
        'geometry':[Point(0,400),Point(0,200),Point(0,0),Point(-200,0)]},crs=4083)
    return forward, backward, calculate_segments(forward), calculate_segments(backward), LineString([(0,0),(0,400)])


def test_shared_profiles_compare_physical_locations_with_different_access_lengths():
    from movilidad_teide.geografia import compare_shared_direction_profiles
    f,b,fs,bs,axis=profiles_with_different_accesses();originals=[x.copy(deep=True) for x in [f,b,fs,bs]]
    points,slopes=compare_shared_direction_profiles(f,b,fs,bs,axis,200)
    assert points.station_m.tolist()==[0,200,400] and len(slopes)==2
    np.testing.assert_allclose(slopes.forward_slope_pct,[10,10])
    np.testing.assert_allclose(slopes.backward_slope_pct,[-10,-10])
    for result,original in zip([f,b,fs,bs],originals):pd.testing.assert_frame_equal(result,original)


@pytest.mark.parametrize('problem',['cota','pendiente','otra_ubicacion','fase','mismo_sentido','cantidad_tramos','no_finito'])
def test_shared_profiles_reject_incoherent_directions_without_changing_samples(problem):
    from movilidad_teide.geografia import compare_shared_direction_profiles
    f,b,fs,bs,axis=profiles_with_different_accesses()
    if problem=='cota':b.loc[1,'elevation_m']+=1
    elif problem=='pendiente':bs.loc[0,'slope_pct']+=1
    elif problem=='otra_ubicacion':b.geometry=b.geometry.translate(xoff=100)
    elif problem=='fase':b.loc[1,'geometry']=Point(0,180)
    elif problem=='mismo_sentido':b=f.copy();bs=fs.copy()
    elif problem=='cantidad_tramos':bs=bs.iloc[:-1].copy()
    else:bs.loc[0,'slope_pct']=np.nan
    with pytest.raises(GeographicDataError):compare_shared_direction_profiles(f,b,fs,bs,axis,200)


def escribir_mdt_nativo_prueba(path,values,transform,*,nodata=-9999.,crs='EPSG:4083',scale=1.):
    values=np.asarray(values,dtype='float32')
    with rasterio.open(path,'w',driver='GTiff',height=values.shape[0],width=values.shape[1],
            count=1,dtype='float32',crs=crs,transform=transform,nodata=nodata) as ds:
        ds.write(values,1);ds.scales=(scale,)


def par_mdt_nativo_prueba(tmp_path,nodata=-9999.):
    base=tmp_path/'base.tif';extra=tmp_path/'extra.tif'
    escribir_mdt_nativo_prueba(base,[[100,101,102],[103,104,105],[106,107,108]],from_origin(0,3,1,1),nodata=nodata)
    escribir_mdt_nativo_prueba(extra,[[201,103,104],[202,106,107],[203,204,205]],from_origin(-1,2,1,1),nodata=nodata)
    return base,extra,tmp_path/'ampliado.tif'


def test_ampliacion_nativa_preserva_celdas_y_no_modifica_entradas(tmp_path):
    from movilidad_teide.geografia import extend_native_dem,file_sha256
    base,extra,out=par_mdt_nativo_prueba(tmp_path);antes=[file_sha256(p) for p in [base,extra]]
    meta=extend_native_dem(base,extra,out)
    with rasterio.open(out) as ds:
        expected=np.array([[-9999,100,101,102],[201,103,104,105],[202,106,107,108],[203,204,205,-9999]],dtype='float32')
        assert np.array_equal(ds.read(1),expected) and ds.res==(1,1) and ds.crs.to_epsg()==4083
    assert meta['base_cells_preserved']==9 and meta['overlap_valid_cells']==4 and meta['overlap_max_abs_m']==0
    assert antes==[file_sha256(p) for p in [base,extra]]


def test_ampliacion_no_rellena_nodata_de_la_base(tmp_path):
    from movilidad_teide.geografia import extend_native_dem
    base,extra,out=par_mdt_nativo_prueba(tmp_path)
    with rasterio.open(base,'r+') as ds:
        a=ds.read(1);a[1,0]=-9999;ds.write(a,1)
    with rasterio.open(extra,'r+') as ds:
        a=ds.read(1);a[0,1]=777;ds.write(a,1)
    meta=extend_native_dem(base,extra,out)
    with rasterio.open(out) as ds:assert ds.read(1)[1,1]==-9999
    assert meta['base_nodata_not_filled']==1 and meta['overlap_valid_cells']==3


def test_ampliacion_sin_nodata_original_marca_solo_huecos_nuevos(tmp_path):
    from movilidad_teide.geografia import extend_native_dem
    base,extra,out=par_mdt_nativo_prueba(tmp_path,nodata=None);meta=extend_native_dem(base,extra,out)
    with rasterio.open(out) as ds:
        a=ds.read(1,masked=True)
        assert np.isnan(ds.nodata) and np.ma.getmaskarray(a).sum()==2
        assert np.array_equal(a.data[:3,1:],np.array([[100,101,102],[103,104,105],[106,107,108]],dtype='float32'))
    assert meta['new_gap_nodata']=='NaN'


@pytest.mark.parametrize('defecto',['crs','malla','cota','sin_solape','escala'])
def test_ampliacion_rechaza_fuentes_incompatibles_sin_remuestrear(tmp_path,defecto):
    from movilidad_teide.geografia import extend_native_dem
    base,extra,out=par_mdt_nativo_prueba(tmp_path)
    if defecto=='crs':
        with rasterio.open(extra,'r+') as ds:ds.crs='EPSG:32628'
    elif defecto=='malla':
        with rasterio.open(extra,'r+') as ds:ds.transform=from_origin(-.5,2,1,1)
    elif defecto=='cota':
        with rasterio.open(extra,'r+') as ds:a=ds.read(1);a[0,1]+=1;ds.write(a,1)
    elif defecto=='sin_solape':
        with rasterio.open(extra,'r+') as ds:ds.transform=from_origin(10,2,1,1)
    else:
        with rasterio.open(extra,'r+') as ds:ds.scales=(2.,)
    with pytest.raises(GeographicDataError):extend_native_dem(base,extra,out)
    assert not out.exists()


def test_ampliacion_no_sobrescribe_destino_existente(tmp_path):
    from movilidad_teide.geografia import extend_native_dem
    base,extra,out=par_mdt_nativo_prueba(tmp_path);out.write_bytes(b'conservar')
    with pytest.raises(GeographicDataError):extend_native_dem(base,extra,out)
    assert out.read_bytes()==b'conservar'


def test_ampliacion_nan_preserva_bytes_y_hueco_original(tmp_path):
    from movilidad_teide.geografia import extend_native_dem, file_sha256
    base, extra, out = par_mdt_nativo_prueba(tmp_path, nodata=np.nan)
    # Un valor nuevo no puede rellenar una ausencia original del MDT base.
    with rasterio.open(base, 'r+') as ds:
        values = ds.read(1); values[1, 0] = np.nan; ds.write(values, 1)
    with rasterio.open(extra, 'r+') as ds:
        values = ds.read(1); values[0, 1] = 777.; ds.write(values, 1)
    before = [file_sha256(p) for p in [base, extra]]
    meta = extend_native_dem(base, extra, out)
    with rasterio.open(base) as a, rasterio.open(out) as b:
        assert np.isnan(b.nodata)
        assert a.read(1).tobytes() == b.read(1)[:3, 1:].tobytes()
        assert np.isnan(b.read(1)[1, 1])
    assert meta['overlap_valid_cells'] == 3 and meta['base_nodata_not_filled'] == 1
    assert meta['new_gap_nodata'] == 'NaN'
    assert before == [file_sha256(p) for p in [base, extra]]


@pytest.mark.parametrize('nodata_extra', [None, -9999., np.inf, -np.inf])
def test_ampliacion_nan_rechaza_convenciones_distintas(tmp_path, nodata_extra):
    from movilidad_teide.geografia import extend_native_dem
    base, extra, out = par_mdt_nativo_prueba(tmp_path, nodata=np.nan)
    with rasterio.open(extra, 'r+') as ds:
        ds.nodata = nodata_extra
    with pytest.raises(GeographicDataError):
        extend_native_dem(base, extra, out)
    assert not out.exists()


@pytest.mark.parametrize('nodata', [np.inf, -np.inf])
def test_ampliacion_rechaza_nodata_infinito_aunque_coincida(tmp_path, nodata):
    from movilidad_teide.geografia import extend_native_dem
    base, extra, out = par_mdt_nativo_prueba(tmp_path, nodata=nodata)
    with pytest.raises(GeographicDataError):
        extend_native_dem(base, extra, out)
    assert not out.exists()


def test_ampliacion_nan_rechaza_cambio_de_cota_valida(tmp_path):
    from movilidad_teide.geografia import extend_native_dem
    base, extra, out = par_mdt_nativo_prueba(tmp_path, nodata=np.nan)
    with rasterio.open(extra, 'r+') as ds:
        values = ds.read(1); values[0, 1] += 1.; ds.write(values, 1)
    with pytest.raises(GeographicDataError):
        extend_native_dem(base, extra, out)
    assert not out.exists()
