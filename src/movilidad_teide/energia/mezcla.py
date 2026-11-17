"""Hipótesis de procedencia y sustitución explícita de consumos no representados."""
from copy import deepcopy
import numpy as np
import pandas as pd
from movilidad_teide.energia.balance import comparar_anualmente_hot
from movilidad_teide.energia.compatibilidad import verificar_representacion_tecnica
from movilidad_teide.energia.balance_condicionado_tipos import MAGNITUD_ANUAL
from movilidad_teide.opciones import CRITERIOS_MEZCLA as CRITERIOS
from movilidad_teide.opciones import PARTICULAR
from movilidad_teide.opciones import ALQUILER
from movilidad_teide.opciones import COLECTIVOS


def verificar_entradas_mezcla(anterior, actual):
    """Permitir únicamente las tres adiciones; comprobar las entradas históricas."""
    new = {p['id']: p for p in actual['parametros']}
    old = {p['id']: p for p in anterior['parametros']}
    if set(CRITERIOS) & set(old) or not set(CRITERIOS) <= set(new) - set(old):
        raise ValueError('Faltan las tres adiciones de mezcla y sustitución.')
    for key, value in CRITERIOS.items():
        row = new[key]
        if row['valor_utilizado'] != value or row['modo_efectivo'] != 'Manual' or not row['justificacion_utilizada'].strip():
            raise ValueError('Falta elegir y justificar el criterio de estudio.')
    projected = deepcopy(actual)
    projected['parametros'] = [p for p in projected['parametros'] if p['id'] not in CRITERIOS]
    projected['elecciones_todos_los_casos'] = [p for p in projected['elecciones_todos_los_casos'] if p['id'] not in CRITERIOS]
    result = verificar_representacion_tecnica(anterior, projected)
    return result | {'criterios_nuevos_aplicados_aparte': list(CRITERIOS)}


def estimar_resto_turismos(diagnostico, perfiles, resumen, *, criterio):
    """Sustituir el consumo, sin completar categoría, norma o combustible original.

    Los donantes no incluyen sustituciones: no hay imputación en cadena. Cada
    media usa cantidades de vehículos una sola vez, con controles ya colapsados.
    """
    if criterio != CRITERIOS['criterio_sustitucion_turismos']:
        raise ValueError('Criterio de sustitución no elegido.')
    d = diagnostico.copy(deep=True)
    if d.grupo_id.duplicated().any() or not np.isfinite(d.vehiculos).all() or d.vehiculos.le(0).any():
        raise ValueError('Perfiles o cantidades no válidos.')
    represented = d.representado_en_contraste | d.referencia_condicionada_disponible
    if (d.representado_en_contraste & d.referencia_condicionada_disponible).any():
        raise ValueError('Cobertura duplicada.')
    if set(perfiles.grupo_id) != set(d.loc[represented, 'grupo_id']):
        raise ValueError('Los donantes no coinciden con los perfiles representados.')
    if perfiles.duplicated(['grupo_id', 'modo', 'velocidad_kmh']).any():
        raise ValueError('Un control alternativo duplicaría vehículos.')
    columns = ['factor_inferior_mj_km', 'factor_superior_mj_km']
    if (not np.isfinite(perfiles[columns]).all().all() or perfiles[columns].lt(0).any().any()
            or perfiles[columns[0]].gt(perfiles[columns[1]]).any()):
        raise ValueError('Factores donantes ausentes o invertidos.')
    original = d.set_index('grupo_id')
    for service, selected in perfiles.groupby('grupo_servicio'):
        expected = set(map(tuple, resumen.loc[resumen.grupo_servicio.eq(service), ['modo', 'velocidad_kmh']].to_numpy()))
        for group_id, group in selected.groupby('grupo_id'):
            if set(map(tuple, group[['modo', 'velocidad_kmh']].to_numpy())) != expected:
                raise ValueError('Faltan condiciones de algún donante; no cambiar la media silenciosamente.')
    for row in perfiles.itertuples():
        source = original.loc[row.grupo_id]
        if row.vehiculos != source.vehiculos or row.grupo_servicio != source.grupo_servicio or str(row.familia_copert) != str(source.familia_copert):
            raise ValueError('El donante contradice el diagnóstico original.')
    totals = d.groupby('grupo_servicio').vehiculos.sum()
    records = []
    donors = []
    for row in d.loc[~represented].itertuples():
        conditions = resumen.loc[resumen.grupo_servicio.eq(row.grupo_servicio), ['modo', 'velocidad_kmh']]
        if conditions.empty or conditions.duplicated().any():
            raise ValueError('Condiciones de circulación incompletas o duplicadas.')
        for condition in conditions.itertuples():
            pool = perfiles.loc[perfiles.grupo_servicio.eq(row.grupo_servicio) & perfiles.modo.eq(condition.modo)
                                & perfiles.velocidad_kmh.eq(condition.velocidad_kmh)]
            fuel = '' if pd.isna(row.familia_copert) else str(row.familia_copert)
            comparable = pool.loc[pool.familia_copert.eq(fuel)] if fuel else pool.iloc[:0]
            method = 'Mismo servicio y combustible'
            if comparable.empty:
                comparable = pool
                method = 'Composición representada del servicio; tecnología real no identificada'
            if comparable.empty:
                raise ValueError('No hay referencia del servicio: no asignar cero.')
            weights = comparable.vehiculos / comparable.vehiculos.sum()
            lower = float((weights * comparable[columns[0]]).sum())
            upper = float((weights * comparable[columns[1]]).sum())
            records.append({'grupo_id': row.grupo_id, 'grupo_servicio': row.grupo_servicio,
                'familia_original': fuel, 'categoria_original': row.CAT_EURO, 'norma_original': row.EMISIONES_EURO,
                'vehiculos': row.vehiculos, 'modo': condition.modo, 'velocidad_kmh': condition.velocidad_kmh,
                'metodo_sustitucion': method, 'vehiculos_donantes': int(comparable.vehiculos.sum()),
                'factor_sustituto_inferior_mj_km': lower, 'factor_sustituto_superior_mj_km': upper,
                'aporte_sustitucion_min_mj_km': lower * row.vehiculos / totals[row.grupo_servicio],
                'aporte_sustitucion_max_mj_km': upper * row.vehiculos / totals[row.grupo_servicio]})
            for donor, weight in zip(comparable.itertuples(), weights):
                donors.append({'grupo_id_receptor': row.grupo_id, 'grupo_id_donante': donor.grupo_id,
                    'modo': condition.modo, 'velocidad_kmh': condition.velocidad_kmh, 'peso_donante': float(weight)})
    detail = pd.DataFrame(records)
    if detail.empty:
        raise ValueError('El diagnóstico no contiene resto pendiente de estimar.')
    keys = ['grupo_servicio', 'modo', 'velocidad_kmh']
    adds = detail.groupby(keys, as_index=False).agg(
        aporte_sustitucion_min_mj_km=('aporte_sustitucion_min_mj_km', 'sum'),
        aporte_sustitucion_max_mj_km=('aporte_sustitucion_max_mj_km', 'sum'),
        vehiculos_estimados_por_sustitucion=('vehiculos', 'sum'))
    full = resumen.merge(adds, on=keys, how='left', validate='one_to_one')
    if full.aporte_sustitucion_min_mj_km.isna().any():
        raise ValueError('Falta sustitución en alguna condición del servicio.')
    if not full.vehiculos_estimados_por_sustitucion.eq(full.vehiculos_aun_sin_referencia).all():
        raise ValueError('No se conserva la cantidad pendiente original.')
    for side in ['min', 'max']:
        field = f'aporte_conjunto_condicionado_{side}_mj_km'
        full[f'aporte_representado_{side}_mj_km'] = full[field]
        full[field] = full[field] + full[f'aporte_sustitucion_{side}_mj_km']
    full['vehiculos_sin_estimacion'] = 0
    full['estado'] = 'Referencia técnica con consumo sustituido; originales incompletos conservados; no flota observada'
    return {'factores': full, 'sustituciones': detail, 'donantes': pd.DataFrame(donors)}


def asignar_servicio_colectivos(actividad, *, alquiler_fuera, residentes, alquiler_espana):
    """Repartir coches equivalentes ya calculados; no personas de todos los modos."""
    if alquiler_fuera != CRITERIOS['criterio_alquiler_procedencia'] or residentes != CRITERIOS['criterio_residentes_coche']:
        raise ValueError('Falta la regla de procedencia elegida.')
    if alquiler_espana not in (0, 1):
        raise ValueError('El grupo mixto se contrasta mediante dos alternativas identificadas.')
    if set(actividad.colectivo) != COLECTIVOS:
        raise ValueError('Colectivo no previsto o ausente; no inferir su procedencia.')
    a = actividad.copy(deep=True)
    valid = a.en_ambito_anual
    if not np.isfinite(a.loc[valid, MAGNITUD_ANUAL]).all() or a.loc[valid, MAGNITUD_ANUAL].lt(0).any():
        raise ValueError('Actividad no válida.')
    fractions = {'extranjero': 1., 'espana_no_tenerife': float(alquiler_espana),
                 'tenerife_no_frecuente': 0., 'tenerife_resto': 0.}
    a['fraccion_alquiler_aproximada'] = a.colectivo.map(fractions)
    a['servicio_asignado'] = np.where(a.fraccion_alquiler_aproximada.eq(1), ALQUILER, PARTICULAR)
    a['tratamiento_procedencia'] = np.where(a.colectivo.eq('espana_no_tenerife'),
        'Grupo mixto: asignación agregada en contraste, sin separar otras islas',
        np.where(a.colectivo.eq('extranjero'), 'Fuera de Canarias según clasificación del Visor; hipótesis alquiler',
                 'Tenerife: particular como simplificación técnica, no uso medido'))
    # Todos los miembros del mismo grupo mantienen coche, origen y rama.
    return a


def comparar_mezcla_anual(actividad_asignada, recorridos, clasificacion, factores, velocidades, energia_buses, *, referencia_acceso):
    """Sumar coches por servicio y contabilizar la oferta de guaguas una sola vez."""
    expected = {PARTICULAR, ALQUILER}
    if not set(actividad_asignada.servicio_asignado) <= expected:
        raise ValueError('Servicio asignado desconocido.')
    results = []
    for service in sorted(expected):
        a = actividad_asignada.copy(deep=True)
        a[MAGNITUD_ANUAL] = a[MAGNITUD_ANUAL].where(a.servicio_asignado.eq(service), 0.)
        f = factores.loc[factores.grupo_servicio.eq(service)]
        if f.empty:
            raise ValueError('Faltan factores de un servicio de la mezcla.')
        results.append(comparar_anualmente_hot(a, recorridos, clasificacion, f, velocidades, energia_buses,
                                               referencia_acceso=referencia_acceso))
    all_components = pd.concat([result['componentes'] for result in results], ignore_index=True)
    ids = ['referencia_tecnica_turismos', 'referencia_acceso', 'referencia_interior', 'componente']
    # Los coches se suman; las mismas guaguas de cada llamada no se suman otra vez.
    car = all_components.loc[all_components.componente.str.startswith('Coches')]
    bus = all_components.loc[~all_components.componente.str.startswith('Coches')]
    base_fields = ['sin_aporte_hot_mj_anio', 'con_aporte_hot_mj_anio', 'diferencia_hot_mj_anio']
    if bus.groupby(ids)[base_fields].nunique().gt(1).any().any():
        raise ValueError('Las llamadas no usan la misma oferta de guaguas.')
    combined = pd.concat([car.groupby(ids, as_index=False)[base_fields].sum(), bus.drop_duplicates(ids)[ids+base_fields]], ignore_index=True)
    combined['grupo_servicio'] = 'Mezcla particular/alquiler por procedencia'
    identity = ['grupo_servicio', 'referencia_tecnica_turismos', 'referencia_acceso', 'referencia_interior']
    summary = combined.groupby(identity, as_index=False)[base_fields].sum().rename(columns={
        'sin_aporte_hot_mj_anio': 'sin_subtotal_hot_identificado_mj_anio',
        'con_aporte_hot_mj_anio': 'con_subtotal_hot_identificado_mj_anio',
        'diferencia_hot_mj_anio': 'diferencia_hot_identificada_mj_anio'})
    for frame in [combined, summary]:
        for field in list(frame):
            if field.endswith('_mj_anio'):
                for unit, divisor in [('kwh',3.6), ('mwh',3600.), ('tep',41868.)]:
                    frame[field.replace('_mj_anio',f'_{unit}_anio')] = frame[field] / divisor
    for field in ['energia_total_sistema_sin_mj_anio','energia_total_sistema_con_mj_anio',
                  'ahorro_total_energia_final_mj_anio','porcentaje_ahorro_total','cumplimiento_minimo_acreditado']:
        summary[field] = np.nan
    summary['alcance'] = 'Mezcla y sustitución para estudio; actividad modal condicionada y otros consumos pendientes'
    detail = pd.concat([result['detalle_coches'] for result in results], ignore_index=True)
    return {'comparacion': summary, 'componentes': combined, 'detalle_coches': detail}
