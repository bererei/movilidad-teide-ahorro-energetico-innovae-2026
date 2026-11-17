"""Prueba favorable de reservas: capacidad de subida y regreso compartida.

No mide llegadas reales o demanda servida. Permite ordenar llegadas dentro de
su hora para buscar una asignación posible; el óptimo no valida la operación.
"""
from collections import deque
import numpy as np
import pandas as pd


def repartir_perfil_horario(perfiles, indices, objetivos, *, anio=2028):
    """Trasladar forma horaria de nueve matrices2025 a objetivos anuales por acceso.

    Media de tres meses por tipo de día; no anualiza p85 o medias de57 matrices.
    La cuota temporal es una hipótesis nueva. Las observaciones ausentes siguen
    identificadas, sin declarar demanda cero durante horas no publicadas.
    """
    from movilidad_teide.demanda.asignacion_tipos import SEGMENTOS
    ids=indices.loc[indices.anio.eq(2025)]
    if len(ids)!=9 or ids.duplicated(['mes_publicado','tipo_dia_publicado']).any():
        raise ValueError('Se requieren nueve matrices únicas de2025.')
    keys=['matrix_index','access_corridor','direccion','hora_servicio']
    p=perfiles.loc[perfiles.matrix_index.isin(ids.matrix_index)&perfiles.direccion.eq('subida')].copy()
    if p.duplicated(keys).any() or not p.hora_servicio.isin(range(24)).all():
        raise ValueError('Claves horarias repetidas o inválidas.')
    if not np.isfinite(p[list(SEGMENTOS)]).all().all() or (p[list(SEGMENTOS)]<0).any().any():
        raise ValueError('Demanda no finita o negativa.')
    p['personas']=p[list(SEGMENTOS)].sum(axis=1)
    p=p.merge(ids[['matrix_index','tipo_dia_publicado']],on='matrix_index',validate='many_to_one')
    x=p.groupby(['access_corridor','tipo_dia_publicado','hora_servicio'],as_index=False).agg(
        personas_media=('personas','mean'),matrices_con_registro=('matrix_index','nunique'))
    if objetivos.corredor.duplicated().any() or set(x.access_corridor)!=set(objetivos.corredor):
        raise ValueError('Objetivos duplicados o ámbitos distintos.')
    if not np.isfinite(objetivos.plazas_necesarias_subida_si_transferencia_completa).all() or (objetivos.plazas_necesarias_subida_si_transferencia_completa<0).any():
        raise ValueError('Objetivos anuales inválidos.')
    fechas=pd.date_range(f'{anio}-01-01',f'{anio}-12-31')
    tipos=np.where(fechas.dayofweek==5,'Sábado',np.where(fechas.dayofweek==6,'Domingo','Laborable'))
    dias=pd.Series(tipos).value_counts().to_dict()
    x['dias_calendario']=x.tipo_dia_publicado.map(dias)
    if x.dias_calendario.isna().any():raise ValueError('Tipo de día no reconocido.')
    x['peso_anual_sin_normalizar']=x.personas_media*x.dias_calendario
    den=x.groupby('access_corridor').peso_anual_sin_normalizar.transform('sum')
    if (den<=0).any():raise ValueError('No hay perfil temporal para distribuir.')
    targets=objetivos.set_index('corredor').plazas_necesarias_subida_si_transferencia_completa
    x['personas_anuales_condicionadas']=x.access_corridor.map(targets)*x.peso_anual_sin_normalizar/den
    x['personas_dia_tipo_condicionadas']=x.personas_anuales_condicionadas/x.dias_calendario
    x['estado']='Forma temporal propuesta normalizada al objetivo D155; ausencias publicadas explícitas'
    return x


def asignar_reservas_favorables(demanda, movimientos, *, capacidad, espera_min, estancia_min, cambio_franja=False):
    """Máximo flujo de cohortes horarias a salidas y regresos con capacidad única.

    Una llegada puede situarse en cualquier minuto de su hora de origen. Eso
    es flexibilidad de reservas, no distribución observada ni garantía de espera.
    Cada plaza de regreso solo se usa una vez; permite estancias más largas.
    """
    for key,v in [('capacidad',capacidad),('espera',espera_min),('estancia',estancia_min)]:
        if isinstance(v,bool) or not np.isfinite(v) or v<0 or (key=='capacidad' and v==0):
            raise ValueError('Condición no válida: '+key)
    if demanda.hora_servicio.duplicated().any() or not demanda.hora_servicio.isin(range(24)).all():
        raise ValueError('Horas inválidas o duplicadas.')
    if not np.isfinite(demanda.personas_dia_tipo_condicionadas).all() or (demanda.personas_dia_tipo_condicionadas<0).any():
        raise ValueError('Demanda inválida.')
    if movimientos.id_salida.duplicated().any():raise ValueError('Salidas duplicadas.')
    if not np.isfinite(movimientos[['salida_min','llegada_min']]).all().all() or (movimientos.llegada_min<movimientos.salida_min).any():
        raise ValueError('Tiempos de salida o llegada inválidos.')
    up=movimientos.loc[movimientos.sentido.eq('ida')&movimientos.componente.str.startswith('comercial')].sort_values('salida_min')
    back=movimientos.loc[movimientos.sentido.eq('vuelta')&movimientos.componente.str.startswith('comercial')].sort_values('salida_min')
    # Red residual: demanda → subida (capacidad única) → regreso → destino.
    graph={};refs={}
    def edge(a,b,c):
        graph.setdefault(a,{});graph.setdefault(b,{})
        graph[a][b]=float(c);graph[b].setdefault(a,0.)
        refs[a,b]=float(c)
    total=float(demanda.personas_dia_tipo_condicionadas.sum());inf=total+1
    for d in demanda.itertuples():
        h=int(d.hora_servicio);node=('hora',h);edge('origen',node,d.personas_dia_tipo_condicionadas)
        for u in up.itertuples():
            # Intersección del bloque [h,h+1) con la llegada admisible [salida-espera,salida].
            left=max(h*60,u.salida_min-espera_min);right=min((h+1)*60-1e-7,u.salida_min)
            if cambio_franja or left<=right:edge(node,('subida',u.id_salida),inf)
    for u in up.itertuples():
        edge(('subida',u.id_salida),('fin_subida',u.id_salida),capacidad)
        for b in back.itertuples():
            if b.salida_min>=u.llegada_min+estancia_min-1e-9:
                edge(('fin_subida',u.id_salida),('regreso',b.id_salida),inf)
    for b in back.itertuples():edge(('regreso',b.id_salida),'destino',capacidad)
    flow=0.
    while True:
        prev={'origen':None};q=deque(['origen'])
        while q and 'destino' not in prev:
            a=q.popleft()
            for b,c in graph.get(a,{}).items():
                if c>1e-9 and b not in prev:prev[b]=a;q.append(b)
        if 'destino' not in prev:break
        delta=inf;v='destino'
        while prev[v] is not None:delta=min(delta,graph[prev[v]][v]);v=prev[v]
        v='destino'
        while prev[v] is not None:
            a=prev[v];graph[a][v]-=delta;graph[v][a]+=delta;v=a
        flow+=delta
    horas=[]
    for d in demanda.itertuples():
        node=('hora',int(d.hora_servicio));pending=graph['origen'][node]
        horas.append({'hora_servicio':d.hora_servicio,'personas_dia_tipo_condicionadas':d.personas_dia_tipo_condicionadas,
            'asignables_bajo_reservas_favorables':d.personas_dia_tipo_condicionadas-pending,
            'sin_asignacion_incluso_favorable':pending})
    loads=[]
    for u in up.itertuples():
        a,b=('subida',u.id_salida),('fin_subida',u.id_salida)
        loads.append({'id_salida':u.id_salida,'sentido':'ida','salida_min':u.salida_min,'personas_asignadas_favorables':capacidad-graph[a][b],'capacidad':capacidad})
    for b in back.itertuples():
        a=('regreso',b.id_salida)
        loads.append({'id_salida':b.id_salida,'sentido':'vuelta','salida_min':b.salida_min,'personas_asignadas_favorables':capacidad-graph[a]['destino'],'capacidad':capacidad})
    pares=[]
    for u in up.itertuples():
        for b in back.itertuples():
            key=(('fin_subida',u.id_salida),('regreso',b.id_salida))
            if key in refs:
                value=refs[key]-graph[key[0]][key[1]]
                if value>1e-8:pares.append({'id_subida':u.id_salida,'id_regreso':b.id_salida,
                    'salida_subida_min':u.salida_min,'llegada_parque_min':u.llegada_min,
                    'salida_regreso_min':b.salida_min,'plazas_vinculadas':value})
    return {'pares':pd.DataFrame(pares),'por_hora':pd.DataFrame(horas),'por_salida':pd.DataFrame(loads),
        'demanda':total,'asignable':flow,'pendiente':total-flow}


def objetivos_reservados_por_dia(referencias, dias_por_tipo, *, crecimiento, ocupacion, fraccion_coche, cupo):
    """Demanda condicionada por día tipo con techo entero GLOBAL de coches.

    Cupos territoriales propuestos por pesos de la demanda modelizada, no aforos.
    El método de mayores restos mantiene el total entero, sin crear 500 por vía.
    La captación no procedente del coche se conserva una sola vez.
    """
    if (ocupacion<1 or not np.isfinite(ocupacion) or not 0<=fraccion_coche<=1 or
        not np.isfinite(crecimiento) or crecimiento<=0 or isinstance(cupo,bool) or cupo<0 or cupo!=int(cupo)):
        raise ValueError('Condiciones de demanda o cupo inválidas.')
    a=referencias.loc[referencias.direccion.eq('subida')].copy()
    keys=['matrix_index','access_corridor','colectivo']
    if a.duplicated(keys).any():raise ValueError('Referencias diarias duplicadas.')
    campos=['viajes_persona_dia_referencia','viajes_persona_captables_dia_referencia']
    if not np.isfinite(a[campos]).all().all() or (a[campos]<0).any().any():raise ValueError('Referencias inválidas.')
    g=a.groupby(['tipo_dia_publicado','access_corridor','colectivo'],as_index=False)[campos].mean()
    g[campos]=g[campos]*crecimiento
    g['coches_sin_condicionados']=g.viajes_persona_dia_referencia*fraccion_coche/ocupacion
    detalles=[];resumen=[]
    for tipo,b in g.groupby('tipo_dia_publicado',sort=True):
        weights=b.groupby('access_corridor').coches_sin_condicionados.sum().sort_index()
        total=weights.sum();roof=min(int(cupo),int(np.floor(total)))
        raw=weights*roof/total if total>0 else weights*0
        quotas=np.floor(raw).astype(int)
        remaining=roof-int(quotas.sum())
        order=(raw-quotas).sort_values(ascending=False,kind='stable').index
        for c in order[:remaining]:quotas.loc[c]+=1
        for corridor,block in b.groupby('access_corridor',sort=True):
            cars=float(weights[corridor]);authorized=min(cars,float(quotas[corridor]))
            ratio=0 if cars==0 else (cars-authorized)/cars
            z=block.copy();z['recorridos_coche_retirados_condicionados_dia']=z.coches_sin_condicionados*ratio
            z['dias_calendario']=dias_por_tipo[tipo]
            z['recorridos_coche_retirados_condicionados_anio']=z.recorridos_coche_retirados_condicionados_dia*z.dias_calendario
            detalles.append(z)
            demand=float((z.recorridos_coche_retirados_condicionados_dia*ocupacion+
                z.viajes_persona_captables_dia_referencia*(1-fraccion_coche)).sum())
            resumen.append({'tipo_dia':tipo,'corredor':corridor,'dias_calendario':dias_por_tipo[tipo],
                'cupo_coches_propuesto_dia':int(quotas[corridor]),'coches_autorizados_condicionados_dia':authorized,
                'coches_sin_condicionados_dia':cars,'demanda_lanzadera_condicionada_dia':demand,
                'demanda_lanzadera_condicionada_anio':demand*dias_por_tipo[tipo]})
    return {'detalle':pd.concat(detalles,ignore_index=True),'resumen':pd.DataFrame(resumen)}


def proponer_refuerzos_reservados(objetivos, movimientos, mapa_puntos, *, capacidad, estancia_min):
    """Conservar oferta y añadir pares de guaguas en horarios ya existentes.

    Cada par adicional duplica una pareja temporal válida, sin alargar cierres.
    Oferta constante al máximo de los tres días medios; no prueba picos o flota
    disponible. Los vehículos, vacíos y kilómetros deben recalcularse después.
    """
    if capacidad<=0 or capacidad!=int(capacidad):raise ValueError('Capacidad de billetes debe ser entera positiva.')
    original=movimientos.loc[movimientos.componente.str.startswith('comercial')].copy(deep=True)
    additions=[];inventario=[];pares=[]
    for corredor,punto in mapa_puntos.items():
        block=original.loc[original.punto.eq(punto)]
        demand=objetivos.loc[objetivos.corredor.eq(corredor)]
        if demand.empty:raise ValueError('Falta demanda por acceso.')
        supply=asignar_reservas_favorables(pd.DataFrame({'hora_servicio':[0],
            'personas_dia_tipo_condicionadas':[len(block)*capacidad+1.]}),block,
            capacidad=capacidad,espera_min=0,estancia_min=estancia_min,cambio_franja=True)
        links=supply['pares']
        if links.empty:raise ValueError('No existe una pareja de subida/regreso para reforzar.')
        if not np.allclose(links.plazas_vinculadas,np.round(links.plazas_vinculadas)):
            raise ValueError('Las cuotas máximas de billetes deben ser enteras.')
        peak=float(demand.demanda_lanzadera_condicionada_dia.max())
        extra=max(0,int(np.ceil((peak-supply['asignable'])/capacidad-1e-12)))
        # Repartir los refuerzos entre las parejas temporales, sin favorecer una hora por ahorro.
        for i in range(extra):
            pair=links.iloc[i%len(links)]
            newids={}
            for sense,field in [('ida','id_subida'),('vuelta','id_regreso')]:
                row=block.loc[block.id_salida.eq(pair[field])].iloc[0].to_dict()
                row['id_salida']=f'{punto}_reserva_extra_{sense}_{i:03d}'
                row['vehiculo_id']='Pendiente de recalcular';newids[sense]=row['id_salida'];additions.append(row)
            pares.append({'punto':punto,'id_subida':newids['ida'],'id_regreso':newids['vuelta'],
                'salida_subida_min':pair.salida_subida_min,'llegada_parque_min':pair.llegada_parque_min,
                'salida_regreso_min':pair.salida_regreso_min,'plazas_vinculadas':capacidad,'tipo':'Refuerzo propuesto'})
        for row in links.to_dict('records'):pares.append({'punto':punto,**row,'tipo':'Pareja de oferta existente'})
        inventario.append({'corredor':corredor,'punto':punto,'capacidad_vinculada_base_dia':supply['asignable'],
            'demanda_maxima_dia_tipo':peak,'pares_adicionales_por_dia':extra,
            'capacidad_vinculada_propuesta_dia':supply['asignable']+extra*capacidad,
            'capacidad_entera_por_salida':capacidad,'criterio':'Oferta constante; máximo de tres días medios, no picos'})
    planned=pd.concat([original,pd.DataFrame(additions)],ignore_index=True) if additions else original
    if planned.id_salida.duplicated().any():raise ValueError('El plan duplica identificadores.')
    if not set(original.id_salida)<=set(planned.id_salida):raise ValueError('Se ha perdido oferta inicial.')
    return {'salidas':planned,'pares':pd.DataFrame(pares),'resumen':pd.DataFrame(inventario)}


def demanda_diseno_p85(perfiles, indices, valores, *, crecimiento, fraccion_coche):
    """Aplicar las reglas del caso a cada matriz antes de obtener percentiles.

    Conservo el cupo global y la transferencia completa del caso vigente.
    El perfil horario del origen no es una llegada medida a la cabecera. Las
    reservas permiten cambiar de franja. El p85 no se anualiza como pasajeros.
    """
    from movilidad_teide.demanda.asignacion_tipos import SEGMENTOS
    from movilidad_teide.operacion.dimensionamiento import CAPTACION
    from movilidad_teide.opciones import PUNTOS
    keys = ['matrix_index', 'access_corridor', 'direccion', 'hora_servicio']
    if (not set(keys + list(SEGMENTOS)) <= set(perfiles) or perfiles.empty
            or perfiles.duplicated(keys).any() or perfiles[keys].isna().any().any()):
        raise ValueError('Perfiles incompletos, ausentes o repetidos.')
    if (set(indices.matrix_index) != set(range(57)) or indices.matrix_index.duplicated().any()
            or set(perfiles.matrix_index) != set(range(57))
            or set(perfiles.access_corridor) != set(PUNTOS)
            or not perfiles.hora_servicio.isin(range(24)).all()
            or not np.isfinite(perfiles[list(SEGMENTOS)]).all().all()
            or perfiles[list(SEGMENTOS)].lt(0).any().any()):
        raise ValueError('Muestra, horas, corredores o personas no válidos.')
    p = valores['percentil_diseno']
    coeffs = {g: valores[k] for g, k in CAPTACION.items()}
    if (not np.isfinite([p, crecimiento, fraccion_coche, *coeffs.values()]).all()
            or not 0 < p < 1 or crecimiento <= 0 or not 0 <= fraccion_coche <= 1
            or any(not 0 <= c <= 1 for c in coeffs.values())):
        raise ValueError('Percentil, crecimiento o captación no válidos.')
    up = perfiles.loc[perfiles.direccion.eq('subida')].copy()
    if any(set(g.matrix_index) != set(range(57)) for _, g in up.groupby('access_corridor')):
        raise ValueError('Faltan observaciones de subida.')
    within = up.hora_servicio.between(valores['hora_inicio_acceso'], valores['hora_fin_acceso'])
    refs = []
    for (i, corridor), g in up.groupby(['matrix_index', 'access_corridor']):
        window = g.hora_servicio.between(valores['hora_inicio_acceso'], valores['hora_fin_acceso'])
        for group in SEGMENTOS:
            refs.append({'matrix_index': i, 'access_corridor': corridor, 'colectivo': group,
                'direccion': 'subida', 'tipo_dia_publicado': str(i),
                'viajes_persona_dia_referencia': float(g[group].sum()),
                'viajes_persona_captables_dia_referencia': float(g.loc[window, group].sum() * coeffs[group])})
    # Una etiqueta distinta por matriz evita promediar antes de aplicar el cupo.
    daily = objetivos_reservados_por_dia(pd.DataFrame(refs), {str(i): 1 for i in range(57)},
        crecimiento=crecimiento, ocupacion=valores['ocupacion_coche'], fraccion_coche=fraccion_coche,
        cupo=valores['cupo_global'])['resumen']
    daily['matrix_index'] = daily.tipo_dia.astype(int)
    daily = daily.drop(columns=['tipo_dia', 'dias_calendario', 'demanda_lanzadera_condicionada_anio'])
    ratio = daily.set_index(['matrix_index', 'corredor'])
    ratios = ((ratio.coches_sin_condicionados_dia - ratio.coches_autorizados_condicionados_dia)
              / ratio.coches_sin_condicionados_dia.where(ratio.coches_sin_condicionados_dia.gt(0))).fillna(0).to_dict()
    fraction = np.array([ratios[i, c] for i, c in zip(up.matrix_index, up.access_corridor)])
    up['personas_transferidas_coche'] = up[list(SEGMENTOS)].sum(axis=1) * crecimiento * fraccion_coche * fraction
    up['personas_captadas_otros'] = sum(up[g] * coeffs[g] for g in SEGMENTOS) * crecimiento * (1-fraccion_coche) * within
    up['personas_lanzadera'] = up.personas_transferidas_coche + up.personas_captadas_otros
    up['dentro_ventana_fuente'] = within
    actual = up.groupby(['matrix_index', 'access_corridor']).personas_lanzadera.sum().sort_index()
    expected = daily.set_index(['matrix_index', 'corredor']).demanda_lanzadera_condicionada_dia.sort_index()
    if not np.allclose(actual, expected, rtol=0, atol=1e-8):
        raise ValueError('La distribución horaria no conserva las personas de la regla diaria.')
    tags = indices[['matrix_index', 'tipo_dia_publicado']]
    up = up.merge(tags, on='matrix_index', validate='many_to_one')
    daily = daily.merge(tags, on='matrix_index', validate='many_to_one')
    hourly = up.groupby(['access_corridor', 'hora_servicio'], as_index=False).agg(
        personas_p85=('personas_lanzadera', lambda x: x.quantile(p)),
        observaciones_publicadas=('matrix_index', 'nunique'),
        dentro_ventana_fuente=('dentro_ventana_fuente', 'first'))
    totals = daily.groupby('corredor', as_index=False).agg(
        personas_p85_total_dia=('demanda_lanzadera_condicionada_dia', lambda x: x.quantile(p)),
        observaciones=('matrix_index', 'nunique'))
    envelope = hourly.groupby('access_corridor').personas_p85.sum()
    totals['suma_p85_horarios'] = totals.corredor.map(envelope)
    totals['punto'] = totals.corredor.map(PUNTOS)
    types = daily.groupby(['tipo_dia_publicado', 'corredor'], as_index=False).agg(
        personas_p85_total_dia=('demanda_lanzadera_condicionada_dia', lambda x: x.quantile(p)),
        observaciones=('matrix_index', 'nunique'))
    return {'observaciones_horarias': up, 'observaciones_diarias': daily,
        'p85_horario': hourly, 'p85_diario': totals, 'p85_por_tipo_dia': types}



def auditar_perfil_reservado_p85(demanda, pares, *, capacidad, espera, cambio_franja):
    """Máximo flujo entre preferencias horarias y cadenas completas ya comprobadas.

    Una cadena conserva subida, interior y regreso de la misma cabecera. Antes
    de usar esta cota, comprobar capacidad interior con todas las cadenas llenas.
    Preferencia horaria de la fuente no equivale a llegada medida a cabecera.
    """
    if (demanda.hora_servicio.duplicated().any() or not demanda.hora_servicio.isin(range(24)).all()
            or not np.isfinite(demanda.personas_p85).all() or demanda.personas_p85.lt(0).any()
            or pares.id_subida.duplicated().any() or pares.id_regreso.duplicated().any()
            or not np.isfinite(pares.salida_min).all()
            or not np.isfinite([capacidad, espera]).all() or capacidad <= 0 or espera < 0):
        raise ValueError('Perfil, cadenas o capacidad inválidos.')
    graph = {}; original = {}
    def edge(a, b, value):
        graph.setdefault(a, {})[b] = float(value)
        graph.setdefault(b, {}).setdefault(a, 0.)
        original[a, b] = float(value)
    total = float(demanda.personas_p85.sum())
    for row in demanda.itertuples():
        node = ('hora', int(row.hora_servicio)); edge('origen', node, row.personas_p85)
        for pair in pares.itertuples():
            compatible = max(row.hora_servicio*60, pair.salida_min-espera) <= min((row.hora_servicio+1)*60-1e-7, pair.salida_min)
            if cambio_franja or compatible:
                edge(node, ('cadena', pair.id_subida), total+1)
    for pair in pares.itertuples(): edge(('cadena', pair.id_subida), 'destino', capacidad)
    value = 0.
    while True:
        parents = {'origen': None}; queue = deque(['origen'])
        while queue and 'destino' not in parents:
            a = queue.popleft()
            for b, qty in graph.get(a, {}).items():
                if qty > 1e-9 and b not in parents: parents[b] = a; queue.append(b)
        if 'destino' not in parents: break
        increment = total+1; b = 'destino'
        while parents[b] is not None:
            a = parents[b]; increment = min(increment, graph[a][b]); b = a
        b = 'destino'
        while parents[b] is not None:
            a = parents[b]; graph[a][b] -= increment; graph[b][a] += increment; b = a
        value += increment
    hours = []
    for row in demanda.itertuples():
        pending = graph['origen'][('hora', int(row.hora_servicio))]
        hours.append({'hora_servicio': int(row.hora_servicio), 'personas_p85': row.personas_p85,
            'asignadas': row.personas_p85-pending, 'sin_asignacion': pending})
    return {'por_hora': pd.DataFrame(hours), 'demanda': total, 'asignacion_maxima_cadenas': value,
        'sin_asignacion': max(0., total-value),
        'por_cadena': pd.DataFrame([{'id_subida': x.id_subida,
            'personas_asignadas': capacidad-graph[('cadena',x.id_subida)]['destino']} for x in pares.itertuples()])}


def ordenar_cadenas_refuerzo(pares):
    """Preparar bloques anidados sin cambiar horas de billetes confirmados.

    Conservo primeras/últimas subidas y última bajada. Completo el orden por
    separación temporal, sin usar consumo o ahorro para elegir las salidas.
    """
    required = {'punto', 'id_subida', 'id_regreso', 'salida_min', 'salida_regreso_min'}
    if (not required <= set(pares) or pares.empty or pares.id_subida.duplicated().any()
            or pares.id_regreso.duplicated().any()
            or not np.isfinite(pares[['salida_min','salida_regreso_min']]).all().all()):
        raise ValueError('Cadenas incompletas, repetidas o tiempos inválidos.')
    rows = []
    for point, group in pares.groupby('punto'):
        g = group.sort_values(['salida_min','id_subida']).reset_index(drop=True)
        selected = list(dict.fromkeys([0,len(g)-1,int(g.salida_regreso_min.idxmax())]))
        while len(selected) < len(g):
            options = [i for i in range(len(g)) if i not in selected]
            chosen = max(options, key=lambda i: (min(abs(g.salida_min.iloc[i]-g.salida_min.iloc[j]) for j in selected),-i))
            selected.append(chosen)
        for rank, i in enumerate(selected, 1):
            rows.append({'punto': point, 'orden_activacion': rank, 'id_subida': g.id_subida.iloc[i],
                'id_regreso': g.id_regreso.iloc[i], 'salida_min': float(g.salida_min.iloc[i]),
                'salida_regreso_min': float(g.salida_regreso_min.iloc[i])})
    return pd.DataFrame(rows)


def construir_perfil_refuerzos(movimientos, pares, orden, cuentas, valores):
    """Recalcular vehículos y vacíos para un subconjunto del reloj D192.

    Interior completo cada15min y bajadas sin pareja conservados. Los perfiles
    son propuestas de operación; no recortes del horario vigente ya adoptados.
    """
    from movilidad_teide.operacion.circulacion import programar_circulacion
    if (set(cuentas) != set(pares.punto) or movimientos.tipo_dia.nunique()!=1
            or pares.tipo_dia.nunique()!=1 or set(pares.id_subida)!=set(orden.id_subida)):
        raise ValueError('Seleccionar un único día de diseño con todos los accesos.')
    selected = []
    for point, count in cuentas.items():
        g = orden.loc[orden.punto.eq(point)]
        if (isinstance(count,(bool,np.bool_)) or not isinstance(count,(int,np.integer))
                or not 3<=count<=len(g)):
            raise ValueError('Cantidad de parejas fuera del catálogo.')
        selected.extend(g.loc[g.orden_activacion.le(count),'id_subida'])
    links = pares.loc[pares.id_subida.isin(selected)].copy()
    commercial = movimientos.loc[movimientos.componente.eq('comercial')].copy()
    pair_ids = set(pares.id_subida)|set(pares.id_regreso)
    # Bajadas adicionales sin pareja siguen ofreciendo su servicio; no se eliminan.
    keep_ids = set(links.id_subida)|set(links.id_regreso)
    keep = commercial.punto.eq('INTERIOR')|commercial.id_salida.isin(keep_ids)|~commercial.id_salida.isin(pair_ids)
    plan = commercial.loc[keep]
    summaries = []
    for point,g in plan.groupby('punto'):
        summaries.append({'punto':point,'salidas_ida_dia':int(g.sentido.eq('ida').sum()),
            'salidas_vuelta_dia':int(g.sentido.eq('vuelta').sum()),
            **{'longitud_'+s+'_km':float(g.loc[g.sentido.eq(s),'km_por_recorrido'].iloc[0]) for s in ['ida','vuelta']}})
    geo = movimientos[['punto','sentido','origen','destino','itinerary_id']].drop_duplicates()
    z = programar_circulacion(pd.DataFrame(summaries),pd.DataFrame(),pd.DataFrame(),geo,valores,
        salidas_propuestas=plan[['punto','sentido','salida_min','id_salida']],plan_completo_reservas=True)
    for point in cuentas:
        base = geo.loc[geo.punto.eq(point)&geo.sentido.eq('ida'),'origen'].item()
        if not z['vehiculos'].loc[z['vehiculos'].punto.eq(point),'terminal_inicial'].eq(base).all():
            raise ValueError('El perfil necesita un acceso iniciado fuera de cabecera.')
    links['personas_asignadas_dia_tipo'] = int(valores['plazas_guagua']*valores['ocupacion_diseno'])
    return {**z,'pares':links}


def elegir_activacion_refuerzos(demanda, catalogo, bases_por_tipo, orden, *, tipo_dia,
                                cadenas_confirmadas=(), capacidad=46):
    """Elegir capacidad propuesta sin inventar demanda servida o frecuencia anual.

    Demanda incluye una sola vez reservas confirmadas y solicitudes consideradas.
    Las cadenas confirmadas fuerzan mantener su bloque y sus horas. Este control
    agregado no sustituye el control de plazas por billete y tramo al vender.
    """
    if tipo_dia not in {*bases_por_tipo,'Festivo/especial'}:
        raise ValueError('Tipo de día sin regla explícita; no se asimila a domingo.')
    points = sorted(orden.punto.unique())
    if (set(demanda)!=set(points) or not np.isfinite(list(demanda.values())).all()
            or min(demanda.values())<0 or not np.isfinite(capacidad) or capacidad<=0):
        raise ValueError('Demanda incompleta, negativa o no finita.')
    confirmed = set(cadenas_confirmadas)
    if confirmed-set(orden.id_subida):raise ValueError('Cadena confirmada ajena al reloj propuesto.')
    maximum = orden.groupby('punto').orden_activacion.max().to_dict()
    floor = maximum if tipo_dia=='Festivo/especial' else bases_por_tipo[tipo_dia]
    required = {q:max(floor[q],int(np.ceil((demanda[q]-1e-8)/capacidad))) for q in points}
    for q,g in orden.loc[orden.id_subida.isin(confirmed)].groupby('punto'):
        required[q]=max(required[q],int(g.orden_activacion.max()))
    candidates = catalogo.loc[catalogo.perfil_comprobado].copy()
    for q in points:candidates=candidates.loc[candidates['parejas_'+q].ge(required[q])]
    chosen = None if candidates.empty else candidates.sort_values(['parejas_totales','vehiculos_con_reserva','perfil_id']).iloc[0]
    if chosen is None:
        # Capacidad conocida del plan completo, no viajeros realmente transportados.
        available = {q:maximum[q]*capacidad for q in points}
        pending = {q:max(0.,demanda[q]-available[q]) for q in points}
        return {'estado':'Fuera del catálogo comprobado; necesita ampliación','perfil_id':None,
            'capacidad_maxima_conocida':available,'demanda_pendiente':pending,
            'demanda_atendida_acreditada':False}
    state = 'Especial: plan completo' if tipo_dia=='Festivo/especial' else (
        'Base' if all(int(chosen['parejas_'+q])==floor[q] for q in points) else 'Con refuerzos')
    return {'estado':state,'perfil_id':str(chosen.perfil_id),
        'capacidad_maxima_conocida':{q:int(chosen['parejas_'+q])*capacidad for q in points},
        'demanda_pendiente':{q:0. for q in points},'demanda_atendida_acreditada':False}
