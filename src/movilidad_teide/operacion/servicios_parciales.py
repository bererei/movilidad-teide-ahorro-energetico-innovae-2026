"""Descompongo viajes interiores usando los pasos por paradas ya calculados."""
import pandas as pd

from .interior import horario_en_paradas


def preparar_viajes(movimientos, pares, paradas, red, *, parciales):
    """Conservo los horarios que experimentan los pasajeros y sus reservas.

    Los parciales terminan en las entradas al Parador o Teleférico sobre el eje.
    La posibilidad física de invertir allí el sentido es una hipótesis pendiente
    de validar; no se añade un trazado de maniobra o entrada a recintos.
    """
    comerciales = movimientos.loc[movimientos.componente.str.startswith("comercial")].copy()
    if comerciales.id_salida.duplicated().any():
        raise ValueError("Evaluar un solo horario, sin viajes comerciales repetidos.")
    reloj = horario_en_paradas(movimientos, paradas).set_index(["id_salida", "parada_id"]).paso_min
    filas, reservas, correspondencias = [], [], {}
    for row in comerciales.loc[comerciales.punto.ne("INTERIOR")].itertuples():
        entry = red.destinos.loc[row.punto, "parada_entrada"]
        a, b = ("cabecera:" + row.punto, entry) if row.sentido == "ida" else (entry, "cabecera:" + row.punto)
        filas.append({"id_salida": row.id_salida, "servicio": row.punto, "familia": "Acceso",
            "origen": a, "destino": b, "salida_min": row.salida_min, "llegada_min": row.llegada_min,
            "km": row.km_por_recorrido, "id_fuente": row.id_salida})
    origenes = comerciales.set_index("id_salida")
    def obtener_viaje(tid, a, b):
        key = (tid, a, b) if parciales else (tid, *red.extremos)
        if key not in correspondencias:
            source = origenes.loc[tid]
            if parciales:
                salida, llegada = float(reloj[tid, a]), float(reloj[tid, b])
                tramo = red.conectar(a, b)
                ident = f"{tid}__{a}__{b}"
                aa, bb, km = a, b, tramo["km"]
                servicio = "INTERIOR_SUR" if red.extremos[0] in {a, b} else "INTERIOR_NORTE"
            else:
                salida, llegada, km, ident = float(source.salida_min), float(source.llegada_min), float(source.km_por_recorrido), tid
                aa, bb = red.extremos if source.sentido == "ida" else red.extremos[::-1]
                servicio = "INTERIOR"
            if llegada <= salida:
                raise ValueError("Una reserva no sigue el sentido del viaje interior.")
            correspondencias[key] = ident
            filas.append({"id_salida": ident, "servicio": servicio, "familia": "Interior",
                "origen": aa, "destino": bb, "salida_min": salida, "llegada_min": llegada,
                "km": km, "id_fuente": tid})
        return correspondencias[key]
    for row in pares.itertuples():
        for leg, tid, a, b in [("ida", row.id_interior_ida, row.parada_entrada, row.parada_destino),
                              ("regreso", row.id_interior_regreso, row.parada_destino, row.parada_entrada)]:
            ident = obtener_viaje(tid, a, b)
            reservas.append({"id_subida": row.id_subida, "id_regreso": row.id_regreso,
                "id_interior": ident, "tramo_visita": leg, "parada_origen": a, "parada_destino": b,
                "embarque_min": float(reloj[tid, a]), "desembarque_min": float(reloj[tid, b]),
                "personas": float(row.personas_asignadas_dia_tipo), "punto": row.punto})
    viajes = pd.DataFrame(filas).sort_values(["salida_min", "id_salida"]).reset_index(drop=True)
    if viajes.id_salida.duplicated().any():
        raise ValueError("La descomposición duplica un viaje comercial.")
    return viajes, pd.DataFrame(reservas)
