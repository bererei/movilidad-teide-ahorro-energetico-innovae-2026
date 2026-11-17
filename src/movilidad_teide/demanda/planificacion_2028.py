"""Distribuyo la referencia de planificación sin confundirla con observaciones."""
from numbers import Real

import numpy as np
import pandas as pd

from .escenarios_2028 import MODOS, calendario
from .referencia_oficial import TOLERANCIA_PERSONAS


CLAVES = ["access_corridor", "colectivo", "tipo_dia_publicado", "hora_servicio"]


def distribuir_referencia(horaria, total, fraccion_coche):
    """Uso la forma OD de 2028, fijo su volumen y conservo TITSA nativo.

    La tasa común incluida en el vector previo se cancela al obtener las
    proporciones. El total adoptado ya corresponde a 2028: no crece otra vez.
    Excursiones sigue siendo el resto colectivo, no una medición independiente.
    """
    if (isinstance(total, (bool, np.bool_)) or not isinstance(total, Real)
            or not np.isfinite(total) or total <= 0
            or isinstance(fraccion_coche, (bool, np.bool_))
            or not isinstance(fraccion_coche, Real)
            or not np.isfinite(fraccion_coche) or not 0 <= fraccion_coche <= 1):
        raise ValueError("Volumen o cuota modal inválidos.")
    campos = [*CLAVES, "anio", "dias_calendario", "visitas_persona_dia", *MODOS]
    if horaria.empty or not set(campos) <= set(horaria):
        raise ValueError("Faltan entradas de demanda de 2028.")
    h = horaria[campos].copy(deep=True)
    numericos = ["visitas_persona_dia", *MODOS]
    if (h.duplicated(CLAVES).any() or h[CLAVES].isna().any().any()
            or not h.anio.eq(2028).all() or not h.hora_servicio.isin(range(24)).all()
            or not np.isfinite(h[numericos]).all().all() or h[numericos].lt(0).any().any()
            or set(h.tipo_dia_publicado) != set(calendario(2028))
            or not h.dias_calendario.eq(h.tipo_dia_publicado.map(calendario(2028))).all()):
        raise ValueError("Demanda duplicada, no física o calendario distinto de 2028.")
    if not np.allclose(h[MODOS].sum(axis=1), h.visitas_persona_dia,
                       atol=TOLERANCIA_PERSONAS, rtol=0):
        raise ValueError("La separación modal previa no conserva personas.")
    if not np.allclose(h.visitas_coche, h.visitas_persona_dia * fraccion_coche,
                       atol=TOLERANCIA_PERSONAS, rtol=0):
        raise ValueError("La cuota modal no coincide con la referencia conservada.")
    anual_previo = h.visitas_persona_dia * h.dias_calendario
    if anual_previo.sum() <= 0:
        raise ValueError("La forma OD no tiene volumen positivo.")
    h["proporcion_anual_od_2028"] = anual_previo / anual_previo.sum()
    h["visitas_persona_anio"] = total * h.proporcion_anual_od_2028
    h["visitas_persona_dia"] = h.visitas_persona_anio / h.dias_calendario
    h["visitas_coche"] = h.visitas_persona_dia * fraccion_coche
    # TITSA conserva calendario y proyección de su fuente propia, sin este factor.
    h["visitas_excursiones_resto_colectivo"] = (
        h.visitas_persona_dia - h.visitas_coche - h.visitas_titsa)
    if h.visitas_excursiones_resto_colectivo.lt(0).any():
        raise ValueError("La referencia deja menos colectivo que el TITSA nativo; revisar hipótesis.")
    h["sentido"] = "entrada"
    h["unidad"] = "visitas-persona; no vehículos ni personas únicas anuales"
    if not np.isclose(h.visitas_persona_anio.sum(), total, atol=TOLERANCIA_PERSONAS, rtol=0):
        raise ValueError("El desglose no conserva el volumen adoptado.")
    return h


def distribuir_territorio(horaria, origenes):
    """Conservo los pesos y ausencias de origen; no infiero recorridos TITSA."""
    claves = ["corredor_fuente", "colectivo"]
    columnas = ["origen_id", "colectivo", "corredor_fuente", "corredor_calculo",
                "cabecera_calculo", "en_ambito_anual", "peso_origen_condicionado"]
    o = origenes[columnas].copy(deep=True)
    if (o.duplicated(["origen_id", "colectivo"]).any()
            or o[["origen_id", "colectivo"]].isna().any().any()
            or not o.en_ambito_anual.isin([True, False]).all()):
        raise ValueError("Claves territoriales inválidas.")
    g = horaria.copy()
    cantidades = ["visitas_persona_anio", *[c + "_anio" for c in MODOS]]
    for c in MODOS: g[c + "_anio"] = g[c] * g.dias_calendario
    g = g.groupby(["access_corridor", "colectivo"], as_index=False)[cantidades].sum().rename(
            columns={"access_corridor": "corredor_fuente"})
    anual = set(map(tuple, g[claves].to_numpy()))
    disponible = set(map(tuple, o.loc[o.en_ambito_anual, claves].drop_duplicates().to_numpy()))
    if anual != disponible:
        raise ValueError("No coinciden los grupos territoriales y anuales.")
    pesos = o.loc[o.en_ambito_anual, "peso_origen_condicionado"]
    if (not np.isfinite(pesos).all() or pesos.lt(0).any()
            or not np.allclose(o.loc[o.en_ambito_anual].groupby(claves)
                               .peso_origen_condicionado.sum(), 1, atol=1e-12, rtol=0)
            or o.loc[~o.en_ambito_anual, "peso_origen_condicionado"].notna().any()):
        raise ValueError("Pesos territoriales inválidos o ausencias sustituidas.")
    x = o.merge(g, on=claves, how="left", validate="many_to_one")
    if not x.visitas_persona_anio.notna().eq(x.en_ambito_anual).all():
        raise ValueError("Una ausencia territorial ha recibido demanda.")
    # Este reparto contable no identifica el origen real de pasajeros TITSA.
    x[cantidades] = x[cantidades].mul(x.peso_origen_condicionado, axis=0)
    x["apto_para_calcular_km_titsa"] = False
    x["anio"] = 2028
    x["unidad"] = "visitas-persona/año"
    x["estado"] = np.where(x.en_ambito_anual,
        "Reparto condicionado por pesos OD; no origen observado",
        "Sin correspondencia anual; cantidad ausente, no cero")
    return x
