"""Ensayos acotados de reservas, sin alterar demanda, asientos o tiempos fuente."""
from itertools import product
import math

import numpy as np
import pandas as pd

from .circulacion_compartida import encadenar_viajes, cerrar_bases, materializar


def construir_reservas(objetivos, red, valores, *, directos, forma_laguna="lineal",
                        forma_vilaflor="lineal", escala_regreso=1., grupo_refuerzo=1):
    """Programo las mismas visitas con transbordo o continuidad en el mismo bus.

    En el servicio directo, la entrada del Parque es un paso intermedio:
    regulación de diez minutos en los extremos reales, sin transbordo en ella.
    El mínimo de visita se sigue contando entre entrada y regreso en el Parque.
    """
    if isinstance(grupo_refuerzo, (bool, np.bool_)) or grupo_refuerzo != 1:
        raise ValueError("Se mantiene un vehículo por salida y quince minutos entre vehículos.")
    if not np.isfinite(escala_regreso) or escala_regreso <= 0:
        raise ValueError("La forma de los regresos necesita escala positiva.")
    if (objetivos.punto.duplicated().any() or set(objetivos.punto) != set(red.puntos)
            or not np.isfinite(objetivos.demanda_lanzadera_dia).all() or objetivos.demanda_lanzadera_dia.lt(0).any()):
        raise ValueError("Objetivos repetidos o demanda no física.")
    cap = int(valores["plazas_guagua"] * valores["ocupacion_diseno"])
    inicio = 60 * valores["hora_inicio_acceso"];cierre = 60 * valores["hora_limite_bajada_parque"]
    estancia, margen = valores["estancia_min_visita_min"], valores["margen_enlace_interior_min"]
    filas, cadenas = [], []
    for row in objetivos.itertuples():
        q = row.punto;cantidad = float(row.demanda_lanzadera_dia)
        n = math.ceil((cantidad - 1e-8) / cap)
        if n <= 0:continue
        entrada, destino = red.destinos.loc[q, ["parada_entrada", "parada_destino"]]
        a = red.conectar("cabecera:" + q, entrada)["minutos"]
        b = red.conectar(entrada, "cabecera:" + q)["minutos"]
        d = red.conectar(entrada, destino)["minutos"]
        last = cierre - estancia - a
        n30 = math.floor((last - inicio) / valores["intervalo_minimo_subidas_min"]) + 1
        refuerzo = n > n30
        por_salida = grupo_refuerzo if refuerzo else 1
        slots = math.ceil(n / por_salida)
        gap = valores["intervalo_refuerzo_punta_min"] if refuerzo else valores["intervalo_minimo_subidas_min"]
        slack = last - inicio - (slots - 1) * gap
        if slack < -1e-8:return None
        x = np.linspace(0, 1, slots)
        forma = forma_laguna if q == "LAGUNA" else forma_vilaflor if q == "VILAFLOR" else "lineal"
        curva = x if forma == "lineal" else (x >= float(forma)).astype(float)
        tiempos = inicio + np.arange(slots) * gap + max(0., slack) * curva
        subidas = np.repeat(tiempos, por_salida)[:n]
        bajadas = np.maximum(subidas + a + estancia, cierre - escala_regreso * (last - subidas))
        if len(bajadas) > 1 and np.min(np.diff(bajadas)) < valores["intervalo_refuerzo_punta_min"] - 1e-8:
            return None
        for i, (u, r) in enumerate(zip(subidas, bajadas)):
            ident = f"{q}_{i:03d}";personas = cantidad / n
            km_antes = red.conectar("cabecera:" + q, entrada)["km"]
            km_despues = red.conectar(entrada, "cabecera:" + q)["km"]
            km_in = red.conectar(entrada, destino)["km"]
            if directos:
                legs = [("ida", "Integrado", q, "cabecera:" + q, destino, u, u + a + d, km_antes + km_in),
                        ("vuelta", "Integrado", q, destino, "cabecera:" + q, r - d, r + b, km_in + km_despues)]
                interior_out, interior_back = ident + "_ida", ident + "_vuelta"
                llega_zona, sale_zona = u + a + d, r - d
            else:
                servicio = "INTERIOR_SUR" if entrada == red.extremos[0] else "INTERIOR_NORTE"
                legs = [("ida", "Acceso", q, "cabecera:" + q, entrada, u, u + a, km_antes),
                        ("interior_ida", "Interior", servicio, entrada, destino, u + a + margen, u + a + margen + d, km_in),
                        ("interior_vuelta", "Interior", servicio, destino, entrada, r - margen - d, r - margen, km_in),
                        ("vuelta", "Acceso", q, entrada, "cabecera:" + q, r, r + b, km_despues)]
                interior_out, interior_back = ident + "_interior_ida", ident + "_interior_vuelta"
                llega_zona, sale_zona = u + a + margen + d, r - margen - d
            if r - (u + a) < estancia - 1e-8 or sale_zona < llega_zona - 1e-8:
                raise ValueError("La visita pierde su estancia mínima o su regreso.")
            for tag, family, service, origen, dest, start, end, dist in legs:
                filas.append({"id_salida": ident + "_" + tag, "familia": family, "servicio": service,
                    "origen": origen, "destino": dest, "salida_min": float(start), "llegada_min": float(end),
                    "km": dist, "personas": personas, "punto_visita": q})
            cadenas.append({"id_visita_grupo": ident, "punto": q, "personas": personas,
                "id_subida": ident + "_ida", "id_regreso": ident + "_vuelta",
                "id_interior_ida": interior_out, "id_interior_regreso": interior_back,
                "entrada_parque_min": u + a, "regreso_parque_min": r,
                "llegada_zona_min": llega_zona, "salida_zona_min": sale_zona,
                "sin_transbordo": directos, "parada_destino": destino})
    return pd.DataFrame(filas), pd.DataFrame(cadenas)


def concurrencia(viajes, regulacion):
    """Cota exacta de simultaneidad del reloj; no disponibilidad geográfica."""
    eventos = [(r.salida_min, 1) for r in viajes.itertuples()]
    eventos += [(r.llegada_min + regulacion, -1) for r in viajes.itertuples()]
    actual = mayor = 0
    for _, cambio in sorted(eventos):actual += cambio;mayor = max(mayor, actual)
    return mayor


def catalogo_cuotas(historia, red, valores, *, cupo, grupo_refuerzo=1):
    """Conservo un cupo local común a los nueve perfiles y todos los orígenes.

    Enumero los estados distintos de número de viajes que permiten las cuotas
    enteras. Dentro del mismo estado conservo el primer reparto determinista.
    """
    puntos = red.puntos;cap = int(valores["plazas_guagua"] * valores["ocupacion_diseno"])
    inicio, cierre = 60 * valores["hora_inicio_acceso"], 60 * valores["hora_limite_bajada_parque"]
    minimos, maximos = [], []
    for q in puntos:
        g = historia.loc[historia.punto.eq(q)]
        a = red.conectar("cabecera:" + q, red.destinos.loc[q, "parada_entrada"])["minutos"]
        slots = math.floor((cierre - valores["estancia_min_visita_min"] - a - inicio) / valores["intervalo_refuerzo_punta_min"]) + 1
        bruto = (g.demanda_bruta_lanzadera_dia if "demanda_bruta_lanzadera_dia" in g
                 else g.visitas_coche + g.visitas_excursiones_transferidas_dia + g.visitas_titsa)
        minimos.append(max(0, math.ceil((float(bruto.max()) - slots * grupo_refuerzo * cap) / valores["ocupacion_coche"] - 1e-10)))
        disponibles = g.coches_maximos_para_cupo_dia if "coches_maximos_para_cupo_dia" in g else g.coches_sin_dia
        maximos.append(math.floor(float(disponibles.min())))
    room = int(cupo - sum(minimos))
    if room < 0 or any(a > b for a, b in zip(minimos, maximos)):return []
    critico = historia.groupby("observacion").demanda_lanzadera_dia.sum().idxmax()
    g = historia.loc[historia.observacion.eq(critico)].set_index("punto").loc[puntos]
    bruto = (g.demanda_bruta_lanzadera_dia if "demanda_bruta_lanzadera_dia" in g
             else g.visitas_coche + g.visitas_excursiones_transferidas_dia + g.visitas_titsa).to_numpy()
    if "demanda_bruta_lanzadera_dia" in g:
        from .cuotas_por_intervalos import estados_por_intervalos
        return [dict(zip(puntos, q)) for q in estados_por_intervalos(bruto, minimos, maximos,
            cupo=cupo, ocupacion=valores["ocupacion_coche"], capacidad=cap)]
    # Solo cambia el reloj al cruzar un umbral de plazas. La tabla por origen
    # no se modifica al reducir el catálogo de repartos equivalentes en tiempo.
    estados = {}
    for a in range(room + 1):
        for b in range(room - a + 1):
            for c in range(room - a - b + 1):
                q = tuple(v + e for v, e in zip(minimos, (a, b, c, room - a - b - c)))
                if any(x > y for x, y in zip(q, maximos)):continue
                n = tuple(np.ceil((bruto - np.array(q) * valores["ocupacion_coche"] - 1e-8) / cap).astype(int))
                estados.setdefault(n, q)
    return [dict(zip(puntos, q)) for _, q in sorted(estados.items())]


def buscar_horario(historia, red, valores, *, cupo, directos, grupo_refuerzo=1):
    """Búsqueda declarada de cuotas y fases; no mínimo global de horarios."""
    critico = historia.groupby("observacion").demanda_lanzadera_dia.sum().idxmax()
    g0 = historia.loc[historia.observacion.eq(critico)].set_index("punto").loc[red.puntos].reset_index()
    antes = (g0.demanda_bruta_lanzadera_dia if "demanda_bruta_lanzadera_dia" in g0
             else g0.visitas_coche + g0.visitas_excursiones_transferidas_dia + g0.visitas_titsa)
    cuotas = catalogo_cuotas(historia, red, valores, cupo=cupo, grupo_refuerzo=grupo_refuerzo)
    best = None;testigo = None;min_concurrencia = None;intentos = [];candidatos = 0
    for q in cuotas:
        g = g0.copy();g["demanda_lanzadera_dia"] = antes.to_numpy() - np.array([q[k] for k in red.puntos]) * valores["ocupacion_coche"]
        for f1, f2, escala in product(["lineal", .5], ["lineal", .5], [.8, 1., 1.2]):
            propuesta = construir_reservas(g, red, valores, directos=directos,
                forma_laguna=f1, forma_vilaflor=f2, escala_regreso=escala, grupo_refuerzo=grupo_refuerzo)
            if propuesta is None:continue
            t, reservas = propuesta;candidatos += 1
            conc = concurrencia(t, valores["regulacion_min"])
            min_concurrencia = conc if min_concurrencia is None else min(min_concurrencia, conc)
            clave = (conc, float((t.llegada_min - t.salida_min).sum()), tuple(q[k] for k in red.puntos), str(f1), str(f2), escala)
            if testigo is None or clave < testigo[0]:
                testigo = (clave, t, reservas, q, f1, f2, escala)
            # Para la pregunta de treinta vehículos no desarrollo circulaciones
            # que ya incumplen la simultaneidad, salvo un testigo diagnóstico.
            if conc > valores["vehiculos_contrato_contraste"] - valores["reserva_minima_dentro_flota"]:
                continue
            trips, cadenas = encadenar_viajes(t, red, regulacion=valores["regulacion_min"])
            cierre = cerrar_bases(trips, cadenas, red, regulacion=valores["regulacion_min"])
            intentos.append({"concurrencia": conc, "cadenas_minimas_reloj": len(cadenas), "cierre_bases": cierre is not None,
                            "forma_laguna": str(f1), "forma_vilaflor": str(f2), "escala_regreso": escala})
            score = (len(cadenas), cierre is None, conc)
            if best is None or score < best["score"]:
                best = {"score": score, "viajes": trips, "cadenas": cadenas, "reservas": reservas,
                        "cuotas": q, "cierre": cierre, "forma_laguna": f1, "forma_vilaflor": f2, "escala_regreso": escala,
                        "observacion": int(critico)}
    if best is None and testigo is not None:
        _, t, reservas, q, f1, f2, escala = testigo
        trips, cadenas = encadenar_viajes(t, red, regulacion=valores["regulacion_min"])
        cierre = cerrar_bases(trips, cadenas, red, regulacion=valores["regulacion_min"])
        best = {"score": (len(cadenas), cierre is None, min_concurrencia), "viajes": trips,
                "cadenas": cadenas, "reservas": reservas, "cuotas": q, "cierre": cierre,
                "forma_laguna": f1, "forma_vilaflor": f2, "escala_regreso": escala, "observacion": int(critico)}
    if best is None:return {"construido": False, "motivo": "No se construye un candidato con las reglas conservadas."}
    n = len(best["cadenas"])
    best["diagnostico"] = {"construido": True, "observacion": int(critico), "candidatos_horarios": candidatos,
        "estados_cuota": len(cuotas), "minima_concurrencia_catalogo": min_concurrencia,
        "cadenas_minimas_para_el_reloj_elegido": n, "cierre_bases": best["cierre"] is not None,
        "cabe_en_30_con_tres_libres": n + valores["reserva_minima_dentro_flota"] <= valores["vehiculos_contrato_contraste"],
        "catalogo_descartado_por_simultaneidad": min_concurrencia + valores["reserva_minima_dentro_flota"] > valores["vehiculos_contrato_contraste"],
        "grupo_refuerzo": grupo_refuerzo, "minimo_global_demostrado": False, "inventario_anual_30_verificado": False}
    if best["cierre"] is not None:
        a, b = best["cierre"]
        best["movimientos"] = materializar(best["viajes"], best["cadenas"], a, red,
            regulacion=valores["regulacion_min"], bases_finales=b)
    best["intentos"] = pd.DataFrame(intentos)
    return best
