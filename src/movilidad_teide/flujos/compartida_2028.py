"""Contrasto flota compartida y servicios interiores parciales sin recalcular energía."""
from pathlib import Path
import json
import platform

import numpy as np
import pandas as pd

from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.operacion.servicios_parciales import preparar_viajes
from movilidad_teide.operacion.circulacion_compartida import encadenar_viajes, cerrar_bases, materializar
from movilidad_teide.operacion.horarios_compartidos import buscar_horario, concurrencia
from movilidad_teide.trazabilidad import sha256_archivo
from .tipos import Etapa


BASE = "data/silver/operacion/red/banda_demanda_cupos"
PARADAS = "data/silver/operacion/paradas/referencias_paradas.csv"
SALIDAS = "data/silver/movilidad/operacion_compartida_2028"
CASOS = ((2500000, 500), (2400000, 525), (2600000, 525))


def preparar_compartida_2028(root, *, explorar=True):
    root = Path(root).resolve();hashes = {}
    def registrar(p, esperado=None):
        actual = sha256_archivo(root / p)
        if esperado is not None and actual != esperado:raise ValueError(f"Fuente modificada: {p}")
        hashes[p] = actual
    registrar(BASE + "/metadatos.json")
    fuente = json.loads((root / BASE / "metadatos.json").read_text())
    for p, h in fuente["fuentes_sha256"].items():registrar(p, h)
    for p, h in fuente["resultados_sha256"].items():registrar(BASE + "/" + p, h)
    registrar(PARADAS)
    parametros = leer_parametros(root);v = {p["id"]: p["valor_utilizado"] for p in parametros["parametros"]}
    if (v["plazas_guagua"] != 55 or int(v["plazas_guagua"] * v["ocupacion_diseno"]) != 46
            or v["reserva_minima_dentro_flota"] != 3 or v["vehiculos_contrato_contraste"] != 30
            or v["intervalo_refuerzo_punta_min"] != 15 or v["regulacion_min"] != 10):
        raise ValueError("Revisar las condiciones conservadas antes de ejecutar otro caso.")
    rd = lambda p: pd.read_csv(root / p, sep=";", float_precision="round_trip")
    movimientos = rd(BASE + "/movimientos_diagnosticos.csv");pares = rd(BASE + "/pares_diagnosticos.csv")
    paradas = rd(PARADAS);objetivos = rd(BASE + "/objetivos_por_perfil.csv")
    red = RedOperativa(movimientos, pares, paradas)
    resumen, cronologias, reservas_todas, fisicas, candidatos, cuotas, conservacion = [], [], [], [], [], [], []
    for volumen, cupo in CASOS:
        mask = movimientos.volumen_planificacion.eq(volumen) & movimientos.cupo_global_coches_dia.eq(cupo)
        mo, pa = movimientos.loc[mask], pares.loc[pares.volumen_planificacion.eq(volumen) & pares.cupo_global_coches_dia.eq(cupo)]
        ident = {"volumen_planificacion": volumen, "cupo_global_coches_dia": cupo,
                 "observacion": int(pa.observacion.unique().item())}
        cantidad = float(pa.personas_asignadas_dia_tipo.sum())
        for parcial in [False, True]:
            trips, res = preparar_viajes(mo, pa, paradas, red, parciales=parcial)
            for compartir in [False, True]:
                variante = ("Parciales" if parcial else "Eje completo") + (" · compartida" if compartir else " · separada")
                t, chains = encadenar_viajes(trips, red, regulacion=v["regulacion_min"], compartir=compartir)
                cierre = cerrar_bases(t, chains, red, regulacion=v["regulacion_min"])
                n = len(chains);tag = {**ident, "variante": variante}
                resumen.append({**tag, "tipo_contraste": "Agenda D238 conservada", "tramos_comerciales_modelados": len(t),
                    "concurrencia_minima_conduccion": concurrencia(t, 0.), "cadenas_minimas_reloj": n,
                    "cierre_bases_construido": cierre is not None, "cabe_en_30_con_tres_libres": n + 3 <= 30,
                    "oferta_anual_30_validada": False})
                cronologias.append(t.assign(**tag));reservas_todas.append(res.assign(**tag))
                if cierre is not None:
                    a, b = cierre
                    fisicas.append(materializar(t, chains, a, red, regulacion=v["regulacion_min"], bases_finales=b).assign(**tag))
                for sentido in ["ida", "regreso"]:
                    qty = float(res.loc[res.tramo_visita.eq(sentido), "personas"].sum())
                    if abs(qty - cantidad) > 1e-8:raise ValueError("Se han perdido o duplicado viajeros en la descomposición.")
                conservacion.append({**tag, "visitas_persona_dia": cantidad, "interior_no_anade_visitas": True,
                                     "regreso_no_anade_visitas": True})
        if explorar:
            hist = objetivos.loc[objetivos.volumen_planificacion.eq(volumen) & objetivos.cupo_global_coches_dia.eq(cupo)
                & objetivos.politica_cupo.eq("Proporcional OD") & ~objetivos.es_media_tipo]
            for directos in [False, True]:
                result = buscar_horario(hist, red, v, cupo=cupo, directos=directos, grupo_refuerzo=1)
                variante = "Reservas nuevas · " + ("directo hasta zona próxima" if directos else "parciales con transbordo")
                tag = {"volumen_planificacion": volumen, "cupo_global_coches_dia": cupo,
                       "observacion": result.get("observacion", -1), "variante": variante}
                if "diagnostico" not in result:
                    resumen.append({**tag, "tipo_contraste": "Agenda nueva", "construido": False,
                                    "motivo": result["motivo"], "oferta_anual_30_validada": False});continue
                d = result["diagnostico"]
                resumen.append({**tag, "tipo_contraste": "Agenda nueva", **d,
                    "cadenas_minimas_reloj": d["cadenas_minimas_para_el_reloj_elegido"], "oferta_anual_30_validada": False})
                cronologias.append(result["viajes"].assign(**tag));reservas_todas.append(result["reservas"].assign(**tag))
                if "movimientos" in result:fisicas.append(result["movimientos"].assign(**tag))
                candidatos.append(result["intentos"].assign(**tag))
                cuotas.append(pd.DataFrame([{"punto": q, "cuota_coches_dia": c, **tag} for q, c in result["cuotas"].items()]))
                # Mismo cupo y mismos visitantes: la autorización solo cambia el modo.
                if sum(result["cuotas"].values()) != cupo:raise ValueError("El nuevo reparto cambia el cupo global.")
                before = hist.loc[hist.observacion.eq(tag["observacion"])].visitas_sin_dia.sum()
                g = hist.loc[hist.observacion.eq(tag["observacion"])].set_index("punto")
                qty = float((g.visitas_coche + g.visitas_excursiones_transferidas_dia + g.visitas_titsa).sum() - cupo * v["ocupacion_coche"])
                actual = float(result["reservas"].personas.sum())
                if abs(qty - actual) > 1e-8:raise ValueError("La nueva agenda cambia las visitas en lanzadera.")
                after = actual + cupo * v["ocupacion_coche"] + g.visitas_excursiones_permanecen_dia.sum()
                if abs(before - after) > 1e-8:raise ValueError("No se conservan las visitas sin/con.")
                conservacion.append({**tag, "visitas_persona_dia": actual, "visitas_sin_total_dia": before,
                                     "visitas_con_total_dia": after, "interior_no_anade_visitas": True,
                                     "regreso_no_anade_visitas": True})
    anual = rd(BASE + "/balance_anual.csv")
    filtro = pd.Series(False, index=anual.index)
    for n, c in CASOS:filtro |= anual.volumen_planificacion.eq(n) & anual.cupo_global_coches_dia.eq(c)
    anual = anual.loc[filtro & anual.politica_cupo.eq("Proporcional OD")].drop(columns="politica_cupo").copy()
    anual["estado"] = "Conservación modal común; no oferta de treinta acreditada"
    tablas = {"resumen": pd.DataFrame(resumen), "cronologias_comerciales": pd.concat(cronologias, ignore_index=True),
        "reservas": pd.concat(reservas_todas, ignore_index=True), "conservacion_visitas": pd.DataFrame(conservacion),
        "movimientos_con_cierre": pd.concat(fisicas, ignore_index=True) if fisicas else pd.DataFrame(),
        "intentos_nuevos_horarios": pd.concat(candidatos, ignore_index=True) if candidatos else pd.DataFrame(),
        "cuotas_propuestas": pd.concat(cuotas, ignore_index=True) if cuotas else pd.DataFrame(),
        "comparacion_anual_modos": anual}
    meta = {"decision": "D239", "hipotesis": "H129", "fecha": "2026-11-07", "parametros": parametros,
        "explorar_nuevas_reservas": bool(explorar),
        "casos": [list(c) for c in CASOS], "fuentes_sha256": hashes,
        "reglas": {"plazas_diseno": 46, "flota_total": 30, "sustitutas_dentro_total": 3,
            "regulacion_terminal_min": 10, "intervalo_refuerzo_por_vehiculo_min": 15,
            "refuerzos_simultaneos_adoptados": False, "cierre_estudio_min": 1200},
        "naturaleza": "Contraste de operaciones; no se adopta una cifra exacta de visitas ni se acredita oferta anual de treinta",
        "energia_calculada": False, "informe_modificado": False, "excel_modificado": False,
        "limites": ["Recorridos parciales y tiempos interpolados sobre el eje conservado, no velocidades o maniobras observadas.",
            "Giro y espera de autocares en Parador/Teleférico, personal y explotación requieren validación; no se entra a recintos o se dibujan conectores.",
            "Los parciales cubren las cadenas conocidas de zona próxima. No se demuestra demanda interior adicional nula ni se suprime por validación el servicio entre ambas zonas.",
            "El mismo vehículo puede cambiar de servicio; toda reposición usa exclusivamente caminos de la red ya trazada y tiempo positivo.",
            "En la continuidad directa no hay transbordo ni terminal en el límite del Parque; se conservan diez minutos de regulación en los extremos reales.",
            "Mínimo de cadenas del reloj elegido calculado por emparejamiento máximo; no es mínimo global de horarios.",
            "Las nuevas agendas prueban un catálogo finito de cuotas y formas de reserva; no todas las organizaciones posibles.",
            "Beatriz confirma conservar quince minutos entre vehículos. No se adoptan ni ejecutan refuerzos simultáneos; las agendas nuevas comprueban también los regresos.",
            "El cierre hasta las 20 h es una condición del contraste, no un turno de conductor validado; las cocheras exteriores no están inventariadas.",
            "Si no se cierra una circulación se publica como diagnóstico, sin reposiciones gratuitas o disponibilidad física supuesta.",
            "El perfil crítico ensayado no sustituye la validación anual ni el diseño p85; usuarios interiores adicionales y continuidad exterior TITSA siguen pendientes."],
        "entorno": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__}}
    return Etapa(tablas), meta


def generar_compartida_2028(root, destino, *, explorar=True):
    root, destino = Path(root).resolve(), Path(destino).resolve();permitido = (root / SALIDAS).resolve()
    data = (root / BASE).resolve().parents[3]
    if destino == permitido or any(destino.is_relative_to(p) for p in [root, data]) and not destino.is_relative_to(permitido):
        raise ValueError("Elegir una ejecución nueva e independiente de los datos previos.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):raise FileExistsError("La ejecución anterior se conserva.")
    etapa, meta = preparar_compartida_2028(root, explorar=explorar);destino.mkdir(parents=True, exist_ok=True)
    for n, t in etapa.tablas.items():
        if not t.empty:t.to_csv(destino / (n + ".csv"), sep=";", index=False, encoding="utf-8-sig", float_format="%.17g")
    paquete = Path(__file__).parents[1]
    nombres = ["flujos/compartida_2028.py", "operacion/red_compartida.py", "operacion/servicios_parciales.py",
               "operacion/circulacion_compartida.py", "operacion/horarios_compartidos.py", "operacion/figuras_compartida.py", "operacion/interior.py"]
    meta["codigo_sha256"] = {"movilidad_teide/" + n: sha256_archivo(paquete / n) for n in nombres}
    meta["codigo_sha256"]["scripts/contrastar_compartida_2028.py"] = sha256_archivo(paquete.parents[1] / "scripts/contrastar_compartida_2028.py")
    meta["resultados_sha256"] = {p.name: sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    from movilidad_teide.operacion.figuras_compartida import dibujar_parciales
    dibujar_parciales(RedOperativa(pd.read_csv(root / BASE / "movimientos_diagnosticos.csv", sep=";", float_precision="round_trip"),
        pd.read_csv(root / BASE / "pares_diagnosticos.csv", sep=";", float_precision="round_trip"),
        pd.read_csv(root / PARADAS, sep=";", float_precision="round_trip")), destino)
    meta["figuras_sha256"] = {p.name: sha256_archivo(p) for p in sorted(destino.glob("esquema_servicios_parciales.*"))}
    (destino / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return etapa, meta
