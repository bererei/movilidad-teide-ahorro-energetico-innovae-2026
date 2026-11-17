"""Compruebo un inventario común por bases para circulaciones ya construidas."""
from collections import deque, Counter
import math


def bases_posibles(viajes, cadenas, red, *, inicio=420., fin=1200., regulacion=10.):
    starts, ends = [], []
    for c in cadenas:
        a, b = viajes.iloc[c[0]], viajes.iloc[c[-1]];ss, ee = set(), set()
        for base in red.bases:
            u, v = red.conectar(base, a.origen)["minutos"], red.conectar(b.destino, base)["minutos"]
            if a.salida_min - u - (regulacion if u else 0) >= inicio - 1e-8:ss.add(base)
            if b.llegada_min + v + (regulacion if v else 0) <= fin + 1e-8:ee.add(base)
        starts.append(ss);ends.append(ee)
    return starts, ends


def asignar_bases(starts, ends, bases, capacidades):
    """Flujo entero: cada final y comienzo pasa por una plaza de una base.

    La capacidad común limita los vehículos iniciales y finales por base. Si
    falla, el corte mínimo aporta una condición necesaria sobre capacidades.
    """
    n, m = len(starts), len(bases);sink = 2*n + 2*m + 1;graph = [[] for _ in range(sink+1)]
    if len(ends) != n or len(set(bases)) != m or set(capacidades) != set(bases):
        raise ValueError("Inventario o cadenas incompatibles.")
    if any(isinstance(x, bool) or not math.isfinite(x) or x < 0 or int(x) != x for x in capacidades.values()):
        raise ValueError("Las capacidades deben ser enteros no negativos.")
    def edge(a, b, cap):
        f = [b, len(graph[b]), cap];r = [a, len(graph[a]), 0]
        graph[a].append(f);graph[b].append(r);return f
    end_edges, start_edges = {}, {}
    for i in range(n):
        edge(0, 1+i, 1);edge(1+n+2*m+i, sink, 1)
        for k, base in enumerate(bases):
            if base in ends[i]:end_edges[i,k] = edge(1+i, 1+n+k, n)
            if base in starts[i]:start_edges[i,k] = edge(1+n+m+k, 1+n+2*m+i, n)
    for k, base in enumerate(bases):edge(1+n+k, 1+n+m+k, capacidades[base])
    flow = 0
    while True:
        prev = [None] * len(graph);prev[0] = (-1,-1);queue = deque([0])
        while queue and prev[sink] is None:
            a = queue.popleft()
            for j, e in enumerate(graph[a]):
                if e[2] > 0 and prev[e[0]] is None:prev[e[0]] = (a,j);queue.append(e[0])
        if prev[sink] is None:break
        b = sink
        while b:
            a,j = prev[b];e = graph[a][j];e[2] -= 1;graph[b][e[1]][2] += 1;b = a
        flow += 1
    if flow == n:
        aa, bb = [None]*n, [None]*n
        for (i,k), e in start_edges.items():
            if e[2] < n:aa[i] = bases[k]
        for (i,k), e in end_edges.items():
            if e[2] < n:bb[i] = bases[k]
        if Counter(aa) != Counter(bb) or None in aa+bb:raise ValueError("El flujo no equilibra las bases.")
        return (aa, bb), None
    reachable = {0};queue = deque([0])
    while queue:
        a = queue.popleft()
        for b, _, cap in graph[a]:
            if cap > 0 and b not in reachable:reachable.add(b);queue.append(b)
    subset = frozenset(base for k,base in enumerate(bases) if 1+n+k in reachable and 1+n+m+k not in reachable)
    return None, (subset, n-flow+sum(capacidades[b] for b in subset))

