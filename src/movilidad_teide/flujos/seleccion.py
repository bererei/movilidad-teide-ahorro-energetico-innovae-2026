from pathlib import Path
import json, hashlib, platform
import numpy as np, pandas as pd
from movilidad_teide.parametros import leer_parametros
from movilidad_teide.presentacion_balance import armonizar_resultados, HOT, FTA
from .tipos import Etapa

def calcular_seleccion(parametros, previa):
    P218 = parametros
    now218 = {p['id']: p for p in P218['parametros']}
    losskey218 = 'perdida_rendimiento_guaguas_contraste'
    B218 = previa.tablas['balance_anual_propuesta'].copy()
    policy218 = previa.tablas['comparacion_referencias_consumo'].politica.unique().item()
    V218 = armonizar_resultados(B218, P218, politica_central=policy218)
    C218 = V218.loc[V218.es_resultado_central].copy()
    F218 = V218.loc[V218.es_contraste_del_central].copy()
    assert len(C218) == len(F218) == 2 and C218.tratamiento_operativo.eq(HOT).all() and F218.tratamiento_operativo.eq(FTA).all()
    pd.testing.assert_frame_equal(V218[B218.columns], B218)
    comparison218 = V218.loc[V218.caso_pendiente.eq('Referencia del Excel')].copy()
    thresholds218 = []
    for r in C218.itertuples():
        margin218 = r.saldo_construccion_condicionada_mwh_anio - 60 * 11.63
        thresholds218.append({'alternativa_procedencia': r.alternativa_procedencia, 'guaguas_hot_mwh_anio': r.guaguas_mwh_anio, 'margen_sobre_60_mwh_anio': margin218, 'margen_sobre_60_tep_anio': margin218 / 11.63, 'umbral_consumo_guaguas_para_60_mwh_anio': r.guaguas_mwh_anio + margin218, 'incremento_consumo_guaguas_que_agota_margen_pct': 100 * margin218 / r.guaguas_mwh_anio, 'demas_componentes_fijos': True, 'probabilidad_asignada': False, 'cumplimiento_acreditado': False})
    config218 = pd.DataFrame([{'id': k, 'valor_utilizado': now218[k]['valor_utilizado'], 'modo': now218[k]['modo_efectivo'], 'justificacion': now218[k]['justificacion_utilizada']} for k in ['tratamiento_central_guaguas', losskey218, 'referencia_guagua_acceso', 'referencia_guagua_interior', 'alcance_consumo_anual', 'reserva_minima_dentro_flota', 'intervalo_refuerzo_punta_min']])
    checks218 = V218[['politica', 'caso_pendiente', 'alternativa_procedencia', 'referencia_id', 'tratamiento_operativo']].copy()
    for f in ['sin_componentes_mwh_anio', 'con_construccion_condicionada_mwh_anio', 'guaguas_mwh_anio', 'saldo_construccion_condicionada_mwh_anio', 'saldo_construccion_condicionada_tep_anio']:
        checks218['cambio_' + f] = V218[f] - B218[f]
        assert checks218['cambio_' + f].eq(0).all()
    conditions218 = pd.DataFrame([{'aspecto': 'Consumo central', 'estado': 'Hot COPERT elegido; estimación condicionada, no consumo real calibrado', 'referencia': 'D218; autocar diésel sin ventaja híbrida D212'}, {'aspecto': 'Sensibilidad FTA', 'estado': 'Pérdida10% de km/combustible; incremento11,111% de energía solo en contraste externo', 'referencia': 'F126 FTA/WVU2007, p.9; D166/D183/D218'}, {'aspecto': 'Operación', 'estado': '30 físicas; hasta27 programadas y mínimo tres libres; refuerzo15min explícito donde necesario; propuesta sin aprobación institucional', 'referencia': 'D216; identidades y cierre por bases comprobados'}, {'aspecto': 'Demanda sin/con', 'estado': 'Mismas nueve observaciones y pesos; demanda completa y p85 separados; no calendario confirmado', 'referencia': 'D194/D213/D216'}, {'aspecto': 'Pendiente de turismos', 'estado': 'Ajuste convencional completo; otras tecnologías mantienen Hot con cambio de pendiente sin estimar', 'referencia': 'D213'}, {'aspecto': 'Frontera energética', 'estado': 'Frío excluido del alcance Hot; instalaciones fijas excluidas; maniobras/consumos materiales pendientes no se convierten en cero', 'referencia': 'D162/D181/D213/D216'}, {'aspecto': 'Fiabilidad', 'estado': 'Tres sin programar son margen nominal; disponibilidad efectiva y respuesta por ubicación sin acreditar', 'referencia': 'D216'}, {'aspecto': 'Conclusiones del informe', 'estado': 'Requisitos y recomendaciones junto al resultado; contraste desfavorable y umbrales visibles; sin intervalo de confianza global', 'referencia': 'D196/D217/D218'}])
    tables218 = {'balance_vigente': V218, 'resultado_central': C218, 'sensibilidad_fta': F218, 'comparacion_ofertas_y_referencias': comparison218, 'configuracion_presentacion': config218, 'umbrales_central': pd.DataFrame(thresholds218), 'comparacion_con_etapa_anterior': checks218, 'condiciones_resultado': conditions218}
    return Etapa(tables218, {})
