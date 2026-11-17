"""Contrasto cambios de fecha sin aumentar visitas ni cambiar sus orígenes."""
import numpy as np
import pandas as pd


FLUJOS = ("visitas_coche_transferidas_dia", "visitas_excursiones_transferidas_dia")
CLAVES = ["origen_id", "colectivo", "punto"]


def redistribuir_fechas(escenarios, perfiles, fracciones, *, ocupacion):
    """Traslado parte del fin de semana a laborables de su mismo mes de referencia.

    Solo cambian de fecha los viajeros previstos en lanzadera procedentes de
    coche o excursión. TITSA, coches autorizados y excursiones finales conservan
    sus fechas. Las cantidades diarias se convierten a aportes anuales mediante
    los días equivalentes: no traslado una media diaria como si fuera un total.
    Los perfiles son referencias representativas, no fechas de reserva reales.
    """
    p = perfiles.set_index("observacion")
    if not p.index.is_unique:raise ValueError("Perfiles duplicados.")
    if set(escenarios) != set(p.index) or set(fracciones) != set(p.mes):
        raise ValueError("Perfiles y meses de redistribución incompatibles.")
    if not np.isfinite(ocupacion) or ocupacion < 1:
        raise ValueError("Ocupación inválida.")
    if any(isinstance(q, bool) or not np.isfinite(q) or not 0 <= q <= 1 for q in fracciones.values()):
        raise ValueError("La fracción temporal debe estar entre cero y uno.")
    if not np.isfinite(p.dias_equivalentes).all() or p.dias_equivalentes.le(0).any():
        raise ValueError("Días equivalentes inválidos.")
    xs, result, trazas = {}, {}, []
    for obs,z in escenarios.items():
        x = z["por_origen_dia"].set_index(CLAVES).copy()
        if not x.index.is_unique:raise ValueError("Orígenes duplicados.")
        if "cambio_fecha_entrada_dia" in x:
            raise ValueError("La redistribución temporal ya está aplicada.")
        if not np.isfinite(x[list(FLUJOS)]).all().all() or x[list(FLUJOS)].lt(0).any().any():
            raise ValueError("Viajeros elegibles inválidos.")
        for c in FLUJOS:x[c + "_antes_fecha"] = x[c]
        x["cambio_fecha_entrada_dia"] = 0.;x["cambio_fecha_salida_dia"] = 0.
        xs[obs] = x
    for mes,g in p.groupby("mes"):
        if sorted(g.tipo.tolist()) != ["Domingo", "Laborable", "Sábado"]:
            raise ValueError("Cada mes requiere un laborable, sábado y domingo.")
        destino = g.index[g.tipo.eq("Laborable")].item();q = fracciones[mes]
        for origen,row in g.loc[g.tipo.ne("Laborable")].iterrows():
            a,b = xs[origen],xs[destino]
            if set(a.index) != set(b.index):
                raise ValueError("No se inventan orígenes receptores ausentes.")
            for c in FLUJOS:
                mov = a[c + "_antes_fecha"] * q
                anual = mov * row.dias_equivalentes
                recibido = anual / p.loc[destino,"dias_equivalentes"]
                a[c] -= mov;b[c] += recibido.reindex(b.index)
                a["cambio_fecha_salida_dia"] += mov
                b["cambio_fecha_entrada_dia"] += recibido.reindex(b.index)
                tr = anual.rename("visitas_persona_anio").reset_index()
                trazas.append(tr.assign(mes=mes, observacion_origen=origen, observacion_destino=destino,
                    flujo=c,fraccion_del_flujo_punta=q))
    antes, despues = [], []
    for obs,z in escenarios.items():
        x = xs[obs].reset_index();pt = z["escenarios_por_punto_dia"].copy()
        agregado = x.groupby("punto")[list(FLUJOS)+["cambio_fecha_entrada_dia","cambio_fecha_salida_dia"]].sum()
        for c in agregado:pt[c] = pt.punto.map(agregado[c])
        pt["demanda_lanzadera_dia"] = pt[list(FLUJOS)].sum(axis=1)+pt.visitas_titsa
        pt["demanda_bruta_lanzadera_dia"] = pt.demanda_lanzadera_dia + pt.coches_autorizados_dia * ocupacion
        pt["regresos_lanzadera_pareados_dia"] = pt.demanda_lanzadera_dia
        pt["visitas_con_objetivo_dia"] = pt.visitas_coche_autorizadas_dia+pt.visitas_excursiones_con_intervencion_dia+pt.demanda_lanzadera_dia
        esperado = pt.visitas_sin_dia + pt.cambio_fecha_entrada_dia - pt.cambio_fecha_salida_dia
        if not np.allclose(esperado,pt.visitas_con_objetivo_dia,rtol=0,atol=1e-8):
            raise ValueError("Se pierde la relación entre fechas de origen y destino.")
        w=p.loc[obs,"dias_equivalentes"]
        antes.append(x.set_index(CLAVES)[[c+"_antes_fecha" for c in FLUJOS]].rename(columns=lambda c:c.removesuffix("_antes_fecha"))*w)
        despues.append(x.set_index(CLAVES)[list(FLUJOS)]*w)
        result[obs]={**z,"por_origen_dia":x,"escenarios_por_punto_dia":pt}
    a=pd.concat(antes).groupby(level=CLAVES).sum().sort_index()
    b=pd.concat(despues).groupby(level=CLAVES).sum().sort_index()
    if not np.allclose(a,b,rtol=0,atol=1e-8):
        raise ValueError("La redistribución cambia las visitas anuales de un origen o colectivo.")
    return result,pd.concat(trazas,ignore_index=True)
