"""Impedir que una equivalencia o lectura parcial oculte un cambio geográfico."""
from pathlib import Path
import json,zipfile
import geopandas as gpd
import pytest
from shapely.geometry import LineString,Point
from movilidad_teide.cartografia.preparacion import catalogo_nativo
from movilidad_teide.fuentes.preparacion_demanda import GTFS
from movilidad_teide.flujos.preparacion_geografia import comparar_geometria,solo_fuentes,verificar_fuentes


def frame(geometry,crs=4083):
    return gpd.GeoDataFrame({'id':['ruta'],'geometry':[geometry]},crs=crs)


@pytest.mark.parametrize('other',[
    LineString([(0,0),(0,1),(1,1)]),
    LineString([(1,1),(1,0),(0,0)]),
    LineString([(0,0),(.5,0),(1,0),(1,1)]),
])
def test_misma_longitud_no_basta_si_cambia_la_geometria_o_su_sentido(other):
    original=LineString([(0,0),(1,0),(1,1)])
    assert original.length==other.length
    with pytest.raises(ValueError):comparar_geometria(frame(original),frame(other),['id'])


def test_coordenadas_iguales_con_crs_distinto_no_son_equivalentes():
    line=LineString([(300000,3100000),(300001,3100001)])
    with pytest.raises(ValueError,match='CRS'):comparar_geometria(frame(line),frame(line,25828),['id'])


def test_geometria_reordenada_por_clave_se_conserva():
    a=gpd.GeoDataFrame({'id':['A','B'],'geometry':[Point(1,2),Point(3,4)]},crs=4083)
    assert comparar_geometria(a.iloc[::-1],a,['id'])==0


@pytest.mark.parametrize('layer',['silver','gold'])
def test_no_leer_capas_preparadas_aunque_existan(tmp_path,layer):
    p=tmp_path/'data'/layer/'dato';p.parent.mkdir(parents=True);p.write_text('anterior')
    with solo_fuentes(tmp_path,tmp_path/'data/silver/ejecuciones/nueva'):
        with pytest.raises(PermissionError):p.read_text()


def test_solo_el_destino_nuevo_puede_proporcionar_terreno_derivado(tmp_path):
    target=tmp_path/'data/silver/ejecuciones/nueva';target.mkdir(parents=True)
    with solo_fuentes(tmp_path,target):
        p=target/'terreno';p.write_text('recién derivado');assert p.read_text()=='recién derivado'


def test_un_enlace_bronze_no_oculta_una_lectura_silver(tmp_path):
    p=tmp_path/'data/silver/anterior';p.parent.mkdir(parents=True);p.write_text('anterior')
    q=tmp_path/'data/bronze/fuente';q.parent.mkdir();q.symlink_to(p)
    with solo_fuentes(tmp_path,tmp_path/'resultado'):
        with pytest.raises(PermissionError):q.read_text()


def test_fuente_alterada_se_detecta_antes_de_extraer_geometrias(tmp_path):
    p=tmp_path/'data/bronze/fuente';p.parent.mkdir(parents=True);p.write_text('alterada')
    m=tmp_path/'manifiestos/preparacion_geografia_bronze.json';m.parent.mkdir();m.write_text(json.dumps({'visitas_sin_y_con':2500000,'fuentes_sha256':{'data/bronze/fuente':'0'*64}}))
    with pytest.raises(ValueError,match='alterada'):verificar_fuentes(tmp_path)


def test_referencias_gtfs_se_derivan_del_zip_sin_un_geopackage_preparado(tmp_path):
    c=tmp_path/'config/itinerarios.json';c.parent.mkdir()
    names=['titsa_stop_references','titsa_route_references','titsa_route_metadata']
    c.write_text(json.dumps({'sources':{k:{'path':'data/silver/no_disponible.gpkg'} for k in names}}))
    p=tmp_path/GTFS;p.parent.mkdir(parents=True)
    tables={'stops':'stop_id,stop_lon,stop_lat\n4009,-16.5,28.4\n',
      'routes':'route_id,route_short_name\nR,342\n','trips':'route_id,shape_id\nR,S\n',
      'shapes':'shape_id,shape_pt_sequence,shape_pt_lon,shape_pt_lat\nS,1,-16.5,28.4\nS,2,-16.51,28.41\n'}
    with zipfile.ZipFile(p,'w') as z:
        for name,value in tables.items():z.writestr(name+'.txt',value)
    catalog,sources,_,resolution=catalogo_nativo(tmp_path)
    point=sources['titsa_stop_references'].set_index('stop_id').loc['4009'].geometry
    assert (point.x,point.y)==(-16.5,28.4)
    assert all(catalog['sources'][k]['path']==GTFS for k in names)
    assert len(resolution)==3
