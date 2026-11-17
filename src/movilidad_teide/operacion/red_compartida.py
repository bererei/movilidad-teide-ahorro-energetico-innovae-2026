"""Conecto únicamente los accesos y el eje interior ya trazados en el estudio."""
import math

import numpy as np


class RedOperativa:
    """Tiempos dirigidos conservados y parciales proporcionales al eje existente.

    La red no busca carreteras nuevas. Sus caminos son secuencias de los cinco
    recorridos del modelo; no conectores rectos ni autorizaciones de maniobra.
    """
    def __init__(self, movimientos, pares, paradas):
        destinos = pares[["punto", "parada_entrada", "parada_destino"]].drop_duplicates()
        if destinos.punto.duplicated().any():
            raise ValueError("Cada acceso debe tener una cadena interior conservada.")
        self.destinos = destinos.set_index("punto")
        self.puntos = sorted(destinos.punto)
        s = paradas.sort_values("orden")
        self.posiciones = s.set_index("parada_id").posicion_m.to_dict()
        extremos = [s.iloc[0].parada_id, s.iloc[-1].parada_id]
        self.extremos = extremos
        seleccion = sorted(set(extremos) | set(destinos.parada_destino), key=self.posiciones.get)
        self.bases = ["cabecera:" + q for q in self.puntos] + extremos
        self.nodos = self.bases[:4] + seleccion
        self.arcos = {}
        for q in self.puntos:
            entrada = self.destinos.loc[q, "parada_entrada"]
            for sentido, a, b in [("ida", "cabecera:" + q, entrada), ("vuelta", entrada, "cabecera:" + q)]:
                g = movimientos.loc[movimientos.punto.eq(q) & movimientos.sentido.eq(sentido)]
                if g.tiempo_recorrido_min.nunique() != 1 or g.km_por_recorrido.nunique() != 1:
                    raise ValueError("Tiempos o distancias de acceso ambiguos.")
                self.arcos[a, b] = (float(g.tiempo_recorrido_min.iloc[0]), float(g.km_por_recorrido.iloc[0]))
        longitud = self.posiciones[extremos[-1]] - self.posiciones[extremos[0]]
        for a, b in zip(seleccion[:-1], seleccion[1:]):
            f = (self.posiciones[b] - self.posiciones[a]) / longitud
            for sentido, origen, destino in [("ida", a, b), ("vuelta", b, a)]:
                g = movimientos.loc[movimientos.punto.eq("INTERIOR") & movimientos.sentido.eq(sentido)]
                if g.tiempo_recorrido_min.nunique() != 1 or g.km_por_recorrido.nunique() != 1:
                    raise ValueError("Tiempos o distancias interiores ambiguos.")
                self.arcos[origen, destino] = (f * float(g.tiempo_recorrido_min.iloc[0]), f * float(g.km_por_recorrido.iloc[0]))
        if any(not np.isfinite(v).all() or min(v) <= 0 for v in self.arcos.values()):
            raise ValueError("Un tramo operativo carece de tiempo o distancia positiva.")
        self.caminos = {}
        for origen in self.nodos:
            distancia = {q: math.inf for q in self.nodos};distancia[origen] = 0.;camino = {origen: []};pendientes = set(self.nodos)
            while pendientes:
                a = min(pendientes, key=lambda q: (distancia[q], q));pendientes.remove(a)
                for (u, v), (tiempo, km) in self.arcos.items():
                    if u == a and distancia[a] + tiempo < distancia[v] - 1e-10:
                        distancia[v] = distancia[a] + tiempo;camino[v] = camino[a] + [(u, v)]
            for destino in self.nodos:
                arcos = camino[destino]
                self.caminos[origen, destino] = {"minutos": sum(self.arcos[e][0] for e in arcos),
                    "km": sum(self.arcos[e][1] for e in arcos), "arcos": arcos}

    def conectar(self, origen, destino):
        return self.caminos[origen, destino]
