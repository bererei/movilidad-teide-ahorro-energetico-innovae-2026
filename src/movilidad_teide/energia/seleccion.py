"""Selección explícita de resultado central y sensibilidad, sin alterar energía."""
import numpy as np
import pandas as pd


HOT = 'Hot COPERT'
FTA = 'Hot con contraste operativo externo'


def armonizar_resultados(tabla, parametros, *, politica_central):
    """Clasificar resultados pareados desde el libro; nunca elegir por su signo.

    Se conservan todas las filas y sus límites. El selector no convierte
    consumos pendientes en cero ni acredita operación o cumplimiento real.
    """
    rows = {p['id']: p['valor_utilizado'] for p in parametros['parametros']}
    treatment = rows.get('tratamiento_central_guaguas')
    loss = rows.get('perdida_rendimiento_guaguas_contraste')
    if (treatment not in {HOT, FTA} or isinstance(loss, (bool, np.bool_))
            or loss is None or not np.isfinite(loss) or not 0 <= loss < 1):
        raise ValueError('Elegir tratamiento central y amplitud FTA válidos en el Excel.')
    keys = ['politica', 'caso_pendiente', 'alternativa_procedencia', 'referencia_id']
    numeric = ['sin_componentes_mwh_anio', 'con_construccion_condicionada_mwh_anio',
               'guaguas_mwh_anio', 'saldo_construccion_condicionada_mwh_anio',
               'saldo_construccion_condicionada_tep_anio']
    required = set(keys + numeric + ['tratamiento_operativo', 'es_referencia_guagua_elegida',
        'circulacion_30_reglas_propuestas_comprobada', 'cumplimiento_acreditado'])
    if (tabla.empty or not required <= set(tabla) or politica_central not in set(tabla.politica)
            or tabla.duplicated(keys + ['tratamiento_operativo']).any()
            or not np.isfinite(tabla[numeric]).all().all()
            or tabla[['sin_componentes_mwh_anio', 'con_construccion_condicionada_mwh_anio', 'guaguas_mwh_anio']].lt(0).any().any()):
        raise ValueError('Resultados incompletos, duplicados o no válidos.')
    for _, group in tabla.groupby(keys, dropna=False):
        if len(group) != 2 or set(group.tratamiento_operativo) != {HOT, FTA}:
            raise ValueError('Cada combinación debe conservar Hot y FTA.')
        pair = group.set_index('tratamiento_operativo')
        h, f = pair.loc[HOT], pair.loc[FTA]
        if (not np.isclose(f.guaguas_mwh_anio, h.guaguas_mwh_anio / (1-loss), rtol=0, atol=1e-8)
                or not np.isclose(h.sin_componentes_mwh_anio, f.sin_componentes_mwh_anio, rtol=0, atol=1e-8)
                or not np.isclose(h.con_construccion_condicionada_mwh_anio-h.guaguas_mwh_anio,
                    f.con_construccion_condicionada_mwh_anio-f.guaguas_mwh_anio, rtol=0, atol=1e-8)):
            raise ValueError('El contraste FTA no concilia una sola aplicación a las mismas guaguas.')
    delta = tabla.sin_componentes_mwh_anio-tabla.con_construccion_condicionada_mwh_anio
    if (not np.allclose(delta, tabla.saldo_construccion_condicionada_mwh_anio, rtol=0, atol=1e-8)
            or not np.allclose(delta/11.63, tabla.saldo_construccion_condicionada_tep_anio, rtol=0, atol=1e-8)):
        raise ValueError('El saldo y sus unidades no concilian.')
    result = tabla.copy(deep=True)
    result['tratamiento_central_elegido_excel'] = treatment
    result['papel_tratamiento'] = np.where(result.tratamiento_operativo.eq(treatment),
        'Tratamiento central elegido', np.where(result.tratamiento_operativo.eq(FTA),
        'Sensibilidad externa FTA', 'Contraste Hot sin recargo'))
    base = (result.politica.eq(politica_central) & result.caso_pendiente.eq('Referencia del Excel')
            & result.es_referencia_guagua_elegida)
    if not base.any() or not result.loc[base, 'circulacion_30_reglas_propuestas_comprobada'].all():
        raise ValueError('Falta la oferta de estudio con circulación comprobada.')
    result['es_resultado_central'] = base & result.tratamiento_operativo.eq(treatment)
    result['es_contraste_del_central'] = base & ~result.tratamiento_operativo.eq(treatment)
    result['es_sensibilidad_fta'] = result.tratamiento_operativo.eq(FTA) & ~result.tratamiento_operativo.eq(treatment)
    central = result.loc[result.es_resultado_central]
    if (central.alternativa_procedencia.duplicated().any()
            or set(central.alternativa_procedencia) != set(result.alternativa_procedencia)):
        raise ValueError('La referencia central debe conservar las alternativas de procedencia.')
    result['estado_resultado'] = 'Estimación condicionada; consumo real, alcance y operación sujetos a sus límites'
    return result
