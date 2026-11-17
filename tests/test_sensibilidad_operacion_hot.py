"""Contrastes de sensibilidad: unidades, dominio y recargos sin doble cómputo."""
from copy import deepcopy
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from movilidad_teide.parametros import leer_parametros
from movilidad_teide.balance_condicionado import (incremento_por_perdida_rendimiento,
    verificar_reutilizacion_sensibilidad,sensibilidad_interior_y_operacion)


def test_diez_por_ciento_menos_km_por_litro_no_es_diez_mas_litros():
    ratio=incremento_por_perdida_rendimiento(.1)
    assert np.isclose(ratio,1/9) and not np.isclose(ratio,.1)
    assert np.isclose(100/((1-.1)*4),100/4*(1+ratio))

@pytest.mark.parametrize('p',[-.1,1.,2.,np.nan,np.inf,True])
def test_perdida_invalida_no_se_convierte_en_consumo(p):
    with pytest.raises(ValueError):incremento_por_perdida_rendimiento(p)

@pytest.fixture
def inputs():
    ids={'grupo_servicio':'Particular sin especificar (B00)','referencia_tecnica_turismos':'Inferior',
        'referencia_acceso':'coach','referencia_interior':'coach'}
    c=pd.DataFrame([ids|{'diferencia_hot_identificada_mwh_anio':-20.}])
    b=pd.DataFrame([ids|{'componente':name,'sin_aporte_hot_mwh_anio':0.,'con_aporte_hot_mwh_anio':value}
        for name,value in [('Accesos: servicio comercial',600.),('Accesos: vacíos modelizados',100.),
        ('Interior: servicio comercial',180.),('Interior: vacíos modelizados',20.),
        ('Cocheras: adicional',0.)]])
    i=pd.DataFrame([{'grupo_servicio':ids['grupo_servicio'],'referencia_tecnica_turismos':'Inferior',
        'patron_id':'ambos','coeficiente_antes_mwh_anio':300.,'coeficiente_autorizados_mwh_anio':100.,
        'coeficiente_transferidos_mwh_anio':200.}])
    return c,b,i

def test_recargo_sobre_toda_la_oferta_una_vez(inputs):
    x=sensibilidad_interior_y_operacion(*inputs,perdida_rendimiento=.1).set_index('perdida_rendimiento_contrastada')
    assert x.loc[0.,'recargo_exploratorio_guaguas_mwh_anio']==0.
    assert np.isclose(x.loc[.1,'recargo_exploratorio_guaguas_mwh_anio'],100.)
    assert x.loc[.1,'saldo_identificado_sin_circuitos_mwh_anio']==pytest.approx(-120.)
    assert x.loc[.1,'q_para_saldo_identificado_cero_con_cuota_igual']==pytest.approx(.6)
    assert x.loc[0.,'q_para_saldo_identificado_cero_con_cuota_igual']==pytest.approx(.1)
    assert x[['fracciones_interiores_elegidas','incremento_operativo_real_estimado','ahorro_total_hot_mwh_anio']].isna().all().all()

def test_cuotas_independientes_no_son_la_recta_de_cuota_igual(inputs):
    x=sensibilidad_interior_y_operacion(*inputs,perdida_rendimiento=.1).iloc[0]
    assert x.saldo_dominio_cuota_igual_q0_mwh_anio==-20.
    assert x.saldo_dominio_cuota_igual_q1_mwh_anio==180.
    assert x.saldo_dominio_cuotas_independientes_min_mwh_anio==-120.
    assert x.saldo_dominio_cuotas_independientes_max_mwh_anio==280.


def test_umbral_superior_a_uno_no_se_recorta(inputs):
    c,b,i=inputs;c=c.copy();c['diferencia_hot_identificada_mwh_anio']=-500.
    x=sensibilidad_interior_y_operacion(c,b,i,perdida_rendimiento=.1)
    assert x.q_para_saldo_identificado_cero_con_cuota_igual.gt(1).all()
    assert x.lectura_cuota_igual.str.contains('negativo en todo').all()


def test_saldo_positivo_no_es_ahorro_total(inputs):
    c,b,i=inputs;c=c.copy();c['diferencia_hot_identificada_mwh_anio']=500.
    x=sensibilidad_interior_y_operacion(c,b,i,perdida_rendimiento=.1)
    assert x.q_para_saldo_identificado_cero_con_cuota_igual.eq(0).all()
    assert x.ahorro_total_hot_mwh_anio.isna().all()

@pytest.mark.parametrize('failure',['componente_ausente','energia_nula','servicio_comun','duplicado','ramas_incoherentes','sin_patron'])
def test_no_omite_consumos_o_incoherencias(inputs,failure):
    c,b,i=[x.copy() for x in inputs]
    if failure=='componente_ausente':b=b.iloc[1:]
    if failure=='energia_nula':b.loc[0,'con_aporte_hot_mwh_anio']=np.nan
    if failure=='servicio_comun':b.loc[0,'sin_aporte_hot_mwh_anio']=1.
    if failure=='duplicado':b=pd.concat([b,b.iloc[:1]],ignore_index=True)
    if failure=='ramas_incoherentes':i['coeficiente_transferidos_mwh_anio']=50.
    if failure=='sin_patron':i['grupo_servicio']='Otro servicio'
    with pytest.raises(ValueError):sensibilidad_interior_y_operacion(c,b,i,perdida_rendimiento=.1)


def test_libro_referencia_y_eleccion_son_distintas(parametros_historicos):
    p=parametros_historicos;key='perdida_rendimiento_guaguas_contraste'
    row=next(x for x in p['parametros'] if x['id']==key)
    assert row['valor_utilizado'] is None and row['propuesta']['valor']==.1
    assert next(x for x in p['parametros'] if x['id']=='ubicacion_cocheras_lanzaderas')['valor_utilizado']=='Cabeceras de acceso y extremos del interior'
    old=deepcopy(p);old['sha256_libro']='0'*64
    old['parametros']=[x for x in old['parametros'] if x['id']!=key]
    old['elecciones_todos_los_casos']=[x for x in old['elecciones_todos_los_casos'] if x['id']!=key]
    result=verificar_reutilizacion_sensibilidad(old,p)
    assert result['control_nuevo_no_usado_por_productor']==key
    assert result['sha256_libro_productor']!=result['sha256_libro_comparacion']
    old['parametros'][0]['valor_utilizado']=2024
    with pytest.raises(ValueError):verificar_reutilizacion_sensibilidad(old,p)
