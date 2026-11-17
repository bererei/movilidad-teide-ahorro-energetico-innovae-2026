"""Límites y ampliaciones de reservas, conservando el horario de partida.

Una construcción es una propuesta. Reducir el intervalo exige indicarlo;
la capacidad por plazas no acredita encaje en la flota o adopción operativa.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from movilidad_teide.opciones import PUNTOS
from movilidad_teide.operacion.interior import horario_en_paradas
from movilidad_teide.operacion.circulacion import programar_circulacion
from movilidad_teide.energia.sensibilidad_modal import reasignar_en_horario_conservado


def limites_por_intervalo(objetivos, movimientos, valores, *, capacidad):
    """Cota necesaria y favorable por apertura, estancia, viaje y cierre.

    Omite conflictos interiores y de flota: superarla demuestra incompatibilidad;
    quedar por debajo no demuestra que exista una operación completa.
    """
    required={'matrix_index','punto','demanda_lanzadera_condicionada_dia'}
    if not required<=set(objetivos) or objetivos.duplicated(['matrix_index','punto']).any():
        raise ValueError('Objetivos incompletos o repetidos.')
    numbers=[capacidad,valores['hora_inicio_acceso'],valores['hora_limite_bajada_parque'],
             valores['estancia_min_visita_min'],valores['intervalo_minimo_subidas_min']]
    if any(isinstance(x,(bool,np.bool_)) for x in numbers) or not np.isfinite(numbers).all() or capacidad<=0 or capacidad!=int(capacidad) or min(numbers[3:])<=0:
        raise ValueError('Capacidad o tiempos inválidos.')
    start=60*valores['hora_inicio_acceso'];close=60*valores['hora_limite_bajada_parque']
    if not 0<=start<close<=1440:raise ValueError('Apertura y cierre incompatibles.')
    need=objetivos.demanda_lanzadera_condicionada_dia
    if not np.isfinite(need).all() or need.lt(0).any():raise ValueError('Demanda ausente o negativa.')
    rows=[]
    for row in objetivos.itertuples():
        d=movimientos.loc[movimientos.punto.eq(row.punto)&movimientos.sentido.eq('ida'),'tiempo_recorrido_min'].unique()
        if len(d)!=1 or not np.isfinite(d[0]) or d[0]<=0:raise ValueError('Duración de acceso ausente o contradictoria.')
        last=close-valores['estancia_min_visita_min']-d[0]
        n=max(0,math.floor((last-start)/valores['intervalo_minimo_subidas_min']+1e-10)+1)
        count=math.ceil(max(0,row.demanda_lanzadera_condicionada_dia-1e-8)/capacidad)
        rows.append({'matrix_index':int(row.matrix_index),'punto':row.punto,'demanda_personas_dia':row.demanda_lanzadera_condicionada_dia,
            'parejas_necesarias':count,'primera_subida_min':start,'ultima_subida_cota_min':last,
            'intervalo_minimo_vigente_min':valores['intervalo_minimo_subidas_min'],
            'parejas_maximas_cota_favorable':n,'plazas_cota_favorable':n*capacidad,
            'incompatible_incluso_sin_conflictos_interiores':count>n,
            'cota_intervalo_para_n_parejas_min':(last-start)/(count-1) if count>1 and last>=start else np.nan})
    return pd.DataFrame(rows)


def _minimo_vehiculos(salidas, duraciones, regulacion):
    """Cardinalidad de cadenas compatibles; el programador verifica después."""
    n=len(salidas);adj=[]
    for sense,departure in salidas:
        reverse='vuelta' if sense=='ida' else 'ida'
        adj.append([j for j,(other,time) in enumerate(salidas)
                    if departure+duraciones[sense]+regulacion+(duraciones[reverse]+regulacion if sense==other else 0)<=time+1e-8])
    matched={}
    def visit(i,seen):
        for j in adj[i]:
            if j in seen:continue
            seen.add(j)
            if j not in matched or visit(matched[j],seen):matched[j]=i;return True
        return False
    for i in range(n):visit(i,set())
    return n-len(matched)


def ampliar_cadenas_conservadas(movimientos, pares, objetivos, paradas, valores, *,
                                intervalo_propuesto_min=None, prioridad=('VILAFLOR','CHIO','OROTAVA','LAGUNA')):
    """Añadir cadenas sin mover billetes, interior o bajadas sin pareja.

    Ensayo determinista de huecos del reloj existente, con espera máxima en la
    llegada. Primero mínimo de vehículos del acceso, después separación entre
    subidas y regreso temprano. No se usa energía o ahorro para elegir horarios.
    El fracaso de esta búsqueda no prueba un mínimo global o imposibilidad.
    """
    points=set(PUNTOS.values());day=objetivos.tipo_dia.unique()
    interval=valores['intervalo_minimo_subidas_min'] if intervalo_propuesto_min is None else intervalo_propuesto_min
    if (len(day)!=1 or objetivos.duplicated(['tipo_dia','punto']).any() or set(objetivos.punto)!=points
            or set(prioridad)!=points or len(prioridad)!=len(points) or movimientos.tipo_dia.nunique()!=1
            or pares.tipo_dia.nunique()!=1 or set(movimientos.tipo_dia)!=set(day) or set(pares.tipo_dia)!=set(day)):
        raise ValueError('Seleccionar un día y los cuatro corredores sin duplicados.')
    if isinstance(interval,(bool,np.bool_)) or not np.isfinite(interval) or interval<=0:
        raise ValueError('Intervalo propuesto inválido.')
    need=objetivos.set_index('punto').demanda_lanzadera_condicionada_dia
    if not np.isfinite(need).all() or need.lt(0).any():raise ValueError('Demanda inválida.')
    capacity=int(valores['plazas_guagua']*valores['ocupacion_diseno'])
    if capacity<=0:raise ValueError('Capacidad inválida.')
    commercial=movimientos.loc[movimientos.componente.eq('comercial'),['punto','sentido','salida_min','id_salida']].copy()
    if commercial.id_salida.duplicated().any() or pares.id_subida.duplicated().any() or pares.id_regreso.duplicated().any():
        raise ValueError('Salidas o reservas repetidas.')
    if not (set(pares.id_subida)|set(pares.id_regreso))<=set(commercial.id_salida):raise ValueError('Reserva sin salida.')
    target={q:max(int(pares.punto.eq(q).sum()),math.ceil(max(0,float(need[q])-1e-8)/capacity)) for q in points}
    links=pares.copy(deep=True);order=paradas.set_index('parada_id').orden.to_dict()
    clock=horario_en_paradas(movimientos,paradas).set_index(['id_salida','parada_id']).paso_min.to_dict()
    def pathkeys(tid,a,b):
        low,high=sorted([order[a],order[b]])
        return {(tid,k) for k in range(int(low),int(high))}
    busy=set()
    for row in links.itertuples():
        busy|=pathkeys(row.id_interior_ida,row.parada_entrada,row.parada_destino)|pathkeys(row.id_interior_regreso,row.parada_destino,row.parada_entrada)
    inner=movimientos.loc[movimientos.punto.eq('INTERIOR')&movimientos.componente.eq('comercial')]
    start=60*valores['hora_inicio_acceso'];close=60*valores['hora_limite_bajada_parque']
    margin=valores['margen_enlace_interior_min'];wait=valores['espera_max_lanzadera_min'];stay=valores['estancia_min_visita_min']
    for q in prioridad:
        seed=pares.loc[pares.punto.eq(q)].iloc[0].to_dict()
        durations={s:float(movimientos.loc[movimientos.punto.eq(q)&movimientos.sentido.eq(s),'tiempo_recorrido_min'].iloc[0]) for s in ['ida','vuelta']}
        side='ida' if order[seed['parada_entrada']]<order[seed['parada_destino']] else 'vuelta'
        reverse='vuelta' if side=='ida' else 'ida'
        for j in range(target[q]-int(links.punto.eq(q).sum())):
            candidates=[];existing=commercial.loc[commercial.punto.eq(q)&commercial.sentido.eq('ida'),'salida_min'].to_numpy()
            qrows=list(commercial.loc[commercial.punto.eq(q),['sentido','salida_min']].itertuples(index=False,name=None))
            for a in inner.loc[inner.sentido.eq(side)].itertuples():
                usedout=pathkeys(a.id_salida,seed['parada_entrada'],seed['parada_destino'])
                if busy&usedout:continue
                arrival=a.salida_min-wait;departure=arrival-durations['ida']
                if departure<start-1e-8 or np.min(np.abs(existing-departure))<interval-1e-8:continue
                for b in inner.loc[inner.sentido.eq(reverse)].itertuples():
                    usedback=pathkeys(b.id_salida,seed['parada_destino'],seed['parada_entrada'])
                    if busy&usedback:continue
                    first=max(clock[b.id_salida,seed['parada_entrada']]+margin,arrival+stay)
                    last=min(clock[b.id_salida,seed['parada_entrada']]+wait,close)
                    if first>last+1e-8 or clock[b.id_salida,seed['parada_destino']]<clock[a.id_salida,seed['parada_destino']]-1e-8:continue
                    nf=_minimo_vehiculos(qrows+[('ida',departure),('vuelta',first)],durations,valores['regulacion_min'])
                    score=(-nf,float(np.min(np.abs(existing-departure))),-departure,-first)
                    candidates.append((score,a,b,departure,arrival,first,usedout|usedback))
            if not candidates:return {'construccion_completa':False,'motivo':'No se construye ampliación conservando el reloj; no demuestra imposibilidad global.','punto_sin_construccion':q}
            _,a,b,dep,arrival,ret,used=max(candidates,key=lambda t:t[0]);busy|=used
            uid=f'{q}_ampliacion_ida_{j:03d}';bid=f'{q}_ampliacion_vuelta_{j:03d}'
            extra={**seed,'id_subida':uid,'id_regreso':bid,'salida_min':dep,'llegada_parque_min':arrival,'salida_regreso_min':ret,
                'id_interior_ida':a.id_salida,'id_interior_regreso':b.id_salida,'interior_up_min':a.salida_min,'interior_back_min':b.salida_min,
                'personas_asignadas_dia_tipo':float(capacity),'slot':np.nan,'plazas_vinculadas':capacity}
            links=pd.concat([links,pd.DataFrame([extra])],ignore_index=True)
            commercial=pd.concat([commercial,pd.DataFrame([{'punto':q,'sentido':'ida','salida_min':dep,'id_salida':uid},
                {'punto':q,'sentido':'vuelta','salida_min':ret,'id_salida':bid}])],ignore_index=True)
    geo=movimientos[['punto','sentido','origen','destino','itinerary_id']].drop_duplicates();summaries=[]
    for q,g in commercial.groupby('punto'):
        summaries.append({'punto':q,'salidas_ida_dia':int(g.sentido.eq('ida').sum()),'salidas_vuelta_dia':int(g.sentido.eq('vuelta').sum()),
            **{'longitud_'+s+'_km':float(movimientos.loc[movimientos.punto.eq(q)&movimientos.sentido.eq(s),'km_por_recorrido'].iloc[0]) for s in ['ida','vuelta']}})
    z=programar_circulacion(pd.DataFrame(summaries),pd.DataFrame(),pd.DataFrame(),geo,valores,
        salidas_propuestas=commercial,plan_completo_reservas=True)
    for q in points:
        base=geo.loc[geo.punto.eq(q)&geo.sentido.eq('ida'),'origen'].item()
        if not z['vehiculos'].loc[z['vehiculos'].punto.eq(q),'terminal_inicial'].eq(base).all():
            return {'construccion_completa':False,'motivo':'La ampliación necesita vehículos de acceso iniciados fuera de cabecera.','punto_sin_construccion':q}
    moves=z['movimientos'].assign(tipo_dia=day[0],dias_calendario=1)
    full=objetivos.copy();full['demanda_lanzadera_condicionada_dia']=full.punto.map(target)*capacity
    maxcheck=reasignar_en_horario_conservado(moves,links,full,paradas,capacidad=capacity,margen=margin,espera=wait,estancia=stay)
    checked=reasignar_en_horario_conservado(moves,links,objetivos,paradas,capacidad=capacity,margen=margin,espera=wait,estancia=stay)
    # Actualizar también las columnas informativas heredadas de la cadena semilla.
    fresh=checked['pares'];lookup=moves.set_index('id_salida')
    for i,row in fresh.iterrows():
        fresh.loc[i,'espera_enlace_ida_min']=lookup.loc[row.id_interior_ida,'salida_min']-lookup.loc[row.id_subida,'llegada_min']
        fresh.loc[i,'espera_enlace_regreso_min']=lookup.loc[row.id_regreso,'salida_min']-clock[row.id_interior_regreso,row.parada_entrada]
        fresh.loc[i,'llegada_destino_min']=clock[row.id_interior_ida,row.parada_destino]
        fresh.loc[i,'salida_destino_min']=clock[row.id_interior_regreso,row.parada_destino]
        fresh.loc[i,'ventana_en_destino_min']=fresh.loc[i,'salida_destino_min']-fresh.loc[i,'llegada_destino_min']
    original=commercial.loc[commercial.id_salida.isin(movimientos.id_salida)].set_index('id_salida').salida_min
    old=movimientos.loc[movimientos.componente.eq('comercial')].set_index('id_salida').salida_min
    if not original.sort_index().equals(old.sort_index()):raise ValueError('Se ha movido o perdido una salida anterior.')
    nf=len(z['vehiculos']);reserve=math.ceil(nf*valores['reserva_flota']-1e-10)
    gaps=commercial.loc[commercial.punto.ne('INTERIOR')&commercial.sentido.eq('ida')].groupby('punto').salida_min.apply(lambda s:s.sort_values().diff().min())
    if gaps.lt(interval-1e-8).any():raise ValueError('La construcción incumple el intervalo propuesto.')
    return {**z,'movimientos':moves,'pares':fresh,'salidas':commercial,'cargas_tramos':checked['cargas_tramos'],
        'cargas_maximas':maxcheck['cargas_tramos'],'construccion_completa':True,
        'diagnostico':{'vehiculos_operativos':nf,'vehiculos_reserva':reserve,'vehiculos_totales':nf+reserve,
            'encaje_flota':bool(nf+reserve<=valores['vehiculos_contrato_contraste']),
            'intervalo_minimo_resultante_min':float(gaps.min()),'intervalo_propuesto_min':float(interval),
            'cumple_intervalo_vigente':bool(gaps.ge(valores['intervalo_minimo_subidas_min']-1e-8).all()),
            'salidas_previas_conservadas':True,'minimo_global_demostrado':False,'propuesta_adoptada':False}}
