"""Integridad del historial y dependencias; los productores pequeños son sintéticos."""
from pathlib import Path
import json
import shutil

import pytest

from test_registro_ejecucion import proyecto, inventariar
from movilidad_teide.configuracion.registro import iniciar_ejecucion, abrir_ejecucion, ARCHIVO
from movilidad_teide.configuracion.productos import leer_estado, bloqueo
from movilidad_teide.configuracion.parametros_tipos import ErrorParametros
from movilidad_teide.flujos import etapas_registradas as flujo
from movilidad_teide.trazabilidad import sha256_archivo


@pytest.fixture
def ejecucion(proyecto):
    return proyecto, iniciar_ejecucion(proyecto, 'data/silver/ejecuciones/prueba', modo='reproduccion')


def productor_sintetico(root, carpeta, datos, etapa, accion, destino, dependencias, **kwargs):
    leidas = {}
    for key, p in dependencias.items():
        leidas[key] = (p / 'tabla.csv').read_text()
    (destino / 'tabla.csv').write_text('visitas\n2500000\n')
    (destino / 'origenes.json').write_text(json.dumps(leidas))
    return dict(sintetico=True, dependencias=list(dependencias))


def ejecutar(ejecucion, monkeypatch, etapa='01', productor=productor_sintetico):
    monkeypatch.setattr(flujo, '_producir', productor)
    root, carpeta = ejecucion
    return flujo.ejecutar_etapa(root, carpeta, etapa)


def estado(ejecucion):
    root, p = ejecucion
    return abrir_ejecucion(root, p)['estado_etapas']


def test_registro_inicial_y_cierre_son_conceptos_distintos(ejecucion, monkeypatch):
    root, p = ejecucion
    inicial = (p / ARCHIVO).read_bytes()
    assert all(x['estado'] == 'pendiente' for x in estado(ejecucion)['etapas'].values())
    ejecutar(ejecucion, monkeypatch)
    e = estado(ejecucion)
    assert e['etapas']['01']['estado'] == 'completada'
    assert e['etapas']['01']['accion'] == 'calcular'
    assert e['productos'] == 3
    assert (p / ARCHIVO).read_bytes() == inicial
    assert json.loads((p / ARCHIVO).read_text())['salidas']['productos_cientificos'] == []


def test_dependencia_incompleta_no_inicia_productor(ejecucion, monkeypatch):
    with pytest.raises(ErrorParametros, match='Primero'):
        ejecutar(ejecucion, monkeypatch, '02')
    assert not (ejecucion[1] / 'resultados/02').exists()


def test_consumidor_recibe_archivo_del_productor_de_la_misma_ejecucion(ejecucion, monkeypatch):
    ejecutar(ejecucion, monkeypatch, '01')
    ejecutar(ejecucion, monkeypatch, '02')
    e = estado(ejecucion)
    a, b = e['etapas']['01'], e['etapas']['02']
    assert b['dependencias'] == {'01': a['evento_sha256']}
    origen = json.loads((ejecucion[1] / b['carpeta'] / 'origenes.json').read_text())
    assert origen == {'01': 'visitas\n2500000\n'}
    assert 'ejecucion:' + a['carpeta'] + '/tabla.csv' in b['lecturas']


def test_producto_alterado_impide_consumirlo(ejecucion, monkeypatch):
    ejecutar(ejecucion, monkeypatch)
    e = estado(ejecucion)['etapas']['01']
    (ejecucion[1] / e['carpeta'] / 'tabla.csv').write_text('alterado\n')
    with pytest.raises(ErrorParametros, match='Producto registrado'):
        ejecutar(ejecucion, monkeypatch, '02')
    assert not (ejecucion[1] / 'resultados/02').exists()


@pytest.mark.parametrize('cambio', ['borrar', 'alterar', 'estado'])
def test_detecta_cadena_incompleta_o_manipulada(ejecucion, monkeypatch, cambio):
    ejecutar(ejecucion, monkeypatch)
    p = ejecucion[1]
    evento = sorted((p / 'eventos').glob('*.json'))[-1]
    if cambio == 'borrar':
        evento.unlink()
    elif cambio == 'alterar':
        evento.write_text(evento.read_text() + ' ')
    else:
        ficha = json.loads((p / 'estado_ejecucion.json').read_text())
        ficha['ultimo_sha256'] = '0' * 64
        (p / 'estado_ejecucion.json').write_text(json.dumps(ficha))
    with pytest.raises(ErrorParametros):
        estado(ejecucion)


def test_no_mezcla_sucesos_de_otro_registro(ejecucion, proyecto, monkeypatch):
    ejecutar(ejecucion, monkeypatch)
    otro = iniciar_ejecucion(proyecto, 'data/silver/ejecuciones/otro')
    shutil.copytree(ejecucion[1] / 'eventos', otro / 'eventos')
    shutil.copy2(ejecucion[1] / 'estado_ejecucion.json', otro / 'estado_ejecucion.json')
    with pytest.raises(ErrorParametros, match='no corresponde'):
        abrir_ejecucion(proyecto, otro)


def test_fallo_conserva_intento_sin_aceptar_productos_y_permite_reintentar(ejecucion, monkeypatch):
    def falla(root, carpeta, datos, etapa, accion, destino, dependencias, **kwargs):
        (destino / 'incompleto.csv').write_text('incompleto\n')
        raise RuntimeError('fallo controlado')
    with pytest.raises(RuntimeError, match='controlado'):
        ejecutar(ejecucion, monkeypatch, productor=falla)
    p = ejecucion[1]
    e = estado(ejecucion)
    fallida = e['etapas']['01']
    assert fallida['estado'] == 'fallida' and e['productos'] == 0
    assert (p / fallida['carpeta'] / 'incompleto.csv').exists()
    ejecutar(ejecucion, monkeypatch)
    e = estado(ejecucion)
    assert e['etapas']['01']['estado'] == 'completada'
    assert e['etapas']['01']['carpeta'] != fallida['carpeta']
    assert len(e['eventos']) == 4


def test_no_sobrescribe_etapa_ya_completada(ejecucion, monkeypatch):
    ejecutar(ejecucion, monkeypatch)
    anterior = (ejecucion[1] / 'estado_ejecucion.json').read_bytes()
    with pytest.raises(ErrorParametros, match='ya está completada'):
        ejecutar(ejecucion, monkeypatch)
    assert (ejecucion[1] / 'estado_ejecucion.json').read_bytes() == anterior


def test_gold_no_puede_preparar_un_resultado(ejecucion, monkeypatch):
    def leer_gold(root, carpeta, datos, etapa, accion, destino, dependencias, **kwargs):
        (root / 'data/gold/resultado.csv').read_text()
    with pytest.raises(PermissionError, match='Gold solo'):
        ejecutar(ejecucion, monkeypatch, productor=leer_gold)
    assert estado(ejecucion)['etapas']['01']['estado'] == 'fallida'


def test_productor_no_puede_modificar_una_entrada(ejecucion, monkeypatch):
    root, p = ejecucion
    fuente = root / 'data/bronze/entrada.csv'
    antes = fuente.read_bytes()
    def escribir(root, carpeta, datos, etapa, accion, destino, dependencias, **kwargs):
        (root / 'data/bronze/entrada.csv').write_text('otra\n')
    with pytest.raises(PermissionError, match='modificar una entrada'):
        ejecutar(ejecucion, monkeypatch, productor=escribir)
    assert fuente.read_bytes() == antes


def test_escritores_no_compiten_por_el_mismo_estado(ejecucion):
    with bloqueo(ejecucion[1]):
        with pytest.raises(ErrorParametros, match='otra etapa'):
            with bloqueo(ejecucion[1]):
                pytest.fail('No debe adquirir un segundo bloqueo')


def test_accion_incompatible_no_inicia_la_etapa(ejecucion):
    with pytest.raises(ErrorParametros, match='acción'):
        flujo.ejecutar_etapa(ejecucion[0], ejecucion[1], '01', accion='ejecutar_motor')
    assert not list((ejecucion[1] / 'resultados').iterdir())


def test_reapertura_en_proceso_nuevo_consulta_estado_durable(ejecucion, monkeypatch, tmp_path):
    import subprocess, sys, os
    ejecutar(ejecucion, monkeypatch)
    root, p = ejecucion
    codigo = """from movilidad_teide.configuracion.registro import abrir_ejecucion
import sys
e=abrir_ejecucion(sys.argv[1],sys.argv[2]);assert e['estado_etapas']['etapas']['01']['estado']=='completada'
print(e['estado_etapas']['productos'])
"""
    r = subprocess.run([sys.executable, '-B', '-c', codigo, str(root), str(p)],
                       cwd=tmp_path, env={**os.environ, 'PYTHONPATH': str(root / 'src')},
                       capture_output=True, text=True, check=True)
    assert r.stdout.strip() == '3'


def test_consultar_factores_no_se_anuncia_como_motor_nuevo(ejecucion, monkeypatch):
    from movilidad_teide.vehiculos import copert_publico
    from movilidad_teide.configuracion.registro import resumen_ejecucion
    def comparar(package, source, reference=None, destination=None):
        (destination / 'factores_autocar.parquet').write_bytes(b'prueba sintetica')
        return dict(motor_copert_ejecutado=True,motor_copert_ejecutado_en_esta_llamada=False,
                    factores_comparados=5294,maxima_diferencia_mj_km=0.,tolerancia_absoluta_mj_km=1e-12)
    monkeypatch.setattr(copert_publico,'compare_package',comparar)
    flujo.ejecutar_etapa(ejecucion[0],ejecucion[1],'05',accion='consultar')
    r=resumen_ejecucion(abrir_ejecucion(*ejecucion))
    assert r['etapas']['05']['estado']=='completada'
    assert not r['motor_copert_ejecutado_en_esta_ejecucion']


def test_solicitar_motor_sin_ejecutarlo_no_es_ejecucion_acreditada(ejecucion):
    from movilidad_teide.configuracion.registro import resumen_ejecucion
    with pytest.raises(ErrorParametros,match='requiere'):
        flujo.ejecutar_etapa(ejecucion[0],ejecucion[1],'05',accion='ejecutar_motor')
    r=resumen_ejecucion(abrir_ejecucion(*ejecucion))
    assert r['etapas']['05']['estado']=='fallida'
    assert not r['motor_copert_ejecutado_en_esta_ejecucion']


def test_reanudar_intento_interrumpido_conserva_parciales(ejecucion,monkeypatch):
    from movilidad_teide.configuracion.productos import preparar_intento
    root,p=ejecucion
    with bloqueo(p):
        destino,_,_=preparar_intento(p,sha256_archivo(p/ARCHIVO),'01','calcular')
        (destino/'parcial.csv').write_text('parcial\n')
    ejecutar(ejecucion,monkeypatch)
    e=estado(ejecucion)
    assert [x['estado'] for x in e['eventos']]==['iniciada','fallida','iniciada','completada']
    assert (destino/'parcial.csv').exists()

