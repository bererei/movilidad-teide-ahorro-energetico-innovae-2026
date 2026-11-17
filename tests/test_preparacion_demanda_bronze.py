"""Evitar filtros ocultos, cambios de fuentes y reutilización de intermedios."""
from pathlib import Path
import json
import pandas as pd
import pytest
from movilidad_teide.fuentes.preparacion_demanda import preparar_od,parametros_de_origen_aforos
from movilidad_teide.flujos.preparacion_demanda import solo_fuentes,comparar_tabla,verificar_fuentes


def consulta(root,idx,direction,mode,stamp='20200101',quantity=1.25,country=False):
    p=root/'data/bronze/demanda/odviewer/api'/('matriz_'+str(idx))/(direction+'_'+mode)/stamp;p.mkdir(parents=True)
    params={'id_matriz2025':idx,('destino2025' if direction=='hacia_teide' else 'origen2025'):'[187,222]'}
    if mode=='privado':params['modo2025']=2
    if country:params['pais_residencia2025']='[1,2]'
    m={'matriz':{'idMatriz':idx,'anio':2025,'mes':3,'tipoDia':'laborable','nombreDia':'Referencia '+str(idx)},'sentido':direction,'modo':mode,'parametros':params}
    (p/'metadata.json').write_text(json.dumps(m));a,b=(1,187) if direction=='hacia_teide' else (187,1)
    (p/'viajes_od.json').write_text(json.dumps([{'origen':a,'destino':b,'viajes':quantity}]))
    (p/'viajes_horarios.json').write_text(json.dumps([{'origen':a,'destino':b,'id_periodo':0,'viajes':quantity}]))
    return p


def test_una_captura_posterior_con_filtro_no_sustituye_la_consulta_completa(tmp_path):
    for i in range(9):
        for d in ['hacia_teide','desde_teide']:
            for m in ['privado','todos_modos']:consulta(tmp_path,i,d,m)
    consulta(tmp_path,0,'hacia_teide','privado',stamp='20990101',quantity=999.,country=True)
    summary,profiles=preparar_od(tmp_path)
    assert len(summary)==36 and summary.viajes_total.eq(1.25).all()
    assert len(profiles)==36 and profiles.viajes.eq(1.25).all()
    assert not summary.fuente.str.contains('20990101').any()


@pytest.mark.parametrize('layer',['silver','gold'])
def test_preparador_rechaza_lecturas_de_intermedios_y_resultados(tmp_path,layer):
    p=tmp_path/'data'/layer/'dato.csv';p.parent.mkdir(parents=True);p.write_text('cantidad\n100\n')
    with solo_fuentes(tmp_path):
        with pytest.raises(PermissionError,match='Bronze'):p.read_text()
    assert '100' in p.read_text()


def test_un_enlace_desde_bronze_no_oculta_una_dependencia_silver(tmp_path):
    p=tmp_path/'data/silver/dato.csv';p.parent.mkdir(parents=True);p.write_text('100')
    q=tmp_path/'data/bronze/enlace.csv';q.parent.mkdir();q.symlink_to(p)
    with solo_fuentes(tmp_path):
        with pytest.raises(PermissionError):q.read_text()


def test_fuente_ausente_da_error_antes_de_calcular(tmp_path):
    m=tmp_path/'manifiestos/preparacion_demanda_bronze.json';m.parent.mkdir();m.write_text(json.dumps({'visitas_sin_y_con':2500000,'fuentes_sha256':{'data/bronze/falta.csv':'0'*64}}))
    with pytest.raises(ValueError,match='ausente o alterada'):verificar_fuentes(tmp_path)


def test_original_de_parametros_aforos_no_admite_sustitucion_silenciosa(tmp_path):
    p=tmp_path/'data/bronze/documentacion/preparacion_aforos';p.mkdir(parents=True)
    (p/'libro.xlsx').write_text('modificado');(p/'procedencia.json').write_text(json.dumps({'archivo':'libro.xlsx','sha256':'0'*64}))
    with pytest.raises(ValueError,match='Libro de origen'):parametros_de_origen_aforos(tmp_path)


@pytest.mark.parametrize('change',['cantidad','ausencia','duplicado','identificador'])
def test_equivalencia_no_admite_perder_o_alterar_demanda(change):
    b=pd.DataFrame({'origen':['A','B'],'personas':[1.25,2.5]});a=b.copy()
    if change=='cantidad':a.loc[0,'personas']+=1e-5
    elif change=='ausencia':a.loc[0,'personas']=float('nan')
    elif change=='duplicado':a.loc[1,'origen']='A'
    else:a.loc[1,'origen']='C'
    with pytest.raises(ValueError):comparar_tabla(a,b,['origen'])


def test_equivalencia_conserva_decimales_y_admite_distinto_orden_de_filas():
    b=pd.DataFrame({'origen':['A','B'],'personas':[1.25,2.5]})
    assert comparar_tabla(b.iloc[::-1],b,['origen'])['maxima_diferencia_absoluta']==0
