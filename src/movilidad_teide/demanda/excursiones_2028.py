"""Reasigno demanda prevista de lanzadera a excursión sin añadir visitantes."""
import numpy as np


def reasignar_excursiones(base, *, incremento, ocupacion):
    """El objetivo de excursiones se refiere al escenario sin intervención.

    Parto del reparto con intervención anterior. La diferencia hasta el nuevo
    objetivo sale proporcionalmente de sus viajeros previstos de coche y
    excursión que iban a usar lanzadera. TITSA conserva su traslado independiente
    a lanzadera. La reasignación opera dentro de cada origen/colectivo/perfil.
    """
    if isinstance(incremento, bool) or not np.isfinite(incremento) or incremento < 0:
        raise ValueError("Incremento de excursiones no válido.")
    if not np.isfinite(ocupacion) or ocupacion < 1:raise ValueError("Ocupación no válida.")
    x = base["por_origen_dia"].copy()
    if "incremento_excursiones_sobre_sin" in x:raise ValueError("La reasignación ya está aplicada; partir de la referencia.")
    originales = ["visitas_coche_transferidas_dia", "visitas_excursiones_transferidas_dia",
                  "visitas_excursiones_permanecen_dia"]
    for c in originales:x[c + "_referencia"] = x[c]
    x = x.rename(columns={"captacion_excursiones": "captacion_excursiones_referencia"})
    objetivo = (1 + incremento) * x.visitas_excursiones_resto_colectivo
    mover = objetivo - x.visitas_excursiones_permanecen_dia
    elegibles = x.visitas_coche_transferidas_dia + x.visitas_excursiones_transferidas_dia
    if (mover < -1e-8).any() or (mover > elegibles + 1e-8).any():
        raise ValueError("No hay viajeros elegibles suficientes; no se altera el cupo o la demanda para cuadrar.")
    ratio = np.divide(mover, elegibles, out=np.zeros(len(x)), where=elegibles.gt(0))
    # Los valores de referencia se conservan: no se aplica el porcentaje dos veces.
    x["visitas_coche_a_excursiones_dia"] = x.visitas_coche_transferidas_dia * ratio
    x["visitas_excursiones_que_retornan_desde_lanzadera_dia"] = x.visitas_excursiones_transferidas_dia * ratio
    x["visitas_coche_transferidas_dia"] -= x.visitas_coche_a_excursiones_dia
    x["visitas_excursiones_transferidas_dia"] -= x.visitas_excursiones_que_retornan_desde_lanzadera_dia
    x["visitas_excursiones_permanecen_dia"] += x.visitas_excursiones_que_retornan_desde_lanzadera_dia
    x["visitas_excursiones_con_intervencion_dia"] = x.visitas_excursiones_permanecen_dia + x.visitas_coche_a_excursiones_dia
    x["visitas_reasignadas_lanzadera_a_excursiones_dia"] = mover
    x["fraccion_reasignacion_sobre_lanzadera_elegible"] = ratio
    x["incremento_excursiones_sobre_sin"] = incremento
    # La cuota por origen conserva el reparto anterior del coche autorizado.
    # Limito el cupo de cada acceso para que ningún origen necesite más viajeros
    # de los que puede transferir; no basta una comprobación solo agregada.
    x["ratio_incremento_sobre_coche_sin"] = np.divide(incremento * x.visitas_excursiones_resto_colectivo,
        x.visitas_coche, out=np.zeros(len(x)), where=x.visitas_coche.gt(0))
    if (x.visitas_coche.eq(0) & (incremento * x.visitas_excursiones_resto_colectivo).gt(1e-8)).any():
        raise ValueError("Excursión adicional sin bolsa de coche compatible en ese origen.")
    group = ["tipo_dia_publicado", "dias_calendario", "punto"]
    nuevos = ["visitas_coche_transferidas_dia", "visitas_excursiones_transferidas_dia",
              "visitas_excursiones_permanecen_dia", "visitas_coche_a_excursiones_dia",
              "visitas_excursiones_con_intervencion_dia", "visitas_reasignadas_lanzadera_a_excursiones_dia"]
    p = base["escenarios_por_punto_dia"].drop(columns=nuevos, errors="ignore").merge(
        x.groupby(group, as_index=False)[nuevos].sum(), on=group, validate="one_to_one")
    limites = x.groupby(group).ratio_incremento_sobre_coche_sin.max().rename("ratio_limite").reset_index()
    p = p.merge(limites, on=group, validate="one_to_one")
    p["coches_maximos_para_cupo_dia"] = p.coches_sin_dia * (1 - p.ratio_limite)
    p["demanda_bruta_lanzadera_dia"] = p.visitas_coche - incremento * p.visitas_excursiones_resto_colectivo + p.visitas_titsa
    p["demanda_lanzadera_dia"] = p.visitas_coche_transferidas_dia + p.visitas_excursiones_transferidas_dia + p.visitas_titsa
    p["visitas_con_objetivo_dia"] = p.visitas_coche_autorizadas_dia + p.visitas_excursiones_con_intervencion_dia + p.demanda_lanzadera_dia
    p["regresos_lanzadera_pareados_dia"] = p.demanda_lanzadera_dia
    p["incremento_excursiones_sobre_sin"] = incremento
    if not np.allclose(p.visitas_sin_dia, p.visitas_con_objetivo_dia, rtol=0, atol=1e-8):
        raise ValueError("La reasignación no conserva visitas.")
    if not np.allclose(x.visitas_coche + x.visitas_excursiones_resto_colectivo,
        x.visitas_coche_autorizadas_dia + x.visitas_coche_transferidas_dia
        + x.visitas_excursiones_con_intervencion_dia + x.visitas_excursiones_transferidas_dia,
        rtol=0, atol=1e-8):raise ValueError("Se pierden visitas de un origen/colectivo.")
    return {**base, "por_origen_dia": x, "escenarios_por_punto_dia": p}
