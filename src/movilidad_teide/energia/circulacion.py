"""Condiciones de trabajo sobre geometrías existentes; COPERT nativo sin desnivel añadido."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString


CLASES = {
    'local': {'residential','living_street','service'},
    'convencional': {'primary','secondary','tertiary','unclassified','motorway_link',
                     'trunk_link','primary_link','secondary_link','tertiary_link'},
    'rapida': {'motorway','trunk'},
}
MODOS = {'local':'urban_off_peak','convencional':'rural','rapida':'highway'}


def clasificar_geometrias_existentes(recorridos, vias, *, tolerancia_m=1e-5, por_arista=False):
    """Asociar cada arista existente a vías coincidentes, sin buscar caminos.

    La tolerancia solo resuelve precisión de coordenadas. No mueve trazados,
    añade conexiones o asigna la vía más cercana. La agrupación a entornos es
    una propuesta: las travesías no quedan identificadas por highway.
    """
    keys=['itinerary_id','rol']
    if not set(keys+['length_m','geometry'])<=set(recorridos) or not {'osm_way_id','highway','geometry'}<=set(vias):
        raise ValueError('Faltan geometrías existentes, sus longitudes o etiquetas OSM.')
    if recorridos.empty or vias.empty or recorridos.duplicated(keys).any():
        raise ValueError('Recorridos/vías vacíos o identificadores duplicados.')
    if recorridos.crs is None or vias.crs!=recorridos.crs or not recorridos.crs.is_projected:
        raise ValueError('Las vías y los recorridos deben compartir un CRS proyectado métrico.')
    if not all(abs(a.unit_conversion_factor-1)<1e-12 for a in recorridos.crs.axis_info[:2]):
        raise ValueError('El CRS debe medir las coordenadas en metros.')
    if not np.isfinite(tolerancia_m) or not 0<tolerancia_m<=.001:
        raise ValueError('Tolerancia de coincidencia fuera de la precisión cartográfica admitida.')
    if vias.geometry.is_empty.any() or vias.geometry.isna().any() or not vias.geometry.geom_type.eq('LineString').all():
        raise ValueError('Las vías originales deben ser líneas no vacías.')
    roads=vias.reset_index(drop=True);buffers=roads.geometry.buffer(tolerancia_m);index=roads.sindex
    cache={};rows=[]
    for route in recorridos.itertuples(index=False):
        line=route.geometry;n=float(route.length_m)
        if not isinstance(line,LineString) or line.is_empty or not line.is_valid or not np.isfinite(n) or n<=0:
            raise ValueError('Recorrido o longitud original no válido.')
        if abs(line.length-n)>.01:raise ValueError('La geometría no concuerda con su longitud original; no corregirla automáticamente.')
        lengths={};ways={};tags={};states={};position=0.
        for a,b in zip(line.coords[:-1],line.coords[1:]):
            edge=LineString([a,b]);length=edge.length
            if length==0:continue
            key=tuple(sorted((tuple(a),tuple(b))))
            if key not in cache:
                candidates=[int(i) for i in index.query(edge.buffer(tolerancia_m))
                    if edge.difference(buffers.iloc[int(i)]).length<=tolerancia_m]
                raw={str(roads.iloc[i].highway) for i in candidates}
                classes={next((c for c,values in CLASES.items() if t in values),'pendiente') for t in raw}
                if len(classes)==1 and 'pendiente' not in classes:clase=next(iter(classes));state='Coincidencia cartográfica; entorno propuesto'
                else:clase='pendiente';state='Sin coincidencia unívoca o sin regla de tipología'
                cache[key]=(clase,state,raw,{str(roads.iloc[i].osm_way_id) for i in candidates})
            clase,state,raw,ids=cache[key]
            if por_arista:
                rows.append({'itinerary_id':route.itinerary_id,'rol':route.rol,
                    'clase_propuesta':clase,'distance_start_m':position*n/line.length,
                    'distance_end_m':(position+length)*n/line.length,
                    'length_m':length*n/line.length,'estado':state,
                    'highway_originales':' | '.join(sorted(raw)),
                    'osm_way_ids':' | '.join(sorted(ids))})
            position+=length
            lengths[clase]=lengths.get(clase,0.)+length;ways.setdefault(clase,set()).update(ids)
            tags.setdefault(clase,set()).update(raw);states[clase]=state
        if not lengths or abs(sum(lengths.values())-line.length)>1e-6:
            raise ValueError('La asociación no conserva la longitud de las aristas.')
        if por_arista:continue
        for clase,length in lengths.items():
            rows.append({'itinerary_id':route.itinerary_id,'rol':route.rol,'clase_propuesta':clase,
                'length_m_original':n,'longitud_clase_km':length*n/line.length/1000,
                'diferencia_geometria_longitud_m':line.length-n,
                'highway_originales':' | '.join(sorted(tags[clase])),
                'osm_way_ids':' | '.join(sorted(ways[clase])), 'estado':states[clase]})
    return pd.DataFrame(rows)


def cargar_y_clasificar_referencias(root, *, por_arista=False):
    """Leer las 31 referencias del catálogo, conservando sus componentes y fuentes."""
    from movilidad_teide.cartografia.fuentes_rutas import read_geospatial_source
    from movilidad_teide.trazabilidad import sha256_archivo
    root=Path(root);cfg_path=root/'config/itinerarios.json';cfg=json.loads(cfg_path.read_text())
    folder=root/'data/silver/geografia/accesos_origenes';cache={};huellas={str(cfg_path.relative_to(root)):sha256_archivo(cfg_path)}
    resultados=[];inventario=[]
    for collection in ['origin_access_comparisons','study_origin_access_comparisons','coastal_valley_comparisons']:
        for cid,ficha in cfg[collection].items():
            coastal=collection=='coastal_valley_comparisons'
            directory=folder/('contraste_costero_valle' if coastal else cid)
            path=directory/('contraste_costero_valle.gpkg' if coastal else 'accesos_origenes.gpkg')
            meta_path=directory/'metadatos.json';meta=json.loads(meta_path.read_text())
            rel=str(path.relative_to(root))
            if meta['archivos_sha256' if coastal else 'outputs_sha256'].get(rel)!=sha256_archivo(path):raise ValueError('GeoPackage distinto del producto geográfico verificado: '+rel)
            huellas[rel]=sha256_archivo(path);huellas[str(meta_path.relative_to(root))]=sha256_archivo(meta_path)
            components=gpd.read_file(path,layer='componentes');rows=[]
            if coastal:
                components=components.loc[components.caso.eq(cid)]
                for q in components.itertuples(index=False):
                    role={'directa_tf523':'directa','alimentador_costero':'alimentador','montana':'montana'}[q.alternativa]
                    rows.append({'itinerary_id':q.itinerary_id,'rol':role,'length_m':q.longitud_km*1000,'geometry':q.geometry})
                ids=ficha['directa_itinerary_ids']+ficha['costera_itinerary_ids']
            else:
                direct=gpd.read_file(path,layer='recorridos_directos')
                ids=ficha['itinerary_ids']+ficha.get('feeder_itinerary_ids',[])
                for q in direct.loc[direct.itinerary_id.isin(ficha['itinerary_ids'])].itertuples(index=False):
                    rows.append({'itinerary_id':q.itinerary_id,'rol':'directa','length_m':q.length_m,'geometry':q.geometry})
                for q in components.itertuples(index=False):
                    if q.componente not in {'origen_cabecera','cabecera_teide'}:continue
                    role='alimentador' if q.componente=='origen_cabecera' else 'montana'
                    source=getattr(q,'source_itinerary_id',None)
                    ident=source if isinstance(source,str) and source else q.itinerary_id
                    rows.append({'itinerary_id':ident,'rol':role,'length_m':q.longitud_km*1000,'geometry':q.geometry})
            routes=gpd.GeoDataFrame(rows,geometry='geometry',crs=components.crs)
            sources={p['source_id'] for ident in ids for p in cfg['itineraries'][ident]['axis_parts']}
            roads=[]
            for sid in sorted(sources):
                if sid not in cache:
                    spec=cfg['sources'][sid];source_path=root/spec['path']
                    if sha256_archivo(source_path)!=spec['expected_sha256']:raise ValueError('Fuente de vías modificada: '+sid)
                    huellas[spec['path']]=sha256_archivo(source_path)
                    cache[sid]=read_geospatial_source(sid,cfg,root).to_crs(routes.crs)
                roads.append(cache[sid])
            ways=gpd.GeoDataFrame(pd.concat(roads,ignore_index=True),crs=routes.crs)
            classified=clasificar_geometrias_existentes(routes,ways,por_arista=por_arista)
            resultados.append(classified.assign(comparacion_id=cid))
            inventario.append({'comparacion_id':cid,'coleccion':collection,'archivo_geografico':rel,
                'sha256_geografico':sha256_archivo(path),'componentes':len(routes),
                'nombre_referencia':ficha.get('label',cid)})
    return {'clasificacion':pd.concat(resultados,ignore_index=True),'inventario':pd.DataFrame(inventario),'huellas':huellas}


def calcular_aportes_circulacion(clasificacion, factores, velocidades):
    """Aplicar aportes condicionados por longitud; nunca completar una media de flota."""
    keys=['comparacion_id','itinerary_id','rol']
    required=set(keys+['clase_propuesta','longitud_clase_km'])
    cols=['grupo_servicio','modo','velocidad_kmh','aporte_conjunto_condicionado_min_mj_km','aporte_conjunto_condicionado_max_mj_km']
    if not required<=set(clasificacion) or not set(cols)<=set(factores):raise ValueError('Faltan longitudes clasificadas o aportes COPERT.')
    if clasificacion.duplicated(keys+['clase_propuesta']).any() or factores.duplicated(cols[:3]).any():raise ValueError('Clases o factores repetidos.')
    lengths=pd.to_numeric(clasificacion.longitud_clase_km,errors='coerce')
    if not np.isfinite(lengths).all() or lengths.le(0).any():raise ValueError('Longitudes ausentes o no positivas.')
    for clase in MODOS:
        speed=velocidades.get(clase)
        if speed is not None and (isinstance(speed,bool) or not np.isfinite(speed) or speed<=0 or speed not in set(factores.velocidad_kmh)):
            raise ValueError('Velocidad sin nodo consultado: no se interpola ni se sustituye automáticamente.')
    detail=[]
    for row in clasificacion.to_dict('records'):
        clase=row['clase_propuesta'];speed=velocidades.get(clase);mode=MODOS.get(clase)
        for service in sorted(factores.grupo_servicio.unique()):
            selected=factores.loc[factores.grupo_servicio.eq(service)&factores.modo.eq(mode)&factores.velocidad_kmh.eq(speed)] if mode and speed is not None else factores.iloc[:0]
            if len(selected)>1:raise ValueError('Más de un aporte por condición de circulación.')
            lo=hi=np.nan
            if len(selected)==1:
                lo,hi=selected.iloc[0][cols[-2:]].to_numpy(dtype=float)
                if np.isinf([lo,hi]).any() or np.isfinite(lo)!=np.isfinite(hi) or (np.isfinite(lo) and (lo<0 or hi<lo)):raise ValueError('Aportes condicionados no coherentes.')
            available=np.isfinite(lo) and np.isfinite(hi)
            detail.append({**row,'grupo_servicio':service,'modo_copert':mode,'velocidad_propuesta_kmh':speed,
                'condicion_y_aporte_disponibles':available,'aporte_min_mj':row['longitud_clase_km']*lo,
                'aporte_max_mj':row['longitud_clase_km']*hi})
    d=pd.DataFrame(detail);summary=[]
    for key,g in d.groupby(keys+['grupo_servicio'],sort=True):
        available=bool(g.condicion_y_aporte_disponibles.all())
        lo=g.aporte_min_mj.sum() if available else np.nan;hi=g.aporte_max_mj.sum() if available else np.nan
        summary.append({**dict(zip(keys+['grupo_servicio'],key)),'longitud_km':g.longitud_clase_km.sum(),
            'longitud_sin_condicion_km':g.loc[~g.condicion_y_aporte_disponibles,'longitud_clase_km'].sum(),
            'aporte_min_mj':lo,'aporte_max_mj':hi,'aporte_min_kwh':lo/3.6,'aporte_max_kwh':hi/3.6,
            'energia_total_flota_mj':np.nan,'alcance':'Aporte parcial condicionado por recorrido; no consumo completo, límite físico o ahorro'})
    return {'detalle':d,'resumen':pd.DataFrame(summary)}


def vincular_aportes_a_referencias(recorridos, aportes):
    """Conservar las 82 filas de D126, sus aproximaciones y el caso sin perfil.

    No anualiza personas ni decide modos o coches retirados. Directa, alimentador
    y montaña son piezas alternativas del cálculo, no kilómetros sumables entre sí.
    """
    keys=['origen_id','sentido'];roles={
        'directa':('itinerario_referencia_id','directa_km'),
        'alimentador':('itinerario_alimentador_id','alimentador_km'),
        'montana':('itinerario_montana_referencia_id','montana_km')}
    if not set(keys+['comparacion_calculo_id','tipo_representacion_calculo'])<=set(recorridos) or recorridos.duplicated(keys).any():
        raise ValueError('Referencias geográficas ausentes o duplicadas.')
    if aportes.duplicated(['comparacion_id','itinerary_id','rol','grupo_servicio']).any():raise ValueError('Aportes geográficos repetidos.')
    rows=[]
    for row in recorridos.to_dict('records'):
        for role,(idfield,lenfield) in roles.items():
            for service in sorted(aportes.grupo_servicio.unique()):
                selected=aportes.loc[aportes.comparacion_id.eq(row['comparacion_calculo_id'])&
                    aportes.itinerary_id.eq(row[idfield])&aportes.rol.eq(role)&aportes.grupo_servicio.eq(service)]
                condicional=row['tipo_representacion_calculo']=='condicional_media_nula'
                if len(selected)!=1 and not condicional:
                    raise ValueError('Falta un componente físico de la referencia geográfica: '+str((row['comparacion_calculo_id'],row[idfield],role)))
                extra={k:np.nan for k in ['aporte_min_mj','aporte_max_mj','aporte_min_kwh','aporte_max_kwh']}
                if len(selected)==1:
                    s=selected.iloc[0]
                    if not np.isfinite(row[lenfield]) or abs(s.longitud_km-row[lenfield])>1e-8:
                        raise ValueError('La longitud de circulación no concuerda con D126; no sustituirla.')
                    extra={k:s[k] for k in extra}
                rows.append({**{k:row[k] for k in keys},'comparacion_id':row['comparacion_calculo_id'],
                    'tipo_representacion_calculo':row['tipo_representacion_calculo'],'rol':role,
                    'itinerario_fisico_referencia':row[idfield],'grupo_servicio':service,
                    'longitud_referencia_km':row[lenfield],**extra,
                    'estado':'Sin perfil; conservar ausencia y revisar con demanda positiva' if condicional else
                        'Aporte condicionado de la referencia geográfica, no circulación observada',
                    'energia_total_flota_mj':np.nan})
    return pd.DataFrame(rows)
