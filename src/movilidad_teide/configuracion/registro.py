"""Registro inicial portable de una ejecución, separado de los resultados científicos."""
from datetime import datetime, timezone
import csv
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

from .estudio import configuracion_resuelta, leer_configuracion
from .parametros_tipos import ErrorParametros, LIBRO
from .ordenacion import INDICE
from movilidad_teide.trazabilidad import sha256_archivo
from movilidad_teide.publicacion.reserva import es_documento

FORMATO = '1.0'
ARCHIVO = 'registro_ejecucion.json'
COPERT = 'data/bronze/copert/entradas_publicas/manifiesto.json'
CONTRATOS = (
    'manifiestos/preparacion_demanda_bronze.json',
    'manifiestos/preparacion_geografia_bronze.json',
    'manifiestos/preparacion_balance.json',
)
ENTORNO = ('.python-version', 'pyproject.toml', 'uv.lock')
PAQUETES = ('openpyxl', 'numpy', 'pandas', 'pyarrow', 'geopandas', 'shapely', 'pyproj', 'rasterio')


def _ruta_interna(root, nombre):
    """Resolver una ruta relativa del paquete sin salir de su raíz ni seguir enlaces."""
    if not isinstance(nombre, str) or not nombre or '\\' in nombre:
        raise ErrorParametros('La entrada necesita una ruta relativa con separadores /.')
    p = Path(nombre)
    if p.is_absolute() or '..' in p.parts or p.as_posix() != nombre:
        raise ErrorParametros('Ruta de entrada no portable: ' + nombre)
    actual = root
    for parte in p.parts:
        actual = actual / parte
        if actual.is_symlink():
            raise ErrorParametros('La entrada está enlazada fuera de su ubicación: ' + nombre)
    if not actual.resolve().is_relative_to(root):
        raise ErrorParametros('La entrada sale de la raíz del proyecto: ' + nombre)
    return actual


def _rol(nombre):
    if nombre.startswith(('data/gold/','data/silver/copert/referencia_comparacion/')):
        return 'referencia_para_comparar'
    if nombre.startswith(('src/', 'scripts/')):
        return 'codigo'
    if nombre.startswith('config/'):
        return 'configuracion'
    if nombre in ENTORNO:
        return 'definicion_del_entorno'
    if nombre in CONTRATOS:
        return 'contrato_de_preparacion'
    if nombre.startswith(('data/bronze/', 'data/silver/')):
        return 'entrada_de_calculo'
    raise ErrorParametros('El registro no reconoce el papel de la entrada: ' + nombre)


def _descriptores(root, datos):
    """Unir las entradas selladas de los contratos sin consultar resultados Gold."""
    ruta = root / 'manifiestos/archivos.json'
    entrega = json.loads(ruta.read_text(encoding='utf-8'))
    inventario = {x['ruta']: x for x in entrega['archivos']}
    if len(inventario) != len(entrega['archivos']):
        raise ErrorParametros('El inventario de la entrega repite rutas.')
    nombres = {str(p.relative_to(root)) for carpeta in ['src', 'scripts']
               for p in (root / carpeta).rglob('*.py')}
    nombres.update(str(p.relative_to(root)) for p in (root / 'config').iterdir() if p.is_file())
    nombres.update(n for n in inventario if n.startswith('data/silver/copert/referencia_comparacion/') or n=='data/silver/copert/factores/factores_nuevos.csv')
    nombres.update(ENTORNO)
    nombres.update(CONTRATOS)
    nombres.add(COPERT)
    esperado = {}

    def incorporar(nombre, huella):
        if nombre not in inventario or inventario[nombre]['sha256'] != huella:
            raise ErrorParametros('Contrato e inventario no coinciden: ' + nombre)
        if nombre in esperado and esperado[nombre] != huella:
            raise ErrorParametros('Dos contratos identifican entradas distintas: ' + nombre)
        esperado[nombre] = huella

    for nombre in sorted(nombres):
        if nombre not in inventario:
            raise ErrorParametros('Falta una entrada del código o configuración en el inventario: ' + nombre)
        incorporar(nombre, inventario[nombre]['sha256'])
    # Comprobar los contratos y el código antes de usar sus declaraciones.
    iniciales = [dict(ruta=n, sha256=h, bytes=inventario[n]['bytes'], rol=_rol(n))
                 for n, h in esperado.items()]
    _comprobar_archivos(root, iniciales)
    if datos['valores']['visitas_anio'] != entrega['visitas_sin_y_con']:
        raise ErrorParametros('La configuración no corresponde a las visitas de esta entrega.')
    for nombre, huella in datos['indice']['entradas_sha256'].items():
        incorporar(nombre, huella)
    for nombre, huella in datos['indice']['gold_sha256'].items():
        if not es_documento(nombre):
            incorporar(nombre, huella)
    referencias=set()
    entradas=set(esperado)
    for contrato in CONTRATOS:
        contenido = json.loads((root / contrato).read_text(encoding='utf-8'))
        for nombre, huella in contenido['fuentes_sha256'].items():
            incorporar(nombre, huella);entradas.add(nombre)
        for caso in contenido.get('comparaciones',[]):
            incorporar(caso['referencia'],caso['sha256_referencia']);referencias.add(caso['referencia'])
    referencias.update(n for n in datos['indice']['entradas_sha256'] if n.startswith('data/silver/') and n not in entradas)
    paquete_copert = json.loads((root / COPERT).read_text(encoding='utf-8'))
    for nombre, huella in paquete_copert['archivos_sha256'].items():
        incorporar(str(Path(COPERT).parent / nombre), huella)
    fuentes = [dict(ruta=n, sha256=h, bytes=inventario[n]['bytes'], rol='referencia_para_comparar' if n in referencias-entradas else _rol(n))
               for n, h in sorted(esperado.items())]
    return fuentes, dict(ruta='manifiestos/archivos.json', sha256=sha256_archivo(ruta),
                         informe=entrega['informe'], visitas_sin_y_con=entrega['visitas_sin_y_con'])


def _comprobar_archivos(root, fuentes, *, comprobar_referencias=False):
    vistos = set()
    comprobados = 0
    referencias = 0
    for fila in fuentes:
        nombre = fila['ruta']
        referencia_silver=fila['rol']=='referencia_para_comparar' and nombre.startswith('data/silver/')
        if nombre in vistos or (fila['rol'] != _rol(nombre) and not referencia_silver):
            raise ErrorParametros('Una entrada está repetida o tiene un papel incompatible: ' + nombre)
        vistos.add(nombre)
        p = _ruta_interna(root, nombre)
        if (re.fullmatch('[0-9a-f]{64}', str(fila['sha256'])) is None
                or type(fila['bytes']) is not int or fila['bytes'] < 0):
            raise ErrorParametros('Descriptor de entrada inválido: ' + nombre)
        if fila['rol'] == 'referencia_para_comparar' and not comprobar_referencias:
            referencias += 1
            continue
        if not p.is_file():
            raise ErrorParametros('Falta la entrada ' + nombre + '. Recupera los archivos de la misma entrega.')
        if p.stat().st_size != fila['bytes'] or sha256_archivo(p) != fila['sha256']:
            raise ErrorParametros('Entrada modificada: ' + nombre + '. Conserva la copia alterada y recupera la de la entrega.')
        comprobados += 1
    return dict(archivos_comprobados=comprobados, referencias_catalogadas_sin_leer=referencias)


def _comprobar_lector_ejecutado(root, fuentes):
    """Impedir atribuir al proyecto un lector importado de otra edición."""
    catalogo = {x['ruta']: x['sha256'] for x in fuentes}
    for nombre, modulo in list(sys.modules.items()):
        if not nombre.startswith('movilidad_teide') or not getattr(modulo, '__file__', None):
            continue
        archivo = Path(modulo.__file__)
        if archivo.suffix != '.py':
            continue
        partes = nombre.split('.')
        relativo = 'src/' + '/'.join(partes) + ('/__init__.py' if archivo.name == '__init__.py' else '.py')
        if catalogo.get(relativo) != sha256_archivo(archivo):
            raise ErrorParametros('El código importado no coincide con el proyecto elegido: ' + relativo)


def _entorno():
    return dict(python=platform.python_version(), sistema=platform.system(),
                paquetes={nombre: version(nombre) for nombre in PAQUETES})


def _git(root):
    if not (root / '.git').exists():
        return dict(revision=None, cambios_locales=None)
    try:
        env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, env=env, text=True).strip()
        estado = subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, env=env, text=True)
        return dict(revision=revision, cambios_locales=bool(estado))
    except (OSError, subprocess.CalledProcessError):
        return dict(revision=None, cambios_locales=None)


def _destino(root, destino):
    p = Path(destino)
    p = p if p.is_absolute() else root / p
    for actual in [p, *p.parents]:
        if actual.is_symlink():
            raise ErrorParametros('El destino de ejecución no puede atravesar enlaces.')
    p = p.resolve()
    permitida = root / 'data/silver/ejecuciones'
    if p == root or (p.is_relative_to(root) and (p == permitida or not p.is_relative_to(permitida))):
        raise ErrorParametros('Usa una carpeta nueva dentro de data/silver/ejecuciones/ o fuera del proyecto.')
    if p.exists():
        raise FileExistsError('Conservo el destino existente. Elige una carpeta de ejecución nueva.')
    return p


def _guardar_json(p, contenido):
    with p.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(contenido, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def iniciar_ejecucion(root, destino, *, modo='consulta', identificador=None):
    """Guardar la configuración y verificar entradas, sin lanzar ningún cálculo.

    El registro inicial es inmutable. Sus productos científicos quedan vacíos:
    la conexión y registro de las salidas de los flujos se implementa en 2.2.
    """
    root = Path(root).resolve()
    if modo not in ('consulta', 'reproduccion'):
        raise ErrorParametros('El modo debe ser consulta o reproduccion; expresa una intención, no un cálculo realizado.')
    destino = _destino(root, destino)
    identificador = identificador or destino.name
    if not isinstance(identificador, str) or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', identificador) is None:
        raise ErrorParametros('El identificador debe usar letras sin tildes, números, guion, punto o guion bajo.')
    datos = leer_configuracion(root)
    instantanea = configuracion_resuelta(datos)
    fuentes, entrega = _descriptores(root, datos)
    control = _comprobar_archivos(root, fuentes)
    _comprobar_lector_ejecutado(root, fuentes)
    entorno = _entorno()
    git = _git(root)
    # Validar todo antes de crear el destino; la exclusión evita sobrescrituras.
    if (sha256_archivo(root / LIBRO) != instantanea['base']['sha256_libro']
            or sha256_archivo(root / INDICE) != instantanea['sha256_indice']):
        raise ErrorParametros('La configuración cambió antes de guardar el registro.')
    destino.mkdir(parents=True, exist_ok=False)
    (destino / 'resultados').mkdir()
    _guardar_json(destino / 'configuracion_resuelta.json', instantanea)
    with (destino / 'parametros_vigentes.csv').open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(datos['procedencia_parametros'][0]), delimiter=';', lineterminator='\n')
        w.writeheader()
        w.writerows(datos['procedencia_parametros'])
    controles = [dict(ruta=n, bytes=(destino / n).stat().st_size, sha256=sha256_archivo(destino / n))
                 for n in ['configuracion_resuelta.json', 'parametros_vigentes.csv']]
    registro = dict(
        version=FORMATO, identificador=identificador,
        fecha_utc=datetime.now(timezone.utc).isoformat(), modo_solicitado=modo,
        estado_inicial='preparada_sin_calculo',
        alcance='Lectura de configuración y verificación de entradas. No ejecuta COPERT ni los flujos de transporte o energía.',
        entrega_de_origen=entrega, git_de_origen=git, entorno_de_creacion=entorno,
        configuracion=dict(ruta='configuracion_resuelta.json', libro=LIBRO, indice=INDICE,
                           condiciones_vigentes=len(datos['valores']), visitas_sin_y_con=datos['valores']['visitas_anio']),
        archivos_control=controles, fuentes=fuentes, comprobacion_inicial=control,
        salidas=dict(directorio_relativo='resultados', productos_cientificos=[], flujos_conectados=False),
    )
    _guardar_json(destino / ARCHIVO, registro)
    with (destino / 'registro_ejecucion.sha256').open('x', encoding='ascii') as f:
        f.write(sha256_archivo(destino / ARCHIVO) + '  ' + ARCHIVO + '\n')
    return destino


def abrir_ejecucion(root, registro, *, comprobar_referencias=False):
    """Reabrir y verificar desde disco, incluso en otra copia con las mismas entradas."""
    root = Path(root).resolve()
    p = Path(registro)
    p = p if p.is_absolute() else root / p
    if p.is_dir():
        p = p / ARCHIVO
    if p.name != ARCHIVO or p.is_symlink() or any(q.is_symlink() for q in p.parents):
        raise ErrorParametros('Selecciona el registro_ejecucion.json original, sin enlaces.')
    carpeta = p.parent.resolve()
    if not p.is_file() or not (carpeta / 'registro_ejecucion.sha256').is_file():
        raise ErrorParametros('Falta el registro inicial o su huella. Recupera la carpeta completa de ejecución.')
    partes = (carpeta / 'registro_ejecucion.sha256').read_text(encoding='ascii').split()
    if partes != [sha256_archivo(p), ARCHIVO]:
        raise ErrorParametros('El registro de ejecución fue modificado. Conserva el original; no lo edites como configuración.')
    contenido = json.loads(p.read_text(encoding='utf-8'))
    if (contenido.get('version') != FORMATO or contenido.get('estado_inicial') != 'preparada_sin_calculo'
            or contenido.get('modo_solicitado') not in ('consulta', 'reproduccion')):
        raise ErrorParametros('Formato o estado inicial del registro no reconocido.')
    if (contenido.get('salidas') != dict(directorio_relativo='resultados', productos_cientificos=[], flujos_conectados=False)
            or contenido.get('configuracion', {}).get('ruta') != 'configuracion_resuelta.json'):
        raise ErrorParametros('El registro inicial no representa un cálculo completado ni admite salidas añadidas a mano.')
    if (len(contenido['archivos_control']) != 2
            or {x['ruta'] for x in contenido['archivos_control']} != {'configuracion_resuelta.json', 'parametros_vigentes.csv'}):
        raise ErrorParametros('Los archivos de control no corresponden al registro inicial.')
    for fila in contenido['archivos_control']:
        actual = _ruta_interna(carpeta, fila['ruta'])
        if (not actual.is_file() or actual.stat().st_size != fila['bytes']
                or sha256_archivo(actual) != fila['sha256']):
            raise ErrorParametros('Archivo de configuración registrado ausente o alterado: ' + fila['ruta'])
    instantanea = json.loads((carpeta / 'configuracion_resuelta.json').read_text(encoding='utf-8'))
    datos = leer_configuracion(root)
    if instantanea != configuracion_resuelta(datos):
        raise ErrorParametros('El Excel o el índice no corresponden a la ejecución registrada. Inicia una ejecución nueva con su referencia documentada.')
    esperada = dict(ruta='configuracion_resuelta.json', libro=LIBRO, indice=INDICE,
                    condiciones_vigentes=len(datos['valores']), visitas_sin_y_con=datos['valores']['visitas_anio'])
    if contenido['configuracion'] != esperada:
        raise ErrorParametros('La descripción del registro contradice la configuración leída del Excel.')
    with (carpeta / 'parametros_vigentes.csv').open(encoding='utf-8-sig', newline='') as f:
        filas_csv = list(csv.DictReader(f, delimiter=';'))
    esperadas_csv = [{k: '' if v is None else str(v) for k, v in x.items()}
                     for x in datos['procedencia_parametros']]
    if filas_csv != esperadas_csv:
        raise ErrorParametros('La tabla de parámetros registrados contradice las celdas del Excel.')
    actuales, _ = _descriptores(root, datos)
    if actuales != contenido['fuentes']:
        raise ErrorParametros('El conjunto de entradas, contratos o código pertenece a otra entrega.')
    control = _comprobar_archivos(root, contenido['fuentes'], comprobar_referencias=comprobar_referencias)
    _comprobar_lector_ejecutado(root, contenido['fuentes'])
    if (sha256_archivo(root / LIBRO) != instantanea['base']['sha256_libro']
            or sha256_archivo(root / INDICE) != instantanea['sha256_indice']):
        raise ErrorParametros('El libro o el índice cambiaron al reabrir la ejecución.')
    from .productos import leer_estado
    estado=leer_estado(carpeta,sha256_archivo(p))
    entorno = _entorno()
    return dict(estado_etapas=estado,registro=contenido, configuracion=instantanea, comprobacion_actual=control,
                entorno_actual=entorno, mismo_entorno=entorno == contenido['entorno_de_creacion'])


def resumen_ejecucion(datos):
    """Resumen de lectura que no presenta la inicialización como resultados nuevos."""
    registro = datos['registro']
    return dict(identificador=registro['identificador'], modo_solicitado=registro['modo_solicitado'],
                estado_inicial=registro['estado_inicial'],
                visitas_sin_y_con=registro['configuracion']['visitas_sin_y_con'],
                condiciones_vigentes=registro['configuracion']['condiciones_vigentes'],
                comprobacion_actual=datos['comprobacion_actual'], mismo_entorno=datos['mismo_entorno'],
                etapas={k:{n:v[n] for n in ['nombre','estado','accion'] if n in v} for k,v in datos.get('estado_etapas',{}).get('etapas',{}).items()},
                productos_registrados=datos.get('estado_etapas',{}).get('productos',0),
                balance_calculado_en_esta_ejecucion=datos.get('estado_etapas',{}).get('etapas',{}).get('06',{}).get('estado')=='completada',
                motor_copert_ejecutado_en_esta_ejecucion=(datos.get('estado_etapas',{}).get('etapas',{}).get('05',{}).get('estado')=='completada' and datos.get('estado_etapas',{}).get('etapas',{}).get('05',{}).get('accion')=='ejecutar_motor'))
