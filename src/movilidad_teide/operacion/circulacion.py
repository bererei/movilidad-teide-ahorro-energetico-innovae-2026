"""Horarios propuestos y circulación constructiva, distintos de validación real."""
from __future__ import annotations
import math
import re
from zipfile import ZipFile
import numpy as np
import pandas as pd


class ErrorOperacion(ValueError):
    """Entradas incompletas o incompatibles con una propuesta de circulación."""


def referencias_tiempo_gtfs(archivo):
    """Conservar tiempos de seis pares de paradas y cada trip, sin anualizarlo."""
    specs=[('OROTAVA','ida','348','4252','7690'),('OROTAVA','vuelta','348','7690','4254'),
           ('VILAFLOR','ida','342','7675','7682'),('VILAFLOR','vuelta','342','7683','7674'),
           ('INTERIOR','ida','342','7682','7690'),('INTERIOR','vuelta','342','7690','7683')]
    with ZipFile(archivo) as z:
        data={name:pd.read_csv(z.open(name+'.txt'),dtype=str,keep_default_na=False)
              for name in ['routes','trips','stop_times','stops']}
    routes,trips,times,stops=[data[n] for n in ['routes','trips','stop_times','stops']]
    if routes.route_id.duplicated().any() or trips.trip_id.duplicated().any() or stops.stop_id.duplicated().any():
        raise ErrorOperacion('Identificadores GTFS duplicados.')
    selected=routes.loc[routes.route_short_name.isin(['342','348'])]
    trips=trips.loc[trips.route_id.isin(selected.route_id)].merge(selected[['route_id','route_short_name']],on='route_id',validate='many_to_one')
    tt=times.loc[times.trip_id.isin(trips.trip_id)].copy()
    tt['seq']=pd.to_numeric(tt.stop_sequence,errors='raise')
    if tt.duplicated(['trip_id','seq']).any():raise ErrorOperacion('Secuencia GTFS duplicada.')
    names=stops.set_index('stop_id').stop_name.to_dict()
    def sec(s):
        if s=='':return np.nan
        if not re.fullmatch(r'\d{2,}:[0-5]\d:[0-5]\d',s):raise ErrorOperacion('Hora GTFS no válida.')
        h,m,s=map(int,s.split(':'));return h*3600+m*60+s
    rows=[]
    for point,sense,line,a,b in specs:
        found=0
        for trip in trips.loc[trips.route_short_name.eq(line)].itertuples():
            block=tt.loc[tt.trip_id.eq(trip.trip_id)]
            aa,bb=block.loc[block.stop_id.eq(a)],block.loc[block.stop_id.eq(b)]
            if aa.empty or bb.empty:continue
            if len(aa)!=1 or len(bb)!=1:raise ErrorOperacion('Parada repetida: revisar la referencia temporal.')
            aa,bb=aa.iloc[0],bb.iloc[0]
            if aa.seq>=bb.seq:continue
            duration=(sec(bb.arrival_time)-sec(aa.departure_time))/60
            rows.append({'punto':point,'sentido':sense,'linea':line,'trip_id':trip.trip_id,
                'service_id':trip.service_id,'shape_id':trip.shape_id,'stop_id_origen':a,'stop_id_destino':b,
                'origen_publicado':names[a],'destino_publicado':names[b],
                'salida_programada':aa.departure_time,'llegada_programada':bb.arrival_time,
                'duracion_programada_min':duration if np.isfinite(duration) and duration>0 else np.nan,
                'alcance':'Paradas del servicio existente, no nuevas cabeceras; tiempo programado, no observado'})
            found+=1
        if not found:raise ErrorOperacion('Falta referencia GTFS para '+point+'/'+sense)
    return pd.DataFrame(rows)


def proponer_tiempos(longitudes, referencias):
    """Proponer minutos, con transferencia explícita y redondeo de planificación."""
    if longitudes.duplicated(['punto','sentido']).any():raise ErrorOperacion('Longitudes repetidas.')
    valid=referencias.dropna(subset=['duracion_programada_min'])
    stats=valid.groupby(['punto','sentido']).duracion_programada_min.agg(['min','max','size']).reset_index()
    direct=longitudes.merge(stats,on=['punto','sentido'],how='left',validate='one_to_one')
    # Equivalencia de planificación: longitud del estudio / tiempo entre paradas comparables.
    # No es una velocidad medida o una reconstrucción de la distancia del shape GTFS.
    speeds={}
    for sense in ['ida','vuelta']:
        v=direct.loc[direct.sentido.eq(sense)&direct['max'].notna()]
        if len(v)!=3:raise ErrorOperacion('Se necesitan las tres referencias comparables por sentido.')
        equiv=v.longitud_geografica_km*60/v['max']
        speeds[sense]=round(float(equiv.median())/5)*5
        if speeds[sense]<=0:raise ErrorOperacion('Referencia de planificación no positiva.')
    rows=[]
    for row in direct.to_dict('records'):
        observed=np.isfinite(row['max'])
        raw=row['max'] if observed else row['longitud_geografica_km']*60/speeds[row['sentido']]
        rows.append({**row,'tiempo_propuesto_min':int(math.ceil(raw/5)*5),
            'metodo':'Referencia GTFS comparable redondeada a5 min' if observed else 'Proxy de planificación desde tres referencias; otro corredor',
            'velocidad_equivalente_proxy_kmh':np.nan if observed else speeds[row['sentido']],
            'estado':'Hipótesis provisional; sin tiempo observado o validación de futura lanzadera'})
    return pd.DataFrame(rows)


def _clock(minute):
    seconds=int(round(minute*60));return f'{seconds//3600:02d}:{seconds%3600//60:02d}:{seconds%60:02d}'


COLUMNAS_REGRESO = ['punto','sentido_revisado','id_salida_origen','salida_ida_local',
    'llegada_destino_local','estancia_revision_min','margen_enlace_min','id_salida_regreso',
    'salida_regreso_compatible_local','estado','alcance']


def _criterios_regreso(valores):
    stay=valores.get('estancia_min_visita_min')
    margin=valores.get('margen_enlace_interior_min',0)
    for label,value,lower in [('estancia',stay,1),('margen interior',margin,0)]:
        if value is None and label=='estancia':continue
        if value is None or isinstance(value,bool) or not np.isfinite(value) or value<lower:
            raise ErrorOperacion('Criterio no válido: '+label)
    return stay,float(margin)


def revisar_regresos(movimientos,valores):
    """Compartir capacidad por salida, sin convertirla en viajeros observados.

    Interior se revisa en ambos sentidos sobre la oferta inicial. Los refuerzos
    son capacidad de cierre, no otra cohorte que exija una vuelta indefinida.
    Dos guaguas a la misma hora son dos capacidades con IDs distintos.
    """
    stay,margin=_criterios_regreso(valores);rows=[]
    if movimientos.empty:return pd.DataFrame(columns=COLUMNAS_REGRESO)
    for point,block in movimientos.groupby('punto',sort=False):
        for sense in (['ida','vuelta'] if point=='INTERIOR' else ['ida']):
            reverse='vuelta' if sense=='ida' else 'ida'
            outward=block.loc[block.componente.eq('comercial')&block.sentido.eq(sense)].sort_values(['llegada_min','id_salida'])
            back=block.loc[block.componente.str.startswith('comercial')&block.sentido.eq(reverse)].sort_values(['salida_min','id_salida']).to_dict('records')
            for trip in outward.to_dict('records'):
                threshold=trip['llegada_min']+margin if point=='INTERIOR' else (None if stay is None else trip['llegada_min']+stay)
                match=next((j for j,m in enumerate(back) if threshold is not None and m['salida_min']>=threshold-1e-9),None)
                chosen=back.pop(match) if match is not None else None
                state=('Salida de enlace de vuelta bajo cota favorable' if chosen else 'Sin enlace de vuelta con el margen de revisión') if point=='INTERIOR' else ('Sin criterio elegido; no adopta cero' if stay is None else ('Una salida de regreso asignada una sola vez' if chosen else 'Sin regreso compatible bajo la prueba de capacidad por salida'))
                rows.append({'punto':point,'sentido_revisado':sense,'id_salida_origen':trip['id_salida'],
                    'salida_ida_local':trip['salida_local'],'llegada_destino_local':trip['llegada_local'],
                    'estancia_revision_min':None if point=='INTERIOR' else stay,
                    'margen_enlace_min':margin if point=='INTERIOR' else 0,
                    'id_salida_regreso':None if chosen is None else chosen['id_salida'],
                    'salida_regreso_compatible_local':None if chosen is None else chosen['salida_local'],
                    'estado':state,'alcance':'Prueba de oferta a capacidad de diseño por salida, no pasajeros o visitas observadas'})
    return pd.DataFrame(rows,columns=COLUMNAS_REGRESO)


def proponer_refuerzos(movimientos,valores):
    """Añadir solo retornos faltantes, a partir de la misma prueba explícita.

    Mantener salidas iniciales y demanda. Cada guagua extra cubre una capacidad
    equivalente de regreso. Su circulación/vacíos se recalcula después.
    """
    stay,margin=_criterios_regreso(valores)
    if movimientos.id_salida.duplicated().any():raise ErrorOperacion('IDs de circulación repetidos.')
    review=revisar_regresos(movimientos,valores);lookup=movimientos.set_index('id_salida');rows=[]
    for row in review.loc[review.id_salida_regreso.isna()].to_dict('records'):
        if row['punto']!='INTERIOR' and stay is None:continue
        trip=lookup.loc[row['id_salida_origen']]
        departure=float(trip.llegada_min)+(margin if row['punto']=='INTERIOR' else stay)
        reverse='vuelta' if row['sentido_revisado']=='ida' else 'ida'
        rows.append({'punto':row['punto'],'sentido':reverse,'salida_min':departure,
            'salida_local':_clock(departure),'id_salida':f"{row['punto']}_refuerzo_{reverse}_{len(rows):03d}",
            'id_salida_necesidad':row['id_salida_origen'],
            'motivo':'Regreso de oferta inicial; sin nueva demanda de visita ni disponibilidad acreditada'})
    return pd.DataFrame(rows,columns=['punto','sentido','salida_min','salida_local','id_salida','id_salida_necesidad','motivo'])


def revisar_cadenas_interiores(movimientos,valores):
    """Posibilidad temporal individual de un recorrido interior completo y vuelta.

    No reserva plazas entre cadenas ni impone que todos hagan el recorrido
    completo. Espera inmediata usa llegada del acceso, no llegada observada a cola.
    """
    stay,margin=_criterios_regreso(valores);rows=[]
    interior=movimientos.loc[movimientos.punto.eq('INTERIOR')&movimientos.componente.str.startswith('comercial')]
    base=interior.loc[interior.componente.eq('comercial')]
    access=movimientos.loc[movimientos.punto.ne('INTERIOR')&movimientos.componente.eq('comercial')&movimientos.sentido.eq('ida')]
    for trip in access.sort_values(['punto','salida_min','id_salida']).itertuples():
        forwards=base.loc[base.origen.eq(trip.destino)&base.salida_min.ge(trip.llegada_min+margin-1e-9)].sort_values('salida_min')
        chosen=None
        for step in forwards.itertuples():
            backwards=interior.loc[interior.origen.eq(step.destino)&interior.destino.eq(trip.destino)&interior.salida_min.ge(step.llegada_min+margin-1e-9)].sort_values('salida_min')
            for ret in backwards.itertuples():
                if stay is None:continue
                threshold=max(trip.llegada_min+stay,ret.llegada_min+margin)
                exits=movimientos.loc[movimientos.punto.eq(trip.punto)&movimientos.sentido.eq('vuelta')&movimientos.componente.str.startswith('comercial')&movimientos.salida_min.ge(threshold-1e-9)].sort_values('salida_min')
                if not exits.empty:chosen=(step,ret,exits.iloc[0]);break
            if chosen is not None:break
        first=None if forwards.empty else forwards.iloc[0]
        rows.append({'punto':trip.punto,'id_salida_acceso':trip.id_salida,'salida_acceso_local':trip.salida_local,
            'llegada_parque_local':trip.llegada_local,'terminal_parque':trip.destino,
            'primera_salida_interior_posible':None if first is None else first.salida_local,
            'espera_enlace_inmediato_min':None if first is None else float(first.salida_min-trip.llegada_min),
            'id_interior_ida':None if chosen is None else chosen[0].id_salida,
            'id_interior_regreso':None if chosen is None else chosen[1].id_salida,
            'id_regreso_acceso':None if chosen is None else chosen[2].id_salida,
            'salida_regreso_acceso_local':None if chosen is None else chosen[2].salida_local,
            'estado':'Cadena temporal disponible; plazas no reservadas' if chosen else ('Sin salida interior inicial posterior a la llegada' if first is None else ('Sin criterio de estancia para revisar' if stay is None else 'Sin cadena completa bajo los criterios')),
            'alcance':'Prueba individual terminal a terminal; no obligación de visita, capacidad conjunta o espera observada'})
    return pd.DataFrame(rows)


def coordinar_horarios(movimientos,valores,frecuencia_interior):
    """Proponer cierres escalonados con un máximo común y oferta trazable.

    El máximo no es una hora obligatoria. No se mueve la demanda del Visor
    ni se acredita aceptación de reservas en otras franjas.
    """
    stay,margin=_criterios_regreso(valores)
    limit=valores.get('hora_limite_bajada_parque')
    if limit is None or isinstance(limit,bool) or not np.isfinite(limit) or not 0<limit<=24:
        raise ErrorOperacion('Falta un límite válido de última bajada desde el Parque.')
    if stay is None:raise ErrorOperacion('Necesito una referencia de visita explícita para coordinar horarios.')
    gap=valores.get('intervalo_minimo_subidas_min',30.)
    if gap is None or isinstance(gap,bool) or not np.isfinite(gap) or gap<=0:
        raise ErrorOperacion('Falta un intervalo mínimo válido entre salidas de acceso.')
    if isinstance(frecuencia_interior,bool) or not np.isfinite(frecuencia_interior) or frecuencia_interior<=0 or frecuencia_interior!=int(frecuencia_interior):
        raise ErrorOperacion('Frecuencia interior no válida para coordinar servicio.')
    if movimientos.id_salida.duplicated().any():raise ErrorOperacion('Salidas de referencia repetidas.')
    base=movimientos.loc[movimientos.componente.eq('comercial')].copy()
    inner=base.loc[base.punto.eq('INTERIOR')];access=base.loc[base.punto.ne('INTERIOR')]
    times=inner.groupby('sentido').tiempo_recorrido_min.first()
    if set(times.index)!={'ida','vuelta'} or access.empty:raise ErrorOperacion('Faltan servicios para coordinar.')
    for _,b in inner.groupby('sentido'):
        if b.tiempo_recorrido_min.nunique()!=1:raise ErrorOperacion('Tiempo interior contradictorio.')
    end=float(limit)*60;interval=60/int(frecuencia_interior);grid=float(gap)/2
    # Referencia de llegada: cierre máximo + regreso más corto. Es planificación,
    # no una hora obligatoria de llegada. Redondear hacia antes, sin alargar servicio.
    return_times=access.loc[access.sentido.eq('vuelta')].groupby('punto').tiempo_recorrido_min.first()
    arrival_reference=end+float(return_times.min())
    deadlines={}
    for point,b in access.groupby('punto',sort=False):
        published_last=float(b.loc[b.sentido.eq('vuelta'),'salida_min'].max())
        proposed=math.floor((arrival_reference-float(return_times[point]))/grid+1e-9)*grid
        deadlines[point]=min(end,published_last,proposed)
    terminal_deadlines={}
    for point,b in access.groupby('punto',sort=False):
        terminal=b.loc[b.sentido.eq('ida'),'destino'].iloc[0]
        terminal_deadlines[terminal]=max(terminal_deadlines.get(terminal,-np.inf),deadlines[point])
    phase=(end-float(times.sum())-2*margin)%interval
    earliest_ready=float(access.loc[access.sentido.eq('ida'),'llegada_min'].min())+margin
    first=phase+math.ceil((earliest_ready-phase)/interval-1e-9)*interval
    inner_rows=[];inner_limits=[]
    for sense,b in inner.groupby('sentido',sort=False):
        sample=b.iloc[0];origin=sample.origen
        if origin not in terminal_deadlines:raise ErrorOperacion('Terminal interior sin regreso de acceso.')
        latest=terminal_deadlines[origin]-float(times.sum())-2*margin
        last=phase+math.floor((latest-phase)/interval+1e-9)*interval
        count=int(round((last-first)/interval))+1
        if count<=0:raise ErrorOperacion('El cierre no permite un recorrido interior completo.')
        for i in range(count):
            dep=first+i*interval
            inner_rows.append({**sample.to_dict(),'id_salida':f'INTERIOR_coordinada_{sense}_{i:03d}',
                'salida_min':dep,'llegada_min':dep+float(times[sense]),
                'salida_local':_clock(dep),'llegada_local':_clock(dep+float(times[sense]))})
        inner_limits.append({'punto':'INTERIOR','sentido':sense,'origen':origin,'destino':sample.destino,
            'primera_salida_visita_min':first,'ultima_salida_visita_min':last,
            'primera_salida_visita_local':_clock(first),'ultima_salida_visita_local':_clock(last),
            'intervalo_min':interval,'salidas_visita_por_sentido':count,
            'estado':'Oferta coordinada propuesta; no demanda nueva ni servicio observado'})
    inner_base=pd.DataFrame(inner_rows)
    closure=proponer_refuerzos(inner_base,valores)
    # Incluir los regresos de cierre para derivar el último acceso posible por corredor.
    inner_pool=inner_base.to_dict('records')
    for extra in closure.to_dict('records'):
        sample=inner_base.loc[inner_base.sentido.eq(extra['sentido'])].iloc[0]
        inner_pool.append({**sample.to_dict(),**extra,'llegada_min':extra['salida_min']+float(times[extra['sentido']])})
    pool=pd.DataFrame(inner_pool);rows=[];ledger=[];limits=[];access_extras=[]
    wait=valores.get('espera_max_lanzadera_min')
    if wait is not None and (isinstance(wait,bool) or not np.isfinite(wait) or wait<margin):
        raise ErrorOperacion('La referencia de espera no permite el margen de enlace elegido.')
    def spread(block,cutoff,point):
        b=block.sort_values(['salida_min','id_salida']);original=b.salida_min.to_numpy(dtype=float)
        planned=original.copy()
        if len(planned):
            planned[-1]=min(planned[-1],cutoff)
            for i in range(len(planned)-2,-1,-1):planned[i]=min(planned[i],planned[i+1]-gap)
        # Alinear subidas y espaciarlas de nuevo hasta estabilizar; nunca ocultar
        # una propuesta imposible adelantando la apertura sin declararlo.
        for _ in range(max(1,4*len(planned))):
            before=planned.copy()
            if len(planned) and b.iloc[0].sentido=='ida' and wait is not None:
                forwards=inner_base.loc[inner_base.origen.eq(b.iloc[0].destino)].sort_values('salida_min')
                for i,row in enumerate(b.itertuples()):
                    arrival=planned[i]+float(row.tiempo_recorrido_min)
                    nxt=forwards.loc[forwards.salida_min.ge(arrival+margin-1e-9)]
                    if nxt.empty:raise ErrorOperacion('Una subida no encuentra salida interior inicial.')
                    dep=float(nxt.iloc[0].salida_min)
                    if dep-arrival>wait+1e-9:planned[i]=dep-interval-margin-float(row.tiempo_recorrido_min)
            for i in range(len(planned)-2,-1,-1):planned[i]=min(planned[i],planned[i+1]-gap)
            if len(planned) and planned[0]<original[0]-1e-9:
                raise ErrorOperacion('No cabe la oferta con el cierre e intervalo elegidos; revisar criterios.')
            if np.allclose(planned,before,atol=1e-9,rtol=0):break
        else:raise ErrorOperacion('No se estabiliza la coordinación de intervalos y enlaces.')
        for row,dep in zip(b.to_dict('records'),planned):
            rows.append({'punto':point,'sentido':row['sentido'],'salida_min':float(dep),'id_salida':row['id_salida']})
            ledger.append({'punto':point,'sentido':row['sentido'],'id_salida':row['id_salida'],
                'salida_referencia_local':row['salida_local'],'salida_propuesta_local':_clock(dep),
                'salida_referencia_min':row['salida_min'],'salida_propuesta_min':float(dep),
                'adelanto_min':float(row['salida_min']-dep),'requiere_reorganizar_oferta':abs(row['salida_min']-dep)>1e-9,
                'estado':'Propuesta previa a reservas; demanda original conservada, aceptación de cambio de franja sin medir'})
    for point,b in access.groupby('punto',sort=False):
        sample=b.loc[b.sentido.eq('ida')].iloc[0];terminal=sample.destino;deadline=deadlines[point]
        possible=[]
        for trip in inner_base.loc[inner_base.origen.eq(terminal)].itertuples():
            reverse=pool.loc[pool.origen.eq(trip.destino)&pool.destino.eq(terminal)&pool.salida_min.ge(trip.llegada_min+margin-1e-9)]
            if (reverse.llegada_min+margin).le(deadline+1e-9).any():possible.append(trip.salida_min)
        if not possible:raise ErrorOperacion('No hay cadena interior con el último regreso de '+point)
        arrival_cut=min(deadline-stay,max(possible)-margin)
        cutoff=arrival_cut-float(sample.tiempo_recorrido_min)
        spread(b.loc[b.sentido.eq('ida')],cutoff,point)
        # Planificar regresos de las subidas ya ajustadas, con oportunidad de visita
        # y un recorrido interior posible. No amontonar la antigua cola de bajadas.
        trips=[x for x in rows if x['punto']==point and x['sentido']=='ida']
        return_slots=[]
        for trip in sorted(trips,key=lambda x:(x['salida_min'],x['id_salida'])):
            arrival=trip['salida_min']+float(sample.tiempo_recorrido_min)
            feasible=[]
            for leg in inner_base.loc[inner_base.origen.eq(terminal)&inner_base.salida_min.ge(arrival+margin-1e-9)].itertuples():
                rr=pool.loc[pool.origen.eq(leg.destino)&pool.destino.eq(terminal)&pool.salida_min.ge(leg.llegada_min+margin-1e-9)]
                if not rr.empty:feasible.append(float(rr.llegada_min.min())+margin)
            if not feasible:raise ErrorOperacion('No hay cadena para planificar el regreso de '+point)
            earliest=max(arrival+stay,min(feasible))
            dep=math.ceil((earliest-1e-9)/grid)*grid
            if dep>deadline+1e-9:raise ErrorOperacion('El regreso práctico supera el cierre del corredor.')
            return_slots.append((dep,trip['id_salida']))
        originals=b.loc[b.sentido.eq('vuelta')].sort_values(['salida_min','id_salida'])
        while len(return_slots)<len(originals):
            # Conservar capacidad publicada adicional sin atribuirle visitantes nuevos.
            candidate=deadline
            if any(abs(x[0]-candidate)<=1e-9 for x in return_slots):
                candidate=next((deadline-grid*k for k in range(1,100) if not any(abs(x[0]-(deadline-grid*k))<=1e-9 for x in return_slots)),deadline)
            return_slots.append((candidate,None))
        return_slots.sort(key=lambda x:x[0])
        for i,(dep,need) in enumerate(return_slots):
            if i<len(originals):
                row=originals.iloc[i]
                rows.append({'punto':point,'sentido':'vuelta','salida_min':dep,'id_salida':row.id_salida})
                ledger.append({'punto':point,'sentido':'vuelta','id_salida':row.id_salida,
                    'salida_referencia_local':row.salida_local,'salida_propuesta_local':_clock(dep),
                    'salida_referencia_min':row.salida_min,'salida_propuesta_min':dep,
                    'adelanto_min':row.salida_min-dep,'requiere_reorganizar_oferta':abs(row.salida_min-dep)>1e-9,
                    'estado':'Regreso propuesto según visita y enlaces; referencia original conservada, sin viajeros observados'})
            else:
                access_extras.append({'punto':point,'sentido':'vuelta','salida_min':dep,'salida_local':_clock(dep),
                    'id_salida':f'{point}_refuerzo_vuelta_{i:03d}','id_salida_necesidad':need,
                    'motivo':'Capacidad de regreso para oferta inicial, con enlace interior y sin nueva visita'})
        limits.append({'punto':point,'limite_subida_calculado_min':cutoff,
            'limite_subida_calculado_local':_clock(cutoff),'ultima_bajada_parque_min':deadline,
            'ultima_bajada_parque_local':_clock(deadline),
            'llegada_ultima_cabecera_local':_clock(deadline+float(return_times[point])),
            'maximo_comun_bajada_min':end,'referencia_llegada_cabeceras_min':arrival_reference,
            'paso_redondeo_min':grid,'intervalo_minimo_acceso_min':gap,
            'criterio':'Máximo común, cierres por corredor y cadena interior; no horas obligatorias iguales'})
    rows.extend({k:x[k] for k in ['punto','sentido','salida_min','id_salida']} for x in inner_rows)
    return {'salidas':pd.DataFrame(rows),'ajustes_acceso':pd.DataFrame(ledger),
        'limites_acceso':pd.DataFrame(limits),'interior':inner_limits,
        'refuerzos':pd.concat([pd.DataFrame(access_extras,columns=closure.columns),closure],ignore_index=True)}


def _cadenas_vehiculos(comerciales,duraciones,distancias,regulacion,vehiculos_objetivo=None):
    """Mínimo de cadenas para este horario, con menor enlace vacío entre ellas.

    Una cantidad objetivo opcional permite contrastar más flota y menos vacío.
    Emparejamiento bipartito de viajes compatibles: cada enlace sustituye
    un vehículo inicial. El coste usa kilómetros vacíos, no pasajeros.
    No incluye turnos de conductor, cocheras o intercambio entre servicios.
    """
    n=len(comerciales)
    if not n:return []
    if vehiculos_objetivo is not None and (
            isinstance(vehiculos_objetivo,(bool,np.bool_))
            or not isinstance(vehiculos_objetivo,(int,np.integer))
            or not 1<=vehiculos_objetivo<=n):
        raise ErrorOperacion('Cantidad objetivo de vehículos no válida.')
    enlaces_objetivo=n if vehiculos_objetivo is None else n-int(vehiculos_objetivo)
    enlaces=0
    source=2*n;sink=source+1;graph=[[] for _ in range(2*n+2)];links={}
    def edge(a,b,cost):
        forward=[b,len(graph[b]),1,float(cost)]
        backward=[a,len(graph[a]),0,-float(cost)]
        graph[a].append(forward);graph[b].append(backward);return forward
    for i in range(n):edge(source,i,0);edge(n+i,sink,0)
    for i,a in enumerate(comerciales):
        arrival=a['salida_min']+duraciones[a['sentido']]
        for j,b in enumerate(comerciales):
            if i==j:continue
            empty=a['sentido']==b['sentido']
            reverse='vuelta' if a['sentido']=='ida' else 'ida'
            required=arrival+regulacion+(duraciones[reverse]+regulacion if empty else 0)
            if required<=b['salida_min']+1e-9:
                links[i,j]=edge(i,n+j,distancias[reverse] if empty else 0)
    # Aumentar el número de enlaces hasta el máximo. Los arcos inversos permiten
    # revisar asignaciones previas en lugar de añadir guaguas por una decisión voraz.
    while enlaces<enlaces_objetivo:
        cost=[float('inf')]*len(graph);parent=[None]*len(graph);cost[source]=0.
        for _ in range(len(graph)-1):
            changed=False
            for a,edges in enumerate(graph):
                if not np.isfinite(cost[a]):continue
                for k,e in enumerate(edges):
                    if e[2] and cost[a]+e[3]<cost[e[0]]-1e-9:
                        cost[e[0]]=cost[a]+e[3];parent[e[0]]=(a,k);changed=True
            if not changed:break
        if parent[sink] is None:break
        enlaces+=1
        pos=sink
        while pos!=source:
            a,k=parent[pos];e=graph[a][k];e[2]-=1;graph[pos][e[1]][2]+=1;pos=a
    following={i:j for (i,j),e in links.items() if e[2]==0};starts=[i for i in range(n) if i not in set(following.values())]
    chains=[]
    for start in starts:
        chain=[start]
        while chain[-1] in following:chain.append(following[chain[-1]])
        chains.append(chain)
    if sorted(i for chain in chains for i in chain)!=list(range(n)):
        raise ErrorOperacion('La asignación no conserva todos los viajes comerciales.')
    if vehiculos_objetivo is not None and len(chains)!=vehiculos_objetivo:
        raise ErrorOperacion('No se construye el horario con esa cantidad de vehículos.')
    return chains


def programar_circulacion(resumen, horaria, salidas_interior, longitudes, valores, refuerzos=None, salidas_propuestas=None, plan_completo_reservas=False, vehiculos_por_servicio=None):
    """Asignar vehículos y vacíos con flota mínima para el horario y enlaces permitidos.

    Se dispone inicialmente de los vehículos en el terminal de su primera salida;
    cocheras siguen aparte. Cada vehículo queda regulado después de cada recorrido.
    El cierre conserva el número de guaguas por terminal, no la identidad de cada una.
    """
    if plan_completo_reservas and (salidas_propuestas is None or refuerzos is not None):
        raise ErrorOperacion('El plan completo de reservas requiere todas sus salidas y ningún refuerzo duplicado.')
    if resumen.punto.duplicated().any() or longitudes.duplicated(['punto','sentido']).any():
        raise ErrorOperacion('Servicios o sentidos repetidos.')
    def num(k,lower=0):
        v=valores.get(k)
        if v is None or isinstance(v,bool) or not np.isfinite(v) or v<lower:raise ErrorOperacion('Falta valor válido para '+k)
        return float(v)
    regulation=num('regulacion_min')
    if vehiculos_por_servicio is not None and (
            not isinstance(vehiculos_por_servicio,dict)
            or set(vehiculos_por_servicio)-set(resumen.punto)):
        raise ErrorOperacion('Asignación de vehículos con servicios ajenos.')
    for c in ['salidas_ida_dia','salidas_vuelta_dia']:
        v=pd.to_numeric(resumen[c],errors='coerce')
        if not np.isfinite(v).all() or v.lt(0).any() or v.mod(1).ne(0).any():raise ErrorOperacion('Totales comerciales no enteros o válidos.')
    if salidas_propuestas is not None:
        if not {'punto','sentido','salida_min','id_salida'}<=set(salidas_propuestas):raise ErrorOperacion('Horario propuesto incompleto.')
        if salidas_propuestas.id_salida.duplicated().any():raise ErrorOperacion('ID de horario propuesto repetido.')
        if not set(salidas_propuestas.punto)<=set(resumen.punto) or not set(salidas_propuestas.sentido)<={'ida','vuelta'}:
            raise ErrorOperacion('Servicio o sentido ajeno en horario propuesto.')
        dep=pd.to_numeric(salidas_propuestas.salida_min,errors='coerce')
        if not np.isfinite(dep).all() or dep.lt(0).any():raise ErrorOperacion('Minutos del horario propuesto no válidos.')
    outputs=[];fleets=[];returns=[]
    for summary in resumen.to_dict('records'):
        point=summary['punto'];geo=longitudes.loc[longitudes.punto.eq(point)].set_index('sentido')
        if set(geo.index)!={'ida','vuelta'}:raise ErrorOperacion('Faltan los sentidos físicos de '+point)
        durations={s:num(('min_vuelta_interior' if s=='ida' else 'min_ida_interior') if point=='INTERIOR' else f'tiempo_{s}_{point}_min',.000001) for s in ['ida','vuelta']}
        distances={s:float(summary[f'longitud_{s}_km']) for s in ['ida','vuelta']}
        if not all(np.isfinite(v) and v>0 for v in distances.values()):raise ErrorOperacion('Longitud no válida.')
        commercial=[]
        for sense in ['ida','vuelta']:
            if plan_completo_reservas:
                departures=[]
            elif point=='INTERIOR':
                departures=salidas_interior.loc[salidas_interior.sentido.eq(sense),'minuto_salida_local'].tolist()
            elif valores.get('origen_oferta')=='Simulador de captación':
                h=horaria.loc[horaria.punto.eq(point)&horaria.direccion.eq('subida' if sense=='ida' else 'bajada')]
                if h.empty or h.hora_servicio.duplicated().any():raise ErrorOperacion('Perfil horario incompleto o repetido.')
                departures=[]
                for row in h.itertuples():
                    count=float(row.expediciones)
                    if not np.isfinite(count) or count<0 or count!=int(count):raise ErrorOperacion('Salidas horarias no enteras.')
                    departures.extend([60*int(row.hora_servicio)+60*k/int(count) for k in range(int(count))])
            else:
                count=int(summary[f'salidas_{sense}_dia']);start=num('hora_inicio_acceso')*60;end=(num('hora_fin_acceso')+1)*60
                departures=[start+(end-start)*k/count for k in range(count)]
            if not all(np.isfinite(v) and v>=0 for v in departures):raise ErrorOperacion('Salida no finita o negativa.')
            if not plan_completo_reservas and len(departures)!=int(summary[f'salidas_{sense}_dia']):raise ErrorOperacion('Las salidas no conservan el total elegido.')
            for i,dep in enumerate(departures):commercial.append({'sentido':sense,'salida_min':float(dep),
                'id_salida':f'{point}_base_{sense}_{i:03d}','componente':'comercial'})
        if salidas_propuestas is not None:
            selected=salidas_propuestas.loc[salidas_propuestas.punto.eq(point)]
            if plan_completo_reservas and set(selected.sentido)!={'ida','vuelta'}:
                raise ErrorOperacion('El plan completo debe identificar ambos sentidos de cada servicio.')
            # Los accesos conservan cada capacidad inicial; el interior puede ampliar su cobertura.
            original_ids={x['id_salida'] for x in commercial}
            if not plan_completo_reservas and point!='INTERIOR' and set(selected.id_salida)!=original_ids:
                raise ErrorOperacion('El horario coordinado pierde o añade capacidades de acceso.')
            commercial=[{**x,'componente':'comercial'} for x in selected.to_dict('records')]
        # Los refuerzos cierran viajes existentes; no crean otra cohorte de visita.
        if refuerzos is not None:
            required={'punto','sentido','salida_min','id_salida'}
            if not required<=set(refuerzos):raise ErrorOperacion('Refuerzos sin identificación completa.')
            if refuerzos.id_salida.duplicated().any():raise ErrorOperacion('Identificadores de refuerzo repetidos.')
            if not set(refuerzos.punto)<=set(resumen.punto):raise ErrorOperacion('Refuerzo de servicio ajeno.')
            for trip in refuerzos.loc[refuerzos.punto.eq(point)].to_dict('records'):
                dep=trip['salida_min']
                if trip['sentido'] not in durations or isinstance(dep,bool) or not np.isfinite(dep) or dep<0:
                    raise ErrorOperacion('Salida o sentido de refuerzo no válido.')
                commercial.append({**trip,'componente':'comercial_refuerzo_regreso'})
        if valores.get('tratamiento_regresos')=='Horario coordinado':
            cap=valores.get('hora_limite_bajada_parque')
            if cap is None:raise ErrorOperacion('Falta elegir la última bajada del Parque.')
            if any(x['salida_min']>float(cap)*60+1e-9 for x in commercial if point=='INTERIOR' or x['sentido']=='vuelta'):
                raise ErrorOperacion('Una salida comercial supera el cierre elegido.')
        if len({x['id_salida'] for x in commercial})!=len(commercial):raise ErrorOperacion('Salida comercial repetida.')
        commercial.sort(key=lambda x:(x['salida_min'],x['sentido'],x['id_salida']))
        buses=[];moves=[]
        def add(bus,sense,dep,component,departure_id=None):
            origin='A' if sense=='ida' else 'B';dest='B' if sense=='ida' else 'A'
            if bus['position']!=origin or bus['ready']>dep+1e-9:raise ErrorOperacion('Vehículo no disponible en origen.')
            arr=dep+durations[sense]
            moves.append({'punto':point,'vehiculo_id':bus['id'],'id_salida':departure_id or f'{point}_vacio_{len(moves):03d}',
                'componente':component,'sentido':sense,
                'origen':geo.loc[sense,'origen'],'destino':geo.loc[sense,'destino'],
                'itinerary_id':geo.loc[sense,'itinerary_id'] if valores['distancias_actividad_lanzaderas']=='Recorridos del estudio' else None,
                'salida_min':dep,'llegada_min':arr,'salida_local':_clock(dep),'llegada_local':_clock(arr),
                'tiempo_recorrido_min':durations[sense],'km_por_recorrido':distances[sense],
                'alcance':'Propuesta condicionada a tiempos y vehículos disponibles; no horario aprobado'})
            bus['position']=dest;bus['ready']=arr+regulation
        for chain in _cadenas_vehiculos(commercial,durations,distances,regulation,
                None if vehiculos_por_servicio is None else vehiculos_por_servicio.get(point)):
            first=commercial[chain[0]];origin='A' if first['sentido']=='ida' else 'B'
            bus={'id':point+'_'+str(len(buses)+1).zfill(2),'initial':origin,'position':origin,'ready':first['salida_min']}
            buses.append(bus)
            for index in chain:
                trip=commercial[index];sense=trip['sentido'];dep=trip['salida_min'];origin='A' if sense=='ida' else 'B'
                if bus['position']!=origin:
                    reverse='vuelta' if sense=='ida' else 'ida'
                    add(bus,reverse,dep-durations[reverse]-regulation,'reposicion_por_horario')
                add(bus,sense,dep,trip['componente'],trip['id_salida'])
        difference=sum(b['position']=='A' for b in buses)-sum(b['initial']=='A' for b in buses)
        for _ in range(abs(difference)):
            sense='ida' if difference>0 else 'vuelta';origin='A' if sense=='ida' else 'B'
            bus=min((b for b in buses if b['position']==origin),key=lambda b:(b['ready'],b['id']))
            add(bus,sense,bus['ready'],'reposicion_cierre_diario')
        if sum(b['position']=='A' for b in buses)!=sum(b['initial']=='A' for b in buses):raise ErrorOperacion('El servicio no cierra su distribución diaria.')
        for bus in buses:
            mm=[m for m in moves if m['vehiculo_id']==bus['id']]
            fleets.append({'punto':point,'vehiculo_id':bus['id'],'terminal_inicial':geo.loc['ida' if bus['initial']=='A' else 'vuelta','origen'],
                'primera_salida_local':_clock(min(m['salida_min'] for m in mm)),
                'ultima_llegada_local':_clock(max(m['llegada_min'] for m in mm)),
                'recorridos_comerciales':sum(m['componente'].startswith('comercial') for m in mm),
                'recorridos_vacios':sum(not m['componente'].startswith('comercial') for m in mm),
                'kilometros_dia':sum(m['km_por_recorrido'] for m in mm),
                'amplitud_vehiculo_min':max(m['llegada_min'] for m in mm)-min(m['salida_min'] for m in mm),
                'tiempo_recorridos_min':sum(m['tiempo_recorrido_min'] for m in mm),
                'alcance':('Cantidad de vehículos ensayada para el horario; no disponibilidad, cocheras o turno de conductor' if vehiculos_por_servicio is not None and point in vehiculos_por_servicio else 'Mínimo de vehículos para este horario y enlaces permitidos; no disponibilidad, cocheras o turno de conductor')})
        returns.extend(revisar_regresos(pd.DataFrame(moves),valores).to_dict('records'))
        outputs.extend(sorted(moves,key=lambda x:(x['salida_min'],x['id_salida'])))
    return {'movimientos':pd.DataFrame(outputs,columns=['punto','vehiculo_id','id_salida','componente','sentido','origen','destino','itinerary_id','salida_min','llegada_min','salida_local','llegada_local','tiempo_recorrido_min','km_por_recorrido','alcance']),
            'vehiculos':pd.DataFrame(fleets,columns=['punto','vehiculo_id','terminal_inicial','primera_salida_local','ultima_llegada_local','recorridos_comerciales','recorridos_vacios','kilometros_dia','amplitud_vehiculo_min','tiempo_recorridos_min','alcance']),
            'regresos':pd.DataFrame(returns,columns=COLUMNAS_REGRESO),
            'salidas_planificadas':None if salidas_propuestas is None else salidas_propuestas.copy()}


def incorporar_circulacion(actividad, programacion):
    """Sumar vacíos de la propuesta, manteniendo aparte cocheras y otros desconocidos."""
    original=actividad['resumen'];moves=programacion['movimientos'];rows=[];summaries=[]
    for row in original.to_dict('records'):
        point=row['punto'];block=moves.loc[moves.punto.eq(point)]
        known=[]
        for (component,sense),b in block.groupby(['componente','sentido'],sort=True):
            if b.km_por_recorrido.nunique()!=1:raise ErrorOperacion('Un mismo sentido usa longitudes contradictorias.')
            first=b.iloc[0];count=len(b);km=float(b.km_por_recorrido.sum());days=int(row['dias_operacion'])
            known.append({'punto':point,'componente':component,'sentido':sense,'origen':first.origen,'destino':first.destino,
                'itinerary_id':first.itinerary_id,'recorridos_dia':count,'km_por_recorrido':first.km_por_recorrido,
                'vehiculo_km_dia':km,'dias_operacion':days,'recorridos_anio':count*days,'vehiculo_km_anio':km*days,
                'base_distancias':row['base_distancias'],'estado':'Propuesta con tiempos elegidos; cocheras y otros vacíos pendientes'})
        # Conservar oferta de origen y distinguir cada refuerzo, sin contarlo como vacío.
        for sense in ['ida','vuelta']:
            base=block.loc[block.componente.eq('comercial')&block.sentido.eq(sense)]
            planned=programacion.get('salidas_planificadas')
            if planned is None:
                if len(base)!=row[f'salidas_{sense}_dia']:raise ErrorOperacion('La circulación altera la oferta base.')
            elif set(base.id_salida)!=set(planned.loc[planned.punto.eq(point)&planned.sentido.eq(sense),'id_salida']):
                raise ErrorOperacion('La circulación no coincide con la propuesta de horarios.')
            row[f'salidas_referencia_{sense}_dia']=row[f'salidas_{sense}_dia']
            row[f'salidas_base_{sense}_dia']=len(base)
            row[f'refuerzos_regreso_{sense}_dia']=int((block.componente.eq('comercial_refuerzo_regreso')&block.sentido.eq(sense)).sum())
            row[f'salidas_{sense}_dia']=int((block.componente.str.startswith('comercial')&block.sentido.eq(sense)).sum())
            row[f'reposicion_modelada_{sense}_dia']=int((~block.componente.str.startswith('comercial')&block.sentido.eq(sense)).sum())
        if row['salidas_ida_dia']+row['reposicion_modelada_ida_dia']!=row['salidas_vuelta_dia']+row['reposicion_modelada_vuelta_dia']:
            raise ErrorOperacion('Los movimientos de circulación no cierran el servicio.')
        row['km_comerciales_base_dia']=float(block.loc[block.componente.eq('comercial'),'km_por_recorrido'].sum())
        row['km_comerciales_dia']=float(block.loc[block.componente.str.startswith('comercial'),'km_por_recorrido'].sum())
        row['vehiculo_km_cierre_minimo_dia']=row['vehiculo_km_identificados_dia']
        row['km_vacios_modelados_dia']=float(block.loc[~block.componente.str.startswith('comercial'),'km_por_recorrido'].sum())
        row['vehiculo_km_identificados_dia']=float(block.km_por_recorrido.sum())
        row['vehiculo_km_identificados_anio']=row['vehiculo_km_identificados_dia']*row['dias_operacion']
        durations=block.groupby('sentido').tiempo_recorrido_min.first()
        row['tiempo_ida_propuesto_min']=durations.get('ida',np.nan)
        row['tiempo_vuelta_propuesto_min']=durations.get('vuelta',np.nan)
        row['flota_propuesta_constructiva']=int(programacion['vehiculos'].loc[lambda t:t.punto.eq(point)].vehiculo_id.nunique())
        summaries.append(row);rows.extend(known)
        unknown=actividad['movimientos'].loc[lambda t:t.punto.eq(point)&t.sentido.eq('pendiente')].copy()
        unknown['componente']=unknown.componente.replace({'vacios_adicionales_por_horario':'otros_vacios_no_modelizados'})
        rows.extend(unknown.to_dict('records'))
    return {**actividad,'movimientos':pd.DataFrame(rows),'resumen':pd.DataFrame(summaries)}
