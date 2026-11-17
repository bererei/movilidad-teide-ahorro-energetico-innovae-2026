"""Encadeno horarios fijados entre servicios, con reposiciones explícitas."""
from collections import deque, Counter

import numpy as np
import pandas as pd


def continuidad_original(a, b, red):
    """Dos fragmentos del mismo viaje no crean un terminal de regulación nuevo."""
    fuente = a.get("id_fuente")
    pos = getattr(red, "posiciones", {})
    if not isinstance(fuente, str) or fuente != b.get("id_fuente"):
        return False
    if not all(q in pos for q in [a["origen"], a["destino"], b["origen"], b["destino"]]):
        return False
    da, db = pos[a["destino"]] - pos[a["origen"]], pos[b["destino"]] - pos[b["origen"]]
    return da * db > 0 and (pos[b["origen"]] - pos[a["destino"]]) * da >= -1e-8


def emparejamiento_maximo(adyacencia, n_derecha):
    """Hopcroft–Karp determinista: máximo de enlaces, sin costes energéticos."""
    izq = [-1] * len(adyacencia);der = [-1] * n_derecha
    while True:
        nivel = [-1] * len(izq);cola = deque()
        for i, elegido in enumerate(izq):
            if elegido < 0:nivel[i] = 0;cola.append(i)
        hay = False
        while cola:
            i = cola.popleft()
            for j in adyacencia[i]:
                otro = der[j]
                if otro < 0:hay = True
                elif nivel[otro] < 0:nivel[otro] = nivel[i] + 1;cola.append(otro)
        if not hay:break
        def buscar(i):
            for j in adyacencia[i]:
                otro = der[j]
                if otro < 0 or nivel[otro] == nivel[i] + 1 and buscar(otro):
                    izq[i] = j;der[j] = i;return True
            nivel[i] = -1;return False
        for i in range(len(izq)):
            if izq[i] < 0:buscar(i)
    return izq, der


def encadenar_viajes(viajes, red, *, regulacion=10., compartir=True, criterio="distancia"):
    """Mínimo de cadenas del reloj y enlaces admitidos; bases se verifican después."""
    if isinstance(regulacion, (bool, np.bool_)) or not np.isfinite(regulacion) or regulacion < 0:
        raise ValueError("La regulación debe ser finita y no negativa.")
    t = viajes.sort_values(["salida_min", "id_salida"]).reset_index(drop=True)
    if t.id_salida.duplicated().any() or not np.isfinite(t[["salida_min", "llegada_min", "km"]]).all().all() or (t.llegada_min <= t.salida_min).any():
        raise ValueError("Viajes comerciales inválidos o repetidos.")
    filas = t.to_dict("records");ady = []
    for i, a in enumerate(filas):
        opciones = []
        for j, b in enumerate(filas):
            if i == j or not compartir and a["servicio"] != b["servicio"]:continue
            path = red.conectar(a["destino"], b["origen"])
            sigue = continuidad_original(a, b, red)
            necesita = a["llegada_min"] + path["minutos"] + (0. if sigue else regulacion + (regulacion if path["minutos"] > 1e-10 else 0.))
            if necesita <= b["salida_min"] + 1e-8:
                clave = (path["km"], b["salida_min"], b["id_salida"])
                if criterio == "servicio":clave = (a["servicio"] != b["servicio"], *clave)
                if criterio == "tiempo":clave = (b["salida_min"], path["km"], b["id_salida"])
                opciones.append((clave, j))
        ady.append([j for _, j in sorted(opciones)])
    match, anterior = emparejamiento_maximo(ady, len(t))
    cadenas = []
    for i, previo in enumerate(anterior):
        if previo < 0:
            cadena = [i]
            while match[cadena[-1]] >= 0:cadena.append(match[cadena[-1]])
            cadenas.append(cadena)
    if sorted(i for c in cadenas for i in c) != list(range(len(t))):
        raise ValueError("El encadenamiento pierde o duplica viajes.")
    return t, cadenas


def bases_admisibles(viajes, cadenas, red, *, inicio=420., fin=1200., regulacion=10.):
    """Cada unidad puede salir y volver a la misma base existente en la ventana."""
    allowed, details = [], []
    for k, cadena in enumerate(cadenas):
        first, last = viajes.iloc[cadena[0]], viajes.iloc[cadena[-1]]
        opciones = []
        for base in red.bases:
            ida, vuelta = red.conectar(base, first.origen), red.conectar(last.destino, base)
            antes = ida["minutos"] + (regulacion if ida["minutos"] > 1e-10 else 0.)
            despues = regulacion + vuelta["minutos"] if vuelta["minutos"] > 1e-10 else 0.
            if first.salida_min - antes >= inicio - 1e-8 and last.llegada_min + despues <= fin + 1e-8:
                opciones.append((ida["km"] + vuelta["km"], base))
                details.append({"cadena": k, "base": base, "km_reposicion_extremos": ida["km"] + vuelta["km"],
                    "salida_base_min": first.salida_min - antes, "llegada_base_min": last.llegada_min + despues})
        allowed.append([b for _, b in sorted(opciones)])
    return allowed, pd.DataFrame(details)


def cerrar_bases(viajes, cadenas, red, *, inicio=420., fin=1200., regulacion=10.):
    """Conservo el inventario por base; las identidades pueden intercambiar bases.

    Emparejo cada final de cadena con un comienzo mediante una base existente.
    Las reposiciones se realizan y registran en esta misma jornada.
    """
    comienzos, finales = [], []
    for cadena in cadenas:
        a, b = viajes.iloc[cadena[0]], viajes.iloc[cadena[-1]]
        starts, ends = set(), set()
        for base in red.bases:
            u, v = red.conectar(base, a.origen), red.conectar(b.destino, base)
            if a.salida_min - u["minutos"] - (regulacion if u["minutos"] else 0) >= inicio - 1e-8:starts.add(base)
            if b.llegada_min + v["minutos"] + (regulacion if v["minutos"] else 0) <= fin + 1e-8:ends.add(base)
        comienzos.append(starts);finales.append(ends)
    adj = [[j for j, a in enumerate(comienzos) if a & b] for b in finales]
    match, _ = emparejamiento_maximo(adj, len(cadenas))
    if any(j < 0 for j in match):return None
    iniciales, finales_base = [None] * len(cadenas), [None] * len(cadenas)
    for i, j in enumerate(match):
        end, start = viajes.iloc[cadenas[i][-1]], viajes.iloc[cadenas[j][0]]
        base = min(finales[i] & comienzos[j], key=lambda b: (
            red.conectar(end.destino, b)["km"] + red.conectar(b, start.origen)["km"], b))
        finales_base[i] = base;iniciales[j] = base
    if Counter(iniciales) != Counter(finales_base):raise ValueError("No cierra el inventario por base.")
    return iniciales, finales_base


def materializar(viajes, cadenas, bases, red, *, regulacion=10., bases_finales=None):
    """Registro desplazamientos y cierre del inventario conjunto por base."""
    filas = []
    def vacio(unidad, origen, destino, salida, clase, continua=False):
        path = red.conectar(origen, destino)
        if path["minutos"] <= 1e-10:return
        filas.append({"unidad_fisica_id": unidad, "id_salida": f"{unidad}_vacio_{len(filas):04d}",
            "servicio": "Reposición", "familia": "Vacío", "origen": origen, "destino": destino,
            "salida_min": salida, "llegada_min": salida + path["minutos"], "km": path["km"],
            "componente": clase, "regulacion_tras_min": 0. if continua else regulacion,
            "arcos_red": ";".join(a + ">" + b for a, b in path["arcos"])})
    bases_finales = bases if bases_finales is None else bases_finales
    for k, (cadena, base, final) in enumerate(zip(cadenas, bases, bases_finales)):
        unidad = f"TF{k+1:02d}";first = viajes.iloc[cadena[0]];path = red.conectar(base, first.origen)
        vacio(unidad, base, first.origen, first.salida_min - path["minutos"] - regulacion, "reposicion_inicial")
        last = None
        for ordinal, i in enumerate(cadena):
            row = viajes.iloc[i].to_dict()
            sigue = last is not None and continuidad_original(last, row, red)
            if last is not None:vacio(unidad, last["destino"], row["origen"], last["llegada_min"] + (0. if sigue else regulacion), "continuidad_sin_pasajeros" if sigue else "reposicion_entre_servicios", sigue)
            continua = ordinal + 1 < len(cadena) and continuidad_original(row, viajes.iloc[cadena[ordinal+1]].to_dict(), red)
            filas.append({**row, "unidad_fisica_id": unidad, "componente": "comercial",
                          "regulacion_tras_min": 0. if continua else regulacion, "arcos_red": ""});last = row
        vacio(unidad, last["destino"], final, last["llegada_min"] + regulacion, "reposicion_cierre")
    return pd.DataFrame(filas).sort_values(["unidad_fisica_id", "salida_min", "id_salida"]).reset_index(drop=True)
