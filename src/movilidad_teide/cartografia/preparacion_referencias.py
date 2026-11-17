"""Aplicar las referencias territoriales declaradas a las longitudes reconstruidas."""
import json
import pandas as pd
import matplotlib.image as mpimg
from movilidad_teide.demanda.representacion import normalizar_recorridos_estudio
from movilidad_teide.fuentes.preparacion_demanda import extraer_visor,preparar_zonas,preparar_gtfs
from movilidad_teide.demanda.asignacion import demanda_por_origen,reconstruir_cabeceras,construir_asignacion
from movilidad_teide.demanda.origenes import seleccionar_origenes_representativos


def reconstruir_referencias(preparador):
    """Reconstruir las 82 referencias dirigidas; las condicionales conservan NA."""
    root=preparador.root;cat=preparador.cat;tables=preparador.tables
    config=json.loads((root/'config/asignacion_demanda.json').read_text());physical={}
    for collection in ['origin_access_comparisons','study_origin_access_comparisons']:
        for key in cat[collection]:physical[collection,key]=tables['origenes/'+key+'/longitudes']
    for key in cat['coastal_valley_comparisons']:
        physical['coastal_valley_comparisons',key]=tables['costa/longitudes'].loc[lambda d:d.caso.eq(key)]
    references,lengths=normalizar_recorridos_estudio(cat,physical,config['corredores'])
    own={spec['origin_id']:key for key,spec in references.items()}
    approximate={x['origen_id']:x['comparacion_referencia_id'] for x in config['aproximaciones_geograficas_estudio']['casos'] if x['tipo']!='condicional_media_nula'}
    conectada=getattr(preparador,'demanda_conectada',None)
    if conectada is not None:
        demands=conectada['territorio/demanda_por_origen'];origins=conectada['territorio/origenes']
    else:
        visor=extraer_visor(root);zones,_=preparar_zonas(root);stops,_=preparar_gtfs(root)
        raw=demanda_por_origen(visor['centroides'],zones.drop(columns='geometry'))
        image=mpimg.imread(root/'data/bronze/documentacion/visor_teide/20261022_mapas_medianias/31_mapa_acceso_dominante_origen_medianias.png')
        assigned=construir_asignacion(raw,reconstruir_cabeceras(image,zones,config['mapa']),config['corredores'])
        _,demands,origins=seleccionar_origenes_representativos(assigned,visor['centroides'],zones,stops)
    for case in config['aproximaciones_geograficas_estudio']['casos']:
        if case['tipo']=='condicional_media_nula' and demands.loc[demands.origen_id.eq(case['origen_id']),'viajes_persona_media_57_matrices'].sum()!=0:
            raise ValueError('Una referencia condicional necesita revisión si su demanda es positiva.')
    cols=[c for c in lengths if c not in ['origen_id','comparacion_id']];rows=[]
    for origin in origins.origen_id:
        comparison=own.get(origin,approximate.get(origin))
        if comparison is None:
            for direction in ['hacia_teide','desde_teide']:
                rows.append({'origen_id':origin,'comparacion_calculo_id':None,**{c:direction if c=='sentido' else None for c in cols}})
        else:
            for row in lengths.loc[lengths.comparacion_id.eq(comparison),cols].to_dict('records'):
                rows.append({'origen_id':origin,'comparacion_calculo_id':comparison,**row})
    table=pd.DataFrame(rows)
    if len(table)!=82 or table.duplicated(['origen_id','sentido']).any():raise ValueError('Referencias de cálculo incompletas.')
    tables['referencias/recorridos_referencia_calculo']=table
