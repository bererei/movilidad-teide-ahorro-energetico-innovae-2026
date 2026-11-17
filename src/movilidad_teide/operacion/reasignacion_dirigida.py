"""Ensayo traspasos mayores en puntas con el mismo inventario de treinta."""
from pathlib import Path
import json

import pandas as pd

from movilidad_teide.demanda.escenarios_2028 import construir_escenarios
from movilidad_teide.demanda.excursiones_2028 import reasignar_excursiones
from movilidad_teide.operacion.reloj_integrado import RelojIntegrado
from movilidad_teide.operacion.refinar_reservas import FORMAS
from movilidad_teide.trazabilidad import sha256_archivo


INVENTARIO = "data/silver/energia_turismos/20261101_flota_30_tres_sustitutas/inventario_30.csv"
CUOTAS = "data/silver/movilidad/horarios_550_2028/20261107_cupo550_reservas/cuotas_comunes.csv"
REJILLA = tuple(i / 100 for i in range(0, 51, 5))


def construir_dirigida(root, horaria, origenes, red, valores, captaciones, *, volumen=2500000):
    """Conservo cuotas e inventario D240/D216; no calibro el total de visitantes.

    Elijo el primer aumento de la rejilla que permite un reloj de hasta 27
    cadenas en cada perfil. No es un mínimo continuo ni una previsión modal.
    El cierre por bases se comprueba después con las treinta unidades existentes.
    """
    root = Path(root)
    inv = pd.read_csv(root / INVENTARIO, sep=";")
    old = json.loads((root / Path(INVENTARIO).parent / "metadatos.json").read_text())
    if sha256_archivo(root / INVENTARIO) != old["outputs_sha256"]["inventario_30.csv"]:
        raise ValueError("Inventario original modificado.")
    if len(inv) != 30 or inv.unidad_fisica_id.duplicated().any():raise ValueError("No son treinta identidades distintas.")
    inv["base_red"] = ["cabecera:" + r.punto if r.punto != "INTERIOR" else
                       red.extremos[0] if r.terminal_inicial == "Boca Tauce" else
                       red.extremos[1] if r.terminal_inicial == "El Portillo" else None for r in inv.itertuples()]
    if inv.base_red.isna().any() or set(inv.base_red) != set(red.bases):raise ValueError("Base de inventario desconocida.")
    ids = inv.groupby("base_red").unidad_fisica_id.apply(list).to_dict();caps = {b: len(a) for b,a in ids.items()}
    q = pd.read_csv(root / CUOTAS, sep=";").loc[lambda t: t.volumen_planificacion.eq(volumen)]
    cuotas = dict(zip(q.punto, q.coches_dia))
    if set(cuotas) != set(red.puntos) or sum(cuotas.values()) != 550:raise ValueError("Cuotas de referencia incompatibles.")
    planes, rates, intentos, seleccion = {}, {}, [], []
    for obs, h in horaria.groupby("matrix_index"):
        base = construir_escenarios(h, origenes, ocupacion=valores["ocupacion_coche"], cupo=550, captaciones=captaciones,
            hora_inicio=valores["hora_inicio_acceso"], hora_fin=valores["hora_fin_acceso"],
            cuotas_por_tipo={h.tipo_dia_publicado.iloc[0]: cuotas})
        candidatos = []
        for incremento in REJILLA:
            try:
                z = reasignar_excursiones(base, incremento=incremento, ocupacion=valores["ocupacion_coche"])
                reloj = RelojIntegrado(z["escenarios_por_punto_dia"], red, valores, cuotas)
            except ValueError as exc:
                intentos.append({"observacion": int(obs), "incremento_excursiones": incremento, "valido": False, "motivo": str(exc)})
                continue
            for forma, alpha in FORMAS:
                u,b = reloj.inicial(forma, alpha);n,e = reloj.evaluar(u,b)
                intentos.append({"observacion": int(obs), "incremento_excursiones": incremento,
                    "forma": forma, "fraccion_regreso": alpha, "valido": True, "vehiculos_reloj": n})
                candidatos.append(((incremento,n,-e,forma,alpha), reloj,u,b))
        viables = [p for p in candidatos if p[0][1] <= 27]
        if not viables:raise ValueError(f"No se construye un perfil de 27 unidades para {obs}; no se fuerza la reasignación.")
        key,clock,u,b = min(viables, key=lambda p:p[0]);t,r = clock.tablas(u,b);inc,n = key[:2]
        planes[int(obs)] = {"viajes": t, "reservas": r, "cuotas": cuotas, "cadenas": n,
            "cadenas_mejor_catalogo_inicial": n, "relojes_iniciales": len(FORMAS),
            "reinicios": pd.DataFrame([{"metodo": "Rejilla dirigida y siete formas; sin ajuste aleatorio",
                                         "pasos_previstos": 0, "mejores_cadenas": n}])}
        rates[int(obs)] = inc
        seleccion.append({"observacion": int(obs), "perfil": f"{h.mes_publicado.iloc[0]} · {h.tipo_dia_publicado.iloc[0]}",
            "incremento_excursiones_sobre_sin": inc, "vehiculos_reloj": n,
            "excursiones_sin_personas_dia": base["escenarios_por_punto_dia"].visitas_excursiones_resto_colectivo.sum(),
            "dias_equivalentes": float(h.dias_equivalentes.iloc[0])})
    return {"cuotas": cuotas, "perfiles": planes, "incrementos": rates, "capacidades": caps,
            "identidades_por_base": ids, "inventario": inv, "intentos": pd.DataFrame(intentos),
            "seleccion": pd.DataFrame(seleccion)}
