"""Lectura común de la configuración vigente, sin modificar el libro de hipótesis."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .lectura import _resolver_parametros
from .ordenacion import INDICE, _resolver_ordenacion
from .parametros_tipos import ErrorParametros, LIBRO
from movilidad_teide.trazabilidad import sha256_archivo


def leer_configuracion(root):
    """Leer una sola apertura del Excel y conservar ambas capas del modelo.

    ``valores`` contiene las 31 condiciones vigentes. ``base`` conserva las
    elecciones que necesitan las preparaciones existentes; no es otro escenario
    activo. ``valores_modelo`` es su traducción efectiva ya utilizada por el
    cálculo. La procedencia añade el nombre y la celda real de cada condición.
    """
    root = Path(root).resolve()
    try:
        libro = (root / LIBRO).read_bytes()
        indice = (root / INDICE).read_bytes()
    except FileNotFoundError as exc:
        raise ErrorParametros(
            'Falta el libro de hipótesis o su índice. Recupera config/ de la misma entrega.'
        ) from exc
    huella_libro = sha256(libro).hexdigest()
    huella_indice = sha256(indice).hexdigest()
    try:
        contenido = json.loads(indice)
        wb = load_workbook(BytesIO(libro), data_only=False)
    except (BadZipFile, InvalidFileException, json.JSONDecodeError) as exc:
        raise ErrorParametros('El libro o el índice no tienen un formato válido.') from exc
    try:
        base = _resolver_parametros(root, 'Central', root / LIBRO, wb, huella_libro)
        datos = _resolver_ordenacion(root, base, wb, contenido, huella_indice)
    finally:
        wb.close()
    if (sha256_archivo(root / LIBRO) != huella_libro
            or sha256_archivo(root / INDICE) != huella_indice):
        raise ErrorParametros('El libro o el índice cambiaron durante la lectura. Vuelve a leerlos.')
    return datos


def configuracion_resuelta(datos):
    """Crear una copia JSON portable de lo leído, sin rutas absolutas ni memoria oculta.

    Es una instantánea de comprobación. Las hipótesis siguen editándose en el
    Excel; modificar este JSON no cambia válidamente la referencia del estudio.
    """
    contenido = {k: v for k, v in datos.items() if k != 'raiz'}
    return json.loads(json.dumps(contenido, ensure_ascii=False, allow_nan=False))
