"""Controles de masa vinculada, no linealidad y balance completo emparejado."""
from pathlib import Path
from copy import deepcopy
import json
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString
import pytest
from movilidad_teide.parametros import leer_parametros
from movilidad_teide.pendiente_anual import (GRUPOS,MODELOS,masas_grupos_desde_dgt,
    recortar_intervalos,energia_pendiente_por_recorrido,aplicar_correcciones_a_actividad,
    verificar_activacion_pendiente_anual)
from movilidad_teide.circulacion_turismos import clasificar_geometrias_existentes
from movilidad_teide.flota import clasificar_microdatos_parque
from movilidad_teide.mezcla_turismos import ALQUILER

ROOT=Path(__file__).resolve().parents[1]


def parameters():return leer_parametros(ROOT)


def parameters_d213():
    # Esta transición histórica conserva su libro de origen, aunque el actual crezca.
    return json.loads((ROOT/'tests/fixtures/parametros_aplicacion_pendiente.json').read_text())['parametros']


def test_aplicacion_anual_conserva_todas_las_elecciones_y_referencias():
    old=json.loads((ROOT/'tests/fixtures/parametros_antes_pendiente.json').read_text())['parametros']
    now=parameters_d213();v=verificar_activacion_pendiente_anual(old,now)
    assert v['valores_y_elecciones_previas_conservados'] and len(v['etiquetas_anuales_actualizadas'])==6
    assert old['elecciones_todos_los_casos']==now['elecciones_todos_los_casos']
    assert len(now['parametros'])==126


@pytest.mark.parametrize('field',['ocupacion_coche','cupo_global','reserva_flota','referencia_guagua_acceso','equipaje_turismo_kg_coche'])
def test_no_reutiliza_actividad_si_cambia_una_eleccion_material(field):
    old=json.loads((ROOT/'tests/fixtures/parametros_antes_pendiente.json').read_text())['parametros'];now=parameters_d213()
    next(x for x in now['parametros'] if x['id']==field)['valor_utilizado']='alterado'
    with pytest.raises(ValueError):verificar_activacion_pendiente_anual(old,now)


def test_guardia_historica_no_acepta_la_ampliacion_del_libro_por_reserva_y_refuerzo():
    old=parameters_d213();now=deepcopy(old);current=parameters()
    added={'reserva_minima_dentro_flota','intervalo_refuerzo_punta_min'}
    now['parametros'].extend(p for p in current['parametros'] if p['id'] in added)
    now['elecciones_todos_los_casos'].extend(p for p in current['elecciones_todos_los_casos'] if p['id'] in added)
    assert len(now['parametros'])==len(old['parametros'])+2
    assert now['parametros'][:len(old['parametros'])]==old['parametros']
    with pytest.raises(ValueError,match='Cambian caso o elecciones'):
        verificar_activacion_pendiente_anual(old,now)


def test_taras_del_mismo_grupo_y_prestamo_solo_si_faltan(tmp_path):
    rows=[]
    for model,tara in [('A','1000'),('A','1400'),('A','5000'),('B','2000'),('C','0')]:
        rows.append({'PROVINCIA':'38','MUNICIPIO':'38001','TIPO_DGT':'TURISMOS','CAT_EURO':'M1','SERVICIO':'A01','RENTING':'',
            'PROPULSION':'0','CATELECT':'','ALIMENTACION':'','TIPO_DISTINTIVO':'C','EMISIONES_EURO':'6BA','PESO_MAX':'2500','TARA':tara,'MARCA':'Sintética','MODELO':model})
    raw=pd.DataFrame(rows);equ={'6BA':'Euro 6 d/e'};t=clasificar_microdatos_parque(raw,['38001'],equ)
    t['MARCA']=raw.MARCA;t['MODELO']=raw.MODELO
    t['segmento_copert_propuesto']=raw.MODELO.map({'A':'Small','B':'Large','C':'Medium'})
    sizes=t[MODELOS+['segmento_copert_propuesto']].drop_duplicates()
    diagnostic=t[GRUPOS].drop_duplicates().copy();diagnostic['grupo_id']=[0,1,2];diagnostic['vehiculos']=[3,1,1]
    f=tmp_path/'sintetico.txt';raw.to_csv(f,sep='|',encoding='cp1252',index=False)
    x=masas_grupos_desde_dgt(f,['38001'],equ,sizes,diagnostic,chunksize=2).set_index('grupo_id')
    assert x.loc[0,'tara_mediana_kg']==1200 and x.loc[0,'registros_tara_validos_grupo']==2
    assert x.loc[0,'tara_p25_kg']==1100 and x.loc[0,'tara_p75_kg']==1300
    assert x.loc[1,'tara_mediana_kg']==2000 and not x.loc[1,'prestamo_de_masa']
    assert x.loc[2,'prestamo_de_masa'] and x.loc[2,'tara_mediana_kg']==1400
    assert x.vehiculos.sum()==5  # La tara incoherente se excluye del estadístico, no del stock.


def segment():
    return pd.DataFrame({'segment_id':['a','b'],'distance_start_m':[0.,100.],'distance_end_m':[100.,200.],
        'length_m':[100.,100.],'slope_pct':[10.,-10.],'elevation_start_m':[0.,10.],'elevation_end_m':[10.,0.]})


def test_recorte_conserva_longitudes_y_desniveles_por_tipo_de_via():
    s=segment();old=s.copy(deep=True)
    i=pd.DataFrame({'distance_start_m':[0.,75.],'distance_end_m':[75.,200.],'clase_propuesta':['local','convencional']})
    x=recortar_intervalos(s,i)
    assert x.length_m.sum()==200 and x.groupby('clase_propuesta').length_m.sum().to_dict()=={'convencional':125.,'local':75.}
    assert (x.elevation_end_m-x.elevation_start_m).sum()==pytest.approx(0)
    assert x.slope_pct.tolist()==pytest.approx([10.,10.,-10.]);pd.testing.assert_frame_equal(s,old)


@pytest.mark.parametrize('bad',['hueco','fuera'])
def test_no_cubre_huecos_del_perfil_con_pendiente_cero(bad):
    s=segment();i=pd.DataFrame({'distance_start_m':[0.],'distance_end_m':[200.]})
    if bad=='hueco':s.loc[1,'distance_start_m']=110.;s.loc[1,'length_m']=90.
    else:i.loc[0,'distance_end_m']=250.
    with pytest.raises(ValueError):recortar_intervalos(s,i)


def test_aristas_y_clasificacion_anterior_suman_lo_mismo():
    routes=gpd.GeoDataFrame({'itinerary_id':['r'],'rol':['directa'],'length_m':[200.]},geometry=[LineString([(0,0),(100,0),(200,0)])],crs='EPSG:32628')
    roads=gpd.GeoDataFrame({'osm_way_id':['a','b'],'highway':['residential','secondary']},geometry=[LineString([(0,0),(100,0)]),LineString([(100,0),(200,0)])],crs=routes.crs)
    old=clasificar_geometrias_existentes(routes,roads)
    x=clasificar_geometrias_existentes(routes,roads,por_arista=True)
    assert x.groupby('clase_propuesta').length_m.sum().to_dict()=={'convencional':100.,'local':100.}
    assert np.allclose(old.sort_values('clase_propuesta').longitud_clase_km*1000,x.sort_values('clase_propuesta').length_m)


def test_corrige_antes_de_ponderar_y_el_plano_reproduce_la_mezcla():
    p=parameters();rows={x['id']:x for x in p['parametros']};eta=rows['eficiencia_incremental_gasolina_pendiente']['valor_utilizado']
    mass=1000.;dh=-3*eta*1e6/(mass*9.81)
    s=pd.DataFrame({'comparacion_id':['c'],'itinerary_id':['i'],'rol':['directa'],'clase_propuesta':['convencional'],
        'length_m':[1000.],'elevation_start_m':[0.],'elevation_end_m':[dh]})
    tara=mass-rows['masa_persona_turismo_kg']['valor_utilizado']-rows['equipaje_turismo_kg_coche']['valor_utilizado']
    c=pd.DataFrame({'grupo_servicio':['s','s'],'clase_propuesta':['convencional']*2,'familia_copert':['Petrol']*2,
        'tara_mediana_kg':[tara]*2,'peso_total':[.5,.5],'hot_ec_mj_per_km':[2.,4.]})
    f=pd.DataFrame({'grupo_servicio':['s'],'modo':['rural'],'velocidad_kmh':[rows['velocidad_turismo_convencional']['valor_utilizado']],
        'aporte_conjunto_condicionado_min_mj_km':[3.],'aporte_conjunto_condicionado_max_mj_km':[3.]})
    z=energia_pendiente_por_recorrido(s,c,f,p,ocupacion=1)
    assert z.energia_convencional_ajustada_mj.item()==pytest.approx(.5) # (max(2−3,0)+max(4−3,0))/2
    assert z.correccion_otras_tecnologias_mj.isna().all() and not z.correccion_completa_de_todas_tecnologias.any()
    s['elevation_end_m']=s.elevation_start_m
    flat=energia_pendiente_por_recorrido(s,c,f,p,ocupacion=1)
    assert flat.correccion_convencional_mj.item()==pytest.approx(0)


def paired_inputs():
    route=[];energy=[];cars=[];other=[]
    for sense in ['hacia_teide','desde_teide']:
        route.append({'origen_id':'o','sentido':sense,'comparacion_calculo_id':'c','itinerario_referencia_id':sense+'d','itinerario_alimentador_id':sense+'f','terminal_calculo':'Boca Tauce'})
        for role,base,delta,tag in [('directa',100.,20.,'d'),('alimentador',50.,5.,'f')]:
            for occ in ([3.2] if role=='directa' else [3.2,1.]):
                energy.append({'comparacion_id':'c','itinerary_id':sense+tag,'rol':role,'grupo_servicio':ALQUILER,'ocupacion_coche':occ,
                    'energia_base_mj_recorrido':base,'energia_base_convencional_mj':.9*base,'correccion_convencional_mj':delta if occ==3.2 else 1.,'energia_base_otras_tecnologias_mj':.1*base})
        for branch,n in [('antes',10.),('autorizados',6.),('transferidos',4.)]:
            base=50. if branch=='transferidos' else 100.+(10. if sense=='hacia_teide' else 0.)
            cars.append({'alternativa_procedencia':'España no Tenerife: particular','origen_id':'o','colectivo':'extranjero','sentido':sense,'rama':branch,'recorridos_coche_anio':n,'energia_mwh_por_vehiculo_sentido':base/3600})
        other.append({'alternativa_procedencia':'España no Tenerife: particular','origen_id':'o','colectivo':'extranjero','sentido':sense,'personas_trayecto_anio':2.,'energia_mwh_por_vehiculo_sentido':50/3600})
    energy.append({'comparacion_id':'visita_proxima_Boca Tauce','itinerary_id':'visita_proxima_Boca Tauce','rol':'interior','grupo_servicio':ALQUILER,'ocupacion_coche':3.2,
        'energia_base_mj_recorrido':10.,'energia_base_convencional_mj':9.,'correccion_convencional_mj':2.,'energia_base_otras_tecnologias_mj':1.})
    return pd.DataFrame(cars),pd.DataFrame(other),pd.DataFrame(route),pd.DataFrame(energy)


def test_balance_completo_incluye_alimentadores_interior_y_ocupacion_correcta():
    c,o,r,e=paired_inputs();before=e.copy(deep=True)
    z=aplicar_correcciones_a_actividad(c,o,r,e).groupby('rama').correccion_convencional_mwh_anio.sum()*3600
    assert z.to_dict()==pytest.approx({'antes':420.,'autorizados':252.,'transferidos':40.,'alimentacion_otros':4.})
    assert z['antes']-z.drop('antes').sum()==pytest.approx(124)
    pd.testing.assert_frame_equal(e,before)


def test_no_atribuye_ahorro_si_se_pierden_coches_en_el_reparto():
    c,o,r,e=paired_inputs();c.loc[c.rama.eq('autorizados'),'recorridos_coche_anio']=5.
    with pytest.raises(ValueError,match='No se conserva'):aplicar_correcciones_a_actividad(c,o,r,e)


def test_no_aplica_un_coeficiente_que_no_reproduce_el_recorrido_anterior():
    c,o,r,e=paired_inputs();e.loc[e.rol.eq('directa'),'energia_base_mj_recorrido']=101.
    with pytest.raises(ValueError,match='no reproduce'):aplicar_correcciones_a_actividad(c,o,r,e)
