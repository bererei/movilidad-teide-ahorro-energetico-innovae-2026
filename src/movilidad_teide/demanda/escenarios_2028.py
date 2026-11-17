"""Proyecto las mismas visitas-persona y separo modos sin resolver la oferta.

El cupo limita entradas de coches, nunca visitas. La transferencia completa
es la hipótesis del libro; su viabilidad se comprueba después, sin borrar demanda.
"""
import numpy as np
import pandas as pd

from movilidad_teide.demanda.referencia_oficial import TOLERANCIA_PERSONAS


MODOS = ["visitas_coche", "visitas_titsa", "visitas_excursiones_resto_colectivo"]
CABECERAS = {"Vilaflor": "VILAFLOR", "Aguamansa": "OROTAVA",
             "La Esperanza": "LAGUNA", "Chío": "CHIO"}


def calendario(anio):
    fechas = pd.date_range(f"{anio}-01-01", f"{anio}-12-31")
    tipos = np.where(fechas.dayofweek == 5, "Sábado",
                     np.where(fechas.dayofweek == 6, "Domingo", "Laborable"))
    return pd.Series(tipos).value_counts().astype(int).to_dict()


def proyectar_demanda(horaria, *, anio, tasa):
    """Cambio calendario y aplico una sola tasa, sin renormalizar otra vez."""
    claves = ["access_corridor", "colectivo", "tipo_dia_publicado", "hora_servicio"]
    campos = ["visitas_normalizadas_2025", *MODOS]
    if (horaria.empty or horaria.duplicated(claves).any()
            or horaria[claves].isna().any().any()
            or not horaria.hora_servicio.isin(range(24)).all()
            or not np.isfinite(horaria[campos]).all().all()
            or horaria[campos].lt(0).any().any()):
        raise ValueError("Demanda de entrada inválida o repetida.")
    if isinstance(anio, bool) or not isinstance(anio, int) or anio < 2025:
        raise ValueError("Año objetivo inválido.")
    if isinstance(tasa, bool) or not np.isfinite(tasa) or tasa <= -1:
        raise ValueError("Tasa de crecimiento inválida.")
    if not np.allclose(horaria[MODOS].sum(axis=1), horaria.visitas_normalizadas_2025,
                       atol=TOLERANCIA_PERSONAS, rtol=0):
        raise ValueError("Los modos no conservan las visitas-persona.")
    x = horaria[claves + campos].copy()
    base, futuro = calendario(2025), calendario(anio)
    if set(x.tipo_dia_publicado) != set(base):
        raise ValueError("Falta un tipo de día o hay etiquetas desconocidas.")
    x[campos] = x[campos].div(x.tipo_dia_publicado.map(base), axis=0) * (1 + tasa)**(anio - 2025)
    x = x.rename(columns={"visitas_normalizadas_2025": "visitas_persona_dia"})
    x["dias_calendario"] = x.tipo_dia_publicado.map(futuro)
    x["anio"] = anio
    x["factor_crecimiento"] = (1 + tasa)**(anio - 2025)
    return x


def _cuotas_enteras(pesos, cupo):
    """Mayores restos con desempate estable por punto, como en las reservas."""
    if isinstance(cupo, bool) or cupo < 0 or int(cupo) != cupo:
        raise ValueError("El cupo debe ser un entero no negativo.")
    pesos = pesos.sort_index()
    total = float(pesos.sum())
    techo = min(int(cupo), int(np.floor(total)))
    bruto = pesos * techo / total if total > 0 else pesos * 0
    cuotas = np.floor(bruto).astype(int)
    orden = (bruto - cuotas).sort_values(ascending=False, kind="stable").index
    for punto in orden[:techo - int(cuotas.sum())]:
        cuotas.loc[punto] += 1
    return cuotas


def construir_escenarios(horaria, origenes, *, ocupacion, cupo, captaciones, hora_inicio, hora_fin,
                         cuotas_por_tipo=None):
    """Distribuyo coche/excursiones por origen y TITSA por su corredor de línea.

    Las cuotas de origen son las conservadas en 2025. TITSA no se convierte
    en kilómetros mediante ese reparto: su asignación a cabecera es distinta.
    """
    if (isinstance(ocupacion, bool) or not np.isfinite(ocupacion) or ocupacion < 1
            or set(captaciones) != set(horaria.colectivo)
            or any(not np.isfinite(v) or not 0 <= v <= 1 for v in captaciones.values())):
        raise ValueError("Ocupación o captaciones inválidas.")
    if (any(isinstance(h, bool) or int(h) != h or not 0 <= h <= 23 for h in [hora_inicio, hora_fin])
            or hora_inicio > hora_fin):
        raise ValueError("Ventana de captación inválida.")
    keys = ["access_corridor", "colectivo", "tipo_dia_publicado", "dias_calendario"]
    h = horaria.copy()
    h["visitas_excursiones_transferidas_dia"] = (h.visitas_excursiones_resto_colectivo
        * h.colectivo.map(captaciones) * h.hora_servicio.between(hora_inicio, hora_fin))
    diario = h.groupby(keys, as_index=False)[["visitas_persona_dia", *MODOS,
                                           "visitas_excursiones_transferidas_dia"]].sum()
    o = origenes.loc[origenes.en_ambito_anual].copy()
    if (o.duplicated(["origen_id", "colectivo"]).any()
            or not o.cabecera_calculo.isin(CABECERAS).all()
            or not np.isfinite(o.peso_origen_condicionado).all()
            or o.peso_origen_condicionado.lt(0).any()):
        raise ValueError("Pesos territoriales inválidos.")
    pesos = o.groupby(["corredor_fuente", "colectivo"]).peso_origen_condicionado.sum()
    if not np.allclose(pesos, 1, atol=1e-12, rtol=0):
        raise ValueError("Los pesos de origen no suman uno.")
    esperados = set(map(tuple, diario[["access_corridor", "colectivo"]].to_numpy()))
    if esperados != set(pesos.index):
        raise ValueError("No coinciden los ámbitos anual y territorial.")
    columnas = ["origen_id", "colectivo", "corredor_fuente", "corredor_calculo",
                "cabecera_calculo", "peso_origen_condicionado"]
    x = diario.merge(o[columnas], left_on=["access_corridor", "colectivo"],
                     right_on=["corredor_fuente", "colectivo"], validate="many_to_many")
    # Solo coche y excursiones emplean estos orígenes para sus recorridos.
    x = x.drop(columns=["visitas_persona_dia", "visitas_titsa"])
    for c in ["visitas_coche", "visitas_excursiones_resto_colectivo", "visitas_excursiones_transferidas_dia"]:
        x[c] *= x.peso_origen_condicionado
    x["punto"] = x.cabecera_calculo.map(CABECERAS)
    x["coches_sin_dia"] = x.visitas_coche / ocupacion
    x["captacion_excursiones"] = x.colectivo.map(captaciones)
    x["visitas_excursiones_permanecen_dia"] = x.visitas_excursiones_resto_colectivo - x.visitas_excursiones_transferidas_dia
    bloques = []
    for _, b in x.groupby("tipo_dia_publicado", sort=True):
        b = b.copy()
        coches = b.groupby("punto").coches_sin_dia.sum()
        if cuotas_por_tipo is None:
            cuotas = _cuotas_enteras(coches, cupo)
        else:
            cuotas = pd.Series(cuotas_por_tipo[b.tipo_dia_publicado.iloc[0]])
            if (set(cuotas.index) != set(coches.index) or not np.isfinite(cuotas).all()
                    or cuotas.lt(0).any() or cuotas.ne(np.floor(cuotas)).any()
                    or cuotas.sum() != cupo):
                raise ValueError("Cuotas de acceso incompatibles con el cupo global.")
            cuotas = cuotas.astype(int)
        autorizados = pd.concat([cuotas, coches], axis=1).min(axis=1)
        ratio = autorizados / coches.replace(0, np.nan)
        b["coches_autorizados_dia"] = b.coches_sin_dia * b.punto.map(ratio).fillna(0.)
        b["cupo_coches_punto"] = b.punto.map(cuotas)
        b["coches_transferidos_dia"] = b.coches_sin_dia - b.coches_autorizados_dia
        b["visitas_coche_autorizadas_dia"] = b.coches_autorizados_dia * ocupacion
        b["visitas_coche_transferidas_dia"] = b.coches_transferidos_dia * ocupacion
        bloques.append(b)
    x = pd.concat(bloques, ignore_index=True)
    # La demanda TITSA conserva el corredor de cada línea, sin reencaminarla
    # desde los pesos de origen, expresamente no aptos para kilómetros TITSA.
    from movilidad_teide.opciones import PUNTOS
    t = diario[[*keys, "visitas_titsa"]].copy()
    t["punto"] = t.access_corridor.map(PUNTOS)
    if t.punto.isna().any():
        raise ValueError("Corredor TITSA sin cabecera de estudio.")
    group = ["tipo_dia_publicado", "dias_calendario", "punto"]
    cols = ["coches_sin_dia", "coches_autorizados_dia", "coches_transferidos_dia",
            "visitas_coche", "visitas_coche_autorizadas_dia", "visitas_coche_transferidas_dia",
            "visitas_excursiones_resto_colectivo", "visitas_excursiones_transferidas_dia",
            "visitas_excursiones_permanecen_dia"]
    puntos = x.groupby(group, as_index=False)[cols].sum().merge(
        t.groupby(group, as_index=False).visitas_titsa.sum(), on=group, validate="one_to_one")
    puntos["demanda_lanzadera_dia"] = (puntos.visitas_coche_transferidas_dia
        + puntos.visitas_excursiones_transferidas_dia + puntos.visitas_titsa)
    puntos["visitas_sin_dia"] = puntos.visitas_coche + puntos.visitas_excursiones_resto_colectivo + puntos.visitas_titsa
    puntos["visitas_con_objetivo_dia"] = (puntos.visitas_coche_autorizadas_dia
        + puntos.visitas_excursiones_permanecen_dia + puntos.demanda_lanzadera_dia)
    puntos["titsa_acceso_con_dia"] = 0.
    puntos["regresos_lanzadera_pareados_dia"] = puntos.demanda_lanzadera_dia
    puntos["estado"] = "Objetivo de conservación de visitas; capacidad pendiente de comprobación"
    return {"por_origen_dia": x, "titsa_por_corredor_colectivo_dia": t,
            "escenarios_por_punto_dia": puntos,
            "origenes_sin_cantidad_anual": origenes.loc[~origenes.en_ambito_anual].copy()}
