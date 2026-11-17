"""Coordinar accesos e interior con reservas, sin reducir oferta ni demanda.

Búsqueda determinista de fases y reparto de salidas. Es la mejor construcción
ensayada, no una prueba del mínimo global. Se distinguen vehículos, viajes,
plazas y reserva de vehículos; las condiciones operativas siguen provisionales.
"""
from itertools import product
import math
import numpy as np
import pandas as pd
from movilidad_teide.operacion.circulacion import programar_circulacion
from movilidad_teide.operacion.interior import horario_en_paradas, cargas_por_tramos
from movilidad_teide.opciones import METODO_HORARIOS as METODO
from movilidad_teide.opciones import PUNTOS
from movilidad_teide.opciones import DESTINOS


NUEVOS={'estrategia_horarios_conjuntos','vehiculos_contrato_contraste','banda_ultimas_bajadas_min'}


def verificar_entradas_conjuntas(anterior,actual):
    """Reutilizar entradas físicas/coeficientes, nunca energía anual del horario viejo."""
    if anterior['caso']!=actual['caso'] or anterior['plantilla_tecnica']!=actual['plantilla_tecnica']:
        raise ValueError('Otro caso o plantilla requiere regeneración.')
    before={p['id'] for p in anterior['parametros']};after={p['id']:p for p in actual['parametros']}
    if before&NUEVOS or set(after)-before!=NUEVOS or not before<=set(after):raise ValueError('Adiciones ajenas o criterios incompletos.')
    projected=[p for p in actual['parametros'] if p['id'] not in NUEVOS]
    choices=[p for p in actual['elecciones_todos_los_casos'] if p['id'] not in NUEVOS]
    if anterior['parametros']!=projected or anterior['elecciones_todos_los_casos']!=choices:
        raise ValueError('Se han cambiado otras entradas o elecciones históricas.')
    if after['estrategia_horarios_conjuntos']['valor_utilizado']!=METODO:
        raise ValueError('Estrategia conjunta no implementada.')
    for key in NUEVOS:
        p=after[key]
        if p['modo_efectivo']!='Manual' or not p['justificacion_utilizada']:raise ValueError('Criterio nuevo sin elección y motivo.')
    return {'entradas_previas_identicas':len(before),'elecciones_previas_identicas':len(choices),
        'nuevos_criterios':sorted(NUEVOS),'recalculo_actividad_y_energia_obligatorio':True}


def _interior(c,a,b):
    rows=[]
    for sentido,start in [('ida',a),('vuelta',b)]:
        deps=list(np.arange(start,c['ultima_interior']+1e-7,c['intervalo']))
        if not deps:return None
        if deps[-1]<c['ultima_interior']-1e-7:deps.append(c['ultima_interior'])
        if len(deps)<c['minimo_interior'][sentido]:return None
        for i,t in enumerate(deps):rows.append({'punto':'INTERIOR','sentido':sentido,'salida_min':float(t),
            'id_salida':f'INTERIOR_conjunto_{sentido}_{i:03d}'})
    return pd.DataFrame(rows)


def _lado(c,points,counts,up,back,bias,spread,delays):
    """Escalonar cohortes completas: una plaza no se reutiliza en el mismo tramo."""
    last={q:-1e6 for q in points};left=dict(counts);assigned={q:0 for q in points};total=sum(counts.values());rows=[]
    eligible=[(i,t) for i,t in enumerate(up) if t-c['espera']+c['estancia']<=min(back[-1]+c['duracion_interior']+c['espera'],c['cierre'])]
    for k,(i,t) in enumerate(eligible):
        choices=[]
        for q in points:
            if left[q]<=0:continue
            # La espera de enlace10–20 permite separar las subidas al menos30min.
            arrival=max(t-c['espera'],c['inicio']+c['duraciones'][q][0],last[q]+c['intervalo_acceso'])
            if arrival>t-c['margen']+1e-8:continue
            quota=(k+1)*counts[q]/(len(eligible) if spread else total)
            choices.append((quota-assigned[q]+bias*(q==points[0]),q,arrival))
        if not choices:continue
        if spread and sum(left.values())<len(eligible)-k and max(x[0] for x in choices)<0:continue
        _,q,arrival=max(choices)
        rows.append({'punto':q,'sentido':'ida','salida_min':arrival-c['duraciones'][q][0],
            'llegada_parque_min':arrival,'interior_up_min':t,'slot':i})
        last[q]=arrival;left[q]-=1;assigned[q]+=1
    if any(left.values()):return None
    used=set()
    last_index={q:max(i for i,x in enumerate(rows) if x['punto']==q) for q in points}
    for index,row in enumerate(rows):
        choices=[]
        for j,t in enumerate(back):
            if j in used:continue
            low=max(t+c['duracion_interior']+c['margen'],row['llegada_parque_min']+c['estancia'])
            high=min(t+c['duracion_interior']+c['espera'],c['cierre'])
            # Reservar una última bajada útil en una banda común de30min.
            if index==last_index[row['punto']]:low=max(low,c['cierre']-c['banda_ultimas_bajadas'])
            if low<=high+1e-8:choices.append((min(high,low+delays[row['punto']]),j,t))
        if not choices:return None
        dep,j,t=min(choices);used.add(j);row.update(salida_regreso_min=dep,interior_back_min=t)
    return rows


def _proponer(c,day,a,b,bias,spread,delays):
    counts=c['cuentas'][day];plan=_interior(c,a,b)
    if plan is None:return None
    times={s:plan.loc[plan.sentido.eq(s),'salida_min'].tolist() for s in ['ida','vuelta']}
    cohorts=[]
    for points,sense in [(('VILAFLOR','CHIO'),'ida'),(('OROTAVA','LAGUNA'),'vuelta')]:
        z=_lado(c,points,{q:counts[q,'ida'] for q in points},times[sense],times['vuelta' if sense=='ida' else 'ida'],bias,spread,delays)
        if z is None:return None
        cohorts.extend(z)
    rows=[];pairs=[]
    for q in PUNTOS.values():
        group=[x for x in cohorts if x['punto']==q]
        for j,x in enumerate(group):
            uid=f'{q}_conjunto_ida_{j:03d}';bid=f'{q}_conjunto_vuelta_{j:03d}'
            rows.extend([{'punto':q,'sentido':'ida','salida_min':x['salida_min'],'id_salida':uid},
                         {'punto':q,'sentido':'vuelta','salida_min':x['salida_regreso_min'],'id_salida':bid}])
            pairs.append({**x,'id_subida':uid,'id_regreso':bid,'plazas_vinculadas':c['capacidad']})
        for j in range(counts[q,'vuelta']-counts[q,'ida']):
            # Mantener también las bajadas adicionales de la oferta previa.
            rows.append({'punto':q,'sentido':'vuelta','salida_min':min(c['cierre'],max(x['salida_regreso_min'] for x in group)+c['margen']*(j+1)),
                         'id_salida':f'{q}_conjunto_vuelta_sin_pareja_{j:03d}'})
    return pd.concat([plan,pd.DataFrame(rows)],ignore_index=True),pd.DataFrame(pairs)


def _programar(c,plan):
    rows=[]
    for point,g in plan.groupby('punto'):
        rows.append({'punto':point,'salidas_ida_dia':int(g.sentido.eq('ida').sum()),'salidas_vuelta_dia':int(g.sentido.eq('vuelta').sum()),
            'longitud_ida_km':c['km'][point,'ida'],'longitud_vuelta_km':c['km'][point,'vuelta']})
    z=programar_circulacion(pd.DataFrame(rows),pd.DataFrame(),pd.DataFrame(),c['geografia'],c['valores'],
        salidas_propuestas=plan,plan_completo_reservas=True)
    # No esconder un traslado de cocheras iniciando una guagua de acceso arriba.
    for q in PUNTOS.values():
        origin=c['geografia'].loc[c['geografia'].punto.eq(q)&c['geografia'].sentido.eq('ida'),'origen'].item()
        if not z['vehiculos'].loc[z['vehiculos'].punto.eq(q),'terminal_inicial'].eq(origin).all():return None
    return z


def energia_movimientos(movimientos,referencias,carga_comercial):
    """Sumar factores nativos por recorrido y carga; los vacíos nunca se omiten."""
    allowed={'comercial','comercial_refuerzo_regreso','reposicion_por_horario','reposicion_cierre_diario'}
    if not set(movimientos.componente)<=allowed:raise ValueError('Movimiento sin tratamiento explícito de carga/energía.')
    if not np.isfinite(carga_comercial) or not 0<=carga_comercial<=1:raise ValueError('Carga comercial no válida.')
    keys=['punto','sentido','carga_fisica']
    if referencias.duplicated(keys).any() or referencias.referencia_id.nunique()!=1:
        raise ValueError('Referencias de más de una categoría o condiciones repetidas.')
    if not referencias.Fuel.eq('Diesel Hybrid').all():raise ValueError('La referencia prevista debe ser híbrida.')
    e=referencias.set_index(keys).energia_mj_recorrido.to_dict();rows=[]
    for row in movimientos.to_dict('records'):
        load=carga_comercial if row['componente'].startswith('comercial') else 0.
        key=(row['punto'],row['sentido'],load)
        if key not in e or not np.isfinite(e[key]) or e[key]<=0:raise ValueError('Falta factor nativo compatible para un movimiento.')
        rows.append(e[key])
    return float(sum(rows))


def _contexto(movimientos,objetivos,paradas,referencias,valores,*,capacidad,margen,espera,estancia,contrato,minimos_interiores,intervalo_interior_min=None):
    interval = espera if intervalo_interior_min is None else intervalo_interior_min
    if isinstance(interval,(bool,np.bool_)) or not isinstance(interval,(int,float,np.integer,np.floating)) or not np.isfinite(interval) or not 0<interval<=espera:
        raise ValueError('Intervalo interior no válido o mayor que la espera máxima.')
    numeric=[capacidad,margen,espera,estancia,contrato,valores['reserva_flota'],valores['intervalo_minimo_subidas_min'],valores['banda_ultimas_bajadas_min']]
    if not np.isfinite(numeric).all() or min(numeric)<0 or capacidad<=0 or capacidad!=int(capacidad) or contrato<=0 or contrato!=int(contrato) or espera<margen or margen<=0 or estancia<=0:
        raise ValueError('Capacidad, tiempos, contrato o reserva no válidos.')
    if valores['reserva_flota']>1:raise ValueError('Reserva fuera del dominio.')
    if objetivos.duplicated(['tipo_dia','punto']).any() or set(objetivos.punto)!=set(PUNTOS.values()):raise ValueError('Objetivos incompletos o repetidos.')
    if not np.isfinite(objetivos.demanda_lanzadera_condicionada_dia).all() or objetivos.demanda_lanzadera_condicionada_dia.lt(0).any():raise ValueError('Demanda inválida.')
    if set(objetivos.tipo_dia)!=set(movimientos.tipo_dia) or movimientos.duplicated(['tipo_dia','id_salida']).any():raise ValueError('Días o identificadores no coherentes.')
    commercial=movimientos.loc[movimientos.componente.str.startswith('comercial')]
    geo=movimientos[['punto','sentido','origen','destino','itinerary_id']].drop_duplicates()
    if geo.duplicated(['punto','sentido']).any() or geo.itinerary_id.isna().any():raise ValueError('Geografía ambigua o sin itinerario.')
    durations={}
    for q in PUNTOS.values():
        duration=[]
        for sense in ['ida','vuelta']:
            g=movimientos.loc[movimientos.punto.eq(q)&movimientos.sentido.eq(sense)]
            x=(g.llegada_min-g.salida_min).unique()
            if len(x)!=1 or x[0]<=0:raise ValueError('Duraciones por sentido ambiguas.')
            duration.append(float(x[0]))
        durations[q]=tuple(duration)
    inner=movimientos.loc[movimientos.punto.eq('INTERIOR')]
    ds=(inner.llegada_min-inner.salida_min).unique()
    if len(ds)!=1:raise ValueError('Esta búsqueda requiere duración interior simétrica; no sustituirla silenciosamente.')
    km=movimientos.groupby(['punto','sentido']).km_por_recorrido
    if km.nunique().gt(1).any():raise ValueError('Distancias contradictorias.')
    counts={day:g.loc[g.punto.ne('INTERIOR')].groupby(['punto','sentido']).size().to_dict() for day,g in commercial.groupby('tipo_dia')}
    for day,table in counts.items():
        for q in PUNTOS.values():
            if (q,'ida') not in table or table.get((q,'vuelta'),0)<table[q,'ida']:raise ValueError('Oferta incompatible con parejas conservadas.')
            need=objetivos.loc[objetivos.tipo_dia.eq(day)&objetivos.punto.eq(q),'demanda_lanzadera_condicionada_dia'].item()
            if need>table[q,'ida']*capacidad+1e-8:raise ValueError('La oferta de acceso no alcanza la demanda; requiere decisión explícita de refuerzo.')
    if set(DESTINOS.values())-set(paradas.parada_id):raise ValueError('Faltan destinos documentados.')
    if set(minimos_interiores)!={'ida','vuelta'} or any(not isinstance(n,(int,np.integer)) or n<=0 for n in minimos_interiores.values()):raise ValueError('Oferta interior mínima sin sentidos o viajes enteros positivos.')
    return {'duraciones':durations,'duracion_interior':float(ds[0]),'geografia':geo,'km':km.first().to_dict(),'cuentas':counts,
        'minimo_interior':dict(minimos_interiores), # Cantidades leídas de la oferta D157, sin inventar servicios.
        'ultima_interior':float(inner.llegada_min.max()-ds[0]),'intervalo':float(interval),'espera':float(espera),'margen':float(margen),
        'estancia':float(estancia),'inicio':float(commercial.loc[commercial.punto.ne('INTERIOR'),'salida_min'].min()),
        'cierre':60*valores['hora_limite_bajada_parque'],'banda_ultimas_bajadas':float(valores['banda_ultimas_bajadas_min']),'intervalo_acceso':float(valores['intervalo_minimo_subidas_min']),
        'capacidad':int(capacidad),'referencias':referencias,'valores':valores,'contrato':int(contrato),'paradas':paradas}


def optimizar_horarios_conjuntos(movimientos,objetivos,paradas,referencias,valores,*,capacidad,margen,espera,estancia,contrato,minimos_interiores,intervalo_interior_min=None):
    """Buscar fases comunes del interior y escalonar accesos por día tipo.

    Conservo todos los viajes comerciales de cada acceso/sentido y un mínimo
    de viajes interiores leído de D157. Primero minimizo vehículos físicos asignados al
    conjunto de días, después energía anual. Cada base conserva sus vehículos;
    la reserva del20% se añade al conjunto, nunca se confunde con viajes.
    """
    c=_contexto(movimientos,objetivos,paradas,referencias,valores,capacidad=capacidad,margen=margen,espera=espera,estancia=estancia,contrato=contrato,minimos_interiores=minimos_interiores,intervalo_interior_min=intervalo_interior_min)
    cache={};records=[];candidates={day:[] for day in objetivos.tipo_dia.unique()}
    def evaluate(day,a,b,bias,spread,delays):
        delays={q:float(delays[q]) for q in PUNTOS.values()}
        key=(day,a,b,bias,spread,tuple(delays.values()))
        if key in cache:return cache[key]
        number=len(records)+1
        record={'candidato_id':number,'tipo_dia':day,'primera_boca_min':a,'primera_portillo_min':b,'prioridad_reparto':bias,'repartir_en_ventana':spread,
            **{'ajuste_regreso_'+q+'_min':d for q,d in delays.items()},'factible':False}
        proposed=_proponer(c,day,a,b,bias,spread,delays)
        if proposed is None:records.append(record);cache[key]=None;return None
        plan,pairs=proposed;physical=_programar(c,plan)
        if physical is None:records.append(record);cache[key]=None;return None
        fleet=physical['vehiculos'].groupby(['punto','terminal_inicial']).size().to_dict()
        cost=energia_movimientos(physical['movimientos'],referencias,valores['carga_copert'])
        days=int(objetivos.loc[objetivos.tipo_dia.eq(day),'dias_calendario'].iloc[0])
        record.update(factible=True,guaguas_fisicas_dia=sum(fleet.values()),hot_mj_dia=cost,vehiculo_km_dia=float(physical['movimientos'].km_por_recorrido.sum()),
            **{'guaguas_'+q:sum(n for (point,_),n in fleet.items() if point==q) for q in [*PUNTOS.values(),'INTERIOR']})
        result={'record':record,'plan':plan,'pares':pairs,'programacion':physical,'bases':fleet,'dias':days,'fase':(a,b),'retrasos':delays}
        records.append(record);candidates[day].append(result);cache[key]=result;return result
    start_a=c['inicio']+c['duraciones']['VILAFLOR'][0]+margen
    start_b=c['inicio']+c['duraciones']['OROTAVA'][0]+margen
    # Universo acotado y reproducible de desfases; no modificar tiempos de viaje.
    for day in candidates:
        for a,b,bias,spread,delay in product([start_a,start_a+espera-margen],[start_b,start_b+espera/2,start_b+espera],[-.5,0.,.5],[True,False],[0.,5.,10.]):
            evaluate(day,a,b,bias,spread,{q:delay for q in PUNTOS.values()})
        seeds=[];seen=set()
        for x in sorted(candidates[day],key=lambda x:(x['record']['guaguas_fisicas_dia'],x['record']['hot_mj_dia'])):
            k=(x['fase'],x['record']['prioridad_reparto'],x['record']['repartir_en_ventana'])
            if k not in seen:seeds.append(x);seen.add(k)
            if len(seeds)==4:break
        # Refinar el enlace de cada corredor sin alterar su capacidad o cierres.
        for seed in seeds:
            current=seed
            for q in PUNTOS.values():
                trials=[evaluate(day,*seed['fase'],seed['record']['prioridad_reparto'],seed['record']['repartir_en_ventana'],{**current['retrasos'],q:d}) for d in [0.,5.,10.]]
                valid=[x for x in trials if x is not None]
                if valid:current=min([current,*valid],key=lambda x:(x['record']['guaguas_fisicas_dia'],x['record']['hot_mj_dia']))
        if not candidates[day]:raise ValueError('No se construye un horario factible para '+day+'; no se reduce demanda.')
    # La misma fase interior todos los días evita tres relojes incompatibles.
    best=None;portfolios=0
    phases=set.intersection(*[{x['fase'] for x in g} for g in candidates.values()])
    for phase in sorted(phases):
        groups=[]
        for day,group in candidates.items():
            byfleet={}
            for x in group:
                if x['fase']!=phase:continue
                key=tuple(sorted(x['bases'].items()))
                if key not in byfleet or x['record']['hot_mj_dia']<byfleet[key]['record']['hot_mj_dia']:byfleet[key]=x
            groups.append(list(byfleet.values()))
        for combo in product(*groups):
            portfolios+=1;bases=set().union(*(set(x['bases']) for x in combo))
            pool={k:max(x['bases'].get(k,0) for x in combo) for k in sorted(bases)}
            vehicles=sum(pool.values());energy=sum(x['record']['hot_mj_dia']*x['dias'] for x in combo)
            score=(vehicles,round(energy,6),phase)
            if best is None or score<best[0]:best=(score,combo,pool)
    if best is None:raise ValueError('No hay fase interior común factible entre días.')
    _,chosen,pool=best
    combined={name:[] for name in ['movimientos','vehiculos','pares','resumen','cargas_tramos','reservas_tramos','salidas','equilibrio']}
    order=paradas.set_index('parada_id').orden.to_dict();entry={paradas.iloc[0].lugar:paradas.iloc[0].parada_id,paradas.iloc[-1].lugar:paradas.iloc[-1].parada_id}
    for x in chosen:
        day=x['record']['tipo_dia'];days=x['dias'];moves=x['programacion']['movimientos'].assign(tipo_dia=day,dias_calendario=days)
        fleet=x['programacion']['vehiculos'].assign(tipo_dia=day,dias_calendario=days)
        times=horario_en_paradas(moves,paradas);ht=times.set_index(['id_salida','parada_id']).paso_min.to_dict()
        btrips=moves.loc[moves.componente.eq('comercial')].set_index('id_salida')
        reservations=[];pairs=[]
        for row in x['pares'].to_dict('records'):
            q=row['punto'];n=int(x['pares'].punto.eq(q).sum());need=float(objetivos.loc[objetivos.tipo_dia.eq(day)&objetivos.punto.eq(q),'demanda_lanzadera_condicionada_dia'].item())
            qty=need/n
            if qty>capacidad+1e-8:raise ValueError('La reserva supera la capacidad.')
            a=btrips.loc[row['id_subida']];back=btrips.loc[row['id_regreso']];start=entry[a.destino];target=DESTINOS[q]
            direct='ida' if order[start]<order[target] else 'vuelta';reverse='vuelta' if direct=='ida' else 'ida'
            outward=x['plan'].loc[x['plan'].punto.eq('INTERIOR')&x['plan'].sentido.eq(direct)&np.isclose(x['plan'].salida_min,row['interior_up_min'])].iloc[0]
            returning=x['plan'].loc[x['plan'].punto.eq('INTERIOR')&x['plan'].sentido.eq(reverse)&np.isclose(x['plan'].salida_min,row['interior_back_min'])].iloc[0]
            uid=outward.id_salida;rid=returning.id_salida
            arrivals=ht[uid,target];pickup=ht[rid,target];waitup=outward.salida_min-a.llegada_min;waitback=back.salida_min-ht[rid,start]
            if min(waitup,waitback)<margen-1e-8 or max(waitup,waitback)>espera+1e-8 or back.salida_min-a.llegada_min<estancia-1e-8 or pickup<arrivals-1e-8:raise ValueError('Cadena sin enlace, visita o regreso.')
            pairs.append({**row,'id_interior_ida':uid,'id_interior_regreso':rid,'parada_entrada':start,'parada_destino':target,
                'personas_asignadas_dia_tipo':qty,'espera_enlace_ida_min':waitup,'espera_enlace_regreso_min':waitback,
                'llegada_destino_min':arrivals,'salida_destino_min':pickup,'ventana_en_destino_min':pickup-arrivals})
            reservations.extend([{'id_salida':uid,'parada_origen':start,'parada_destino':target,'personas':qty},
                                 {'id_salida':rid,'parada_origen':target,'parada_destino':start,'personas':qty}])
        reservations=pd.DataFrame(reservations);pairs=pd.DataFrame(pairs);loads=cargas_por_tramos(times,paradas,reservations,capacidad=capacidad)
        for q,g in moves.loc[moves.punto.ne('INTERIOR')&moves.componente.eq('comercial')&moves.sentido.eq('ida')].groupby('punto'):
            if g.sort_values('salida_min').salida_min.diff().dropna().lt(c['intervalo_acceso']-1e-8).any():raise ValueError('Subidas no laminadas con el intervalo elegido.')
        for (q,base),size in pool.items():
            first=fleet.loc[fleet.punto.eq(q)&fleet.terminal_inicial.eq(base)].shape[0]
            group=moves.loc[moves.punto.eq(q)].sort_values('llegada_min').groupby('vehiculo_id').last()
            last=int(group.destino.eq(base).sum())
            if first!=last:raise ValueError('Un traslado entre jornadas queda sin representar.')
            combined['equilibrio'].append({'tipo_dia':day,'punto':q,'base':base,'vehiculos_pool':size,'vehiculos_activos_inicio':first,
                'vehiculos_activos_final':last,'vehiculos_no_asignados_ese_dia':size-first,'equilibrio_comprobado':True})
        for point,g in moves.groupby('punto'):
            commercial=g.componente.eq('comercial');nf=fleet.loc[fleet.punto.eq(point)].shape[0]
            combined['resumen'].append({'tipo_dia':day,'dias_calendario':days,'punto':point,'guaguas_fisicas_asignadas_dia':nf,
                'viajes_comerciales_ida_dia':int((commercial&g.sentido.eq('ida')).sum()),'viajes_comerciales_vuelta_dia':int((commercial&g.sentido.eq('vuelta')).sum()),
                'recorridos_vacios_dia':int((~commercial).sum()),'vehiculo_km_dia':float(g.km_por_recorrido.sum()),
                'hot_mwh_anio':energia_movimientos(g,referencias,valores['carga_copert'])*days/3600,'candidato_id':x['record']['candidato_id']})
        combined['movimientos'].append(moves);combined['vehiculos'].append(fleet)
        combined['pares'].append(pairs.assign(tipo_dia=day,dias_calendario=days));combined['cargas_tramos'].append(loads.assign(tipo_dia=day,dias_calendario=days))
        combined['reservas_tramos'].append(reservations.assign(tipo_dia=day));combined['salidas'].append(x['plan'].assign(tipo_dia=day))
    result={key:pd.DataFrame(value) if key in {'resumen','equilibrio'} else pd.concat(value,ignore_index=True) for key,value in combined.items()}
    pool_count=sum(pool.values());reserve=int(math.ceil(pool_count*valores['reserva_flota']-1e-10))
    result.update(intentos=pd.DataFrame(records),pool=pd.DataFrame([{'punto':q,'base':base,'guaguas_fisicas_pool':size} for (q,base),size in pool.items()]),
        diagnostico={'metodo':METODO,'candidatos_evaluados':len(records),'candidatos_factibles':sum(x['factible'] for x in records),'combinaciones_entre_dias':portfolios,
            'fase_interior_comun':{'Boca Tauce':float(chosen[0]['fase'][0]),'El Portillo':float(chosen[0]['fase'][1])},
            'intervalo_interior_ensayado_min':c['intervalo'],
            'guaguas_fisicas_pool_operativo':pool_count,'guaguas_fisicas_reserva':reserve,'guaguas_fisicas_con_reserva':pool_count+reserve,
            'reserva_proporcion':valores['reserva_flota'],'banda_ultima_bajada_min':[c['cierre']-c['banda_ultimas_bajadas'],c['cierre']],'vehiculos_del_contrato_para_contraste':int(contrato),
            'encaje_numerico_en_contrato':pool_count+reserve<=contrato,'disponibilidad_confirmada':False,'minimo_global_demostrado':False,
            'criterio':'Primero vehículos físicos por base en el conjunto de días; después Hot anual. Demanda y oferta de accesos conservadas, sin criterio de ahorro mínimo.'})
    return result


def contrastar_circulacion_con_flota(movimientos, valores, *, contrato):
    """Reducir kilómetros vacíos con las mismas salidas y flota disponible.

    Contraste físico separado del escenario adoptado: conserva interior,
    horarios y billetes. Ensaya cantidades de vehículos en cada acceso y
    minimiza kilómetros anuales; no usa factores ni un objetivo de ahorro.
    El emparejamiento ensayado no acredita un óptimo global.
    """
    reserve = valores.get('reserva_flota')
    if (isinstance(contrato, (bool, np.bool_)) or not isinstance(contrato, (int, float, np.integer, np.floating))
            or not np.isfinite(contrato) or contrato <= 0 or contrato != int(contrato)
            or isinstance(reserve, (bool, np.bool_)) or not isinstance(reserve, (int, float, np.integer, np.floating))
            or not np.isfinite(reserve) or not 0 <= reserve <= 1):
        raise ValueError('Contrato o reserva de flota no válidos.')
    keys = ['tipo_dia', 'punto', 'sentido', 'id_salida', 'vehiculo_id', 'componente',
            'salida_min', 'llegada_min', 'km_por_recorrido', 'dias_calendario', 'origen', 'destino', 'itinerary_id']
    if movimientos.empty or set(keys) - set(movimientos):
        raise ValueError('Horario incompleto.')
    allowed = {'comercial', 'comercial_refuerzo_regreso', 'reposicion_por_horario', 'reposicion_cierre_diario'}
    if movimientos.componente.isna().any() or set(movimientos.componente) - allowed:
        raise ValueError('Movimiento sin tratamiento explícito; no se elimina del contraste.')
    if movimientos.duplicated(['tipo_dia', 'id_salida']).any():
        raise ValueError('Salidas repetidas; seleccionar un solo caso.')
    numeric = ['salida_min', 'llegada_min', 'km_por_recorrido', 'dias_calendario']
    if (not np.isfinite(movimientos[numeric]).all().all()
            or movimientos.km_por_recorrido.le(0).any()
            or movimientos.dias_calendario.le(0).any()
            or movimientos.dias_calendario.mod(1).ne(0).any()
            or movimientos.groupby('tipo_dia').dias_calendario.nunique().ne(1).any()):
        raise ValueError('Distancias, tiempos o calendario inválidos.')
    if set(movimientos.punto) != {*PUNTOS.values(), 'INTERIOR'}:
        raise ValueError('Faltan servicios del sistema.')
    days = sorted(movimientos.tipo_dia.unique())
    expected = {(d, q) for d in days for q in [*PUNTOS.values(), 'INTERIOR']}
    if set(movimientos.groupby(['tipo_dia', 'punto']).groups) != expected:
        raise ValueError('Falta un servicio en algún día tipo.')
    rcount = lambda n: int(math.ceil(n * reserve - 1e-10))
    maximum = max((n for n in range(1, int(contrato) + 1) if n + rcount(n) <= contrato), default=0)
    groups = {key: g.copy() for key, g in movimientos.groupby(['tipo_dia', 'punto'])}

    def fleet_from_moves(g):
        first = g.sort_values(['salida_min', 'id_salida']).groupby('vehiculo_id', sort=True).first()
        return first.reset_index()[['vehiculo_id', 'punto', 'origen']].rename(columns={'origen': 'terminal_inicial'})

    def pool_size(tables):
        f = pd.concat([fleet_from_moves(g).assign(tipo_dia=d) for d, g in tables.items()], ignore_index=True)
        return int(f.groupby(['tipo_dia', 'terminal_inicial']).size().unstack(fill_value=0).max().sum())

    baseline = {q: pool_size({d: groups[d, q] for d in days}) for q in [*PUNTOS.values(), 'INTERIOR']}
    slack = maximum - sum(baseline.values())
    if slack < 0:
        raise ValueError('La oferta conservada ya excede el contrato con reserva.')
    attempts = []
    options = {}
    for q in sorted(PUNTOS.values()):
        candidates = {}
        for d in days:
            old = groups[d, q]
            n = old.vehiculo_id.nunique()
            candidates[d] = [(old, n, -1)]  # Conservar siempre la construcción previa.
            plan = old.loc[old.componente.str.startswith('comercial'), ['punto', 'sentido', 'salida_min', 'id_salida']]
            geo = old[['punto', 'sentido', 'origen', 'destino', 'itinerary_id']].drop_duplicates()
            if geo.duplicated(['punto', 'sentido']).any() or set(geo.sentido) != {'ida', 'vuelta'}:
                raise ValueError('Geografía incompatible.')
            summary = {'punto': q}
            for s in ['ida', 'vuelta']:
                lengths = old.loc[old.sentido.eq(s), 'km_por_recorrido'].unique()
                if len(lengths) != 1:
                    raise ValueError('Distancias contradictorias por sentido.')
                summary['salidas_' + s + '_dia'] = int(plan.sentido.eq(s).sum())
                summary['longitud_' + s + '_km'] = float(lengths[0])
            lower = geo.loc[geo.sentido.eq('ida'), 'origen'].item()
            for limit in range(n, min(baseline[q] + slack, len(plan)) + 1):
                z = programar_circulacion(pd.DataFrame([summary]), pd.DataFrame(), pd.DataFrame(), geo, valores,
                    salidas_propuestas=plan, plan_completo_reservas=True, vehiculos_por_servicio={q: limit})
                g = z['movimientos'].assign(tipo_dia=d, dias_calendario=int(old.dias_calendario.iloc[0]))
                # Rechazar inicios en montaña: no ocultar desplazamientos desde la base.
                valid = bool(z['vehiculos'].terminal_inicial.eq(lower).all())
                number = len(attempts)
                attempts.append({'intento_id': number, 'tipo_dia': d, 'punto': q, 'vehiculos_solicitados': limit,
                    'inicio_en_cabecera_comprobado': valid, 'vehiculo_km_dia': float(g.km_por_recorrido.sum()),
                    'recorridos_vacios_dia': int((~g.componente.str.startswith('comercial')).sum())})
                if valid:
                    candidates[d].append((g, limit, number))
        options[q] = []
        for cap in range(baseline[q], baseline[q] + slack + 1):
            chosen = {d: min((c for c in candidates[d] if c[1] <= cap),
                key=lambda c: (round(float(c[0].km_por_recorrido.sum()), 9), c[1], c[2])) for d in days}
            tables = {d: c[0] for d, c in chosen.items()}
            options[q].append({'tablas': tables, 'pool': pool_size(tables),
                'km_anio': sum(float(g.km_por_recorrido.sum() * g.dias_calendario.iloc[0]) for g in tables.values()),
                'intentos': {d: int(c[2]) for d, c in chosen.items()}})
    inner = {d: groups[d, 'INTERIOR'] for d in days}
    inner_km = sum(float(g.km_por_recorrido.sum() * g.dias_calendario.iloc[0]) for g in inner.values())
    frontier = []
    best = None
    for combo in product(*(options[q] for q in sorted(options))):
        count = baseline['INTERIOR'] + sum(x['pool'] for x in combo)
        km = inner_km + sum(x['km_anio'] for x in combo)
        row = {'alternativa_id': len(frontier), 'guaguas_fisicas_pool': count, 'reserva': rcount(count),
            'total_con_reserva': count + rcount(count), 'vehiculo_km_anio': km,
            'encaje_numerico': bool(count + rcount(count) <= contrato)}
        frontier.append(row)
        score = (round(km, 6), count, row['alternativa_id'])
        if row['encaje_numerico'] and (best is None or score < best[0]):
            best = (score, combo, row)
    if best is None:
        raise ValueError('Sin construcción que encaje con la reserva.')
    _, selected, record = best
    moves = pd.concat([*inner.values(), *[g for x in selected for g in x['tablas'].values()]], ignore_index=True)
    commercial_keys = ['tipo_dia', 'punto', 'sentido', 'id_salida', 'salida_min', 'llegada_min', 'origen', 'destino', 'itinerary_id', 'km_por_recorrido']
    commercial = lambda g: g.loc[g.componente.str.startswith('comercial'), commercial_keys].sort_values(['tipo_dia', 'id_salida']).reset_index(drop=True)
    pd.testing.assert_frame_equal(commercial(movimientos), commercial(moves), check_dtype=False)
    fleets = []
    balances = []
    summaries = []
    for (d, q), g in moves.groupby(['tipo_dia', 'punto']):
        first = fleet_from_moves(g)
        last = g.sort_values(['llegada_min', 'id_salida']).groupby('vehiculo_id').last()
        start_count = first.terminal_inicial.value_counts().sort_index()
        end_count = last.destino.value_counts().sort_index()
        pd.testing.assert_series_equal(start_count, end_count, check_names=False)
        for _, chain in g.groupby('vehiculo_id'):
            chain = chain.sort_values('salida_min')
            if (not np.array_equal(chain.destino.iloc[:-1], chain.origen.iloc[1:])
                    or np.any(chain.salida_min.iloc[1:].to_numpy() < chain.llegada_min.iloc[:-1].to_numpy() + valores['regulacion_min'] - 1e-8)):
                raise ValueError('Circulación sin continuidad o regulación.')
        fleets.append(first.assign(tipo_dia=d))
        for base, count in start_count.items():
            balances.append({'tipo_dia': d, 'punto': q, 'base': base,
                'vehiculos_inicio': int(count), 'vehiculos_final': int(end_count[base])})
        old = groups[d, q]
        summaries.append({'tipo_dia': d, 'punto': q, 'dias_calendario': int(g.dias_calendario.iloc[0]),
            'vehiculos_antes': int(old.vehiculo_id.nunique()), 'vehiculos_propuesta': len(first),
            'km_antes_dia': float(old.km_por_recorrido.sum()), 'km_propuesta_dia': float(g.km_por_recorrido.sum()),
            'vacios_antes_dia': int((~old.componente.str.startswith('comercial')).sum()),
            'vacios_propuesta_dia': int((~g.componente.str.startswith('comercial')).sum())})
    return {'movimientos': moves, 'vehiculos': pd.concat(fleets, ignore_index=True),
        'equilibrio': pd.DataFrame(balances), 'resumen': pd.DataFrame(summaries),
        'intentos': pd.DataFrame(attempts),
        'alternativas': pd.DataFrame(frontier).assign(seleccionada=lambda x: x.alternativa_id.eq(record['alternativa_id'])),
        'diagnostico': {**record, 'pool_previo': sum(baseline.values()), 'reserva_proporcion': float(reserve),
            'contrato_contraste': int(contrato), 'minimo_global_demostrado': False,
            'criterio': 'Menor kilometraje anual entre las construcciones ensayadas que encajan con reserva; mismas salidas, interior y demanda. Sin objetivo energético.',
            'estado': 'Propuesta técnica no adoptada en el Excel; disponibilidad y explotación reales pendientes.'}}
