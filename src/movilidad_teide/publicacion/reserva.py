"""Política documental única: el bloque señalado de .gitignore.

Las reglas generales de Git para data/ eligen el canal (release). Solo las
cuatro reglas documentales de este bloque deciden la reserva temporal.
"""
from dataclasses import dataclass
import fnmatch
import hashlib
import json
from pathlib import Path

INICIO = '# === RESERVA_DOCUMENTAL_TEMPORAL: INICIO ==='
FIN = '# === RESERVA_DOCUMENTAL_TEMPORAL: FIN ==='
PATRONES = (
    '/docs/informe_energetico/',
    '/data/gold/anexos/',
    '/data/gold/ANEXOS_ENERGETICOS_2028_v*.zip',
    '/data/silver/ejecuciones/recursos_*/',
)


def _coincide(nombre, patron):
    n = Path(nombre).as_posix().rstrip('/')
    p = patron.lstrip('/').rstrip('/')
    return fnmatch.fnmatchcase(n, p) or (patron.endswith('/') and fnmatch.fnmatchcase(n, p + '/*'))


def es_documento(nombre):
    """Separar documentación de entrega de las referencias numéricas obligatorias."""
    return any(_coincide(nombre, p) for p in PATRONES)


def _base(texto):
    lineas = texto.splitlines()
    starts = [i for i, s in enumerate(lineas) if s.strip() == INICIO]
    ends = [i for i, s in enumerate(lineas) if s.strip() == FIN]
    if not starts and not ends:
        return texto.strip() + '\n', ()
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError('El bloque de reserva de .gitignore está incompleto o repetido.')
    a, b = starts[0], ends[0]
    reglas = tuple(s.strip() for s in lineas[a + 1:b] if s.strip() and not s.lstrip().startswith('#'))
    if reglas and (len(reglas) != len(PATRONES) or set(reglas) != set(PATRONES)):
        raise ValueError('La reserva admite las cuatro reglas documentales o ninguna. Para levantarla, comenta las cuatro; no ocultes entradas de cálculo.')
    return '\n'.join(lineas[:a] + lineas[b + 1:]).strip() + '\n', reglas


@dataclass(frozen=True)
class PoliticaDocumental:
    contenido: bytes
    patrones: tuple
    sha256_base: str
    existe: bool = True

    @property
    def reservada(self):
        return bool(self.patrones)

    def excluye(self, nombre):
        return any(_coincide(nombre, p) for p in self.patrones)

    def resumen(self):
        return dict(control='.gitignore', estado='reservada' if self.reservada else 'completa',
                    patrones=list(self.patrones), sha256=hashlib.sha256(self.contenido).hexdigest(),
                    sha256_fuera_del_bloque=self.sha256_base)


def leer_politica(root, archivo=None):
    p = Path(archivo) if archivo is not None else Path(root) / '.gitignore'
    if not p.exists():
        if archivo is not None:
            raise FileNotFoundError('No existe el .gitignore público indicado: ' + str(p))
        return PoliticaDocumental(b'', (), hashlib.sha256(b'\n').hexdigest(), existe=False)
    if p.is_symlink() or not p.is_file():
        raise ValueError('La política debe ser un archivo .gitignore regular, sin enlaces.')
    contenido = p.read_bytes()
    base, reglas = _base(contenido.decode('utf-8'))
    return PoliticaDocumental(contenido, reglas, hashlib.sha256(base.encode()).hexdigest())


def catalogo_completo(manifiesto):
    """Las fichas de documentos reservados no pueden ocultar datos científicos."""
    normales = manifiesto['archivos']
    reservados = manifiesto.get('documentos_no_distribuidos', [])
    resultado = {}
    for row in normales + reservados:
        n = row['ruta']
        if n in resultado:
            raise ValueError('Ruta repetida entre archivos o documentos reservados: ' + n)
        if row in reservados and not es_documento(n):
            raise ValueError('Una entrada de cálculo no puede declararse documento reservado: ' + n)
        resultado[n] = row
    return resultado


def proyectar(root, politica=None):
    """Preparar el inventario real de una entrega sin editar su árbol de origen."""
    root = Path(root).resolve()
    politica = politica or leer_politica(root)
    original = json.loads((root / 'manifiestos/archivos.json').read_text())
    catalogo = catalogo_completo(original)
    disponibles, reservados = [], []
    for n, row in sorted(catalogo.items()):
        if politica.excluye(n):
            reservados.append(dict(row))
            continue
        fila = dict(row)
        if n == '.gitignore' and politica.existe:
            fila.update(bytes=len(politica.contenido), sha256=hashlib.sha256(politica.contenido).hexdigest())
        else:
            p = root / n
            if not p.is_file():
                raise FileNotFoundError('Falta ' + n + '. Para levantar la reserva, recupera la entrega documental completa antes de preparar los paquetes.')
        disponibles.append(fila)
    if politica.existe and '.gitignore' not in catalogo:
        disponibles.append(dict(ruta='.gitignore', bytes=len(politica.contenido),
                                sha256=hashlib.sha256(politica.contenido).hexdigest(), capa='codigo_documentacion'))
    resultado = {**original, 'archivos': sorted(disponibles, key=lambda x:x['ruta']),
                 'documentos_no_distribuidos': reservados,
                 'politica_documental_en_preparacion': politica.resumen(),
                 'gitignore_editable': {'sha256_fuera_del_bloque': politica.sha256_base,
                                       'alcance': 'Solo el bloque documental; no altera hipótesis ni referencias numéricas.'}}
    # Las matrices conservan la procedencia completa; solo se distribuyen los archivos de este inventario.
    resultado.pop('politica_git_de_publicacion', None)
    return resultado
