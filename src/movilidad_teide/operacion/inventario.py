"""Inventario físico cerrado: las unidades libres ya forman la sustitución.

Se verifica la operación programada. No se simulan averías ni se acredita
la respuesta de una sustituta ubicada en otra base.
"""
from collections import Counter
import numpy as np
import pandas as pd


def _entero(valor, nombre, minimo=0):
    if (isinstance(valor, (bool, np.bool_)) or not isinstance(valor, (int, float, np.number))
            or not np.isfinite(valor) or valor != int(valor) or valor < minimo):
        raise ValueError(f'{nombre}: se requiere un entero válido.')
    return int(valor)


def construir_inventario(vehiculos, *, total):
    """Un mismo parque inicial cubre observaciones y políticas alternativas.

    Los máximos por base se obtienen del horario, no del objetivo energético.
    El remanente se sitúa en el acceso con más vehículos requeridos, criterio
    sencillo de estudio que no acredita su ubicación óptima ante averías.
    """
    total = _entero(total, 'Flota total', 1)
    keys = ['politica', 'observacion', 'punto', 'terminal_inicial']
    if (vehiculos.empty or not set(keys + ['vehiculo_id']) <= set(vehiculos)
            or vehiculos[keys + ['vehiculo_id']].isna().any().any()
            or vehiculos.duplicated(['politica', 'observacion', 'vehiculo_id']).any()):
        raise ValueError('Asignaciones de vehículos incompletas o duplicadas.')
    need = (vehiculos.groupby(keys).size().groupby(['punto', 'terminal_inicial'])
            .max().rename('puestos_requeridos').reset_index())
    if need.puestos_requeridos.sum() > total:
        raise ValueError('El inventario no cubre las bases; hacen falta recolocaciones explícitas.')
    need['unidades_inventario'] = need.puestos_requeridos
    candidates = need.loc[need.punto.ne('INTERIOR')]
    if candidates.empty:
        candidates = need
    chosen = candidates.sort_values(['puestos_requeridos', 'punto', 'terminal_inicial'],
                                    ascending=[False, True, True]).index[0]
    need.loc[chosen, 'unidades_inventario'] += total - need.puestos_requeridos.sum()
    rows = []
    for r in need.sort_values(['punto', 'terminal_inicial']).itertuples():
        for _ in range(int(r.unidades_inventario)):
            rows.append({'unidad_fisica_id': f'TF{len(rows)+1:02d}',
                         'punto': r.punto, 'terminal_inicial': r.terminal_inicial})
    return pd.DataFrame(rows), need


def asignar_inventario(movimientos, vehiculos, inventario, *, reserva_minima, regulacion):
    """Asignar identidades físicas y cerrar el inventario tras cada construcción.

    La secuencia ordenada es una auditoría, no un calendario futuro. El balance
    por terminal se conserva en cada jornada; por ello admite cualquier orden
    de los perfiles sin recolocaciones gratuitas. Las identidades físicas se
    mantienen al cambiar de jornada aunque un vehículo acabe en otro terminal.
    """
    minimum = _entero(reserva_minima, 'Reserva mínima')
    if (inventario.empty or inventario.unidad_fisica_id.duplicated().any()
            or inventario[['unidad_fisica_id', 'punto', 'terminal_inicial']].isna().any().any()
            or isinstance(regulacion, (bool, np.bool_)) or not np.isfinite(regulacion) or regulacion < 0):
        raise ValueError('Inventario o regulación no válidos.')
    total = len(inventario)
    if minimum > total:
        raise ValueError('La reserva mínima supera la flota total.')
    grouping = ['politica', 'observacion']
    if (vehiculos.duplicated(grouping + ['vehiculo_id']).any()
            or movimientos.duplicated(grouping + ['id_salida']).any()
            or set(map(tuple, vehiculos[grouping].to_numpy())) != set(map(tuple, movimientos[grouping].to_numpy()))):
        raise ValueError('Construcciones de flota y movimientos incompatibles o repetidas.')
    initial = dict(zip(inventario.unidad_fisica_id,
                       zip(inventario.punto, inventario.terminal_inicial)))
    target = Counter(initial.values())
    roles, moves, balances, diagnostics = [], [], [], []
    for policy, scenarios in vehiculos.groupby('politica', sort=True):
        positions = initial.copy()
        for sequence, (obs, fleet) in enumerate(scenarios.groupby('observacion', sort=True)):
            g = movimientos.loc[movimientos.politica.eq(policy) & movimientos.observacion.eq(obs)]
            if set(g.vehiculo_id) != set(fleet.vehiculo_id):
                raise ValueError('Vehículo sin sus movimientos o movimiento sin vehículo.')
            start = positions.copy()
            assignments = {}
            for r in fleet.sort_values(['punto', 'terminal_inicial', 'vehiculo_id']).itertuples():
                choices = sorted(u for u, location in start.items()
                                 if location == (r.punto, r.terminal_inicial) and u not in assignments)
                if not choices:
                    raise ValueError('Falta una unidad en su base; no se permiten traslados implícitos.')
                unit = choices[0]
                assignments[unit] = r.vehiculo_id
                path = g.loc[g.vehiculo_id.eq(r.vehiculo_id)].sort_values(['salida_min', 'id_salida'])
                location, ready = r.terminal_inicial, -np.inf
                for trip in path.itertuples():
                    if (trip.punto != r.punto or trip.origen != location
                            or trip.salida_min < ready-1e-8
                            or not np.isfinite([trip.salida_min, trip.llegada_min, trip.km_por_recorrido]).all()
                            or trip.llegada_min <= trip.salida_min or trip.km_por_recorrido <= 0):
                        raise ValueError('Circulación sin continuidad, tiempo o regulación suficiente.')
                    location = trip.destino
                    ready = trip.llegada_min + regulacion
                positions[unit] = (r.punto, location)
                moves.append(path.assign(unidad_fisica_id=unit, orden_auditoria=sequence))
            if Counter(positions.values()) != target:
                raise ValueError('No cierra el inventario por terminal; falta programar una recolocación.')
            for unit, base in start.items():
                roles.append({'politica': policy, 'observacion': obs, 'orden_auditoria': sequence,
                    'unidad_fisica_id': unit, 'punto': base[0], 'terminal_inicial': base[1],
                    'terminal_final': positions[unit][1], 'vehiculo_horario_id': assignments.get(unit),
                    'programada': unit in assignments,
                    'rol': 'Operación programada' if unit in assignments else 'Sin programar; sustitución propuesta'})
            for (point, terminal), stock in target.items():
                active = sum(u in assignments and base == (point, terminal) for u, base in start.items())
                balances.append({'politica': policy, 'observacion': obs, 'punto': point,
                    'terminal': terminal, 'inventario_inicial': stock,
                    'inventario_final': Counter(positions.values())[point, terminal],
                    'programadas_desde_base': active, 'sin_programar_en_base': stock-active})
            active = len(assignments)
            diagnostics.append({'politica': policy, 'observacion': obs, 'flota_total': total,
                'vehiculos_programados': active, 'vehiculos_sin_programar': total-active,
                'minimo_sustitucion_propuesto': minimum,
                'cumple_minimo_sustitucion': total-active >= minimum,
                'cierre_de_bases_comprobado': True,
                'respuesta_ante_averias_validada': False, 'propuesta_adoptada': False})
    return {'asignaciones': pd.DataFrame(roles), 'movimientos': pd.concat(moves, ignore_index=True),
            'balance_bases': pd.DataFrame(balances), 'diagnostico': pd.DataFrame(diagnostics)}


def comprobar_intervalos(movimientos, cotas, *, intervalo_ordinario, intervalo_punta):
    """Permitir refuerzo solo donde la cota ordinaria no cubre la demanda.

    La cota es favorable: su exceso justifica ensayar refuerzo, pero no valida
    por sí solo el horario. La asignación de cadenas conserva su comprobación.
    """
    if (not np.isfinite([intervalo_ordinario, intervalo_punta]).all()
            or isinstance(intervalo_ordinario, (bool, np.bool_))
            or isinstance(intervalo_punta, (bool, np.bool_))
            or not 0 < intervalo_punta <= intervalo_ordinario
            or cotas.duplicated(['matrix_index', 'punto']).any()):
        raise ValueError('Intervalos o cotas incompatibles.')
    lookup = cotas.set_index(['matrix_index', 'punto'])
    trips = movimientos.loc[movimientos.componente.str.startswith('comercial')
                            & movimientos.punto.ne('INTERIOR') & movimientos.sentido.eq('ida')]
    rows = []
    for (policy, obs, point), g in trips.groupby(['politica', 'observacion', 'punto']):
        gaps = g.salida_min.sort_values().diff().dropna()
        actual = float(gaps.min()) if len(gaps) else np.inf
        excess = bool(lookup.loc[(obs, point), 'incompatible_incluso_sin_conflictos_interiores']) if (obs, point) in lookup.index else False
        used = intervalo_punta if excess else intervalo_ordinario
        rows.append({'politica': policy, 'observacion': obs, 'punto': point,
            'intervalo_real_min': actual, 'cota_ordinaria_insuficiente': excess,
            'intervalo_ordinario_min': intervalo_ordinario, 'intervalo_propuesto_aplicable_min': used,
            'cumple_regla_vigente': actual >= intervalo_ordinario-1e-8,
            'cumple_regla_propuesta': actual >= used-1e-8,
            'excepcion_de_regla_necesaria': actual < intervalo_ordinario-1e-8,
            'propuesta_adoptada': False})
    return pd.DataFrame(rows)
