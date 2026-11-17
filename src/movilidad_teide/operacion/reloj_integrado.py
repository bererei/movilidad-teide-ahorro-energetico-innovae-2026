"""Reservas directas con subidas y regresos ajustables dentro de sus ventanas."""
import math

import numpy as np

from .circulacion_compartida import emparejamiento_maximo
from .horarios_compartidos import construir_reservas


class RelojIntegrado:
    """Represento los mismos viajeros y trayectos; solo ajusto sus horas.

    La matriz de enlaces conserva tiempos de reposición y ambas regulaciones.
    El mínimo de cadenas es exacto para cada reloj, no entre todos los relojes.
    """
    def __init__(self, objetivos, red, valores, cuotas, *, limites_regreso_por_punto=None,
                 admitir_accesos_sin_demanda=False):
        self.red, self.v, self.cuotas = red, valores, dict(cuotas)
        self.g = objetivos.set_index("punto").loc[red.puntos].reset_index().copy()
        bruto = (self.g.demanda_bruta_lanzadera_dia if "demanda_bruta_lanzadera_dia" in self.g
                 else self.g.visitas_coche + self.g.visitas_titsa + self.g.visitas_excursiones_transferidas_dia)
        self.g["demanda_lanzadera_dia"] = bruto.to_numpy() - np.array([cuotas[q] for q in red.puntos]) * valores["ocupacion_coche"]
        cap = int(valores["plazas_guagua"] * valores["ocupacion_diseno"])
        no_fisica = (self.g.demanda_lanzadera_dia.lt(0) if admitir_accesos_sin_demanda
                     else self.g.demanda_lanzadera_dia.le(0))
        if not np.isfinite(self.g.demanda_lanzadera_dia).all() or no_fisica.any():
            raise ValueError("El contraste requiere demanda positiva en los cuatro accesos.")
        self.n = np.ceil((self.g.demanda_lanzadera_dia.to_numpy() - 1e-8) / cap).astype(int)
        if not self.n.any():raise ValueError("No hay expediciones que programar.")
        heads = ["cabecera:" + q for q in red.puntos]
        entries = [red.destinos.loc[q, "parada_entrada"] for q in red.puntos]
        zones = [red.destinos.loc[q, "parada_destino"] for q in red.puntos]
        self.a = np.array([red.conectar(x, y)["minutos"] for x, y in zip(heads, entries)])
        self.b = np.array([red.conectar(y, x)["minutos"] for x, y in zip(heads, entries)])
        self.d = np.array([red.conectar(x, y)["minutos"] for x, y in zip(entries, zones)])
        self.inicio = 60 * valores["hora_inicio_acceso"]
        self.cierre = 60 * valores["hora_limite_bajada_parque"]
        # Los límites se expresan en minutos de paso por la entrada del Parque.
        # En invierno, un descenso más largo obliga a regresar antes por aquí.
        if limites_regreso_por_punto is None:
            self.cierres = np.full(len(red.puntos), self.cierre)
        else:
            if (set(limites_regreso_por_punto) != set(red.puntos)
                or not np.isfinite(list(limites_regreso_por_punto.values())).all()
                or any(not self.inicio < x <= self.cierre + 1e-8 for x in limites_regreso_por_punto.values())):
                raise ValueError("Límites de regreso por acceso incompatibles con la ventana.")
            self.cierres = np.array([limites_regreso_por_punto[q] for q in red.puntos],dtype=float)
        self.estancia = valores["estancia_min_visita_min"]
        self.last = self.cierres - self.estancia - self.a
        self.intervalo = valores["intervalo_refuerzo_punta_min"]
        ordinario = valores["intervalo_minimo_subidas_min"]
        self.gap = np.array([ordinario if nn <= math.floor((last - self.inicio) / ordinario) + 1
                             else self.intervalo for nn, last in zip(self.n, self.last)])
        self.slack = self.last - self.inicio - (self.n - 1) * self.gap
        if (self.slack < -1e-8).any():raise ValueError("El cupo no satisface el intervalo de acceso.")
        origins, destinations, durations = [], [], []
        for k, nn in enumerate(self.n):
            origins += [heads[k]] * nn + [zones[k]] * nn
            destinations += [zones[k]] * nn + [heads[k]] * nn
            durations += [self.a[k] + self.d[k]] * nn + [self.b[k] + self.d[k]] * nn
        self.duraciones = np.array(durations)
        tr = np.array([[red.conectar(x, y)["minutos"] for y in red.nodos] for x in red.nodos])
        ix = {p: i for i, p in enumerate(red.nodos)}
        transfer = tr[np.array([ix[p] for p in destinations])[:, None], np.array([ix[p] for p in origins])[None, :]]
        reg = valores["regulacion_min"]
        self.necesita = self.duraciones[:, None] + transfer + reg + (transfer > 1e-10) * reg

    def inicial(self, forma="lineal", fraccion_regreso=0.):
        """Combino relojes tempranos, extendidos, tardíos o con pausa central."""
        us, bs = [], []
        for k, nn in enumerate(self.n):
            if nn == 0:
                us.append(np.array([]));bs.append(np.array([]));continue
            x = np.linspace(0, 1, nn)
            curvas = {"lineal": x, "temprana": np.zeros(nn), "tardia": np.ones(nn), "pausa": (x >= .5).astype(float)}
            if forma not in curvas or not 0 <= fraccion_regreso <= 1:raise ValueError("Forma horaria inválida.")
            u = self.inicio + np.arange(nn) * self.gap[k] + max(0., self.slack[k]) * curvas[forma]
            low = u + self.a[k] + self.estancia
            high = self.cierres[k] - np.arange(nn - 1, -1, -1) * self.intervalo
            us.append(u);bs.append(low + fraccion_regreso * (high - low))
        self.validar(us, bs)
        return us, bs

    def validar(self, us, bs):
        for k, nn in enumerate(self.n):
            u, b = us[k], bs[k]
            if nn == 0:
                if len(u) or len(b):raise ValueError("Un acceso sin demanda no tiene expediciones.")
                continue
            if (len(u) != nn or len(b) != nn or not np.isfinite([u, b]).all()
                or u[0] < self.inicio - 1e-8 or u[-1] > self.last[k] + 1e-8
                or (np.diff(u) < self.gap[k] - 1e-8).any() or (np.diff(b) < self.intervalo - 1e-8).any()
                or (b - u - self.a[k] < self.estancia - 1e-8).any() or b[-1] > self.cierres[k] + 1e-8):
                raise ValueError("El reloj incumple intervalo, ventana o estancia.")

    def salidas(self, us, bs):
        return np.concatenate([t for k in range(len(self.n)) for t in [us[k], bs[k] - self.d[k]]])

    def evaluar(self, us, bs):
        t = self.salidas(us, bs)
        enlaces = t[:, None] + self.necesita <= t[None, :] + 1e-8
        adj = [np.flatnonzero(f).tolist() for f in enlaces]
        match, _ = emparejamiento_maximo(adj, len(t))
        return len(t) - sum(j >= 0 for j in match), int(enlaces.sum())

    def cota_inicial(self, us, bs):
        """Cota inferior de cadenas y número exacto de enlaces, sin emparejar.

        Desplazo los comienzos 1e-8 min al contar solapes para que el redondeo
        nunca haga más estricta esta cota que la tolerancia del encadenador.
        """
        t = self.salidas(us, bs)
        ends = t + self.duraciones + self.v["regulacion_min"]
        values = np.r_[t + 1e-8, ends];changes = np.r_[np.ones(len(t), dtype=int), -np.ones(len(t), dtype=int)]
        order = np.lexsort((changes, values))
        bound = int(np.cumsum(changes[order]).max())
        edges = int((t[:, None] + self.necesita <= t[None, :] + 1e-8).sum())
        return bound, edges

    def modificar(self, us, bs, rng):
        """Muevo una salida o un bloque; conservo sus límites físicos."""
        u, b = [x.copy() for x in us], [x.copy() for x in bs]
        k = int(rng.integers(len(self.n)))
        if self.n[k] == 0:k = int(rng.choice(np.flatnonzero(self.n)))
        nn = self.n[k];j = int(rng.integers(nn))
        kind = int(rng.integers(3));step = float(rng.choice([-15, -10, -5, -2, 2, 5, 10, 15]))
        if kind == 0:
            low = self.inicio if j == 0 else u[k][j-1] + self.gap[k]
            high = self.last[k] if j == nn-1 else u[k][j+1] - self.gap[k]
            u[k][j] = np.clip(u[k][j] + step, low, high)
            b[k][j] = max(b[k][j], u[k][j] + self.a[k] + self.estancia)
        elif kind == 1:
            low = max(u[k][j] + self.a[k] + self.estancia, b[k][j-1] + self.intervalo if j else -np.inf)
            high = b[k][j+1] - self.intervalo if j < nn-1 else self.cierres[k]
            b[k][j] = np.clip(b[k][j] + step, low, high)
        else:
            lo, hi = sorted((j, int(rng.integers(nn))))
            low = max(np.max(u[k][lo:hi+1] + self.a[k] + self.estancia - b[k][lo:hi+1]),
                      b[k][lo-1] + self.intervalo - b[k][lo] if lo else -np.inf)
            high = b[k][hi+1] - self.intervalo - b[k][hi] if hi < nn-1 else self.cierres[k] - b[k][hi]
            b[k][lo:hi+1] += np.clip(step, low, high)
        try:self.validar(u, b)
        except ValueError:return None
        return u, b

    def tablas(self, us, bs):
        """Actualizo el reloj del constructor común, manteniendo plazas y reservas."""
        self.validar(us, bs)
        viajes, reservas = construir_reservas(self.g, self.red, self.v, directos=True)
        viajes = viajes.set_index("id_salida")
        for k, q in enumerate(self.red.puntos):
            ids = reservas.index[reservas.punto.eq(q)]
            for i, idx in enumerate(ids):
                u, b = us[k][i], bs[k][i];row = reservas.loc[idx]
                viajes.loc[row.id_subida, ["salida_min", "llegada_min"]] = [u, u + self.a[k] + self.d[k]]
                viajes.loc[row.id_regreso, ["salida_min", "llegada_min"]] = [b - self.d[k], b + self.b[k]]
                reservas.loc[idx, ["entrada_parque_min", "regreso_parque_min", "llegada_zona_min", "salida_zona_min"]] = [u + self.a[k], b, u + self.a[k] + self.d[k], b - self.d[k]]
        return viajes.reset_index(), reservas
