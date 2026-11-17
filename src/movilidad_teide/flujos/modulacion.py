from pathlib import Path
import json, hashlib, platform, math
import numpy as np, pandas as pd
from movilidad_teide.parametros import leer_parametros
from movilidad_teide.modulacion_cabildo import modular_por_reservas, pool_fijo_por_bases, balance_modulacion
from movilidad_teide.cierre_operacion_agregada import valorar_movimientos
from movilidad_teide.ampliacion_reservas import limites_por_intervalo
from movilidad_teide.reservas_lanzaderas import auditar_perfil_reservado_p85
from movilidad_teide.horarios_conjuntos import PUNTOS
from .tipos import Etapa

def calcular_modulacion(root, parametros, previa):
    """Reconstruyo la oferta por reservas y la valoro con el balance de pendiente recién calculado."""
    root_m = Path(root)
    params_m = parametros
    v_m = {p['id']: p['valor_utilizado'] for p in params_m['parametros']}
    read_m = lambda p: pd.read_csv(p, sep=';', float_precision='round_trip')
    paths_m = {'control': 'data/silver/energia_turismos/20261101_referencia_diesel_y_descenso/condiciones_operacion_conservadas.csv', 'moves': 'data/silver/energia_turismos/20261031_activacion_refuerzos/movimientos_por_perfil.csv', 'pairs': 'data/silver/energia_turismos/20261031_activacion_refuerzos/cadenas_por_perfil.csv', 'ext_moves': 'data/silver/energia_turismos/20261031_ampliacion_capacidad/movimientos.csv', 'ext_pairs': 'data/silver/energia_turismos/20261031_ampliacion_capacidad/pares.csv', 'goals': 'data/silver/energia_turismos/20261031_sensibilidad_anual/objetivos_por_corredor.csv', 'stops': 'data/silver/operacion/paradas/referencias_paradas.csv', 'factors': 'data/silver/copert/20261029_energia_anual_lanzaderas/consumo_por_recorrido_y_referencia.csv', 'energy_previous': 'data/silver/energia_turismos/20261101_referencia_diesel_y_descenso/energia_guaguas_anual.csv', 'base': 'data/silver/energia/referencias_unitarias/pendiente_turismos/balance_anual_con_ajuste_convencional.csv', 'p85_day': 'data/silver/energia_turismos/20261031_revision_p85/p85_diario.csv', 'p85_hour': 'data/silver/energia_turismos/20261031_revision_p85/p85_horario.csv'}
    x_m = {k: read_m(root_m / p) for (k, p) in paths_m.items()}
    x_m['base'] = previa.tablas['balance_anual_con_ajuste_convencional'].copy()
    obs_m = x_m['control']
    assert len(obs_m) == 9 and abs(obs_m.dias_equivalentes_ponderacion.sum() - 366) < 1e-08
    allg_m = x_m['goals'].loc[x_m['goals'].caso_sensibilidad.eq('referencia_3_2')].copy()
    policies_m = [('Accesos modulados; interior regular', False), ('Accesos e interior según reservas', True)]
    records_m = []
    fleets_m = []
    moves_m = []
    links_m = []
    loads_m = []
    bounds_m = []
    costs_m = []
    p85checks_m = []
    jobs_m = [(int(c.matrix_index), c.perfil_coste, float(c.dias_equivalentes_ponderacion), False) for c in obs_m.itertuples()]
    jobs_m.append((-85, 'P089', 0.0, True))
    for (idx_m, pid_m, days_m, design_m) in jobs_m:
        ext_m = not pid_m.startswith('P')
        key_m = 'ensayo_id' if ext_m else 'perfil_id'
        mo_m = x_m['ext_moves' if ext_m else 'moves'].loc[lambda z: z[key_m].eq(pid_m)].copy().assign(tipo_dia='periodo', dias_calendario=1)
        pa_m = x_m['ext_pairs' if ext_m else 'pairs'].loc[lambda z: z[key_m].eq(pid_m)].copy().assign(tipo_dia='periodo', dias_calendario=1)
        if design_m:
            goals_m = x_m['p85_day'][['punto', 'personas_p85_total_dia']].rename(columns={'personas_p85_total_dia': 'demanda_lanzadera_condicionada_dia'}).assign(tipo_dia='periodo', dias_calendario=1, matrix_index=-85)
        else:
            goals_m = allg_m.loc[allg_m.matrix_index.eq(idx_m)].copy().assign(tipo_dia='periodo', dias_calendario=1)
        for (policy_m, trim_m) in policies_m:
            z_m = modular_por_reservas(mo_m, pa_m, goals_m, x_m['stops'], v_m, interior_solo_reservas=trim_m)
            identity_m = {'politica': policy_m, 'observacion': idx_m, 'es_diseno_p85': design_m, 'dias_equivalentes': days_m}
            records_m.append({**identity_m, **z_m['diagnostico'], 'personas_lanzadera_dia': float(goals_m.demanda_lanzadera_condicionada_dia.sum()), 'viajes_comerciales_dia': int(z_m['movimientos'].componente.str.startswith('comercial').sum()), 'viajes_vacios_dia': int((~z_m['movimientos'].componente.str.startswith('comercial')).sum())})
            fleets_m.append(z_m['vehiculos'].assign(**identity_m))
            moves_m.append(z_m['movimientos'].assign(**identity_m))
            links_m.append(z_m['pares'].assign(**identity_m))
            loads_m.append(z_m['cargas_tramos'].assign(**identity_m))
            bounds_m.append(z_m['cota_por_servicio'].assign(**identity_m))
            e_m = valorar_movimientos(z_m['movimientos'], x_m['factors'], carga_comercial=v_m['carga_copert'], perdida_rendimiento=v_m['perdida_rendimiento_guaguas_contraste'])
            ec_m = e_m.groupby('referencia_id', as_index=False).agg(hot_mwh_dia=('hot_mwh', 'sum'), con_contraste_mwh_dia=('con_contraste_mwh', 'sum'), vehiculos_km_dia=('km_recorrido', 'sum'))
            costs_m.append(ec_m.assign(**identity_m))
            if design_m:
                for (corridor_m, pnt_m) in PUNTOS.items():
                    dem_m = x_m['p85_hour'].loc[x_m['p85_hour'].access_corridor.eq(corridor_m) & x_m['p85_hour'].dentro_ventana_fuente]
                    checked_m = auditar_perfil_reservado_p85(dem_m, z_m['pares'].loc[z_m['pares'].punto.eq(pnt_m)], capacidad=46, espera=v_m['espera_max_lanzadera_min'], cambio_franja=True)
                    assert checked_m['sin_asignacion'] < 1e-08
                    p85checks_m.append({**identity_m, 'punto': pnt_m, 'demanda_p85_horaria': checked_m['demanda'], 'sin_asignacion': checked_m['sin_asignacion'], 'p85_diario_comprobado': True, 'cambio_franja_acordado': True})
    rec_m = pd.DataFrame(records_m)
    fl_m = pd.concat(fleets_m, ignore_index=True)
    mov_m = pd.concat(moves_m, ignore_index=True)
    ln_m = pd.concat(links_m, ignore_index=True)
    (pool_m, pool_tot_m) = pool_fijo_por_bases(fl_m, reserva=v_m['reserva_flota'], contrato=v_m['vehiculos_contrato_contraste'])
    feasibility_m = []
    for p_m in pool_tot_m.itertuples():
        sub_m = rec_m.loc[rec_m.politica.eq(p_m.politica) & ~rec_m.es_diseno_p85]
        feasible_m = bool(sub_m.cabe_en_30.all() and sub_m.cumple_intervalo_vigente.all() and p_m.cabe_en_30_sin_traslados_entre_bases)
        feasibility_m.append({'politica': p_m.politica, 'observaciones_atendidas_en_construccion': len(sub_m), 'observaciones_con_flota_30': int(sub_m.cabe_en_30.sum()), 'observaciones_flota_y_reglas_vigentes': int((sub_m.cabe_en_30 & sub_m.cumple_intervalo_vigente).sum()), 'p85_con_cadenas_completas_comprobado': True, 'vehiculos_operativos_pool': p_m.vehiculos_operativos_pool, 'vehiculos_totales_pool': p_m.vehiculos_totales_pool, 'oferta_anual_30_reglas_vigentes_demostrada': feasible_m, 'propuesta_adoptada': False})
    feasibility_m = pd.DataFrame(feasibility_m)
    cc_m = pd.concat(costs_m, ignore_index=True)
    cc_m['hot_mwh_anio'] = cc_m.hot_mwh_dia * cc_m.dias_equivalentes
    cc_m['vehiculos_km_anio'] = cc_m.vehiculos_km_dia * cc_m.dias_equivalentes
    annual_cost_m = cc_m.groupby(['politica', 'referencia_id'], as_index=False)[['hot_mwh_anio', 'vehiculos_km_anio']].sum()
    balance_m = balance_modulacion(x_m['base'], annual_cost_m, feasibility_m, x_m['energy_previous'], perdida=v_m['perdida_rendimiento_guaguas_contraste'])
    assert not feasibility_m.oferta_anual_30_reglas_vigentes_demostrada.any()
    assert balance_m.saldo_oferta_viable_30_mwh_anio.isna().all()
    limit_m = limites_por_intervalo(allg_m, x_m['moves'], v_m, capacidad=46)
    floors_m = []
    factor_m = x_m['factors'].loc[x_m['factors'].referencia_id.eq('referencia_guagua_2')].set_index(['punto', 'sentido', 'carga_fisica'])
    old_mov_m = read_m(root_m / 'data/silver/energia_turismos/20261101_referencia_diesel_y_descenso/movimientos_con_referencia_elegida.csv')
    for z_m in obs_m.itertuples():
        g_m = allg_m.loc[allg_m.matrix_index.eq(z_m.matrix_index)]
        access_m = sum((math.ceil(max(0, r.demanda_lanzadera_condicionada_dia - 1e-08) / 46) * sum((factor_m.loc[r.punto, s, 0.5].energia_mj_recorrido for s in ['ida', 'vuelta'])) / 3600 for r in g_m.itertuples()))
        interior_m = old_mov_m.loc[old_mov_m.matrix_index.eq(z_m.matrix_index) & old_mov_m.punto.eq('INTERIOR'), 'hot_mwh'].sum()
        floors_m.append({'observacion': z_m.matrix_index, 'dias_equivalentes': z_m.dias_equivalentes_ponderacion, 'comerciales_acceso_sin_vacios_mwh_dia': access_m, 'interior_regular_conservado_mwh_dia': interior_m, 'cota_hot_mwh_anio': (access_m + interior_m) * z_m.dias_equivalentes_ponderacion})
    floor_m = pd.DataFrame(floors_m)
    lower_m = float(floor_m.cota_hot_mwh_anio.sum())
    thresholds_m = []
    for b_m in x_m['base'].loc[x_m['base'].es_referencia_guagua_elegida & x_m['base'].caso_pendiente.eq('Referencia del Excel')].itertuples():
        prev_m = x_m['energy_previous'].set_index('referencia_id').loc[b_m.referencia_id]
        oldbus_m = prev_m.hot_mwh_anio if b_m.tratamiento_operativo == 'Hot COPERT' else prev_m.con_contraste_mwh_anio
        available_m = b_m.saldo_con_ajuste_convencional_mwh_anio + oldbus_m
        energyfloor_m = lower_m if b_m.tratamiento_operativo == 'Hot COPERT' else lower_m / (1 - v_m['perdida_rendimiento_guaguas_contraste'])
        thresholds_m.append({'alternativa_procedencia': b_m.alternativa_procedencia, 'tratamiento_operativo': b_m.tratamiento_operativo, 'consumo_guaguas_maximo_para_60_mwh_anio': available_m - 697.8, 'cota_favorable_interior_regular_mwh_anio': energyfloor_m, 'saldo_maximo_bajo_cota_favorable_tep_anio': (available_m - energyfloor_m) / 11.63, 'limita_solo_politica_interior_regular': True, 'cota_de_consumo_real': False, 'oferta_viable_construida': False})
    tables_m = {'diagnostico_por_observacion': rec_m, 'pool_por_bases': pool_m, 'factibilidad_anual': feasibility_m, 'costes_por_observacion': cc_m, 'costes_anuales': annual_cost_m, 'balance_construcciones_condicionadas': balance_m, 'limites_temporales': limit_m, 'cotas_reloj_fijo': pd.concat(bounds_m, ignore_index=True), 'comprobacion_p85': pd.DataFrame(p85checks_m), 'suelo_energia_interior_regular': floor_m, 'umbrales_y_cota_favorable': pd.DataFrame(thresholds_m)}
    return Etapa(tables_m, {'movimientos': mov_m, 'pares': ln_m, 'vehiculos': fl_m, 'cargas_tramos': pd.concat(loads_m, ignore_index=True)})
