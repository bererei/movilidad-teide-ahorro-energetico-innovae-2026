"""Compruebo capacidad sin convertir una cota favorable en un horario viable."""
import math
import numpy as np
import pandas as pd


def comprobar_flota(objetivos, movimientos, pares, paradas, valores, *, capacidad_contraste=None):
    """Cota de conducción y plazas del horario anterior, con visitas conservadas.

    Omite regulación, esperas, vacíos y restricciones de bases en la cota.
    Permite usar los vehículos indistintamente durante toda la ventana de acceso.
    Si ni así caben, ningún horario más restringido resuelve ese día medio.
    """
    cap = int(valores["plazas_guagua"] * valores["ocupacion_diseno"])
    if capacidad_contraste is not None:
        if (isinstance(capacidad_contraste, bool) or not np.isfinite(capacidad_contraste)
                or int(capacidad_contraste) != capacidad_contraste
                or not 1 <= capacidad_contraste <= valores["plazas_guagua"]):
            raise ValueError("Capacidad de contraste fuera del vehículo nominal.")
        cap = int(capacidad_contraste)
    # La última hora del perfil está incluida: 7..19 representa [7,20).
    # Concedo toda esa ventana también al interior, aunque los cierres de
    # visita y las últimas bajadas solo pueden restringir más la operación.
    ventana = 60 * (valores["hora_fin_acceso"] + 1 - valores["hora_inicio_acceso"])
    flota = int(valores["vehiculos_contrato_contraste"])
    reserva = int(valores["reserva_minima_dentro_flota"])
    if cap <= 0 or ventana <= 0 or not 0 <= reserva < flota:
        raise ValueError("Capacidad, ventana o flota inválidas.")
    if objetivos.duplicated(["tipo_dia_publicado", "punto"]).any():
        raise ValueError("Objetivos repetidos.")
    demanda = objetivos.demanda_lanzadera_dia
    if not np.isfinite(demanda).all() or demanda.lt(0).any():
        raise ValueError("Demanda de lanzaderas inválida.")
    destinos = pares[["punto", "parada_entrada", "parada_destino"]].drop_duplicates()
    if destinos.punto.duplicated().any() or set(destinos.punto) != set(objetivos.punto):
        raise ValueError("El patrón interior anterior no es único por acceso.")
    pos = paradas.set_index("parada_id").posicion_m
    if pos.index.duplicated().any() or not pos.is_monotonic_increasing or pos.iloc[-1] <= 0:
        raise ValueError("Referencias interiores inválidas.")
    tiempos = movimientos.groupby(["punto", "sentido"]).tiempo_recorrido_min.agg(["min", "max"])
    if not np.isfinite(tiempos).all().all() or not np.allclose(tiempos["min"], tiempos["max"], rtol=0, atol=1e-10):
        raise ValueError("Duraciones incompatibles entre las observaciones.")
    detalle, cargas, filas = [], [], []
    for tipo, block in objetivos.groupby("tipo_dia_publicado", sort=True):
        days = int(block.dias_calendario.iloc[0])
        for c in block.itertuples():
            ida, vuelta = (float(tiempos.loc[(c.punto, s), "min"]) for s in ["ida", "vuelta"])
            n = math.ceil(max(0., c.demanda_lanzadera_dia - 1e-8) / cap)
            # Última subida favorable: solo llegada y 120 minutos de estancia.
            ultimo = 60 * valores["hora_limite_bajada_parque"] - valores["estancia_min_visita_min"] - ida
            primero = 60 * valores["hora_inicio_acceso"]
            interval = valores["intervalo_refuerzo_punta_min"]
            salidas = max(0, math.floor((ultimo - primero) / interval + 1e-10) + 1)
            detalle.append({"tipo_dia_publicado": tipo, "punto": c.punto,
                "dias_calendario": days, "demanda_lanzadera_dia": c.demanda_lanzadera_dia,
                "parejas_minimas_acceso": n, "minutos_conduccion_acceso_minimos": n * (ida + vuelta),
                "salidas_maximas_si_intervalo_15_sin_salidas_simultaneas": salidas,
                "plazas_cota_intervalo_15": salidas * cap,
                "supera_cota_intervalo_15_sin_salidas_simultaneas": n > salidas})
        # Plazas por tramo del interior; no se suman sus embarques como visitas.
        # Se supone carga perfecta y ninguna reposición: es una relajación favorable.
        for a, b in zip(pos.iloc[:-1], pos.iloc[1:]):
            ocupantes = 0.
            for c in block.itertuples():
                z = destinos.loc[destinos.punto.eq(c.punto)].iloc[0]
                low, high = sorted([float(pos[z.parada_entrada]), float(pos[z.parada_destino])])
                if low <= a + 1e-8 and high >= b - 1e-8:
                    ocupantes += c.demanda_lanzadera_dia
            recorridos = math.ceil(max(0., ocupantes - 1e-8) / cap)
            minutos = (b - a) / float(pos.iloc[-1] - pos.iloc[0]) * sum(
                float(tiempos.loc[("INTERIOR", s), "min"]) for s in ["ida", "vuelta"])
            cargas.append({"tipo_dia_publicado": tipo, "inicio_m": a, "fin_m": b,
                "viajeros_por_sentido_dia": ocupantes, "recorridos_minimos_por_sentido": recorridos,
                "minutos_conduccion_interior_minimos": recorridos * minutos})
        accesos = sum(z["minutos_conduccion_acceso_minimos"] for z in detalle if z["tipo_dia_publicado"] == tipo)
        interior = sum(z["minutos_conduccion_interior_minimos"] for z in cargas if z["tipo_dia_publicado"] == tipo)
        cota_acceso = math.ceil((accesos - 1e-8) / ventana)
        cota_total = math.ceil((accesos + interior - 1e-8) / ventana)
        filas.append({"tipo_dia_publicado": tipo, "dias_calendario": days,
            "visitas_lanzadera_objetivo_dia": float(block.demanda_lanzadera_dia.sum()),
            "plazas_por_vehiculo": cap, "flota_total": flota, "reserva_minima": reserva,
            "maximo_programables": flota - reserva, "minutos_disponibles_por_vehiculo": ventana,
            "minutos_acceso_minimos": accesos, "minutos_interior_minimos": interior,
            "cota_vehiculos_solo_acceso": cota_acceso,
            "cota_vehiculos_acceso_e_interior": cota_total,
            "cota_total_incluida_reserva": cota_total + reserva,
            "imposible_30_incluso_sin_reserva": cota_total > flota,
            "imposible_30_con_reserva": cota_total > flota - reserva,
            "horario_viable_construido": False,
            "alcance": "Cota necesaria favorable de conducción; no dimensionamiento suficiente"})
    # El inventario anterior tiene cadenas completas ya verificadas. Su capacidad
    # se muestra por observación, sin afirmar que sea la máxima de treinta guaguas.
    anterior = []
    for (politica, observacion), b in pares.groupby(["politica", "observacion"], sort=True):
        for tipo, g in objetivos.groupby("tipo_dia_publicado", sort=True):
            por_punto = b.groupby("punto").plazas_vinculadas.sum()
            for c in g.itertuples():
                plazas = float(por_punto.get(c.punto, 0.))
                anterior.append({"politica": politica, "observacion_anterior": observacion,
                    "tipo_dia_nuevo": tipo, "punto": c.punto, "objetivo_visitas_dia": c.demanda_lanzadera_dia,
                    "plazas_cadenas_anteriores": plazas,
                    "pendientes_en_horario_anterior_dia": max(0., c.demanda_lanzadera_dia - plazas),
                    "cota_maxima_de_toda_operacion_con_30": False})
    return {"cota_flota_dias_medios": pd.DataFrame(filas),
            "cota_accesos_e_intervalos": pd.DataFrame(detalle),
            "cota_interior_por_tramos": pd.DataFrame(cargas),
            "contraste_cadenas_anteriores": pd.DataFrame(anterior)}
