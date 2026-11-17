"""Conservar ámbitos, ausencias y alternativas al integrar el balance parcial."""
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from movilidad_teide.balance_condicionado import (
    CRITERIO_TERRITORIAL, MAGNITUD_ANUAL, repartir_actividad_condicionada,
    calcular_aportes_anuales, comparar_con_lanzaderas, componentes_pendientes)


def reparto_base():
    d = pd.DataFrame({'origen_id': ['a', 'b', 'resto'], 'colectivo': ['c'] * 3,
        'sentido': ['hacia_teide'] * 3, 'corredor_fuente': ['fuente', 'fuente', 'sin_asignar'],
        'corredor_calculo': ['estudio', 'otro_estudio', 'otro'],
        'viajes_persona_media_57_matrices': [1., 3., .5]})
    c = pd.DataFrame({'access_corridor': ['fuente'], 'colectivo': ['c'], 'direccion': ['subida'],
        'anio_calendario': [2028], MAGNITUD_ANUAL: [40.]})
    return d, c


def test_cuotas_conservan_total_anual_y_corredor_fuente_sin_anualizar_media():
    d, c = reparto_base();antes = d.copy(deep=True)
    x = repartir_actividad_condicionada(d, c, criterio=CRITERIO_TERRITORIAL)
    assert x.loc[:1, MAGNITUD_ANUAL].tolist() == [10., 30.]
    assert x.loc[:1, 'corredor_calculo'].tolist() == ['estudio', 'otro_estudio']
    assert x.loc[2, 'viajes_persona_media_57_matrices'] == .5
    assert pd.isna(x.loc[2, MAGNITUD_ANUAL]) and not x.loc[2, 'en_ambito_anual']
    assert x.coches_efectivamente_sustituidos.isna().all()
    assert_frame_equal(d, antes)


def test_eleccion_pendiente_no_adopta_propuesta_ni_reparte():
    d, c = reparto_base()
    x = repartir_actividad_condicionada(d, c)
    assert x[MAGNITUD_ANUAL].isna().all() and x.cuota_territorial_condicionada.isna().all()
    c[MAGNITUD_ANUAL] = np.nan
    x = repartir_actividad_condicionada(d, c, criterio=CRITERIO_TERRITORIAL)
    assert x[MAGNITUD_ANUAL].isna().all()


@pytest.mark.parametrize('fallo', ['negativo', 'infinito', 'duplicado', 'grupo_sin_territorio', 'cuota_nula', 'sentido', 'criterio'])
def test_reparto_rechaza_incoherencias_sin_inventar_cuotas(fallo):
    d, c = reparto_base();criterio = CRITERIO_TERRITORIAL
    if fallo == 'negativo': d.loc[0, 'viajes_persona_media_57_matrices'] = -1
    if fallo == 'infinito': c[MAGNITUD_ANUAL] = np.inf
    if fallo == 'duplicado': c = pd.concat([c, c])
    if fallo == 'grupo_sin_territorio': c['access_corridor'] = 'inexistente'
    if fallo == 'cuota_nula': d.loc[:1, 'viajes_persona_media_57_matrices'] = 0
    if fallo == 'sentido': d.loc[0, 'sentido'] = 'vuelta'
    if fallo == 'criterio': criterio = 'reparto equitativo'
    with pytest.raises(ValueError): repartir_actividad_condicionada(d, c, criterio=criterio)


def entradas_balance():
    d, c = reparto_base();d = d.iloc[:1].copy()
    reparto = repartir_actividad_condicionada(d, c, criterio=CRITERIO_TERRITORIAL)
    r = pd.DataFrame({'origen_id': ['a'], 'sentido': ['hacia_teide'], 'comparacion_calculo_id': ['c'],
        'tipo_representacion_calculo': ['perfil_propio'], 'itinerario_referencia_id': ['r'],
        'itinerario_alimentador_id': ['r'], 'directa_km': [10.], 'alimentador_km': [10.]})
    x = pd.DataFrame({'comparacion_id': ['c', 'c'], 'itinerary_id': ['r', 'r'],
        'rol': ['directa', 'alimentador'], 'clase_propuesta': ['convencional', 'convencional'],
        'longitud_clase_km': [10., 10.]})
    f = pd.DataFrame({'grupo_servicio': ['B00'], 'modo': ['rural'], 'velocidad_kmh': [40],
        'aporte_conjunto_condicionado_min_mj_km': [1.], 'aporte_conjunto_condicionado_max_mj_km': [3.]})
    return reparto, r, x, f, {'local': None, 'convencional': 40, 'rapida': None}


def test_consumo_comun_se_cancela_antes_de_elegir_extremos():
    x = calcular_aportes_anuales(*entradas_balance(), fraccion_coche_alimentador=1)['total_ambito_anual']
    assert x.aporte_diferencia_menor_mj_anio.item() == 0
    assert x.aporte_diferencia_mayor_mj_anio.item() == 0
    assert x.vehiculo_km_directa_anio.item() == 400
    assert x.vehiculo_km_alimentador_anio.item() == 400


def test_desvio_negativo_invierte_extremos_y_no_se_recorta():
    d, r, c, f, v = entradas_balance()
    r['alimentador_km'] = 12.;c.loc[c.rol.eq('alimentador'), 'longitud_clase_km'] = 12.
    x = calcular_aportes_anuales(d, r, c, f, v, fraccion_coche_alimentador=1)['total_ambito_anual'].iloc[0]
    assert x.vehiculo_km_diferencia_anio == -80
    assert x.aporte_diferencia_menor_mj_anio == -240
    assert x.aporte_diferencia_mayor_mj_anio == -80


def test_extremo_sin_coche_no_identifica_energia_del_otro_modo():
    x = calcular_aportes_anuales(*entradas_balance(), fraccion_coche_alimentador=0)['total_ambito_anual'].iloc[0]
    assert x.aporte_diferencia_menor_mj_anio == 400
    assert x.aporte_diferencia_mayor_mj_anio == 1200
    assert componentes_pendientes().componente.str.contains('Alimentación distinta').any()


@pytest.mark.parametrize('fraccion', [-1, 2, True, np.nan])
def test_fraccion_invalida_no_se_corrige(fraccion):
    with pytest.raises(ValueError): calcular_aportes_anuales(*entradas_balance(), fraccion_coche_alimentador=fraccion)


@pytest.mark.parametrize('fallo', ['longitud', 'duplicado', 'factor_negativo', 'extremos_invertidos', 'velocidad', 'origen_ausente'])
def test_integracion_rechaza_incoherencias_materiales(fallo):
    d, r, c, f, v = entradas_balance()
    if fallo == 'longitud': r['directa_km'] = 12
    if fallo == 'duplicado': c = pd.concat([c, c.iloc[[0]]])
    if fallo == 'factor_negativo': f['aporte_conjunto_condicionado_min_mj_km'] = -1
    if fallo == 'extremos_invertidos': f['aporte_conjunto_condicionado_min_mj_km'] = 4
    if fallo == 'velocidad': v['convencional'] = 35
    if fallo == 'origen_ausente': r['origen_id'] = 'otro'
    with pytest.raises(ValueError): calcular_aportes_anuales(d, r, c, f, v, fraccion_coche_alimentador=1)


def test_factor_ausente_no_se_suma_como_cero_y_no_se_oculta_al_agregar():
    d, r, c, f, v = entradas_balance();f['aporte_conjunto_condicionado_min_mj_km'] = np.nan
    x = calcular_aportes_anuales(d, r, c, f, v, fraccion_coche_alimentador=0)['total_ambito_anual']
    assert x.aporte_diferencia_menor_mj_anio.isna().all()
    assert x.aporte_diferencia_mayor_mj_anio.isna().all()


def test_alternativas_no_se_suman_ni_completan_ahorro_y_unidades_coherentes():
    a = calcular_aportes_anuales(*entradas_balance(), fraccion_coche_alimentador=0)['total_ambito_anual']
    buses = pd.DataFrame({'referencia_id': ['uno', 'dos'], 'referencia': ['Diésel', 'Híbrida'],
        'energia_identificada_mj_anio': [500., 1500.]})
    x = comparar_con_lanzaderas(a, buses)
    assert len(x) == 2
    assert x.diferencia_parcial_menor_mj_anio.tolist() == [-100., -1100.]
    assert np.allclose(x.diferencia_parcial_mayor_mwh_anio * 3600, x.diferencia_parcial_mayor_mj_anio)
    assert np.allclose(x.diferencia_parcial_mayor_tep_anio * 41868, x.diferencia_parcial_mayor_mj_anio)
    assert x.filter(regex='^(energia_total_sistema|ahorro_total_sistema)').isna().all().all()
    assert (x.diferencia_parcial_menor_mj_anio <= x.diferencia_parcial_mayor_mj_anio).all()


def test_propuesta_territorial_conectada_al_excel_sin_activar_central(parametros_historicos):
    from pathlib import Path
    from movilidad_teide.parametros import leer_parametros
    p = parametros_historicos
    f = next(x for x in p['parametros'] if x['id'] == 'criterio_reparto_territorial_anual')
    assert f['propuesta']['valor'] == CRITERIO_TERRITORIAL
    assert f['valor_utilizado'] is None


def test_actividad_negativa_no_produce_ahorro_artificial():
    d, r, c, f, v = entradas_balance();d[MAGNITUD_ANUAL] = -1
    with pytest.raises(ValueError): calcular_aportes_anuales(d, r, c, f, v, fraccion_coche_alimentador=1)


def datos_cupo():
    from movilidad_teide.balance_condicionado import revisar_cupo_y_oferta
    p=pd.DataFrame({'access_corridor':['a','b'],'colectivo':['c','c'],'direccion':['subida','subida'],
        'viajes_persona_proyectados':[2400.,1200.],'viajes_persona_captables_proyectados':[600.,300.]})
    o=pd.DataFrame({'corredor':['a','b'],'subidas_dia':[1,1],'bajadas_dia':[1,1]})
    return revisar_cupo_y_oferta,p,o


def test_cupo_es_global_conserva_personas_y_no_suma_captacion_dos_veces():
    f,p,o=datos_cupo();x=f(p,o,cupo_global_dia=2,dias=100,ocupacion=3,fraccion_coche=.75,plazas=10)
    assert x.techo_visitas_coche_autorizadas_condicionado.sum()==pytest.approx(200)
    assert x.visitas_coche_sin_condicionadas.sum()==900
    assert x.personas_que_requeririan_otro_tratamiento.sum()==2100
    assert x.plazas_necesarias_subida_si_transferencia_completa.sum()==2325
    assert x.coches_efectivamente_sustituidos.isna().all()
    assert not x.operacion_viable_validada.any()


def test_cupo_holgado_no_fabrica_transferencia_y_regreso_limita_capacidad():
    f,p,o=datos_cupo();o.loc[0,'bajadas_dia']=0
    x=f(p,o,cupo_global_dia=100,dias=100,ocupacion=3,fraccion_coche=.75,plazas=10)
    assert x.personas_que_requeririan_otro_tratamiento.sum()==0
    assert x.loc[x.corredor.eq('a'),'capacidad_ida_vuelta_teorica_anio'].item()==0
    assert x.loc[x.corredor.eq('a'),'saldo_plazas_anual_condicionado'].item()<0


@pytest.mark.parametrize('cambio',['corridor','duplicado','captacion','negativo'])
def test_prueba_cupo_rechaza_ambitos_y_cantidades_incoherentes(cambio):
    f,p,o=datos_cupo()
    if cambio=='corridor':o.loc[0,'corredor']='otro'
    if cambio=='duplicado':p=pd.concat([p,p.iloc[[0]]])
    if cambio=='captacion':p.loc[0,'viajes_persona_captables_proyectados']=3000
    if cambio=='negativo':o.loc[0,'subidas_dia']=-1
    with pytest.raises(ValueError):f(p,o,cupo_global_dia=2,dias=100,ocupacion=3,fraccion_coche=.75,plazas=10)


def test_regreso_condicionado_conserva_parejas_y_no_modifica_original():
    from movilidad_teide.balance_condicionado import emparejar_retornos_condicionados
    f,p,o=datos_cupo()
    d,c=reparto_base();up=repartir_actividad_condicionada(d,c,criterio=CRITERIO_TERRITORIAL)
    down=up.assign(sentido='desde_teide',recorridos_coche_equivalentes_condicionados=999.)
    both=pd.concat([up,down],ignore_index=True);before=both.copy(deep=True)
    x=emparejar_retornos_condicionados(both)
    assert x.loc[x.sentido.eq('desde_teide'),MAGNITUD_ANUAL].iloc[:2].tolist()==[10.,30.]
    assert x.loc[x.origen_id.eq('resto'),MAGNITUD_ANUAL].isna().all()
    assert_frame_equal(both,before)
    with pytest.raises(ValueError):emparejar_retornos_condicionados(both.iloc[:-1])
