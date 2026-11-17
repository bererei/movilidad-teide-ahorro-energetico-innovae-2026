from pathlib import Path
import json, hashlib, platform
import numpy as np, pandas as pd
from movilidad_teide.parametros import leer_parametros
from movilidad_teide.flota_cerrada import construir_inventario, asignar_inventario, comprobar_intervalos
from movilidad_teide.sensibilidad_modal import reasignar_en_horario_conservado
from movilidad_teide.cierre_operacion_agregada import valorar_movimientos
from .tipos import Etapa

def calcular_inventario(root, parametros, previa):
    """Asigno identidades físicas, compruebo capacidad y revaloro la misma actividad."""
    R216 = Path(root)
    S216 = R216 / 'data/silver/energia_turismos/20261101_modulacion_cabildo_30'
    P216 = parametros
    V216 = {p['id']: p['valor_utilizado'] for p in P216['parametros']}
    RD216 = lambda p: pd.read_csv(p, sep=';', float_precision='round_trip')
    F216 = previa.auxiliares['vehiculos'].copy()
    MV216 = previa.auxiliares['movimientos'].copy()
    PA216 = previa.auxiliares['pares'].copy()
    (inventory216, positions216) = construir_inventario(F216, total=V216['vehiculos_contrato_contraste'])
    Z216 = asignar_inventario(MV216, F216, inventory216, reserva_minima=V216['reserva_minima_dentro_flota'], regulacion=V216['regulacion_min'])
    T216 = comprobar_intervalos(MV216, previa.tablas['limites_temporales'].copy(), intervalo_ordinario=V216['intervalo_minimo_subidas_min'], intervalo_punta=V216['intervalo_refuerzo_punta_min'])
    diag216 = Z216['diagnostico'].merge(previa.tablas['diagnostico_por_observacion'].copy()[['politica', 'observacion', 'es_diseno_p85', 'dias_equivalentes']], on=['politica', 'observacion'], validate='one_to_one')
    flags216 = T216.groupby(['politica', 'observacion'], as_index=False).agg(cumple_intervalo_vigente=('cumple_regla_vigente', 'all'), cumple_intervalos_propuestos=('cumple_regla_propuesta', 'all'))
    diag216 = diag216.merge(flags216, on=['politica', 'observacion'], validate='one_to_one')
    stops216 = RD216(R216 / 'data/silver/operacion/paradas/referencias_paradas.csv')
    goals216 = RD216(R216 / 'data/silver/energia_turismos/20261031_sensibilidad_anual/objetivos_por_corredor.csv')
    goals216 = goals216.loc[goals216.caso_sensibilidad.eq('referencia_3_2')]
    p85day216 = RD216(R216 / 'data/silver/energia_turismos/20261031_revision_p85/p85_diario.csv')
    loads216 = []
    pairs216 = []
    for ((policy216, idx216), moves216) in Z216['movimientos'].groupby(['politica', 'observacion']):
        chains216 = PA216.loc[PA216.politica.eq(policy216) & PA216.observacion.eq(idx216)]
        goals_now216 = (p85day216[['punto', 'personas_p85_total_dia']].rename(columns={'personas_p85_total_dia': 'demanda_lanzadera_condicionada_dia'}) if idx216 == -85 else goals216.loc[goals216.matrix_index.eq(idx216)]).copy().assign(tipo_dia='periodo', dias_calendario=1)
        cap216 = int(V216['plazas_guagua'] * V216['ocupacion_diseno'])
        checked216 = reasignar_en_horario_conservado(moves216, chains216, goals_now216, stops216, capacidad=cap216, margen=V216['margen_enlace_interior_min'], espera=V216['espera_max_lanzadera_min'], estancia=V216['estancia_min_visita_min'])
        full216 = goals_now216.copy()
        full216['demanda_lanzadera_condicionada_dia'] = full216.punto.map(chains216.groupby('punto').size()) * cap216
        reasignar_en_horario_conservado(moves216, chains216, full216, stops216, capacidad=cap216, margen=V216['margen_enlace_interior_min'], espera=V216['espera_max_lanzadera_min'], estancia=V216['estancia_min_visita_min'])
        loads216.append(checked216['cargas_tramos'].assign(politica=policy216, observacion=idx216))
        pairs216.append(checked216['pares'].assign(politica=policy216, observacion=idx216))
    diag216['demanda_y_cadenas_completas_comprobadas'] = True
    diag216['circulacion_30_reglas_propuestas_comprobada'] = diag216.cumple_minimo_sustitucion & diag216.cierre_de_bases_comprobado & diag216.cumple_intervalos_propuestos
    assert diag216.circulacion_30_reglas_propuestas_comprobada.all()
    assert diag216.vehiculos_programados.max() == 27 and diag216.vehiculos_sin_programar.min() == 3
    p85check216 = previa.tablas['comprobacion_p85'].copy()
    assert p85check216.sin_asignacion.max() < 1e-08 and p85check216.p85_diario_comprobado.all()
    annual216 = diag216.groupby('politica', as_index=False).agg(observaciones_y_diseno=('observacion', 'size'), flota_total=('flota_total', 'max'), maximo_programadas=('vehiculos_programados', 'max'), minimo_sin_programar=('vehiculos_sin_programar', 'min'), circulacion_30_reglas_propuestas_comprobada=('circulacion_30_reglas_propuestas_comprobada', 'all'), cumple_intervalo_vigente=('cumple_intervalo_vigente', 'all'), dias_equivalentes=('dias_equivalentes', 'sum'))
    annual216['disponibilidad_y_respuesta_incidentes_validadas'] = False
    annual216['propuesta_adoptada'] = False
    assert np.allclose(annual216.dias_equivalentes, 366, atol=1e-08, rtol=0)
    factors216 = RD216(R216 / 'data/silver/copert/20261029_energia_anual_lanzaderas/consumo_por_recorrido_y_referencia.csv')
    costs216 = []
    for ((policy216, idx216), moves216) in Z216['movimientos'].groupby(['politica', 'observacion']):
        e216 = valorar_movimientos(moves216, factors216, carga_comercial=V216['carga_copert'], perdida_rendimiento=V216['perdida_rendimiento_guaguas_contraste'])
        weight216 = diag216.loc[diag216.politica.eq(policy216) & diag216.observacion.eq(idx216), 'dias_equivalentes'].item()
        e216['hot_mwh_anio'] = e216.hot_mwh * weight216
        e216['vehiculos_km_anio'] = e216.km_recorrido * weight216
        costs216.append(e216.groupby('referencia_id', as_index=False)[['hot_mwh_anio', 'vehiculos_km_anio']].sum().assign(politica=policy216))
    costs216 = pd.concat(costs216).groupby(['politica', 'referencia_id'], as_index=False)[['hot_mwh_anio', 'vehiculos_km_anio']].sum()
    previous_cost216 = previa.tablas['costes_anuales'].copy().sort_values(['politica', 'referencia_id']).reset_index(drop=True)
    assert np.allclose(costs216.hot_mwh_anio, previous_cost216.hot_mwh_anio, atol=1e-09, rtol=0)
    assert np.allclose(costs216.vehiculos_km_anio, previous_cost216.vehiculos_km_anio, atol=1e-08, rtol=0)
    balance216 = previa.tablas['balance_construcciones_condicionadas'].copy()
    balance216['circulacion_30_reglas_propuestas_comprobada'] = balance216.politica.map(annual216.set_index('politica').circulacion_30_reglas_propuestas_comprobada)
    balance216['saldo_oferta_estudio_30_reglas_propuestas_mwh_anio'] = np.where(balance216.circulacion_30_reglas_propuestas_comprobada, balance216.saldo_construccion_condicionada_mwh_anio, np.nan)
    balance216['regla_de_reserva'] = 'Mínimo absoluto dentro de flota total; libres ya cuentan como sustitución'
    balance216['reserva_minima_vehiculos'] = V216['reserva_minima_dentro_flota']
    balance216['cambio_de_energia_por_reserva_mwh_anio'] = 0.0
    balance216['propuesta_adoptada'] = False
    peak216 = Z216['balance_bases'].merge(diag216[['politica', 'observacion', 'vehiculos_sin_programar']], on=['politica', 'observacion'], validate='many_to_one')
    peak216 = peak216.loc[peak216.vehiculos_sin_programar.eq(V216['reserva_minima_dentro_flota'])].copy()
    peak216['sustituta_local_sin_traslado'] = peak216.sin_programar_en_base.gt(0)
    peak216['respuesta_inmediata_en_todas_las_bases_acreditada'] = False
    robustness216 = []
    for d216 in diag216.itertuples():
        for unavailable216 in range(V216['reserva_minima_dentro_flota'] + 2):
            robustness216.append({'politica': d216.politica, 'observacion': d216.observacion, 'indisponibles_simultaneas': unavailable216, 'flota_disponible_por_cantidad': d216.flota_total - unavailable216, 'programadas_necesarias': d216.vehiculos_programados, 'cumple_solo_cota_global_de_cantidad': d216.flota_total - unavailable216 >= d216.vehiculos_programados, 'respuesta_por_ubicacion_demostrada': False, 'probabilidad_asignada': False})
    compare216 = balance216.loc[balance216.politica.eq('Accesos e interior según reservas') & balance216.caso_pendiente.eq('Referencia del Excel')].copy()
    compare216['categoria_copert'] = compare216.referencia_id.map({'referencia_guagua_1': 'Guagua urbana diésel15–18t; control', 'referencia_guagua_2': 'Autocar diésel<=18t; referencia elegida', 'referencia_guagua_3': 'Guagua urbana híbrida; sustituto provisional'})
    tables216 = {'inventario_30': inventory216, 'resumen_inventario_bases': positions216, 'asignacion_unidades': Z216['asignaciones'], 'balance_de_bases': Z216['balance_bases'], 'diagnostico_diario': diag216, 'intervalos_propuestos': T216, 'factibilidad_anual': annual216, 'balance_anual_propuesta': balance216, 'cobertura_local_puntas': peak216, 'sensibilidad_indisponibilidad': pd.DataFrame(robustness216), 'comparacion_referencias_consumo': compare216, 'costes_anuales_reproducidos': costs216}
    return Etapa(tables216, {'movimientos_con_identidad_fisica': Z216['movimientos'], 'cargas_tramos_revisadas': pd.concat(loads216, ignore_index=True), 'pares_revisados': pd.concat(pairs216, ignore_index=True)})
