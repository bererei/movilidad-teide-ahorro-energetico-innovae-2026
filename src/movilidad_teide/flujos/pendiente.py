from pathlib import Path
import hashlib, json, platform, time
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from movilidad_teide.parametros import leer_parametros
from movilidad_teide.circulacion_turismos import cargar_y_clasificar_referencias
from movilidad_teide.pendiente_anual import masas_grupos_desde_dgt, cargar_perfiles_completos, perfiles_visita_interior, preparar_curvas_convencionales, energia_pendiente_por_recorrido, aplicar_correcciones_a_actividad, verificar_activacion_pendiente_anual
from .tipos import Etapa

def calcular_pendiente(root, parametros):
    """Reconstruyo las masas y la energía de todos los recorridos con los parámetros vigentes."""
    root_a = Path(root)
    params_a = parametros
    v_a = {p['id']: p['valor_utilizado'] for p in params_a['parametros']}
    from movilidad_teide.energia.preparacion_pendiente import preparar_fisica
    base_a = preparar_fisica(root_a, params_a)
    x_a = base_a['x']
    profiles_a, masses_a, curves_a = base_a['perfiles'], base_a['masas'], base_a['curvas']
    paths_a = {'coches': 'data/silver/energia/referencias_unitarias/detalle_costes_coches.csv', 'otros': 'data/silver/energia/referencias_unitarias/detalle_alimentacion_otros.csv', 'condiciones': 'data/silver/energia_turismos/20261101_referencia_diesel_y_descenso/condiciones_operacion_conservadas.csv', 'balance_base': 'data/silver/energia_turismos/20261101_referencia_diesel_y_descenso/balance_anual_referencias.csv'}
    x_a.update({k: pd.read_csv(root_a/p, sep=';', float_precision='round_trip') for k,p in paths_a.items()})
    weights_a = x_a['condiciones'][['matrix_index', 'tipo_dia', 'dias_equivalentes_ponderacion']].copy()
    weights_a['periodo_id'] = weights_a.matrix_index.map(lambda i: f'observacion_{i:02d}')
    assert len(weights_a) == 9 and abs(weights_a.dias_equivalentes_ponderacion.sum() - 366) < 1e-08
    activities_a = []
    daily_a = []
    for (key_a, qty_a) in [('coches', 'recorridos_coche_periodo'), ('otros', 'personas_trayecto_periodo')]:
        z_a = x_a[key_a].loc[x_a[key_a].periodo_id.isin(weights_a.periodo_id)].merge(weights_a, on='periodo_id', validate='many_to_one')
        z_a['cantidad_anual'] = z_a[qty_a] * z_a.dias_equivalentes_ponderacion
        ids_a = ['alternativa_procedencia', 'origen_id', 'colectivo', 'sentido', 'energia_mwh_por_vehiculo_sentido'] + (['rama'] if key_a == 'coches' else [])
        annual_a = z_a.groupby(ids_a, dropna=False, as_index=False).cantidad_anual.sum()
        annual_a = annual_a.rename(columns={'cantidad_anual': 'recorridos_coche_anio' if key_a == 'coches' else 'personas_trayecto_anio'})
        activities_a.append(annual_a)
        daily_a.append(z_a)
    cases_a = [('Referencia del Excel', {}), ('Descenso sin reducción', {'tratamiento': 'Sin reducción de consumo en descenso'}), ('Tara P25', {'estadistico': 'Cuartil inferior (P25)'}), ('Tara P75', {'estadistico': 'Cuartil superior (P75)'}), ('Transmisión 0,95', {'multiplicador_eta': 0.95 / 0.85})]
    all_routes_a = []
    all_details_a = []
    all_totals_a = []
    all_daily_a = []
    annual_balances_a = []
    checks_a = []
    for (case_a, overrides_a) in cases_a:
        print('Valorando:', case_a, flush=True)
        energy_a = pd.concat([energia_pendiente_por_recorrido(profiles_a, curves_a, x_a['factores'], params_a, ocupacion=occ_a, **overrides_a) for occ_a in [v_a['ocupacion_coche'], 1.0]], ignore_index=True)
        detail_a = aplicar_correcciones_a_actividad(*activities_a, x_a['recorridos'], energy_a)
        group_a = detail_a.groupby(['alternativa_procedencia', 'rama'], as_index=False)[['energia_base_mwh_anio', 'energia_base_convencional_mwh_anio', 'correccion_convencional_mwh_anio', 'energia_base_otras_tecnologias_mwh_anio']].sum()
        group_a['energia_con_ajuste_convencional_mwh_anio'] = group_a.energia_base_mwh_anio + group_a.correccion_convencional_mwh_anio
        group_a['fraccion_energia_base_convencional'] = group_a.energia_base_convencional_mwh_anio / group_a.energia_base_mwh_anio
        group_a['correccion_otras_tecnologias_mwh_anio'] = np.nan
        for base_a in x_a['balance_base'].itertuples():
            g_a = group_a.loc[group_a.alternativa_procedencia.eq(base_a.alternativa_procedencia)].set_index('rama')
            assert abs(g_a.loc['antes', 'energia_base_mwh_anio'] - base_a.coches_sin_mwh_anio) < 1e-08
            assert abs(g_a.loc[['autorizados', 'transferidos'], 'energia_base_mwh_anio'].sum() - base_a.coches_con_mwh_anio) < 1e-08
            assert abs(g_a.loc['alimentacion_otros', 'energia_base_mwh_anio'] - base_a.alimentacion_otros_mwh_anio) < 1e-08
            before_a = float(g_a.loc['antes', 'correccion_convencional_mwh_anio'])
            auto_a = float(g_a.loc['autorizados', 'correccion_convencional_mwh_anio'])
            modal_a = float(g_a.loc['transferidos', 'correccion_convencional_mwh_anio'])
            other_a = float(g_a.loc['alimentacion_otros', 'correccion_convencional_mwh_anio'])
            after_a = auto_a + modal_a + other_a
            net_a = before_a - after_a
            sin_a = base_a.sin_componentes_mwh_anio + before_a
            con_a = base_a.con_componentes_mwh_anio + after_a
            assert abs(sin_a - con_a - (base_a.saldo_componentes_mwh_anio + net_a)) < 1e-08
            annual_balances_a.append({'caso_pendiente': case_a, 'alternativa_procedencia': base_a.alternativa_procedencia, 'referencia_id': base_a.referencia_id, 'es_referencia_guagua_elegida': base_a.es_referencia_seleccionada, 'tratamiento_operativo': base_a.tratamiento_operativo, 'sin_base_mwh_anio': base_a.sin_componentes_mwh_anio, 'con_base_mwh_anio': base_a.con_componentes_mwh_anio, 'saldo_base_mwh_anio': base_a.saldo_componentes_mwh_anio, 'correccion_sin_mwh_anio': before_a, 'correccion_autorizados_mwh_anio': auto_a, 'correccion_alimentacion_transferidos_mwh_anio': modal_a, 'correccion_alimentacion_otros_mwh_anio': other_a, 'correccion_con_mwh_anio': after_a, 'efecto_neto_pendiente_mwh_anio': net_a, 'sin_con_ajuste_convencional_mwh_anio': sin_a, 'con_con_ajuste_convencional_mwh_anio': con_a, 'saldo_con_ajuste_convencional_mwh_anio': sin_a - con_a, 'saldo_con_ajuste_convencional_tep_anio': (sin_a - con_a) / 11.63, 'correccion_pendiente_otras_tecnologias_mwh_anio': np.nan, 'ahorro_final_acreditado_mwh_anio': np.nan, 'margen_condicionado_sobre_60tep_mwh_anio': sin_a - con_a - 60 * 11.63, 'intervalo_confianza': False, 'operacion_30_con_reglas_vigentes_validada': False, 'cumplimiento_acreditado': False})
        dd_a = []
        id_a = ['alternativa_procedencia', 'origen_id', 'colectivo', 'sentido']
        for (k_a, z_a) in enumerate(daily_a):
            ids_a = id_a + (['rama'] if k_a == 0 else [])
            coeff_a = detail_a.loc[detail_a.rama.ne('alimentacion_otros') if k_a == 0 else detail_a.rama.eq('alimentacion_otros'), ids_a + ['correccion_mwh_por_vehiculo_sentido']]
            joined_a = z_a.merge(coeff_a, on=ids_a, how='left', validate='many_to_one')
            assert joined_a.correccion_mwh_por_vehiculo_sentido.notna().all()
            q_a = 'recorridos_coche_periodo' if k_a == 0 else 'personas_trayecto_periodo'
            joined_a['correccion_mwh_dia'] = joined_a[q_a] * joined_a.correccion_mwh_por_vehiculo_sentido
            if k_a == 1:
                joined_a['rama'] = 'alimentacion_otros'
            dd_a.append(joined_a)
        perday_a = pd.concat(dd_a, ignore_index=True).groupby(['alternativa_procedencia', 'matrix_index', 'tipo_dia', 'dias_equivalentes_ponderacion', 'rama'], as_index=False).correccion_mwh_dia.sum()
        perday_a['correccion_mwh_anio'] = perday_a.correccion_mwh_dia * perday_a.dias_equivalentes_ponderacion
        check_a = perday_a.groupby(['alternativa_procedencia', 'rama']).correccion_mwh_anio.sum()
        assert np.allclose(check_a.sort_index(), group_a.set_index(['alternativa_procedencia', 'rama']).correccion_convencional_mwh_anio.sort_index(), rtol=0, atol=1e-08)
        all_routes_a.append(energy_a.assign(caso_pendiente=case_a))
        all_details_a.append(detail_a.assign(caso_pendiente=case_a))
        all_totals_a.append(group_a.assign(caso_pendiente=case_a))
        all_daily_a.append(perday_a.assign(caso_pendiente=case_a))
        checks_a.append({'caso_pendiente': case_a, 'base_sin_con_reproducida': True, 'correccion_diaria_y_anual_conciliada': True, 'stock_sin_descartes_ni_renormalizacion': True, 'todas_tecnologias_corregidas': False})
    balances_a = pd.DataFrame(annual_balances_a)
    route_values_a = pd.concat(all_routes_a, ignore_index=True)
    details_a = pd.concat(all_details_a, ignore_index=True)
    totals_a = pd.concat(all_totals_a, ignore_index=True)
    days_a = pd.concat(all_daily_a, ignore_index=True)
    flat_a = profiles_a.copy()
    flat_a['elevation_end_m'] = flat_a.elevation_start_m
    flat_a['slope_pct'] = 0.0
    f_a = energia_pendiente_por_recorrido(flat_a, curves_a, x_a['factores'], params_a, ocupacion=v_a['ocupacion_coche'])
    assert f_a.correccion_convencional_mj.abs().lt(1e-08).all()
    primary_a = balances_a.loc[balances_a.caso_pendiente.eq('Referencia del Excel')]
    upper_a = balances_a.loc[balances_a.caso_pendiente.eq('Descenso sin reducción')]
    join_a = primary_a.merge(upper_a, on=['alternativa_procedencia', 'referencia_id', 'tratamiento_operativo'], suffixes=('_ref', '_sin_reduccion'))
    assert (join_a.saldo_con_ajuste_convencional_mwh_anio_ref <= join_a.saldo_con_ajuste_convencional_mwh_anio_sin_reduccion + 1e-08).all()
    tables_a = {'masas_por_grupo': masses_a, 'energia_por_recorrido': route_values_a, 'correccion_por_origen_y_rama': details_a, 'correccion_por_componente_anual': totals_a, 'correccion_por_observacion': days_a, 'balance_anual_con_ajuste_convencional': balances_a, 'controles_de_reproduccion': pd.DataFrame(checks_a), 'condiciones_operativas_conservadas': x_a['condiciones']}
    return Etapa(tables_a, {'segmentos_por_via': profiles_a, 'curvas_y_masas': curves_a})
