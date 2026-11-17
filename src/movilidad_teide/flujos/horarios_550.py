"""Contraste de 550 coches y reservas de dos o tres unidades, sin energía."""
from collections import Counter
from pathlib import Path
import json
import platform

import numpy as np
import pandas as pd

from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.demanda.escenarios_2028 import construir_escenarios
from movilidad_teide.demanda.perfiles_operacion_2028 import reconstruir_observaciones, COLECTIVOS
from movilidad_teide.demanda.excursiones_2028 import reasignar_excursiones
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.operacion.refinar_reservas import buscar_refinado, refinar_perfil
from movilidad_teide.operacion.circulacion_compartida import encadenar_viajes, cerrar_bases, materializar
from movilidad_teide.operacion.horarios_compartidos import concurrencia
from movilidad_teide.trazabilidad import sha256_archivo
from .compartida_2028 import BASE, PARADAS
from .operacion_2028 import FUENTES, BASE as REFERENCIA
from .tipos import Etapa


ANTERIOR = "data/silver/movilidad/operacion_compartida_2028/20261107_compartida_y_parciales"
SALIDAS = "data/silver/movilidad/horarios_550_2028"
VOLUMENES = (2400000, 2500000, 2600000)


def preparar_horarios_550(root, *, volumenes=VOLUMENES, reinicios=6, pasos=1200, pasos_otros=120,
                         incremento_excursiones=None, propuesta_operacion=None):
    root = Path(root).resolve();fuentes = {}
    old = json.loads((root / ANTERIOR / "metadatos.json").read_text())
    def registrar(p, esperado=None):
        h = sha256_archivo(root / p)
        if esperado is not None and h != esperado:raise ValueError(f"Fuente modificada: {p}")
        fuentes[p] = h
    registrar(ANTERIOR + "/metadatos.json")
    for p, h in old["fuentes_sha256"].items():registrar(p, h)
    for p, h in old["resultados_sha256"].items():registrar(ANTERIOR + "/" + p, h)
    for p in FUENTES.values():registrar(p)
    rd = lambda p: pd.read_parquet(root / p) if p.endswith(".parquet") else pd.read_csv(root / p, sep=";", float_precision="round_trip")
    params = leer_parametros(root);v = {p["id"]: p["valor_utilizado"] for p in params["parametros"]}
    if (v["cupo_global"] != 500 or v["reserva_minima_dentro_flota"] != 3
        or v["vehiculos_contrato_contraste"] != 30 or v["intervalo_refuerzo_punta_min"] != 15
        or int(v["plazas_guagua"] * v["ocupacion_diseno"]) != 46 or v["regulacion_min"] != 10):
        raise ValueError("Revisar las condiciones conservadas antes de ejecutar otro contraste.")
    red = RedOperativa(rd(BASE + "/movimientos_diagnosticos.csv"), rd(BASE + "/pares_diagnosticos.csv"), rd(PARADAS))
    objetivos = rd(BASE + "/objetivos_por_perfil.csv");media = rd(REFERENCIA + "/demanda_horaria_2028.csv")
    frac = json.loads((root / REFERENCIA / "metadatos.json").read_text())["fraccion_coche_conservada"]
    perf, indices, origen = rd(FUENTES["perfiles"]), rd(FUENTES["indices"]), rd(FUENTES["origenes"])
    capt = dict(zip(COLECTIVOS, [v[k] for k in ["captacion_extranjero", "captacion_nacional", "captacion_local", "captacion_frecuente"]]))
    names = ["resumen", "perfiles", "cuotas_comunes", "cronologias", "reservas", "movimientos",
             "modos_por_perfil", "origenes_por_perfil", "titsa_por_perfil", "reinicios", "inventario_por_base", "controles"]
    tablas = {n: [] for n in names};controles = []
    tablas["origenes_sin_cantidad_anual"] = origen.loc[~origen.en_ambito_anual].copy()
    colectivos = []
    def incremento_para(obs):
        return incremento_excursiones[int(obs)] if isinstance(incremento_excursiones, dict) else incremento_excursiones
    def control(nombre, actual, esperado):
        if not np.isfinite([actual, esperado]).all() or abs(actual - esperado) > 1e-8:
            raise ValueError(f"Diferencia sin explicar en {nombre}: {actual} frente a {esperado}")
        controles.append({"control": nombre, "actual": actual, "esperado": esperado, "tolerancia": 1e-8, "correcto": True})
    for volumen in volumenes:
        ho = reconstruir_observaciones(perf, indices, media, total=volumen, fraccion_coche=frac,
            hora_inicio=v["hora_inicio_acceso"], hora_fin=v["hora_fin_acceso"])
        hist = objetivos.loc[objetivos.volumen_planificacion.eq(volumen) & objetivos.cupo_global_coches_dia.eq(500)
            & objetivos.politica_cupo.eq("Proporcional OD") & ~objetivos.es_media_tipo]
        if hist.empty:raise ValueError("Volumen ajeno a la banda OD conservada.")
        if incremento_excursiones is not None:
            bloques = []
            for obs, h in ho.groupby("matrix_index"):
                base = construir_escenarios(h, origen, ocupacion=v["ocupacion_coche"], cupo=550, captaciones=capt,
                    hora_inicio=v["hora_inicio_acceso"], hora_fin=v["hora_fin_acceso"])
                nuevo = reasignar_excursiones(base, incremento=incremento_para(obs), ocupacion=v["ocupacion_coche"])
                bloques.append(nuevo["escenarios_por_punto_dia"].assign(observacion=int(obs)))
            hist = pd.concat(bloques, ignore_index=True)
        if propuesta_operacion is None:
            result = buscar_refinado(hist, red, v, cupo=550, reinicios=reinicios, pasos=pasos, semilla=24000)
        else:
            principal = int(hist.groupby("observacion").demanda_lanzadera_dia.sum().idxmax())
            result = {**propuesta_operacion["perfiles"][principal], "observacion": principal,
                      "cuotas": propuesta_operacion["cuotas"]}
        cuotas = result["cuotas"];control(f"{volumen}: cupo común", sum(cuotas.values()), 550)
        tablas["cuotas_comunes"].append(pd.DataFrame([{"volumen_planificacion": volumen, "punto": q, "coches_dia": c} for q, c in cuotas.items()]))
        control(f"{volumen}: anualidad OD", (ho.visitas_persona_dia * ho.dias_equivalentes).sum(), volumen)
        stocks, totales, cierres, modos_anuales = [], [], [], []
        for obs, h in ho.groupby("matrix_index"):
            tag = {"volumen_planificacion": volumen, "observacion": int(obs),
                   "perfil": f"{h.mes_publicado.iloc[0]} · {h.tipo_dia_publicado.iloc[0]}",
                   "dias_equivalentes": float(h.dias_equivalentes.iloc[0])}
            if incremento_excursiones is not None:tag["incremento_excursiones_sobre_sin"] = incremento_para(obs)
            z = construir_escenarios(h, origen, ocupacion=v["ocupacion_coche"], cupo=550, captaciones=capt,
                hora_inicio=v["hora_inicio_acceso"], hora_fin=v["hora_fin_acceso"], cuotas_por_tipo={h.tipo_dia_publicado.iloc[0]: cuotas})
            if incremento_excursiones is not None:
                z = reasignar_excursiones(z, incremento=incremento_para(obs), ocupacion=v["ocupacion_coche"])
            pts = z["escenarios_por_punto_dia"]
            control(f"{tag}: visitas sin/con", pts.visitas_sin_dia.sum(), pts.visitas_con_objetivo_dia.sum())
            control(f"{tag}: coches", pts.coches_autorizados_dia.sum(), 550)
            control(f"{tag}: TITSA", pts.visitas_titsa.sum(), h.visitas_titsa.sum())
            for colectivo, g in z["por_origen_dia"].groupby("colectivo"):
                before = g.visitas_coche.sum() + g.visitas_excursiones_resto_colectivo.sum()
                after = g.visitas_coche_autorizadas_dia.sum() + g.visitas_coche_transferidas_dia.sum() + g.visitas_excursiones_permanecen_dia.sum() + g.visitas_excursiones_transferidas_dia.sum()
                if "visitas_coche_a_excursiones_dia" in g:after += g.visitas_coche_a_excursiones_dia.sum()
                control(f"{tag}: colectivo {colectivo}", before, after)
                titsa = z["titsa_por_corredor_colectivo_dia"].loc[lambda t: t.colectivo.eq(colectivo), "visitas_titsa"].sum()
                control(f"{tag}: TITSA de {colectivo}", titsa, h.loc[h.colectivo.eq(colectivo), "visitas_titsa"].sum())
                colectivos.append({"volumen_planificacion": volumen, "colectivo": colectivo,
                    "visitas_sin_anio": (before + titsa) * tag["dias_equivalentes"],
                    "visitas_con_anio": (after + titsa) * tag["dias_equivalentes"]})
            current = (propuesta_operacion["perfiles"][int(obs)] if propuesta_operacion is not None else
                       result if obs == result["observacion"] else refinar_perfil(pts, red, v, cuotas,
                       pasos=pasos_otros, semilla=25000 + int(obs) * 2))
            viajes, reservas = current["viajes"], current["reservas"]
            control(f"{tag}: reservas", reservas.personas.sum(), pts.demanda_lanzadera_dia.sum())
            control(f"{tag}: reservas y plazas", viajes.personas.sum(), 2 * reservas.personas.sum())
            closed = None
            for criterio in ["distancia", "tiempo", "servicio"]:
                t, cadenas = encadenar_viajes(viajes, red, regulacion=v["regulacion_min"], criterio=criterio)
                control(f"{tag}: enlaces equivalentes", len(cadenas), current["cadenas"])
                if propuesta_operacion is None:
                    closed = cerrar_bases(t, cadenas, red, regulacion=v["regulacion_min"])
                else:
                    from movilidad_teide.operacion.inventario_comun import bases_posibles, asignar_bases
                    ss, ee = bases_posibles(t, cadenas, red, regulacion=v["regulacion_min"])
                    closed, _ = asignar_bases(ss, ee, red.bases, propuesta_operacion["capacidades"])
                if closed is not None:break
            n = len(cadenas);totales.append(n);cierres.append(closed is not None)
            if closed is not None:
                a, b = closed;stocks.append(Counter(a))
                fisicos = materializar(t, cadenas, a, red, regulacion=v["regulacion_min"], bases_finales=b)
                if propuesta_operacion is not None:
                    disponibles = {base: ids.copy() for base, ids in propuesta_operacion["identidades_por_base"].items()}
                    equivalencias = {f"TF{k+1:02d}": disponibles[base].pop(0) for k,base in enumerate(a)}
                    for original, real in equivalencias.items():
                        mask = fisicos.unidad_fisica_id.eq(original) & fisicos.familia.eq("Vacío")
                        fisicos.loc[mask, "id_salida"] = fisicos.loc[mask, "id_salida"].str.replace(original+"_", real+"_", n=1, regex=False)
                    fisicos["unidad_fisica_id"] = fisicos.unidad_fisica_id.map(equivalencias)
                    fisicos = fisicos.sort_values(["unidad_fisica_id", "salida_min"]).reset_index(drop=True)
                tablas["movimientos"].append(fisicos.assign(**tag))
            tablas["cronologias"].append(viajes.assign(**tag));tablas["reservas"].append(reservas.assign(**tag))
            tablas["reinicios"].append(current["reinicios"].assign(**tag))
            estancia = reservas.regreso_parque_min - reservas.entrada_parque_min
            tablas["perfiles"].append(pd.DataFrame([{**tag, "es_perfil_busqueda_cuotas": obs == result["observacion"],
                "visitas_lanzadera_dia": reservas.personas.sum(), "cadenas_catalogo_inicial": current["cadenas_mejor_catalogo_inicial"],
                "vehiculos_programados_reloj": n, "concurrencia_reloj": concurrencia(viajes, v["regulacion_min"]),
                "cierre_bases": closed is not None, "relojes_iniciales": current["relojes_iniciales"],
                "estancia_parque_min_min": estancia.min(), "estancia_parque_max_min": estancia.max()}]))
            tablas["origenes_por_perfil"].append(z["por_origen_dia"].assign(**tag))
            tablas["titsa_por_perfil"].append(z["titsa_por_corredor_colectivo_dia"].assign(**tag))
            for scenario, quantities in [("Sin intervención", {"Coche particular y alquiler": pts.visitas_coche.sum(), "TITSA": pts.visitas_titsa.sum(), "Excursiones/resto colectivo": pts.visitas_excursiones_resto_colectivo.sum()}),
                ("Con intervención", {"Coche particular y alquiler": pts.visitas_coche_autorizadas_dia.sum(), "TITSA": 0., "Excursiones/resto colectivo": pts.get("visitas_excursiones_con_intervencion_dia", pts.visitas_excursiones_permanecen_dia).sum(), "Lanzadera de acceso": pts.demanda_lanzadera_dia.sum()})]:
                for mode, qty in quantities.items():
                    row = {**tag, "escenario": scenario, "modo_entrada": mode, "visitas_persona_dia": qty,
                           "visitas_persona_anio": qty * tag["dias_equivalentes"]}
                    modos_anuales.append(row)
        stock = {base: max((c[base] for c in stocks), default=0) for base in red.bases}
        tablas["inventario_por_base"].append(pd.DataFrame([{"volumen_planificacion": volumen, "base": b, "unidades_necesarias_circulaciones_construidas": n} for b, n in stock.items()]))
        modos = pd.DataFrame(modos_anuales);tablas["modos_por_perfil"].append(modos)
        for scenario, g in modos.groupby("escenario"):control(f"{volumen}: anual {scenario}", g.visitas_persona_anio.sum(), volumen)
        for reserva in [2, 3]:
            fits = all(cierres) and max(totales) + reserva <= 30 and sum(stock.values()) <= 30
            tablas["resumen"].append(pd.DataFrame([{"volumen_planificacion": volumen, "cupo_coches_dia": 550,
                "reserva_ensayada": reserva, "maximo_programable": 30 - reserva,
                "mayor_flota_programada_construida": max(totales), "total_con_reserva": max(totales) + reserva,
                "inventario_comun_para_circulaciones": sum(stock.values()), "nueve_perfiles_con_cierre": all(cierres),
                "caben_circulaciones_construidas_en_30": fits, "minimo_global_demostrado": False,
                "oferta_anual_completa_validada": False, "energia_calculada": False}]))
    tablas["controles"] = pd.DataFrame(controles)
    for k in names:
        if isinstance(tablas[k], list):tablas[k] = pd.concat(tablas[k], ignore_index=True) if tablas[k] else pd.DataFrame()
    tablas["balance_anual"] = tablas["modos_por_perfil"].groupby(["volumen_planificacion", "escenario", "modo_entrada"], as_index=False).visitas_persona_anio.sum()
    tablas["colectivos_anuales"] = pd.DataFrame(colectivos).groupby(["volumen_planificacion", "colectivo"], as_index=False)[["visitas_sin_anio", "visitas_con_anio"]].sum()
    meta = {"decision": "D240", "hipotesis": "H130", "fecha": "2026-11-07", "parametros_conservados": params,
        "contraste_autorizado": {"cupo_coches_dia": 550, "reservas": [2, 3], "flota_fisica": 30, "volumenes": list(volumenes),
            "plazas_diseno": 46, "intervalo_minimo_acceso_y_regreso_min": 15, "regulacion_terminal_min": 10,
            "estancia_min_desde_entrada_parque_min": 120, "cierre_estudio_min": 1200},
        "busqueda": {"reinicios_principal": reinicios, "pasos_principal": pasos, "pasos_otros_perfiles": pasos_otros,
            "semilla_principal": 24000, "formas_iniciales": 7, "objetivo": "Número de cadenas del reloj; enlaces como desempate, sin objetivo energético",
            "minimo_global_demostrado": False}, "fuentes_sha256": fuentes,
        "limites": ["550 y dos reservas son hipótesis autorizadas para contraste; el libro conserva 500 y tres, sin nueva adopción institucional.",
            "Los repartos OD, colectivos, ocupaciones y visitas sin/con se conservan; los regresos y el interior no añaden visitas.",
            "La selección de cuotas usa el perfil de mayor demanda total; no demuestra que sea el más exigente para cualquier horario.",
            "La búsqueda horaria es finita y reproducible. No encontrar una solución no demuestra imposibilidad global.",
            "Los parciales cubren las zonas próximas representadas, con tiempos derivados y giros/espera sin validar. Otros usuarios y la continuidad interior no se suponen nulos.",
            "Reservas de estancia y aceptación no observadas: se publican las horas y duraciones, sin certificar calidad o aceptación real.",
            "Cierre de estudio a las 20 h; personal, cocheras exteriores y alimentación/continuidad exterior TITSA siguen pendientes.",
            "Las circulaciones que exceden treinta son diagnósticos; el inventario construido tampoco es un mínimo global.",
            "No se calcula energía, ahorro o p85 nuevo ni se actualiza el informe."],
        "entorno": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__}}
    return Etapa(tablas), meta


def generar_horarios_550(root, destino, **kwargs):
    root, destino = Path(root).resolve(), Path(destino).resolve();permitido = (root / SALIDAS).resolve()
    data = (root / BASE).resolve().parents[3]
    if destino == permitido or any(destino.is_relative_to(p) for p in [root, data]) and not destino.is_relative_to(permitido):
        raise ValueError("Elegir una ejecución nueva, independiente de fuentes y resultados anteriores.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):raise FileExistsError("La ejecución anterior se conserva.")
    etapa, meta = preparar_horarios_550(root, **kwargs);destino.mkdir(parents=True, exist_ok=True)
    for n, t in etapa.tablas.items():
        if not t.empty:t.to_csv(destino / (n + ".csv"), sep=";", index=False, encoding="utf-8-sig", float_format="%.17g")
    paquete = Path(__file__).parents[1]
    nombres = ["flujos/horarios_550.py", "operacion/reloj_integrado.py", "operacion/refinar_reservas.py",
               "operacion/horarios_compartidos.py", "operacion/circulacion_compartida.py", "operacion/red_compartida.py",
               "demanda/escenarios_2028.py", "demanda/perfiles_operacion_2028.py", "operacion/figura_reloj.py"]
    meta["codigo_sha256"] = {"movilidad_teide/" + p: sha256_archivo(paquete / p) for p in nombres}
    meta["codigo_sha256"]["scripts/contrastar_horarios_550.py"] = sha256_archivo(paquete.parents[1] / "scripts/contrastar_horarios_550.py")
    meta["resultados_sha256"] = {p.name: sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    from movilidad_teide.operacion.figura_reloj import dibujar_circulaciones
    dibujar_circulaciones(etapa.tablas["movimientos"], etapa.tablas["perfiles"], destino)
    meta["figuras_sha256"] = {p.name: sha256_archivo(p) for p in sorted(destino.glob("circulacion_550.*"))}
    (destino / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return etapa, meta
