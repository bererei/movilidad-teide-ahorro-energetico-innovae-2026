"""Configuración congelada, registros portables y rechazo de entradas incoherentes."""
from pathlib import Path
import csv
import json
import os
import shutil
import subprocess
import sys

from openpyxl import load_workbook
import pytest

from movilidad_teide.configuracion.estudio import leer_configuracion
from movilidad_teide.configuracion.registro import (
    ARCHIVO, CONTRATOS, COPERT, ENTORNO, iniciar_ejecucion, abrir_ejecucion,
)
from movilidad_teide.configuracion.parametros_tipos import ErrorParametros
from movilidad_teide.trazabilidad import sha256_archivo

ROOT = Path(__file__).resolve().parents[1]


def escribir_json(p, contenido):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(contenido, ensure_ascii=False, indent=2) + '\n')


def inventariar(root):
    filas = []
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if rel.parts[0] not in {'src', 'scripts', 'config', 'data', 'manifiestos'} and str(rel) not in ENTORNO:
            continue
        if rel.as_posix() == 'manifiestos/archivos.json':
            continue
        filas.append(dict(ruta=rel.as_posix(), bytes=p.stat().st_size, sha256=sha256_archivo(p)))
    escribir_json(root / 'manifiestos/archivos.json', dict(archivos=filas, visitas_sin_y_con=2500000, informe='v0.25'))


@pytest.fixture
def proyecto(tmp_path):
    """Paquete pequeño con el libro real y fuentes identificables de prueba.

    Conserva los 31 valores y el código efectivo, pero no pretende reproducir la
    demanda o la energía con los dos archivos sintéticos de esta prueba.
    """
    root = tmp_path / 'proyecto'
    for name in ['config', 'src', 'scripts']:
        shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns('__pycache__'))
    for name in ENTORNO:
        shutil.copy2(ROOT / name, root / name)
    fuente = root / 'data/bronze/entrada.csv'
    fuente.parent.mkdir(parents=True)
    fuente.write_text('visitas\n2500000\n')
    gold = root / 'data/gold/resultado.csv'
    gold.parent.mkdir(parents=True)
    gold.write_text('resultado\n1\n')
    indice = root / 'config/referencia_ordenacion_2028.json'
    datos = json.loads(indice.read_text())
    datos['entradas_sha256'] = {'data/bronze/entrada.csv': sha256_archivo(fuente)}
    datos['gold_sha256'] = {'data/gold/resultado.csv': sha256_archivo(gold)}
    escribir_json(indice, datos)
    for name in CONTRATOS:
        escribir_json(root / name, {'fuentes_sha256': {'data/bronze/entrada.csv': sha256_archivo(fuente)}})
    nativa = root / Path(COPERT).parent / 'tabla.csv'
    nativa.parent.mkdir(parents=True)
    nativa.write_text('stock\n1\n')
    escribir_json(root / COPERT, {'archivos_sha256': {'tabla.csv': sha256_archivo(nativa)}})
    inventariar(root)
    return root


def crear(root, destino='data/silver/ejecuciones/nueva', modo='consulta'):
    return iniciar_ejecucion(root, destino, modo=modo)


def volver_a_sellar(carpeta, datos):
    escribir_json(carpeta / ARCHIVO, datos)
    (carpeta / 'registro_ejecucion.sha256').write_text(sha256_archivo(carpeta / ARCHIVO) + '  ' + ARCHIVO + '\n')


def test_lector_conserva_condiciones_y_su_celda_real():
    datos = leer_configuracion(ROOT)
    filas = {x['id']: x for x in datos['procedencia_parametros']}
    assert datos['valores']['visitas_anio'] == 2500000
    assert datos['valores']['max_programadas_ordinaria'] == 27
    assert datos['valores_modelo']['cupo_global'] == 650
    assert len(filas) == 31 and filas['visitas_anio']['celda'] == 'Inicio!D35'
    assert len(datos['base']['parametros']) == 129


def test_registro_no_es_una_ejecucion_de_calculo(proyecto):
    p = crear(proyecto, modo='reproduccion')
    datos = abrir_ejecucion(proyecto, p)
    ficha = datos['registro']
    assert ficha['modo_solicitado'] == 'reproduccion'
    assert ficha['estado_inicial'] == 'preparada_sin_calculo'
    assert ficha['salidas']['productos_cientificos'] == []
    assert not ficha['salidas']['flujos_conectados']
    assert list((p / 'resultados').iterdir()) == []
    assert datos['comprobacion_actual']['referencias_catalogadas_sin_leer'] == 1
    with (p / 'parametros_vigentes.csv').open(encoding='utf-8-sig') as f:
        assert len(list(csv.DictReader(f, delimiter=';'))) == 31
    assert str(proyecto) not in (p / ARCHIVO).read_text()
    assert str(proyecto) not in (p / 'configuracion_resuelta.json').read_text()


def test_portable_a_otra_raiz_y_a_un_proceso_nuevo(proyecto, tmp_path):
    p = crear(proyecto)
    nuevo = tmp_path / 'copia'
    shutil.copytree(proyecto, nuevo)
    movido = nuevo / p.relative_to(proyecto)
    codigo = """import sys
from movilidad_teide.configuracion.registro import abrir_ejecucion
d=abrir_ejecucion(sys.argv[1],sys.argv[2]);assert d['registro']['configuracion']['visitas_sin_y_con']==2500000
print(d['registro']['estado_inicial'])
"""
    out = subprocess.run([sys.executable, '-B', '-c', codigo, str(nuevo), str(movido)], cwd=tmp_path,
                         env={**os.environ, 'PYTHONPATH': str(nuevo / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'},
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == 'preparada_sin_calculo'


@pytest.mark.parametrize('cambio', ['ausente', 'alterada'])
def test_entrada_incorrecta_impide_crear_y_no_deja_destino(proyecto, cambio):
    p = proyecto / 'data/bronze/entrada.csv'
    if cambio == 'ausente':
        p.unlink()
    else:
        p.write_text('otra entrada\n')
    with pytest.raises(ErrorParametros, match='Falta la entrada|Entrada modificada'):
        crear(proyecto)
    assert not (proyecto / 'data/silver/ejecuciones/nueva').exists()


def test_entrada_alterada_despues_de_crear_se_detecta(proyecto):
    p = crear(proyecto)
    (proyecto / 'data/bronze/entrada.csv').write_text('otra entrada\n')
    with pytest.raises(ErrorParametros, match='Entrada modificada'):
        abrir_ejecucion(proyecto, p)


@pytest.mark.parametrize('cambio', ['ausente', 'alterada'])
def test_catalogo_incluye_tambien_las_entradas_nativas_copert(proyecto, cambio):
    nativa = proyecto / Path(COPERT).parent / 'tabla.csv'
    if cambio == 'ausente':
        nativa.unlink()
    else:
        nativa.write_text('stock\n2\n')
    with pytest.raises(ErrorParametros, match='Falta la entrada|Entrada modificada'):
        crear(proyecto)


@pytest.mark.parametrize('nombre', ['registro_ejecucion.json', 'configuracion_resuelta.json', 'parametros_vigentes.csv'])
def test_no_acepta_alteraciones_del_registro_o_sus_controles(proyecto, nombre):
    p = crear(proyecto)
    with (p / nombre).open('a') as f:
        f.write('\nmodificado\n')
    with pytest.raises(ErrorParametros, match='modificado|alterado'):
        abrir_ejecucion(proyecto, p)


@pytest.mark.parametrize('cambio', ['formato', 'visitas', 'csv', 'configuracion', 'resultado_ficticio'])
def test_resellar_a_mano_no_convierte_incoherencias_en_validas(proyecto, cambio):
    p = crear(proyecto)
    ficha = json.loads((p / ARCHIVO).read_text())
    if cambio == 'formato':
        ficha['version'] = 'otra'
    elif cambio == 'visitas':
        ficha['configuracion']['visitas_sin_y_con'] = 2600000
    elif cambio == 'resultado_ficticio':
        ficha['salidas']['productos_cientificos'] = ['balance.csv']
    else:
        nombre = 'parametros_vigentes.csv' if cambio == 'csv' else 'configuracion_resuelta.json'
        fichero = p / nombre
        fichero.write_text(fichero.read_text(encoding='utf-8-sig').replace('2500000', '2600000'),
                           encoding='utf-8-sig' if cambio == 'csv' else 'utf-8')
        entrada = next(x for x in ficha['archivos_control'] if x['ruta'] == nombre)
        entrada.update(bytes=fichero.stat().st_size, sha256=sha256_archivo(fichero))
    volver_a_sellar(p, ficha)
    with pytest.raises(ErrorParametros):
        abrir_ejecucion(proyecto, p)


def test_modificar_excel_no_permite_reabrir_la_misma_referencia(proyecto):
    p = crear(proyecto)
    libro = proyecto / 'config/parametros_modelo.xlsx'
    wb = load_workbook(libro)
    wb['Inicio']['D35'] = 2600000
    wb.save(libro)
    wb.close()
    with pytest.raises(ErrorParametros):
        abrir_ejecucion(proyecto, p)


@pytest.mark.parametrize('accion', ['modificar', 'agregar'])
def test_cambiar_codigo_cambia_la_entrega(proyecto, accion):
    p = crear(proyecto)
    codigo = proyecto / ('src/movilidad_teide/configuracion/estudio.py' if accion == 'modificar' else 'src/modulo_nuevo.py')
    codigo.write_text((codigo.read_text() if codigo.exists() else '') + '\n# otra edición\n')
    with pytest.raises(ErrorParametros):
        abrir_ejecucion(proyecto, p)


def test_gold_se_reserva_para_comparacion_separada(proyecto):
    p = crear(proyecto)
    (proyecto / 'data/gold/resultado.csv').unlink()
    assert abrir_ejecucion(proyecto, p)['comprobacion_actual']['referencias_catalogadas_sin_leer'] == 1
    with pytest.raises(ErrorParametros, match='Falta la entrada'):
        abrir_ejecucion(proyecto, p, comprobar_referencias=True)


@pytest.mark.parametrize('destino', ['data/gold/no', 'config/no', 'docs/no', 'data/silver/ejecuciones'])
def test_protege_las_entradas_y_el_informe(proyecto, destino):
    with pytest.raises(ErrorParametros):
        crear(proyecto, destino=destino)


def test_no_sobrescribe_una_carpeta_existente(proyecto):
    p = crear(proyecto)
    antes = (p / ARCHIVO).read_bytes()
    with pytest.raises(FileExistsError):
        crear(proyecto)
    assert (p / ARCHIVO).read_bytes() == antes


def test_no_utiliza_un_enlace_a_gold_como_destino(proyecto):
    destino = proyecto / 'data/silver/ejecuciones'
    destino.parent.mkdir(parents=True)
    destino.symlink_to(proyecto / 'data/gold', target_is_directory=True)
    with pytest.raises(ErrorParametros, match='enlaces'):
        crear(proyecto)
    assert not (proyecto / 'data/gold/nueva').exists()



def test_registro_numerico_no_exige_anexos_documentales(proyecto):
    indice=proyecto/'config/referencia_ordenacion_2028.json'
    datos=json.loads(indice.read_text());datos['gold_sha256']['data/gold/anexos/balance_anual.csv']='a'*64
    escribir_json(indice,datos);inventariar(proyecto)
    carpeta=crear(proyecto);d=abrir_ejecucion(proyecto,carpeta,comprobar_referencias=True)
    assert not any(x['ruta'].startswith('data/gold/anexos/') for x in d['registro']['fuentes'])
    assert any(x['ruta']=='data/gold/resultado.csv' for x in d['registro']['fuentes'])


def test_registro_no_omite_referencia_numerica_ausente(proyecto):
    indice=proyecto/'config/referencia_ordenacion_2028.json'
    datos=json.loads(indice.read_text());datos['gold_sha256']['data/gold/referencia_anual/falta.csv']='a'*64
    escribir_json(indice,datos);inventariar(proyecto)
    with pytest.raises(ErrorParametros,match='Contrato e inventario'):
        crear(proyecto)
