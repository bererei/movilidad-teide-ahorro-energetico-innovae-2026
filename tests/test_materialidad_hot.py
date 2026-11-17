"""Materialidad: flota activa, distancia de cochera y auxiliares sin doble cómputo."""
import numpy as np
import pandas as pd
import pytest
from movilidad_teide.balance_condicionado import (exposicion_lanzaderas_materialidad,
    coeficientes_cocheras_auxiliares,integrar_coeficientes_materialidad)

@pytest.fixture
def offer():
    v=pd.DataFrame([{'tipo_dia':'Laborable','punto':p,'vehiculo_id':'bus1','kilometros_dia':40.}
        for p in ['NORTE','INTERIOR']])
    h=pd.DataFrame([{'tipo_dia':'Laborable','punto':p,'vehiculo_id':'bus1','id_salida':str(i),
        'km_por_recorrido':10.,'tiempo_recorrido_min':20.,'dias_calendario':200}
        for p in ['NORTE','INTERIOR'] for i in range(4)])
    refs=pd.DataFrame([{'referencia_id':id,'Category':'Buses','Fuel':fuel,'Segment':segment,'Euro Standard':'Euro VI'}
        for id,fuel,segment in [('coach','Diesel','Coach'),('hybrid','Diesel Hybrid','Urban')]])
    f=refs.drop(columns='referencia_id').assign(rural_speed_kmh=34.,load_fraction=0.,slope_class_pct=0.,hot_ec_mj_per_km=[10.,8.])
    return v,h,refs,f

def test_flota_no_se_multiplica_por_expediciones(offer):
    v,h,*_=offer;x=exposicion_lanzaderas_materialidad(v,h)
    assert x.vehiculos_dia_anio.sum()==400
    assert x.vehiculo_km_identificados_anio.sum()==16000
    assert np.isclose(x.horas_movimiento_anio.sum(),2*4*20*200/60)
    assert x[['km_cochera_reales_dia_vehiculo','incremento_auxiliar_real_mj_km']].isna().all().all()

@pytest.mark.parametrize('failure',['vehiculo_duplicado','km_no_concilian','vehiculo_sin_salidas','salida_duplicada','dias_inconsistentes','calendario_fraccionario','tiempo_desconocido'])
def test_rechaza_oferta_incoherente(offer,failure):
    v,h,*_=offer;v=v.copy();h=h.copy()
    if failure=='vehiculo_duplicado':v=pd.concat([v,v.iloc[:1]],ignore_index=True)
    if failure=='km_no_concilian':v.loc[0,'kilometros_dia']=39.
    if failure=='vehiculo_sin_salidas':h=h.loc[h.punto.ne('NORTE')]
    if failure=='salida_duplicada':h=pd.concat([h,h.iloc[:1]],ignore_index=True)
    if failure=='dias_inconsistentes':h.loc[0,'dias_calendario']=100
    if failure=='calendario_fraccionario':h['dias_calendario']=200.5
    if failure=='tiempo_desconocido':h.loc[0,'tiempo_recorrido_min']=np.nan
    with pytest.raises(ValueError):exposicion_lanzaderas_materialidad(v,h)

def coefficients(offer):
    v,h,r,f=offer
    return coeficientes_cocheras_auxiliares(exposicion_lanzaderas_materialidad(v,h),f,r,
        referencia_acceso='coach',velocidad=34.)

def test_tecnologias_son_alternativas_y_auxiliares_incluyen_cochera(offer):
    x=coefficients(offer)['resumen'].set_index('referencia_interior')
    assert len(x)==2
    assert np.isclose(x.loc['coach','K_cochera_mwh_por_km_diario_vehiculo'],400*10/3600)
    assert np.isclose(x.loc['hybrid','K_cochera_mwh_por_km_diario_vehiculo'],200*(10+8)/3600)
    assert np.allclose(x.K_auxiliar_mwh_por_mj_km,16000/3600)
    # Un caso sintético verifica también d*u; los valores no son una propuesta real.
    d,u=7.,2.
    expression=d*x.loc['coach','K_cochera_mwh_por_km_diario_vehiculo']+u*x.loc['coach','K_auxiliar_mwh_por_mj_km']+d*u*x.loc['coach','K_interaccion_d_u']
    assert np.isclose(expression,(400*d*10+(16000+400*d)*u)/3600)
    assert x[['d_cochera_elegida','u_auxiliar_elegido','energia_cocheras_auxiliares_real_mwh_anio']].isna().all().all()

@pytest.mark.parametrize('failure',['carga_distinta','pendiente_distinta','velocidad_distinta','factor_nulo','factor_duplicado','dias_flota_incompatibles'])
def test_referencia_tecnica_exige_condiciones_explicitas(offer,failure):
    v,h,r,f=offer;f=f.copy();e=exposicion_lanzaderas_materialidad(v,h)
    if failure=='carga_distinta':f['load_fraction']=.5
    if failure=='pendiente_distinta':f['slope_class_pct']=2.
    if failure=='velocidad_distinta':f['rural_speed_kmh']=40.
    if failure=='factor_nulo':f.loc[0,'hot_ec_mj_per_km']=np.nan
    if failure=='factor_duplicado':f=pd.concat([f,f.iloc[:1]],ignore_index=True)
    if failure=='dias_flota_incompatibles':e.loc[0,'vehiculos_dia_anio']+=1
    with pytest.raises(ValueError):coeficientes_cocheras_auxiliares(e,f,r,referencia_acceso='coach',velocidad=34.)

def integrated(offer):
    bus=coefficients(offer)['resumen']
    comparison=pd.DataFrame([{'grupo_servicio':'Particular sin especificar (B00)',
        'referencia_tecnica_turismos':'Referencia técnica','referencia_acceso':'coach',
        'referencia_interior':id,'diferencia_hot_identificada_mwh_anio':-50.}
        for id in ['coach','hybrid']])
    interior=pd.DataFrame([{'grupo_servicio':'Particular sin especificar (B00)',
        'referencia_tecnica_turismos':'Referencia técnica','patron_id':'ambas_zonas',
        'coeficiente_antes_mwh_anio':200.,'coeficiente_autorizados_mwh_anio':80.,
        'coeficiente_transferidos_mwh_anio':120.}])
    return comparison,interior,bus

def test_sensibilidad_conserva_signos_y_desconocidos(offer):
    x=integrar_coeficientes_materialidad(*integrated(offer))
    assert x.diferencia_hot_identificada_mwh_anio.eq(-50.).all()
    assert x.respuesta_por_punto_porcentual_q_sin_mwh_anio.eq(2.).all()
    assert x.respuesta_por_punto_porcentual_q_autorizados_mwh_anio.eq(-.8).all()
    assert x.respuesta_por_punto_porcentual_cuota_igual_mwh_anio.eq(1.2).all()
    assert x[['ahorro_total_hot_mwh_anio','cambio_neto_otros_C_mwh_anio']].isna().all().all()

@pytest.mark.parametrize('failure',['referencia_interior_ausente','servicio_desconocido','no_conserva_ramas','coeficiente_ausente'])
def test_no_ignora_componentes_al_integrar(offer,failure):
    c,i,b=integrated(offer)
    if failure=='referencia_interior_ausente':b=b.iloc[:1]
    if failure=='servicio_desconocido':i['grupo_servicio']='otro'
    if failure=='no_conserva_ramas':i['coeficiente_transferidos_mwh_anio']=50.
    if failure=='coeficiente_ausente':b.loc[0,'K_interaccion_d_u']=np.nan
    with pytest.raises(ValueError):integrar_coeficientes_materialidad(c,i,b)


@pytest.mark.parametrize('field',['q_sin_elegida','q_autorizados_elegida','d_cochera_elegida','u_auxiliar_elegido'])
def test_no_oculta_una_eleccion_adoptada_como_incognita(offer,field):
    c,i,b=integrated(offer)
    if field.startswith('q_'):i[field]=.5
    else:b[field]=1.
    with pytest.raises(ValueError):integrar_coeficientes_materialidad(c,i,b)
