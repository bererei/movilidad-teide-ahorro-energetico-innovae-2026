"""Preparar geografía con Bronze y comparar después con las referencias Silver."""
from pathlib import Path
from contextlib import contextmanager
from functools import lru_cache
import csv,json,os,platform,sys
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
import rasterio,pyproj
from pyproj import CRS
from movilidad_teide.trazabilidad import sha256_archivo
from movilidad_teide.flujos.ordenacion_vigente import _destino_nuevo
from movilidad_teide.flujos.preparacion_demanda import comparar_tabla

CONTRATO='manifiestos/preparacion_geografia_bronze.json'
_estado=None
_instalado=False


@contextmanager
def solo_fuentes(root,destino):
    """Denegar intermedios previos; permitir solo los derivados del destino nuevo."""
    global _estado,_instalado
    if _estado is not None:raise RuntimeError('Auditoría geográfica ya activa.')
    root,destino=Path(root).resolve(),Path(destino).resolve();reads=set()
    if not _instalado:
        def audit(event,args):
            if _estado is None or event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)):return
            p=Path(os.fsdecode(args[0])).resolve();base,target,seen=_estado
            if p.is_relative_to(target):return
            if not p.is_relative_to(base):return
            relative=p.relative_to(base);parts=relative.parts
            if parts[:2] in [('data','silver'),('data','gold')] or parts[:1] in [('desarrollo',),('outputs',),('docs',)]:
                raise PermissionError('Preparación geográfica: lectura de un intermedio anterior '+str(relative))
            seen.add(str(relative))
        sys.addaudithook(audit);_instalado=True
    _estado=(root,destino,reads)
    try:yield reads
    finally:_estado=None


def verificar_fuentes(root):
    root=Path(root).resolve();contract=json.loads((root/CONTRATO).read_text())
    if contract['visitas_sin_y_con']!=2500000:raise ValueError('Contrato de otra referencia.')
    for name,digest in contract['fuentes_sha256'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or not (root/p).resolve().is_relative_to(root):raise ValueError('Fuente fuera del proyecto.')
        if not name.startswith(('data/bronze/','config/')):raise ValueError('Intermedio declarado como fuente.')
        if not (root/p).is_file() or sha256_archivo(root/p)!=digest:raise ValueError('Fuente ausente o alterada: '+name)
    return contract


def preparar(root,destino,*,demanda=None,clasificar_vias=False,referencia=None):
    root=Path(root).resolve();contract=verificar_fuentes(root);destino=_destino_nuevo(root,destino)
    from movilidad_teide.cartografia.preparacion import Preparador
    from movilidad_teide.configuracion.ordenacion import leer_ordenacion
    with solo_fuentes(root,destino) as reads:
        reference=referencia if referencia is not None else leer_ordenacion(root)
        prep=Preparador(root,destino,demanda=demanda);tables,metadata=prep.preparar()
    undeclared={n for n in reads if n.startswith(('data/bronze/','config/'))}-set(contract['fuentes_sha256'])
    if undeclared:raise ValueError('Lecturas sin declarar: '+str(sorted(undeclared)))
    outputs={};summary=[]
    for name,df in tables.items():
        path=destino/'tablas'/(name+'.parquet');path.parent.mkdir(parents=True,exist_ok=True)
        df.to_parquet(path,index=False);outputs[str(path.relative_to(destino))]=sha256_archivo(path)
        summary.append({'producto':name,'filas':len(df),'columnas':len(df.columns),'geometria':'geometry' in df,
                        'archivo':str(path.relative_to(destino))})
    for row in metadata['terrenos']:
        name=row.get('salida_relativa')
        if name:outputs[name]=sha256_archivo(destino/name)
    pd.DataFrame(summary).to_csv(destino/'indice_tablas.csv',sep=';',index=False,encoding='utf-8-sig')
    outputs['indice_tablas.csv']=sha256_archivo(destino/'indice_tablas.csv')
    if clasificar_vias:
        from movilidad_teide.energia.preparacion_vial import clasificar_habituales,unir_perfiles_habituales
        from movilidad_teide.energia.preparacion_osrm import clasificar_reasignados,unir_reasignados
        edges,resumen_vias,collections=clasificar_habituales(prep)
        habituales=unir_perfiles_habituales(prep,edges,collections)
        seleccion=json.loads((root/CONTRATO).read_text())['cabeceras']['ordinarias']
        roads=clasificar_reasignados(prep,seleccion);reasignados=unir_reasignados(prep,roads)
        for name,table in [('aristas_habituales',edges),('tipologia_por_componente',resumen_vias),('segmentos_habituales',habituales),('aristas_osrm',roads),('segmentos_osrm',reasignados)]:
            p=destino/'clasificacion'/(name+'.parquet');p.parent.mkdir(parents=True,exist_ok=True);table.to_parquet(p,index=False)
            outputs[str(p.relative_to(destino))]=sha256_archivo(p)
        p=destino/'catalogo_resuelto.json';p.write_text(json.dumps(prep.cat,ensure_ascii=False,indent=2)+'\n');outputs[p.name]=sha256_archivo(p)
        metadata.update(clasificacion_reconstruida=True,demanda_de_ejecucion_recibida=demanda is not None)
    verificar_fuentes(root)
    metadata.update({'visitas_sin_y_con':reference['valores']['visitas_anio'],'restricciones':reference['valores'],
        'fases':'Preparación desde Bronze; comparación con Silver en una fase posterior',
        'tablas_producidas':len(tables),'resumen_tablas':summary,'salidas_sha256':outputs,
        'fuentes_sha256':contract['fuentes_sha256'],'lecturas_python_del_proyecto':sorted(reads),
        'lecturas_silver_gold_previos':False,'lecturas_de_terrenos_regenerados_en_el_destino_nuevo':True,
        'contrato_sha256':sha256_archivo(root/CONTRATO),
        'codigo_sha256':{str(p.relative_to(root)):sha256_archivo(p) for p in sorted((root/'src').rglob('*.py'))},
        'entorno':{'python':platform.python_version(),'pandas':pd.__version__,'geopandas':gpd.__version__,'rasterio':rasterio.__version__,'pyproj':pyproj.__version__,'shapely':shapely.__version__},
        'parametros_modificados':False,'energia_recalculada':False})
    (destino/'metadatos.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    return metadata


def leer_tabla(path):
    if Path(path).suffix=='.csv':return pd.read_csv(path,sep=';',float_precision='round_trip')
    table=pd.read_parquet(path)
    if 'geometry' in table:
        geographic=gpd.read_parquet(path)
        table['geometry']=geographic.geometry
        table.attrs['crs']=geographic.crs.to_wkt() if geographic.crs else None
    return table


def comparar_geometria(a,b,keys):
    """Contrastar tipo, vértices, orden y coordenadas; no solo longitud total."""
    crs_a=getattr(a,'crs',None) or a.attrs.get('crs');crs_b=getattr(b,'crs',None) or b.attrs.get('crs')
    if not crs_a or not crs_b or CRS.from_user_input(crs_a)!=CRS.from_user_input(crs_b):raise ValueError('CRS ausente o distinto.')
    aa=a.sort_values(keys,kind='stable').reset_index(drop=True)
    bb=b.sort_values(keys,kind='stable').reset_index(drop=True)
    if len(aa)!=len(bb):raise ValueError('Número de geometrías distinto.')
    maximum=0.
    for x,y in zip(aa.geometry,bb.geometry):
        if x is None or y is None:
            if x is not None or y is not None:raise ValueError('Geometría ausente distinta.')
            continue
        u,v=shapely.get_coordinates(x),shapely.get_coordinates(y)
        if x.geom_type!=y.geom_type or u.shape!=v.shape:raise ValueError('Tipo o vértices de geometría distintos.')
        if not np.isfinite(u).all() or not np.isfinite(v).all():raise ValueError('Coordenadas no finitas.')
        maximum=max(maximum,float(np.abs(u-v).max()))
    if maximum>1e-8:raise ValueError('Coordenadas distintas: '+str(maximum))
    return maximum


def comparar(root,resultados,destino):
    root=Path(root).resolve();resultados=Path(resultados).resolve();destino=_destino_nuevo(root,destino)
    contract=json.loads((root/CONTRATO).read_text());metadata=json.loads((resultados/'metadatos.json').read_text())
    if metadata['contrato_sha256']!=sha256_archivo(root/CONTRATO):raise ValueError('Otro contrato de preparación.')
    for name,digest in metadata['salidas_sha256'].items():
        if sha256_archivo(resultados/name)!=digest:raise ValueError('Resultado de preparación alterado: '+name)
    aliases=contract.get('procedencia_mdt',{})
    rows=[]
    for case in contract['comparaciones']:
        path=root/case['referencia']
        if not path.is_file() or sha256_archivo(path)!=case['sha256_referencia']:raise ValueError('Referencia Silver ausente o alterada: '+case['referencia'])
        a=leer_tabla(resultados/'tablas'/(case['producto']+'.parquet'));b=leer_tabla(path)
        if case.get('columnas'):a,b=a[case['columnas']],b[case['columnas']]
        translated=[]
        for col in ['mdt','mdt_archivo','fuente_mdt']:
            if col in a:
                a[col]=a[col].map(lambda x:aliases.get(x,x));b[col]=b[col].map(lambda x:aliases.get(x,x));translated.append(col)
        try:
            geom=comparar_geometria(a,b,case['claves']) if 'geometry' in a else None
            result=comparar_tabla(a.drop(columns='geometry',errors='ignore'),b.drop(columns='geometry',errors='ignore'),case['claves'])
            rows.append({'producto':case['producto'],'referencia':case['referencia'],'equivalente':True,
                         'diferencia_maxima_coordenadas_m':geom,'procedencia_mdt_normalizada':translated,**result})
        except (ValueError,KeyError) as error:rows.append({'producto':case['producto'],'referencia':case['referencia'],'equivalente':False,'error':str(error)})
    pd.DataFrame(rows).to_csv(destino/'comparacion_equivalencia.csv',sep=';',index=False,encoding='utf-8-sig')
    result={'equivalente':all(x['equivalente'] for x in rows),'interfaces_comparadas':len(rows),
        'maxima_diferencia_numerica_absoluta':max((x.get('maxima_diferencia_absoluta',0.) for x in rows),default=0.),
        'maxima_diferencia_coordenadas_m':max((x.get('diferencia_maxima_coordenadas_m') or 0. for x in rows),default=0.),
        'tolerancia_absoluta':1e-8,'tablas_producidas':metadata['tablas_producidas'],
        'visitas_sin_y_con':metadata['visitas_sin_y_con'],'informe_modificado':False,'energia_recalculada':False,
        'preparacion_sin_silver_gold_previos':not metadata['lecturas_silver_gold_previos']}
    (destino/'verificacion.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if not result['equivalente']:raise ValueError('Hay interfaces geográficas no equivalentes; consultar comparacion_equivalencia.csv.')
    return result
