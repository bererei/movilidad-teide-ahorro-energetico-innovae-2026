"""Aislar el efecto de la pendiente sin alterar demanda, operación o consumo con proyecto."""
from pathlib import Path
import json
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from movilidad_teide.configuracion.ordenacion import leer_ordenacion
from movilidad_teide.energia.titsa import recalcular_titsa, leer_producto

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def caso():
    ref=leer_ordenacion(ROOT);folder=ROOT/ref['indice']['titsa_pendiente']['directorio']
    return ref,folder

def test_cuatro_sentidos_y_366_expediciones_conservan_longitudes(caso):
    ref,folder=caso;result=recalcular_titsa(ROOT,ref)
    assert len(result)==48 and set(result.linea)=={342,348}
    assert result.groupby(['linea','shape_id']).dias.sum().eq(366).all()
    assert result.expediciones_dia.eq(1).all()
    old=pd.read_csv(ROOT/'data/silver/energia/referencias_tecnicas/titsa_sin_pendiente_control.csv',sep=';')
    for shape,g in result.groupby('shape_id'):
        np.testing.assert_allclose(g.longitud_km,old.loc[old.shape_id.eq(shape),'longitud_km'].iloc[0],atol=1e-8,rtol=0)
    np.testing.assert_allclose(result.energia_hot_mwh_anio.sum(),303.2389995504144,atol=1e-10,rtol=0)

def test_terreno_nativo_completo_y_elevaciones_bilineales(caso):
    _,folder=caso;p=gpd.read_parquet(folder/'perfiles.parquet')
    assert p.crs.to_epsg()==4083 and len(p)==1186
    assert not p.interpretacion_provisional_crs.any()
    assert p.support_valid_count.eq(4).all() and p.elevation_method.eq('bilinear').all()
    rebuilt=sum(p[f'support_{i}_weight']*p[f'support_{i}_value_m'] for i in range(4))
    np.testing.assert_allclose(rebuilt,p.elevation_m,atol=1e-10,rtol=0)
    for name in p.mdt_archivo.unique():
        with rasterio.open(ROOT/name) as ds:
            assert ds.crs.to_epsg()==4083 and ds.res==(5.,5.)
    for _,g in p.groupby(['linea','shape_id']):
        d=np.diff(g.sort_values('distance_m').distance_m)
        assert (d>0).all() and (d<=200+1e-8).all()

def test_factores_interpolados_conservan_pendiente_fisica_y_limite(caso):
    ref,folder=caso;s=pd.read_parquet(folder/'segmentos.parquet');f=pd.read_parquet(folder/'factores_utilizados.parquet').sort_values('slope_class_pct')
    assert list(f.slope_class_pct)==[-6,-4,-2,0,2,4,6]
    assert f.rural_speed_kmh.eq(ref['valores_modelo']['velocidad_copert']).all()
    assert f.load_fraction.eq(ref['valores_modelo']['carga_copert']).all()
    physical=100*(s.elevation_end_m-s.elevation_start_m)/s.length_m
    np.testing.assert_allclose(s.slope_pct,physical,atol=1e-12,rtol=0)
    np.testing.assert_allclose(s.pendiente_asignacion_pct,physical.clip(-6,6),atol=1e-12,rtol=0)
    assert np.array_equal(s.fuera_dominio,physical.abs().gt(6)) and s.fuera_dominio.any()
    expected=np.interp(physical,f.slope_class_pct,f.hot_ec_mj_per_km)
    np.testing.assert_allclose(s.hot_ec_mj_per_km,expected,atol=1e-12,rtol=0)
    np.testing.assert_allclose(s.energia_mj,s.length_m/1000*expected,atol=1e-12,rtol=0)

def test_factor_cero_reproduce_la_referencia_plana(caso):
    ref,folder=caso;s=pd.read_parquet(folder/'segmentos.parquet');f=pd.read_parquet(folder/'factores_utilizados.parquet')
    f0=f.loc[f.slope_class_pct.eq(0),'hot_ec_mj_per_km'].item()
    old=pd.read_csv(ROOT/'data/silver/energia/referencias_tecnicas/titsa_sin_pendiente_control.csv',sep=';',float_precision='round_trip')
    np.testing.assert_allclose(old.factor_referencia_comun_mj_km,f0,atol=1e-12,rtol=0)
    flat=s.length_m.sum()/1000*f0/3600*366
    np.testing.assert_allclose(flat,old.energia_hot_equivalente_mwh_anio.sum(),atol=1e-10,rtol=0)
    delta=ref['indice']['titsa_pendiente']['consumo_mwh_anio']-flat
    np.testing.assert_allclose(delta,53.36199398139533,atol=1e-10,rtol=0)


def test_ida_y_regreso_se_calculan_por_separado(caso):
    _,folder=caso;t=pd.read_csv(folder/'resumen_recorridos.csv',sep=';',float_precision='round_trip')
    for _,g in t.groupby('linea'):
        assert len(g)==2 and g.origen.iloc[0]==g.destino.iloc[1] and g.destino.iloc[0]==g.origen.iloc[1]
        assert g.kilometros.iloc[0]!=g.kilometros.iloc[1]
        np.testing.assert_allclose(g.desnivel_neto_m.sum(),0,atol=1e-8,rtol=0)
        np.testing.assert_allclose(g.ascenso_m-g.descenso_m,g.desnivel_neto_m,atol=1e-8,rtol=0)

