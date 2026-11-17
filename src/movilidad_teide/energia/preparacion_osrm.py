"""Reconstruir clases de vía de los accesos OSRM conservando las ambigüedades."""
from pathlib import Path
from collections import defaultdict
import json,math,xml.etree.ElementTree as ET
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString
from pyproj import Transformer
from movilidad_teide.energia.circulacion import CLASES
from movilidad_teide.energia.pendiente import recortar_intervalos
from movilidad_teide.energia.preparacion_vial import verificar_union

FUENTE='data/bronze/geografia/osm/accesos_reasignados_20261109'
PRECISION_PROTOCOLO_M=2*math.sqrt(2)*111320*.5e-6


def clase_unica(classes):
    return next(iter(classes)) if len(classes)==1 and 'pendiente' not in classes else 'pendiente'



def coincide_nodo(nativo,cuantizado):
    """Semicelda del protocolo 1e-6 grados, admitiendo solo redondeo binario.

    La identidad procede de OSRM. Esta comprobación rechaza un nodo distinto
    aunque esté cerca; no amplía la banda ni elige la carretera más próxima.
    """
    return all(abs(a-b)<=.5e-6+8*max(math.ulp(a),math.ulp(b)) for a,b in zip(nativo,cuantizado))

def leer_vias(paths,procedencia=None):
    """Asociar pares exactos de coordenadas/nodos y conservar las vías originales."""
    by_coordinates=defaultdict(set);by_nodes=defaultdict(set);coordinates={};geometries=[];seen=set()
    for path in paths:
        tree=ET.parse(path).getroot()
        source='data/bronze/'+str(path).split('/data/bronze/',1)[1]
        nodes={n.attrib['id']:(round(float(n.attrib['lon']),6),round(float(n.attrib['lat']),6)) for n in tree.findall('node')}
        coordinates.update({n.attrib['id']:(float(n.attrib['lon']),float(n.attrib['lat'])) for n in tree.findall('node')})
        for way in tree.findall('way'):
            tags={t.attrib['k']:t.attrib['v'] for t in way.findall('tag')};refs=[n.attrib['ref'] for n in way.findall('nd')]
            if 'highway' not in tags or len(refs)<2:continue
            road=next((key for key,values in CLASES.items() if tags['highway'] in values),'pendiente')
            for a,b in zip(refs,refs[1:]):
                by_nodes[tuple(sorted((a,b)))].add(road)
                if procedencia is not None:procedencia.setdefault(('nodos',tuple(sorted((a,b)))),set()).add(way.attrib['id']+'@'+source)
                if a in nodes and b in nodes:
                    by_coordinates[tuple(sorted((nodes[a],nodes[b])))].add(road)
                    if procedencia is not None:procedencia.setdefault(('coordenadas',tuple(sorted((nodes[a],nodes[b])))),set()).add(way.attrib['id']+'@'+source)
            if set(refs)<=nodes.keys() and way.attrib['id'] not in seen:
                seen.add(way.attrib['id']);geometries.append({'osm_way_id':way.attrib['id'],'clase':road,'fuente_osm':source,'geometry':LineString([nodes[n] for n in refs])})
    return by_coordinates,by_nodes,coordinates,geometries


def clasificar_reasignados(prep,selection):
    """Repetir coincidencias exactas y banda de cuantización; no buscar otra ruta."""
    root=prep.root;folder=root/FUENTE;native=root/'data/bronze/geografia/rutas_cabeceras/20261108_osrm'
    base_paths=sorted(p for p in (root/'data/bronze/geografia/osm').rglob('*.osm') if not p.is_relative_to(folder))
    provenance={};base,base_nodes,base_points,_=leer_vias(base_paths,provenance)
    extension,extra_nodes,extra_points,_=leer_vias([folder/'vias_rutas_osm.xml'],provenance)
    metadata=json.loads((folder/'control_vias_api.json').read_text())+json.loads((folder/'control_vias_bbox.json').read_text())
    api_paths=[folder/x['archivo'] for x in metadata if 'archivo' in x]
    api_provenance={};api,_,_,features=leer_vias(api_paths,api_provenance)
    roads=gpd.GeoDataFrame(features,crs=4326).to_crs(4083);index=roads.sindex
    transform=Transformer.from_crs(4326,4083,always_xy=True)
    node_points={**base_points,**extra_points};node_classes=defaultdict(set)
    for registry in [base_nodes,extra_nodes]:
        for key,values in registry.items():node_classes[key].update(values)
    rows=[]
    for name in selection:
        print('Clasificación OSRM:',name,flush=True)
        original=json.loads((native/name).read_text())['routes'][0]
        annotated=json.loads((folder/name).read_text())['routes'][0]
        if original['geometry']!=annotated['geometry'] or original['distance']!=annotated['distance']:
            raise ValueError('Las anotaciones no corresponden a la geometría de referencia.')
        coords=original['geometry']['coordinates'];nodes=[str(int(n)) for n in annotated['legs'][0]['annotation']['nodes']]
        if len(nodes)!=len(coords):raise ValueError('Nodos OSRM sin correspondencia geométrica completa.')
        line=gpd.GeoSeries([LineString(coords)],crs=4326).to_crs(4083).iloc[0];position=0.
        for i,(a,b) in enumerate(zip(coords,coords[1:])):
            edge=LineString(line.coords[i:i+2]);length=edge.length
            key=tuple(sorted((tuple(a),tuple(b))))
            prior=clase_unica(base[key]);extra=clase_unica(extension[key])
            if prior=='pendiente' and extra!='pendiente':prior=extra
            # Un identificador solo se usa si sus coordenadas nativas confirman
            # las dos posiciones de la geometría, incluidos sus extremos.
            pair=nodes[i:i+2]
            verified=all(node in node_points and coincide_nodo(node_points[node],point) for node,point in zip(pair,[a,b]))
            identified=clase_unica(node_classes[tuple(sorted(pair))]) if verified else 'pendiente'
            if prior=='pendiente' and identified!='pendiente':prior=identified
            sources=api_provenance.get(('coordenadas',key),set())
            road=clase_unica(api[key]);method='Par exacto de coordenadas al protocolo OSRM de seis decimales'
            if road=='pendiente' and prior!='pendiente':
                road=prior;method='Coincidencia exacta de coordenadas o identidad nativa de nodos'
                sources=set(provenance.get(('coordenadas',key),set()))
                if verified:sources.update(provenance.get(('nodos',tuple(sorted(pair))),set()))
            if road=='pendiente':
                # La banda viene del protocolo: toda la arista debe estar
                # cubierta y todos los candidatos deben indicar la misma clase.
                candidates=[int(k) for k in index.query(edge.buffer(PRECISION_PROTOCOLO_M))
                    if edge.difference(roads.geometry.iloc[int(k)].buffer(PRECISION_PROTOCOLO_M)).length<1e-5]
                road=clase_unica(set(roads.iloc[candidates].clase))
                sources={r.osm_way_id+'@'+r.fuente_osm for r in roads.iloc[candidates].itertuples()}
                method='Cobertura completa y clase unívoca; banda de cuantización OSRM a 1e-6 grados'
            rows.append({'itinerary_id':name,'rol':'alimentador','comparacion_id':name.rsplit('_',1)[0],
                'segment_id':i,'distance_start_m':position,'distance_end_m':position+length,'length_m':length,
                'clase_propuesta':road,'criterio_clasificacion':method,'identidad_nodos_confirmada':verified,'nodos_osrm':'|'.join(pair),'vias_y_fuentes_osm':'|'.join(sorted(sources))})
            position+=length
        if abs(position-line.length)>1e-6:raise ValueError('La clasificación pierde longitud de trazado.')
    return pd.DataFrame(rows)


def unir_reasignados(prep,roads):
    """Partir por vía/perfil y expresar solo la abscisa en kilómetros de actividad."""
    profiles=prep.tables['cabeceras/ordinarias/segmentos']
    catalog=pd.read_csv(prep.root/'data/bronze/geografia/rutas_cabeceras/20261108_osrm/catalogo.csv',sep=';',float_precision='round_trip').set_index('archivo')
    pieces=[]
    for scenario in ['local','convencional','rapida']:
        for name,group in roads.groupby('itinerary_id',sort=False):
            profile=profiles.loc[profiles.itinerary_id.eq(name)].copy();r=group.copy()
            r.loc[r.clase_propuesta.eq('pendiente'),'clase_propuesta']=scenario
            cut=recortar_intervalos(profile,r);verificar_union(profile,cut)
            ratio=catalog.loc[name,'km']*1000/float(profile.length_m.sum())
            cut[['distance_start_m','distance_end_m','length_m']]*=ratio
            cut['slope_pct']=100*(cut.elevation_end_m-cut.elevation_start_m)/cut.length_m
            cut['clase_sensibilidad_residuo']=scenario;cut['factor_abscisa_API_geometria']=ratio
            if abs(cut.length_m.sum()-catalog.loc[name,'km']*1000)>1e-6:raise ValueError('No se conserva la distancia de actividad.')
            pieces.append(cut)
    return pd.concat(pieces,ignore_index=True)
