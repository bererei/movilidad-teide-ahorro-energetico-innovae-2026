"""Contrasto cupos y construcciones de horarios sin seleccionar por energía."""
from itertools import product
import math

import numpy as np
import pandas as pd

from movilidad_teide.demanda.escenarios_2028 import _cuotas_enteras
from movilidad_teide.operacion.ampliacion import _minimo_vehiculos
from movilidad_teide.operacion.horarios import _proponer, _programar
from movilidad_teide.energia.sensibilidad_modal import reasignar_en_horario_conservado


def cota_cualquier_reparto(objetivos, movimientos, valores, *, cupo):
    """Minimizo una cota necesaria sobre todos los repartos enteros del cupo.

    Se mantienen flotas separadas por servicio y recorridos interiores completos,
    como en el constructor existente. La regulación entre viajes cuenta; omito
    vacíos, conflictos y espera. No es el mínimo de una oferta realizable.
    """
    p = objetivos.set_index("punto")
    puntos = ["CHIO", "VILAFLOR", "OROTAVA", "LAGUNA"]
    if set(p.index) != set(puntos) or p.index.duplicated().any():
        raise ValueError("Faltan accesos o están repetidos.")
    cap = int(valores["plazas_guagua"] * valores["ocupacion_diseno"])
    occ, reg = valores["ocupacion_coche"], valores["regulacion_min"]
    inicio, cierre = 60 * valores["hora_inicio_acceso"], 60 * valores["hora_limite_bajada_parque"]
    margen, estancia, espera = (valores[k] for k in ["margen_enlace_interior_min", "estancia_min_visita_min", "espera_max_lanzadera_min"])
    tiempos = movimientos.groupby(["punto", "sentido"]).tiempo_recorrido_min.first()
    di = float(tiempos["INTERIOR", "ida"])
    if di != tiempos["INTERIOR", "vuelta"] or cap <= 0 or reg < 0 or occ <= 0:
        raise ValueError("Duraciones o capacidades incompatibles con la cota.")
    # Los viajes usados empiezan con el primer enlace posible. El último es
    # regreso antes de la última bajada, o salida de la última visita admisible.
    primero = inicio + min(tiempos[q, "ida"] for q in puntos) + margen
    ultimo = max(cierre - margen, cierre - estancia + espera + di)
    if ultimo <= primero:
        raise ValueError("Ventana interior sin duración positiva.")
    antes = p.visitas_coche + p.visitas_excursiones_transferidas_dia + p.visitas_titsa
    quotas = np.arange(int(cupo) + 1)
    access = {}
    for q in puntos:
        ni = np.maximum(0, np.ceil((antes[q] - quotas * occ - 1e-8) / cap))
        maximo = math.floor((cierre - estancia - tiempos[q, "ida"] - inicio) / valores["intervalo_refuerzo_punta_min"]) + 1
        # Con V vehículos, N viajes requieren N- V regulaciones dentro de
        # su ventana: V >= trabajo/(ventana + regulación).
        access[q] = np.ceil((ni * (tiempos[q, "ida"] + tiempos[q, "vuelta"] + 2 * reg) - 1e-8)
                            / (cierre + tiempos[q, "vuelta"] - inicio + reg))
        access[q][(quotas > math.floor(p.loc[q, "coches_sin_dia"])) | (ni > maximo)] = np.inf
    def pareja(a, b):
        mins, reparto = [], []
        for total in quotas:
            izquierda = np.arange(total + 1)
            valores = access[a][izquierda] + access[b][total - izquierda]
            elegido = int(valores.argmin())
            mins.append(valores[elegido]); reparto.append((elegido, int(total) - elegido))
        return np.array(mins), reparto
    sur, qs = pareja("CHIO", "VILAFLOR")
    norte, qn = pareja("OROTAVA", "LAGUNA")
    demanda_sur = antes[["CHIO", "VILAFLOR"]].sum() - quotas * occ
    demanda_norte = antes[["OROTAVA", "LAGUNA"]].sum() - (cupo - quotas) * occ
    recorridos = np.maximum(0, np.ceil((np.maximum(demanda_sur, demanda_norte) - 1e-8) / cap))
    interior = np.ceil((2 * recorridos * (di + reg) - 1e-8) / (ultimo - primero + reg))
    totales = sur + norte[cupo - quotas] + interior
    if not np.isfinite(totales).any():
        return {"reparto_admisible_por_intervalos": False, "cota_con_sustitucion": np.nan}
    elegido = int(totales.argmin())
    reparto = dict(zip(puntos, [*qs[elegido], *qn[cupo - elegido]]))
    return {"reparto_admisible_por_intervalos": True,
        "cota_acceso": int(sur[elegido] + norte[cupo - elegido]), "cota_interior": int(interior[elegido]),
        "cota_programadas": int(totales[elegido]),
        "cota_con_sustitucion": int(totales[elegido] + valores["reserva_minima_dentro_flota"]),
        "descarta_30_bajo_servicios_separados": bool(totales[elegido] + valores["reserva_minima_dentro_flota"] > valores["vehiculos_contrato_contraste"]),
        "inicio_ventana_interior_min": primero, "fin_ventana_interior_min": ultimo,
        **{"cuota_en_minimo_cota_" + q: int(n) for q, n in reparto.items()},
        "horario_suficiente_demostrado": False,
        "alcance": "Cota favorable sobre todos los cupos enteros; flotas separadas y recorridos interiores completos"}


def cuotas_para_limites(objetivos, limites, *, cupo, ocupacion, capacidad):
    """Primero cubro la necesidad por intervalo; reparto el resto con pesos OD.

    Es una propuesta de regulación por acceso. Conserva la demanda territorial
    total; cambia qué visitantes en coche obtienen autorización, no su origen.
    Cumplir este límite necesario no acredita interior, horarios o flota.
    """
    p = objetivos.set_index("punto")
    slots = limites.set_index("punto").salidas_maximas_si_intervalo_15_sin_salidas_simultaneas
    if set(p.index) != set(slots.index) or p.index.duplicated().any() or slots.index.duplicated().any():
        raise ValueError("Los accesos de cuotas y límites no coinciden.")
    antes = p.visitas_coche + p.visitas_excursiones_transferidas_dia + p.visitas_titsa
    necesarias = np.ceil(((antes - slots * capacidad) / ocupacion - 1e-10).clip(lower=0)).astype(int)
    tabla = pd.DataFrame({"coches_minimos_por_limite_acceso": necesarias,
                          "coches_sin_intervencion_dia": p.coches_sin_dia})
    if necesarias.sum() > cupo or necesarias.gt(np.floor(p.coches_sin_dia)).any():
        return None, tabla.reset_index()
    extras = _cuotas_enteras(p.coches_sin_dia - necesarias, cupo - int(necesarias.sum()))
    cuotas = necesarias + extras
    tabla["cuota_candidata_coches"] = cuotas
    return cuotas.to_dict(), tabla.reset_index()


def ensayar_horario(objetivos, movimientos, pares_anteriores, paradas, valores):
    """Búsqueda acotada con el constructor existente y modulación del interior.

    Ensayo dos intervalos interiores, fases y prioridades; conservo tiempos,
    estancias, conexiones, destinos, cierre y regulación. El fracaso no prueba
    un mínimo global. Un horario fuera de treinta es solo un diagnóstico.
    """
    cap = int(valores["plazas_guagua"] * valores["ocupacion_diseno"])
    puntos = ["VILAFLOR", "CHIO", "OROTAVA", "LAGUNA"]
    if objetivos.tipo_dia_publicado.nunique() != 1 or set(objetivos.punto) != set(puntos):
        raise ValueError("El constructor necesita un solo perfil con cuatro accesos.")
    dia = objetivos.tipo_dia_publicado.iloc[0]
    dur = {q: tuple(float(movimientos.loc[movimientos.punto.eq(q) & movimientos.sentido.eq(s),
                    "tiempo_recorrido_min"].unique().item()) for s in ["ida", "vuelta"]) for q in puntos}
    di = movimientos.loc[movimientos.punto.eq("INTERIOR"), "tiempo_recorrido_min"].unique()
    if len(di) != 1:
        raise ValueError("La búsqueda necesita una duración interior simétrica conservada.")
    geo = movimientos[["punto", "sentido", "origen", "destino", "itinerary_id"]].drop_duplicates()
    km = movimientos.groupby(["punto", "sentido"]).km_por_recorrido.first().to_dict()
    destinos = pares_anteriores[["punto", "parada_entrada", "parada_destino"]].drop_duplicates().set_index("punto")
    if destinos.index.duplicated().any():
        raise ValueError("Los destinos conservados no son únicos por acceso.")
    orden = paradas.set_index("parada_id").orden
    counts = {(r.punto, s): max(1, math.ceil((r.demanda_lanzadera_dia - 1e-8) / cap))
              for r in objetivos.itertuples() for s in ["ida", "vuelta"]}
    inicio = 60 * valores["hora_inicio_acceso"]
    margen, espera = valores["margen_enlace_interior_min"], valores["espera_max_lanzadera_min"]
    a0, b0 = inicio + dur["VILAFLOR"][0] + margen, inicio + dur["OROTAVA"][0] + margen
    ultima = float(movimientos.loc[movimientos.punto.eq("INTERIOR") &
                                   movimientos.componente.str.startswith("comercial"), "salida_min"].max())
    candidatos, intentos = [], []
    for intervalo, da, db, bias, spread in product([10., 7.5], [0., 10.], [0., 10., 20.], [-.5, 0., .5], [True, False]):
        c = {"duraciones": dur, "duracion_interior": float(di[0]), "geografia": geo, "km": km,
             "cuentas": {dia: counts}, "minimo_interior": {"ida": 1, "vuelta": 1},
             "ultima_interior": ultima, "intervalo": intervalo, "espera": espera, "margen": margen,
             "estancia": valores["estancia_min_visita_min"], "inicio": inicio,
             "cierre": 60 * valores["hora_limite_bajada_parque"],
             "banda_ultimas_bajadas": valores["banda_ultimas_bajadas_min"],
             "intervalo_acceso": valores["intervalo_refuerzo_punta_min"], "capacidad": cap, "valores": valores}
        propuesta = _proponer(c, dia, a0 + da, b0 + db, bias, spread, {q: 0. for q in puntos})
        registro = {"intervalo_interior_min": intervalo, "fase_boca_min": a0 + da,
                    "fase_portillo_min": b0 + db, "prioridad": bias, "repartir_en_ventana": spread,
                    "cadenas_construidas": propuesta is not None}
        intentos.append(registro)
        if propuesta is None:
            continue
        plan, parejas = propuesta
        interiores = plan.loc[plan.punto.eq("INTERIOR")]
        links = []
        for row in parejas.to_dict("records"):
            punto = row["punto"]
            a, b = destinos.loc[punto, ["parada_entrada", "parada_destino"]]
            sentido = "ida" if orden[a] < orden[b] else "vuelta"
            reverse = "vuelta" if sentido == "ida" else "ida"
            uid = interiores.loc[interiores.sentido.eq(sentido) & np.isclose(interiores.salida_min, row["interior_up_min"]), "id_salida"].item()
            bid = interiores.loc[interiores.sentido.eq(reverse) & np.isclose(interiores.salida_min, row["interior_back_min"]), "id_salida"].item()
            links.append({**row, "parada_entrada": a, "parada_destino": b,
                          "id_interior_ida": uid, "id_interior_regreso": bid,
                          "personas_asignadas_dia_tipo": cap, "tipo_dia": dia})
        links = pd.DataFrame(links)
        usados = set(links.id_interior_ida) | set(links.id_interior_regreso)
        plan = plan.loc[plan.punto.ne("INTERIOR") | plan.id_salida.isin(usados)].copy()
        # Aplico treinta minutos donde la cota ordinaria permite atender el acceso.
        permitido = True
        for q, g in plan.loc[plan.punto.ne("INTERIOR") & plan.sentido.eq("ida")].groupby("punto"):
            ultimo = c["cierre"] - c["estancia"] - dur[q][0]
            n30 = math.floor((ultimo - inicio) / valores["intervalo_minimo_subidas_min"]) + 1
            minimo = valores["intervalo_refuerzo_punta_min"] if counts[q, "ida"] > n30 else valores["intervalo_minimo_subidas_min"]
            if g.salida_min.sort_values().diff().dropna().lt(minimo - 1e-8).any():
                permitido = False
        registro["intervalos_admisibles"] = permitido
        if not permitido:
            continue
        lower = sum(_minimo_vehiculos(list(zip(g.sentido, g.salida_min)),
                    dict(zip(["ida", "vuelta"], (di[0], di[0]) if q == "INTERIOR" else dur[q])), valores["regulacion_min"])
                    for q, g in plan.groupby("punto"))
        registro["cota_para_reloj_fijo"] = lower
        candidatos.append((lower, len(plan), intervalo, a0 + da, b0 + db, bias, spread, c, plan, links))
    if not candidatos:
        return {"diagnostico": {"horario_construido": False, "motivo": "Búsqueda acotada sin candidato; no prueba imposibilidad global"},
                "intentos": pd.DataFrame(intentos)}
    # Verifico como máximo tres construcciones distintas; no optimizo por energía.
    best = None
    for candidate in sorted(candidatos, key=lambda x: x[:7])[:3]:
        lower, _, _, _, _, _, _, c, plan, links = candidate
        if best is not None and lower >= len(best["vehiculos"]):
            continue
        fisica = _programar(c, plan)
        if fisica is None:
            continue
        mo = fisica["movimientos"].assign(tipo_dia=dia, dias_calendario=1)
        objetivos_check = objetivos.rename(columns={"tipo_dia_publicado": "tipo_dia",
            "demanda_lanzadera_dia": "demanda_lanzadera_condicionada_dia"}).copy()
        objetivos_check["dias_calendario"] = 1
        check = reasignar_en_horario_conservado(mo, links, objetivos_check, paradas, capacidad=cap,
            margen=margen, espera=espera, estancia=valores["estancia_min_visita_min"])
        full = objetivos_check.copy()
        full["demanda_lanzadera_condicionada_dia"] = full.punto.map(links.groupby("punto").size()) * cap
        reasignar_en_horario_conservado(mo, links, full, paradas, capacidad=cap,
            margen=margen, espera=espera, estancia=valores["estancia_min_visita_min"])
        best = {**fisica, "movimientos": mo, "pares": check["pares"], "cargas_tramos": check["cargas_tramos"]}
    if best is None:
        return {"diagnostico": {"horario_construido": False, "motivo": "No se construye circulación cerrada; sin prueba global"},
                "intentos": pd.DataFrame(intentos)}
    n = len(best["vehiculos"])
    best["diagnostico"] = {"horario_construido": True, "vehiculos_programados": n,
        "sustitucion_minima": int(valores["reserva_minima_dentro_flota"]),
        "total_necesario_en_esta_construccion": n + int(valores["reserva_minima_dentro_flota"]),
        "cabe_en_30_con_reserva": n + valores["reserva_minima_dentro_flota"] <= valores["vehiculos_contrato_contraste"],
        "minimo_global_demostrado": False, "otros_usuarios_interior_identificados": False,
        "motivo": "Construcción de cadenas conocidas; no dimensionamiento mínimo global ni validación institucional"}
    best["intentos"] = pd.DataFrame(intentos)
    return best
