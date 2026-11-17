"""Ejecutar Bronze → demanda y comparar después con Silver, por fases separadas."""
from pathlib import Path
from contextlib import contextmanager
import json,os,platform,sys
from functools import lru_cache
import numpy as np
import pandas as pd
from movilidad_teide.trazabilidad import sha256_archivo
from movilidad_teide.flujos.ordenacion_vigente import _destino_nuevo

CONTRATO='manifiestos/preparacion_demanda_bronze.json'
_audit_state=None
_hook_instalado=False


@contextmanager
def solo_fuentes(root):
    """Denegar lecturas de Silver/Gold y registrar las lecturas Python del proyecto.

    El aislamiento completo de aceptación se hace además con esas capas
    ausentes y el desarrollo original oculto. GDAL puede abrir auxiliares fuera
    del evento Python: por eso el contrato sella también todos sus componentes.
    """
    global _audit_state,_hook_instalado
    if _audit_state is not None:raise RuntimeError('Auditoría de preparación ya activa.')
    root=Path(root).resolve();reads=set()
    if not _hook_instalado:
        def audit(event,args):
            state=_audit_state
            if state is None or event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)):return
            p=Path(os.fsdecode(args[0])).resolve()
            if not p.is_relative_to(state[0]):return
            rel=p.relative_to(state[0]);parts=rel.parts
            if parts[:2] in [('data','silver'),('data','gold')] or parts[:1] in [('desarrollo',),('outputs',),('docs',)]:
                raise PermissionError('La preparación desde Bronze no puede leer '+str(rel))
            state[1].add(str(rel))
        sys.addaudithook(audit);_hook_instalado=True
    _audit_state=(root,reads)
    try:yield reads
    finally:_audit_state=None


def verificar_fuentes(root):
    root=Path(root).resolve();contract=json.loads((root/CONTRATO).read_text())
    if contract['visitas_sin_y_con']!=2500000:raise ValueError('Contrato de otra referencia.')
    for name,digest in contract['fuentes_sha256'].items():
        path=Path(name)
        if path.is_absolute() or '..' in path.parts or not (root/path).resolve().is_relative_to(root):raise ValueError('Fuente fuera de la raíz.')
        if not name.startswith(('data/bronze/','config/')):raise ValueError('El contrato contiene un intermedio como fuente.')
        if not (root/path).is_file() or sha256_archivo(root/path)!=digest:raise ValueError('Fuente ausente o alterada: '+name)
    return contract


def preparar(root,destino,*,guardar_parquet=False,referencia=None):
    root=Path(root).resolve();contract=verificar_fuentes(root);destino=_destino_nuevo(root,destino)
    from movilidad_teide.demanda.preparacion import preparar_demanda
    with solo_fuentes(root) as reads:tables,metadata=preparar_demanda(root,referencia=referencia)
    undeclared={n for n in reads if n.startswith(('data/bronze/','config/'))}-set(contract['fuentes_sha256'])
    if undeclared:raise ValueError('Lecturas no declaradas en el contrato: '+str(sorted(undeclared)))
    outputs={};summary=[]
    for name,df in tables.items():
        p=destino/'tablas'/(name+'.csv');p.parent.mkdir(parents=True,exist_ok=True)
        df.to_csv(p,sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
        outputs[str(p.relative_to(destino))]=sha256_archivo(p)
        summary.append({'producto':name,'filas':len(df),'columnas':len(df.columns)})
    if guardar_parquet:
        for name,df in tables.items():
            p=destino/'tablas_parquet'/(name+'.parquet');p.parent.mkdir(parents=True,exist_ok=True);df.to_parquet(p,index=False)
            outputs[str(p.relative_to(destino))]=sha256_archivo(p)
    verificar_fuentes(root)
    metadata.update({'fases':'Preparación pura; la comparación con Silver es otra fase',
        'fuentes_sha256':contract['fuentes_sha256'],'lecturas_python_del_proyecto':sorted(reads),
        'lecturas_silver_gold':False,'tablas_producidas':len(tables),'resumen_tablas':summary,'salidas_sha256':outputs,
        'codigo_sha256':{str(p.relative_to(root)):sha256_archivo(p) for p in sorted((root/'src').rglob('*.py'))},
        'contrato_sha256':sha256_archivo(root/CONTRATO),'entorno':{'python':platform.python_version(),'pandas':pd.__version__,'numpy':np.__version__},
        'libro_vigente_sha256':sha256_archivo(root/'config/parametros_modelo.xlsx'),
        'libro_de_origen_aforos_sha256':sha256_archivo(root/'data/bronze/documentacion/preparacion_aforos/libro_de_origen.xlsx'),
        'alcance_geografico':'Zonificación y correspondencias de la demanda; no reconstrucción de perfiles altimétricos o coeficientes de energía.'})
    (destino/'metadatos.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    return metadata


def comparar_tabla(actual,referencia,claves,columnas=None,normalizar_ruta=None):
    """Exigir esquema, claves, ausencias y textos; conservar tolerancia 1e-8."""
    a,b=actual.copy(),referencia.copy()
    if columnas:a,b=a[columnas],b[columnas]
    if set(a)!=set(b) or len(a)!=len(b):raise ValueError('Esquema o filas de demanda distintos.')
    if not claves or a.duplicated(claves).any() or b.duplicated(claves).any():raise ValueError('Claves de comparación vacías o duplicadas.')
    translated=[]
    for col in ['fuente']:
        if col in a and normalizar_ruta:
            a[col]=a[col].map(normalizar_ruta);b[col]=b[col].map(normalizar_ruta);translated.append(col)
    a=a.sort_values(claves,kind='stable').reset_index(drop=True);b=b.sort_values(claves,kind='stable').reset_index(drop=True)
    maximum=0.
    for col in b:
        if not a[col].isna().equals(b[col].isna()):raise ValueError('Ausencias distintas en '+col)
        if pd.api.types.is_numeric_dtype(a[col]) and pd.api.types.is_numeric_dtype(b[col]) and not pd.api.types.is_bool_dtype(b[col]):
            delta=(a[col]-b[col]).abs().max();delta=0. if pd.isna(delta) else float(delta);maximum=max(maximum,delta)
            if delta>1e-8:raise ValueError('Diferencia numérica superior a la tolerancia en '+col+': '+str(delta))
        elif not a[col].fillna('<ausente>').astype(str).equals(b[col].fillna('<ausente>').astype(str)):
            raise ValueError('Texto, identificador o booleano distinto en '+col)
    return {'filas':len(b),'columnas':len(b.columns),'maxima_diferencia_absoluta':maximum,'columnas_de_procedencia_relocalizadas':translated}


def comparar(root,resultados,destino):
    root=Path(root).resolve();resultados=Path(resultados).resolve();destino=_destino_nuevo(root,destino)
    contract=json.loads((root/CONTRATO).read_text());metadata=json.loads((resultados/'metadatos.json').read_text())
    if metadata['contrato_sha256']!=sha256_archivo(root/CONTRATO):raise ValueError('La ejecución usa otro contrato de demanda.')
    for name,expected in metadata['salidas_sha256'].items():
        if sha256_archivo(resultados/name)!=expected:raise ValueError('Resultado de preparación alterado: '+name)
    from movilidad_teide.configuracion.rutas import resolver_procedencia
    @lru_cache(maxsize=None)
    def canonical(name):
        return str(resolver_procedencia(root,name).relative_to(root)) if isinstance(name,str) and name.startswith('data/') else name
    rows=[]
    for case in contract['comparaciones']:
        expected=root/case['referencia']
        if not expected.is_file() or sha256_archivo(expected)!=case['sha256_referencia']:raise ValueError('Referencia Silver alterada: '+case['referencia'])
        a=pd.read_csv(resultados/'tablas'/(case['producto']+'.csv'),sep=';',float_precision='round_trip')
        b=pd.read_csv(expected,sep=';',float_precision='round_trip')
        try:
            outcome=comparar_tabla(a,b,case['claves'],case.get('columnas'),canonical)
            rows.append({'producto':case['producto'],'referencia':case['referencia'],'equivalente':True,**outcome})
        except (ValueError,KeyError) as error:
            rows.append({'producto':case['producto'],'referencia':case['referencia'],'equivalente':False,'error':str(error)})
    pd.DataFrame(rows).to_csv(destino/'comparacion_equivalencia.csv',sep=';',index=False,encoding='utf-8-sig')
    verification={'equivalente':all(x['equivalente'] for x in rows),'interfaces_comparadas':len(rows),
        'visitas_sin_y_con':metadata['visitas_sin_y_con'],'tablas_producidas':metadata['tablas_producidas'],
        'maxima_diferencia_absoluta':max((x.get('maxima_diferencia_absoluta',0.) for x in rows),default=0.),'tolerancia_absoluta':1e-8,
        'preparacion_sin_lecturas_silver_gold':not metadata['lecturas_silver_gold'],
        'demanda_328':'Se comparan claves y cantidades de demanda; sus columnas de diagnóstico/perfiles geográficos no forman parte de esta preparación.',
        'indice_de_fuentes':'manifiestos/preparacion_demanda_bronze.json','informe_modificado':False,'energia_recalculada':False}
    (destino/'verificacion.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n')
    if not verification['equivalente']:raise ValueError('Hay interfaces de demanda no equivalentes; revisar comparacion_equivalencia.csv.')
    return verification
