"""Represento 2028 conservando los aportes anuales de las nueve referencias OD."""
import numpy as np
import pandas as pd
from .escenarios_2028 import calendario, construir_escenarios, _cuotas_enteras
from .ajuste_invierno import limites_cuotas
from .excursiones_2028 import reasignar_excursiones
from .p85_alternativas import representar_ceros_numericos

CAMPOS = ['visitas_persona_dia', 'visitas_coche', 'visitas_titsa', 'visitas_excursiones_resto_colectivo']
REFERENCIA_MES = {m: 3 if m <= 4 else 7 if m <= 8 else 10 for m in range(1, 13)}
NOMBRES = {3: 'Marzo', 7: 'Julio', 10: 'Octubre'}


class HipotesisModalNoAplicable(ValueError):
    """La población disponible no permite el incremento previsto de excursiones."""


def crear_calendario(anio=2028):
    if anio != 2028:
        raise ValueError('Este contraste conserva el calendario de 2028.')
    fechas = pd.date_range('2028-01-01', '2028-12-31')
    c = pd.DataFrame({'fecha': fechas.strftime('%Y-%m-%d'), 'mes': fechas.month,
                      'tipo_dia_publicado': np.where(fechas.dayofweek == 5, 'Sábado', np.where(fechas.dayofweek == 6, 'Domingo', 'Laborable'))})
    c['mes_referencia'] = c.mes.map(REFERENCIA_MES)
    c['temporada'] = c.mes_referencia.map({3: 'Enero–abril', 7: 'Mayo–agosto', 10: 'Septiembre–diciembre'})
    c['fin_bases_min'] = np.where(c.mes.between(5, 8), 1290, 1200)
    return c


def construir_perfiles_anuales(historica, *, metodo='Estacional'):
    """Cada aporte OD mantiene su peso anual; no ajusto la demanda a la flota.

    Los factores de calendario afectan a la representación temporal de todos
    los modos, manteniendo los totales anuales nativos de TITSA. No son una
    expansión telefónica, crecimiento o mediciones de los meses sin fuente.
    """
    if metodo not in ['Estacional', 'Media anual']:
        raise ValueError('Método temporal no definido.')
    ref = historica.loc[historica.anio_fuente.eq(2025)].copy()
    if ref.matrix_index.nunique() != 9 or set(ref.mes_publicado) != set(NOMBRES.values()):
        raise ValueError('Conservar las nueve referencias OD de 2025.')
    cal = crear_calendario()
    ntemp = cal.groupby(['mes_referencia', 'tipo_dia_publicado']).size()
    nmes = cal.groupby(['mes', 'tipo_dia_publicado']).size()
    anual = calendario(2028)
    claves = ['access_corridor', 'colectivo', 'tipo_dia_publicado', 'hora_servicio']
    media = ref.groupby(claves, as_index=False)[CAMPOS].sum()
    media[CAMPOS] /= 3
    perfiles = []
    for (mes, tipo), dias in nmes.items():
        origen = REFERENCIA_MES[mes]
        if metodo == 'Estacional':
            g = ref.loc[ref.mes_publicado.eq(NOMBRES[origen]) & ref.tipo_dia_publicado.eq(tipo)].copy()
            factor = anual[tipo] / (3 * ntemp.loc[(origen, tipo)])
            fuente = NOMBRES[origen] + ' 2025'
        else:
            g = media.loc[media.tipo_dia_publicado.eq(tipo)].copy()
            factor = 1.
            fuente = 'Media de aportes marzo/julio/octubre 2025'
        for campo in CAMPOS:
            g[campo + '_referencia_dia'] = g[campo]
            g[campo] *= factor
        g['mes_modelo'] = int(mes)
        g['dias_calendario'] = int(dias)
        g['factor_calendario'] = factor
        g['referencia_temporal'] = fuente
        g['metodo_calendario'] = metodo
        g['id_perfil'] = f'M{mes:02d}_{tipo}'
        perfiles.append(g)
    h = pd.concat(perfiles, ignore_index=True)
    esperado = ref[CAMPOS].multiply(ref.tipo_dia_publicado.map(anual) / 3, axis=0).sum()
    obtenido = h[CAMPOS].multiply(h.dias_calendario, axis=0).sum()
    if not np.allclose(esperado, obtenido, atol=1e-8, rtol=0):
        raise ValueError('El calendario cambia los totales anuales de partida.')
    # También conservo el aporte de cada corredor/colectivo/hora/tipo de día.
    a = ref.assign(peso=ref.tipo_dia_publicado.map(anual) / 3)
    a[CAMPOS] = a[CAMPOS].multiply(a.peso, axis=0)
    b = h.copy(); b[CAMPOS] = b[CAMPOS].multiply(b.dias_calendario, axis=0)
    aa = a.groupby(claves)[CAMPOS].sum().sort_index()
    bb = b.groupby(claves)[CAMPOS].sum().sort_index()
    if not aa.index.equals(bb.index) or not np.allclose(aa, bb, atol=1e-8, rtol=0):
        raise ValueError('Se altera la estructura anual de un corredor/colectivo/hora.')
    return cal, h


def aplicar_cupo_global(horaria, origenes, valores, *, cupo=600, incremento=.15):
    """Derivo el reparto OD del único cupo, sin optimizar permisos por carretera.

    Busco el mayor uso entero del máximo global compatible con la excursión
    prevista en cada origen/colectivo. Los permisos pueden quedar sin usar.
    """
    if isinstance(cupo, bool) or int(cupo) != cupo or cupo < 0 or not 0 <= incremento <= .30:
        raise ValueError('Cupo global o incremento de excursiones inválido.')
    from .perfiles_operacion_2028 import COLECTIVOS
    capt = dict(zip(COLECTIVOS, [valores[k] for k in ['captacion_extranjero', 'captacion_nacional', 'captacion_local', 'captacion_frecuente']]))
    def construir(q):
        return construir_escenarios(horaria, origenes, ocupacion=valores['ocupacion_coche'], cupo=q,
             captaciones=capt, hora_inicio=valores['hora_inicio_acceso'], hora_fin=valores['hora_fin_acceso'])
    base = construir(cupo)
    x = base['por_origen_dia']
    if (incremento * x.visitas_excursiones_resto_colectivo > x.visitas_coche + 1e-8).any():
        raise HipotesisModalNoAplicable('No hay población elegible en algún origen/colectivo.')
    pesos = x.groupby('punto').coches_sin_dia.sum()
    maximos = limites_cuotas(x, incremento, ocupacion=valores['ocupacion_coche'])
    usado = None
    for q in range(min(int(cupo), int(np.floor(pesos.sum()))), -1, -1):
        reparto = _cuotas_enteras(pesos, q)
        if (reparto <= np.floor(maximos + 1e-12)).all():
            usado = q
            break
    if usado is None:
        raise HipotesisModalNoAplicable('La hipótesis de excursión no es aplicable a todos los orígenes/colectivos.')
    if usado != cupo:
        base = construir(usado)
    modal = reasignar_excursiones(base, incremento=incremento, ocupacion=valores['ocupacion_coche'])
    modal, residuos = representar_ceros_numericos(modal, ocupacion=valores['ocupacion_coche'])
    p = modal['escenarios_por_punto_dia']
    p['cupo_global_maximo_coches_dia'] = cupo
    p['cupo_global_utilizado_coches_dia'] = usado
    reparto = modal['por_origen_dia'].groupby('punto').cupo_coches_punto.first()
    p['reparto_coches_estimado_OD'] = p.punto.map(reparto)
    p['reparto_es_cuota_regulatoria'] = False
    if abs(p.coches_autorizados_dia.sum() - usado) > 1e-8 or usado > cupo:
        raise ValueError('Se incumple el único máximo global de coches.')
    return modal, residuos
