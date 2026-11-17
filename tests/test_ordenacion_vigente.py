"""Integridad de la referencia y rechazo de mezclas de casos o destinos."""
from pathlib import Path
import json,shutil
import pytest
from openpyxl import load_workbook
from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.configuracion.ordenacion import leer_ordenacion,verificar_entradas,ErrorParametros,LIBRO,INDICE
from movilidad_teide.flujos.ordenacion_vigente import (
    ContextoOrdenacion,_leer,_destino_nuevo,_auditar_oferta,consultar_ordenacion,
    generar_recursos_ordenacion)

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def libro(tmp_path):
    (tmp_path/'config').mkdir()
    for name in [LIBRO,INDICE]:shutil.copy2(ROOT/name,tmp_path/name)
    return tmp_path


def test_referencia_actual_y_elecciones_historicas_se_distinguen():
    ref=leer_ordenacion(ROOT);old=leer_parametros(ROOT)
    assert len(old['parametros'])==129 and len(old['elecciones_todos_los_casos'])==387
    assert next(p['valor_utilizado'] for p in old['parametros'] if p['id']=='cupo_global')==500
    assert ref['valores_modelo']['cupo_global']==650
    assert ref['valores_modelo']['captacion_extranjero']==0
    assert ref['valores']['max_programadas_ordinaria']==27


@pytest.mark.parametrize('value',[700,'=650+50',None])
def test_cambio_de_cupo_sin_nuevas_circulaciones_se_rechaza(libro,value):
    p=libro/LIBRO;wb=load_workbook(p)
    for row in wb['Inicio'].iter_rows(min_row=35):
        if row[0].value=='cupo_ordinario':row[3].value=value
    wb.save(p)
    with pytest.raises(ErrorParametros):leer_ordenacion(libro)


def test_cambio_de_eleccion_inactiva_tambien_invalida_la_referencia(libro):
    p=libro/LIBRO;wb=load_workbook(p)
    for row in wb['Escenarios'].iter_rows(min_row=7):
        if row[0].value=='Variante A' and row[12].value=='cupo_global':
            row[8].value='Otro motivo no perteneciente a esta referencia'
    wb.save(p)
    with pytest.raises(ErrorParametros,match='históricas'):leer_ordenacion(libro)


def test_entrada_ausente_o_distinta_se_rechaza(tmp_path):
    ref={'indice':{'entradas_sha256':{'entrada.csv':'0'*64}}}
    with pytest.raises(ErrorParametros,match='ausente'):verificar_entradas(tmp_path,ref)
    (tmp_path/'entrada.csv').write_text('dato distinto')
    with pytest.raises(ErrorParametros,match='modificada'):verificar_entradas(tmp_path,ref)


def test_no_sobrescribir_entradas_incluso_a_traves_de_enlace(tmp_path):
    real=tmp_path/'datos_reales';real.mkdir();root=tmp_path/'proyecto';root.mkdir();(root/'data').symlink_to(real,target_is_directory=True)
    with pytest.raises(ValueError):_destino_nuevo(root,root/'data/nueva_salida')
    assert not (real/'nueva_salida').exists()


def test_no_sobrescribir_una_ejecucion_anterior(tmp_path):
    (tmp_path/'resultado').mkdir();(tmp_path/'resultado/prueba').write_text('conservar')
    with pytest.raises(FileExistsError):_destino_nuevo(tmp_path/'entrada',tmp_path/'resultado')
    assert (tmp_path/'resultado/prueba').read_text()=='conservar'


def test_consulta_y_exportacion_actual_no_mezclan_el_maestro_anterior(tmp_path):
    d=consultar_ordenacion(ROOT);cal=d['tablas']['calendario_operativo']
    assert len(cal)==366 and abs(cal.visitas_sin_dia.sum()-2500000)<1e-8
    assert cal.groupby('programadas').size().to_dict()=={20:85,23:18,24:110,27:53,28:87,30:13}
    assert cal.externas_programadas.sum()==0 and cal.externas_disponibles.sum()==26
    result=generar_recursos_ordenacion(ROOT,tmp_path/'recursos')
    assert not (tmp_path/'recursos/main.tex').exists()
    assert result['maestro_anterior_copiado'] is False
    assert result['visitas_sin_y_con']==2500000


def test_oferta_con_movimiento_duplicado_no_se_acepta(tmp_path):
    ctx=ContextoOrdenacion(ROOT);op=_leer(ctx.captura/'resultados_operacion.csv');r=next(op[op.cierre].itertuples())
    source=ctx.captura/'ofertas'/str(r.cupo)/str(r.max_programadas)/r.perfil
    for name in ['viajes','reservas','movimientos','objetivos']:shutil.copy2(source/(name+'.csv'),tmp_path/(name+'.csv'))
    m=_leer(tmp_path/'movimientos.csv');import pandas as pd
    pd.concat([m,m.iloc[[0]]],ignore_index=True).to_csv(tmp_path/'movimientos.csv',sep=';',index=False)
    with pytest.raises(AssertionError):_auditar_oferta(ctx,r,tmp_path,_leer(tmp_path/'objetivos.csv'))
