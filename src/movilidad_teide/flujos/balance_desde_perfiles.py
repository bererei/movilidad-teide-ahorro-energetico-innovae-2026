"""Anualizar coeficientes recién preparados, antes de abrir referencias Gold."""
from pathlib import Path
import json,shutil
import pandas as pd
from movilidad_teide.trazabilidad import sha256_archivo
from movilidad_teide.flujos.ordenacion_vigente import (ContextoOrdenacion,_preparar_factores,
    _valorar_programa,_guardar,_json,_anualizar_politicas,_materializar_recomendada,_anualizar_sensibilidad)
from movilidad_teide.flujos.compartida_2028 import BASE,PARADAS
from movilidad_teide.flujos.cierre_anual import INVENTARIO,SOLAR
from movilidad_teide.flujos.operacion_2028 import FUENTES


def completar_raiz_calculo(root,calc,demanda,*,operacion=None):
    root,calc=Path(root),Path(calc)
    for n in ['config',BASE,PARADAS,INVENTARIO,SOLAR,'data/silver/operacion/oferta_vigente','data/bronze/geografia/rutas_cabeceras/20261108_osrm']:
        a,b=(root if operacion is None or n=='config' else Path(operacion))/n,calc/n
        if a.is_dir():shutil.copytree(a,b,dirs_exist_ok=True)
        else:b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(a,b)
    for key,name in [('territorio/origenes_por_modo_2025',FUENTES['origenes']),('calendario/demanda_horaria_calendario','data/silver/demanda/calendario/volumen_y_cabeceras/250_alternativa/demanda_horaria_calendario.csv')]:_guardar(calc/name,demanda[key])
    # La copia de configuración solo cambia los sellos de ficheros que acabamos
    # de reconstruir. No cambia parámetros, hipótesis, rutas ni tolerancias.
    index=calc/'config/referencia_ordenacion_2028.json';cfg=json.loads(index.read_text());original=dict(cfg['entradas_sha256'])
    cfg['entradas_sha256']={str(p.relative_to(calc)):sha256_archivo(p) for p in sorted((calc/'data').rglob('*')) if p.is_file()}
    _json(index,cfg)
    _json(calc.parent/'procedencia_indice_temporal.json',{'sha256_indice_original':sha256_archivo(root/'config/referencia_ordenacion_2028.json'),
        'parametros_base_y_31_condiciones_identicos':True,'entradas_generadas_o_elegidas':cfg['entradas_sha256'],
        'referencias_originales_no_utilizadas_como_entrada':[n for n in original if n not in cfg['entradas_sha256']],
        'razon':'Raíz de ejecución nueva; sin Gold ni coeficientes anteriores. El índice original permanece intacto.'})
    return calc


def calcular_balance(calc,destino):
    """Misma aritmética y programas vigentes; comparación en otra fase."""
    destino=Path(destino);destino.mkdir(parents=True,exist_ok=False);ctx=ContextoOrdenacion(calc);ctx.factores=_preparar_factores(ctx)
    op=pd.read_csv(ctx.captura/'resultados_operacion.csv',sep=';',float_precision='round_trip');costs=[]
    for i,r in enumerate(op[op.cierre].itertuples(),1):
        costs.extend(_valorar_programa(ctx,r,ctx.captura/'ofertas'/str(r.cupo)/str(r.max_programadas)/r.perfil))
        if i%25==0:print('Programas principales comprobados:',i,flush=True)
    _guardar(destino/'energia_por_programa.csv',pd.DataFrame(costs));_anualizar_politicas(ctx,destino);_materializar_recomendada(ctx,destino)
    acts=pd.read_csv(ctx.captura/'sensibilidad_excursiones/actividad_por_programa.csv',sep=';',float_precision='round_trip');allcost=[]
    for i,r in enumerate(acts.itertuples(),1):
        folder=ctx.captura/'sensibilidad_excursiones'/str(round(r.incremento_excursiones*100))/('conservada' if r.oferta=='Oferta conservada' else 'ajustada')/r.perfil
        for cc in _valorar_programa(ctx,r,folder,r.incremento_excursiones):allcost.append({**cc,'incremento_excursiones':r.incremento_excursiones,'oferta':r.oferta,'dias_seleccionados':r.dias})
        if i%36==0:print('Programas de sensibilidad comprobados:',i,flush=True)
    _guardar(destino/'sensibilidad_excursiones/energia_por_programa.csv',pd.DataFrame(allcost));_anualizar_sensibilidad(ctx,destino,allcost)
    _guardar(destino/'auditoria_programas.csv',pd.DataFrame(ctx.auditorias))
    return ctx
