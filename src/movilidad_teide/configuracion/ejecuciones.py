"""configuracion: ejecuciones. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from movilidad_teide.configuracion.parametros_tipos import ErrorParametros


def conservar_ejecucion(root, parametros, componente, archivos):
    """Registrar valores y resultados nuevos; conservar controles y copias históricas."""
    from movilidad_teide.trazabilidad import sha256_archivo
    root = Path(root)
    if sha256_archivo(root / parametros["ruta_libro"]) != parametros["sha256_libro"]:
        raise ErrorParametros("El Excel ha cambiado; no se archivan resultados con otras entradas.")
    if componente not in {"aforos", "actividad_norte", "conciliacion_demanda"}:
        raise ErrorParametros("Componente de ejecución no reconocido.")
    archivos = [Path(p) for p in archivos]
    if len({p.name for p in archivos}) != len(archivos):
        raise ErrorParametros("Hay nombres de salida repetidos en el archivo de ejecución.")
    identidad = {p.name: sha256_archivo(p) for p in archivos}
    token = hashlib.sha256(json.dumps({"libro": parametros["sha256_libro"], "caso": parametros["caso"], "archivos": identidad}, sort_keys=True).encode()).hexdigest()[:20]
    destino = root / "data/silver/modelo/ejecuciones" / componente / token
    if destino.exists():
        manifiesto = destino / "manifiesto.json"
        if not manifiesto.is_file():
            raise ErrorParametros("La ejecución archivada no conserva su manifiesto.")
        ficha = json.loads(manifiesto.read_text())
        formato = ficha.get("registro_entradas", "excel_copiado")
        if formato == "excel_copiado":
            # Las ejecuciones anteriores mantienen íntegro el control de su Excel.
            if not (destino / "parametros_modelo.xlsx").is_file() or sha256_archivo(destino / "parametros_modelo.xlsx") != parametros["sha256_libro"]:
                raise ErrorParametros("La copia archivada del libro no conserva su integridad.")
        elif formato == "valores_y_elecciones":
            valores = destino / "parametros_resueltos.json"
            if not valores.is_file() or sha256_archivo(valores) != ficha.get("sha256_parametros_resueltos"):
                raise ErrorParametros("El registro de parámetros no conserva su integridad.")
        else:
            raise ErrorParametros("Formato de registro de entradas no reconocido.")
        if ficha.get("sha256_libro") != parametros["sha256_libro"] or ficha.get("archivos") != identidad:
            raise ErrorParametros("El manifiesto archivado no coincide con las entradas y salidas.")
        if not (destino / "parametros_resueltos.json").is_file() or json.loads((destino / "parametros_resueltos.json").read_text()) != parametros:
            raise ErrorParametros("Las elecciones archivadas no coinciden con la ejecución.")
        for nombre, huella in identidad.items():
            if not (destino / nombre).is_file() or sha256_archivo(destino / nombre) != huella:
                raise ErrorParametros("Una ejecución archivada no conserva su integridad.")
        return destino
    destino.mkdir(parents=True)
    # Las nuevas ejecuciones registran el contenido utilizado sin copiar otro Excel.
    for p in archivos: shutil.copy2(p, destino / p.name)
    (destino / "parametros_resueltos.json").write_text(json.dumps(parametros, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (destino / "manifiesto.json").write_text(json.dumps({"fecha_utc": datetime.now(timezone.utc).isoformat(), "caso": parametros["caso"], "sha256_libro": parametros["sha256_libro"], "registro_entradas": "valores_y_elecciones", "sha256_parametros_resueltos": sha256_archivo(destino / "parametros_resueltos.json"), "archivos": identidad}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destino
