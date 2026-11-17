"""Preparo solo demanda de planificación; no ejecuto oferta ni energía."""
from pathlib import Path
import json
import platform

import numpy as np
import pandas as pd

from movilidad_teide.demanda.escenarios_2028 import MODOS, calendario
from movilidad_teide.demanda.planificacion_2028 import distribuir_referencia, distribuir_territorio
from movilidad_teide.demanda.referencia_oficial import TOLERANCIA_PERSONAS
from movilidad_teide.trazabilidad import sha256_archivo
from .tipos import Etapa


BASE = "data/silver/movilidad/escenarios_2028/20261106_demanda_oficial_titsa"
SEPARACION = "data/silver/demanda/separacion_titsa/reasignacion"
FUENTE = "data/bronze/documentacion/referencia_demanda_cabildo/20261107_comunicacion.json"
SALIDAS = "data/silver/movilidad/referencia_planificacion_2028"
REFERENCIA_2025 = "data/silver/movilidad/referencia_oficial_2025/20261106_oapn_od"


def preparar_referencia_2028(root):
    """Verifico las capturas y distribuyo 2,5 millones con la forma OD conservada."""
    root = Path(root).resolve()
    hashes = {}
    def registrar(ruta, esperado=None):
        ruta = Path(ruta)
        if ruta.is_absolute() or ".." in ruta.parts:
            raise ValueError("Una entrada debe ser una ruta interna relativa.")
        actual = sha256_archivo(root / ruta)
        if esperado is not None and actual != esperado:
            raise ValueError(f"Entrada distinta de la conservada: {ruta}")
        hashes[ruta.as_posix()] = actual
    # Las huellas enlazan esta etapa con las fuentes nativas y ejecuciones previas.
    for carpeta in [BASE, SEPARACION, REFERENCIA_2025]:
        registrar(carpeta + "/metadatos.json")
        m = json.loads((root / carpeta / "metadatos.json").read_text())
        for ruta, huella in m["fuentes_sha256"].items(): registrar(ruta, huella)
        for nombre, huella in m["resultados_sha256"].items(): registrar(carpeta + "/" + nombre, huella)
    meta_previa = json.loads((root / BASE / "metadatos.json").read_text())
    meta_modal = json.loads((root / SEPARACION / "metadatos.json").read_text())
    meta_2025 = json.loads((root / REFERENCIA_2025 / "metadatos.json").read_text())
    v = {p["id"]: p["valor_utilizado"] for p in meta_previa["parametros"]["parametros"]}
    if v["cupo_global"] != 500:
        raise ValueError("El cupo de referencia requiere una revisión explícita.")
    registrar(FUENTE)
    fuente = json.loads((root / FUENTE).read_text())
    decision = fuente["decision_estudio"]
    if (fuente["anio_observacion"] is not None or decision["anio_planificacion"] != 2028
            or decision["crecimiento_adicional"] is not False
            or decision["volumen_adoptado_visitas_persona"] != fuente["visitas_persona_anuales_orientativas"]):
        raise ValueError("La fuente requiere una decisión de planificación revisada.")
    total = decision["volumen_adoptado_visitas_persona"]
    leer = lambda p: pd.read_csv(root / p, sep=";", float_precision="round_trip")
    anterior = leer(BASE + "/demanda_horaria_2028.csv")
    origenes = leer(SEPARACION + "/origenes_por_modo_2025.csv")
    q = meta_modal["fraccion_coche_heredada"]
    h = distribuir_referencia(anterior, total, q)
    o = distribuir_territorio(h, origenes)
    campos = ["visitas_persona_anio", *[c + "_anio" for c in MODOS]]
    anuales = h.copy()
    for c in MODOS: anuales[c + "_anio"] = anuales[c] * anuales.dias_calendario
    tablas = {"demanda_horaria_2028": h, "origenes_2028": o}
    for nombre, claves in [("colectivos_2028", ["colectivo"]),
                          ("accesos_fuente_2028", ["access_corridor"]),
                          ("colectivos_accesos_2028", ["access_corridor", "colectivo"]),
                          ("perfiles_temporales_2028", ["tipo_dia_publicado", "dias_calendario"])]:
        t = anuales.groupby(claves, as_index=False)[campos].sum()
        t["proporcion_total"] = t.visitas_persona_anio / total
        t["anio"] = 2028
        t["unidad"] = "visitas-persona/año"
        tablas[nombre] = t
    # Acceso de cálculo y corredor fuente no son siempre la misma asignación.
    tablas["accesos_calculo_2028"] = o.loc[o.en_ambito_anual].groupby(
        ["corredor_calculo", "cabecera_calculo"], as_index=False).visitas_persona_anio.sum()
    tablas["accesos_calculo_2028"]["unidad"] = "visitas-persona/año; reparto territorial condicionado"
    tablas["accesos_calculo_2028"]["apto_para_calcular_km_titsa"] = False
    n = leer(BASE + "/titsa_proyeccion_linea_ambito.csv")
    tablas["titsa_linea_ambito_conservado"] = n
    # Un regreso por visita es una hipótesis de cadena, no otra entrada al Parque.
    r = h[["access_corridor", "colectivo", "tipo_dia_publicado", "hora_servicio",
           "visitas_persona_anio"]].copy()
    r = r.rename(columns={"hora_servicio": "hora_entrada_referencia",
                          "visitas_persona_anio": "regresos_persona_pareados_anio"})
    r["cuenta_visita_adicional"] = False
    r["estado"] = "Regreso contable sin horario asignado; no salida TITSA observada"
    tablas["regresos_pareados_2028"] = r
    # El contraste conserva periodos y naturalezas; no suma fuentes como demandas.
    tablas["contraste_fuentes"] = pd.DataFrame([
        {"referencia": "OD anualizado D233", "periodo": "2025", "cantidad": meta_2025["total_od_anterior"],
         "unidad": "entradas de personas/año modelizadas", "estado": "Población y expansión pendientes de caracterizar"},
        {"referencia": "OAPN F161, página 7", "periodo": "2025", "cantidad": meta_2025["total_oficial"],
         "unidad": "visitas-persona/año publicadas", "estado": "Estadística oficial conservada; no sustituida"},
        {"referencia": "Cabildo, comunicación referida F162", "periodo": "Últimos años; sin año concreto",
         "cantidad": fuente["visitas_persona_anuales_orientativas"], "unidad": "visitas-persona/año aproximadas",
         "estado": "Orientación interna referida; sin respaldo escrito disponible"},
        {"referencia": "Referencia adoptada D237/H127", "periodo": "2028", "cantidad": total,
         "unidad": "visitas-persona/año de planificación", "estado": "Hipótesis; no medición ni capacidad demostrada"}])
    aforos = leer(REFERENCIA_2025 + "/contraste_fuentes_2025.csv")
    aforos = aforos.loc[aforos.fuente.eq("Aforos 2025 y ocupaciones históricas")]
    if len(aforos) != 1:
        raise ValueError("No hay un contraste único de aforos documentado.")
    tablas["contraste_fuentes"] = pd.concat([tablas["contraste_fuentes"], pd.DataFrame([{
        "referencia": aforos.fuente.iloc[0], "periodo": "2025", "cantidad": aforos.cantidad.iloc[0],
        "unidad": "personas-paso de entrada/año estimadas",
        "estado": aforos.interpretacion.iloc[0]}])], ignore_index=True)
    controles = []
    def control(nombre, actual, esperado, tol=TOLERANCIA_PERSONAS):
        if not np.isfinite([actual, esperado]).all() or abs(actual - esperado) > tol:
            raise ValueError(f"No se cumple {nombre}: {actual} frente a {esperado}")
        controles.append({"control": nombre, "actual": actual, "esperado": esperado,
                          "tolerancia_absoluta": tol, "correcto": True})
    control("volumen adoptado 2028 sin crecimiento adicional", h.visitas_persona_anio.sum(), total)
    control("modos conservan personas", anuales[[c + "_anio" for c in MODOS]].sum().sum(), total)
    control("164 filas de origen conservadas", len(o), len(origenes), 0)
    control("ocho filas sin cantidad anual", o.visitas_persona_anio.isna().sum(), 8, 0)
    control("cuatro colectivos", h.colectivo.nunique(), 4, 0)
    control("regresos separados de visitas", r.regresos_persona_pareados_anio.sum(), total)
    control("341 sin entradas", n.loc[n.linea_id.eq(341) & n.cuenta_visita_acceso,
                                      "pasajeros_tramo_anio_2028"].sum(), 0, 0)
    tit = float(anuales.visitas_titsa_anio.sum())
    control("TITSA no normalizado", tit, (anterior.visitas_titsa * anterior.dias_calendario).sum())
    control("TITSA nativo de acceso por línea", tit, n.loc[n.cuenta_visita_acceso, "pasajeros_tramo_anio_2028"].sum())
    previo = anterior.visitas_persona_dia * anterior.dias_calendario
    control("máxima diferencia de proporciones OD horarias",
        np.abs(h.proporcion_anual_od_2028.to_numpy() - (previo / previo.sum()).to_numpy()).max(), 0, 1e-12)
    control("máximo descuadre modal por fila diaria",
        np.abs(h[MODOS].sum(axis=1) - h.visitas_persona_dia).max(), 0)
    grupos = h.groupby(["access_corridor", "colectivo"]).visitas_persona_anio.sum()
    territorial = o.loc[o.en_ambito_anual].groupby(["corredor_fuente", "colectivo"]).visitas_persona_anio.sum()
    for k in grupos.index: control(f"reparto territorial {k}", territorial.loc[k], grupos.loc[k])
    tablas["controles"] = pd.DataFrame(controles)
    meta = {"decision": "D237", "hipotesis": "H127", "fuente": fuente, "fecha": "2026-11-07",
        "anio_planificacion": 2028, "total_visitas_persona": total, "calendario": calendario(2028),
        "fraccion_coche_conservada": q, "crecimiento_adicional_aplicado": False,
        "forma_od": BASE + "/demanda_horaria_2028.csv",
        "tasa_comun_en_forma_previa": meta_previa["tasa_anual_conservada"],
        "explicacion_tasa": "Se cancela al dividir por el total previo; no eleva el volumen adoptado. TITSA conserva su proyección nativa D236.",
        "metodo": "Visitas del grupo en 2028 = 2.500.000 × proporción OD anualizada con calendario 2028; origen = grupo × peso OD condicionado.",
        "titsa_visitas_persona_anio": tit, "fuentes_sha256": hashes,
        "capacidad_calculada": False, "energia_calculada": False, "informe_actualizado": False,
        "parametros_modificados": False, "cupo_coches_global_dia_conservado": v["cupo_global"],
        "tolerancia": "1e-8 visitas-persona por acumulación binaria; 1e-12 en proporciones. No son incertidumbre de fuentes ni corrección de filas.",
        "limites": [*fuente["limites"],
            "Pesos territoriales, cuota modal y perfiles representativos son hipótesis heredadas, no nuevas mediciones.",
            "Excursiones/resto colectivo es el residuo tras TITSA; no inventario medido de excursiones.",
            "Ocho filas de dos orígenes carecen de correspondencia anual; no se inventan visitas adicionales ni ceros.",
            "No hay identificación de personas únicas ni corrección demostrada de reentradas.",
            "Interiores TITSA y salidas se conservan aparte; no se añaden al total ni al interior derivado de las reservas.",
            "El reparto territorial de TITSA no permite calcular sus kilómetros ni escoger su cabecera real."],
        "entorno": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__}}
    return Etapa(tablas), meta


def generar_referencia_2028(root, destino):
    """Escribo solo una ejecución nueva, independiente de las fuentes y el informe."""
    root, destino = Path(root).resolve(), Path(destino).resolve()
    permitido = (root / SALIDAS).resolve()
    # Incluyo los datos físicos cuando trabajo desde una copia con enlaces.
    protegidos = [root, (root / BASE).resolve().parents[3], *[(root / p).resolve() for p in
                  ["data", "config", "src", "scripts", "tests", "docs", "notebooks", "outputs"]]]
    if destino == permitido or any(destino.is_relative_to(p) for p in protegidos) and not destino.is_relative_to(permitido):
        raise ValueError("Destino ajeno a la nueva rama de referencia_planificacion_2028.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):
        raise FileExistsError("La ejecución anterior se conserva: usar un destino nuevo.")
    etapa, meta = preparar_referencia_2028(root)
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, tabla in etapa.tablas.items():
        tabla.to_csv(destino / (nombre + ".csv"), sep=";", index=False,
                     encoding="utf-8-sig", float_format="%.17g")
    paquete = Path(__file__).parents[1]
    productores = [Path(__file__), paquete / "demanda/planificacion_2028.py",
                   paquete / "demanda/escenarios_2028.py", paquete / "demanda/referencia_oficial.py"]
    meta["codigo_sha256"] = {"movilidad_teide/" + p.relative_to(paquete).as_posix():
                             sha256_archivo(p) for p in productores}
    script = Path(__file__).parents[3] / "scripts/preparar_referencia_2028.py"
    meta["codigo_sha256"]["scripts/preparar_referencia_2028.py"] = sha256_archivo(script)
    meta["resultados_sha256"] = {p.name: sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    (destino / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return etapa, meta
