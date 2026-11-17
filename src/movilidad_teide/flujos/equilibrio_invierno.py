"""Contrasto cuotas positivas y cercanas sin ampliar el crecimiento de excursiones."""
from pathlib import Path
import json
import pandas as pd
from movilidad_teide.operacion.equilibrio_invierno import BuscadorEquilibrado
from movilidad_teide.operacion.cuotas_cercanas import metricas_cercania
from movilidad_teide.trazabilidad import sha256_archivo
from .ajuste_invierno import preparar_ajuste_invierno,CUOTAS_PREVIAS

ANTERIOR='data/silver/movilidad/ajuste_invierno_2028/20261108_cupos_y_excursiones'
SALIDAS='data/silver/movilidad/equilibrio_invierno_2028'


def preparar_equilibrio_invierno(root):
    root=Path(root).resolve();buscador=BuscadorEquilibrado()
    etapa,meta=preparar_ajuste_invierno(root,buscador=buscador,orden_cupos=(600,575,550),orden_incrementos=(.10,),orden_margenes=(15,30))
    old=json.loads((root/ANTERIOR/'metadatos.json').read_text())
    for name,h in old['resultados_sha256'].items():
        p=ANTERIOR+'/'+name;actual=sha256_archivo(root/p)
        if actual!=h:raise ValueError(f'La captura D246 ha cambiado: {p}')
        meta['fuentes_sha256'][p]=actual
    for name in ['metadatos.json','verificacion.json']:meta['fuentes_sha256'][ANTERIOR+'/'+name]=sha256_archivo(root/ANTERIOR/name)
    rd=lambda n:pd.read_csv(root/ANTERIOR/(n+'.csv'),sep=';',float_precision='round_trip')
    etapa.tablas['referencia_D246_sintesis']=rd('sintesis');etapa.tablas['referencia_D246_cuotas']=rd('cuotas_punta')
    rows=[];s=etapa.tablas['sintesis'];qq=etapa.tablas['cuotas_punta']
    oldq=rd('cuotas_punta');puntos=list(CUOTAS_PREVIAS)
    for row in s.itertuples():
        q=qq[qq.caso.eq(row.caso)].set_index('punto').loc[puntos].coches_dia.to_list()
        previous=oldq[oldq.caso.eq(row.caso)].set_index('punto').loc[puntos].coches_dia.to_list()
        newdist=metricas_cercania(q,list(CUOTAS_PREVIAS.values()),cupo=int(row.cupo_punta_coches_dia));olddist=metricas_cercania(previous,list(CUOTAS_PREVIAS.values()),cupo=int(row.cupo_punta_coches_dia))
        rows.append({'caso':row.caso,'cupo_punta_coches_dia':row.cupo_punta_coches_dia,'incremento_excursiones_punta':row.incremento_excursiones_punta,'margen_min':row.margen_min,
            'perfiles_con_cierre':row.perfiles_con_cierre,'max_desviacion_relativa':float(newdist[0]),'suma_desviaciones_relativas':float(newdist[1]),
            'max_desviacion_D246':float(olddist[0]),'cuotas_positivas':min(q)>0,**dict(zip(puntos,q))})
    etapa.tablas['comparacion_equilibrio']=pd.DataFrame(rows)
    meta.update(decision='D247',hipotesis='H137',criterio='Cuotas estrictamente positivas. Minimizar la mayor desviación relativa a las proporciones352/107/82/9, después su suma, entre cierres construidos. No se igualan artificialmente los cuatro accesos.',
        orden_contraste={'cupos':[600,575,550],'incrementos':[.10],'margenes':[15,30]},
        confirmacion_preferencia='Beatriz mantiene excursiones como máximo+10 % y admite más variación territorial,08/11/2026.',
        presupuesto='Catálogo exacto de estados en banda relativa75 %; hasta5000 estados cercanos por caso; semillas horarias15/30 compatibles con mínimo15; tres configuraciones refinadas, dos reinicios1800 por geometría pendiente.',
        semillas='247000 +primeros8 hex SHA256 JSON clave de geometría y contexto +reinicio. Reutilización de geometría con cantidades actuales comprobadas.',
        busqueda_global_optima_demostrada=False)
    meta['incremento_excursiones_contrastes']=[.10]
    meta['limites'] += ['Esta búsqueda concentra el contraste en el máximo+10 % ya autorizado para buscar cuotas más cercanas. No repite aquí los casos0/5 % de D246.',
        'El cierre de bases usa flujo de coste mínimo para el reloj fijo cuando los tres emparejamientos previos no construyen testigo; no cambia bases, regulación o flota.',
        'La cercanía se mide sobre proporciones adaptadas al cupo global; un aumento de cupo y una redistribución territorial son decisiones distintas.',
        'El catálogo de cuotas es exacto dentro de la banda75 %, pero se ensaya un presupuesto de relojes/estados. Un caso sin cierre no prueba imposibilidad global ni la mínima desviación necesaria.',
        'Las cantidades de viajeros se reconstruyen por origen/colectivo para cada caso. La caché solo comparte geometría, horarios y cadenas cuando coinciden viajes, red, ventanas, regulación e inventario; nunca conserva pasajeros de otra alternativa.',
        'El desglose de población coche/excursión hacia lanzadera es un saldo neto operativo, no los flujos brutos de alimentación; no se usa para energía en esta fase.']
    return etapa,meta


def generar_equilibrio_invierno(root,destino):
    root,destino=Path(root).resolve(),Path(destino).resolve();permitido=(root/SALIDAS).resolve()
    if destino==permitido or destino.is_relative_to(root) and not destino.is_relative_to(permitido):raise ValueError('Elegir una captura nueva fuera de fuentes e informe.')
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):raise FileExistsError('La ejecución anterior se conserva.')
    etapa,meta=preparar_equilibrio_invierno(root);destino.mkdir(parents=True,exist_ok=True)
    for n,t in etapa.tablas.items():t.to_csv(destino/(n+'.csv'),sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
    paquete=Path(__file__).parents[1];names=['flujos/equilibrio_invierno.py','flujos/ajuste_invierno.py','demanda/ajuste_invierno.py','operacion/cuotas_cercanas.py','operacion/equilibrio_invierno.py',
        'operacion/ajuste_invierno.py','operacion/invierno.py','operacion/reloj_integrado.py','operacion/refinar_reservas.py','operacion/ventana_horaria.py','operacion/red_compartida.py','operacion/horarios_compartidos.py','operacion/inventario_comun.py','operacion/circulacion_compartida.py','operacion/cierre_con_bases.py']
    meta['codigo_sha256']={'movilidad_teide/'+n:sha256_archivo(paquete/n) for n in names};meta['codigo_sha256']['scripts/buscar_equilibrio_invierno.py']=sha256_archivo(paquete.parents[1]/'scripts/buscar_equilibrio_invierno.py')
    meta['resultados_sha256']={p.name:sha256_archivo(p) for p in sorted(destino.glob('*.csv'))};(destino/'metadatos.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    return etapa,meta
