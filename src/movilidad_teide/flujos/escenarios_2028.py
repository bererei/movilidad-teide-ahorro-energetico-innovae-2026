"""Recalculo la nueva demanda de 2028 y compruebo las restricciones conservadas."""
from pathlib import Path
import json
import platform

import numpy as np
import pandas as pd

from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.demanda.escenarios_2028 import calendario, proyectar_demanda, construir_escenarios
from movilidad_teide.energia.escenarios_2028 import valorar_componentes
from movilidad_teide.operacion.comprobacion_2028 import comprobar_flota
from movilidad_teide.trazabilidad import sha256_archivo
from .fuentes import verificar_entradas
from .tipos import Etapa


BASE = "data/silver/demanda/separacion_titsa/reasignacion"
FLOTA = "data/silver/energia_turismos/20261101_flota_30_tres_sustitutas"
PENDIENTE = "data/silver/energia/referencias_unitarias/pendiente_turismos"
PAREADO = "data/silver/energia/referencias_unitarias"
FUENTES = {
    "horaria": BASE + "/reparto_modal_horario_2025.csv",
    "origenes": BASE + "/origenes_por_modo_2025.csv",
    "titsa": BASE + "/estimacion_anual_titsa_2025.csv",
    "tendencia": "data/silver/actividad/corredor_norte/tendencias_personas_visor.csv",
    "movimientos": FLOTA + "/movimientos_con_identidad_fisica.parquet",
    "pares": FLOTA + "/pares_revisados.parquet",
    "paradas": "data/silver/operacion/paradas/referencias_paradas.csv",
    "correcciones": PENDIENTE + "/correccion_por_origen_y_rama.csv",
    "comunes": PAREADO + "/detalle_guaguas_comunes.csv",
    "factores": "data/silver/copert/20261029_energia_anual_lanzaderas/consumo_por_recorrido_y_referencia.csv",
}


def preparar_escenarios_2028(root):
    """Verifico entradas, conservo visitas y calculo lo que permiten las fuentes."""
    root = Path(root).resolve()
    parametros = leer_parametros(root)
    v = {p["id"]: p["valor_utilizado"] for p in parametros["parametros"]}
    # No proyecto silenciosamente otro año, otra captación o una respuesta al cupo.
    if (v["anio_base"] != 2025 or v["anio_objetivo"] != 2028
            or v["crecimiento_personas"] != "Tasa comparable del Visor 2024–2025"
            or v["transferencia_lanzadera"] != 1 or v["induccion"] != 0
            or v["fraccion_visita_primera_zona"] != 1 or v["fraccion_visita_segunda_zona"] != 0):
        raise ValueError("La ejecución necesita revisar explícitamente el nuevo caso del libro.")
    verificar_entradas(root)
    hashes = {}
    def registrar(ruta, esperado=None):
        p = root / ruta
        huella = sha256_archivo(p)
        if esperado is not None and huella != esperado:
            raise ValueError(f"Entrada distinta de la conservada: {ruta}")
        hashes[str(ruta)] = huella
    registrar(BASE + "/metadatos.json")
    meta_base = json.loads((root / BASE / "metadatos.json").read_text())
    for ruta, huella in meta_base["fuentes_sha256"].items(): registrar(ruta, huella)
    for nombre, huella in meta_base["resultados_sha256"].items(): registrar(BASE + "/" + nombre, huella)
    # Verifico los coeficientes reutilizados y conservo el enlace a sus fuentes.
    for carpeta, campo in [(PENDIENTE, "outputs_sha256"), (PAREADO, "archivos_sha256")]:
        registrar(carpeta + "/metadatos.json")
        m = json.loads((root / carpeta / "metadatos.json").read_text())
        for ruta in FUENTES.values():
            p = Path(ruta)
            if p.parent.as_posix() == carpeta:
                esperado = m[campo].get(p.name, m[campo].get(ruta))
                if esperado is None: raise ValueError(f"No hay huella de referencia para {ruta}")
                registrar(ruta, esperado)
    for ruta in [*FUENTES.values(), "config/parametros_modelo.xlsx"]: registrar(ruta)
    x = {k: pd.read_parquet(root / ruta) if ruta.endswith(".parquet") else
         pd.read_csv(root / ruta, sep=";", float_precision="round_trip") for k, ruta in FUENTES.items()}
    tendencia = x["tendencia"].loc[x["tendencia"].colectivo.eq("total_sistema")
        & x["tendencia"].metodo.eq("cagr_2024_2025_mismo_formato")]
    if len(tendencia) != 1 or not tendencia.aplicable_mismo_formato.all():
        raise ValueError("No hay una tasa comparable única.")
    tasa = float(tendencia.tasa_anual.iloc[0])
    h = proyectar_demanda(x["horaria"], anio=2028, tasa=tasa)
    captaciones = dict(zip(["extranjero", "espana_no_tenerife", "tenerife_no_frecuente", "tenerife_resto"],
        [v[k] for k in ["captacion_extranjero", "captacion_nacional", "captacion_local", "captacion_frecuente"]]))
    tablas = construir_escenarios(h, x["origenes"], ocupacion=v["ocupacion_coche"],
                                  cupo=v["cupo_global"], captaciones=captaciones,
                                  hora_inicio=v["hora_inicio_acceso"], hora_fin=v["hora_fin_acceso"])
    tablas["demanda_horaria_2028"] = h
    puntos = tablas["escenarios_por_punto_dia"]
    tablas.update(comprobar_flota(puntos, x["movimientos"], x["pares"], x["paradas"], v))
    nominal = comprobar_flota(puntos, x["movimientos"], x["pares"], x["paradas"], v,
                             capacidad_contraste=v["plazas_guagua"])["cota_flota_dias_medios"]
    nominal["estado"] = "Contraste favorable a capacidad nominal; no cambio de plazas de diseño"
    tablas["cota_flota_capacidad_nominal"] = nominal
    tablas.update(valorar_componentes(tablas["por_origen_dia"], x["correcciones"], x["comunes"],
        puntos, tablas["cota_interior_por_tramos"], x["factores"], v))
    # Native TITSA, incluidas bajadas y actividad interior, sigue siendo un
    # contraste separado. Solo las entradas representan nuevas visitas-persona.
    n = x["titsa"].copy()
    n["dias_calendario_2028"] = n.tipo_dia.map(calendario(2028))
    n["pasajeros_tramo_anio_2028"] = n.pasajeros_media_dia * (1 + tasa)**3 * n.dias_calendario_2028
    n["cuenta_visita_acceso"] = n.ambito_fisico.eq("entrada")
    n["sumable_a_interior_desde_reservas"] = False
    tablas["titsa_proyeccion_linea_ambito"] = n
    # Cupos enteros por acceso; los coches desagregados son cantidades esperadas.
    cupos = tablas["por_origen_dia"][["tipo_dia_publicado", "punto", "dias_calendario", "cupo_coches_punto"]].drop_duplicates()
    tablas["cupo_global_2028"] = cupos
    campos = ["coches_sin_dia", "coches_autorizados_dia", "coches_transferidos_dia", "visitas_coche",
        "visitas_coche_autorizadas_dia", "visitas_coche_transferidas_dia", "visitas_titsa",
        "visitas_excursiones_resto_colectivo", "visitas_excursiones_transferidas_dia",
        "visitas_excursiones_permanecen_dia", "demanda_lanzadera_dia", "visitas_sin_dia", "visitas_con_objetivo_dia"]
    anuales = pd.DataFrame({"magnitud_diaria": campos,
        "cantidad_anual": [float((puntos[c] * puntos.dias_calendario).sum()) for c in campos],
        "unidad": ["entradas de vehículos/año" if c.startswith("coches_") else "visitas-persona/año" for c in campos]})
    tablas["resumen_anual_2028"] = anuales
    origen_anual = tablas["por_origen_dia"].copy()
    cg = ["visitas_coche", "visitas_coche_autorizadas_dia", "visitas_coche_transferidas_dia",
          "visitas_excursiones_resto_colectivo", "visitas_excursiones_transferidas_dia",
          "visitas_excursiones_permanecen_dia"]
    origen_anual[cg] = origen_anual[cg].mul(origen_anual.dias_calendario, axis=0)
    colectivos = origen_anual.groupby("colectivo", as_index=False)[cg].sum()
    tt = tablas["titsa_por_corredor_colectivo_dia"].copy()
    tt["visitas_titsa_anio"] = tt.visitas_titsa * tt.dias_calendario
    colectivos = colectivos.merge(tt.groupby("colectivo", as_index=False).visitas_titsa_anio.sum(),
                                   on="colectivo", validate="one_to_one")
    colectivos["visitas_sin_anio"] = (colectivos.visitas_coche
        + colectivos.visitas_excursiones_resto_colectivo + colectivos.visitas_titsa_anio)
    colectivos["visitas_lanzadera_objetivo_anio"] = (colectivos.visitas_coche_transferidas_dia
        + colectivos.visitas_excursiones_transferidas_dia + colectivos.visitas_titsa_anio)
    colectivos["visitas_con_objetivo_anio"] = (colectivos.visitas_coche_autorizadas_dia
        + colectivos.visitas_excursiones_permanecen_dia + colectivos.visitas_lanzadera_objetivo_anio)
    colectivos = colectivos.rename(columns={c: c.removesuffix("_dia") + "_anio"
        for c in cg})
    tablas["escenarios_por_colectivo_anual"] = colectivos
    controles = []
    def control(nombre, actual, esperado, tolerancia=1e-8):
        if not np.isfinite([actual, esperado]).all() or abs(actual - esperado) > tolerancia:
            raise ValueError(f"No se cumple {nombre}: {actual} frente a {esperado}")
        controles.append({"control": nombre, "actual": actual, "esperado": esperado,
                          "tolerancia_absoluta": tolerancia, "correcto": True})
    for tipo, b in puntos.groupby("tipo_dia_publicado", sort=True):
        control(f"cupo global {tipo}", b.coches_autorizados_dia.sum(), v["cupo_global"])
        control(f"cuotas enteras {tipo}", cupos.loc[cupos.tipo_dia_publicado.eq(tipo), "cupo_coches_punto"].sum(), v["cupo_global"], 0)
        control(f"personas autorizadas {tipo}", b.visitas_coche_autorizadas_dia.sum(), v["cupo_global"] * v["ocupacion_coche"])
        control(f"visitas sin/con {tipo}", b.visitas_sin_dia.sum(), b.visitas_con_objetivo_dia.sum())
        control(f"coches antes = autorizados + transferidos {tipo}", b.coches_sin_dia.sum(),
                b.coches_autorizados_dia.sum() + b.coches_transferidos_dia.sum())
        control(f"regreso pareado {tipo}", b.regresos_lanzadera_pareados_dia.sum(), b.demanda_lanzadera_dia.sum())
        control(f"TITSA nativo sin expansión OAPN {tipo}", b.visitas_titsa.sum(),
                n.loc[n.tipo_dia.eq(tipo) & n.cuenta_visita_acceso, "pasajeros_media_dia"].sum() * (1 + tasa)**3)
    control("visitas anuales conservadas", float((h.visitas_persona_dia * h.dias_calendario).sum()),
            float((puntos.visitas_sin_dia * puntos.dias_calendario).sum()))
    control("cuatro colectivos", h.colectivo.nunique(), 4, 0)
    for c in colectivos.itertuples():
        control(f"colectivo {c.colectivo} sin/con", c.visitas_sin_anio, c.visitas_con_objetivo_anio)
    control("341 sin visitas de acceso", n.loc[n.linea_id.eq(341) & n.cuenta_visita_acceso, "pasajeros_tramo_anio_2028"].sum(), 0., 0)
    control("ocho filas sin cantidad conservadas", len(tablas["origenes_sin_cantidad_anual"]), 8, 0)
    for _, row in tablas["balance_componentes_2028"].iterrows():
        control("sin ahorro total cuando falta oferta o componente", int(pd.isna(row.ahorro_total_mwh_anio)), 1, 0)
    tablas["controles"] = pd.DataFrame(controles)
    meta = {"decision": "D236", "hipotesis": "H126", "fecha": "2026-11-06", "parametros": parametros,
        "fuentes_sha256": hashes, "entorno": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__},
        "tasa_anual_conservada": tasa, "factor_crecimiento": (1 + tasa)**3,
        "calendario_2025": calendario(2025), "calendario_2028": calendario(2028),
        "unidad_visitas": "visitas-persona; no personas únicas ni vehículos",
        "estado": ("Demanda y componentes recalculados; configuración incompatible con treinta vehículos"
            if tablas["cota_flota_dias_medios"].imposible_30_con_reserva.any()
            else "Demanda y componentes recalculados; cota favorable sin horario completo demostrado"),
        "metodo": ["Perfiles medios de marzo/julio/octubre por tipo de día; calendario 2028 y tasa común elegida en el libro",
            "Coche y excursiones por pesos territoriales heredados y cabecera de cálculo; TITSA por corredor de línea",
            "500 coches globales/día mediante mayores restos; transferencia completa condicionada, sin inducción",
            "Captación solo sobre excursiones/resto colectivo dentro de 7–19 h inclusive, como en la referencia; sustitución TITSA completa contada una vez",
            "Un regreso por visita; las bajadas nativas y embarques interiores TITSA no son nuevas visitas",
            "Cota de conducción de acceso e interior por tramos, con máxima flexibilidad y sin vacíos ni regulación",
            "Coeficientes Hot y pendiente conservados por origen, sentido, rama y asignación A/B",
            "FTA solo en el suelo de actividad de lanzaderas; no sobre coches o ahorro"],
        "limites": ["Días medios condicionados, no nueva validación de las nueve observaciones o p85 anteriores",
            "El factor oficial no explica la discrepancia OD-aforos ni valida sus proporciones territoriales",
            "Cota de vehículos necesaria, no suficiente: no es propuesta de ampliar flota",
            "No hay horario de treinta unidades que cumpla la cota; no se fabrica oferta, se recortan visitas o se conserva el ahorro anterior",
            "El consumo sin intervención de TITSA necesita inventario de servicios/recorridos; pasajeros no son expediciones",
            "Las líneas 341/342/348 se sustituyen; alimentación y continuidad de viajeros exteriores no cuantificadas",
            "Excursiones/resto colectivo es un residuo estimado; consumo equivalente y continuidad energética, no flota observada",
            "El interior TITSA puede solaparse con las cadenas de acceso y no se suma de nuevo",
            "Un coche/persona para captados de excursiones es hipótesis heredada; no se impone a antiguos usuarios TITSA",
            "No se cuantifican ahorros totales, aceptación de reservas, conductores, calidad de visita o aprobación operativa"],
        "informe_actualizado": False, "libro_modificado": False, "oferta_viable_30_demostrada": False,
        "ahorro_total_calculado": False, "tolerancia": "1e-8 en visitas, vehículos o MWh para redondeo binario; no incertidumbre física"}
    return Etapa(tablas), meta


def generar_escenarios_2028(root, destino):
    """Exporto a una ejecución nueva; nunca a las fuentes o al informe."""
    root, destino = Path(root).resolve(), Path(destino).resolve()
    permitido = (root / "data/silver/movilidad/escenarios_2028").resolve()
    if destino == root or any(destino.is_relative_to((root / p).resolve()) for p in
            ("data", "config", "src", "tests", "docs", "notebooks")) and not destino.is_relative_to(permitido):
        raise ValueError("El destino debe ser independiente o una ejecución nueva en escenarios_2028.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):
        raise FileExistsError("Conservo la ejecución existente; el destino debe estar vacío.")
    etapa, meta = preparar_escenarios_2028(root)
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, tabla in etapa.tablas.items():
        tabla.to_csv(destino / (nombre + ".csv"), sep=";", index=False, encoding="utf-8-sig", float_format="%.17g")
    paquete = Path(__file__).parents[1]
    productores = [Path(__file__), paquete / "demanda/escenarios_2028.py", paquete / "operacion/comprobacion_2028.py",
                   paquete / "energia/escenarios_2028.py", paquete / "configuracion/lectura.py", paquete / "flujos/fuentes.py"]
    meta["codigo_sha256"] = {"movilidad_teide/" + p.relative_to(paquete).as_posix(): sha256_archivo(p) for p in productores}
    script = Path(__file__).parents[3] / "scripts/recalcular_escenarios_2028.py"
    meta["codigo_sha256"]["scripts/recalcular_escenarios_2028.py"] = sha256_archivo(script)
    meta["resultados_sha256"] = {p.name: sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    (destino / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return etapa, meta
