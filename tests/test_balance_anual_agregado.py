"""Agregación emparejada, componentes objetivo y modulación sin frecuencias ficticias."""
import numpy as np
import pandas as pd
import pytest
from movilidad_teide.balance_anual_agregado import agregar_componentes_objetivo,tabla_anual_de_trabajo,coeficientes_modulacion,limites_materialidad

DAYS={'Laborable':260,'Sábado':53,'Domingo':53}


def entradas():
    ids=[];cars=[];common=[];controls=[]
    for i in range(9):
        day=list(DAYS)[i%3];period=f'p{i}'
        ids.append({'matrix_index':i,'anio':2025,'mes_publicado':['Marzo','Julio','Octubre'][i//3],'tipo_dia_publicado':day})
        cars.append({'periodo_id':period,'alternativa_procedencia':'a','demanda_referencia_id':period,'unidad_periodo':'dia',
          'coches_sin_mwh_periodo':100.+i,'coches_con_objetivo_mwh_periodo':60.+i,'alimentacion_otros_mwh_periodo':5.})
        common.append({'periodo_id':period,'demanda_referencia_id':period,'unidad_periodo':'dia','servicios_comunes_sin_mwh_periodo':10.+i,'servicios_comunes_con_mwh_periodo':10.+i})
        controls.append({'periodo_id':period,'matrix_index':i,'tipo_dia_fuente':day,'oferta_suficiente':False,'conservacion_personas_comprobada':True,
          'personas_referencia_dia':2000.+i,'coches_sin_dia':600.+i,'coches_autorizados_dia':500.,'coches_transferidos_dia':100.+i,
          'personas_transferidas_desde_coche_dia':320.+3.2*i,'personas_captadas_desde_otros_modos_dia':30.,'personas_lanzadera_dia':350.+3.2*i})
    return pd.DataFrame(cars),pd.DataFrame(common),pd.DataFrame(controls),pd.DataFrame(ids),dict(DAYS)


def ofertas():
    return pd.DataFrame([{'politica_oferta':p,'tipo_dia':d,'dias_calendario':n,'guaguas_con_contraste_mwh_dia':e} for p,e in [('base',20.),('completa',25.)] for d,n in DAYS.items()])


def test_todas_las_observaciones_conservan_peso_sin_y_con_aunque_oferta_insuficiente():
    args=entradas();old=[a.copy(deep=True) if isinstance(a,pd.DataFrame) else dict(a) for a in args]
    x=agregar_componentes_objetivo(*args);t=x['total'].iloc[0]
    expected=sum((103+j)*n for j,n in enumerate(DAYS.values()))
    assert t.coches_sin_mwh_anio==pytest.approx(expected)
    assert t.servicios_comunes_sin_mwh_anio==t.servicios_comunes_con_mwh_anio
    assert t.coches_sin_mwh_anio-t.coches_con_objetivo_mwh_anio-t.alimentacion_otros_mwh_anio==pytest.approx(35*366)
    assert x['ponderacion'].peso_dias_equivalentes.sum()==pytest.approx(366)
    assert x['por_tipo'].observaciones_con_oferta_D194.eq(0).all()
    assert x['demanda_por_tipo'].coches_autorizados_anio.sum()==pytest.approx(500*366)
    for a,b in zip(args,old):
        if isinstance(a,pd.DataFrame):pd.testing.assert_frame_equal(a,b)
        else:assert a==b


@pytest.mark.parametrize('failure',['car_missing','common_missing','control_missing','unit','demand_id','energy_negative','calendar','capacity_unknown','cars_not_conserved','duplicate_month'])
def test_no_renormalizar_o_mezclar_entradas(failure):
    cars,common,controls,ids,days=entradas()
    if failure=='car_missing':cars=cars.iloc[:-1]
    if failure=='common_missing':common=common.iloc[:-1]
    if failure=='control_missing':controls=controls.iloc[:-1]
    if failure=='unit':common.loc[0,'unidad_periodo']='anio'
    if failure=='demand_id':common.loc[0,'demanda_referencia_id']='otra'
    if failure=='energy_negative':cars.loc[0,'coches_sin_mwh_periodo']=-1
    if failure=='calendar':days['Laborable']=259
    if failure=='capacity_unknown':controls['oferta_suficiente']=None
    if failure=='cars_not_conserved':controls.loc[0,'coches_sin_dia']+=1
    if failure=='duplicate_month':ids.loc[3,'mes_publicado']='Marzo'
    with pytest.raises(ValueError):agregar_componentes_objetivo(cars,common,controls,ids,days)


def test_tabla_anual_no_convierte_componentes_en_ahorro_final_o_frecuencia_cabildo():
    c=agregar_componentes_objetivo(*entradas())['total'];x=tabla_anual_de_trabajo(c,ofertas())
    assert len(x)==2 and x.modulacion_operativa.eq('Cabildo de Tenerife').all()
    assert x.set_index('politica_oferta').loc['base','saldo_componentes_objetivo_mwh_anio']==pytest.approx(15*366)
    assert x.set_index('politica_oferta').loc['completa','saldo_componentes_objetivo_mwh_anio']==pytest.approx(10*366)
    assert x[['operacion_adicional_pendiente_mwh_anio','otros_cambios_netos_pendientes_mwh_anio','con_total_anual_mwh','ahorro_final_mwh_anio','ahorro_final_tep_anio','porcentaje_ahorro_final']].isna().all().all()
    assert not x.operacion_anual_completa_comprobada.any() and not x.cumplimiento_acreditado.any()


@pytest.mark.parametrize('failure',['missing_day','negative','missing_component'])
def test_tabla_no_anualiza_oferta_o_componentes_incompletos(failure):
    c=agregar_componentes_objetivo(*entradas())['total'];o=ofertas()
    if failure=='missing_day':o=o.iloc[:-1]
    if failure=='negative':o.loc[0,'guaguas_con_contraste_mwh_dia']=-1
    if failure=='missing_component':c.loc[0,'alimentacion_otros_mwh_anio']=np.nan
    with pytest.raises(ValueError):tabla_anual_de_trabajo(c,o)


def coef():
    return pd.DataFrame([{'referencia_id':'h','tipo_dia_calendario_aproximado':d,'dias_calendario':n,'base_mwh_dia':20.,'completo_mwh_dia':25.,'incremento_por_dia_sustituido_mwh':5.} for d,n in DAYS.items()])


def test_coeficiente_no_fija_fechas_y_diferencia_incluye_una_vez_consumos():
    x=coeficientes_modulacion(coef());assert x.incremento_por_dia_sustituido_mwh.eq(5).all()
    assert x.fechas_activadas_por_cabildo.isna().all() and x.consumo_adicional_fuera_catalogo_mwh_anio.isna().all()
    assert not x.frecuencia_adoptada.any()
    bad=coef();bad.loc[0,'incremento_por_dia_sustituido_mwh']=6
    with pytest.raises(ValueError):coeficientes_modulacion(bad)


def test_umbral_negativo_no_se_recorta_a_cero_o_se_confunde_con_prevision():
    x=tabla_anual_de_trabajo(agregar_componentes_objetivo(*entradas())['total'],ofertas());l=limites_materialidad(x,objetivo_tep=1000)
    assert l.cambio_neto_adicional_admisible_para_objetivo_mwh_anio.lt(0).all()
    assert np.allclose(l.cambio_neto_adicional_admisible_para_objetivo_mwh_anio,l.saldo_componentes_objetivo_mwh_anio-11630)
    assert not l.cumplimiento_acreditado.any()
