"""Separo visitas de acceso y tramos interiores antes de reasignar los servicios."""
from numbers import Real

import numpy as np
import pandas as pd

from movilidad_teide.demanda.referencia_oficial import TOLERANCIA_PERSONAS


CORREDORES_TITSA = {342: "TF21_BocaTauce_Granadilla", 348: "TF21_Orotava_Portillo"}
MESES_REFERENCIA = (3, 7, 10)
TIPOS = {"Laborable (matriz)": "Laborable", "Sabado": "Sábado", "Festivo": "Domingo"}
AMBITOS = ("entrada", "salida", "interior", "exterior")


def clasificar_frontera(viajes, paradas):
    """Clasifico cada registro una vez con paradas mensuales y límite físico.

    Las cantidades son pasajeros-tramo agregados. Una entrada exterior puede
    representar una visita bajo la hipótesis del estudio; un embarque interior
    nunca se añade como nueva visita. No deduzco exterior de una parada ausente.
    """
    requeridas = {"registro_fuente_id", "mes", "linea_id", "parada_entrada_id", "parada_salida_id",
                  "pasajeros_cantidad", "linea_anterior_id", "linea_siguiente_id"}
    if (viajes.empty or not requeridas <= set(viajes) or viajes.registro_fuente_id.isna().any()
            or viajes.registro_fuente_id.duplicated().any() or not viajes.linea_id.isin([341, 342, 348]).all()):
        raise ValueError("Faltan claves únicas de fuente o líneas del ámbito TITSA.")
    cantidades = pd.to_numeric(viajes.pasajeros_cantidad, errors="raise")
    if not np.isfinite(cantidades).all() or cantidades.lt(0).any():
        raise ValueError("Las cantidades publicadas deben ser finitas y no negativas.")
    if (not {"mes", "parada_id", "dentro_parque"} <= set(paradas)
            or paradas.duplicated(["mes", "parada_id"]).any()
            or paradas.dentro_parque.isna().any()
            or not paradas.dentro_parque.isin([True, False]).all()):
        raise ValueError("El catálogo mensual no identifica de forma única las paradas.")
    x = viajes.copy(deep=True)
    for lado, campo in [("origen", "parada_entrada_id"), ("destino", "parada_salida_id")]:
        lookup = paradas[["mes", "parada_id", "dentro_parque"]].rename(
            columns={"parada_id": campo, "dentro_parque": "dentro_" + lado})
        x = x.merge(lookup, on=["mes", campo], how="left", validate="many_to_one")
    if x[["dentro_origen", "dentro_destino"]].isna().any().any():
        raise ValueError("Hay paradas sin localizar; no se tratan como exteriores.")
    a, b = x.dentro_origen, x.dentro_destino
    x["ambito_fisico"] = np.select([~a & b, a & ~b, a & b], AMBITOS[:3], default="exterior")
    if not x.loc[x.linea_id.eq(341), "ambito_fisico"].eq("interior").all():
        raise ValueError("La 341 contiene un cruce exterior inesperado; revisar antes de asignarlo.")
    entradas = x.ambito_fisico.eq("entrada")
    if x.loc[entradas & x.mes.isin(MESES_REFERENCIA), "linea_anterior_id"].isin([341, 342, 348]).any():
        raise ValueError("Una entrada tiene enlace previo con otra línea del sistema: requiere revisar la cadena.")
    x["usado_en_anualizacion"] = x.mes.isin(MESES_REFERENCIA)
    x["cuenta_visita_acceso"] = entradas
    x["destino_reasignacion"] = x.ambito_fisico.map({
        "entrada": "lanzadera de acceso", "salida": "regreso: contraste separado, no nueva visita",
        "interior": "servicio interior del sistema", "exterior": "fuera del ámbito de visitas; continuidad pendiente"})
    return x


def anualizar_titsa(clasificados):
    """Promedio tres meses por tipo de día y conservo separados los cuatro ámbitos.

    fechas_calculadas es el total de días de la matriz, repetido en las etiquetas
    de no laborables. Los divisores sábado/domingo se deducen del calendario,
    solo si los totales publicados coinciden con él en marzo/julio/octubre.
    """
    x = clasificados.loc[clasificados.mes.isin(MESES_REFERENCIA)].copy()
    if (x.empty or not x.anio.eq(2025).all() or not set(x.tipo_dia) <= set(TIPOS)
            or set(x.mes) != set(MESES_REFERENCIA)):
        raise ValueError("Faltan referencias de 2025 o hay tipos de día no reconocidos.")
    calendarios = []
    for mes in MESES_REFERENCIA:
        fechas = pd.date_range(f"2025-{mes:02d}-01", periods=pd.Timestamp(2025, mes, 1).days_in_month)
        dias = {"Laborable": int((fechas.dayofweek < 5).sum()), "Sábado": int((fechas.dayofweek == 5).sum()),
                "Domingo": int((fechas.dayofweek == 6).sum())}
        for tipo, etiquetas in [("laborables", ["Laborable (matriz)"]), ("no_laborables", ["Sabado", "Festivo"])]:
            bloque = x.loc[x.mes.eq(mes) & x.tipo_matriz.eq(tipo)]
            nd = bloque.fechas_calculadas.unique()
            esperado = dias["Laborable"] if tipo == "laborables" else dias["Sábado"] + dias["Domingo"]
            if (len(nd) != 1 or nd[0] != esperado or set(bloque.linea_id) != {341, 342, 348}
                    or set(bloque.tipo_dia) != set(etiquetas)):
                raise ValueError("Cobertura o días publicados incompatibles con la regla temporal elegida.")
            for etiqueta in etiquetas:
                calendarios.append({"mes": mes, "tipo_dia_fuente": etiqueta, "tipo_dia": TIPOS[etiqueta],
                    "dias_matriz_publicados": int(nd[0]), "dias_etiqueta_inferidos": dias[TIPOS[etiqueta]],
                    "regla": "Calendario compatible; Festivo representa domingo en los tres meses de referencia"})
    cal = pd.DataFrame(calendarios)
    x["tipo_dia_modelo"] = x.tipo_dia.map(TIPOS)
    key = ["mes", "linea_id", "tipo_dia_modelo", "ambito_fisico"]
    cantidades = x.groupby(key).pasajeros_cantidad.sum()
    indice = pd.MultiIndex.from_product([MESES_REFERENCIA, [341, 342, 348], list(TIPOS.values()), AMBITOS], names=key)
    diario = cantidades.reindex(indice, fill_value=0).rename("pasajeros_publicados").reset_index()
    if not np.isclose(diario.pasajeros_publicados.sum(), x.pasajeros_cantidad.sum(), rtol=0, atol=TOLERANCIA_PERSONAS):
        raise ValueError("La clasificación temporal pierde registros publicados.")
    diario = diario.rename(columns={"tipo_dia_modelo": "tipo_dia"}).merge(cal, on=["mes", "tipo_dia"], validate="many_to_one")
    diario["pasajeros_media_dia"] = diario.pasajeros_publicados / diario.dias_etiqueta_inferidos
    if not np.allclose(diario.pasajeros_media_dia * diario.dias_etiqueta_inferidos,
                       diario.pasajeros_publicados, rtol=0, atol=TOLERANCIA_PERSONAS):
        raise ValueError("La conversión diaria no reconstruye las cantidades mensuales.")
    anual = diario.groupby(["linea_id", "tipo_dia", "ambito_fisico"], as_index=False).agg(
        pasajeros_media_dia=("pasajeros_media_dia", "mean"), meses_referencia=("mes", "nunique"))
    if not anual.meses_referencia.eq(3).all():
        raise ValueError("No se promedian referencias mensuales incompletas.")
    anual["dias_calendario_2025"] = anual.tipo_dia.map({"Laborable": 261, "Sábado": 52, "Domingo": 52})
    anual["pasajeros_tramo_anuales_equivalentes"] = anual.pasajeros_media_dia * anual.dias_calendario_2025
    anual["unidad"] = "pasajeros-tramo/año equivalentes; las entradas representan visitas por hipótesis"
    return cal, diario, anual


def separar_modos(base, anual_titsa, fraccion_coche):
    """Extraigo TITSA del colectivo existente; el resto se representa como excursiones.

    TITSA conserva su estimación absoluta, sin multiplicarla por el factor OAPN.
    Dentro de cada corredor/tipo de día se reparte con proporciones OD, porque
    TITSA no identifica los cuatro colectivos ni la hora equivalente del Visor.
    No aplico cupo, captación de coches/excursiones, oferta o crecimiento.
    """
    keys = ["access_corridor", "colectivo", "tipo_dia_publicado", "hora_servicio"]
    if (base.empty or not {*keys, "anio", "sentido", "visitas_normalizadas_2025"} <= set(base)
            or base.duplicated(keys).any() or not base.anio.eq(2025).all() or not base.sentido.eq("entrada").all()
            or base[keys].isna().any().any()
            or "visitas_titsa" in base):
        raise ValueError("La base debe contener entradas únicas de 2025 aún sin separar.")
    if (isinstance(fraccion_coche, (bool, np.bool_)) or not isinstance(fraccion_coche, Real)
            or not np.isfinite(fraccion_coche) or not 0 < fraccion_coche < 1):
        raise ValueError("La cuota de coche debe estar entre cero y uno.")
    x = base[keys + ["visitas_normalizadas_2025"]].copy(deep=True)
    if not np.isfinite(x.visitas_normalizadas_2025).all() or x.visitas_normalizadas_2025.lt(0).any():
        raise ValueError("Las visitas de la base deben ser finitas y no negativas.")
    x["visitas_coche"] = x.visitas_normalizadas_2025 * fraccion_coche
    x["visitas_colectivo"] = x.visitas_normalizadas_2025 - x.visitas_coche
    x["visitas_titsa"] = 0.
    targets = anual_titsa.loc[anual_titsa.ambito_fisico.eq("entrada") & anual_titsa.linea_id.isin(CORREDORES_TITSA)].copy()
    if (len(targets) != 6 or targets.duplicated(["linea_id", "tipo_dia"]).any()
            or set(zip(targets.linea_id, targets.tipo_dia)) != {(l, t) for l in CORREDORES_TITSA for t in TIPOS.values()}):
        raise ValueError("Falta un objetivo TITSA de acceso por línea y tipo de día.")
    for r in targets.itertuples():
        target = r.pasajeros_tramo_anuales_equivalentes
        if not np.isfinite(target) or target < 0:
            raise ValueError("El objetivo TITSA es negativo o no finito.")
        mask = x.access_corridor.eq(CORREDORES_TITSA[r.linea_id]) & x.tipo_dia_publicado.eq(r.tipo_dia)
        disponible = x.loc[mask, "visitas_colectivo"].sum()
        if disponible <= 0 or target > disponible + TOLERANCIA_PERSONAS:
            raise ValueError("TITSA supera el colectivo disponible; no recorto ni redistribuyo para ocultarlo.")
        x.loc[mask, "visitas_titsa"] = x.loc[mask, "visitas_colectivo"] * (target / disponible)
        if not np.isclose(x.loc[mask, "visitas_titsa"].sum(), target, rtol=0, atol=TOLERANCIA_PERSONAS):
            raise ValueError("El reparto por colectivos y horas no conserva el objetivo TITSA.")
    x["visitas_excursiones_resto_colectivo"] = x.visitas_colectivo - x.visitas_titsa
    # La sustitución es una asignación de demanda, no una simulación de oferta.
    x["visitas_lanzadera_acceso_por_sustitucion_titsa"] = x.visitas_titsa
    x["visitas_titsa_acceso_tras_sustitucion"] = 0.
    before = x.visitas_coche + x.visitas_titsa + x.visitas_excursiones_resto_colectivo
    after = x.visitas_coche + x.visitas_lanzadera_acceso_por_sustitucion_titsa + x.visitas_excursiones_resto_colectivo
    if (x.visitas_excursiones_resto_colectivo.lt(0).any()
            or not np.allclose(before, x.visitas_normalizadas_2025, rtol=0, atol=TOLERANCIA_PERSONAS)
            or not np.allclose(after, x.visitas_normalizadas_2025, rtol=0, atol=TOLERANCIA_PERSONAS)):
        raise ValueError("La separación o la sustitución pierde o duplica visitas.")
    return x
