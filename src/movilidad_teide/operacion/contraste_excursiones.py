"""Exijo los ocho perfiles además del p85 en la búsqueda de cuotas y reloj."""
import heapq
import numpy as np
from .equilibrio_invierno import BuscadorEquilibrado
from .reloj_integrado import RelojIntegrado
from .refinar_reservas import FORMAS
from movilidad_teide.demanda.excursiones_acotadas import reasignar_con_maximos


class BuscadorConMuestra(BuscadorEquilibrado):
    """Reutilizo la búsqueda D247 y compruebo los demás perfiles antes de aceptar.

    Los dos perfiles críticos y el p85 forman el catálogo de estados. Una
    cuota solo se acepta si también se construyen los otros seis cierres.
    Las negativas de la búsqueda acotada nunca prueban imposibilidad global.
    """
    def _estado(self, obs, g, q, red, v, lim):
        pt = g.copy()
        pt['demanda_lanzadera_dia'] = pt.demanda_bruta_lanzadera_dia - pt.punto.map(q) * v['ocupacion_coche']
        reloj = self._reloj(pt, red, v, q, lim)
        key = (self.contexto, int(obs), tuple(map(int, reloj.n)), tuple(map(float, reloj.cierres)),
               float(reloj.inicio), float(reloj.estancia), float(v['regulacion_min']))
        if getattr(self, 'max_programadas', 27) != 27:
            key = (*key, ('max_programadas', self.max_programadas))
        hit = key in self.cache
        if not hit:
            # Cada clave provisional es <= su clave exacta. La cola devuelve
            # las dos mismas semillas que evaluar todo el catálogo ordenado.
            seeds, seen = [], set()
            limits = dict(zip(lim.punto, lim.ultimo_paso_regreso_parque_min))
            for ordinary in [15, 30]:
                op = {**reloj.v, 'intervalo_minimo_subidas_min': ordinary}
                clock = RelojIntegrado(pt, red, op, q, limites_regreso_por_punto=limits, admitir_accesos_sin_demanda=True)
                for forma, alpha in sorted(FORMAS):
                    u, b = clock.inicial(forma, alpha)
                    fingerprint = tuple(np.concatenate(u+b))
                    if fingerprint in seen:
                        continue
                    seen.add(fingerprint)
                    reloj.validar(u, b)
                    bound, edges = reloj.cota_inicial(u, b)
                    seeds.append(((bound, -edges, forma+f'_{ordinary}', alpha), u, b))
            heap = [(score, False, i) for i, (score, _, _) in enumerate(seeds)]
            heapq.heapify(heap)
            exact, first = {}, []
            while heap and len(first) < 2:
                score, confirmed, i = heapq.heappop(heap)
                if not confirmed:
                    n, e = reloj.evaluar(seeds[i][1], seeds[i][2])
                    if n < score[0]:
                        raise ValueError('La cota de simultaneidad supera las cadenas exactas.')
                    value = (n, -e, score[2], score[3])
                    exact[i] = value
                    heapq.heappush(heap, (value, True, i))
                else:
                    first.append(i)
            limite = getattr(self, 'max_programadas', 27)
            if exact[first[0]][0] <= limite:
                # Conservo todas las semillas que pueden cerrar con bases.
                for i, (score, u, b) in enumerate(seeds):
                    if i not in exact:
                        n, e = reloj.evaluar(u, b)
                        exact[i] = (n, -e, score[2], score[3])
                chosen = sorted(exact, key=lambda i: exact[i])
            else:
                # Las demás superan el límite y no pueden producir un cierre.
                chosen = first
            curves = [(exact[i], seeds[i][1], seeds[i][2]) for i in chosen]
            self.cache[key] = {'semillas': curves, 'curvas': list(curves), 'version': 0,
                               'cierre_version': -1, 'cerrado': None, 'refinado': False}
        return key, reloj, self.cache[key], hit

    def configurar(self, origenes, puntos, limites, incremento):
        self.origenes = origenes
        self.puntos_muestra = puntos
        self.limites_muestra = limites
        self.incremento = incremento
        self.otros = {}

    def comprobar_otros(self, cuotas, red, valores, capacidades, identidades):
        firma = tuple(sorted(cuotas.items()))
        if firma not in self.otros:
            results = {}
            for obs in sorted(set(self.puntos_muestra) - {6, 22}):
                z = reasignar_con_maximos(self.origenes[obs], self.puntos_muestra[obs], cuotas,
                                         incremento=self.incremento, ocupacion=valores['ocupacion_coche'])
                pt = z['escenarios_por_punto_dia'].copy()
                # El reloj resta la cuota máxima; repongo el saldo efectivo.
                pt['demanda_bruta_lanzadera_dia'] = pt.demanda_lanzadera_dia + pt.punto.map(cuotas) * valores['ocupacion_coche']
                key, reloj, state, _ = self._estado(obs, pt, cuotas, red, valores, self.limites_muestra[obs])
                results[obs] = super()._cerrar(key, reloj, state, red, valores, capacidades, identidades)
            self.otros[firma] = results
        return self.otros[firma]

    def _cerrar(self, key, reloj, state, red, valores, capacidades, identidades):
        z = super()._cerrar(key, reloj, state, red, valores, capacidades, identidades)
        if z is not None and key[1] == 85 and getattr(self, 'exigir_muestra', True):
            otros = self.comprobar_otros(reloj.cuotas, red, valores, capacidades, identidades)
            if not all(answer is not None for answer in otros.values()):
                return None
        return z
