"""Reaplico coeficientes Hot conservados; dejo ausentes los totales no cerrados."""
import math
import numpy as np
import pandas as pd


def valorar_componentes(origenes, correcciones, comunes, puntos, interior, factores, valores):
    """No escalo el ahorro anterior ni atribuyo consumo cero a TITSA.

    La alimentación adicional de excursiones mantiene la hipótesis de un coche
    por persona; no se extiende a los viajeros de TITSA sin una cadena definida.
    Las lanzaderas se valoran mediante una cota de actividad, no un horario nuevo.
    """
    keys = ["origen_id", "colectivo", "sentido", "rama"]
    coef = correcciones.loc[correcciones.caso_pendiente.eq("Referencia del Excel")].copy()
    if coef.duplicated(["alternativa_procedencia", *keys]).any():
        raise ValueError("Coeficientes energéticos repetidos.")
    coef["mwh_por_vehiculo_sentido"] = coef.energia_base_mwh_por_vehiculo_sentido + coef.correccion_mwh_por_vehiculo_sentido
    if not np.isfinite(coef.mwh_por_vehiculo_sentido).all() or coef.mwh_por_vehiculo_sentido.lt(0).any():
        raise ValueError("Coeficientes energéticos ausentes o negativos.")
    cantidades = []
    campos = {"antes": "coches_sin_dia", "autorizados": "coches_autorizados_dia",
              "transferidos": "coches_transferidos_dia",
              "alimentacion_otros": "visitas_excursiones_transferidas_dia"}
    for rama, campo in campos.items():
        for sentido in ["hacia_teide", "desde_teide"]:
            z = origenes[["origen_id", "colectivo", "tipo_dia_publicado", "dias_calendario", campo]].copy()
            z = z.rename(columns={campo: "recorridos_vehiculo_dia"})
            z["rama"], z["sentido"] = rama, sentido
            cantidades.append(z)
    q = pd.concat(cantidades, ignore_index=True)
    x = q.merge(coef[["alternativa_procedencia", *keys, "mwh_por_vehiculo_sentido"]], on=keys,
                how="left", validate="many_to_many")
    if len(x) != 2 * len(q) or x.mwh_por_vehiculo_sentido.isna().any():
        raise ValueError("Falta cobertura energética de los orígenes activos.")
    x["energia_mwh_anio"] = x.recorridos_vehiculo_dia * x.dias_calendario * x.mwh_por_vehiculo_sentido
    # Distancias y factor equivalentes de la referencia anterior. Solo se aplican
    # al residuo excursiones/resto colectivo; jamás a TITSA desde orígenes ficticios.
    ck = ["origen_id", "colectivo", "sentido"]
    cc = comunes[[*ck, "longitud_referencia_sentido_km", "factor_hot_referencia_mj_km"]].drop_duplicates()
    if cc.duplicated(ck).any():
        raise ValueError("La referencia de excursiones no es única.")
    exc = pd.concat([origenes.assign(sentido=s) for s in ["hacia_teide", "desde_teide"]], ignore_index=True)
    exc = exc.merge(cc, on=ck, how="left", validate="many_to_one")
    if not np.isfinite(exc[["longitud_referencia_sentido_km", "factor_hot_referencia_mj_km"]]).all().all():
        raise ValueError("Falta distancia o factor de excursiones.")
    exc["guaguas_equivalentes_sentido_anio"] = (exc.visitas_excursiones_resto_colectivo
        * exc.dias_calendario / valores["ocupacion_guagua_aforo"])
    exc["energia_equivalente_mwh_anio"] = (exc.guaguas_equivalentes_sentido_anio
        * exc.longitud_referencia_sentido_km * exc.factor_hot_referencia_mj_km / 3600)
    # H120 se conserva exclusivamente para la oferta residual que permanece:
    # retirar viajeros no demuestra retirar expediciones ni igual cambio de energía.
    exc["energia_con_mwh_anio"] = exc.energia_equivalente_mwh_anio
    exc["alcance"] = "Excursiones/resto colectivo equivalente; oferta energética conservada, no inventario observado"
    cap = int(valores["plazas_guagua"] * valores["ocupacion_diseno"])
    f = factores.loc[factores.referencia_id.eq("referencia_guagua_2")
                     & factores.carga_fisica.eq(valores["carga_copert"])].copy()
    if f.duplicated(["punto", "sentido"]).any():
        raise ValueError("La referencia diésel no es única.")
    f = f.set_index(["punto", "sentido"])
    actividad = []
    for row in puntos.itertuples():
        n = math.ceil(max(0., row.demanda_lanzadera_dia - 1e-8) / cap)
        for sentido in ["ida", "vuelta"]:
            ff = f.loc[row.punto, sentido]
            actividad.append({"tipo_dia_publicado": row.tipo_dia_publicado, "punto": row.punto,
                "sentido": sentido, "dias_calendario": row.dias_calendario,
                "recorridos_comerciales_minimos_dia": n, "hot_mwh_anio": n * ff.energia_mj_recorrido / 3600 * row.dias_calendario,
                "vehiculos_km_anio": n * ff.longitud_km * row.dias_calendario})
    # El diseño vigente recorre el eje interior completo. Para ese diseño el
    # tramo de mayor carga exige al menos este número de recorridos por sentido.
    for tipo, b in interior.groupby("tipo_dia_publicado", sort=True):
        n = int(b.recorridos_minimos_por_sentido.max())
        days = int(puntos.loc[puntos.tipo_dia_publicado.eq(tipo), "dias_calendario"].iloc[0])
        for sentido in ["ida", "vuelta"]:
            ff = f.loc["INTERIOR", sentido]
            actividad.append({"tipo_dia_publicado": tipo, "punto": "INTERIOR", "sentido": sentido,
                "dias_calendario": days, "recorridos_comerciales_minimos_dia": n,
                "hot_mwh_anio": n * ff.energia_mj_recorrido / 3600 * days,
                "vehiculos_km_anio": n * ff.longitud_km * days})
    actividad = pd.DataFrame(actividad)
    rows = []
    suelo = float(actividad.hot_mwh_anio.sum())
    for alt, b in x.groupby("alternativa_procedencia", sort=True):
        antes = float(b.loc[b.rama.eq("antes"), "energia_mwh_anio"].sum())
        con = float(b.loc[b.rama.isin(["autorizados", "transferidos"]), "energia_mwh_anio"].sum())
        feed = float(b.loc[b.rama.eq("alimentacion_otros"), "energia_mwh_anio"].sum())
        comun = float(exc.energia_equivalente_mwh_anio.sum())
        for tratamiento in ["Hot COPERT", "Contraste FTA"]:
            minimum = suelo if tratamiento == "Hot COPERT" else suelo / (1 - valores["perdida_rendimiento_guaguas_contraste"])
            rows.append({"alternativa_procedencia": alt, "tratamiento_lanzaderas": tratamiento,
                "coches_sin_mwh_anio": antes, "coches_con_objetivo_mwh_anio": con,
                "alimentacion_excursiones_mwh_anio": feed, "excursiones_equivalentes_sin_mwh_anio": comun,
                "excursiones_equivalentes_con_mwh_anio": comun,
                "subtotal_sin_coches_excursiones_mwh_anio": antes + comun,
                "subtotal_con_sin_lanzaderas_ni_alimentacion_titsa_mwh_anio": con + feed + comun,
                "suelo_lanzaderas_comerciales_eje_completo_mwh_anio": minimum,
                "diferencia_parcial_menos_suelo_mwh_anio": antes - con - feed - minimum,
                "titsa_sin_mwh_anio": np.nan, "titsa_lineas_sustituidas_con_mwh_anio": 0.,
                "alimentacion_y_continuidad_titsa_con_mwh_anio": np.nan,
                "lanzaderas_oferta_viable_30_mwh_anio": np.nan,
                "sin_total_mwh_anio": np.nan, "con_total_mwh_anio": np.nan,
                "ahorro_total_mwh_anio": np.nan, "ahorro_total_tep_anio": np.nan,
                "oferta_viable_30_demostrada": False,
                "alcance": "Componentes y suelo de actividad con factores fijos; no ahorro realizable ni cota del consumo real"})
    return {"costes_coches_y_alimentacion_excursiones": x, "excursiones_equivalentes": exc,
            "suelo_actividad_lanzaderas": actividad, "balance_componentes_2028": pd.DataFrame(rows)}
