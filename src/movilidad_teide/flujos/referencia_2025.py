"""Preparo la demanda de 2025 como una etapa separada del balance de 2028."""
from pathlib import Path
import json
import platform

import numpy as np
import pandas as pd

from movilidad_teide.demanda.actividad import anualizar_referencias_visor
from movilidad_teide.demanda.asignacion_tipos import SEGMENTOS
from movilidad_teide.demanda.referencia_oficial import (
    TOLERANCIA_PERSONAS, normalizar_aportes, distribuir_origenes,
)
from movilidad_teide.trazabilidad import sha256_archivo
from .tipos import Etapa


FUENTES = {
    "oficial": "data/bronze/documentacion/visitas_parque/metadatos_2025.json",
    "perfiles": "data/silver/movilidad/visor_teide/20261016T154509Z_f7cda5fc/demanda_horaria_medianias_por_indice.csv",
    "indices": "data/silver/actividad/corredor_norte/matrices_con_formato_publicado.csv",
    "anual_previa": "data/silver/actividad/corredor_norte/demanda_anual_referencia_visor.csv",
    "origenes": "data/silver/demanda/asignacion/demanda_referencia_calculo.csv",
    "aforos": "data/silver/aforos_teide/reparto_personas_aforos_conjunto.csv",
    "od_original": "data/silver/actividad/corredor_norte/contraste_ambito_od_visor_2025.csv",
    "parametros_conservados": "config/parametros_modelo.xlsx",
}


def preparar_referencia_2025(root):
    """Reconstruyo primero la anualización anterior; después distribuyo el total oficial.

    No aplico captación, reparto modal, crecimiento, cupo, p85 o consumo. Las
    salidas OD originales se conservan como contraste; los regresos hipotéticos
    se emparejan con las entradas y nunca aumentan el número de visitas.
    """
    root = Path(root).resolve()
    hashes = {ruta: sha256_archivo(root / ruta) for ruta in FUENTES.values()}
    ficha = json.loads((root / FUENTES["oficial"]).read_text())
    pdf = (Path(FUENTES["oficial"]).parent / ficha["archivo"]).as_posix()
    hashes[pdf] = sha256_archivo(root / pdf)
    if hashes[pdf] != ficha["sha256"] or ficha["anio"] != 2025 or ficha["parque"] != "Teide":
        raise ValueError("La referencia oficial no coincide con su original identificado.")
    leer = lambda clave: pd.read_csv(root / FUENTES[clave], sep=";", float_precision="round_trip")
    perfiles, indices, origenes = leer("perfiles"), leer("indices"), leer("origenes")
    ind = indices.loc[indices.anio.eq(2025)]
    anual = anualizar_referencias_visor(perfiles, indices, dict.fromkeys(SEGMENTOS, 0.),
        anio_base=2025, anio_calendario=2025, criterio="Media de meses 2025 por tipo de día")
    previa = leer("anual_previa").query("anio_calendario == 2025")
    grupos = ["access_corridor", "direccion", "colectivo"]
    esperado = previa.set_index(grupos).viajes_persona_anuales_referencia.sort_index()
    reconstruido = anual["demanda_anual_referencia_visor"].set_index(grupos).viajes_persona_anuales_referencia.sort_index()
    pd.testing.assert_series_equal(reconstruido, esperado, check_names=False, rtol=0, atol=TOLERANCIA_PERSONAS)
    dias = anual["calendario_anualizacion"].groupby("tipo_dia_publicado").dias_calendario.sum()
    p = perfiles.loc[perfiles.matrix_index.isin(ind.matrix_index) & perfiles.direccion.eq("subida")].copy()
    p = p.merge(ind[["matrix_index", "mes_publicado", "tipo_dia_publicado"]], on="matrix_index", validate="many_to_one")
    keys = ["access_corridor", "tipo_dia_publicado", "hora_servicio"]
    h = p.groupby(keys, as_index=False)[list(SEGMENTOS)].sum()
    cobertura = p.groupby(keys).agg(meses_con_registro=("mes_publicado", "nunique"),
        indices_fuente=("matrix_index", lambda s: ",".join(map(str, sorted(s.unique()))))).reset_index()
    h = h.merge(cobertura, on=keys, validate="one_to_one")
    h = h.melt(id_vars=keys + ["meses_con_registro", "indices_fuente"], value_vars=list(SEGMENTOS),
               var_name="colectivo", value_name="suma_tres_referencias")
    # Divido por los tres meses de la regla vigente, también donde faltan registros horarios.
    # Conservo esa cobertura incompleta explícita: no la convierto en un cero observado.
    h["dias_calendario"] = h.tipo_dia_publicado.map(dias)
    h["aporte_anual_od"] = h.suma_tres_referencias * h.dias_calendario / 3
    h["sentido"] = "entrada"
    h["anio"] = 2025
    norm = normalizar_aportes(h, ficha["visitas_anuales"], claves=keys + ["colectivo"])
    norm["colectivo_nombre"] = norm.colectivo.map(SEGMENTOS)
    norm["unidad"] = "visitas anuales estimadas; no personas únicas, vehículos ni captados"
    def desglose(cols):
        return norm.groupby(cols, as_index=False)[["aporte_anual_od", "proporcion_anual_od", "visitas_normalizadas_2025"]].sum()
    por_grupo = desglose(["access_corridor", "colectivo"])
    check_anual = anual["demanda_anual_referencia_visor"].query('direccion == "subida"').set_index(["access_corridor", "colectivo"]).viajes_persona_anuales_referencia
    pd.testing.assert_series_equal(por_grupo.set_index(["access_corridor", "colectivo"]).aporte_anual_od.sort_index(),
                                  check_anual.sort_index(), check_names=False, rtol=0, atol=TOLERANCIA_PERSONAS)
    origen = distribuir_origenes(origenes, por_grupo.rename(columns={"access_corridor": "corredor_fuente"}))
    columnas = ["origen_id", "colectivo", "sentido", "corredor_fuente", "corredor_calculo",
        "cabecera_calculo", "viajes_persona_media_57_matrices", "en_ambito_anual",
        "peso_origen_condicionado", "visitas_normalizadas_2025", "estado"]
    origen = origen[columnas]
    regresos = origen.copy(deep=True)
    regresos["sentido"] = "desde_teide"
    regresos["viajes_regreso_pareados"] = regresos.pop("visitas_normalizadas_2025")
    regresos["contabiliza_visitas_adicionales"] = False
    regresos["estado"] = "Un regreso por entrada por hipótesis; no salidas OD observadas ni visitas adicionales"
    aforo = leer("aforos")
    aforo = aforo.loc[aforo.anio.eq(2025) & aforo.sentido.eq("entrada") & aforo.ocupacion_coche_aplicada.notna()]
    if len(aforo) != 1:
        raise ValueError("La referencia de aforos debe ser única y tener ocupaciones explícitas.")
    od = leer("od_original")
    od["dias_calendario"] = od.tipo_dia.map({"laborable": 261, "sabado": 52, "domingo": 52})
    if od.dias_calendario.isna().any() or len(od) != 18 or not od.anio.eq(2025).all():
        raise ValueError("El contraste OD no conserva las dieciocho referencias de 2025.")
    raw = od.loc[od.sentido.eq("hacia_teide")]
    raw_total = float((raw.viajes_externos * raw.dias_calendario / 3).sum())
    base = float(norm.aporte_anual_od.sum())
    comparacion = pd.DataFrame([
        {"fuente": "OAPN 2025", "cantidad": ficha["visitas_anuales"], "interpretacion": "Estimación oficial de visitas; referencia agregada", "ruta": pdf},
        {"fuente": "Aforos 2025 y ocupaciones históricas", "cantidad": float(aforo.personas_paso_estimadas.iloc[0]), "interpretacion": "Personas-paso de entrada estimadas; no censo independiente de visitas", "ruta": FUENTES["aforos"]},
        {"fuente": "Visor, anualización anterior de entradas", "cantidad": base, "interpretacion": "Viajes-persona anualizados desde nueve perfiles; antes de captación", "ruta": FUENTES["perfiles"]},
        {"fuente": "Consultas OD, entradas externas anualizadas", "cantidad": raw_total, "interpretacion": "Contraste de preparación; no se suma al Visor", "ruta": FUENTES["od_original"]},
    ])
    comparacion["cociente_respecto_oficial"] = comparacion.cantidad / ficha["visitas_anuales"]
    controles = []
    def comprobar(nombre, condicion, diferencia=0., tolerancia=0.):
        if not bool(condicion):
            raise ValueError(f"No se cumple el control: {nombre}")
        controles.append({"control": nombre, "cumple": True, "diferencia": diferencia, "tolerancia_absoluta": tolerancia})
    comprobar("Anualización previa reconstruida por grupo y sentido", True)
    comprobar("Calendario 2025: 261 laborables aproximados, 52 sábados y 52 domingos", dias.to_dict() == {"Domingo": 52, "Laborable": 261, "Sábado": 52})
    comprobar("Los cuatro colectivos permanecen", set(norm.colectivo) == set(SEGMENTOS))
    comprobar("Los cuatro corredores fuente permanecen", norm.access_corridor.nunique() == 4)
    comprobar("Entradas externas sin internos o regresos", norm.sentido.eq("entrada").all())
    error = float(norm.visitas_normalizadas_2025.sum() - ficha["visitas_anuales"])
    comprobar("Suma del desglose igual al total oficial", abs(error) <= TOLERANCIA_PERSONAS, error, TOLERANCIA_PERSONAS)
    err_peso = float(norm.proporcion_anual_od.sum() - 1)
    comprobar("Las proporciones suman uno", abs(err_peso) <= 1e-12, err_peso, 1e-12)
    comprobar("Las proporciones se conservan tras normalizar", np.allclose(norm.visitas_normalizadas_2025 / ficha["visitas_anuales"], norm.proporcion_anual_od, rtol=0, atol=1e-12), tolerancia=1e-12)
    comprobar("Todos los orígenes y colectivos de entrada se conservan", set(map(tuple, origen[["origen_id", "colectivo"]].to_numpy())) == set(map(tuple, origenes.loc[origenes.sentido.eq("hacia_teide"), ["origen_id", "colectivo"]].to_numpy())))
    comprobar("Sin referencia anual: cantidades ausentes conservadas", origen.loc[~origen.en_ambito_anual, "visitas_normalizadas_2025"].isna().all())
    err_origen = float(origen.visitas_normalizadas_2025.sum() - ficha["visitas_anuales"])
    comprobar("Desagregación territorial conserva total", abs(err_origen) <= TOLERANCIA_PERSONAS, err_origen, TOLERANCIA_PERSONAS)
    comprobar("Regresos pareados sin visitas adicionales", np.allclose(origen.visitas_normalizadas_2025, regresos.viajes_regreso_pareados, rtol=0, atol=0, equal_nan=True) and not regresos.contabiliza_visitas_adicionales.any())
    for ruta, huella in hashes.items():
        comprobar("Entrada conservada: " + ruta, sha256_archivo(root / ruta) == huella)
    tablas = {"demanda_horaria_2025": norm, "desglose_colectivos_2025": desglose(["colectivo"]),
        "desglose_accesos_fuente_2025": desglose(["access_corridor"]),
        "desglose_tipos_dia_2025": desglose(["tipo_dia_publicado"]),
        "origenes_2025": origen, "regresos_pareados_2025": regresos,
        "contraste_fuentes_2025": comparacion, "controles": pd.DataFrame(controles)}
    meta = {"decision": "D233", "hipotesis": "H124", "fecha": "2026-11-06", "anio": 2025,
        "total_oficial": ficha["visitas_anuales"], "total_od_anterior": base,
        "factor_equivalente": ficha["visitas_anuales"] / base,
        "formula": "visitas_i = total_oficial_2025 * aporte_anual_OD_i / suma_aportes_anuales_OD",
        "identificacion_temporal": "Correspondencia de índices inferida por totales únicos compatibles con redondeo; conservo su estado y fuente en matrices_con_formato_publicado.csv, sin presentarla como confirmación del productor.",
        "fuentes_sha256": hashes, "origenes_conservados": int(origen.origen_id.nunique()),
        "filas_origen_sin_referencia_anual": int((~origen.en_ambito_anual).sum()),
        "celdas_horarias_con_menos_de_tres_meses": int(norm.loc[norm.meses_con_registro.lt(3), keys].drop_duplicates().shape[0]),
        "tolerancia_personas": TOLERANCIA_PERSONAS,
        "justificacion_tolerancia": "1e-8 visitas/año cubre únicamente acumulación y exportación de coma flotante; no es incertidumbre física. No se redondean ni ajustan filas para cerrar sumas.",
        "estado": "Base 2025 normalizada para revisión; no activada en el balance de 2028 ni en el informe v0.14",
        "calibracion_del_operador_telefonico_acreditada": False,
        "representatividad_proporciones_validada": False,
        "causa_discrepancia_identificada": False,
        "titsa_excursiones_desagregados": False, "operacion_2028_recalculada": False,
        "energia_recalculada": False, "informe_modificado": False,
        "entorno": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__}}
    return Etapa(tablas), meta


def generar_referencia_2025(root, destino):
    """Exporto una nueva ejecución y rechazo destinos que alteren entradas o resultados anteriores."""
    root, destino = Path(root).resolve(), Path(destino).resolve()
    permitido = (root / "data/silver/movilidad/referencia_oficial_2025").resolve()
    if destino == root or any(destino.is_relative_to((root / p).resolve()) for p in ("config", "src", "tests", "docs", "notebooks", "data")) and not destino.is_relative_to(permitido):
        raise ValueError("Elijo un destino independiente o una ejecución nueva bajo referencia_oficial_2025.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):
        raise FileExistsError("Conservo la ejecución anterior: el destino debe estar vacío.")
    resultado, meta = preparar_referencia_2025(root)
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, tabla in resultado.tablas.items():
        tabla.to_csv(destino / f"{nombre}.csv", sep=";", index=False, encoding="utf-8-sig", float_format="%.17g")
    meta["codigo_sha256"] = {str(Path(__file__).relative_to(Path(__file__).parents[2])): sha256_archivo(__file__),
        "movilidad_teide/demanda/referencia_oficial.py": sha256_archivo(Path(__file__).parents[1] / "demanda/referencia_oficial.py"),
        "movilidad_teide/demanda/actividad.py": sha256_archivo(Path(__file__).parents[1] / "demanda/actividad.py"),
        "movilidad_teide/demanda/asignacion_tipos.py": sha256_archivo(Path(__file__).parents[1] / "demanda/asignacion_tipos.py"),
        "scripts/preparar_demanda_2025.py": sha256_archivo(Path(__file__).parents[3] / "scripts/preparar_demanda_2025.py")}
    meta["resultados_sha256"] = {p.name: sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    (destino / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return resultado, meta
