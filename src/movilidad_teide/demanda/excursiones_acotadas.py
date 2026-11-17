"""Aplico un incremento explícito de excursiones conservando origen y colectivo."""
import math
import numpy as np
import pandas as pd
from .ajuste_invierno import limites_cuotas, reasignar_invierno


def reasignar_con_maximos(origenes, puntos, cuotas, *, incremento, ocupacion):
    """El cupo es un máximo; no se llena si faltan viajeros elegibles.

    El saldo coche→lanzadera es operativo, no el flujo bruto de alimentación
    necesario para calcular energía. Se reutiliza la conservación de D246.
    """
    if not 0 <= incremento <= .15:
        raise ValueError('El contraste admite incrementos entre cero y quince por ciento.')
    maximum = limites_cuotas(origenes, incremento, ocupacion=ocupacion)
    efectivos = {p: min(q, max(0, math.floor(maximum[p] + 1e-12))) for p, q in cuotas.items()}
    base = puntos.copy()
    # Las columnas originales C/E/T son la referencia; no sumo el aumento P20.
    base['visitas_excursiones_con_intervencion_dia'] = base.visitas_excursiones_resto_colectivo
    x, pt = reasignar_invierno(origenes, base, efectivos, incremento=incremento, ocupacion=ocupacion)
    pt['cuota_maxima_coches_dia'] = pt.punto.map(cuotas)
    pt['coches_no_autorizados_por_bolsa_elegible'] = pt.cuota_maxima_coches_dia - pt.coches_autorizados_dia
    # Las utilidades de fecha trabajan sobre los saldos operativos del caso.
    x['visitas_coche_transferidas_dia'] = x.visitas_coche_a_lanzadera_dia
    x['visitas_excursiones_transferidas_dia'] = 0.
    pt['visitas_coche_transferidas_dia'] = pt.visitas_coche_a_lanzadera_dia
    pt['visitas_excursiones_transferidas_dia'] = 0.
    pt['demanda_bruta_lanzadera_dia'] = pt.demanda_lanzadera_dia + pt.coches_autorizados_dia * ocupacion
    return {'por_origen_dia': x, 'escenarios_por_punto_dia': pt}


def p85_afin_comprobado(origenes, diarios, *, incremento, ocupacion, cupo_maximo):
    """Compruebo la forma afín en todos los cupos enteros antes de usarla.

    Las referencias pequeñas pueden dejar permisos sin usar; por eso no doy
    por supuesto que restar un cupo al percentil sea siempre válido.
    """
    filas = []
    for obs, g in diarios.groupby('matrix_index'):
        upper = limites_cuotas(origenes[obs], incremento, ocupacion=ocupacion)
        for row in g.itertuples():
            filas.append({'matrix_index': int(obs), 'punto': row.punto,
                          'bruto': row.visitas_coche + row.visitas_titsa - incremento * row.visitas_excursiones_resto_colectivo,
                          'maximo_elegible': max(0, math.floor(upper[row.punto] + 1e-12))})
    raw = pd.DataFrame(filas)
    resultado = []; controles = []
    for punto, g in raw.groupby('punto'):
        maximum = cupo_maximo[punto] if isinstance(cupo_maximo, dict) else cupo_maximo
        grid = np.arange(maximum + 1)
        if len(g) != 57:
            raise ValueError('El p85 requiere las 57 matrices originales.')
        bruto = g.bruto.to_numpy()
        real = np.quantile(bruto[:, None] - ocupacion * np.minimum(grid, g.maximo_elegible.to_numpy()[:, None]), .85, axis=0, method='linear')
        p85 = float(np.quantile(bruto, .85, method='linear'))
        error = float(np.max(np.abs(real - (p85 - grid * ocupacion))))
        if error > 1e-8:
            raise ValueError(f'No se admite aproximación afín del p85 en {punto}: {error}.')
        resultado.append({'punto': punto, 'demanda_bruta_lanzadera_dia': p85})
        controles.append({'punto': punto, 'cuotas_enteras_comprobadas': len(grid), 'error_maximo_personas': error})
    return pd.DataFrame(resultado), pd.DataFrame(controles)
