"""Búsqueda acotada y reproducible de relojes; no garantiza un óptimo global."""
import math
import heapq

import numpy as np
import pandas as pd

from .horarios_compartidos import catalogo_cuotas
from .reloj_integrado import RelojIntegrado


FORMAS = (("lineal", 0.), ("lineal", .5), ("lineal", 1.), ("temprana", 0.),
          ("temprana", .5), ("tardia", 0.), ("pausa", 0.))


def semillas_por_cota(pool, crear_reloj, cantidad):
    """Obtengo el mismo orden inicial y semillas con emparejamientos diferidos.

    Cada clave provisional es inferior o igual a su clave exacta. Un candidato
    confirmado que sale primero de la cola ya no puede ser adelantado por los
    restantes. No se elimina ningún reparto por una aproximación optimista.
    """
    heap = [(row[0], False, i) for i, row in enumerate(pool)];heapq.heapify(heap)
    ordenados, elegidos, exactos = [], [], 0
    while heap:
        key, confirmado, idx = heapq.heappop(heap);row = pool[idx]
        if not confirmado:
            reloj = crear_reloj(row);u, b = reloj.inicial(key[3], key[4]);n, edges = reloj.evaluar(u, b)
            if n < key[0]:raise ValueError("La cota de simultaneidad no es inferior al encadenamiento.")
            heapq.heappush(heap, ((n, -edges, *key[2:]), True, idx));exactos += 1
            continue
        current = (key, row[1], row[2]);ordenados.append(current)
        counts = np.array(row[2])
        if not elegidos or min(np.abs(counts - np.array(p[2])).sum() for p in elegidos) >= 2:
            elegidos.append(current)
        if len(elegidos) == cantidad:break
    if len(elegidos) < cantidad:
        claves = {row[0] for row in elegidos}
        elegidos.extend(row for row in ordenados if row[0] not in claves)
        elegidos = elegidos[:cantidad]
    return ordenados[0], elegidos, exactos


def mejorar_reloj(reloj, us, bs, *, semilla, pasos):
    """Ajusto reservas individuales con presupuesto y semilla declarados.

    Minimizo primero vehículos distintos. El número de enlaces solo desempata;
    no equivale a minimizar vacíos o consumo. Admito cambios peores limitados
    para explorar otros relojes; publico siempre el mejor reloj encontrado.
    """
    rng = np.random.default_rng(semilla);score, edges = reloj.evaluar(us, bs)
    best = (score, -edges, [u.copy() for u in us], [b.copy() for b in bs]);evaluados = 0
    for i in range(pasos):
        nuevo = reloj.modificar(us, bs, rng)
        if nuevo is None:continue
        u, b = nuevo;s, e = reloj.evaluar(u, b);evaluados += 1
        if (s, -e) < best[:2]:best = (s, -e, [x.copy() for x in u], [x.copy() for x in b])
        temp = .35 * (1 - i / max(1, pasos)) + .05
        if (s < score or s == score and (e >= edges or rng.random() < .6)
            or rng.random() < .1 * math.exp(min(0., (score - s) / temp))):
            us, bs, score, edges = u, b, s, e
    return best, evaluados


def buscar_refinado(historia, red, valores, *, cupo=550, reinicios=6, pasos=1800, semilla=24000):
    """Exploro cuotas comunes y relojes flexibles del perfil más exigente."""
    if reinicios < 1 or pasos < 0:raise ValueError("Presupuesto de búsqueda inválido.")
    obs = int(historia.groupby("observacion").demanda_lanzadera_dia.sum().idxmax())
    g = historia.loc[historia.observacion.eq(obs)]
    diferido = "demanda_bruta_lanzadera_dia" in g
    pool, vistos = [], []
    for cuotas in catalogo_cuotas(historia, red, valores, cupo=cupo):
        reloj = RelojIntegrado(g, red, valores, cuotas)
        for forma, alpha in FORMAS:
            us, bs = reloj.inicial(forma, alpha)
            n, edges = reloj.cota_inicial(us, bs) if diferido else reloj.evaluar(us, bs)
            clave = (n, -edges, tuple(cuotas[q] for q in red.puntos), forma, alpha)
            pool.append((clave, cuotas, tuple(reloj.n)))
    if not pool:raise ValueError("No hay cuotas compatibles con las ventanas conservadas.")
    semillas = []
    if diferido:
        first, semillas, exactos = semillas_por_cota(pool, lambda row: RelojIntegrado(g, red, valores, row[1]), reinicios)
    else:
        pool.sort(key=lambda z: z[0]);first = pool[0];exactos = len(pool)
    clave, cuotas, _ = first
    reloj = RelojIntegrado(g, red, valores, cuotas)
    us, bs = reloj.inicial(clave[3], clave[4]);best = (clave, reloj, us, bs);inicial = clave[0]
    # Evito dedicar todos los reinicios a casi el mismo número de viajes.
    for row in ([] if diferido else pool):
        counts = np.array(row[2])
        if not semillas or min(np.abs(counts - np.array(p[2])).sum() for p in semillas) >= 2:semillas.append(row)
        if len(semillas) == reinicios:break
    if not diferido and len(semillas) < reinicios:
        usados = {id(row) for row in semillas}
        semillas.extend(row for row in pool if id(row) not in usados)
        semillas = semillas[:reinicios]
    for k, (clave, cuotas, _) in enumerate(semillas):
        reloj = RelojIntegrado(g, red, valores, cuotas)
        us, bs = reloj.inicial(clave[3], clave[4])
        out, count = mejorar_reloj(reloj, us, bs, semilla=semilla + k, pasos=pasos)
        n, ne, u, b = out
        candidate = ((n, ne, clave[2], "ajuste_individual", float(k)), reloj, u, b)
        if candidate[0] < best[0]:best = candidate
        vistos.append({"reinicio": k, "semilla": semilla + k, "pasos_previstos": pasos,
                       "relojes_validos_evaluados": count, "cadenas_inicio": clave[0], "mejores_cadenas": n})
    clave, reloj, us, bs = best
    viajes, reservas = reloj.tablas(us, bs)
    return {"observacion": obs, "viajes": viajes, "reservas": reservas, "cuotas": reloj.cuotas,
            "cadenas": clave[0], "cadenas_mejor_catalogo_inicial": inicial,
            "relojes_iniciales": len(pool), "reinicios": pd.DataFrame(vistos),
            "encadenamientos_iniciales_evaluados_exactamente": exactos,
            "minimo_global_demostrado": False}


def refinar_perfil(objetivos, red, valores, cuotas, *, pasos=300, semilla=25000):
    """Compruebo otro perfil con las mismas cuotas locales, sin reoptimizarlas."""
    reloj = RelojIntegrado(objetivos, red, valores, cuotas);pool = []
    for forma, alpha in FORMAS:
        u, b = reloj.inicial(forma, alpha);n, e = reloj.evaluar(u, b)
        pool.append((n, -e, forma, alpha, u, b))
    pool.sort(key=lambda z: z[:4]);best = pool[0];logs = []
    for k, row in enumerate(pool[:2]):
        n, ne, u, b = mejorar_reloj(reloj, row[4], row[5], semilla=semilla+k, pasos=pasos)[0]
        candidate = (n, ne, "ajuste_individual", float(k), u, b)
        if candidate[:4] < best[:4]:best = candidate
        logs.append({"reinicio": k, "semilla": semilla+k, "pasos_previstos": pasos,
                     "cadenas_inicio": row[0], "mejores_cadenas": n})
    viajes, reservas = reloj.tablas(best[4], best[5])
    return {"viajes": viajes, "reservas": reservas, "cuotas": cuotas, "cadenas": best[0],
            "cadenas_mejor_catalogo_inicial": pool[0][0], "relojes_iniciales": len(pool),
            "reinicios": pd.DataFrame(logs), "minimo_global_demostrado": False}
