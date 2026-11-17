"""Preparar solo datos y controles de release; el código se obtiene de Git.

Herramienta de distribución independiente del código de cálculo sellado en
src/ y scripts/. No edita registros de ejecución, datos o hipótesis científicas.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from movilidad_teide.publicacion.nucleo import verificar, sha, dump, copiar_nucleo
from movilidad_teide.publicacion.reserva import leer_politica, proyectar
from movilidad_teide.publicacion.seleccion import evaluar_seleccion
from movilidad_teide.publicacion.empaquetado import empaquetar

PAQUETES = {c: 'datos_' + c + '.zip' for c in ('bronze', 'silver', 'gold')}


def _comprobar_zip(archivo, esperados):
    vistos = set()
    with zipfile.ZipFile(archivo) as z:
        for item in z.infolist():
            n = item.filename
            p = Path(n)
            if (p.is_absolute() or '..' in p.parts or '\\' in n or n in vistos
                    or stat.S_ISLNK(item.external_attr >> 16) or n not in esperados):
                raise ValueError('Miembro inesperado, duplicado o inseguro: ' + n)
            h = hashlib.sha256()
            with z.open(item) as stream:
                for b in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(b)
            fila = esperados[n]
            if item.file_size != fila['bytes'] or h.hexdigest() != fila['sha256']:
                raise ValueError('Contenido diferente del inventario: ' + n)
            vistos.add(n)
    if vistos != set(esperados):
        raise ValueError('El ZIP no contiene exactamente los datos de su capa.')


def preparar_release(root, destino, *, datos_existentes=None, gitignore_publico=None):
    root, destino = Path(root).resolve(), Path(destino).resolve()
    if destino == root or root.is_relative_to(destino) or destino.is_relative_to(root):
        raise ValueError('Elegir un destino nuevo fuera del repositorio que se empaqueta.')
    if destino.exists() and any(destino.iterdir()):
        raise FileExistsError('El destino debe estar vacío.')
    verificar(root)
    politica = leer_politica(root, gitignore_publico)
    control = evaluar_seleccion(root, politica)
    if not control['apta_para_difusion']:
        raise ValueError('Existen condiciones de difusión pendientes.')
    vista = proyectar(root, politica)
    esperado = {c: {x['ruta']: x for x in vista['archivos']
                   if x['ruta'].startswith('data/' + c + '/')} for c in PAQUETES}
    # Los archivos de Git se distribuyen exclusivamente en el repositorio.
    codigo = {x['ruta']: x['sha256'] for x in vista['archivos']
              if not x['ruta'].startswith('data/')}
    codigo['manifiestos/archivos.json'] = hashlib.sha256(
        (json.dumps(vista, ensure_ascii=False, indent=2) + '\n').encode()).hexdigest()
    if any(set(xs) & set(codigo) for xs in esperado.values()):
        raise ValueError('Los paquetes de datos se solapan con los archivos de código.')
    destino.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='teide_release_datos_') as temporal:
        temporal = Path(temporal)
        if datos_existentes is None:
            arbol = copiar_nucleo(root, temporal / 'arbol', politica=politica)
            empaquetar(arbol, temporal / 'generados')
            fuente = temporal / 'generados'
        else:
            fuente = Path(datos_existentes).resolve()
            if fuente == destino:
                raise ValueError('El origen de datos y el destino deben ser distintos.')
        paquetes = []
        for capa, nombre in PAQUETES.items():
            p = fuente / nombre
            _comprobar_zip(p, esperado[capa])
            shutil.copy2(p, destino / nombre)
            paquetes.append(dict(archivo=nombre, archivos=len(esperado[capa]),
                                 bytes=p.stat().st_size, sha256=sha(p), capa=capa))
    referencia = json.loads((root / 'manifiestos/referencia.json').read_text())
    huella_codigo = hashlib.sha256(json.dumps(codigo, sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    manifiesto = dict(formato='3.0', estado='Preparado localmente; sin publicación',
        referencia=referencia, paquetes=paquetes,
        codigo=dict(canal='Repositorio Git', url='https://github.com/bererei/movilidad-teide-ahorro-energetico-innovae-2026',
                    archivos=len(codigo), sha256_inventario=huella_codigo,
                    identificacion='Huella de las rutas y SHA-256 del código de esta entrega; el commit se identifica al publicar.'),
        codigo_incluido_en_release=False, coincidencias_por_ruta_codigo_datos=0,
        politica_documental=politica.resumen(), documentos_no_distribuidos=len(vista.get('documentos_no_distribuidos', [])),
        extraccion='Obtener el código de la misma entrega y extraer los tres ZIP en su raíz.',
        apta_para_difusion=True, casos_pendientes=[], publicacion_realizada=False)
    dump(destino / 'manifiesto_paquetes.json', manifiesto)
    (destino / 'SHA256SUMS').write_text(''.join(x['sha256'] + '  ' + x['archivo'] + '\n' for x in paquetes))
    dump(destino / 'ACEPTACION_PAQUETES.json', dict(
        formato='3.0', correcto=True, alcance='Contenido, huellas, rutas, cobertura de datos y separación respecto del código; sin ejecutar el cálculo científico.',
        paquetes=paquetes, codigo=manifiesto['codigo'], codigo_incluido_en_release=False,
        manifiesto_paquetes_sha256=sha(destino / 'manifiesto_paquetes.json'),
        SHA256SUMS_sha256=sha(destino / 'SHA256SUMS'),
        visitas_sin_y_con=referencia.get('visitas_sin_y_con'),
        condiciones=len(referencia.get('parametros_efectivos', {})),
        documentos_no_distribuidos=manifiesto['documentos_no_distribuidos'],
        calculo_cientifico_nuevo=False, motor_copert_ejecutado=False,
        publicacion_realizada=False))
    return manifiesto


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--destino', type=Path, required=True)
    parser.add_argument('--datos-existentes', type=Path)
    parser.add_argument('--gitignore-publico', type=Path)
    args = parser.parse_args()
    info = preparar_release(args.root, args.destino, datos_existentes=args.datos_existentes,
                            gitignore_publico=args.gitignore_publico)
    print('Release preparada: tres ZIP de datos y tres controles; código exclusivamente en Git.')
