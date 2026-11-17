"""Protecciones de la reconstrucción; no duplican las fórmulas científicas."""
from pathlib import Path
import hashlib,json,math
import pytest
from movilidad_teide.energia.preparacion_osrm import coincide_nodo,clase_unica,leer_vias
from movilidad_teide.flujos.preparacion_balance import entradas_declaradas,verificar_fuentes


def contrato(root,names):
    (root/'manifiestos').mkdir(exist_ok=True)
    content={'visitas_sin_y_con':2500000,'fuentes_sha256':{n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in names}}
    (root/'manifiestos/preparacion_balance.json').write_text(json.dumps(content))
    return content


def fuente(root,name,contents='fuente'):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(contents);return p


@pytest.mark.parametrize('a,b',[
    ((-16.7404684,28.1229265),(-16.740468,28.122927)),
    ((-16.7404685,28.1229264),(-16.740469,28.122926)),
])
def test_identidad_admite_semicelda_y_redondeo_binario(a,b):
    assert coincide_nodo(a,b)


def test_identidad_rechaza_nodo_proximo_fuera_del_protocolo():
    assert not coincide_nodo((-16.740468,28.122926),(-16.740468,28.122928))


@pytest.mark.parametrize('classes', [set(),{'local','rapida'},{'pendiente'},{'local','pendiente'}])
def test_ambiguedad_se_conserva(classes):
    assert clase_unica(classes)=='pendiente'


def test_via_parcial_conserva_identidad_sin_inventar_geometria(tmp_path):
    p=fuente(tmp_path,'data/bronze/parcial.osm','''<osm>
    <node id="1" lon="-16.7" lat="28.1"/><node id="2" lon="-16.6" lat="28.2"/>
    <way id="9"><nd ref="1"/><nd ref="2"/><nd ref="3"/><tag k="highway" v="primary"/></way></osm>''')
    by_coords,by_nodes,points,geometries=leer_vias([p])
    assert by_nodes[('2','3')]=={'convencional'}
    assert len(by_coords)==1 and not geometries
    assert '3' not in points


def test_contrato_detecta_ausencia_y_alteracion(tmp_path):
    p=fuente(tmp_path,'data/bronze/entrada.csv');contrato(tmp_path,['data/bronze/entrada.csv'])
    verificar_fuentes(tmp_path);p.write_text('alterada')
    with pytest.raises(ValueError,match='ausente o alterada'):verificar_fuentes(tmp_path)
    p.unlink()
    with pytest.raises(ValueError,match='ausente o alterada'):verificar_fuentes(tmp_path)


@pytest.mark.parametrize('name',['data/gold/resultado.csv','data/silver/energia/coef.csv','data/silver/geografia/perfil.csv','data/silver/vehiculos/ponderacion/factores.csv'])
def test_contrato_no_admite_resultados_previos(tmp_path,name):
    fuente(tmp_path,name);contrato(tmp_path,[name])
    with pytest.raises(ValueError,match='resultado físico o energético'):verificar_fuentes(tmp_path)


def test_auditoria_denega_gold_y_coeficientes_aunque_existan(tmp_path):
    allowed=fuente(tmp_path,'data/silver/operacion/eleccion.csv');gold=fuente(tmp_path,'data/gold/resultado.csv');old=fuente(tmp_path,'data/silver/energia/coef.csv');new=tmp_path/'nueva';new.mkdir()
    with entradas_declaradas(tmp_path,new,{'data/silver/operacion/eleccion.csv'}) as reads:
        assert allowed.read_text()=='fuente'
        with pytest.raises(PermissionError,match='no declarado'):gold.read_text()
        with pytest.raises(PermissionError,match='no declarado'):old.read_text()
        (new/'resultado.csv').write_text('calculado');assert (new/'resultado.csv').read_text()=='calculado'
    assert 'data/silver/operacion/eleccion.csv' in reads


def test_fuente_no_puede_escapar_por_enlace(tmp_path):
    outside=tmp_path/'fuera.csv';outside.write_text('fuera');root=tmp_path/'proyecto';root.mkdir();p=root/'data/bronze';p.mkdir(parents=True);(p/'enlace.csv').symlink_to(outside)
    contrato(root,['data/bronze/enlace.csv'])
    with pytest.raises(ValueError,match='no portable'):verificar_fuentes(root)


def test_union_rechaza_perder_longitud_o_invertir_desnivel():
    import pandas as pd
    from movilidad_teide.energia.preparacion_vial import verificar_union
    source=pd.DataFrame({'distance_start_m':[0.],'distance_end_m':[100.],'length_m':[100.],'elevation_start_m':[20.],'elevation_end_m':[30.]})
    split=pd.DataFrame({'distance_start_m':[0.,50.],'distance_end_m':[50.,100.],'length_m':[50.,50.],'elevation_start_m':[20.,25.],'elevation_end_m':[25.,30.]})
    verificar_union(source,split)
    wrong=split.copy();wrong.loc[1,'length_m']=49.
    with pytest.raises(ValueError,match='longitud o desnivel'):verificar_union(source,wrong)
    wrong=split.copy();wrong.loc[1,'elevation_end_m']=20.
    with pytest.raises(ValueError,match='longitud o desnivel'):verificar_union(source,wrong)
