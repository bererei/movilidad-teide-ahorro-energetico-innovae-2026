"""La release contiene solo las tres capas y controles, sin duplicar Git."""
from pathlib import Path
import csv
import hashlib
import importlib.util
import json
import zipfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preparar_release_datos', ROOT / 'preparar_release_datos.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
from movilidad_teide.publicacion.reserva import INICIO, FIN, PATRONES


@pytest.fixture
def proyecto(tmp_path):
    root = tmp_path / 'repo'
    contenido = {
        '.gitignore': INICIO + '\n' + '\n'.join(PATRONES) + '\n' + FIN + '\n',
        'src/calculo.py': 'visitas = 2500000\n',
        'README.md': 'Código y guías en Git.\n',
        'data/bronze/fuente.csv': 'observacion;1\n',
        'data/silver/preparacion.csv': 'preparado;2\n',
        'data/gold/resultado.csv': 'resultado;3\n',
        'docs/informe_energetico/informe.pdf': 'INFORME_EXCLUIDO',
        'data/gold/anexos/anexo.csv': 'ANEXO_EXCLUIDO',
        'manifiestos/referencia.json': json.dumps({'visitas_sin_y_con': 2500000, 'parametros_efectivos': {}}),
    }
    for n, s in contenido.items():
        p = root / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(s)
    nombres = list(contenido) + ['manifiestos/seleccion_entrega_publica.csv', 'manifiestos/condiciones_entrega_publica.csv']
    def tabla(n, filas):
        with (root / n).open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0]), delimiter=';')
            w.writeheader()
            w.writerows(filas)
    tabla('manifiestos/seleccion_entrega_publica.csv', [{'ruta': n, 'decision_final_8_2': 'incluir', 'caso_externo': ''} for n in nombres + ['manifiestos/archivos.json']])
    tabla('manifiestos/condiciones_entrega_publica.csv', [{'condicion': 'ninguna', 'estado': 'no_aplica'}])
    filas = [{'ruta': n, 'bytes': (root / n).stat().st_size,
              'sha256': hashlib.sha256((root / n).read_bytes()).hexdigest()} for n in nombres]
    (root / 'manifiestos/archivos.json').write_text(json.dumps({'version': '2.8', 'archivos': filas}))
    return root


def test_seis_adjuntos_sin_codigo_o_documentos_excluidos(proyecto, tmp_path):
    destino = tmp_path / 'release'
    info = release.preparar_release(proyecto, destino)
    assert {p.name for p in destino.iterdir()} == {
        'datos_bronze.zip', 'datos_silver.zip', 'datos_gold.zip',
        'SHA256SUMS', 'manifiesto_paquetes.json', 'ACEPTACION_PAQUETES.json'}
    miembros = []
    for row in info['paquetes']:
        with zipfile.ZipFile(destino / row['archivo']) as z:
            miembros.extend(z.namelist())
            assert all(n.startswith('data/' + row['capa'] + '/') for n in z.namelist())
            assert not any(b'EXCLUIDO' in z.read(n) for n in z.namelist())
    assert len(miembros) == len(set(miembros)) == 3
    assert not info['codigo_incluido_en_release']
    assert len((destino / 'SHA256SUMS').read_text().splitlines()) == 3
    acta = json.loads((destino / 'ACEPTACION_PAQUETES.json').read_text())
    assert acta['manifiesto_paquetes_sha256'] == release.sha(destino / 'manifiesto_paquetes.json')
    assert acta['SHA256SUMS_sha256'] == release.sha(destino / 'SHA256SUMS')


def test_reusar_datos_exige_mismos_miembros_y_contenido(proyecto, tmp_path):
    primero, segundo = tmp_path / 'uno', tmp_path / 'dos'
    a = release.preparar_release(proyecto, primero)
    b = release.preparar_release(proyecto, segundo, datos_existentes=primero)
    assert a['paquetes'] == b['paquetes']
    assert (primero / 'datos_bronze.zip').read_bytes() == (segundo / 'datos_bronze.zip').read_bytes()


@pytest.mark.parametrize('caso', ['extra', 'ausente', 'alterado', 'duplicado'])
def test_cache_incorrecta_no_se_acepta(proyecto, tmp_path, caso):
    cache = tmp_path / 'cache'
    release.preparar_release(proyecto, cache)
    p = cache / 'datos_bronze.zip'
    with zipfile.ZipFile(p, 'w') as z:
        if caso != 'ausente':
            z.writestr('data/bronze/fuente.csv', 'diferente' if caso == 'alterado' else 'observacion;1\n')
        if caso == 'extra':
            z.writestr('README.md', 'copia del código')
        if caso == 'duplicado':
            with pytest.warns(UserWarning):
                z.writestr('data/bronze/fuente.csv', 'observacion;1\n')
    with pytest.raises(ValueError):
        release.preparar_release(proyecto, tmp_path / 'nuevo', datos_existentes=cache)


def test_no_sobrescribe_destinos_o_fuentes(proyecto, tmp_path):
    with pytest.raises(ValueError):
        release.preparar_release(proyecto, proyecto / 'datos')
    destino = tmp_path / 'ocupado'
    destino.mkdir()
    (destino / 'mantener.txt').write_text('conservar')
    with pytest.raises(FileExistsError):
        release.preparar_release(proyecto, destino)
    assert (destino / 'mantener.txt').read_text() == 'conservar'
