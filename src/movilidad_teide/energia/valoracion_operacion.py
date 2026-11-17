"""Actividad mínima por volumen y valoración condicional de la oferta conservada.

Las cotas de viajes no resuelven conexiones, horarios ni flota. Su valoración
energética solo rige bajo los factores elegidos; no acota el consumo real.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from movilidad_teide.validacion import comprobar_claves as _claves
from movilidad_teide.opciones import PUNTOS


def necesidades_comerciales(objetivos, movimientos, pares, *, capacidad):
    """Conservar demanda y contar plazas y viajes faltantes por sentido.

    Cuento todos los viajes comerciales existentes, también regresos sin pareja,
    antes de calcular el suelo de viajes añadidos. No duplico esos regresos.
    La falta de plazas en cadenas completas y la cota de viajes son diferentes.
    """
    if (isinstance(capacidad, (bool, np.bool_)) or not np.isfinite(capacidad)
            or capacidad <= 0 or capacidad != int(capacidad)):
        raise ValueError('Capacidad de diseño inválida.')
    _claves(objetivos, ['punto'], 'Objetivos')
    _claves(movimientos, ['id_salida'], 'Movimientos')
    _claves(pares, ['id_subida'], 'Cadenas')
    _claves(pares, ['id_regreso'], 'Regresos vinculados')
    points = set(PUNTOS.values())
    if set(objetivos.punto) != points or set(pares.punto) != points:
        raise ValueError('Falta un corredor de acceso.')
    demands = objetivos.set_index('punto').demanda_lanzadera_condicionada_dia
    if not np.isfinite(demands).all() or demands.lt(0).any():
        raise ValueError('Demanda inválida.')
    known = movimientos.set_index('id_salida')
    commercial = movimientos.loc[movimientos.componente.str.startswith('comercial')]
    if not set(commercial.sentido) <= {'ida', 'vuelta'}:
        raise ValueError('Sentido comercial no reconocido.')
    counts = commercial.groupby(['punto', 'sentido']).size()
    rows = []
    for point, chain in pares.groupby('punto'):
        if (not chain.plazas_vinculadas.eq(capacidad).all()
                or not set(chain.id_subida) <= set(known.index)
                or not set(chain.id_regreso) <= set(known.index)):
            raise ValueError('Cadena sin sus viajes o capacidad de diseño.')
        for field, sense in [('id_subida', 'ida'), ('id_regreso', 'vuelta')]:
            trips = known.loc[chain[field]]
            if (not trips.punto.eq(point).all() or not trips.sentido.eq(sense).all()
                    or not trips.componente.str.startswith('comercial').all()):
                raise ValueError('Cadena con viaje incompatible.')
        demand = float(demands[point])
        needed = math.ceil(max(0., demand - 1e-8) / capacidad)
        linked = len(chain)
        record = {'punto': point, 'demanda_personas_dia': demand,
            'plazas_cadenas_completas_dia': linked * capacidad,
            'exceso_sobre_cadenas_personas_dia': max(0., demand - linked * capacidad),
            'parejas_existentes': linked, 'parejas_necesarias_por_volumen': needed,
            'parejas_adicionales_por_volumen': max(0, needed - linked),
            'operacion_completa_demostrada': False}
        for sense in ['ida', 'vuelta']:
            existing = int(counts.get((point, sense), 0))
            if existing < linked:
                raise ValueError('Menos viajes que cadenas conservadas.')
            record['comerciales_existentes_' + sense] = existing
            record['minimo_comerciales_adicionales_' + sense] = max(0, needed - existing)
        rows.append(record)
    return pd.DataFrame(rows)


def valorar_movimientos(movimientos, factores, *, carga_comercial, perdida_rendimiento):
    """Valorar todos los comerciales y vacíos, sin mezclar referencias técnicas.

    Devuelve cada categoría por separado. Diesel urbano y autocar son controles
    del método; no se convierten en flota híbrida ni extremos probabilísticos.
    """
    if (isinstance(carga_comercial, (bool, np.bool_)) or not np.isfinite(carga_comercial)
            or not 0 <= carga_comercial <= 1
            or isinstance(perdida_rendimiento, (bool, np.bool_))
            or not np.isfinite(perdida_rendimiento) or not 0 <= perdida_rendimiento < 1):
        raise ValueError('Carga o contraste operativo inválidos.')
    _claves(movimientos, ['id_salida'], 'Movimientos')
    _claves(factores, ['referencia_id', 'punto', 'sentido', 'carga_fisica'], 'Factores')
    allowed = {'comercial', 'comercial_refuerzo_regreso',
        'reposicion_por_horario', 'reposicion_cierre_diario'}
    if movimientos.empty or factores.empty or not set(movimientos.componente) <= allowed:
        raise ValueError('Movimiento vacío o sin tratamiento de consumo.')
    if (not np.isfinite(movimientos.km_por_recorrido).all()
            or movimientos.km_por_recorrido.le(0).any()
            or not set(movimientos.sentido) <= {'ida', 'vuelta'}):
        raise ValueError('Distancia o sentido inválido.')
    rows = []
    for ref, factors in factores.groupby('referencia_id'):
        lookup = factors.set_index(['punto', 'sentido', 'carga_fisica'])
        for trip in movimientos.itertuples():
            load = carga_comercial if trip.componente.startswith('comercial') else 0.
            key = (trip.punto, trip.sentido, load)
            if key not in lookup.index:
                raise ValueError('Falta factor para un movimiento.')
            factor = lookup.loc[key]
            energy = factor.energia_mj_recorrido
            if (not np.isfinite(energy) or energy <= 0
                    or not np.isclose(trip.km_por_recorrido, factor.longitud_km, rtol=0, atol=1e-8)):
                raise ValueError('Factor no compatible con el recorrido conservado.')
            hot = float(energy) / 3600
            rows.append({'referencia_id': ref, 'id_salida': trip.id_salida,
                'punto': trip.punto, 'sentido': trip.sentido, 'componente': trip.componente,
                'carga_fisica': float(load), 'km_recorrido': float(trip.km_por_recorrido),
                'hot_mwh': hot, 'con_contraste_mwh': hot / (1 - perdida_rendimiento)})
    return pd.DataFrame(rows)


def valorar_suelo_accesos(necesidades, factores, *, carga_comercial, perdida_rendimiento):
    """Valorar solo viajes comerciales imprescindibles por volumen de accesos.

    Se omiten de esta cota las conexiones, interior y vacíos adicionales, cuyo
    coste sigue pendiente. No es un servicio completo ni una cota física del
    consumo real fuera de los factores y recorridos de estudio.
    """
    _claves(necesidades, ['punto'], 'Necesidades')
    if set(necesidades.punto) != set(PUNTOS.values()):
        raise ValueError('Necesidades incompletas.')
    trips = []
    for z in necesidades.itertuples():
        for sense in ['ida', 'vuelta']:
            n = getattr(z, 'minimo_comerciales_adicionales_' + sense)
            if (isinstance(n, (bool, np.bool_)) or not np.isfinite(n) or n < 0 or n != int(n)):
                raise ValueError('Número de viajes inválido.')
            lengths = factores.loc[factores.punto.eq(z.punto) & factores.sentido.eq(sense), 'longitud_km']
            if lengths.empty or not np.isfinite(lengths).all() or not np.allclose(lengths, lengths.iloc[0], rtol=0, atol=1e-8):
                raise ValueError('Recorrido de acceso ausente o ambiguo.')
            for i in range(int(n)):
                trips.append({'punto': z.punto, 'sentido': sense, 'componente': 'comercial',
                    'id_salida': f'{z.punto}_{sense}_suelo_{i}', 'km_por_recorrido': lengths.iloc[0]})
    # Una cota nula en un día no dice que su operación completa cueste cero.
    if not trips:
        # Uso la validación normal de factores y condiciones antes de devolver cero.
        first = necesidades.iloc[0].punto
        length = factores.loc[factores.punto.eq(first) & factores.sentido.eq('ida'), 'longitud_km']
        if length.empty:
            raise ValueError('Falta recorrido para valorar necesidades.')
        probe = pd.DataFrame([{'punto': first, 'sentido': 'ida', 'componente': 'comercial',
            'id_salida': 'validacion_cota_nula', 'km_por_recorrido': length.iloc[0]}])
        valid = valorar_movimientos(probe, factores, carga_comercial=carga_comercial,
            perdida_rendimiento=perdida_rendimiento)
        return pd.DataFrame({'referencia_id': valid.referencia_id,
            'suelo_comerciales_adicionales_mwh_dia': 0., 'suelo_comerciales_adicionales_km_dia': 0.,
            'otros_refuerzos_mwh_dia': np.nan, 'operacion_completa_demostrada': False})
    priced = valorar_movimientos(pd.DataFrame(trips), factores,
        carga_comercial=carga_comercial, perdida_rendimiento=perdida_rendimiento)
    total = priced.groupby('referencia_id', as_index=False).agg(
        suelo_comerciales_adicionales_mwh_dia=('con_contraste_mwh', 'sum'),
        suelo_comerciales_adicionales_km_dia=('km_recorrido', 'sum'))
    total['otros_refuerzos_mwh_dia'] = np.nan
    total['operacion_completa_demostrada'] = False
    return total


def seleccionar_referencias_guaguas(energia, parametros):
    """Elegir acceso e interior desde el libro sin cambiar actividad o tecnología futura.

    La tabla de entrada conserva las alternativas calculadas para cada movimiento.
    Un factor ausente o un viaje perdido exige corregir entradas; nunca se omite.
    """
    referencias = {
        'Autocar diésel de hasta 18 t': 'referencia_guagua_2',
        'Guagua urbana diésel de 15–18 t': 'referencia_guagua_1',
        'Guagua urbana diésel híbrida': 'referencia_guagua_3',
    }
    rows = {p['id']: p for p in parametros['parametros']}
    keys = ['referencia_guagua_acceso', 'referencia_guagua_interior']
    if not set(keys) <= set(rows):
        raise ValueError('Falta la referencia energética de acceso o interior.')
    choices = {k: rows[k]['valor_utilizado'] for k in keys}
    if any(v not in referencias for v in choices.values()):
        raise ValueError('Referencia de guaguas pendiente o sin factores implementados.')
    _claves(energia, ['referencia_id', 'id_salida'], 'Energía por movimiento')
    if energia.empty or not {'punto', 'hot_mwh', 'con_contraste_mwh', 'km_recorrido'} <= set(energia):
        raise ValueError('Faltan movimientos o su valoración energética.')
    if (energia.punto.isna().any()
            or not set(energia.punto) <= set(PUNTOS.values()) | {'INTERIOR'}
            or energia.groupby('id_salida').punto.nunique().gt(1).any()
            or not np.isfinite(energia[['hot_mwh', 'con_contraste_mwh', 'km_recorrido']]).all().all()
            or energia[['hot_mwh', 'con_contraste_mwh', 'km_recorrido']].le(0).any().any()):
        raise ValueError('Movimiento incompatible o energía/distancia inválidas.')
    interior = energia.punto.eq('INTERIOR')
    selected = energia.loc[
        (~interior & energia.referencia_id.eq(referencias[choices[keys[0]]]))
        | (interior & energia.referencia_id.eq(referencias[choices[keys[1]]]))
    ].copy()
    if (selected.id_salida.duplicated().any()
            or set(selected.id_salida) != set(energia.id_salida)):
        raise ValueError('La selección pierde movimientos; falta un factor de acceso o interior.')
    selected['criterio_referencia_energetica'] = np.where(
        selected.punto.eq('INTERIOR'), choices[keys[1]], choices[keys[0]])
    return selected


def verificar_entradas_referencia_consumo(anterior, actual):
    """Autorizar solo la transición documentada D212, sin relajar controles previos.

    Reutiliza demanda, recorridos y actividad cuando todas sus elecciones siguen
    idénticas. Las nuevas entradas físicas solo controlan la sensibilidad separada.
    """
    changed = {'referencia_guagua_acceso', 'referencia_guagua_interior',
               'criterio_tara_turismos', 'masa_persona_turismo_kg', 'equipaje_turismo_kg_coche'}
    added = {'eficiencia_incremental_gasolina_pendiente',
             'eficiencia_incremental_diesel_pendiente', 'tratamiento_descenso_turismos'}
    old = {p['id']: p for p in anterior['parametros']}
    now = {p['id']: p for p in actual['parametros']}
    if (anterior['caso'] != actual['caso'] or actual['caso'] != 'Central'
            or set(now) - set(old) != added or not set(old) <= set(now)):
        raise ValueError('La transición no corresponde a las entradas D212 de Central.')
    for key, before in old.items():
        after = now[key]
        if key not in changed:
            if before != after:
                raise ValueError('Cambio ajeno a las referencias de consumo: ' + key)
            continue
        stable = {'id', 'grupo', 'parametro', 'unidad', 'propuesta'}
        if key != 'referencia_guagua_interior':
            stable.add('aplicacion')
        if (any(before[k] != after[k] for k in stable)
                or after['modo_efectivo'] != 'Manual'
                or not after['justificacion_utilizada'].strip()):
            raise ValueError('Referencia o elección de consumo sin conservar/justificar: ' + key)
    old_choices = {(p['caso'], p['id']): p for p in anterior['elecciones_todos_los_casos']}
    new_choices = {(p['caso'], p['id']): p for p in actual['elecciones_todos_los_casos']}
    expected = set(old_choices) | {(c, k) for c in ['Central', 'Variante A', 'Variante B'] for k in added}
    if set(new_choices) != expected:
        raise ValueError('Faltan elecciones o se han añadido otras distintas de D212.')
    for key, before in old_choices.items():
        if key[0] == 'Central' and key[1] in changed:
            continue
        if before != new_choices[key]:
            raise ValueError('Cambio ajeno en otra elección o variante.')
    return {'referencias_previas_conservadas': len(old),
            'elecciones_previas_conservadas': len(old_choices) - len(changed),
            'claves_recalculadas': sorted(changed), 'claves_fisicas_nuevas': sorted(added),
            'demanda_recorridos_y_actividad_sin_cambios': True}
