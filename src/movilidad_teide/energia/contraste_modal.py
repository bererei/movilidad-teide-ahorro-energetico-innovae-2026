"""Referencias modales condicionadas y refuerzos derivados de demanda.

Los aforos aportan proporciones de personas-paso bajo ocupaciones explícitas;
no visitas únicas ni respuesta observada de quienes usan las lanzaderas.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from movilidad_teide.demanda.actividad import estimar_reparto_personas_aforos
from movilidad_teide.opciones import PUNTOS
from movilidad_teide.vehiculos.lanzaderas import anualizar_consumos_lanzaderas


def referencias_modales(resumen_aforos, *, ocupacion_coche, ocupacion_guagua,
                        fraccion_historica, anios=(2024, 2025)):
    """Conservar el histórico y contrastar años recientes sin calibrar escalas.

    Solo uso entradas para construir la referencia de visitas de subida. Las
    salidas se conservan aparte, sin sumarlas ni interpretarlas como más visitas.
    """
    if (isinstance(fraccion_historica, bool) or not np.isfinite(fraccion_historica)
            or not 0 <= fraccion_historica <= 1):
        raise ValueError('La fracción histórica debe estar entre cero y uno.')
    if any(x is None or isinstance(x, bool) or not np.isfinite(x) or x < 1
           for x in [ocupacion_coche, ocupacion_guagua]):
        raise ValueError('Se requieren ocupaciones explícitas de al menos una persona.')
    result = estimar_reparto_personas_aforos(
        resumen_aforos, ocupacion_coche=ocupacion_coche,
        ocupacion_guagua=ocupacion_guagua, anios=list(anios),
        puntos=list(PUNTOS.values()))
    aggregate = result['conjunto_por_sentido']
    entries = aggregate.loc[aggregate.sentido.eq('entrada')]
    if (len(entries) != len(anios) or not entries.conteos_aptos_para_contraste.all()
            or not np.isfinite(entries.fraccion_personas_paso_en_coche).all()):
        raise ValueError('Aforos incompletos o no aptos: no construir una cuota parcial.')
    rows = [{'caso_modal': 'historico_2019', 'referencia_modal': 'Referencia histórica de 2019',
             'anio_fuente': 2019, 'fraccion_coche_condicionada': float(fraccion_historica),
             'ocupacion_coche_condicionada': float(ocupacion_coche),
             'ocupacion_guagua_condicionada': np.nan,
             'clasificacion_modal_confirmada': False,
             'origen_coche_de_captados_medido': False}]
    for x in entries.sort_values('anio').itertuples():
        rows.append({'caso_modal': f'aforos_{x.anio}',
                     'referencia_modal': f'Reparto condicionado desde aforos {x.anio}',
                     'anio_fuente': int(x.anio),
                     'fraccion_coche_condicionada': float(x.fraccion_personas_paso_en_coche),
                     'ocupacion_coche_condicionada': float(ocupacion_coche),
                     'ocupacion_guagua_condicionada': float(ocupacion_guagua),
                     'clasificacion_modal_confirmada': False,
                     'origen_coche_de_captados_medido': False})
    return {'referencias': pd.DataFrame(rows), 'por_acceso': result['por_acceso'],
            'conjunto_por_sentido': aggregate}


def comprobar_demanda_modal(detalle, resumen, *, ocupacion, fraccion_coche, cupo):
    """Conciliar personas, coches y captación sin sumar sensores y telefonía.

    Retirar todos los coches que excedan el cupo sigue siendo la condición del
    ensayo. Los demás captados se añaden como personas, nunca como coches evitados.
    """
    keys = ['tipo_dia_publicado', 'access_corridor', 'colectivo']
    if detalle.duplicated(keys).any() or resumen.duplicated(['tipo_dia', 'corredor']).any():
        raise ValueError('Demanda duplicada.')
    fields = ['coches_sin_condicionados', 'recorridos_coche_retirados_condicionados_dia',
              'viajes_persona_dia_referencia', 'viajes_persona_captables_dia_referencia']
    if (not np.isfinite(detalle[fields]).all().all() or detalle[fields].lt(0).any().any()
            or not np.isfinite([ocupacion, fraccion_coche, cupo]).all()
            or ocupacion < 1 or not 0 <= fraccion_coche <= 1 or cupo < 0):
        raise ValueError('Condiciones o magnitudes de demanda inválidas.')
    if detalle.viajes_persona_captables_dia_referencia.gt(detalle.viajes_persona_dia_referencia + 1e-8).any():
        raise ValueError('La captación no puede superar la demanda de su grupo.')
    if not set(detalle.tipo_dia_publicado) == set(resumen.tipo_dia):
        raise ValueError('Días de demanda y resumen distintos.')
    records = []
    for day, group in detalle.groupby('tipo_dia_publicado'):
        r = resumen.loc[resumen.tipo_dia.eq(day)]
        if set(r.corredor) != set(group.access_corridor):
            raise ValueError('Falta un corredor en la conciliación.')
        if group.dias_calendario.nunique() != 1 or r.dias_calendario.nunique() != 1:
            raise ValueError('Calendario incoherente.')
        days = float(group.dias_calendario.iloc[0])
        if days <= 0 or days != int(days) or days != r.dias_calendario.iloc[0]:
            raise ValueError('Días no enteros o de otro calendario.')
        cars = float(group.coches_sin_condicionados.sum())
        removed = float(group.recorridos_coche_retirados_condicionados_dia.sum())
        retained = cars - removed
        people = float(group.viajes_persona_dia_referencia.sum())
        original_car = cars * ocupacion
        original_other = people - original_car
        other_captured = float(group.viajes_persona_captables_dia_referencia.sum() * (1-fraccion_coche))
        demand = removed * ocupacion + other_captured
        if (removed < -1e-8 or retained < -1e-8 or retained > cupo+1e-8
                or original_other < -1e-8 or other_captured > original_other+1e-8
                or not np.isclose(original_car, people*fraccion_coche, rtol=1e-12, atol=1e-8)
                or not np.isclose(r.coches_sin_condicionados_dia.sum(), cars)
                or not np.isclose(r.coches_autorizados_condicionados_dia.sum(), retained)
                or not np.isclose(r.demanda_lanzadera_condicionada_dia.sum(), demand)):
            raise ValueError('No concilian personas, cupo global, coches o demanda de lanzadera.')
        records.append({'tipo_dia': day, 'dias_calendario': int(days),
            'personas_referencia_dia': people, 'personas_en_coche_sin_dia': original_car,
            'personas_otros_modos_sin_dia': original_other,
            'coches_sin_dia': cars, 'coches_autorizados_dia': retained,
            'coches_transferidos_dia': removed,
            'personas_transferidas_desde_coche_dia': removed*ocupacion,
            'personas_captadas_desde_otros_modos_dia': other_captured,
            'personas_otros_modos_que_permanecen_dia': original_other-other_captured,
            'personas_lanzadera_dia': demand,
            'conservacion_personas_comprobada': bool(np.isclose(
                people, retained*ocupacion+demand+original_other-other_captured)),
            'personas_lanzadera_anio': demand*days,
            'coches_transferidos_anio': removed*days,
            'coches_sin_anio': cars*days,
            'coches_autorizados_anio': retained*days})
    return pd.DataFrame(records)


def preparar_conteos_reforzados(movimientos, objetivos, *, capacidad):
    """Añadir los pares mínimos por cantidad de plazas, sin fingir un horario.

    Las filas añadidas son plantillas de conteo para el planificador existente.
    Deben reconstruirse horario, continuidad, flota, vacío y energía antes de usar
    la oferta. Esta función sola no acredita retornos o capacidad interior.
    """
    if (isinstance(capacidad, bool) or not np.isfinite(capacidad)
            or capacidad <= 0 or capacidad != int(capacidad)):
        raise ValueError('La capacidad debe ser un número entero positivo.')
    if (objetivos.duplicated(['tipo_dia', 'punto']).any()
            or movimientos.duplicated(['tipo_dia', 'id_salida']).any()
            or set(objetivos.punto) != set(PUNTOS.values())
            or set(objetivos.tipo_dia) != set(movimientos.tipo_dia)):
        raise ValueError('Objetivos o movimientos duplicados/incompletos.')
    demand = objetivos.demanda_lanzadera_condicionada_dia
    if not np.isfinite(demand).all() or demand.lt(0).any():
        raise ValueError('Demanda no válida.')
    extra = []; controls = []
    for row in objetivos.sort_values(['tipo_dia', 'punto']).itertuples():
        g = movimientos.loc[movimientos.tipo_dia.eq(row.tipo_dia) & movimientos.punto.eq(row.punto)
                           & movimientos.componente.eq('comercial')]
        counts = g.sentido.value_counts()
        if not {'ida', 'vuelta'} <= set(counts.index) or counts['vuelta'] < counts['ida']:
            raise ValueError('Falta oferta o regreso en la plantilla.')
        required = int(math.ceil(max(0., row.demanda_lanzadera_condicionada_dia-1e-9)/capacidad))
        pairs = max(0, required-int(counts['ida']))
        controls.append({'tipo_dia': row.tipo_dia, 'punto': row.punto,
            'demanda_lanzadera_dia': row.demanda_lanzadera_condicionada_dia,
            'ida_previa_dia': int(counts['ida']), 'vuelta_previa_dia': int(counts['vuelta']),
            'pares_adicionales_por_capacidad': pairs, 'ida_propuesta_dia': int(counts['ida'])+pairs,
            'vuelta_propuesta_dia': int(counts['vuelta'])+pairs,
            'plazas_ida_antes': int(counts['ida'])*capacidad})
        for sense in ['ida', 'vuelta']:
            template = g.loc[g.sentido.eq(sense)].iloc[0]
            for n in range(pairs):
                x = template.to_dict()
                x['id_salida'] = f'{row.punto}_plantilla_modal_{sense}_{n:03d}'
                extra.append(x)
    prepared = pd.concat([movimientos.copy(deep=True), pd.DataFrame(extra)], ignore_index=True)
    if prepared.duplicated(['tipo_dia', 'id_salida']).any():
        raise ValueError('El refuerzo genera un identificador repetido.')
    return {'plantilla_recuento': prepared, 'refuerzos': pd.DataFrame(controls)}


def anualizar_oferta_modal(movimientos, referencias, parametros):
    """Sumar todos los viajes finales, incluidos vacíos, con factores nativos."""
    v = {x['id']: x['valor_utilizado'] for x in parametros['parametros']}
    activities = []; energies = []
    units = referencias.drop(columns=['caso_excel', 'sha256_libro'], errors='ignore')
    for day, group in movimientos.groupby('tipo_dia'):
        days = group.dias_calendario.unique()
        if len(days) != 1 or days[0] <= 0 or days[0] != int(days[0]):
            raise ValueError('Calendario incompatible con los movimientos.')
        rows = []
        for (point, component, sense), block in group.groupby(['punto', 'componente', 'sentido']):
            first = block.iloc[0]; n = len(block)
            rows.append({'punto': point, 'componente': component, 'sentido': sense,
                'origen': first.origen, 'destino': first.destino, 'itinerary_id': first.itinerary_id,
                'recorridos_dia': n, 'km_por_recorrido': first.km_por_recorrido,
                'vehiculo_km_dia': float(block.km_por_recorrido.sum()),
                'dias_operacion': int(days[0]), 'recorridos_anio': n*int(days[0]),
                'vehiculo_km_anio': float(block.km_por_recorrido.sum()*days[0]),
                'base_distancias': 'Recorridos del estudio', 'caso_excel': parametros['caso'],
                'sha256_libro': parametros['sha256_libro']})
        a = pd.DataFrame(rows)
        e = anualizar_consumos_lanzaderas(a, units, caso_excel=parametros['caso'],
            sha256_libro=parametros['sha256_libro'], carga_comercial=v['carga_copert'],
            anio=v['anio_objetivo'])['detalle']
        activities.append(a.assign(tipo_dia=day)); energies.append(e.assign(tipo_dia=day))
    return {'actividad': pd.concat(activities, ignore_index=True),
            'energia': pd.concat(energies, ignore_index=True)}
