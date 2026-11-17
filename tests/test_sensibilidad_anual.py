"""Sensibilidad sin probabilidades ficticias, oferta parcial y catálogos no monótonos."""
import numpy as np
import pandas as pd
import pytest
from movilidad_teide.horarios_conjuntos import PUNTOS
from movilidad_teide.sensibilidad_anual import seleccionar_componente_catalogo,sensibilidad_componentes,limites_catalogo_por_tipo

POINTS=list(PUNTOS.values());DAYS={'Laborable':260,'Sábado':53,'Domingo':53}


def catalogo():
    rows=[]
    for pid,counts in [('P0',{p:1 for p in POINTS}),('P1',{p:2 if p=='CHIO' else 1 for p in POINTS}),('P2',{p:2 for p in POINTS})]:
        rows.append({'perfil_id':pid,'perfil_comprobado':True,**{'parejas_'+q:n for q,n in counts.items()}})
    return pd.DataFrame(rows)


def bases():return {d:{q:1 for q in POINTS} for d in DAYS}


def energia():return pd.DataFrame({'perfil_id':['P0','P1','P2'],'referencia_id':['h']*3,'con_contraste_mwh_dia':[10.,9.,12.]})


def test_exceso_no_se_elimina_ni_confunde_con_demanda_servida():
    demand={q:20. for q in POINTS};demand['CHIO']=100.
    z=seleccionar_componente_catalogo(demand,catalogo(),bases(),tipo_dia='Laborable',capacidad=46)
    assert z['perfil_id']=='P1' and not z['cabe_por_volumen_diario']
    assert z['exceso_personas_por_corredor']['CHIO']==8
    assert z['parejas_necesarias_por_corredor']['CHIO']==3 and z['parejas_por_corredor']['CHIO']==2
    assert not z['actividad_fuera_catalogo_cuantificada'] and not z['frecuencia_futura_confirmada']


def test_especial_exige_plan_completo_y_no_se_imputa_domingo():
    demand={q:1. for q in POINTS}
    assert seleccionar_componente_catalogo(demand,catalogo(),bases(),tipo_dia='Festivo/especial',capacidad=46)['perfil_id']=='P2'
    with pytest.raises(ValueError):seleccionar_componente_catalogo(demand,catalogo(),bases(),tipo_dia='Desconocido',capacidad=46)


@pytest.mark.parametrize('bad',[True,0,np.nan,46.5])
def test_capacidad_invalida_no_da_plazas_aparentes(bad):
    with pytest.raises(ValueError):seleccionar_componente_catalogo({q:1. for q in POINTS},catalogo(),bases(),tipo_dia='Laborable',capacidad=bad)


def test_dominio_revisa_todos_los_perfiles_sin_imponer_monotonia_o_frecuencias():
    x=limites_catalogo_por_tipo(catalogo(),energia(),bases(),DAYS)
    assert x.minimo_catalogo_mwh_dia.eq(9).all() and x.maximo_catalogo_mwh_dia.eq(12).all()
    assert x.incremento_anual_minimo_dentro_catalogo_mwh.sum()==-366
    assert x.incremento_anual_maximo_dentro_catalogo_mwh.sum()==732
    assert x.energia_fuera_catalogo_mwh_anio.isna().all() and not x.frecuencia_cabildo_confirmada.any()


@pytest.mark.parametrize('failure',['incomplete','calendar','negative'])
def test_no_inventar_energia_de_perfiles_ausentes(failure):
    e=energia();d=dict(DAYS)
    if failure=='incomplete':e=e.iloc[:-1]
    if failure=='calendar':d['Laborable']=259
    if failure=='negative':e.loc[0,'con_contraste_mwh_dia']=-1
    with pytest.raises(ValueError):limites_catalogo_por_tipo(catalogo(),e,bases(),d)


def tabla():
    return pd.DataFrame({'politica_oferta':['base'],'alternativa_procedencia':['a'],'coches_sin_mwh_anio':[100.],
      'coches_con_objetivo_mwh_anio':[50.],'alimentacion_otros_mwh_anio':[10.],
      'servicios_comunes_sin_mwh_anio':[5.],'servicios_comunes_con_mwh_anio':[5.],
      'guaguas_regulares_con_contraste_mwh_anio':[20.],'saldo_componentes_objetivo_mwh_anio':[20.]})


def test_sensibilidad_considera_todos_los_coches_ambos_lados_y_alimentacion():
    t=tabla();old=t.copy(deep=True);z=sensibilidad_componentes(t,perdida_rendimiento=.1,objetivo_tep=60)
    u=z['respuesta_y_umbrales'].iloc[0]
    assert u.cambio_saldo_por_menos_1pct_consumo_todos_coches_mwh_anio==pytest.approx(-.4)
    assert u.cambio_saldo_por_mas_1pct_consumo_nuevas_guaguas_mwh_anio==pytest.approx(-.2)
    assert u.reduccion_uniforme_coches_para_saldo_cero_pct==pytest.approx(50)
    assert u.incremento_nuevas_guaguas_para_saldo_cero_pct==pytest.approx(100)
    assert u.fraccion_energia_coche_evitada_para_saldo_cero==pytest.approx(.6)
    assert u.coste_neto_adicional_para_objetivo_mwh_anio<0 and pd.isna(u.probabilidad_asignada)
    c=z['controles_consumo'];assert c.guaguas_mwh_anio.tolist()==[20.,18.]
    assert c.saldo_componentes_antes_adicionales_mwh_anio.tolist()==[20.,22.]
    assert c.contraste_externo_mwh_anio.eq(2).all()
    assert c.ahorro_final_mwh_anio.isna().all() and not c.escenario_futuro_adoptado.any()
    pd.testing.assert_frame_equal(t,old)


@pytest.mark.parametrize('failure',['perdida','negativo','inconciliable'])
def test_no_bajar_controles_para_obtener_ahorro(failure):
    t=tabla();p=.1
    if failure=='perdida':p=1
    if failure=='negativo':t.loc[0,'coches_sin_mwh_anio']=-1
    if failure=='inconciliable':t.loc[0,'saldo_componentes_objetivo_mwh_anio']=100
    with pytest.raises(ValueError):sensibilidad_componentes(t,perdida_rendimiento=p,objetivo_tep=60)


def test_saldos_adversos_se_conservan_y_umbral_no_se_recorta():
    t=tabla();t['guaguas_regulares_con_contraste_mwh_anio']=80.;t['saldo_componentes_objetivo_mwh_anio']=-40.
    z=sensibilidad_componentes(t,perdida_rendimiento=.1,objetivo_tep=60)
    u=z['respuesta_y_umbrales'].iloc[0]
    assert u.reduccion_uniforme_coches_para_saldo_cero_pct==-100
    assert u.incremento_nuevas_guaguas_para_saldo_cero_pct==-50
    assert z['controles_consumo'].saldo_componentes_antes_adicionales_mwh_anio.lt(0).all()
