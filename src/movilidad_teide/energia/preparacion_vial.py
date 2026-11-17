"""Clasificación y unión física sobre geometrías y perfiles recién reconstruidos."""
import json
import geopandas as gpd
import pandas as pd
from movilidad_teide.energia.circulacion import clasificar_geometrias_existentes
from movilidad_teide.energia.pendiente import recortar_intervalos



def verificar_union(perfil,union):
    """La partición conserva longitud y desnivel firmado, sin rellenos."""
    import numpy as np
    fields=['distance_start_m','distance_end_m','length_m','elevation_start_m','elevation_end_m']
    if union.empty or not np.isfinite(union[fields].to_numpy(float)).all() or union.length_m.le(0).any():
        raise ValueError('Unión de perfil y vía vacía o no física.')
    source=np.array([perfil.length_m.sum(),(perfil.elevation_end_m-perfil.elevation_start_m).sum()])
    target=np.array([union.length_m.sum(),(union.elevation_end_m-union.elevation_start_m).sum()])
    if not np.allclose(source,target,rtol=0,atol=1e-6):
        raise ValueError('La unión altera longitud o desnivel firmado del perfil.')

def componentes_habituales(prep):
    """Conservar referencia directa, alimentador y montaña de los 31 casos."""
    cat=prep.cat;all_rows={};collections={}
    regular={**cat['origin_access_comparisons'],**cat['study_origin_access_comparisons']}
    for collection in ['origin_access_comparisons','study_origin_access_comparisons']:
        for key,spec in cat[collection].items():
            rows=[]
            for ident in spec['itinerary_ids']:
                line=prep.ruta(ident)
                rows.append({'itinerary_id':ident,'rol':'directa','length_m':line.length,'geometry':line})
            for d,ident in enumerate(spec['itinerary_ids']):
                for role in (['origen_cabecera','cabecera_teide'] if d==0 else ['cabecera_teide','origen_cabecera']):
                    line=prep.parts[key][d][role]
                    source=ident
                    if spec.get('geometry_mode')=='independent_reference_and_feeders':
                        source=(spec['feeder_itinerary_ids'][d] if role=='origen_cabecera' else regular[spec['reused_mountain_comparison_id']]['itinerary_ids'][d])
                    rows.append({'itinerary_id':source,'rol':'alimentador' if role=='origen_cabecera' else 'montana',
                                 'length_m':(line.length/1000)*1000,'geometry':line})
            all_rows[key]=gpd.GeoDataFrame(rows,crs=cat['metric_crs']);collections[key]=collection
    for key,spec in cat['coastal_valley_comparisons'].items():
        rows=[]
        for d,ident in enumerate(spec['costera_itinerary_ids']):
            a,b=prep.partir(ident,prep.punto(spec['head_axis_anchor_ids'][d]))
            feeder,mountain=(a,b) if d==0 else (b,a)
            for source,role,line in [(spec['directa_itinerary_ids'][d],'directa',prep.ruta(spec['directa_itinerary_ids'][d])),
                                     (ident,'alimentador',feeder),(ident,'montana',mountain)]:
                rows.append({'itinerary_id':source,'rol':role,'length_m':(line.length/1000)*1000,'geometry':line})
        all_rows[key]=gpd.GeoDataFrame(rows,crs=cat['metric_crs']);collections[key]='coastal_valley_comparisons'
    return all_rows,collections


def clasificar_habituales(prep):
    """Aplicar la regla existente de coincidencia, sin recurrir al GeoPackage."""
    routes,collections=componentes_habituales(prep);classified=[];summary=[]
    for key,frame in routes.items():
        spec=prep.cat[collections[key]][key]
        ids=spec['directa_itinerary_ids']+spec['costera_itinerary_ids'] if collections[key]=='coastal_valley_comparisons' else spec['itinerary_ids']+spec.get('feeder_itinerary_ids',[])
        sources={part['source_id'] for ident in ids for part in prep.cat['itineraries'][ident]['axis_parts']}
        roads=gpd.GeoDataFrame(pd.concat([prep.sources[sid].to_crs(frame.crs) for sid in sorted(sources)],ignore_index=True),crs=frame.crs)
        print('Clasificación habitual:',key,flush=True)
        edges=clasificar_geometrias_existentes(frame,roads,por_arista=True).assign(comparacion_id=key)
        aggregate=clasificar_geometrias_existentes(frame,roads,por_arista=False).assign(comparacion_id=key)
        classified.append(edges);summary.append(aggregate)
    return pd.concat(classified,ignore_index=True),pd.concat(summary,ignore_index=True),collections


def unir_perfiles_habituales(prep,edges,collections):
    """Usar los mismos intervalos de vía y tramos de perfil, sin alisado."""
    results=[]
    for key,collection in collections.items():
        coastal=collection=='coastal_valley_comparisons';spec=prep.cat[collection][key]
        raw=prep.tables['costa/segmentos'] if coastal else prep.tables['origenes/'+key+'/segmentos']
        selected=edges.loc[edges.comparacion_id.eq(key)&edges.rol.isin(['directa','alimentador'])]
        for (ident,role),roads in selected.groupby(['itinerary_id','rol'],sort=False):
            if coastal:
                direction='Hacia el Teide' if '_ida_' in ident else 'Regreso'
                alt='directa_tf523' if role=='directa' else 'alimentador_costero'
                sequence=[raw.loc[raw.caso.eq(key)&raw.sentido.eq(direction)&raw.alternativa.eq(alt)]]
            else:
                direct=ident
                if role=='alimentador' and ident not in set(raw.itinerary_id):
                    direct=spec['itinerary_ids'][spec['feeder_itinerary_ids'].index(ident)]
                full=raw.loc[raw.itinerary_id.eq(direct)]
                if role=='alimentador':sequence=[full.loc[full.componente.eq('origen_cabecera')]]
                elif full.componente.eq('referencia_directa').any():sequence=[full.loc[full.componente.eq('referencia_directa')]]
                else:
                    direction=spec['itinerary_ids'].index(direct)
                    order=['origen_cabecera','cabecera_teide'] if direction==0 else ['cabecera_teide','origen_cabecera']
                    sequence=[full.loc[full.componente.eq(k)] for k in order]
            parts=[];offset=0.
            for i,segment in enumerate(sequence):
                if segment.empty:raise ValueError('Falta un componente del perfil recién reconstruido.')
                s=segment.sort_values('distance_start_m').copy();s['segment_id']=s.segment_id.map(lambda n:f'{i}:{n}')
                s['distance_start_m']+=offset;s['distance_end_m']+=offset;offset+=float(s.length_m.sum());parts.append(s)
            profile=pd.concat(parts,ignore_index=True)
            if abs(offset-roads.length_m.sum())>1e-5:raise ValueError('La unión de perfil y vía pierde longitud.')
            cut=recortar_intervalos(profile,roads);verificar_union(profile,cut);cut['comparacion_id']=key
            cut['fuente_perfil']='data/silver/geografia/accesos_origenes/'+('contraste_costero_valle' if coastal else key)+'/segmentos.parquet'
            results.append(cut)
    return pd.concat(results,ignore_index=True)
