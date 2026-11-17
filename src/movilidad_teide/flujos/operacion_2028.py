"""Contrasto la viabilidad operativa de una demanda aproximada de 2028."""
from pathlib import Path
import json
import platform

import numpy as np
import pandas as pd

from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.demanda.escenarios_2028 import construir_escenarios
from movilidad_teide.demanda.planificacion_2028 import distribuir_referencia
from movilidad_teide.demanda.perfiles_operacion_2028 import reconstruir_observaciones, COLECTIVOS
from movilidad_teide.operacion.comprobacion_2028 import comprobar_flota
from movilidad_teide.operacion.viabilidad_2028 import cuotas_para_limites, ensayar_horario, cota_cualquier_reparto
from movilidad_teide.trazabilidad import sha256_archivo
from .tipos import Etapa


BASE = "data/silver/movilidad/referencia_planificacion_2028/20261107_cabildo_2_5_millones"
DESTINOS = "data/silver/movilidad/operacion_planificacion_2028"
FUENTES = {
    "perfiles": "data/silver/movilidad/visor_teide/20261016T154509Z_f7cda5fc/demanda_horaria_medianias_por_indice.csv",
    "indices": "data/silver/actividad/corredor_norte/matrices_con_formato_publicado.csv",
    "origenes": "data/silver/demanda/separacion_titsa/reasignacion/origenes_por_modo_2025.csv",
    "movimientos": "data/silver/energia_turismos/20261101_flota_30_tres_sustitutas/movimientos_con_identidad_fisica.parquet",
    "pares": "data/silver/energia_turismos/20261101_flota_30_tres_sustitutas/pares_revisados.parquet",
    "paradas": "data/silver/operacion/paradas/referencias_paradas.csv",
}
VOLUMENES = (2400000, 2500000, 2600000)
CUPOS = (475, 500, 525)


def preparar_operacion_2028(root, *, construir=True):
    """Conservo visitas sin/con, contrasto cuotas y ensayo el perfil crítico.

    El intervalo de volúmenes y cupos es una exploración declarada, no una
    estimación estadística o un cambio del libro. Ningún caso se elige por ahorro.
    """
    root = Path(root).resolve()
    meta_base = json.loads((root / BASE / "metadatos.json").read_text())
    hashes = {}
    def registrar(ruta, esperado=None):
        h = sha256_archivo(root / ruta)
        if esperado is not None and h != esperado:
            raise ValueError(f"La fuente conservada ha cambiado: {ruta}")
        hashes[ruta] = h
    registrar(BASE + "/metadatos.json")
    for p, h in meta_base["fuentes_sha256"].items(): registrar(p, h)
    for p, h in meta_base["resultados_sha256"].items(): registrar(BASE + "/" + p, h)
    for p in FUENTES.values(): registrar(p)
    parametros = leer_parametros(root)
    v = {p["id"]: p["valor_utilizado"] for p in parametros["parametros"]}
    if (v["cupo_global"] != 500 or v["vehiculos_contrato_contraste"] != 30
            or v["reserva_minima_dentro_flota"] != 3 or v["transferencia_lanzadera"] != 1
            or v["induccion"] != 0):
        raise ValueError("Revisar explícitamente las condiciones del nuevo contraste.")
    leer = lambda p: pd.read_parquet(root / p) if p.endswith(".parquet") else pd.read_csv(
        root / p, sep=";", float_precision="round_trip")
    x = {k: leer(p) for k, p in FUENTES.items()}
    media = leer(BASE + "/demanda_horaria_2028.csv")
    q = meta_base["fraccion_coche_conservada"]
    capt = dict(zip(COLECTIVOS, [v[k] for k in ["captacion_extranjero", "captacion_nacional", "captacion_local", "captacion_frecuente"]]))
    tablas = {n: [] for n in ["modos_por_perfil", "objetivos_por_perfil", "limites_acceso", "cotas_flota",
        "cuotas_alternativas", "balance_anual", "colectivos_anuales", "resumen_casos", "horarios_diagnosticos",
        "movimientos_diagnosticos", "pares_diagnosticos", "flota_diagnostica", "cargas_diagnosticas", "intentos_horarios",
        "cota_todos_los_repartos"]}
    controles = []
    def control(nombre, actual, esperado, tol=1e-8):
        if not np.isfinite([actual, esperado]).all() or abs(actual - esperado) > tol:
            raise ValueError(f"No se cumple {nombre}: {actual} frente a {esperado}")
        controles.append({"control": nombre, "actual": actual, "esperado": esperado,
                          "tolerancia": tol, "correcto": True})
    def calcular(h, cupo, cuotas=None):
        return construir_escenarios(h, x["origenes"], ocupacion=v["ocupacion_coche"], cupo=cupo,
            captaciones=capt, hora_inicio=v["hora_inicio_acceso"], hora_fin=v["hora_fin_acceso"], cuotas_por_tipo=cuotas)
    for volumen in VOLUMENES:
        hm = distribuir_referencia(media, volumen, q)
        ho = reconstruir_observaciones(x["perfiles"], x["indices"], media, total=volumen,
            fraccion_coche=q, hora_inicio=v["hora_inicio_acceso"], hora_fin=v["hora_fin_acceso"])
        control(f"{volumen}: total ponderado de nueve observaciones", (ho.visitas_persona_dia * ho.dias_equivalentes).sum(), volumen)
        for campo in ["visitas_coche", "visitas_titsa", "visitas_excursiones_resto_colectivo"]:
            control(f"{volumen}: nueve referencias conservan {campo}", (ho[campo] * ho.dias_equivalentes).sum(), (hm[campo] * hm.dias_calendario).sum())
        perfiles = []
        for obs, h in ho.groupby("matrix_index"):
            perfiles.append((int(obs), f"{h.mes_publicado.iloc[0]} · {h.tipo_dia_publicado.iloc[0]}",
                             float(h.dias_equivalentes.iloc[0]), False, h))
        for i, (tipo, h) in enumerate(hm.groupby("tipo_dia_publicado")):
            perfiles.append((-i-1, "Media · " + tipo, 0., True, h))
        for cupo in CUPOS:
            for politica in ["Proporcional OD", "Cuotas según límite de acceso"]:
                ident = {"volumen_planificacion": volumen, "cupo_global_coches_dia": cupo, "politica_cupo": politica}
                resultados = []
                for obs, nombre, peso, es_media, h in perfiles:
                    z = calcular(h, cupo)
                    pts = z["escenarios_por_punto_dia"]
                    b = comprobar_flota(pts, x["movimientos"], x["pares"], x["paradas"], v)
                    tag = {**ident, "observacion": obs, "perfil": nombre, "dias_equivalentes": peso, "es_media_tipo": es_media}
                    if politica == "Proporcional OD":
                        tablas["cota_todos_los_repartos"].append(pd.DataFrame([{**tag,
                            **cota_cualquier_reparto(pts, x["movimientos"], v, cupo=cupo)}]))
                    if politica != "Proporcional OD":
                        cuotas, c = cuotas_para_limites(pts, b["cota_accesos_e_intervalos"],
                            cupo=cupo, ocupacion=v["ocupacion_coche"], capacidad=int(v["plazas_guagua"] * v["ocupacion_diseno"]))
                        tablas["cuotas_alternativas"].append(c.assign(**tag))
                        if cuotas is None:
                            resultados.append({"tag": tag, "limite_incompatible": True, "sin_cuotas": True})
                            continue
                        z = calcular(h, cupo, {h.tipo_dia_publicado.iloc[0]: cuotas})
                        pts = z["escenarios_por_punto_dia"]
                        b = comprobar_flota(pts, x["movimientos"], x["pares"], x["paradas"], v)
                    limites = b["cota_accesos_e_intervalos"].copy()
                    tiempos = x["movimientos"].groupby(["punto", "sentido"]).tiempo_recorrido_min.first()
                    limites["intervalo_maximo_necesario_min"] = [
                        (60 * v["hora_limite_bajada_parque"] - v["estancia_min_visita_min"] - tiempos[p, "ida"]
                         - 60 * v["hora_inicio_acceso"]) / (n - 1) if n > 1 else np.nan
                        for p, n in zip(limites.punto, limites.parejas_minimas_acceso)]
                    limites["deficit_minimo_visitas_dia"] = (limites.demanda_lanzadera_dia - limites.plazas_cota_intervalo_15).clip(lower=0)
                    tablas["limites_acceso"].append(limites.assign(**tag))
                    tablas["cotas_flota"].append(b["cota_flota_dias_medios"].assign(**tag))
                    tablas["objetivos_por_perfil"].append(pts.assign(**tag))
                    modo_rows = []
                    for escenario, cantidades in [("Sin intervención", {"Coche particular y alquiler": pts.visitas_coche.sum(),
                            "TITSA": pts.visitas_titsa.sum(), "Excursiones/resto colectivo": pts.visitas_excursiones_resto_colectivo.sum()}),
                        ("Con intervención", {"Coche particular y alquiler": pts.visitas_coche_autorizadas_dia.sum(),
                            "TITSA": 0., "Excursiones/resto colectivo": pts.visitas_excursiones_permanecen_dia.sum(),
                            "Lanzadera de acceso": pts.demanda_lanzadera_dia.sum()})]:
                        for modo, cantidad in cantidades.items():
                            modo_rows.append({**tag, "escenario": escenario, "modo_entrada": modo,
                                "visitas_persona_dia": float(cantidad), "unidad": "visitas-persona/día"})
                    tablas["modos_por_perfil"].append(pd.DataFrame(modo_rows))
                    control(f"{ident}/{obs}: visitas sin/con", pts.visitas_sin_dia.sum(), pts.visitas_con_objetivo_dia.sum())
                    control(f"{ident}/{obs}: coches autorizados", pts.coches_autorizados_dia.sum(), cupo)
                    control(f"{ident}/{obs}: TITSA una vez", pts.visitas_titsa.sum(), h.visitas_titsa.sum())
                    control(f"{ident}/{obs}: regresos no añaden visitas", pts.regresos_lanzadera_pareados_dia.sum(), pts.demanda_lanzadera_dia.sum())
                    origen = z["por_origen_dia"].groupby("colectivo")
                    titsa = z["titsa_por_corredor_colectivo_dia"].groupby("colectivo").visitas_titsa.sum()
                    for colectivo, g in origen:
                        before = g.visitas_coche.sum() + g.visitas_excursiones_resto_colectivo.sum() + titsa[colectivo]
                        after = g.visitas_coche_autorizadas_dia.sum() + g.visitas_coche_transferidas_dia.sum() + g.visitas_excursiones_permanecen_dia.sum() + g.visitas_excursiones_transferidas_dia.sum() + titsa[colectivo]
                        control(f"{ident}/{obs}: colectivo {colectivo}", before, after)
                        if not es_media:
                            tablas["colectivos_anuales"].append(pd.DataFrame([{**ident, "colectivo": colectivo,
                                "visitas_sin_anio": before * peso, "visitas_con_anio": after * peso}]))
                    resultados.append({"tag": tag, "puntos": pts,
                        "limite_incompatible": bool(limites.supera_cota_intervalo_15_sin_salidas_simultaneas.any()),
                        "sin_cuotas": False, "total_lanzadera_dia": float(pts.demanda_lanzadera_dia.sum())})
                reales = [z for z in resultados if not z["tag"]["es_media_tipo"]]
                incompatibles = sum(z["limite_incompatible"] for z in reales)
                resumen = {**ident, "observaciones_od": len(reales), "observaciones_incompatibles_por_intervalo": incompatibles,
                    "oferta_anual_30_construida": False, "energia_calculada": False,
                    "estado": "Incompatible con intervalos de acceso y reparto ensayado" if incompatibles else "Límites necesarios satisfechos; falta construcción de flota"}
                if construir and not incompatibles:
                    # Primero el perfil de mayor demanda total; si no se construye
                    # dentro de treinta, no afirmo haber comprobado toda la anualidad.
                    critico = max(reales, key=lambda z: z["total_lanzadera_dia"])
                    tag = critico["tag"]
                    op = ensayar_horario(critico["puntos"], x["movimientos"], x["pares"], x["paradas"], v)
                    tablas["horarios_diagnosticos"].append(pd.DataFrame([{**tag, **op["diagnostico"]}]))
                    tablas["intentos_horarios"].append(op["intentos"].assign(**tag))
                    if op["diagnostico"]["horario_construido"]:
                        for nombre, clave in [("movimientos_diagnosticos", "movimientos"), ("pares_diagnosticos", "pares"),
                                             ("flota_diagnostica", "vehiculos"), ("cargas_diagnosticas", "cargas_tramos")]:
                            tablas[nombre].append(op[clave].assign(**tag))
                        resumen["programadas_en_perfil_critico"] = op["diagnostico"]["vehiculos_programados"]
                        resumen["total_con_sustitucion_en_construccion"] = op["diagnostico"]["total_necesario_en_esta_construccion"]
                        resumen["estado"] = "Construcción diagnóstica fuera de treinta; no prueba mínimo global" if not op["diagnostico"]["cabe_en_30_con_reserva"] else "Perfil crítico cabe; anualidad y otros usuarios interiores pendientes"
                    else:
                        resumen["estado"] = "Búsqueda acotada sin horario; no prueba imposibilidad global"
                tablas["resumen_casos"].append(pd.DataFrame([resumen]))
    tablas = {k: pd.concat(v, ignore_index=True) if v else pd.DataFrame() for k, v in tablas.items()}
    mod = tablas["modos_por_perfil"].loc[~tablas["modos_por_perfil"].es_media_tipo].copy()
    mod["visitas_persona_anio"] = mod.visitas_persona_dia * mod.dias_equivalentes
    ids = ["volumen_planificacion", "cupo_global_coches_dia", "politica_cupo"]
    tablas["balance_anual"] = mod.groupby([*ids, "escenario", "modo_entrada"], as_index=False).visitas_persona_anio.sum()
    tablas["balance_anual"]["unidad"] = "visitas-persona/año"
    tablas["colectivos_anuales"] = tablas["colectivos_anuales"].groupby([*ids, "colectivo"], as_index=False)[["visitas_sin_anio", "visitas_con_anio"]].sum()
    tablas["colectivos_anuales"]["unidad"] = "visitas-persona/año"
    for key, g in tablas["balance_anual"].groupby([*ids, "escenario"]):
        control(f"Anual {key}", g.visitas_persona_anio.sum(), key[0])
    tablas["controles"] = pd.DataFrame(controles)
    meta = {"decision": "D238", "hipotesis": "H128", "fecha": "2026-11-07", "parametros": parametros,
        "volumenes_explorados": list(VOLUMENES), "cupos_explorados": list(CUPOS),
        "caracter_intervalos": "Exploración local: ±100.000 visitas y ±25 coches respecto a la referencia; no intervalo de confianza ni decisión institucional",
        "igualdad_escenarios": "Misma demanda en ambos escenarios para cada caso; TITSA solo sin intervención y absorbido una vez por lanzaderas con intervención",
        "unidad": "Visitas-persona para demanda; entradas de coches para cupo; vehículos físicos para flota",
        "crecimiento_adicional": False, "fuentes_sha256": hashes,
        "energia_calculada": False, "informe_actualizado": False, "libro_modificado": False,
        "construcciones_ensayadas": construir, "oferta_anual_30_verificada": False,
        "tolerancia_personas": 1e-8,
        "limites": ["No se adopta exactamente 2,5 millones ni otro volumen por favorecer ahorro.",
            "TITSA mensual no observado: referencia por tipo de día y corredor/colectivo/ventana conservada de D237, distribuida con las horas OD de cada referencia.",
            "Los tres meses se ponderan por igual dentro del tipo de día; permanecen las ausencias fuente, sin rellenarlas como ceros observados.",
            "Las cuotas territoriales alternativas son una propuesta explícita de regulación; no alteran OD ni el cupo global y no acreditan oferta suficiente.",
            "La cota de acceso permite una sola guagua por salida con intervalo mínimo de quince minutos e ignora interior y flota: es necesaria, no suficiente.",
            "Construcción acotada con funciones existentes, dos intervalos interiores 10/7,5 min y modulación por reservas; no optimización global ni horarios adoptados.",
            "Solo se construye el perfil crítico de cada caso que supera las cotas: no se afirma comprobación anual o p85 nuevo.",
            "Coches conservan acceso a aparcamiento próximo bajo el libro y segunda zona cero; no añado demanda interior inexistente en esa cadena.",
            "Uso interior adicional de excursionistas y solapamiento de embarques TITSA no identificados; no se suman automáticamente ni se certifican como nulos.",
            "El servicio de alimentación/continuidad exterior TITSA sigue pendiente; sus viajeros no desaparecen ni se convierten en nuevas visitas al Parque.",
            "Los horarios que exceden treinta son diagnósticos; no sustituyen la flota contratada ni prueban que toda otra operación sea imposible.",
            "La cota sobre todos los repartos mantiene vehículos separados por servicio y recorridos interiores completos; incluye regulación y omite vacíos. No se extiende a una explotación que intercale servicios o haga recorridos parciales."],
        "entorno": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__}}
    return Etapa(tablas), meta


def generar_operacion_2028(root, destino, *, construir=True):
    root, destino = Path(root).resolve(), Path(destino).resolve()
    permitido = (root / DESTINOS).resolve()
    data_real = (root / BASE).resolve().parents[3]
    if destino == permitido or any(destino.is_relative_to(p) for p in [root, data_real]) and not destino.is_relative_to(permitido):
        raise ValueError("Usar una ejecución independiente o una carpeta nueva en operacion_planificacion_2028.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):
        raise FileExistsError("La ejecución existente se conserva; elegir otro destino.")
    etapa, meta = preparar_operacion_2028(root, construir=construir)
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, tabla in etapa.tablas.items():
        if not tabla.empty:
            tabla.to_csv(destino / (nombre + ".csv"), sep=";", index=False, encoding="utf-8-sig", float_format="%.17g")
    paquete = Path(__file__).parents[1]
    nombres = ["flujos/operacion_2028.py", "demanda/perfiles_operacion_2028.py", "demanda/escenarios_2028.py",
        "demanda/planificacion_2028.py", "operacion/viabilidad_2028.py", "operacion/figuras_2028.py", "operacion/comprobacion_2028.py",
        "operacion/horarios.py", "operacion/ampliacion.py", "operacion/circulacion.py", "energia/sensibilidad_modal.py"]
    meta["codigo_sha256"] = {"movilidad_teide/" + n: sha256_archivo(paquete / n) for n in nombres}
    script = paquete.parents[1] / "scripts/contrastar_operacion_2028.py"
    meta["codigo_sha256"]["scripts/contrastar_operacion_2028.py"] = sha256_archivo(script)
    meta["resultados_sha256"] = {p.name: sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    from movilidad_teide.operacion.figuras_2028 import dibujar_cotas
    dibujar_cotas(etapa.tablas, destino)
    meta["figuras_sha256"] = {p.name: sha256_archivo(p) for p in sorted(destino.glob("demanda_y_cotas_flota.*"))}
    (destino / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return etapa, meta
