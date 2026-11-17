"""configuracion: lectura. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import json
import math
from pathlib import Path
from openpyxl import Workbook, load_workbook
from movilidad_teide.configuracion.parametros_tipos import CASOS
from movilidad_teide.configuracion.parametros_tipos import ErrorParametros
from movilidad_teide.configuracion.parametros_tipos import LIBRO
from movilidad_teide.configuracion.parametros_tipos import MODOS
from movilidad_teide.configuracion.parametros_tipos import ACCESOS
from movilidad_teide.configuracion.parametros_tipos import METODOS


def leer_parametros(root, caso=None, path=None):
    """Leer la capa base con el mismo resolvedor usado por la referencia vigente."""
    from io import BytesIO
    from hashlib import sha256
    root = Path(root); path = Path(path) if path else root / LIBRO
    contenido = path.read_bytes(); huella = sha256(contenido).hexdigest()
    wb = load_workbook(BytesIO(contenido), data_only=False)
    try:
        return _resolver_parametros(root, caso, path, wb, huella)
    finally:
        wb.close()


def configuracion_actividad(parametros):
    """Traducir las elecciones a la interfaz del modelo existente, sin leer el JSON viejo."""
    from movilidad_teide.configuracion.catalogo import catalogo
    datos = {r["id"]: r["valor_utilizado"] for r in parametros["parametros"]}
    def requerir(clave):
        if datos[clave] is None: raise ErrorParametros(f"Falta elegir {catalogo()[clave].nombre} en el Excel.")
        return datos[clave]
    cfg = json.loads(json.dumps(parametros["plantilla_tecnica"]))
    for clave in ["anio_base", "anio_objetivo"]: cfg[clave] = requerir(clave)
    metodo = METODOS[requerir("metodo_crecimiento")]
    cfg["tendencia"].update(metodo_central=metodo, anios_excluidos_periodo=requerir("anios_excluidos"), metodos_comparacion=[m for m in METODOS.values() if m != metodo and m != "tasas_manuales"])
    cfg["tendencia"]["tasas_manuales"] = {p: requerir(f"tasa_{p}") for p in ACCESOS} if metodo == "tasas_manuales" else None
    cfg["cupo"]["coches_privados_dia"] = requerir("cupo_global")
    manual = requerir("reparto_cupo") == "Porcentajes manuales"
    pesos = {p: requerir(f"cuota_{p}") for p in ACCESOS} if manual else None
    if pesos is not None and not math.isclose(sum(pesos.values()), 1.0, abs_tol=1e-9, rel_tol=0):
        raise ErrorParametros("Los porcentajes manuales del CUPO DE COCHES deben sumar 100 %.")
    cfg["cupo"].update(pesos_manuales=pesos, asignacion_teorica="porcentajes_manuales" if manual else "proporcional_a_entradas_diarias_proyectadas_por_acceso", duracion_permanencia_minutos=datos["permanencia_min"], franjas_reserva=datos["franja_reserva_min"])
    calendario_manual = requerir("calendario") == "Número de días manual"
    cfg["lanzadera_acceso"].update(calendario="numero_dias_manual" if calendario_manual else "todos_los_dias_del_anio_objetivo", dias_operacion_manual=requerir("dias_servicio") if calendario_manual else None)
    simulador = datos.get("origen_oferta") == "Simulador de captación"
    cfg["oferta_norte_elegida"] = {k: datos[f"{k}_OROTAVA"] if simulador and k != "km" else requerir(f"{k}_OROTAVA") for k in ["subidas", "bajadas", "reposiciones", "km"]}
    cfg["origen_oferta"] = datos.get("origen_oferta")
    if cfg["oferta_norte_elegida"]["km"] <= 0: raise ErrorParametros("La distancia de un sentido debe ser positiva.")
    # El estado de la elección describe el caso activo, no atribuye su aprobación a la referencia.
    cfg["tendencia"]["estado"] = f"Caso {parametros['caso']} — método elegido en Excel: {metodo}; propuesta H033 conservada aparte."
    cfg["cupo"]["estado"] = f"Caso {parametros['caso']} — cupo elegido {cfg['cupo']['coches_privados_dia']} coches/día; reparto {cfg['cupo']['asignacion_teorica']}. Referencias H034/H036 conservadas."
    cfg["lanzadera_acceso"]["estado"] = f"Caso {parametros['caso']} — calendario elegido {cfg['lanzadera_acceso']['calendario']}; referencia H035 conservada."
    cfg["excel"] = {"caso": parametros["caso"], "sha256_libro": parametros["sha256_libro"], "ruta_libro": parametros["ruta_libro"]}
    return cfg


def _resolver_parametros(root, caso, path, wb, huella):
    """Resolver un libro ya abierto sin volver a leerlo o alterar sus elecciones."""
    from movilidad_teide.configuracion.excel import _comprobar_vinculos
    from movilidad_teide.configuracion.catalogo import _firma_referencias
    from movilidad_teide.configuracion.catalogo import _valor
    from movilidad_teide.configuracion.catalogo import catalogo
    from movilidad_teide.trazabilidad import sha256_archivo
    if set(wb.sheetnames) != {"Inicio", "Propuestas", "Escenarios", "Resumen", "_Origen"} or wb["_Origen"]["B1"].value != "1.0":
        raise ErrorParametros("Estructura o versión del libro no reconocida.")
    caso = caso or wb["Inicio"]["B5"].value
    if caso not in CASOS: raise ErrorParametros("Selecciona Central, Variante A o Variante B en Inicio!B5.")
    campos = catalogo(); propuestas = {}; elecciones = {}
    for row in wb["Propuestas"].iter_rows(min_row=7, values_only=True):
        clave = row[7]
        if clave not in campos or clave in propuestas: raise ErrorParametros("Parámetro de referencia desconocido o repetido.")
        campo = campos[clave]
        if (row[0], row[1], row[2], row[6]) != (campo.grupo, campo.nombre, campo.unidad, campo.aplicacion):
            raise ErrorParametros(f"Se ha alterado el significado/unidad de {clave}; conserva la referencia y usa Manual.")
        valor = _valor(row[3], campo)
        if not isinstance(row[4], str) or not row[4].strip() or not isinstance(row[5], str) or not row[5].strip():
            raise ErrorParametros(f"{campo.nombre}: falta fundamento o fuente de la referencia.")
        propuestas[clave] = {"valor": valor, "justificacion": row[4], "fuente": row[5]}
    if set(propuestas) != set(campos): raise ErrorParametros("Faltan parámetros de referencia.")
    if _firma_referencias(propuestas) != wb["_Origen"]["B5"].value:
        raise ErrorParametros("Se ha alterado una propuesta/referencia conservada. Usa las columnas Manual y Motivo; una nueva referencia requiere una versión documentada.")
    for row in wb["Escenarios"].iter_rows(min_row=7, values_only=True):
        actual, clave, modo = row[0], row[12], row[6]
        if actual not in CASOS or clave not in campos or (actual, clave) in elecciones:
            raise ErrorParametros("Caso o parámetro desconocido/repetido en Escenarios.")
        if (row[1], row[2], row[3], row[11]) != (campos[clave].grupo, campos[clave].nombre, campos[clave].unidad, campos[clave].aplicacion):
            raise ErrorParametros(f"{clave}: se ha alterado el ámbito de la elección.")
        if modo not in MODOS or actual == "Central" and modo == "Heredar central":
            raise ErrorParametros(f"{actual}/{clave}: elección no válida.")
        manual = _valor(row[7], campos[clave])
        justificacion = row[8]
        if modo == "Manual" and (manual is None or not isinstance(justificacion, str) or not justificacion.strip() or justificacion.startswith("=")):
            raise ErrorParametros(f"{actual} — {campos[clave].nombre}: Manual exige valor y justificación.")
        elecciones[(actual, clave)] = {"eleccion": modo, "valor_manual": manual, "justificacion_manual": justificacion}
    if set(elecciones) != {(c, k) for c in CASOS for k in campos}: raise ErrorParametros("Faltan elecciones de alguno de los casos.")
    _comprobar_vinculos(wb)
    filas = []
    for clave, campo in campos.items():
        eleccion = elecciones[(caso, clave)]
        origen = "Central" if eleccion["eleccion"] == "Heredar central" else caso
        efectiva = elecciones[(origen, clave)]
        modo = efectiva["eleccion"]
        valor = efectiva["valor_manual"] if modo == "Manual" else propuestas[clave]["valor"] if modo == "Propuesta" else None
        motivo = efectiva["justificacion_manual"] if modo == "Manual" else propuestas[clave]["justificacion"]
        if valor is None: motivo = "Pendiente de elegir. " + propuestas[clave]["justificacion"]
        filas.append({"id": clave, "grupo": campo.grupo, "parametro": campo.nombre, "unidad": campo.unidad, "propuesta": propuestas[clave], "eleccion": eleccion, "origen_efectivo": origen, "modo_efectivo": modo, "valor_utilizado": valor, "justificacion_utilizada": motivo, "aplicacion": campo.aplicacion})
    plantilla = json.loads(wb["_Origen"]["B2"].value)
    if sha256_archivo(path) != huella: raise ErrorParametros("El libro cambió durante su lectura; guarda y vuelve a ejecutar.")
    return {"version": "1.0", "caso": caso, "sha256_libro": huella, "ruta_libro": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path), "parametros": filas, "elecciones_todos_los_casos": [{"caso": c, "id": k, **v} for (c, k), v in elecciones.items()], "plantilla_tecnica": plantilla}
