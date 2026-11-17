"""Integro las matrices TITSA en la base de 2025 sin alterar su ejecución anterior."""
from pathlib import Path
import json
import platform

import geopandas as gpd
import numpy as np
import pandas as pd

from movilidad_teide.demanda.separacion_titsa import (
    CORREDORES_TITSA, MESES_REFERENCIA, clasificar_frontera, anualizar_titsa, separar_modos,
)
from movilidad_teide.demanda.referencia_oficial import TOLERANCIA_PERSONAS
from movilidad_teide.trazabilidad import sha256_archivo
from .tipos import Etapa


BASE = "data/silver/movilidad/referencia_oficial_2025/20261106_oapn_od"
CAPTURA = "data/bronze/transporte_publico/pasajeros_titsa/2025/20261022T171917Z_f6db4cae"
PASAJEROS = "data/silver/demanda/asignacion/pasajeros_titsa_2025.parquet"
LIMITE = "data/bronze/documentacion/contexto_informe/cartografia_parque/PN_Teide/Limites/Limite_Teide.shp"
AFOROS = "data/silver/aforos_teide/reparto_personas_aforos_conjunto.csv"


def preparar_separacion_2025(root):
    """Verifico fuentes, clasifico cruces, estimo referencias y separo las mismas visitas."""
    root = Path(root).resolve()
    hashes = {}
    def registrar(ruta, esperado=None):
        ruta = Path(ruta).as_posix()
        actual = sha256_archivo(root / ruta)
        if esperado is not None and actual != esperado:
            raise ValueError(f"La fuente no coincide con su huella: {ruta}")
        hashes[ruta] = actual
    registrar(BASE + "/metadatos.json")
    previa = json.loads((root / BASE / "metadatos.json").read_text())
    for ruta, esperado in previa["fuentes_sha256"].items(): registrar(ruta, esperado)
    for nombre, esperado in previa["resultados_sha256"].items(): registrar(BASE + "/" + nombre, esperado)
    antecedente = "data/silver/demanda/asignacion/metadatos.json"
    registrar(antecedente)
    preparacion_previa = json.loads((root / antecedente).read_text())
    registrar(PASAJEROS, preparacion_previa["sha256_pasajeros_titsa"])
    registrar(CAPTURA + "/metadatos.json", preparacion_previa["fuentes"]["demanda_titsa"]["sha256"])
    capture = json.loads((root / CAPTURA / "metadatos.json").read_text())
    registrar(CAPTURA + "/catalogo.json", capture["sha256_catalogo"])
    if len(capture["meses"]) != 12 or {m["mes"] for m in capture["meses"]} != set(range(1, 13)):
        raise ValueError("La captura debe conservar los doce meses y sus ausencias.")
    for m in capture["meses"]:
        for f in m["archivos"]: registrar(CAPTURA + "/" + f["archivo"], f["sha256"])
    for p in (root / LIMITE).parent.glob("Limite_Teide.*"): registrar(p.relative_to(root))
    registrar("data/silver/descargas_tenerife/rutas_341_342_348.gpkg", preparacion_previa["fuentes"]["rutas_titsa"]["sha256"])
    registrar("config/parametros_modelo.xlsx")
    viajes = pd.read_parquet(root / PASAJEROS)
    if not viajes.anio.eq(2025).all(): raise ValueError("La tabla TITSA mezcla años.")
    limite = gpd.read_file(root / LIMITE).to_crs(4326)
    if limite.empty or not limite.is_valid.all(): raise ValueError("El límite del Parque no es válido.")
    geometria = limite.geometry.union_all()
    stops = []
    lineas = []
    for m in capture["meses"]:
        ficha = next(f for f in m["archivos"] if f["tipo"] == "paradas_csv")
        s = pd.read_csv(root / CAPTURA / ficha["archivo"])
        if s.parada_id.isna().any() or s.parada_id.duplicated().any():
            raise ValueError("Paradas mensuales repetidas o sin identificador.")
        usados = viajes.loc[viajes.mes.eq(m["mes"])]
        ids = set(usados.parada_entrada_id) | set(usados.parada_salida_id)
        s = s.loc[s.parada_id.isin(ids)].copy()
        if set(s.parada_id) != ids or not np.isfinite(s[["parada_latitud", "parada_longitud"]]).all().all():
            raise ValueError("Falta una coordenada de las paradas usadas; no se deduce exterior.")
        puntos = gpd.GeoSeries(gpd.points_from_xy(s.parada_longitud, s.parada_latitud), crs=4326)
        s["dentro_parque"] = puntos.map(geometria.covers).to_numpy()
        s["mes"] = m["mes"]
        s["archivo_fuente"] = ficha["archivo"]
        stops.append(s[["mes", "parada_id", "parada_nombre", "parada_latitud", "parada_longitud", "dentro_parque", "archivo_fuente"]])
        f = next(f for f in m["archivos"] if f["tipo"] == "lineas_json")
        l = pd.DataFrame(json.loads((root / CAPTURA / f["archivo"]).read_text())["lineas"])
        l = l.loc[l.linea_id.isin([341, 342, 348])]
        if set(l.linea_id) != {341, 342, 348} or not l.linea_empresa.eq("TITSA").all():
            raise ValueError("Los catálogos mensuales no identifican las líneas seleccionadas.")
        lineas.append(l.assign(mes=m["mes"])[["mes", "linea_id", "linea_nombre"]])
    paradas = pd.concat(stops, ignore_index=True)
    clasificados = clasificar_frontera(viajes, paradas)
    cal, diario, anual = anualizar_titsa(clasificados)
    columnas_resumen = ["mes", "linea_id", "tipo_matriz", "tipo_dia", "ambito_fisico", "usado_en_anualizacion"]
    publicado = clasificados.groupby(columnas_resumen, as_index=False).agg(
        pasajeros_publicados=("pasajeros_cantidad", "sum"), registros_fuente=("registro_fuente_id", "size"))
    base = pd.read_csv(root / BASE / "demanda_horaria_2025.csv", sep=";", float_precision="round_trip")
    aforos = pd.read_csv(root / AFOROS, sep=";", float_precision="round_trip")
    a = aforos.loc[aforos.anio.eq(2025) & aforos.sentido.eq("entrada") & aforos.ocupacion_coche_aplicada.notna()]
    if len(a) != 1: raise ValueError("El reparto de aforos 2025 no es único.")
    a = a.iloc[0]
    q = float(a.fraccion_personas_paso_en_coche)
    q_reconstruida = a.pasos_coche * a.ocupacion_coche_aplicada / (a.pasos_coche * a.ocupacion_coche_aplicada + a.pasos_guagua * a.ocupacion_guagua_aplicada)
    if not np.isclose(q, q_reconstruida, rtol=0, atol=1e-12): raise ValueError("La cuota modal no reproduce sus conteos y ocupaciones.")
    modal = separar_modos(base, anual, q)
    modos = ["visitas_coche", "visitas_titsa", "visitas_excursiones_resto_colectivo"]
    nuevo = ["visitas_coche", "visitas_lanzadera_acceso_por_sustitucion_titsa", "visitas_excursiones_resto_colectivo"]
    resumen_modal = pd.DataFrame([{"situacion": situacion, "modo": col, "visitas_anuales": float(modal[col].sum())}
        for situacion, cols in [("Referencia 2025", modos), ("Reasignación de servicios; no escenario operativo", nuevo)] for col in cols])
    group = ["access_corridor", "colectivo"]
    totales = modal.groupby(group, as_index=False)[["visitas_normalizadas_2025", *modos]].sum()
    origen = pd.read_csv(root / BASE / "origenes_2025.csv", sep=";", float_precision="round_trip")
    nombres = {c: "fraccion_" + c for c in modos}
    for col in modos: totales[nombres[col]] = totales[col] / totales.visitas_normalizadas_2025
    por_origen = origen.merge(totales[[*group, *nombres.values()]].rename(columns={"access_corridor": "corredor_fuente"}),
        on=["corredor_fuente", "colectivo"], how="left", validate="many_to_one")
    for col in modos: por_origen[col] = por_origen.visitas_normalizadas_2025 * por_origen[nombres[col]]
    por_origen["visitas_lanzadera_acceso_por_sustitucion_titsa"] = por_origen.visitas_titsa
    por_origen["modo_titsa_observado_en_origen"] = False
    por_origen["apto_para_calcular_km_titsa"] = False
    regreso = por_origen[["origen_id", "colectivo", "corredor_fuente", *modos,
        "visitas_lanzadera_acceso_por_sustitucion_titsa"]].copy()
    regreso["sentido"] = "desde_teide"
    regreso["cuenta_nuevas_visitas"] = False
    regreso["unidad"] = "regresos pareados por hipótesis, no salidas TITSA observadas"
    reasignacion = anual.loc[anual.ambito_fisico.isin(["entrada", "salida"]) & anual.linea_id.isin(CORREDORES_TITSA)].copy()
    reasignacion["access_corridor"] = reasignacion.linea_id.map(CORREDORES_TITSA)
    reasignacion["destino"] = "lanzadera de acceso"
    reasignacion["visitas_adicionales"] = 0.
    reasignacion["cuenta_visita_acceso"] = reasignacion.ambito_fisico.eq("entrada")
    interior = anual.loc[anual.ambito_fisico.eq("interior")].copy()
    interior["destino"] = "servicio interior del sistema; cobertura operativa por verificar"
    interior["cuenta_nuevas_visitas"] = False
    interior["sumable_al_interior_generado_desde_accesos"] = False
    interior["unidad"] = "embarques/tramos interiores anuales equivalentes; no usuarios únicos o demanda adicional"
    controles = []
    def check(nombre, condicion, diferencia=0.):
        if not bool(condicion): raise ValueError("Falla el control: " + nombre)
        controles.append({"control": nombre, "cumple": True, "diferencia": diferencia})
    check("La clasificación conserva registros y cantidades publicadas", len(clasificados) == len(viajes) and clasificados.registro_fuente_id.nunique() == len(viajes) and clasificados.pasajeros_cantidad.sum() == viajes.pasajeros_cantidad.sum())
    check("341 exclusivamente interior y sin visitas de acceso", not clasificados.loc[clasificados.linea_id.eq(341), "cuenta_visita_acceso"].any())
    check("Nueve referencias temporales completas", len(cal) == 9)
    check("Los cuatro colectivos de la base permanecen", set(modal.colectivo) == set(base.colectivo))
    check("La estimación TITSA conserva sus cantidades sin expansión OAPN", np.isclose(modal.visitas_titsa.sum(), reasignacion.loc[reasignacion.cuenta_visita_acceso, "pasajeros_tramo_anuales_equivalentes"].sum(), rtol=0, atol=TOLERANCIA_PERSONAS))
    check("Los regresos publicados estimados se conservan aparte sin visitas nuevas", np.isclose(
        reasignacion.loc[reasignacion.ambito_fisico.eq("salida"), "pasajeros_tramo_anuales_equivalentes"].sum(),
        anual.loc[anual.linea_id.isin(CORREDORES_TITSA) & anual.ambito_fisico.eq("salida"), "pasajeros_tramo_anuales_equivalentes"].sum(), rtol=0, atol=TOLERANCIA_PERSONAS)
        and not reasignacion.loc[reasignacion.ambito_fisico.eq("salida"), "cuenta_visita_acceso"].any())
    check("No se añaden pasajeros TITSA al total de visitas", np.isclose(modal.visitas_normalizadas_2025.sum(), previa["total_oficial"], rtol=0, atol=TOLERANCIA_PERSONAS))
    for situacion, cols in [("antes", modos), ("tras reasignar TITSA", nuevo)]:
        error = float(modal[cols].sum().sum() - previa["total_oficial"])
        check("Conservación total " + situacion, abs(error) <= TOLERANCIA_PERSONAS, error)
        check("Conservación por celda " + situacion, np.allclose(modal[cols].sum(axis=1), base.visitas_normalizadas_2025, rtol=0, atol=TOLERANCIA_PERSONAS))
    check("Sustitución completa y una sola vez de TITSA de acceso", np.array_equal(modal.visitas_titsa, modal.visitas_lanzadera_acceso_por_sustitucion_titsa) and modal.visitas_titsa_acceso_tras_sustitucion.eq(0).all())
    check("Todos los orígenes y ausencias de la fase 1 se conservan", len(por_origen) == len(origen) and por_origen.loc[~por_origen.en_ambito_anual, modos].isna().all().all())
    for col in modos:
        check("Reparto territorial conserva " + col, np.isclose(por_origen[col].sum(), modal[col].sum(), rtol=0, atol=TOLERANCIA_PERSONAS))
        check("Regresos pareados de " + col, np.allclose(por_origen[col], regreso[col], rtol=0, atol=0, equal_nan=True))
    check("Interior no sumado como visitas o demanda adicional", not interior.cuenta_nuevas_visitas.any() and not interior.sumable_al_interior_generado_desde_accesos.any())
    for ruta, sha in hashes.items(): check("Fuente conservada: " + ruta, sha256_archivo(root / ruta) == sha)
    regreso = regreso.rename(columns={c: c.replace("visitas_", "regresos_", 1)
        for c in [*modos, "visitas_lanzadera_acceso_por_sustitucion_titsa"]})
    tablas = {"clasificacion_titsa_2025": clasificados, "paradas_clasificadas_2025": paradas,
        "lineas_catalogo_2025": pd.concat(lineas, ignore_index=True), "publicados_por_linea_ambito": publicado,
        "dias_referencia_2025": cal, "referencias_diarias_titsa_2025": diario, "estimacion_anual_titsa_2025": anual,
        "reparto_modal_horario_2025": modal, "desglose_modal_2025": resumen_modal, "origenes_por_modo_2025": por_origen,
        "regresos_pareados_por_modo_2025": regreso, "reasignacion_titsa_acceso_2025": reasignacion,
        "reasignacion_tramos_interiores_2025": interior, "controles": pd.DataFrame(controles)}
    meta = {"decision": "D234", "hipotesis": "H125", "fecha": "2026-11-06", "anio": 2025,
        "total_visitas": previa["total_oficial"], "fraccion_coche_heredada": q,
        "titsa_acceso_visitas_equivalentes": float(modal.visitas_titsa.sum()),
        "excursiones_resto_colectivo_visitas": float(modal.visitas_excursiones_resto_colectivo.sum()),
        "fuentes_sha256": hashes, "corredores_titsa": CORREDORES_TITSA,
        "meses_referencia": MESES_REFERENCIA, "predicado_geografico": "covers sobre límite físico del Parque en EPSG:4326; sin buffer",
        "regla_anualizacion": "Media de marzo/julio/octubre por tipo; sábado y Festivo/domingo divididos por días de calendario compatibles con el total mensual publicado; 261/52/52 días en 2025",
        "regla_colectivos_horas": "Proporciones OD del colectivo no-coche del corredor/tipo; no nacionalidad TITSA observada ni horarios efectivos",
        "regla_origenes": "Pesos territoriales heredados solo para conciliación de visitas; las paradas TITSA no son el origen completo de los viajes OD. Este reparto no acredita cobertura de cada origen ni sirve para calcular kilómetros de TITSA.",
        "regla_excursiones": "Resto del colectivo después de TITSA, dentro de la aproximación de modos del estudio; puede incluir otros servicios no identificados; no conteo observado de excursiones",
        "regla_interior": "Sustituyo cada tramo interior como actividad; no sumo sus embarques a visitas ni al interior de las cadenas de acceso. Solapamiento de personas sin identificar.",
        "regla_exterior": "Conservo tramos exterior-exterior fuera del total de visitas; su continuidad necesita definición operativa posterior",
        "regla_regresos": "Conservo y reasigno también las salidas TITSA de su propia estimación, sin sumarlas como visitas ni igualarlas a las entradas. El regreso pareado por modo del modelo es una hipótesis distinta, no una medición de dichas salidas.",
        "ausencias": "Agosto no laborable ausente y noviembre 341 anómalo conservados; no se imputan ni se usan en la anualización elegida; TITSA no ha respondido",
        "tolerancia_absoluta_visitas": TOLERANCIA_PERSONAS,
        "justificacion_tolerancia": "Acumulación y exportación de coma flotante; no incertidumbre física ni redondeo o ajuste de filas",
        "viajeros_unicos_identificados": False, "desglose_medido_excursiones": False,
        "cobertura_y_capacidad_lanzaderas_verificadas": False, "operacion_2028_recalculada": False,
        "energia_recalculada": False, "informe_modificado": False, "excel_modificado": False,
        "entorno": {"python": platform.python_version(), "pandas": pd.__version__, "geopandas": gpd.__version__}}
    return Etapa(tablas), meta


def generar_separacion_2025(root, destino):
    """Escribo una ejecución nueva, sin sobrescribir fuentes o la normalización previa."""
    root, destino = Path(root).resolve(), Path(destino).resolve()
    permitido = (root / "data/silver/movilidad/separacion_titsa_2025").resolve()
    if destino == root or any(destino.is_relative_to((root / p).resolve()) for p in ("data", "config", "src", "tests", "docs", "notebooks")) and not destino.is_relative_to(permitido):
        raise ValueError("El destino debe ser independiente o una nueva ejecución bajo separacion_titsa_2025.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):
        raise FileExistsError("El destino debe estar vacío; conservo las ejecuciones anteriores.")
    resultado, meta = preparar_separacion_2025(root)
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, tabla in resultado.tablas.items():
        tabla.to_csv(destino / (nombre + ".csv"), sep=";", index=False, encoding="utf-8-sig", float_format="%.17g")
    paquete = Path(__file__).parents[1]
    meta["codigo_sha256"] = {"movilidad_teide/" + str(p.relative_to(paquete)): sha256_archivo(p)
        for p in [Path(__file__), paquete / "demanda/separacion_titsa.py"]}
    script = Path(__file__).parents[3] / "scripts/separar_titsa_2025.py"
    meta["codigo_sha256"]["scripts/separar_titsa_2025.py"] = sha256_archivo(script)
    meta["resultados_sha256"] = {p.name: sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    (destino / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return resultado, meta
