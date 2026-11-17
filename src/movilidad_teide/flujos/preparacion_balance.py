"""Reproducción nativa de demanda, geografía, clases y balance, por fases.

Se reconstruyen las magnitudes físicas y energéticas. Permanecen fijas las
selecciones técnicas del parque, los factores COPERT certificados y los
programas de servicio. Gold solo se abre en la comparación posterior.
"""
from pathlib import Path
from contextlib import contextmanager
import json,os,platform,sys
import pandas as pd
from movilidad_teide.trazabilidad import sha256_archivo
from movilidad_teide.flujos.ordenacion_vigente import _destino_nuevo,_comparar_json
from movilidad_teide.flujos.preparacion_demanda import comparar_tabla
from movilidad_teide.flujos.preparacion_geografia import leer_tabla

CONTRATO='manifiestos/preparacion_balance.json'
_audit_state=None
_instalado=False


@contextmanager
def entradas_declaradas(root,destino,names):
    """Bloquear cualquier dato previo no declarado, incluido todo Gold."""
    global _audit_state,_instalado
    if _audit_state is not None:raise RuntimeError('Auditoría de integración ya activa.')
    root,destino=Path(root).resolve(),Path(destino).resolve();reads=set()
    if not _instalado:
        def audit(event,args):
            if _audit_state is None or event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)):return
            p=Path(os.fsdecode(args[0])).resolve();base,target,allowed,seen=_audit_state
            if p.is_relative_to(target) or not p.is_relative_to(base):return
            rel=str(p.relative_to(base))
            if rel.startswith(('data/','config/')) and rel not in allowed:raise PermissionError('Dato no declarado para reconstrucción: '+rel)
            if rel.startswith(('desarrollo/','outputs/','docs/')):raise PermissionError('Material ajeno a la reconstrucción: '+rel)
            seen.add(rel)
        sys.addaudithook(audit);_instalado=True
    _audit_state=(root,destino,set(names),reads)
    try:yield reads
    finally:_audit_state=None


def verificar_fuentes(root):
    root=Path(root).resolve();c=json.loads((root/CONTRATO).read_text())
    if c['visitas_sin_y_con']!=2500000:raise ValueError('Referencia de visitas distinta.')
    for n,h in c['fuentes_sha256'].items():
        p=Path(n)
        if p.is_absolute() or '..' in p.parts or not (root/p).resolve().is_relative_to(root):raise ValueError('Ruta de entrada no portable: '+n)
        if n.startswith(('data/gold/','data/silver/energia/','data/silver/geografia/','data/silver/vehiculos/ponderacion/')):raise ValueError('Un resultado físico o energético se ha declarado como entrada: '+n)
        if not (root/n).is_file() or sha256_archivo(root/n)!=h:raise ValueError('Entrada ausente o alterada: '+n)
    return c


def preparar(root,destino):
    root=Path(root).resolve();contract=verificar_fuentes(root);destino=_destino_nuevo(root,destino)
    code={str(p.relative_to(root)):sha256_archivo(p) for p in sorted((root/'src').rglob('*.py'))}
    from movilidad_teide.demanda.preparacion import preparar_demanda
    from movilidad_teide.cartografia.preparacion import Preparador
    from movilidad_teide.configuracion.ordenacion import leer_ordenacion
    from movilidad_teide.energia.preparacion_vial import clasificar_habituales,unir_perfiles_habituales
    from movilidad_teide.energia.preparacion_osrm import clasificar_reasignados,unir_reasignados
    from movilidad_teide.energia.preparacion_coeficientes import (guardar,preparar_turismos,preparar_autobuses,
        preparar_excursiones,preparar_alimentacion_titsa,preparar_unidades_reasignadas)
    from movilidad_teide.flujos.balance_desde_perfiles import completar_raiz_calculo,calcular_balance
    with entradas_declaradas(root,destino,contract['fuentes_sha256']) as reads:
        ref=leer_ordenacion(root)
        demand,_=preparar_demanda(root)
        for k,t in demand.items():guardar(destino,'demanda/'+k+'.parquet',t)
        geo=destino/'geografia';geo.mkdir();prep=Preparador(root,geo);tables,geometa=prep.preparar()
        for k,t in tables.items():guardar(geo,'tablas/'+k+'.parquet',t)
        edges,summary,collections=clasificar_habituales(prep);habituales=unir_perfiles_habituales(prep,edges,collections)
        selection=json.loads((root/'manifiestos/preparacion_geografia_bronze.json').read_text())['cabeceras']['ordinarias']
        roads=clasificar_reasignados(prep,selection);reasignados=unir_reasignados(prep,roads)
        for n,t in [('aristas_habituales',edges),('tipologia_por_componente',summary),('segmentos_habituales',habituales),('aristas_osrm',roads),('segmentos_osrm',reasignados)]:guardar(destino,'clasificacion/'+n+'.parquet',t)
        calc=destino/'calculo';calc.mkdir();import shutil;shutil.copytree(root/'config',calc/'config')
        base=preparar_turismos(root,calc,prep,habituales,demand,ref['base'])
        preparar_autobuses(root,calc,prep,ref['base']);preparar_excursiones(calc,base,ref['base'])
        preparar_alimentacion_titsa(root,calc,demand,ref['base'])
        preparar_unidades_reasignadas(root,calc,prep,reasignados,base,ref['base'])
        completar_raiz_calculo(root,calc,demand);ctx=calcular_balance(calc,destino/'balance')
    verificar_fuentes(root)
    if code!={str(p.relative_to(root)):sha256_archivo(p) for p in sorted((root/'src').rglob('*.py'))}:raise ValueError('El código cambió durante el cálculo.')
    cal=pd.read_csv(destino/'balance/recomendada_calendario.csv',sep=';',float_precision='round_trip')
    if len(cal)!=366 or abs(cal.visitas_sin_dia.sum()-2500000)>1e-8:raise ValueError('El balance no conserva calendario y visitas.')
    outputs={str(p.relative_to(destino)):sha256_archivo(p) for p in sorted(destino.rglob('*')) if p.is_file()}
    metadata={'contrato_sha256':sha256_archivo(root/CONTRATO),'visitas_sin_y_con':2500000,'restricciones':ref['valores'],
        'fuentes_sha256':contract['fuentes_sha256'],'lecturas_python_del_proyecto':sorted(reads),'lecturas_gold_durante_calculo':False,
        'coeficientes_energeticos_previos_utilizados':False,'programas_y_seleccion_tecnica_fijos':True,
        'ejecucion_nueva_motor_copert':False,'sin_cambios_de_hipotesis':True,
        'aristas_habituales':len(edges),'combinaciones_tipologia':len(summary),'segmentos_habituales':len(habituales),'aristas_reasignadas':len(roads),
        'segmentos_reasignados_con_tres_alternativas':len(reasignados),'longitud_residuo_vial_m':float(roads.loc[roads.clase_propuesta.eq('pendiente'),'length_m'].sum()),
        'programas_comprobados':len(ctx.auditorias),'fuentes_geograficas':geometa,'salidas_sha256':outputs,
        'codigo_sha256':code,
        'entorno':{'python':platform.python_version(),'pandas':pd.__version__},
        'alcance':'Demanda y geografía desde Bronze; clasificación, masas y energía reconstruidas con decisiones técnicas y programas fijos. Comparación con Silver y Gold en otra fase.'}
    (destino/'metadatos.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2,default=str)+'\n')
    return metadata


def comparar(root,resultados,destino,*,productos=None):
    root,resultados=Path(root).resolve(),Path(resultados).resolve();destino=_destino_nuevo(root,destino)
    c=json.loads((root/CONTRATO).read_text());m=json.loads((resultados/'metadatos.json').read_text())
    if m['contrato_sha256']!=sha256_archivo(root/CONTRATO):raise ValueError('Otro contrato de reconstrucción.')
    for n,h in m['salidas_sha256'].items():
        if sha256_archivo(resultados/n)!=h:raise ValueError('Salida alterada antes de comparar: '+n)
    rows=[]
    for case in c['comparaciones']:
        a,b=Path(productos[case['salida']]) if productos and case['salida'] in productos else resultados/case['salida'],root/case['referencia']
        if sha256_archivo(b)!=case['sha256_referencia']:raise ValueError('Referencia alterada: '+case['referencia'])
        try:
            if b.suffix=='.json':
                _comparar_json(json.loads(a.read_text()),json.loads(b.read_text()),case['salida']);out={}
            else:
                aa,bb=leer_tabla(a),leer_tabla(b)
                if case.get('filtro_referencia'):
                    for k,v in case['filtro_referencia'].items():bb=bb[bb[k].eq(v)]
                if case.get('comparador')=='anual':
                    pd.testing.assert_frame_equal(aa,bb,check_dtype=False,check_exact=False,atol=1e-8,rtol=0)
                    numeric=bb.select_dtypes(include='number').columns
                    out={'filas':len(bb),'columnas':len(bb.columns),'maxima_diferencia_absoluta':max((float((aa[n]-bb[n]).abs().max()) for n in numeric if (aa[n]-bb[n]).notna().any()),default=0.)}
                else:out=comparar_tabla(aa,bb,case['claves'],case.get('columnas'))
            rows.append(dict(producto=case['salida'],referencia=case['referencia'],equivalente=True,**out))
        except (ValueError,KeyError,AssertionError) as error:rows.append(dict(producto=case['salida'],referencia=case['referencia'],equivalente=False,error=str(error)))
    pd.DataFrame(rows).to_csv(destino/'comparacion_equivalencia.csv',sep=';',index=False,encoding='utf-8-sig')
    outcome={'equivalente':all(x['equivalente'] for x in rows),'interfaces_comparadas':len(rows),'productos_anuales':sum(x['salida'].startswith('balance/') for x in c['comparaciones']),
        'tolerancia_absoluta':1e-8,'maxima_diferencia_absoluta':max((x.get('maxima_diferencia_absoluta',0.) for x in rows),default=0.),'visitas_sin_y_con':2500000,
        'comparacion_posterior_al_calculo':True,'contrato_sha256':m['contrato_sha256'],'metadatos_preparacion_sha256':sha256_archivo(resultados/'metadatos.json')}
    (destino/'verificacion.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2)+'\n')
    if not outcome['equivalente']:raise ValueError('La reproducción difiere; consulte comparacion_equivalencia.csv.')
    return outcome
