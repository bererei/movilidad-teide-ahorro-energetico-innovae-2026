"""Distribuyo un volumen oficial entre proporciones OD, sin corregir los originales."""
from numbers import Real

import numpy as np
import pandas as pd


TOLERANCIA_PERSONAS = 1e-8


def normalizar_aportes(aportes, total_oficial, *, claves, cantidad="aporte_anual_od"):
    """Conservo las proporciones de aportes ya anualizados y un único total.

    Las filas representan entradas externas. No se aceptan regresos o internos
    como visitas adicionales. El total oficial no identifica expansión telefónica
    ni acredita la representatividad de las proporciones.
    """
    if (isinstance(total_oficial, (bool, np.bool_)) or not isinstance(total_oficial, Real)
            or not np.isfinite(total_oficial) or total_oficial <= 0):
        raise ValueError("El total oficial debe ser finito y positivo.")
    requeridas = {*claves, cantidad, "sentido"}
    if aportes.empty or not requeridas <= set(aportes):
        raise ValueError("Faltan aportes anualizados o sus claves.")
    if "visitas_normalizadas_2025" in aportes:
        raise ValueError("La normalización se aplica una sola vez, desde los aportes originales.")
    if aportes[claves].isna().any().any() or aportes.duplicated(claves).any():
        raise ValueError("Hay claves ausentes o repetidas.")
    if not aportes.sentido.eq("entrada").all():
        raise ValueError("Solo las entradas externas se normalizan como visitas.")
    valores = pd.to_numeric(aportes[cantidad], errors="raise")
    if not np.isfinite(valores).all() or valores.lt(0).any() or valores.sum() <= 0:
        raise ValueError("La base OD debe ser finita, no negativa y tener suma positiva.")
    salida = aportes.copy(deep=True)
    salida["proporcion_anual_od"] = valores / valores.sum()
    salida["factor_normalizacion"] = total_oficial / valores.sum()
    salida["visitas_normalizadas_2025"] = total_oficial * salida.proporcion_anual_od
    if not np.isclose(salida.visitas_normalizadas_2025.sum(), total_oficial,
                      rtol=0, atol=TOLERANCIA_PERSONAS):
        raise ValueError("El desglose no conserva el total oficial.")
    return salida


def distribuir_origenes(demanda, totales):
    """Desagrego con los pesos territoriales históricos ya utilizados en el estudio.

    Conservo todos los orígenes de entrada, incluidos los que carecen de grupo
    anual. Para estos últimos la cantidad sigue ausente; no invento un cero.
    Las cabeceras de estudio permanecen separadas del corredor de la fuente.
    """
    d = demanda.loc[demanda.sentido.eq("hacia_teide")].copy(deep=True)
    claves = ["origen_id", "colectivo"]
    grupos = ["corredor_fuente", "colectivo"]
    if (d.empty or d.duplicated(claves).any() or d[claves + grupos[:1]].isna().any().any()
            or totales.duplicated(grupos).any()):
        raise ValueError("Las claves de origen o de grupo anual no son únicas.")
    q = d.viajes_persona_media_57_matrices
    if not np.isfinite(q).all() or q.lt(0).any():
        raise ValueError("Los pesos territoriales históricos no son físicos.")
    columnas = grupos + ["visitas_normalizadas_2025"]
    x = d.merge(totales[columnas].rename(columns={"visitas_normalizadas_2025": "visitas_grupo_anual"}),
                on=grupos, how="left", validate="many_to_one")
    x["en_ambito_anual"] = x.visitas_grupo_anual.notna()
    disponibles = set(map(tuple, x.loc[x.en_ambito_anual, grupos].drop_duplicates().to_numpy()))
    if disponibles != set(map(tuple, totales[grupos].to_numpy())):
        raise ValueError("Hay un grupo anual sin correspondencia territorial.")
    denominador = x.groupby(grupos).viajes_persona_media_57_matrices.transform("sum")
    if (x.en_ambito_anual & denominador.le(0)).any():
        raise ValueError("Un grupo anual carece de pesos territoriales positivos.")
    x["peso_origen_condicionado"] = (x.viajes_persona_media_57_matrices / denominador).where(x.en_ambito_anual)
    x["visitas_normalizadas_2025"] = x.visitas_grupo_anual * x.peso_origen_condicionado
    for _, g in x.loc[x.en_ambito_anual].groupby(grupos):
        if not np.isclose(g.visitas_normalizadas_2025.sum(), g.visitas_grupo_anual.iloc[0],
                          rtol=0, atol=TOLERANCIA_PERSONAS):
            raise ValueError("La desagregación territorial pierde visitas.")
    x["estado"] = np.where(x.en_ambito_anual,
        "Reparto condicionado con pesos históricos; no origen observado de todas las visitas",
        "Sin correspondencia anual: cantidad ausente, no cero ni visitas adicionales")
    return x
