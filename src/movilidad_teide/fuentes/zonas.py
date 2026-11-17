"""Lectores de zonas; conservo formatos, ausencias y procedencia."""
import json
import zipfile
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely import make_valid, union_all, is_valid_reason

def componentes_poligonales(geometria):
    if geometria.geom_type in {'Polygon', 'MultiPolygon'}:
        return geometria
    partes = [componentes_poligonales(g) for g in geometria.geoms if g.geom_type in {'Polygon', 'MultiPolygon', 'GeometryCollection'}]
    return union_all(partes)

def leer_poligonos(nombre, *, zip_zonas, crs_metrico, incidencias):
    CRS_METRICO = crs_metrico
    ZIP_ZONAS = Path(zip_zonas)
    with zipfile.ZipFile(ZIP_ZONAS) as archivo:
        datos = json.loads(archivo.read(nombre + '.geojson'))
    if datos.get('crs', {}).get('properties', {}).get('name') != 'urn:ogc:def:crs:OGC:1.3:CRS84':
        raise ValueError('Reviso el sistema de coordenadas de la fuente.')
    capa = gpd.GeoDataFrame.from_features(datos['features'], crs='EPSG:4326')
    capa = capa.loc[capa.geom_type.isin(['Polygon', 'MultiPolygon'])].copy()
    if capa['ID'].duplicated().any() or capa['ID'].isna().any():
        raise ValueError('Los polígonos no tienen identificadores únicos.')
    capa['geometria_reparada'] = ~capa.is_valid
    for indice in capa.index[capa['geometria_reparada']]:
        original = capa.loc[indice, 'geometry']
        reparada = make_valid(original)
        poligonal = componentes_poligonales(reparada)
        antes = gpd.GeoSeries([original], crs=capa.crs).to_crs(CRS_METRICO).area.iloc[0]
        despues = gpd.GeoSeries([poligonal], crs=capa.crs).to_crs(CRS_METRICO).area.iloc[0]
        incidencias.append({'capa': nombre, 'id': int(capa.loc[indice, 'ID']), 'motivo': is_valid_reason(original), 'tipo_make_valid': reparada.geom_type, 'extraccion_poligonal': reparada.geom_type == 'GeometryCollection', 'area_antes_m2': antes, 'area_despues_m2': despues, 'diferencia_area_m2': despues - antes})
        capa.loc[indice, 'geometry'] = poligonal
    capa = capa.to_crs(CRS_METRICO)
    if not capa.is_valid.all() or capa.is_empty.any() or capa.geometry.isna().any():
        raise ValueError('Reviso las geometrías antes de continuar.')
    return capa

def cruzar_referencias(administrativa, identificador, nombre, *, zonas):
    cruce = gpd.overlay(zonas[['zona_id', 'geometry']], administrativa[[identificador, nombre, 'geometry']], how='intersection', keep_geom_type=False)
    cruce['area_interseccion_m2'] = cruce.area
    cruce = cruce.loc[cruce['area_interseccion_m2'] > 0].copy()
    areas = zonas.set_index('zona_id').area
    cruce['porcentaje_area_zona'] = 100 * cruce['area_interseccion_m2'] / cruce['zona_id'].map(areas)
    cobertura = cruce.groupby('zona_id')['porcentaje_area_zona'].sum()
    if set(cobertura.index) != set(zonas['zona_id']) or not cobertura.between(99.9, 100.1).all():
        raise ValueError('Reviso la cobertura del cruce territorial.')
    principal = cruce.sort_values('area_interseccion_m2', ascending=False).drop_duplicates('zona_id')
    principal = principal[['zona_id', identificador, nombre, 'porcentaje_area_zona']].rename(columns={identificador: identificador + '_principal', nombre: nombre + '_principal', 'porcentaje_area_zona': 'pct_area_' + nombre + '_principal'})
    lista = cruce.loc[cruce['porcentaje_area_zona'] >= 1].groupby('zona_id')[nombre].agg(lambda valores: ' | '.join(sorted(set(valores))))
    principal[nombre + '_referencias'] = principal['zona_id'].map(lista)
    principal['pct_cobertura_' + nombre] = principal['zona_id'].map(cobertura)
    return (principal, pd.DataFrame(cruce.drop(columns='geometry')))
