"""Conservación de personas, coste adicional y límites del balance parcial."""
import numpy as np
import pandas as pd
import pytest
from movilidad_teide.materialidad_pendientes import (actividad_otros_captados,
    consumo_alimentacion_unitaria, contrastar_otros_consumos)
from movilidad_teide.mezcla_turismos import ALQUILER, PARTICULAR


@pytest.fixture
def datos():
    diario=pd.DataFrame({'tipo_dia_publicado':['Laborable','Sábado','Domingo'],
        'access_corridor':['norte']*3,'colectivo':['extranjero']*3,
        'viajes_persona_dia_referencia':[100.]*3,'viajes_persona_captables_dia_referencia':[10.,20.,30.],
        'dias_calendario':[260,53,53]})
    demanda=pd.DataFrame([{'origen_id':o,'colectivo':'extranjero','sentido':s,
        'corredor_fuente':'norte','viajes_persona_media_57_matrices':w}
        for o,w in [('a',1.),('b',3.)] for s in ['hacia_teide','desde_teide']])
    recorridos=pd.DataFrame([{'origen_id':o,'sentido':s,'comparacion_calculo_id':o,
        'itinerario_alimentador_id':o+s,'alimentador_km':3. if o=='a' else 4.}
        for o in ['a','b'] for s in ['hacia_teide','desde_teide']])
    tipos=pd.DataFrame([{'comparacion_id':o,'itinerary_id':o+s,'rol':'alimentador',
        'clase_propuesta':c,'longitud_clase_km':km}
        for o,parts in [('a',[('local',1.),('convencional',2.)]),('b',[('convencional',4.)])]
        for s in ['hacia_teide','desde_teide'] for c,km in parts])
    factores=pd.DataFrame([{'grupo_servicio':g,'modo':m,'velocidad_kmh':v,
        'aporte_conjunto_condicionado_min_mj_km':f,'aporte_conjunto_condicionado_max_mj_km':f}
        for g in [ALQUILER,PARTICULAR] for m,v,f in [('urban_off_peak',20,3.),('rural',40,2.),('highway',80,1.)]])
    return diario,demanda,recorridos,tipos,factores,{'local':20,'convencional':40,'rapida':80}


def test_personas_no_se_dividen_por_ocupacion_ni_se_duplican_por_regreso(datos):
    diario,demanda,*_=datos;original=diario.copy(deep=True)
    x=actividad_otros_captados(diario,demanda,fraccion_coche=.75,anio=2028)
    assert x['diario'].personas_otros_captados_anio.sum()==1312.5
    a=x['actividad'];assert not any('coche' in c for c in a.columns)
    assert a.groupby('sentido').personas_trayecto_anio.sum().to_dict()=={'desde_teide':1312.5,'hacia_teide':1312.5}
    assert a.query('origen_id=="a"').personas_trayecto_anio.eq(328.125).all()
    pd.testing.assert_frame_equal(diario,original)


@pytest.mark.parametrize('bad',[True,-.1,1.1,np.nan])
def test_no_se_aplica_cuota_modal_invalida(datos,bad):
    with pytest.raises(ValueError):actividad_otros_captados(*datos[:2],fraccion_coche=bad,anio=2028)


@pytest.mark.parametrize('error',['dia_falta','calendario','captacion_excesiva','duplicado'])
def test_no_se_pierde_demanda_por_calendario_o_conversion(datos,error):
    d,m,*_=datos
    if error=='dia_falta':d=d.iloc[:-1]
    if error=='calendario':d.loc[0,'dias_calendario']=259
    if error=='captacion_excesiva':d.loc[0,'viajes_persona_captables_dia_referencia']=101
    if error=='duplicado':d=pd.concat([d,d.iloc[[0]]])
    with pytest.raises(ValueError):actividad_otros_captados(d,m,fraccion_coche=.75,anio=2028)


def test_coche_por_persona_solo_hasta_cabecera_y_un_regreso(datos):
    d,m,r,c,f,s=datos;a=actividad_otros_captados(d,m,fraccion_coche=.75,anio=2028)['actividad']
    z=consumo_alimentacion_unitaria(a,r,c,f,s)
    # A:1km*3+2km*2=7MJ; B:4km*2=8MJ; ambos sentidos.
    assert np.allclose(z['resumen'].consumo_ensayo_mj_anio,1312.5*(.25*7+.75*8)*2)
    assert z['resumen'].visitas_persona_otro_modo_anio.eq(1312.5).all()
    assert z['resumen'].energia_real_alimentacion_mwh_anio.isna().all()
    # La persona no se cuenta otra vez por cada clase viaria.
    assert len(z['resumen'])==2
    assert np.allclose(z['resumen'].vehiculo_km_ensayo_anio,1312.5*(.25*3+.75*4)*2)


@pytest.mark.parametrize('error',['ruta','factor','extremos','longitud','clase'])
def test_no_ocultar_falta_de_factores_o_geografia(datos,error):
    d,m,r,c,f,s=datos;a=actividad_otros_captados(d,m,fraccion_coche=.75,anio=2028)['actividad']
    if error=='ruta':r=r.iloc[:-1]
    if error=='factor':f=f.iloc[:-1]
    if error=='extremos':f.loc[0,'aporte_conjunto_condicionado_max_mj_km']=9
    if error=='longitud':c.loc[0,'longitud_clase_km']=-1
    if error=='clase':c.loc[0,'clase_propuesta']='desconocida'
    with pytest.raises(ValueError):consumo_alimentacion_unitaria(a,r,c,f,s)


def test_recargo_y_alimentacion_se_cuentan_una_sola_vez_sin_ahorro_ficticio():
    c=pd.DataFrame({'alternativa_procedencia':['a'],'sin_subtotal_hot_identificado_mwh_anio':[100.],
        'con_subtotal_hot_identificado_mwh_anio':[50.],'diferencia_hot_identificada_mwh_anio':[50.],
        'recargo_operativo_contraste_mwh_anio':[5.],'saldo_parcial_tras_contraste_mwh_anio':[45.]})
    a=pd.DataFrame({'alternativa_procedencia':['a'],'consumo_ensayo_mwh_anio':[10.]})
    z=contrastar_otros_consumos(c,a,anio=2028,objetivo_tep=1).iloc[0]
    assert z.con_subtotal_ampliado_ensayo_mwh_anio==65
    assert z.saldo_parcial_ampliado_ensayo_mwh_anio==35
    assert z.otros_costes_netos_criticos_para_objetivo_mwh_anio==pytest.approx(35-11.63)
    assert z.coeficiente_instalaciones_mwh_por_kw_medio==8.784
    assert pd.isna(z.ahorro_total_sistema_mwh_anio) and not z.cumplimiento_acreditado
    assert pd.isna(z.potencia_instalaciones_elegida_kw)
    c.loc[0,'con_subtotal_hot_identificado_mwh_anio']=110
    c.loc[0,'diferencia_hot_identificada_mwh_anio']=-10
    c.loc[0,'saldo_parcial_tras_contraste_mwh_anio']=-15
    bad=contrastar_otros_consumos(c,a,anio=2025,objetivo_tep=1).iloc[0]
    assert bad.saldo_parcial_ampliado_ensayo_mwh_anio==-25
    assert bad.potencia_media_equivalente_para_objetivo_kw<0
    assert bad.coeficiente_instalaciones_mwh_por_kw_medio==8.76


def test_saldo_incoherente_o_alternativa_perdida_se_rechazan():
    c=pd.DataFrame({'alternativa_procedencia':['a'],'sin_subtotal_hot_identificado_mwh_anio':[100.],
        'con_subtotal_hot_identificado_mwh_anio':[50.],'diferencia_hot_identificada_mwh_anio':[0.],
        'recargo_operativo_contraste_mwh_anio':[5.],'saldo_parcial_tras_contraste_mwh_anio':[45.]})
    a=pd.DataFrame({'alternativa_procedencia':['a'],'consumo_ensayo_mwh_anio':[10.]})
    with pytest.raises(ValueError):contrastar_otros_consumos(c,a,anio=2028,objetivo_tep=1)
    a['alternativa_procedencia']='b'
    with pytest.raises(ValueError):contrastar_otros_consumos(c,a,anio=2028,objetivo_tep=1)


def test_servicios_comunes_cancelan_diferencia_sin_inventar_sus_consumos():
    from movilidad_teide.materialidad_pendientes import aplicar_cambio_servicios_existentes
    x=pd.DataFrame({'caso_ocupacion':['caso'],'alternativa_procedencia':['alternativa'],
        'sin_subtotal_hot_identificado_mwh_anio':[100.],
        'con_subtotal_ampliado_ensayo_mwh_anio':[70.],'saldo_parcial_ampliado_ensayo_mwh_anio':[30.]})
    before=x.copy(deep=True)
    z=aplicar_cambio_servicios_existentes(x,cambio_neto_mwh_anio=0).iloc[0]
    # Cualquier K común se cancela, pero sus dos importes continúan desconocidos.
    for k in [1.,10000.]:assert (100+k)-(70+k)==z.diferencia_condicionada_transporte_mwh_anio
    assert pd.isna(z.consumo_comun_servicios_sin_mwh_anio) and pd.isna(z.consumo_comun_servicios_con_mwh_anio)
    assert pd.isna(z.energia_total_transporte_sin_mwh_anio) and pd.isna(z.porcentaje_ahorro_total_transporte)
    assert pd.isna(z.otros_cambios_transporte_no_representados_mwh_anio) and not z.cumplimiento_acreditado
    costly=aplicar_cambio_servicios_existentes(x,cambio_neto_mwh_anio=40).iloc[0]
    assert costly.diferencia_condicionada_transporte_mwh_anio==-10
    assert costly.variacion_restante_critica_para_60tep_mwh_anio<0
    cheaper=aplicar_cambio_servicios_existentes(x,cambio_neto_mwh_anio=-5).iloc[0]
    assert cheaper.diferencia_condicionada_transporte_mwh_anio==35
    pd.testing.assert_frame_equal(x,before)


@pytest.mark.parametrize('bad',[None,np.nan,np.inf,True,'0'])
def test_cambio_de_servicios_ausente_no_se_convierte_en_cero(bad):
    from movilidad_teide.materialidad_pendientes import aplicar_cambio_servicios_existentes
    with pytest.raises(ValueError):aplicar_cambio_servicios_existentes(pd.DataFrame(),cambio_neto_mwh_anio=bad)


def test_cambio_servicios_rechaza_alternativas_duplicadas_y_saldos_incoherentes():
    from movilidad_teide.materialidad_pendientes import aplicar_cambio_servicios_existentes
    x=pd.DataFrame({'caso_ocupacion':['caso'],'alternativa_procedencia':['alternativa'],
        'sin_subtotal_hot_identificado_mwh_anio':[100.],
        'con_subtotal_ampliado_ensayo_mwh_anio':[70.],'saldo_parcial_ampliado_ensayo_mwh_anio':[30.]})
    with pytest.raises(ValueError):aplicar_cambio_servicios_existentes(pd.concat([x,x]),cambio_neto_mwh_anio=0)
    x.loc[0,'saldo_parcial_ampliado_ensayo_mwh_anio']=99
    with pytest.raises(ValueError):aplicar_cambio_servicios_existentes(x,cambio_neto_mwh_anio=0)


def test_cambio_servicios_se_resuelve_desde_el_excel_con_fuente_y_motivo(tmp_path):
    from pathlib import Path
    from openpyxl import load_workbook
    from movilidad_teide.parametros import leer_parametros,_guardar_con_vista
    root=Path(__file__).resolve().parents[1]
    key='cambio_neto_servicios_existentes_mwh_anio'
    params=leer_parametros(root);new=next(p for p in params['parametros'] if p['id']==key)
    assert new['valor_utilizado']==0 and new['modo_efectivo']=='Propuesta'
    assert 'H120' in new['propuesta']['fuente'] and 'por hipótesis' in new['propuesta']['justificacion']
    w=load_workbook(root/'config/parametros_modelo.xlsx');esc=w['Escenarios']
    row=next(f for f in range(7,esc.max_row+1) if esc.cell(f,1).value=='Central' and esc.cell(f,13).value==key)
    esc.cell(row,7,'Manual');esc.cell(row,8,-7.5);esc.cell(row,9,'Contraste técnico con reducción explícita; no dato observado.')
    path=tmp_path/'parametros.xlsx';_guardar_con_vista(w,path);changed=leer_parametros(root,path=path)
    assert next(p for p in changed['parametros'] if p['id']==key)['valor_utilizado']==-7.5
    assert [p for p in params['parametros'] if p['id']!=key]==[p for p in changed['parametros'] if p['id']!=key]


def test_totales_comunes_no_generan_ahorro_y_complemento_desconocido_no_es_cero():
    from movilidad_teide.materialidad_pendientes import completar_totales_representados
    x=pd.DataFrame({'alternativa_procedencia':['a'],'sin_subtotal_hot_identificado_mwh_anio':[100.],
        'con_subtotal_ampliado_ensayo_mwh_anio':[80.],'diferencia_condicionada_transporte_mwh_anio':[20.]})
    z=completar_totales_representados(x,comun_mwh_anio=100).iloc[0]
    assert z.sin_total_ambito_representado_mwh_anio==200 and z.con_total_ambito_representado_mwh_anio==180
    assert z.porcentaje_reduccion_ambito_representado==10
    assert pd.isna(z.sin_total_ambito_ampliado_mwh_anio) and pd.isna(z.porcentaje_reduccion_ambito_ampliado)
    assert not z.cumplimiento_acreditado
    q=completar_totales_representados(x,comun_mwh_anio=100,complemento_mwh_anio=200).iloc[0]
    assert q.sin_total_ambito_ampliado_mwh_anio==400 and q.con_total_ambito_ampliado_mwh_anio==380
    assert q.porcentaje_reduccion_ambito_ampliado==5


@pytest.mark.parametrize('bad',[-1,np.nan,np.inf,True])
def test_no_se_acepta_consumo_comun_invalido(bad):
    from movilidad_teide.materialidad_pendientes import completar_totales_representados
    with pytest.raises(ValueError):completar_totales_representados(pd.DataFrame(),comun_mwh_anio=bad)


def test_porcentaje_negativo_y_denominador_nulo_se_conservan():
    from movilidad_teide.materialidad_pendientes import completar_totales_representados
    x=pd.DataFrame({'alternativa_procedencia':['a','b'],'sin_subtotal_hot_identificado_mwh_anio':[100.,0.],
        'con_subtotal_ampliado_ensayo_mwh_anio':[110.,0.],'diferencia_condicionada_transporte_mwh_anio':[-10.,0.]})
    z=completar_totales_representados(x,comun_mwh_anio=0)
    assert z.loc[0,'porcentaje_reduccion_ambito_representado']==-10
    assert pd.isna(z.loc[1,'porcentaje_reduccion_ambito_representado'])


def test_guaguas_comunes_cuentan_interior_ida_vuelta_una_vez():
    from movilidad_teide.materialidad_pendientes import estimar_guaguas_comunes
    from movilidad_teide.balance_condicionado import MAGNITUD_ANUAL
    a=pd.DataFrame({'rama':['antes','antes'],'origen_id':['a','a'],'colectivo':['c','c'],
        'sentido':['hacia_teide','desde_teide'],'en_ambito_anual':[True,True],MAGNITUD_ANUAL:[10.,10.]})
    r=pd.DataFrame({'origen_id':['a','a'],'sentido':['hacia_teide','desde_teide'],
        'terminal_calculo':['t','t'],'directa_km':[20.,22.]})
    p=pd.DataFrame({'terminal_calculo':['t'],'patron_id':['zona_proxima'],'longitud_interior_ida_vuelta_km':[10.]})
    z=estimar_guaguas_comunes(a,r,p,ocupacion_coche=2,fraccion_coche=.5,ocupacion_guagua=10,factor_mj_km=3.6)
    assert z.personas_no_coche_sentido_anio.tolist()==[20.,20.]
    assert z.guaguas_equivalentes_sentido_anio.tolist()==[2.,2.]
    assert z.vehiculo_km_comunes_anio.sum()==2*(20+22+10)
    assert z.energia_comun_mwh_anio.sum()==pytest.approx(104/1000)
    bad=r.iloc[:1]
    with pytest.raises(ValueError):estimar_guaguas_comunes(a,bad,p,ocupacion_coche=2,fraccion_coche=.5,ocupacion_guagua=10,factor_mj_km=3.6)


def test_nuevos_controles_comunes_estan_conectados_y_no_modifican_la_referencia():
    import json
    from pathlib import Path
    from movilidad_teide.parametros import leer_parametros
    root=Path(__file__).resolve().parents[1]
    # Contrato D184 con su estado conservado, anterior a las elecciones D212.
    actual=json.loads((root/'tests/fixtures/parametros_contrato_comunes.json').read_text())['parametros']
    prior=json.loads((root/'tests/fixtures/parametros_contrato_previo.json').read_text())['parametros']
    added={'criterio_guaguas_comunes','consumo_comun_complementario_mwh_anio'}
    assert [p for p in actual['parametros'] if p['id'] not in added]==prior['parametros']
    assert next(p for p in actual['parametros'] if p['id']=='consumo_comun_complementario_mwh_anio')['valor_utilizado'] is None

    # La revisión de pendientes reconoce el complemento sin declararlo cero o inocuo.
    from movilidad_teide.balance_condicionado import revisar_elecciones_para_cierre
    pendientes=revisar_elecciones_para_cierre(actual).set_index('id')
    assert pendientes.loc['consumo_comun_complementario_mwh_anio','tratamiento_actual']=='Total del ámbito ampliado pendiente'
