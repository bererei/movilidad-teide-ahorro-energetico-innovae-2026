"""Evitar doble cómputo de visitas y cuotas inventadas en los contrastes Hot."""
import numpy as np
import pandas as pd
import pytest
from movilidad_teide.balance_condicionado import (recorridos_interiores_coche,
    coeficientes_hot_interior_coche,contraste_umbral_interior_hot,MAGNITUD_ANUAL)

@pytest.fixture
def inputs():
    stops=pd.DataFrame({'parada_id':['boca','parador','tele','portillo'],'posicion_m':[0.,6000.,10000.,21000.]})
    patterns=[{'patron_id':'parador','nombre':'Parador','destinos':['parador']},
        {'patron_id':'tele','nombre':'Teleférico','destinos':['tele']},
        {'patron_id':'ambos','nombre':'Ambos','destinos':['tele','parador']}]
    routes=recorridos_interiores_coche(stops,patterns,{'Boca Tauce':'boca','El Portillo':'portillo'})
    activity=pd.DataFrame([{'rama':branch,'origen_id':origin,'colectivo':'visitantes','sentido':direction,
        'en_ambito_anual':True,MAGNITUD_ANUAL:number}
        for origin in ['sur','norte'] for direction in ['hacia_teide','desde_teide']
        for branch,number in [('antes',100.),('autorizados',40.),('transferidos',60.)]])
    refs=pd.DataFrame([{'origen_id':origin,'sentido':direction,'terminal_calculo':terminal}
        for origin,terminal in [('sur','Boca Tauce'),('norte','El Portillo')]
        for direction in ['hacia_teide','desde_teide']])
    factors=pd.DataFrame({'grupo_servicio':['Particular sin especificar (B00)'],'modo':['rural'],'velocidad_kmh':[40.],
        'aporte_conjunto_condicionado_min_mj_km':[1.],'aporte_conjunto_condicionado_max_mj_km':[2.]})
    return stops,patterns,routes,activity,refs,factors

def calculate(x):
    return coeficientes_hot_interior_coche(x[3],x[4],x[2],x[5],velocidad_rural=40.)

def test_varias_paradas_no_son_dos_excursiones(inputs):
    r=inputs[2].set_index(['terminal_calculo','patron_id'])
    assert r.loc[('Boca Tauce','ambos'),'longitud_interior_ida_vuelta_km']==20.
    assert r.loc[('El Portillo','ambos'),'longitud_interior_ida_vuelta_km']==30.
    assert r.loc[('Boca Tauce','ambos'),'longitud_interior_ida_vuelta_km']!=32.
    assert r.loc[('Boca Tauce','ambos'),'secuencia_referencias']=='boca → parador → tele → boca'
    assert r.loc[('El Portillo','ambos'),'secuencia_referencias']=='portillo → tele → parador → portillo'

def test_cuenta_subidas_como_visitas_y_regreso_una_vez(inputs):
    result=calculate(inputs)
    assert result['visitas_por_entrada'].query("rama == 'antes'")[MAGNITUD_ANUAL].sum()==200.
    g=result['coeficientes'].query("patron_id == 'ambos' and referencia_tecnica_turismos == 'Factores técnicos bajos por clase'").iloc[0]
    assert np.isclose(g.coeficiente_antes_mwh_anio,100*(20+30)/3600)
    assert np.isclose(g.coeficiente_transferidos_mwh_anio,60*(20+30)/3600)
    assert result['coeficientes'][['q_sin_elegida','q_autorizados_elegida','aporte_interior_sin_mwh_anio','aporte_interior_con_mwh_anio']].isna().all().all()

@pytest.mark.parametrize('failure',['destino_desconocido','destino_repetido','posicion_nula','entrada_intermedia','patron_repetido'])
def test_rechaza_geografia_incompleta(inputs,failure):
    stops,patterns,*_=inputs;stops=stops.copy();patterns=[dict(p) for p in patterns];entries={'Boca Tauce':'boca','El Portillo':'portillo'}
    if failure=='destino_desconocido':patterns[0]['destinos']=['no existe']
    if failure=='destino_repetido':patterns[0]['destinos']=['parador','parador']
    if failure=='posicion_nula':stops.loc[0,'posicion_m']=np.nan
    if failure=='entrada_intermedia':entries['Boca Tauce']='parador'
    if failure=='patron_repetido':patterns.append(patterns[0])
    with pytest.raises(ValueError):recorridos_interiores_coche(stops,patterns,entries)

@pytest.mark.parametrize('failure',['regreso_distinto','actividad_desconocida','rama_no_conserva','terminal_desconocido','regreso_otro_extremo','factor_ausente','factor_invertido','patron_incompleto'])
def test_rechaza_incoherencia_entre_direcciones_ramas_factores(inputs,failure):
    x=[t.copy(deep=True) if isinstance(t,pd.DataFrame) else t for t in inputs]
    if failure=='regreso_distinto':x[3].loc[1,MAGNITUD_ANUAL]+=1
    if failure=='actividad_desconocida':x[3].loc[0,MAGNITUD_ANUAL]=np.nan
    if failure=='rama_no_conserva':x[3].loc[x[3].rama.eq('antes'),MAGNITUD_ANUAL]=99.
    if failure=='terminal_desconocido':x[4].loc[0,'terminal_calculo']='otro'
    if failure=='regreso_otro_extremo':x[4].loc[1,'terminal_calculo']='El Portillo'
    if failure=='factor_ausente':x[5].loc[0,'velocidad_kmh']=35.
    if failure=='factor_invertido':x[5].loc[0,'aporte_conjunto_condicionado_max_mj_km']=.5
    if failure=='patron_incompleto':x[2]=x[2].iloc[:-1]
    with pytest.raises(ValueError):calculate(x)

def comparison(c,base):
    return c[['grupo_servicio','referencia_tecnica_turismos']].drop_duplicates().assign(
        referencia_interior='autocar',referencia_acceso='autocar',diferencia_hot_identificada_mwh_anio=base)

def test_umbral_mayor_cien_no_se_recorta_o_adopta(inputs):
    c=calculate(inputs)['coeficientes'];r=contraste_umbral_interior_hot(c,comparison(c,-100.))
    assert r.q_condicionada_para_saldo_identificado_cero.gt(1).all()
    assert r[['q_adoptada','ahorro_total_energia_final_mwh_anio']].isna().all().all()
    assert r.condicion_algebraica.str.startswith('Exigiría').all()

def test_saldo_positivo_no_implica_ahorro_total(inputs):
    c=calculate(inputs)['coeficientes'];r=contraste_umbral_interior_hot(c,comparison(c,1.))
    assert r.q_condicionada_para_saldo_identificado_cero.eq(0).all()
    assert r.ahorro_total_energia_final_mwh_anio.isna().all()

def test_sin_transferencia_no_se_inventa_respuesta(inputs):
    x=list(inputs);x[3]=inputs[3].copy();x[3].loc[x[3].rama.eq('transferidos'),MAGNITUD_ANUAL]=0.
    x[3].loc[x[3].rama.eq('autorizados'),MAGNITUD_ANUAL]=100.
    c=calculate(x)['coeficientes']
    with np.errstate(divide='ignore',invalid='ignore'):r=contraste_umbral_interior_hot(c,comparison(c,-1.))
    assert r.q_condicionada_para_saldo_identificado_cero.isna().all()
    assert r.condicion_algebraica.str.startswith('Sin respuesta').all()

def test_cuota_elegida_no_pasa_por_desconocida(inputs):
    c=calculate(inputs)['coeficientes'];c['q_sin_elegida']=.5
    with pytest.raises(ValueError):contraste_umbral_interior_hot(c,comparison(c,-1.))
