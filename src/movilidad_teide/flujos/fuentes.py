"""Compruebo las entradas conservadas antes de reconstruir el estudio."""
from pathlib import Path
import json

from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.trazabilidad import sha256_archivo


ETAPAS = {
    'pendiente': '20261101_pendiente_anual_pareada',
    'modulacion': '20261101_modulacion_cabildo_30',
    'inventario': '20261101_flota_30_tres_sustitutas',
    'seleccion': '20261101_hot_central_fta_sensibilidad',
}


def raiz_proyecto(inicio=None):
    """Localizo el proyecto desde la raíz o desde cualquier carpeta de cuadernos."""
    inicio = Path(inicio or Path.cwd()).resolve()
    for p in (inicio, *inicio.parents):
        if (p / 'config/parametros_modelo.xlsx').is_file() and (p / 'pyproject.toml').is_file():
            return p
    raise FileNotFoundError('No encuentro el libro y la configuración del proyecto.')


def carpeta_etapa(root, etapa):
    return Path(root) / 'data/silver/energia_turismos' / ETAPAS[etapa]


def _archivo(root, carpeta, nombre):
    p = Path(nombre)
    return p if p.is_absolute() else root / p if p.parts[0] in ('data', 'config', 'src', 'outputs', 'docs') else carpeta / p


def verificar_entradas(root):
    """Verifico datos y elecciones; el productor histórico conserva su propio código.

    Las huellas antiguas del código y de los libros anteriores se mantienen en
    sus metadatos. Una reconstrucción nueva utiliza y registra el código y el
    libro actuales, sin declarar que sus archivos coinciden con los históricos.
    """
    root = Path(root).resolve()
    parametros = leer_parametros(root)
    meta_actual = json.loads((carpeta_etapa(root, 'seleccion') / 'metadatos.json').read_text())
    if parametros != meta_actual['parametros']:
        # Compatibilidad explícita con la extensión de ordenación: valido la
        # nueva tabla y la igualdad exacta de todas las elecciones históricas.
        # No se acepta una alteración genérica de parámetros o del libro.
        from movilidad_teide.configuracion.ordenacion import leer_ordenacion
        referencia = leer_ordenacion(root)
        anterior = {k: v for k, v in meta_actual['parametros'].items() if k != 'sha256_libro'}
        if referencia['indice']['parametros_base_conservados'] != anterior:
            raise ValueError('El libro difiere de la referencia histórica fijada.')
    actuales = {p['id']: p['valor_utilizado'] for p in parametros['parametros']}
    verificados = {}
    productores_historicos = {}
    for etapa in ETAPAS:
        carpeta = carpeta_etapa(root, etapa)
        meta = json.loads((carpeta / 'metadatos.json').read_text())
        historicos = {p['id']: p['valor_utilizado'] for p in meta['parametros']['parametros']}
        if any(actuales[k] != v for k, v in historicos.items()):
            raise ValueError(f'{etapa}: han cambiado valores de cálculo respecto a su referencia.')
        for campo in ('inputs_sha256', 'outputs_sha256'):
            for nombre, esperado in meta[campo].items():
                p = _archivo(root, carpeta, nombre)
                if campo == 'inputs_sha256' and (p.suffix in ('.py', '.ipynb') or p == root / 'config/parametros_modelo.xlsx'):
                    productores_historicos[f'{etapa}:{nombre}'] = esperado
                    continue
                if not p.is_file() or sha256_archivo(p) != esperado:
                    raise ValueError(f'{etapa}: entrada o resultado conservado distinto: {nombre}')
                verificados[str(p)] = esperado
    return parametros, verificados, productores_historicos
