"""Enumero los mismos estados de expediciones sin recorrer cada coche individual."""
from itertools import product
import math


def estados_por_intervalos(bruto, minimos, maximos, *, cupo, ocupacion, capacidad):
    """Para cada vector de viajes conservo su primera cuota lexicográfica.

    Cada número de expediciones corresponde a un intervalo entero de cuotas.
    La suma de cuatro intervalos contiene el cupo si y solo si sus límites lo
    contienen. La construcción elige el mismo primer reparto de la enumeración
    histórica, sin modificar la demanda o la capacidad.
    """
    opciones = []
    for cantidad, lo, hi in zip(bruto, minimos, maximos):
        estados = {}
        for q in range(lo, min(hi, cupo) + 1):
            n = math.ceil((cantidad - q * ocupacion - 1e-8) / capacidad)
            if n not in estados:estados[n] = [q, q]
            else:estados[n][1] = q
        opciones.append(sorted(estados.items()))
    resultado = []
    for combo in product(*opciones):
        bajo, alto = [p[1][0] for p in combo], [p[1][1] for p in combo]
        if sum(bajo) > cupo or sum(alto) < cupo:continue
        q = [];resto = cupo
        for k in range(len(combo)):
            valor = max(bajo[k], resto - sum(alto[k+1:]));q.append(valor);resto -= valor
        if resto or any(x > h for x, h in zip(q, alto)):raise ValueError("Estado de cuota inconsistente.")
        resultado.append(tuple(q))
    return resultado
