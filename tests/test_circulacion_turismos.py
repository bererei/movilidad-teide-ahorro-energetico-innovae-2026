"""Proteger trazados, longitudes y referencias parciales al simplificar la circulación."""
import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString
from movilidad_teide.circulacion_turismos import (
    clasificar_geometrias_existentes,calcular_aportes_circulacion,vincular_aportes_a_referencias)


def geometrias():
    route=gpd.GeoDataFrame([{'itinerary_id':'r','rol':'directa','length_m':3.,
        'geometry':LineString([(0,0),(1,0),(2,0),(3,0)])}],crs=4083)
    ways=gpd.GeoDataFrame([{'osm_way_id':str(i),'highway':tag,
        'geometry':LineString([(i,0),(i+1,0)])} for i,tag in enumerate(['residential','primary','motorway'])],crs=4083)
    return route,ways


def test_clasificacion_conserva_geometrias_longitudes_y_etiquetas():
    r,w=geometrias();a,b=r.copy(deep=True),w.copy(deep=True)
    x=clasificar_geometrias_existentes(r,w)
    assert x.set_index('clase_propuesta').longitud_clase_km.to_dict()==pytest.approx({'local':.001,'convencional':.001,'rapida':.001})
    assert x.longitud_clase_km.sum()==pytest.approx(.003)
    assert_geodataframe_equal(r,a);assert_geodataframe_equal(w,b)


def test_precision_de_coordenadas_no_mueve_ni_prolonga_el_trazado():
    r,w=geometrias();w.geometry=w.geometry.translate(yoff=2e-6)
    x=clasificar_geometrias_existentes(r,w)
    assert 'pendiente' not in set(x.clase_propuesta) and x.longitud_clase_km.sum()==pytest.approx(.003)
    w.geometry=w.geometry.translate(yoff=.1)
    y=clasificar_geometrias_existentes(r,w)
    assert y.clase_propuesta.eq('pendiente').all()


def test_dos_vias_del_mismo_tipo_no_duplican_la_longitud():
    r,w=geometrias();extra=w.iloc[[1]].copy();extra['osm_way_id']='otro';extra['highway']='secondary'
    x=clasificar_geometrias_existentes(r,pd.concat([w,extra],ignore_index=True))
    assert x.longitud_clase_km.sum()==pytest.approx(.003)
    assert set(x.loc[x.clase_propuesta.eq('convencional'),'osm_way_ids'].item().split(' | '))=={'1','otro'}


def test_vias_que_discrepan_conservan_el_tramo_pendiente():
    r,w=geometrias();extra=w.iloc[[1]].copy();extra['highway']='residential';extra['osm_way_id']='otro'
    x=clasificar_geometrias_existentes(r,pd.concat([w,extra],ignore_index=True))
    assert x.loc[x.clase_propuesta.eq('pendiente'),'longitud_clase_km'].sum()==pytest.approx(.001)


def test_un_cruce_no_acredita_que_el_trayecto_siga_esa_via():
    r,_=geometrias();w=gpd.GeoDataFrame([{'osm_way_id':'cruce','highway':'motorway',
        'geometry':LineString([(1.5,-2),(1.5,2)])}],crs=4083)
    x=clasificar_geometrias_existentes(r,w)
    assert x.clase_propuesta.eq('pendiente').all()


@pytest.mark.parametrize('cambio',['crs','longitud','duplicado','tolerancia'])
def test_clasificacion_rechaza_geometria_o_precision_incoherentes(cambio):
    r,w=geometrias();tol=1e-5
    if cambio=='crs':r=r.set_crs(4326,allow_override=True)
    if cambio=='longitud':r['length_m']=10
    if cambio=='duplicado':r=pd.concat([r,r],ignore_index=True)
    if cambio=='tolerancia':tol=1
    with pytest.raises(ValueError):clasificar_geometrias_existentes(r,w,tolerancia_m=tol)


def datos_consumo():
    x=pd.DataFrame({'comparacion_id':['c']*3,'itinerary_id':['r']*3,'rol':['directa']*3,
        'clase_propuesta':['local','convencional','rapida'],'longitud_clase_km':[1.,1.,1.]})
    f=pd.DataFrame({'grupo_servicio':['B00']*3,'modo':['urban_off_peak','rural','highway'],
        'velocidad_kmh':[20,40,80],'aporte_conjunto_condicionado_min_mj_km':[1.,2.,3.],
        'aporte_conjunto_condicionado_max_mj_km':[2.,4.,6.]})
    return x,f,{'local':20,'convencional':40,'rapida':80}


def test_consumo_por_longitud_sin_promediar_velocidades_o_factores():
    x,f,v=datos_consumo();z=calcular_aportes_circulacion(x,f,v)['resumen'].iloc[0]
    assert z.aporte_min_mj==6 and z.aporte_max_mj==12
    assert z.aporte_min_kwh==pytest.approx(6/3.6) and z.aporte_max_kwh==pytest.approx(12/3.6)
    assert np.isnan(z.energia_total_flota_mj)


@pytest.mark.parametrize('cambio',['velocidad_pendiente','aporte_pendiente','tipo_pendiente'])
def test_ausencias_no_desaparecen_al_sumar_el_recorrido(cambio):
    x,f,v=datos_consumo()
    if cambio=='velocidad_pendiente':v['local']=None
    if cambio=='aporte_pendiente':f.loc[0,['aporte_conjunto_condicionado_min_mj_km','aporte_conjunto_condicionado_max_mj_km']]=np.nan
    if cambio=='tipo_pendiente':x.loc[0,'clase_propuesta']='pendiente'
    z=calcular_aportes_circulacion(x,f,v)['resumen'].iloc[0]
    assert z.longitud_km==3 and z.longitud_sin_condicion_km==1
    assert np.isnan(z.aporte_min_mj) and np.isnan(z.aporte_max_mj)


def test_velocidad_sin_consulta_no_se_interpola_ni_se_reemplaza():
    x,f,v=datos_consumo();v['local']=35
    with pytest.raises(ValueError):calcular_aportes_circulacion(x,f,v)


def test_referencia_geografica_preserva_aproximacion_y_caso_condicional():
    x,f,v=datos_consumo();z=calcular_aportes_circulacion(x,f,v)['resumen']
    z=pd.concat([z,z.assign(rol='alimentador'),z.assign(rol='montana')],ignore_index=True)
    r=pd.DataFrame([{'origen_id':'o','sentido':'ida','comparacion_calculo_id':'c','tipo_representacion_calculo':'territorial_explicita',
        'itinerario_referencia_id':'r','itinerario_alimentador_id':'r','itinerario_montana_referencia_id':'r',
        'directa_km':3.,'alimentador_km':3.,'montana_km':3.},
        {'origen_id':'sin_perfil','sentido':'ida','comparacion_calculo_id':'','tipo_representacion_calculo':'condicional_media_nula',
        'itinerario_referencia_id':'','itinerario_alimentador_id':'','itinerario_montana_referencia_id':'',
        'directa_km':np.nan,'alimentador_km':np.nan,'montana_km':np.nan}])
    y=vincular_aportes_a_referencias(r,z)
    assert len(y)==6 and y.loc[y.origen_id.eq('sin_perfil'),'aporte_min_mj'].isna().all()
    assert y.loc[y.origen_id.eq('o'),'tipo_representacion_calculo'].eq('territorial_explicita').all()
    r.loc[0,'directa_km']=2
    with pytest.raises(ValueError):vincular_aportes_a_referencias(r,z)
