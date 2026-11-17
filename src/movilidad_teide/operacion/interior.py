"""Capacidad compartida y cadenas de visita del interior del Parque.

Prueba explícita de dos recorridos interiores completos por visita. No estima
su utilización real. La asignación es constructiva y no garantiza el óptimo.
"""
import numpy as np
import pandas as pd


def _numero(valor,nombre,positivo=False):
    if isinstance(valor,bool) or not np.isfinite(valor) or valor<0 or (positivo and valor==0):
        raise ValueError('Valor no válido: '+nombre)
    return float(valor)


def cotas_capacidad_interior(objetivos,movimientos,*,capacidad,ocupacion_coche):
    """Cotas para una visita que consume una plaza de cada sentido interior.

    Las personas de los coches autorizados son población potencial condicionada,
    no demanda observada del interior. Otros modos conservan demanda desconocida.
    """
    cap=_numero(capacidad,'capacidad',True);ocup=_numero(ocupacion_coche,'ocupación',True)
    if objetivos.duplicated(['tipo_dia','corredor']).any():raise ValueError('Objetivos repetidos.')
    rows=[]
    for tipo,block in objetivos.groupby('tipo_dia',sort=True):
        x=movimientos.loc[movimientos.tipo_dia.eq(tipo)&movimientos.punto.eq('INTERIOR')&
            movimientos.componente.str.startswith('comercial')]
        if x.empty or x.id_salida.duplicated().any() or not set(x.sentido)<={'ida','vuelta'}:
            raise ValueError('Oferta interior ausente o duplicada.')
        if block.dias_calendario.nunique()!=1:raise ValueError('Calendario incoherente.')
        counts=x.groupby('sentido').size().to_dict()
        ida=counts.get('ida',0)*cap;vuelta=counts.get('vuelta',0)*cap;limit=min(ida,vuelta)
        demand=float(block.demanda_lanzadera_condicionada_dia.sum())
        private=float(block.coches_autorizados_condicionados_dia.sum())*ocup
        days=int(block.dias_calendario.iloc[0])
        rows.append({'tipo_dia':tipo,'dias_calendario':days,'salidas_interior_ida':counts.get('ida',0),
            'salidas_interior_vuelta':counts.get('vuelta',0),'plazas_trayecto_ida_dia':ida,
            'plazas_trayecto_vuelta_dia':vuelta,'plazas_trayecto_totales_dia':ida+vuelta,
            'cota_visitas_dos_trayectos_dia':limit,'demanda_accesos_condicionada_dia':demand,
            'personas_coches_autorizados_potenciales_dia':private,
            'fraccion_maxima_solo_por_capacidad_accesos':min(1.,limit/demand) if demand>0 else np.nan,
            'fraccion_maxima_pool_accesos_y_coches':min(1.,limit/(demand+private)) if demand+private>0 else np.nan,
            'deficit_minimo_si_todos_accesos_dos_trayectos_dia':max(0.,demand-limit),
            'recorridos_minimos_por_sentido_si_todos_accesos':int(np.ceil(demand/cap)),
            'demanda_real_interior_dia':np.nan,'demanda_otros_modos_interior_dia':np.nan,
            'alcance':'Cota de dos recorridos completos por visita; no demanda prevista, horarios o utilización real'})
    return pd.DataFrame(rows)


def coordinar_visitas_completas(objetivos,movimientos,pares,*,capacidad,margen,estancia,espera_max=None,mantener_pares=True):
    """Construir asignaciones con plaza de acceso, interior ida/vuelta y regreso.

    Mantener pares contrasta billetes D157. Recoordinar permite otra bajada del
    mismo corredor, compartiendo todas las capacidades. Las dos variantes son
    pruebas de planificación; no se venden nuevas visitas ni se cambia oferta.
    La espera máxima incluye el margen en los dos enlaces acceso/interior.
    """
    cap=_numero(capacidad,'capacidad',True);margin=_numero(margen,'margen');stay=_numero(estancia,'estancia',True)
    if espera_max is not None:
        wait=_numero(espera_max,'espera')
        if wait<margin:raise ValueError('La espera total no puede ser menor que el margen de enlace.')
    else:wait=None
    keys=['punto','corredor'];needed=keys+['demanda_lanzadera_condicionada_dia']
    if not set(needed)<=set(objetivos) or objetivos.punto.duplicated().any():raise ValueError('Objetivos incompletos o repetidos.')
    if not np.isfinite(objetivos.demanda_lanzadera_condicionada_dia).all() or (objetivos.demanda_lanzadera_condicionada_dia<0).any():raise ValueError('Demanda inválida.')
    m=movimientos.loc[movimientos.componente.str.startswith('comercial')].copy()
    if m.id_salida.duplicated().any() or not np.isfinite(m[['salida_min','llegada_min']]).all().all() or (m.llegada_min<m.salida_min).any():
        raise ValueError('Movimientos repetidos o tiempos inválidos.')
    byid=m.set_index('id_salida').to_dict('index')
    interior=m.loc[m.punto.eq('INTERIOR')].sort_values(['salida_min','id_salida']).to_dict('records')
    if not interior:raise ValueError('Falta la oferta interior.')
    pointmap=objetivos.set_index('punto').corredor.to_dict()
    demand=objetivos.set_index('corredor').demanda_lanzadera_condicionada_dia.to_dict()
    remaining={('viaje',i):cap for i in byid}
    choices=[]
    if mantener_pares:
        required=['id_subida','id_regreso','plazas_vinculadas']
        if not set(required)<=set(pares) or pares.duplicated(['id_subida','id_regreso']).any():raise ValueError('Pares ausentes o repetidos.')
        for field in ['id_subida','id_regreso']:
            if not set(pares[field])<=set(byid):raise ValueError('Par de acceso sin viaje físico.')
            if (pares.groupby(field).plazas_vinculadas.sum()>cap+1e-9).any():raise ValueError('Pares que duplican capacidad de acceso.')
        for idx,p in enumerate(pares.to_dict('records')):
            c=_numero(p['plazas_vinculadas'],'capacidad de par')
            remaining[('par',idx)]=c;choices.append((p['id_subida'],p['id_regreso'],('par',idx)))
    else:
        for u in m.loc[m.punto.isin(pointmap)&m.sentido.eq('ida')].to_dict('records'):
            for b in m.loc[m.punto.eq(u['punto'])&m.sentido.eq('vuelta')].to_dict('records'):
                choices.append((u['id_salida'],b['id_salida'],None))
    chains=[];possible=set()
    for uid,bid,pairkey in choices:
        u,b=byid[uid],byid[bid]
        if u['punto'] not in pointmap or u['punto']!=b['punto'] or u['sentido']!='ida' or b['sentido']!='vuelta' or u['destino']!=b['origen']:
            raise ValueError('El regreso no corresponde a la misma cabecera/cadena.')
        if b['salida_min']<u['llegada_min']+stay-1e-9:continue
        for i in interior:
            if i['origen']!=u['destino'] or i['salida_min']<u['llegada_min']+margin-1e-9:continue
            if wait is not None and i['salida_min']>u['llegada_min']+wait+1e-9:continue
            for j in interior:
                if j['origen']!=i['destino'] or j['destino']!=u['destino'] or j['salida_min']<i['llegada_min']+margin-1e-9:continue
                if j['llegada_min']+margin>b['salida_min']+1e-9:continue
                if wait is not None and b['salida_min']>j['llegada_min']+wait+1e-9:continue
                resources=[('viaje',uid),('viaje',i['id_salida']),('viaje',j['id_salida']),('viaje',bid)]
                if len(set(resources))!=4:raise ValueError('La cadena repite un viaje como ida y vuelta.')
                if pairkey is not None:resources.append(pairkey)
                possible.add(uid)
                chains.append({'corredor':pointmap[u['punto']],'punto':u['punto'],'id_subida_acceso':uid,
                    'id_interior_ida':i['id_salida'],'id_interior_regreso':j['id_salida'],'id_bajada_acceso':bid,
                    'salida_acceso_min':u['salida_min'],'llegada_parque_min':u['llegada_min'],
                    'salida_interior_ida_min':i['salida_min'],'llegada_otro_terminal_min':i['llegada_min'],
                    'salida_interior_regreso_min':j['salida_min'],'llegada_terminal_acceso_min':j['llegada_min'],
                    'salida_bajada_acceso_min':b['salida_min'],'espera_enlace_ida_min':i['salida_min']-u['llegada_min'],
                    'espera_enlace_regreso_min':b['salida_min']-j['llegada_min'],
                    'tiempo_en_otro_terminal_min':j['salida_min']-i['llegada_min'],'resources':resources})
    # Priorizar cierres tempranos. Esta construcción factible no certifica máximo.
    chains.sort(key=lambda c:(c['salida_bajada_acceso_min'],c['salida_acceso_min'],c['salida_interior_ida_min'],c['salida_interior_regreso_min'],c['corredor']))
    initial=dict(remaining);assigned=[]
    for chain in chains:
        amount=min(demand[chain['corredor']],*(remaining[x] for x in chain['resources']))
        if amount<=1e-9:continue
        demand[chain['corredor']]-=amount
        for resource in chain['resources']:remaining[resource]-=amount
        assigned.append({k:v for k,v in chain.items() if k!='resources'}|{'personas_asignadas_dia_tipo':amount})
    rows=[]
    for o in objetivos.to_dict('records'):
        qty=float(o['demanda_lanzadera_condicionada_dia']);left=max(0.,demand[o['corredor']])
        rows.append({'punto':o['punto'],'corredor':o['corredor'],'demanda_si_todos_usan_interior_dia':qty,
            'asignacion_constructiva_dia':qty-left,'pendiente_no_certifica_imposibilidad_dia':left,
            'subidas_con_alguna_cadena_temporal':sum(byid[i]['punto']==o['punto'] for i in possible),
            'demanda_real_interior_dia':np.nan,'operacion_validada':False})
    loads=[]
    for rid,row in byid.items():
        loads.append({'id_salida':rid,'punto':row['punto'],'sentido':row['sentido'],
            'capacidad':cap,'personas_asignadas_dia_tipo':initial[('viaje',rid)]-remaining[('viaje',rid)]})
    return {'resumen':pd.DataFrame(rows),'asignaciones':pd.DataFrame(assigned,columns=['corredor','punto','id_subida_acceso','id_interior_ida','id_interior_regreso','id_bajada_acceso','salida_acceso_min','llegada_parque_min','salida_interior_ida_min','llegada_otro_terminal_min','salida_interior_regreso_min','llegada_terminal_acceso_min','salida_bajada_acceso_min','espera_enlace_ida_min','espera_enlace_regreso_min','tiempo_en_otro_terminal_min','personas_asignadas_dia_tipo']),'cargas':pd.DataFrame(loads),
        'cadenas_temporales_candidatas':len(chains),'metodo':'Construcción por cierre temprano; no certificado de óptimo'}


def referenciar_paradas_del_eje(trazados, anclajes, atencion, puntos, *, itinerario_ida):
    """Ordenar referencias existentes; una proyección no valida un embarque.

    Las entradas adoptadas prevalecen sobre la proximidad del lugar turístico.
    Los puntos sin entrada se proyectan como propuesta, sin crear carreteras.
    """
    tables = [trazados, anclajes, atencion, puntos]
    if any(x.crs is None or x.crs != trazados.crs for x in tables):
        raise ValueError('Las capas necesitan el mismo CRS métrico.')
    if not trazados.crs.is_projected or any(a.unit_name != 'metre' for a in trazados.crs.axis_info):
        raise ValueError('La referencia longitudinal requiere metros.')
    route = trazados.loc[trazados.itinerary_id.eq(itinerario_ida)]
    if len(route) != 1 or route.geometry.iloc[0].geom_type != 'LineString':
        raise ValueError('Falta un único eje de ida.')
    line = route.geometry.iloc[0]
    anchors = anclajes.loc[anclajes.itinerary_id.eq(itinerario_ida)].set_index('anchor_id')
    if anchors.index.duplicated().any() or puntos.target_id.duplicated().any() or atencion.target_id.duplicated().any():
        raise ValueError('Referencias geográficas repetidas.')
    if not set(atencion.target_id) <= set(puntos.target_id):
        raise ValueError('Atención turística sin lugar identificado.')
    candidates = []
    for role, name in [('origin', 'Boca Tauce'), ('destination', 'El Portillo')]:
        a = anchors.loc[anchors.anchor_role.eq(role)]
        if len(a) != 1:
            raise ValueError('Extremos del eje ambiguos.')
        x = a.iloc[0]
        position = float(x.itinerary_measure_m)
        if not np.isclose(position, 0 if role == 'origin' else line.length, atol=1e-5):
            raise ValueError('Extremo incompatible con la longitud del eje.')
        candidates.append({'parada_id': str(a.index[0]), 'lugar': name, 'posicion_m': position,
            'target_id': '', 'criterio': 'Extremo existente del eje', 'separacion_referencia_eje_m': 0.})
    attention = atencion.set_index('target_id')
    for p in puntos.itertuples():
        if not p.adoptada_para_estudio:
            continue
        if p.target_id in attention.index:
            a = attention.loc[p.target_id]
            anchor = a.anchor_id_referencia
            if pd.notna(anchor):
                if anchor not in anchors.index:
                    raise ValueError('Entrada adoptada ausente del eje.')
                position = float(anchors.loc[anchor, 'itinerary_measure_m'])
                reference = anchors.loc[anchor, 'geometry']
                pid, label = str(anchor), str(anchors.loc[anchor, 'label'])
                criterion = 'Entrada adoptada D091 sobre carretera principal'
            else:
                reference = a.geometry
                position = float(line.project(reference))
                pid = 'referencia_titsa_' + str(a.stop_id_actual)
                label = str(a.referencia)
                criterion = 'Proyección de referencia TITSA existente; embarque pendiente'
        else:
            reference = p.geometry
            position = float(line.project(reference))
            pid, label = 'referencia_' + p.target_id, p.lugar
            criterion = 'Proyección de marcador turístico adoptado; parada por concretar'
        candidates.append({'parada_id': pid, 'lugar': label, 'posicion_m': position,
            'target_id': p.target_id, 'criterio': criterion,
            'separacion_referencia_eje_m': float(line.distance(reference))})
    # Compartir una parada entre objetivos evita crear capacidad o embarques dobles.
    stops, coverage = [], []
    for c in sorted(candidates, key=lambda x: (x['posicion_m'], x['target_id'])):
        existing = next((s for s in stops if abs(s['posicion_m'] - c['posicion_m']) <= 1e-6), None)
        if existing is None:
            existing = {k: c[k] for k in ['parada_id', 'lugar', 'posicion_m', 'criterio']}
            existing.update(orden=len(stops), embarque_validado=False)
            stops.append(existing)
        if c['target_id']:
            coverage.append({'target_id': c['target_id'], 'parada_id': existing['parada_id'],
                'criterio': c['criterio'], 'separacion_referencia_eje_m': c['separacion_referencia_eje_m'],
                'distancia_peatonal_m': np.nan, 'tiempo_acceso_peatonal_min': np.nan,
                'embarque_validado': False})
    result = pd.DataFrame(stops)
    if result.parada_id.duplicated().any() or len(result) < 2:
        raise ValueError('Paradas sin identificación longitudinal única.')
    return result, pd.DataFrame(coverage)


def horario_en_paradas(movimientos, paradas):
    """Distribuir el tiempo total por distancia, como propuesta sin mediciones.

    No se añaden minutos de parada ni se acredita que el tiempo total los cubra.
    Se conservan precisión de cálculo, extremos, oferta y duración de cada viaje.
    """
    s = paradas.sort_values('orden')
    positions = s.posicion_m.to_numpy(dtype=float)
    if (s.parada_id.duplicated().any() or not np.isfinite(positions).all()
            or positions[0] != 0 or np.any(np.diff(positions) <= 0)):
        raise ValueError('Paradas desordenadas, repetidas o distancias inválidas.')
    m = movimientos.loc[movimientos.punto.eq('INTERIOR') & movimientos.componente.str.startswith('comercial')]
    if m.empty or m.duplicated(['tipo_dia', 'id_salida']).any():
        raise ValueError('Oferta interior ausente o repetida.')
    rows = []
    for v in m.itertuples():
        if (v.sentido not in {'ida', 'vuelta'} or not np.isfinite([v.salida_min, v.llegada_min]).all()
                or v.llegada_min <= v.salida_min or not np.isclose(v.km_por_recorrido * 1000, positions[-1], atol=1e-4)):
            raise ValueError('Tiempo, sentido o longitud de viaje incoherente.')
        endpoints = (s.iloc[0].lugar, s.iloc[-1].lugar)
        if (v.origen, v.destino) != (endpoints if v.sentido == 'ida' else endpoints[::-1]):
            raise ValueError('Terminales incompatibles con el sentido.')
        for stop in s.itertuples():
            fraction = stop.posicion_m / positions[-1]
            if v.sentido == 'vuelta':
                fraction = 1 - fraction
            rows.append({'tipo_dia': v.tipo_dia, 'id_salida': v.id_salida, 'sentido': v.sentido,
                'parada_id': stop.parada_id, 'lugar': stop.lugar, 'orden': stop.orden,
                'posicion_m': stop.posicion_m,
                'paso_min': v.salida_min + fraction * (v.llegada_min - v.salida_min),
                'tiempo_parada_individualizado_min': np.nan, 'horario_observado': False})
    return pd.DataFrame(rows)


def cargas_por_tramos(horarios, paradas, reservas, *, capacidad):
    """Comprobar reservas explícitas compartiendo plazas solo donde coinciden.

    Reservas de un día y un contraste. Los cero son asignaciones de esta prueba,
    nunca demanda real cero de otros usuarios o viajes observados.
    """
    cap = _numero(capacidad, 'capacidad', True)
    s = paradas.sort_values('orden').reset_index(drop=True)
    order = s.set_index('parada_id').orden.to_dict()
    if horarios.id_salida.nunique() * len(s) != len(horarios) or horarios.duplicated(['id_salida', 'parada_id']).any():
        raise ValueError('Horarios repetidos o incompletos; evaluar un día tipo cada vez.')
    remaining, rows = {}, []
    for trip, block in horarios.groupby('id_salida', sort=False):
        b = block.set_index('parada_id')
        if set(b.index) != set(order) or b.sentido.nunique() != 1:
            raise ValueError('Viaje sin todas las paradas o con sentido ambiguo.')
        times = b.loc[s.parada_id, 'paso_min'].to_numpy(dtype=float)
        direction = b.sentido.iloc[0]
        if (direction not in {'ida', 'vuelta'} or not np.isfinite(times).all()
                or not np.all(np.diff(times) * (1 if direction == 'ida' else -1) > 0)):
            raise ValueError('Pasos por parada incompatibles con el sentido.')
        for i in range(len(s) - 1):
            remaining[(trip, i)] = 0.
    for r in reservas.itertuples():
        qty = _numero(r.personas, 'personas')
        if r.id_salida not in set(horarios.id_salida) or r.parada_origen not in order or r.parada_destino not in order:
            raise ValueError('Reserva sin viaje o parada.')
        a, b = order[r.parada_origen], order[r.parada_destino]
        h = horarios.loc[horarios.id_salida.eq(r.id_salida)].set_index('parada_id')
        if a == b or h.loc[r.parada_destino, 'paso_min'] <= h.loc[r.parada_origen, 'paso_min']:
            raise ValueError('Reserva contraria al sentido o sin desplazamiento.')
        for i in range(min(a, b), max(a, b)):
            remaining[(r.id_salida, i)] += qty
    for (trip, i), qty in remaining.items():
        if qty > cap + 1e-8:
            raise ValueError('La reserva supera plazas compartidas por tramo.')
        h = horarios.loc[horarios.id_salida.eq(trip)]
        rows.append({'id_salida': trip, 'sentido': h.sentido.iloc[0], 'tramo_orden': i,
            'parada_desde_eje': s.iloc[i].parada_id, 'parada_hasta_eje': s.iloc[i+1].parada_id,
            'longitud_tramo_km': (s.iloc[i+1].posicion_m-s.iloc[i].posicion_m)/1000,
            'capacidad_referencia': cap, 'personas_asignadas_prueba_dia': qty,
            'plazas_restantes_prueba': cap-qty, 'demanda_real_otros_usuarios': np.nan})
    return pd.DataFrame(rows)


def coordinar_destino_por_tramos(objetivos, movimientos, paradas, horarios, *, destino,
        capacidad, margen, estancia, espera_max, ventana_parada_min=0.):
    """Contrastar un destino por visita y volver a la misma cabecera.

    destino=None: entorno del terminal; 'otro_terminal': eje completo; otro:
    parada existente. Cada contraste usa toda la demanda condicional por separado.
    No mezcla destinos ni adopta cuotas. Recoordina parejas de acceso existentes.
    La ventana en parada incluye accesos, colas y embarque; no es visita útil neta.
    Construcción factible por cierre temprano, sin certificado de máximo.
    """
    cap = _numero(capacidad, 'capacidad', True)
    margin = _numero(margen, 'margen')
    stay = _numero(estancia, 'estancia', True)
    wait = _numero(espera_max, 'espera')
    window = _numero(ventana_parada_min, 'ventana')
    if wait < margin:
        raise ValueError('El margen está incluido en la espera máxima.')
    s = paradas.sort_values('orden').reset_index(drop=True)
    if list(s.orden) != list(range(len(s))) or s.parada_id.duplicated().any():
        raise ValueError('Orden de paradas inválido.')
    allowed = {None, 'otro_terminal', *s.parada_id}
    if isinstance(destino, dict):
        if set(destino) != set(objetivos.punto) or any(v not in allowed for v in destino.values()):
            raise ValueError('Mapa de destinos incompleto o sin parada del estudio.')
    elif destino not in allowed:
        raise ValueError('Destino sin parada del estudio.')
    o = objetivos
    if (o.punto.duplicated().any() or o.corredor.duplicated().any()
            or not np.isfinite(o.demanda_lanzadera_condicionada_dia).all()
            or (o.demanda_lanzadera_condicionada_dia < 0).any()):
        raise ValueError('Demanda repetida o inválida.')
    m = movimientos.loc[movimientos.componente.str.startswith('comercial')].copy()
    if (m.id_salida.duplicated().any() or not np.isfinite(m[['salida_min', 'llegada_min']]).all().all()
            or (m.llegada_min <= m.salida_min).any() or not set(m.sentido) <= {'ida', 'vuelta'}):
        raise ValueError('Viajes repetidos o tiempos inválidos; evaluar un día tipo.')
    interior = m.loc[m.punto.eq('INTERIOR')].to_dict('records')
    if not interior or set(horarios.id_salida) != {i['id_salida'] for i in interior}:
        raise ValueError('Horarios de otro conjunto de viajes interiores.')
    # Validar capacidades/horarios también cuando la construcción no asigna viajeros.
    empty = pd.DataFrame(columns=['id_salida', 'parada_origen', 'parada_destino', 'personas'])
    cargas_por_tramos(horarios, s, empty, capacidad=cap)
    ht = horarios.set_index(['id_salida', 'parada_id']).paso_min.to_dict()
    for trip in interior:
        a, b = (s.iloc[0].parada_id, s.iloc[-1].parada_id)
        if trip['sentido'] == 'vuelta': a, b = b, a
        if (not np.isclose(ht[(trip['id_salida'], a)], trip['salida_min'], atol=1e-8, rtol=0)
                or not np.isclose(ht[(trip['id_salida'], b)], trip['llegada_min'], atol=1e-8, rtol=0)):
            raise ValueError('Pasos por parada de otro horario de extremos.')
    order = s.set_index('parada_id').orden.to_dict()
    terminals = {s.iloc[0].lugar: s.iloc[0].parada_id, s.iloc[-1].lugar: s.iloc[-1].parada_id}
    demand = o.set_index('corredor').demanda_lanzadera_condicionada_dia.to_dict()
    pointmap = o.set_index('punto').corredor.to_dict()
    resources = {('acceso', r.id_salida): cap for r in m.loc[m.punto.isin(pointmap)].itertuples()}
    for trip in interior:
        for k in range(len(s)-1):
            resources[('tramo', trip['id_salida'], k)] = cap
    candidates = []
    for u in m.loc[m.punto.isin(pointmap) & m.sentido.eq('ida')].to_dict('records'):
        if u['destino'] not in terminals:
            raise ValueError('Acceso fuera de los terminales interiores.')
        start = terminals[u['destino']]
        # Los cuatro corredores comparten recursos aunque visiten destinos diferentes.
        local_destination = destino[u['punto']] if isinstance(destino, dict) else destino
        target = (s.iloc[-1].parada_id if start == s.iloc[0].parada_id else s.iloc[0].parada_id) if local_destination == 'otro_terminal' else (local_destination or start)
        a, b = order[start], order[target]
        for back in m.loc[m.punto.eq(u['punto']) & m.sentido.eq('vuelta')].to_dict('records'):
            if back['origen'] != u['destino'] or back['destino'] != u['origen']:
                raise ValueError('El regreso no vuelve a la misma cabecera.')
            if back['salida_min'] < u['llegada_min'] + stay - 1e-9:
                continue
            common = {'punto': u['punto'], 'corredor': pointmap[u['punto']], 'parada_destino': target,
                'id_subida_acceso': u['id_salida'], 'id_bajada_acceso': back['id_salida'],
                'salida_acceso_min': u['salida_min'], 'llegada_parque_min': u['llegada_min'],
                'salida_bajada_acceso_min': back['salida_min']}
            access = [('acceso', u['id_salida']), ('acceso', back['id_salida'])]
            if a == b:
                pause = back['salida_min']-u['llegada_min']
                if pause >= window:
                    candidates.append(common | {'id_interior_ida': None, 'id_interior_regreso': None,
                        'llegada_destino_min': u['llegada_min'], 'salida_destino_min': back['salida_min'],
                        'ventana_parada_min': pause, 'espera_enlace_ida_min': np.nan,
                        'espera_enlace_regreso_min': np.nan, 'resources': access, 'legs': []})
                continue
            for i in interior:
                if i['origen'] != u['destino']:
                    continue
                initial_wait = i['salida_min']-u['llegada_min']
                if initial_wait < margin-1e-9 or initial_wait > wait+1e-9:
                    continue
                arrival = ht[(i['id_salida'], target)]
                for j in interior:
                    if j['destino'] != u['destino']:
                        continue
                    departure = ht[(j['id_salida'], target)]
                    pause = departure-arrival
                    final_wait = back['salida_min']-j['llegada_min']
                    if pause < max(margin, window)-1e-9 or final_wait < margin-1e-9 or final_wait > wait+1e-9:
                        continue
                    used = access + [('tramo', trip, k) for trip in [i['id_salida'], j['id_salida']]
                        for k in range(min(a,b), max(a,b))]
                    candidates.append(common | {'id_interior_ida': i['id_salida'], 'id_interior_regreso': j['id_salida'],
                        'llegada_destino_min': arrival, 'salida_destino_min': departure,
                        'ventana_parada_min': pause, 'espera_enlace_ida_min': initial_wait,
                        'espera_enlace_regreso_min': final_wait, 'resources': used,
                        'legs': [(i['id_salida'], start, target), (j['id_salida'], target, start)]})
    # Esta prioridad ofrece una solución reproducible, no un óptimo de transporte.
    candidates.sort(key=lambda c: (c['salida_bajada_acceso_min'], c['salida_acceso_min'], c['llegada_destino_min'], c['corredor']))
    assigned, legs = [], []
    for c in candidates:
        qty = min(demand[c['corredor']], *(resources[k] for k in c['resources']))
        if qty <= 1e-9:
            continue
        demand[c['corredor']] -= qty
        for key in c['resources']:
            resources[key] -= qty
        assigned.append({k:v for k,v in c.items() if k not in {'resources', 'legs'}} | {'personas_asignadas_prueba_dia': qty,
            'tiempo_actividad_util_validado_min': np.nan})
        for trip, origin, destination in c['legs']:
            legs.append({'id_salida': trip, 'parada_origen': origin, 'parada_destino': destination, 'personas': qty})
    summary = []
    for row in o.itertuples():
        choices = [c for c in candidates if c['corredor'] == row.corredor]
        summary.append({'corredor': row.corredor, 'punto': row.punto,
            'demanda_condicionada_prueba_dia': row.demanda_lanzadera_condicionada_dia,
            'asignacion_constructiva_dia': row.demanda_lanzadera_condicionada_dia-demand[row.corredor],
            'pendiente_constructivo_no_imposibilidad_dia': demand[row.corredor],
            'cadenas_temporales_candidatas': len(choices),
            'max_ventana_parada_en_candidatas_min': max((c['ventana_parada_min'] for c in choices), default=np.nan),
            'demanda_real_interior_dia': np.nan, 'operacion_validada': False})
    reservations = pd.DataFrame(legs, columns=list(empty))
    loads = cargas_por_tramos(horarios, s, reservations, capacidad=cap)
    access_loads = [{'id_salida': r[1], 'capacidad_referencia': cap, 'personas_asignadas_prueba_dia': cap-left}
        for r,left in resources.items() if r[0] == 'acceso']
    return {'resumen': pd.DataFrame(summary), 'asignaciones': pd.DataFrame(assigned),
        'reservas_interiores': reservations, 'cargas_tramos': loads, 'cargas_acceso': pd.DataFrame(access_loads)}
