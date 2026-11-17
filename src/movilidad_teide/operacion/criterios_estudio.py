"""Revisión con criterios de Luis: aparcamiento, híbridas y actividad común."""
from copy import deepcopy
import numpy as np
import pandas as pd
from movilidad_teide.energia.compatibilidad import verificar_representacion_tecnica
from movilidad_teide.energia.visita_privada import NUEVOS as INTERIOR_NUEVOS, verificar_entradas_interior
from movilidad_teide.opciones import HYBRID
from movilidad_teide.opciones import HYBRID_ID
from movilidad_teide.opciones import PARK_INTERIOR
from movilidad_teide.opciones import PARK_ENTRADA
from movilidad_teide.opciones import OFFICIALS
from movilidad_teide.opciones import REFUERZOS


NUEVOS = {'referencia_guagua_interior','aparcamiento_reservado_referencia','tratamiento_vehiculos_oficiales',
          'fraccion_visita_primera_zona','fraccion_visita_segunda_zona','estrategia_refuerzo_interior'}


def verificar_revision_luis(anterior, actual):
    """Reutilizar solo entradas físicas no afectadas y recalcular energía de buses.

    La categoría de acceso cambia de forma explícita. Ningún resultado antiguo
    se reetiqueta como híbrido: el productor actual vuelve a sumar sus consumos.
    """
    old={p['id']:p for p in anterior['parametros']};new={p['id']:p for p in actual['parametros']}
    if set(old)&NUEVOS or not NUEVOS<=set(new)-set(old):raise ValueError('Faltan las nuevas decisiones de revisión.')
    if new['referencia_guagua_interior']['valor_utilizado']!=HYBRID or new['referencia_guagua_acceso']['valor_utilizado']!=HYBRID:
        raise ValueError('Las nuevas lanzaderas deben contrastarse como híbridas según la respuesta.')
    if new['tratamiento_vehiculos_oficiales']['valor_utilizado']!=OFFICIALS:
        raise ValueError('La actividad oficial necesita tratamiento explícito; no asignar cero a su consumo.')
    if new['aparcamiento_reservado_referencia']['valor_utilizado'] not in {PARK_INTERIOR,PARK_ENTRADA}:
        raise ValueError('Referencia de aparcamiento sin elegir.')
    for k in ['fraccion_visita_primera_zona','fraccion_visita_segunda_zona']:
        value=new[k]['valor_utilizado']
        if value is None or not np.isfinite(value) or not 0<=value<=1:raise ValueError('Fracción de visita no válida.')
    if new['estrategia_refuerzo_interior']['valor_utilizado']!=REFUERZOS:
        raise ValueError('Estrategia interior no implementada.')
    projected=deepcopy(actual)
    projected['parametros']=[p for p in projected['parametros'] if p['id'] not in NUEVOS]
    projected['elecciones_todos_los_casos']=[p for p in projected['elecciones_todos_los_casos'] if p['id'] not in NUEVOS]
    key='referencia_guagua_acceso'
    if key not in old:raise ValueError('Productor anterior sin referencia de acceso revisable.')
    if old[key]['valor_utilizado']!=new[key]['valor_utilizado']:
        if new[key]['propuesta']!=old[key]['propuesta'] or any(new[key][k]!=old[key][k] for k in ['id','grupo','parametro','unidad','aplicacion']):
            raise ValueError('No se conserva el significado de la referencia anterior.')
        if new[key]['modo_efectivo']!='Manual' or not new[key]['justificacion_utilizada'].strip():
            raise ValueError('Cambio de tecnología sin justificación.')
        projected['parametros']=[deepcopy(old[key]) if p['id']==key else p for p in projected['parametros']]
        choices={(p['caso'],p['id']):p for p in anterior['elecciones_todos_los_casos']}
        for i,p in enumerate(projected['elecciones_todos_los_casos']):
            if p['id']!=key:continue
            before=choices[(p['caso'],key)]
            if p['caso']=='Central':
                if any(p[k]!=before[k] for k in p if k not in {'eleccion','valor_manual','justificacion_manual'}):
                    raise ValueError('Cambio ajeno a la referencia de acceso.')
                if p['eleccion']!='Manual' or p['valor_manual']!=HYBRID or not p['justificacion_manual']:
                    raise ValueError('Referencia híbrida no documentada.')
                projected['elecciones_todos_los_casos'][i]=deepcopy(before)
            elif p!=before:raise ValueError('Cambio ajeno en otra variante.')
    validator=verificar_representacion_tecnica if INTERIOR_NUEVOS<=set(old) else verificar_entradas_interior
    return validator(anterior,projected)|{'cambio_categoria_acceso_aplicado_en_recalculo':True,
        'nuevos_criterios_aplicados_aparte':sorted(NUEVOS),'energia_antigua_reetiquetada':False}


def recalcular_oferta_hibrida(energia):
    """Recomponer Hot anual desde cada recorrido con referencia híbrida nativa."""
    d=energia.loc[energia.referencia_id.eq(HYBRID_ID)].copy()
    if d.empty or not d.Fuel.eq('Diesel Hybrid').all() or not d.Segment.eq('Urban Buses Diesel Hybrid').all() or not d['Euro Standard'].eq('Euro VI D/E').all():
        raise ValueError('La biblioteca no acredita la referencia técnica híbrida.')
    known=d.energia_mj_recorrido.notna()
    if d.loc[~known,'vehiculo_km_anio'].fillna(0).gt(0).any():raise ValueError('Actividad de buses sin energía.')
    fields=['recorridos_anio','energia_mj_recorrido']
    if not np.isfinite(d.loc[known,fields]).all().all() or d.loc[known,fields].lt(0).any().any():
        raise ValueError('Energía o recorridos inválidos.')
    fresh=d.loc[known,'recorridos_anio']*d.loc[known,'energia_mj_recorrido']
    if not np.allclose(fresh,d.loc[known,'energia_mj_anio'],rtol=1e-12,atol=1e-6):raise ValueError('El producto recorridos por consumo no concilia.')
    d.loc[known,'energia_mj_anio']=fresh
    d.loc[known,'energia_kwh_anio']=fresh/3.6
    return d


def balance_con_aparcamiento(base, coeficientes, *, primera, segunda, aparcamiento):
    """Conservar el acceso a parking y anular solo circulación privada posterior.

    Primera es la fracción de visitas representadas por el núcleo próximo.
    Segunda es, dentro de ellas, la fracción que añade la otra zona. No son
    porcentajes observados y la hipótesis de visita tipo se contrasta aparte.
    """
    if any(x is None or not np.isfinite(x) or not 0<=x<=1 for x in [primera,segunda]):raise ValueError('Fracciones de visita inválidas.')
    if aparcamiento not in {PARK_INTERIOR,PARK_ENTRADA}:raise ValueError('Aparcamiento no definido.')
    if base.duplicated('alternativa_procedencia').any() or coeficientes.duplicated(['alternativa_procedencia','patron_id']).any():raise ValueError('Alternativas duplicadas.')
    c=coeficientes.set_index(['alternativa_procedencia','patron_id'])
    rows=[]
    for row in base.to_dict('records'):
        ident=row['alternativa_procedencia'];one=c.loc[ident,'zona_proxima'];both=c.loc[ident,'ambas_zonas']
        for branch in ['antes','autorizados','transferidos']:
            if both['K_'+branch+'_mwh_anio']<one['K_'+branch+'_mwh_anio']-1e-8:raise ValueError('Circuito adicional negativo.')
        first_before=primera*one.K_antes_mwh_anio
        parking_after=primera*one.K_autorizados_mwh_anio if aparcamiento==PARK_INTERIOR else 0.
        extra_before=primera*segunda*(both.K_antes_mwh_anio-one.K_antes_mwh_anio)
        before=row['sin_subtotal_hot_identificado_mj_anio']/3600+first_before+extra_before
        after=row['con_subtotal_hot_identificado_mj_anio']/3600+parking_after
        row.update(fraccion_primera_zona=primera,fraccion_segunda_zona=segunda,aparcamiento_referencia=aparcamiento,
            acceso_zona_sin_mwh_anio=first_before,acceso_aparcamiento_con_mwh_anio=parking_after,
            entre_zonas_sin_mwh_anio=extra_before,entre_zonas_privado_con_mwh_anio=0.,
            diferencia_oficiales_mwh_anio=0.,consumo_oficiales_sin_mwh_anio=np.nan,consumo_oficiales_con_mwh_anio=np.nan,
            diferencia_previa_sin_interior_mwh_anio=row['diferencia_hot_identificada_mwh_anio'],
            sin_subtotal_hot_identificado_mj_anio=before*3600,con_subtotal_hot_identificado_mj_anio=after*3600,
            diferencia_hot_identificada_mj_anio=(before-after)*3600,
            alcance='Referencia técnica condicionada; parking conservado, oficiales comunes sin total estimado; no ahorro total acreditado')
        for stem in ['sin_subtotal_hot_identificado','con_subtotal_hot_identificado','diferencia_hot_identificada']:
            for unit,divisor in [('kwh',3.6),('mwh',3600.),('tep',41868.)]:row[stem+'_'+unit+'_anio']=row[stem+'_mj_anio']/divisor
        row['margen_parcial_sobre_60_tep_mwh_anio']=row['diferencia_hot_identificada_mwh_anio']-697.8
        rows.append(row)
    return pd.DataFrame(rows)


def cota_refuerzos_interior(objetivos, movimientos, *, primera, segunda, parking_entrada, capacidad, ocupacion):
    """Necesidad mínima diaria por capacidad de tramos; no horario suficiente.

    Las demandas primarias de ambos extremos usan tramos separados. Los viajes
    a la segunda zona usan el tramo central y comparten recurso una sola vez.
    """
    if any(not np.isfinite(v) or v<=0 for v in [capacidad,ocupacion]) or not 0<=primera<=1 or not 0<=segunda<=1:
        raise ValueError('Capacidad, ocupación o fracciones no válidas.')
    if objetivos.duplicated(['tipo_dia','punto']).any():raise ValueError('Objetivos repetidos.')
    sides={'VILAFLOR':'Boca Tauce','CHIO':'Boca Tauce','OROTAVA':'El Portillo','LAGUNA':'El Portillo'}
    if set(objetivos.punto)!=set(sides):raise ValueError('Falta algún corredor.')
    rows=[]
    for day,g in objetivos.groupby('tipo_dia'):
        if g.dias_calendario.nunique()!=1:raise ValueError('Calendario no coherente.')
        cols=['demanda_lanzadera_condicionada_dia','coches_autorizados_condicionados_dia']
        if not np.isfinite(g[cols]).all().all() or g[cols].lt(0).any().any():raise ValueError('Demanda inválida.')
        m=movimientos.loc[movimientos.tipo_dia.eq(day)&movimientos.punto.eq('INTERIOR')&movimientos.componente.str.startswith('comercial')]
        if m.empty or m.id_salida.duplicated().any():raise ValueError('Oferta interior ausente o repetida.')
        counts=m.groupby('sentido').size().to_dict()
        if set(counts)!={'ida','vuelta'}:raise ValueError('Falta un sentido del servicio.')
        g=g.assign(terminal=g.punto.map(sides))
        access=g.groupby('terminal').demanda_lanzadera_condicionada_dia.sum()
        cars=g.groupby('terminal').coches_autorizados_condicionados_dia.sum()*ocupacion
        demand={'Boca Tauce–zona Parador':primera*(access['Boca Tauce']+(cars['Boca Tauce'] if parking_entrada else 0.)),
            'Zona Teleférico–El Portillo':primera*(access['El Portillo']+(cars['El Portillo'] if parking_entrada else 0.)),
            'Entre Parador y Teleférico':primera*segunda*(access.sum()+cars.sum())}
        for segment,people in demand.items():
            for direction,count in counts.items():
                required=int(np.ceil(max(0.,people-1e-9)/capacidad))
                rows.append({'tipo_dia':day,'dias_calendario':int(g.dias_calendario.iloc[0]),'tramo':segment,'sentido':direction,
                    'personas_por_sentido_dia':float(people),'salidas_existentes':count,'plazas_existentes':count*capacidad,
                    'min_salidas_por_capacidad':required,'min_salidas_adicionales':max(0,required-count),
                    'horario_suficiente_acreditado':False,'otros_usuarios_interiores_identificados':False})
    return pd.DataFrame(rows)

def reforzar_reservas_interior(objetivos, movimientos, pares, paradas, *, destinos,
        capacidad, margen, espera_max, estancia, ventana_parada_min=0.):
    """Añadir salidas interiores a reservas existentes, sin reducir demanda.

    Conserva toda la oferta comercial base. Reutiliza plazas por tramo antes de
    añadir salidas completas. Es una construcción factible, no un mínimo global
    de guaguas o energía; falta asignar vehículos con programar_circulacion.
    Evalúa un único día tipo. La estancia se cuenta desde llegada al Parque.
    """
    from movilidad_teide.operacion.interior import cargas_por_tramos, horario_en_paradas
    if any(not np.isfinite(x) or x < 0 for x in [capacidad,margen,espera_max,estancia,ventana_parada_min]) or capacidad<=0 or espera_max<margen:
        raise ValueError('Capacidad o tiempos de enlace inválidos.')
    o=objetivos
    if o.tipo_dia.nunique()!=1 or o.punto.duplicated().any() or set(destinos)!=set(o.punto):
        raise ValueError('Evaluar un día con destinos y objetivos únicos.')
    if not np.isfinite(o.demanda_lanzadera_condicionada_dia).all() or o.demanda_lanzadera_condicionada_dia.lt(0).any():
        raise ValueError('Demanda no válida.')
    m=movimientos.loc[movimientos.componente.str.startswith('comercial')].copy()
    if m.id_salida.duplicated().any() or set(m.tipo_dia)!={o.tipo_dia.iloc[0]}:
        raise ValueError('Viajes repetidos o de otro día.')
    access=m.loc[m.punto.ne('INTERIOR')].set_index('id_salida')
    inner=m.loc[m.punto.eq('INTERIOR')].copy()
    s=paradas.sort_values('orden').reset_index(drop=True)
    if list(s.orden)!=list(range(len(s))) or s.parada_id.duplicated().any():raise ValueError('Paradas incoherentes.')
    endpoints={s.iloc[0].lugar:s.iloc[0].parada_id,s.iloc[-1].lugar:s.iloc[-1].parada_id}
    order=s.set_index('parada_id').orden.to_dict();positions=s.set_index('parada_id').posicion_m.to_dict()
    if not set(destinos.values())<=set(order):raise ValueError('Destino fuera de las paradas.')
    templates={}
    for sense in ['ida','vuelta']:
        g=inner.loc[inner.sentido.eq(sense)]
        if g.empty or (g.llegada_min-g.salida_min).nunique()!=1:raise ValueError('Duración interior ambigua.')
        templates[sense]=g.iloc[0].to_dict()
    if pares.duplicated(['id_subida','id_regreso']).any() or not np.isfinite(pares.plazas_vinculadas).all() or pares.plazas_vinculadas.lt(0).any():
        raise ValueError('Pares repetidos o capacidad inválida.')
    for field in ['id_subida','id_regreso']:
        if not set(pares[field])<=set(access.index) or pares.groupby(field).plazas_vinculadas.sum().gt(capacidad+1e-8).any():
            raise ValueError('Las parejas exceden capacidad o no tienen viaje físico.')
    # Las plazas libres se comparten entre todos los corredores y ambos extremos.
    trips=inner.to_dict('records');remaining={(t['id_salida'],i):float(capacidad) for t in trips for i in range(len(s)-1)}
    demand=o.set_index('punto').demanda_lanzadera_condicionada_dia.to_dict();assigned=[];reservations=[];new_count=0
    def segments(a,b):return list(range(min(order[a],order[b]),max(order[a],order[b])))
    def at(t,pid):
        fraction=positions[pid]/s.iloc[-1].posicion_m
        if t['sentido']=='vuelta':fraction=1-fraction
        return t['salida_min']+fraction*(t['llegada_min']-t['salida_min'])
    def virtual(sense,departure):
        t=dict(templates[sense]);duration=t['llegada_min']-t['salida_min']
        t.update(id_salida=None,salida_min=float(departure),llegada_min=float(departure+duration),refuerzo_reservas=True)
        return t
    def register(t):
        nonlocal new_count
        if t['id_salida'] is not None:return t
        new_count+=1;t=dict(t);t['id_salida']=f'INTERIOR_reservas_{new_count:03d}_{t["sentido"]}'
        if t['id_salida'] in set(m.id_salida):raise ValueError('Identificador de refuerzo repetido.')
        trips.append(t)
        for i in range(len(s)-1):remaining[(t['id_salida'],i)]=float(capacidad)
        return t
    def free(t,parts):return capacidad if t['id_salida'] is None else min(remaining[(t['id_salida'],i)] for i in parts)
    ordered=pares.sort_values(['salida_regreso_min','llegada_parque_min','id_subida','id_regreso'])
    for p in ordered.itertuples():
        u,b=access.loc[p.id_subida],access.loc[p.id_regreso]
        point=u.punto
        if point not in demand or point!=b.punto or u.sentido!='ida' or b.sentido!='vuelta' or u.destino!=b.origen or u.destino not in endpoints:
            raise ValueError('Reserva sin regreso al mismo acceso.')
        if not np.allclose([p.llegada_parque_min,p.salida_regreso_min],[u.llegada_min,b.salida_min],rtol=0,atol=1e-8):
            raise ValueError('Pareja de otro horario.')
        left=min(float(p.plazas_vinculadas),demand[point])
        if left<=1e-9:continue
        if b.salida_min-u.llegada_min<estancia-1e-8:raise ValueError('Reserva sin estancia mínima en el Parque.')
        entry=endpoints[u.destino];target=destinos[point]
        if target==entry:raise ValueError('El refuerzo requiere desplazamiento a una parada interior.')
        forward='ida' if order[target]>order[entry] else 'vuelta';reverse='vuelta' if forward=='ida' else 'ida'
        parts=segments(entry,target)
        duration_back=templates[reverse]['llegada_min']-templates[reverse]['salida_min']
        while left>1e-8:
            outward=[t for t in trips if t['sentido']==forward and u.llegada_min+margen-1e-8<=t['salida_min']<=u.llegada_min+espera_max+1e-8]
            returns=[t for t in trips if t['sentido']==reverse and b.salida_min-espera_max-1e-8<=t['llegada_min']<=b.salida_min-margen+1e-8]
            outward.append(virtual(forward,u.llegada_min+margen));returns.append(virtual(reverse,b.salida_min-margen-duration_back))
            choices=[]
            for a in outward:
                for z in returns:
                    room=min(free(a,parts),free(z,parts));window=at(z,target)-at(a,target)
                    if room>1e-8 and window>=ventana_parada_min-1e-8:
                        choices.append((int(a['id_salida'] is None)+int(z['id_salida'] is None),-room,a['salida_min'],z['salida_min'],a,z,window))
            if not choices:break # Conservar como pendiente, nunca quitar demanda de la tabla.
            _,_,_,_,a,z,window=min(choices,key=lambda x:x[:4]);a=register(a);z=register(z)
            qty=min(left,free(a,parts),free(z,parts))
            for t in [a,z]:
                for i in parts:remaining[(t['id_salida'],i)]-=qty
            for t,origin,destination in [(a,entry,target),(z,target,entry)]:
                reservations.append({'id_salida':t['id_salida'],'parada_origen':origin,'parada_destino':destination,'personas':qty})
            assigned.append({'punto':point,'id_subida_acceso':p.id_subida,'id_bajada_acceso':p.id_regreso,
                'id_interior_ida':a['id_salida'],'id_interior_regreso':z['id_salida'],'parada_destino':target,
                'llegada_parque_min':u.llegada_min,'salida_bajada_acceso_min':b.salida_min,
                'espera_enlace_ida_min':a['salida_min']-u.llegada_min,'espera_enlace_regreso_min':b.salida_min-z['llegada_min'],
                'llegada_destino_min':at(a,target),'salida_destino_min':at(z,target),'ventana_en_destino_min':window,
                'personas_asignadas_dia_tipo':qty})
            left-=qty;demand[point]-=qty
    plan=pd.DataFrame(trips)
    plan['refuerzo_reservas']=plan.id_salida.str.startswith('INTERIOR_reservas_')
    times=horario_en_paradas(plan,s)
    reserve=pd.DataFrame(reservations,columns=['id_salida','parada_origen','parada_destino','personas'])
    loads=cargas_por_tramos(times,s,reserve,capacidad=capacidad)
    chains=pd.DataFrame(assigned)
    # Verificar por separado que ninguna plaza de acceso/regreso se reutiliza.
    if not chains.empty:
        for field in ['id_subida_acceso','id_bajada_acceso']:
            if chains.groupby(field).personas_asignadas_dia_tipo.sum().gt(capacidad+1e-8).any():raise ValueError('Capacidad pública duplicada.')
    summary=o[['punto','corredor','demanda_lanzadera_condicionada_dia']].copy()
    summary['asignacion_constructiva_dia']=summary.apply(lambda x:x.demanda_lanzadera_condicionada_dia-max(0.,demand[x.punto]),axis=1)
    summary['pendiente_constructivo_dia']=summary.punto.map(demand).clip(lower=0.)
    return {'salidas_comerciales':plan,'asignaciones':chains,'reservas_tramos':reserve,'cargas_tramos':loads,'resumen':summary}
