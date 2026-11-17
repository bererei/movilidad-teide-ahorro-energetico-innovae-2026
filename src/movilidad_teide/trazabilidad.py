"""Huellas de archivos: leo por bloques sin modificar el contenido original."""
from hashlib import sha256
from pathlib import Path
import subprocess
import re


def sha256_archivo(path, chunk_size=1_048_576):
    digest = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(chunk_size), b''):
            digest.update(block)
    return digest.hexdigest()


def file_sha256(path, chunk_size=1_048_576):
    """Conservo la validación de existencia de la interfaz geográfica."""
    if not Path(path).is_file():
        raise FileNotFoundError(f'No existe el archivo: {Path(path)}')
    return sha256_archivo(path, chunk_size)


file_hash = sha256_archivo


REVISION_PRODUCTOR = 'ec62b79cbbf8f1e91bb1a3d9b6917451539d4806'


def verificar_archivo_de_referencia(root, relativo, esperado, *, revision=None):
    """Verifico los datos actuales y el código del productor en su revisión Git.

    Cuando cambia el código, contrasto sus bytes en la revisión conservada.
    Una revisión explícita debe ser un commit completo; permite verificar
    también las entradas de scripts. Las fuentes de datos nunca utilizan
    esta excepción ni se aceptan por tener el mismo nombre.
    """
    root, relativo = Path(root), Path(relativo)
    if relativo.is_absolute() or '..' in relativo.parts:
        raise ValueError('La referencia necesita una ruta interna inequívoca.')
    if revision is not None and (not isinstance(revision,str) or re.fullmatch('[0-9a-fA-F]{40}',revision) is None):
        raise ValueError('La revisión histórica debe ser un commit completo e inmutable.')
    fijada=revision or REVISION_PRODUCTOR
    p = root / relativo
    if p.is_file() and sha256_archivo(p) == esperado:
        return 'Archivo actual idéntico'
    carpetas={'src'} if revision is None else {'src','scripts'}
    if relativo.parts[0] not in carpetas or relativo.suffix != '.py':
        raise ValueError(f'Entrada vigente alterada: {relativo}')
    try:
        contenido = subprocess.check_output(
            ['git', '-C', str(root), 'show', f'{fijada}:{relativo.as_posix()}'],
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f'No puedo comprobar el productor histórico {fijada[:7]}: {relativo}') from exc
    if sha256(contenido).hexdigest() != esperado:
        raise ValueError(f'El código histórico no coincide con la referencia: {relativo}')
    return f'Productor histórico verificado en {fijada[:7]}'
