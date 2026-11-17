"""Alimentación de captados de otros modos y costes pendientes, sin ahorro ficticio."""
import calendar
import numpy as np
import pandas as pd
from movilidad_teide.validacion import comprobar_claves as _claves
from movilidad_teide.energia.actividad_pareada import repartir_actividad_condicionada
from movilidad_teide.energia.balance_condicionado_tipos import CRITERIO_TERRITORIAL, MAGNITUD_ANUAL
from movilidad_teide.energia.circulacion import MODOS
from movilidad_teide.opciones import ALQUILER, PARTICULAR, COLECTIVOS


def actividad_otros_captados(diario, demanda, *, fraccion_coche, anio, dias_periodo=None):
    """Distribuir PERSONAS de otros modos; un regreso por subida es hipótesis.

    Un periodo explícito permite comprobar un día; sin él exijo el año completo.
    Reutilizo las cuotas espaciales existentes, sin anualizar las 57 matrices.
    La unidad de salida es personas-trayecto; no coches realmente observados.
    """
    if isinstance(fraccion_coche, bool) or not np.isfinite(fraccion_coche) or not 0 <= fraccion_coche <= 1:
        raise ValueError('Fracción modal inválida.')
    if isinstance(anio, bool) or not isinstance(anio, (int, np.integer)) or not 1900 <= anio <= 2200:
        raise ValueError('Año inválido.')
    _claves(diario, ['tipo_dia_publicado','access_corridor','colectivo'], 'Captación diaria')
    vals=diario[['viajes_persona_dia_referencia','viajes_persona_captables_dia_referencia','dias_calendario']]
    if (not np.isfinite(vals).all().all() or vals.lt(0).any().any()
            or diario.viajes_persona_captables_dia_referencia.gt(diario.viajes_persona_dia_referencia+1e-9).any()
            or diario.dias_calendario.le(0).any() or diario.dias_calendario.mod(1).ne(0).any()):
        raise ValueError('Demanda o días inválidos.')
    days=diario.groupby('tipo_dia_publicado').dias_calendario
    expected_days = 366 if calendar.isleap(anio) else 365
    if dias_periodo is not None:
        if isinstance(dias_periodo,(bool,np.bool_)) or not isinstance(dias_periodo,(int,np.integer)) or dias_periodo<1:
            raise ValueError('Duración explícita de periodo no válida.')
        expected_days=int(dias_periodo)
    if days.nunique().ne(1).any() or int(days.first().sum()) != expected_days:
        raise ValueError('El calendario no representa el año completo.' if dias_periodo is None else 'La actividad no representa el periodo explícito.')
    combinations=diario.groupby(['access_corridor','colectivo']).tipo_dia_publicado.nunique()
    if combinations.ne(diario.tipo_dia_publicado.nunique()).any():
        raise ValueError('Falta un día tipo para algún colectivo/corredor.')
    d=diario.copy(deep=True)
    d['personas_otros_captados_dia']=d.viajes_persona_captables_dia_referencia*(1-fraccion_coche)
    d['personas_otros_captados_anio']=d.personas_otros_captados_dia*d.dias_calendario
    annual=d.groupby(['access_corridor','colectivo'],as_index=False).personas_otros_captados_anio.sum()
    annual=annual.rename(columns={'personas_otros_captados_anio':MAGNITUD_ANUAL})
    # El distribuidor recibe una magnitud; renombro el resultado para conservar su unidad real.
    conversion=pd.concat([annual.assign(direccion=s,anio_calendario=anio) for s in ['subida','bajada']],ignore_index=True)
    x=repartir_actividad_condicionada(demanda,conversion,criterio=CRITERIO_TERRITORIAL)
    x=x.rename(columns={MAGNITUD_ANUAL:'personas_trayecto_anio','recorridos_grupo_anio':'personas_grupo_sentido_anio'})
    x=x.drop(columns='coches_efectivamente_sustituidos')
    x['estado_reparto']=np.where(x.en_ambito_anual,'Personas de otros modos captadas: reparto territorial condicionado',
                                'Sin ámbito anual; ausencia conservada')
    # Impido duplicar la visita anual por sumar subida y regreso.
    totals=x.loc[x.en_ambito_anual].groupby('sentido').personas_trayecto_anio.sum()
    if len(totals)!=2 or not np.allclose(totals,annual[MAGNITUD_ANUAL].sum(),rtol=1e-12,atol=1e-8):
        raise ValueError('No se conservan las personas de subida y regreso.')
    return {'diario':d,'actividad':x}


def consumo_alimentacion_unitaria(actividad, recorridos, tipologias, factores, velocidades):
    """Ensayar un coche por persona captada de otros modos, solo hasta cabecera.

    Uso las mezclas técnicas existentes y dos asignaciones del colectivo nacional.
    No acredito vehículos retirados del modo previo ni un ahorro de ese servicio.
    Es una prueba exigente, no una cota garantizada: taxi, desvíos y consumos reales
    distintos pueden costar más. La ocupación no es una observación nueva.
    """
    _claves(actividad,['origen_id','colectivo','sentido'],'Actividad de personas')
    _claves(recorridos,['origen_id','sentido'],'Recorridos')
    _claves(tipologias,['comparacion_id','itinerary_id','rol','clase_propuesta'],'Tipologías')
    _claves(factores,['grupo_servicio','modo','velocidad_kmh'],'Factores')
    if set(velocidades)!=set(MODOS) or not set(actividad.colectivo)<=COLECTIVOS:
        raise ValueError('Velocidades o colectivos incompatibles.')
    fields=['comparacion_calculo_id','itinerario_alimentador_id','alimentador_km']
    a=actividad.drop(columns=[c for c in fields if c in actividad]).merge(
        recorridos[['origen_id','sentido']+fields],on=['origen_id','sentido'],how='left',validate='many_to_one',indicator=True)
    if a._merge.ne('both').any():raise ValueError('Falta representación geográfica; no omitir personas.')
    positive=a.loc[a.en_ambito_anual]
    if (positive.empty or not np.isfinite(positive.personas_trayecto_anio).all()
            or positive.personas_trayecto_anio.lt(0).any()):
        raise ValueError('Actividad anual desconocida o negativa.')
    lookup={}
    for service in [PARTICULAR,ALQUILER]:
        for road,mode in MODOS.items():
            f=factores.loc[factores.grupo_servicio.eq(service)&factores.modo.eq(mode)&factores.velocidad_kmh.eq(velocidades[road])]
            if len(f)!=1:raise ValueError('Falta un factor compatible con la velocidad elegida.')
            pair=f[['aporte_conjunto_condicionado_min_mj_km','aporte_conjunto_condicionado_max_mj_km']].to_numpy(float)[0]
            if not np.isfinite(pair).all() or (pair<0).any() or not np.isclose(pair[0],pair[1],rtol=1e-12,atol=1e-12):
                raise ValueError('Se requiere la referencia ponderada única, sin elegir extremos favorables.')
            lookup[service,road]=pair[0]
    rows=[]
    for national,label in [(0,'España no Tenerife: particular'),(1,'España no Tenerife: alquiler')]:
        for row in positive.itertuples():
            service=ALQUILER if row.colectivo=='extranjero' or (national and row.colectivo=='espana_no_tenerife') else PARTICULAR
            c=tipologias.loc[tipologias.comparacion_id.eq(row.comparacion_calculo_id)&tipologias.itinerary_id.eq(row.itinerario_alimentador_id)&tipologias.rol.eq('alimentador')]
            if (c.empty or not set(c.clase_propuesta)<=set(MODOS)
                    or not np.isfinite(c.longitud_clase_km).all() or c.longitud_clase_km.lt(0).any()
                    or not np.isfinite(row.alimentador_km) or row.alimentador_km<0
                    or not np.isclose(c.longitud_clase_km.sum(),row.alimentador_km,rtol=0,atol=1e-8)):
                raise ValueError('Falta longitud o tipología del acceso a cabecera.')
            for part in c.itertuples():
                km=row.personas_trayecto_anio*part.longitud_clase_km
                rows.append({'alternativa_procedencia':label,'origen_id':row.origen_id,'colectivo':row.colectivo,
                    'sentido':row.sentido,'grupo_servicio':service,'itinerary_id':row.itinerario_alimentador_id,
                    'clase_propuesta':part.clase_propuesta,'personas_trayecto_anio':row.personas_trayecto_anio,
                    'longitud_clase_km':part.longitud_clase_km,'vehiculo_km_ensayo_anio':km,
                    'hot_mj_km':lookup[service,part.clase_propuesta],
                    'consumo_ensayo_mj_anio':km*lookup[service,part.clase_propuesta]})
    detail=pd.DataFrame(rows)
    summary=detail.groupby('alternativa_procedencia',as_index=False)[['vehiculo_km_ensayo_anio','consumo_ensayo_mj_anio']].sum()
    # Las personas se cuentan una vez por origen/sentido; no una vez por clase de carretera.
    visits=float(positive.loc[positive.sentido.eq('hacia_teide'),'personas_trayecto_anio'].sum())
    summary['visitas_persona_otro_modo_anio']=visits
    summary['consumo_ensayo_mwh_anio']=summary.consumo_ensayo_mj_anio/3600
    summary['consumo_ensayo_kwh_por_visita']=summary.consumo_ensayo_mwh_anio*1000/visits if visits else np.nan
    summary['energia_real_alimentacion_mwh_anio']=np.nan
    summary['alcance']='Un coche por persona y regreso; contraste, no previsión o máximo garantizado; sin ahorro atribuido al modo previo'
    return {'detalle':detail,'resumen':summary}


def contrastar_otros_consumos(comparacion, alimentacion, *, anio, objetivo_tep):
    """Añadir el coste del ensayo una vez y expresar qué otros cambios faltan.

    El recargo externo existente de guaguas se conserva, sin añadir de nuevo
    auxiliares de esas guaguas. Electricidad de instalaciones está fuera de él.
    Las potencias críticas son equivalencias algebraicas, no presupuestos.
    """
    if isinstance(anio,bool) or not isinstance(anio,(int,np.integer)) or not 1900<=anio<=2200:
        raise ValueError('Año inválido.')
    if isinstance(objetivo_tep,bool) or not np.isfinite(objetivo_tep) or objetivo_tep<=0:
        raise ValueError('Objetivo inválido.')
    _claves(comparacion,['alternativa_procedencia'],'Comparación de un caso')
    _claves(alimentacion,['alternativa_procedencia'],'Alimentación de un caso')
    x=comparacion.merge(alimentacion,on='alternativa_procedencia',how='outer',validate='one_to_one',indicator=True)
    if x._merge.ne('both').any():raise ValueError('Alternativas sin correspondencia.')
    fields=['sin_subtotal_hot_identificado_mwh_anio','con_subtotal_hot_identificado_mwh_anio',
        'diferencia_hot_identificada_mwh_anio','saldo_parcial_tras_contraste_mwh_anio',
        'recargo_operativo_contraste_mwh_anio','consumo_ensayo_mwh_anio']
    if (not np.isfinite(x[fields]).all().all()
            or x[['sin_subtotal_hot_identificado_mwh_anio','con_subtotal_hot_identificado_mwh_anio',
                  'recargo_operativo_contraste_mwh_anio','consumo_ensayo_mwh_anio']].lt(0).any().any()
            or not np.allclose(x.sin_subtotal_hot_identificado_mwh_anio-x.con_subtotal_hot_identificado_mwh_anio,x.diferencia_hot_identificada_mwh_anio)
            or not np.allclose(x.diferencia_hot_identificada_mwh_anio-x.recargo_operativo_contraste_mwh_anio,x.saldo_parcial_tras_contraste_mwh_anio)):
        raise ValueError('Los componentes y saldos no concilian.')
    x=x.drop(columns='_merge')
    x['con_subtotal_ampliado_ensayo_mwh_anio']=x.con_subtotal_hot_identificado_mwh_anio+x.recargo_operativo_contraste_mwh_anio+x.consumo_ensayo_mwh_anio
    x['saldo_parcial_ampliado_ensayo_mwh_anio']=x.sin_subtotal_hot_identificado_mwh_anio-x.con_subtotal_ampliado_ensayo_mwh_anio
    x['objetivo_parcial_mwh_anio']=objetivo_tep*11.63
    x['otros_costes_netos_criticos_para_objetivo_mwh_anio']=x.saldo_parcial_ampliado_ensayo_mwh_anio-x.objetivo_parcial_mwh_anio
    x['coeficiente_instalaciones_mwh_por_kw_medio']=24*(366 if calendar.isleap(anio) else 365)/1000
    x['potencia_media_equivalente_para_objetivo_kw']=x.otros_costes_netos_criticos_para_objetivo_mwh_anio/x.coeficiente_instalaciones_mwh_por_kw_medio
    x['otros_costes_netos_reales_mwh_anio']=np.nan
    x['potencia_instalaciones_elegida_kw']=np.nan
    x['ahorro_total_sistema_mwh_anio']=np.nan
    x['porcentaje_ahorro_total_sistema']=np.nan
    x['cumplimiento_acreditado']=False
    x['ecuacion']='Saldo condicionado ampliado − C_otros; C = incremento neto con menos sin; desconocido, puede tener ambos signos'
    return x


def aplicar_cambio_servicios_existentes(comparacion, *, cambio_neto_mwh_anio):
    """Restar el cambio con menos sin de los servicios mantenidos, una sola vez.

    Cero representa continuidad EN ESTE ENSAYO, no consumo físico nulo o igualdad
    medida. No atribuyo ahorro a un servicio por perder pasajeros. El término
    común desconocido se cancela solo bajo la hipótesis explícita; no completa
    totales ni porcentaje. Otros cambios de transporte conservan su ausencia.
    """
    if (isinstance(cambio_neto_mwh_anio,(bool,np.bool_))
            or not isinstance(cambio_neto_mwh_anio,(int,float,np.integer,np.floating))
            or not np.isfinite(cambio_neto_mwh_anio)):
        raise ValueError('Cambio neto pendiente o inválido; no adoptar cero por ausencia.')
    _claves(comparacion,['caso_ocupacion','alternativa_procedencia'],'Comparación de transporte')
    fields=['sin_subtotal_hot_identificado_mwh_anio','con_subtotal_ampliado_ensayo_mwh_anio',
            'saldo_parcial_ampliado_ensayo_mwh_anio']
    if (comparacion.empty or not np.isfinite(comparacion[fields]).all().all()
            or comparacion[fields[:2]].lt(0).any().any()
            or not np.allclose(comparacion[fields[0]]-comparacion[fields[1]],comparacion[fields[2]],rtol=1e-12,atol=1e-8)):
        raise ValueError('La comparación de partida no concilia.')
    x=comparacion.copy(deep=True)
    x['cambio_neto_servicios_existentes_sup_mwh_anio']=float(cambio_neto_mwh_anio)
    # Un incremento de combustible de servicios existentes disminuye el saldo.
    x['diferencia_condicionada_transporte_mwh_anio']=x.saldo_parcial_ampliado_ensayo_mwh_anio-cambio_neto_mwh_anio
    x['diferencia_condicionada_transporte_kwh_anio']=x.diferencia_condicionada_transporte_mwh_anio*1000
    x['diferencia_condicionada_transporte_tep_anio']=x.diferencia_condicionada_transporte_mwh_anio/11.63
    x['variacion_restante_critica_para_60tep_mwh_anio']=x.diferencia_condicionada_transporte_mwh_anio-60*11.63
    x['consumo_comun_servicios_sin_mwh_anio']=np.nan
    x['consumo_comun_servicios_con_mwh_anio']=np.nan
    x['cambio_neto_observado_servicios_mwh_anio']=np.nan
    x['otros_cambios_transporte_no_representados_mwh_anio']=np.nan
    x['energia_total_transporte_sin_mwh_anio']=np.nan
    x['energia_total_transporte_con_mwh_anio']=np.nan
    x['porcentaje_ahorro_total_transporte']=np.nan
    x['cumplimiento_acreditado']=False
    x['tratamiento_servicios']=('Continuidad energética asumida para el ensayo; no igualdad observada' if cambio_neto_mwh_anio==0
        else 'Cambio neto introducido para estudio; fuente y motivo deben acompañar la elección')
    x['formula_transporte']='Diferencia base − cambio_neto_servicios − otros_cambios_transporte; el último permanece desconocido'
    return x


def estimar_guaguas_comunes(actividad_coches, recorridos, patrones, *, ocupacion_coche,
                           fraccion_coche, ocupacion_guagua, factor_mj_km):
    """Aproximar la movilidad no-coche por guaguas equivalentes, no expediciones GTFS.

    Reutilizo el reparto anual y espacial del caso principal. El mismo consumo
    se conserva antes/después por H120, aunque parte de sus pasajeros se transfiera.
    Ida y regreso proceden de filas distintas; el interior ida/vuelta se reparte
    a mitades. No sumo otra vez TITSA, excursiones o coches ya representados.
    """
    numbers=[ocupacion_coche,fraccion_coche,ocupacion_guagua,factor_mj_km]
    if (any(isinstance(v,(bool,np.bool_)) for v in numbers) or not np.isfinite(numbers).all()
            or ocupacion_coche<1 or ocupacion_guagua<1 or not 0<fraccion_coche<1 or factor_mj_km<0):
        raise ValueError('Ocupación, cuota o factor de referencia inválidos.')
    _claves(actividad_coches,['rama','origen_id','colectivo','sentido'],'Actividad')
    _claves(recorridos,['origen_id','sentido'],'Referencias geográficas')
    _claves(patrones,['terminal_calculo','patron_id'],'Patrones interiores')
    a=actividad_coches.loc[actividad_coches.rama.eq('antes')&actividad_coches.en_ambito_anual].copy()
    if a.empty or set(a.sentido)!={'hacia_teide','desde_teide'}:
        raise ValueError('Faltan movimientos anuales de ambos sentidos.')
    n=a[MAGNITUD_ANUAL].to_numpy(float)
    if not np.isfinite(n).all() or (n<0).any():raise ValueError('Actividad anual ausente o negativa.')
    # La cuota global se aplica por igual a colectivos en la referencia elegida.
    a['personas_no_coche_sentido_anio']=n*ocupacion_coche*(1-fraccion_coche)/fraccion_coche
    a['guaguas_equivalentes_sentido_anio']=a.personas_no_coche_sentido_anio/ocupacion_guagua
    b=recorridos[['origen_id','sentido','terminal_calculo','directa_km']]
    a=a.drop(columns=[c for c in ['terminal_calculo','directa_km'] if c in a]).merge(b,on=['origen_id','sentido'],how='left',validate='many_to_one')
    p=patrones.loc[patrones.patron_id.eq('zona_proxima'),['terminal_calculo','longitud_interior_ida_vuelta_km']]
    a=a.merge(p,on='terminal_calculo',how='left',validate='many_to_one')
    if (not np.isfinite(a[['directa_km','longitud_interior_ida_vuelta_km']]).all().all()
            or a[['directa_km','longitud_interior_ida_vuelta_km']].lt(0).any().any()):
        raise ValueError('Faltan distancias de acceso o visita; no asignar cero.')
    totals=a.groupby('sentido').personas_no_coche_sentido_anio.sum()
    if not np.isclose(totals.iloc[0],totals.iloc[1],rtol=1e-12,atol=1e-8):
        raise ValueError('Subida y regreso no conservan las visitas representadas.')
    a['longitud_referencia_sentido_km']=a.directa_km+a.longitud_interior_ida_vuelta_km/2
    a['vehiculo_km_comunes_anio']=a.guaguas_equivalentes_sentido_anio*a.longitud_referencia_sentido_km
    a['factor_hot_referencia_mj_km']=factor_mj_km
    a['energia_comun_mwh_anio']=a.vehiculo_km_comunes_anio*factor_mj_km/3600
    a['alcance_comun']='Guaguas equivalentes de visitas modelizadas; TITSA/excursiones agregadas, no oferta GTFS o inventario medido; sin vacíos adicionales identificados'
    return a


def completar_totales_representados(comparacion, *, comun_mwh_anio, complemento_mwh_anio=None):
    """Sumar K igual sin/con y distinguir el ámbito representado del ampliado.

    Un complemento desconocido NO se sustituye por cero. El porcentaje del
    ámbito ampliado solo existe cuando ese complemento se ha estimado y justificado.
    """
    for value in [comun_mwh_anio]+([] if complemento_mwh_anio is None else [complemento_mwh_anio]):
        if isinstance(value,(bool,np.bool_)) or not np.isfinite(value) or value<0:
            raise ValueError('Consumo común negativo o no finito.')
    _claves(comparacion,['alternativa_procedencia'],'Comparación')
    cols=['sin_subtotal_hot_identificado_mwh_anio','con_subtotal_ampliado_ensayo_mwh_anio','diferencia_condicionada_transporte_mwh_anio']
    if (comparacion.empty or not np.isfinite(comparacion[cols]).all().all()
            or not np.allclose(comparacion[cols[0]]-comparacion[cols[1]],comparacion[cols[2]],rtol=1e-12,atol=1e-8)):
        raise ValueError('La comparación base no concilia; un cambio neto adicional requiere ambos consumos.')
    x=comparacion.copy(deep=True)
    x['consumo_comun_estimado_mwh_anio']=comun_mwh_anio
    x['sin_total_ambito_representado_mwh_anio']=x[cols[0]]+comun_mwh_anio
    x['con_total_ambito_representado_mwh_anio']=x[cols[1]]+comun_mwh_anio
    denominator=x.sin_total_ambito_representado_mwh_anio
    x['porcentaje_reduccion_ambito_representado']=np.nan
    good=denominator>0
    x.loc[good,'porcentaje_reduccion_ambito_representado']=100*x.loc[good,cols[2]]/denominator[good]
    x['consumo_comun_complementario_mwh_anio']=complemento_mwh_anio if complemento_mwh_anio is not None else np.nan
    x['sin_total_ambito_ampliado_mwh_anio']=np.nan
    x['con_total_ambito_ampliado_mwh_anio']=np.nan
    x['porcentaje_reduccion_ambito_ampliado']=np.nan
    if complemento_mwh_anio is not None:
        x['sin_total_ambito_ampliado_mwh_anio']=x.sin_total_ambito_representado_mwh_anio+complemento_mwh_anio
        x['con_total_ambito_ampliado_mwh_anio']=x.con_total_ambito_representado_mwh_anio+complemento_mwh_anio
        den=x.sin_total_ambito_ampliado_mwh_anio
        pos=den>0
        x.loc[pos,'porcentaje_reduccion_ambito_ampliado']=100*x.loc[pos,cols[2]]/den[pos]
    x['alcance_totales']='Totales estimados de las visitas representadas, no inventario exhaustivo de toda circulación del Parque; complemento desconocido conservado'
    x['cumplimiento_acreditado']=False
    return x


def balance_periodo_pareado(coches, comunes, guaguas):
    """Exigir misma demanda, periodo y unidad antes de comparar sin/con.

    Los coches posteriores son el objetivo de transferencia; si la oferta no
    lo atiende, no publico total con actuación ni ahorro. Los componentes
    conocidos quedan visibles y el consumo común se cuenta una vez por lado.
    """
    keys=['periodo_id','alternativa_procedencia']
    _claves(coches,keys,'Coches del periodo')
    _claves(comunes,['periodo_id'],'Servicios comunes del periodo')
    _claves(guaguas,['periodo_id'],'Oferta del periodo')
    if coches.empty or comunes.empty or guaguas.empty:
        raise ValueError('No comparar tablas vacías.')
    for t in [coches,comunes,guaguas]:
        if not {'demanda_referencia_id','unidad_periodo'}<=set(t) or t[['demanda_referencia_id','unidad_periodo']].isna().any().any():
            raise ValueError('Falta identificación de demanda o unidad de periodo.')
    if not (set(coches.periodo_id)==set(comunes.periodo_id)==set(guaguas.periodo_id)):
        raise ValueError('Escenarios de periodos distintos o incompletos.')
    x=coches.merge(comunes,on='periodo_id',validate='many_to_one',suffixes=('_coches','_comunes'))
    x=x.merge(guaguas.rename(columns={'demanda_referencia_id':'demanda_referencia_id_guaguas','unidad_periodo':'unidad_periodo_guaguas'}),on='periodo_id',validate='many_to_one')
    for f in ['demanda_referencia_id','unidad_periodo']:
        if not x[f+'_coches'].eq(x[f+'_comunes']).all() or not x[f+'_coches'].eq(x[f+'_guaguas']).all():
            raise ValueError('No mezclar demanda, periodo o unidad entre sin/con.')
    if not x.unidad_periodo_coches.isin(['dia','anio']).all():
        raise ValueError('Unidad de periodo no reconocida.')
    fields=['coches_sin_mwh_periodo','coches_con_objetivo_mwh_periodo','alimentacion_otros_mwh_periodo',
            'servicios_comunes_sin_mwh_periodo','servicios_comunes_con_mwh_periodo','guaguas_con_contraste_mwh_periodo']
    if not np.isfinite(x[fields]).all().all() or x[fields].lt(0).any().any():
        raise ValueError('Componentes ausentes, negativos o no finitos.')
    if x.oferta_suficiente.isna().any() or not x.oferta_suficiente.map(lambda z:isinstance(z,(bool,np.bool_))).all():
        raise ValueError('El estado de capacidad debe ser explícito.')
    x['demanda_referencia_id']=x.demanda_referencia_id_coches
    x['unidad_periodo']=x.unidad_periodo_coches
    x['sin_ambito_representado_mwh_periodo']=x.coches_sin_mwh_periodo+x.servicios_comunes_sin_mwh_periodo
    x['con_componentes_objetivo_conocidos_mwh_periodo']=(x.coches_con_objetivo_mwh_periodo+x.alimentacion_otros_mwh_periodo+
        x.servicios_comunes_con_mwh_periodo+x.guaguas_con_contraste_mwh_periodo)
    valid=x.oferta_suficiente
    x['con_ambito_representado_mwh_periodo']=x.con_componentes_objetivo_conocidos_mwh_periodo.where(valid)
    x['saldo_pareado_mwh_periodo']=x.sin_ambito_representado_mwh_periodo-x.con_ambito_representado_mwh_periodo
    x['porcentaje_ambito_representado']=np.where(valid&x.sin_ambito_representado_mwh_periodo.gt(0),
        100*x.saldo_pareado_mwh_periodo/x.sin_ambito_representado_mwh_periodo,np.nan)
    x['energia_adicional_necesaria_fuera_catalogo_mwh_periodo']=np.nan
    x['cumplimiento_acreditado']=False
    return x


def agregar_anio_pareado_2025(diarios, indices, dias_por_tipo):
    """Ponderar las nueve observaciones2025 conservadas, sin descartar faltantes.

    Media de marzo/julio/octubre por tipo y calendario2028 del caso. Si falta
    oferta suficiente en una observación, el total con actuación y el saldo
    anual quedan ausentes; no se ponderan solo los días favorables.
    """
    expected=indices.loc[indices.anio.eq(2025)]
    if (len(expected)!=9 or expected.duplicated(['mes_publicado','tipo_dia_publicado']).any()
            or set(dias_por_tipo)!=set(expected.tipo_dia_publicado)
            or any(not isinstance(v,(int,np.integer)) or isinstance(v,(bool,np.bool_)) or v<1 for v in dias_por_tipo.values())
            or sum(dias_por_tipo.values())!=366):
        raise ValueError('Se requieren nueve observaciones2025 y el calendario2028 completo.')
    _claves(diarios,['matrix_index','alternativa_procedencia'],'Balances diarios')
    if not diarios.unidad_periodo.eq('dia').all():raise ValueError('La ponderación exige balances diarios.')
    rows=[]
    for alt,g in diarios.groupby('alternativa_procedencia'):
        a=g.loc[g.matrix_index.isin(expected.matrix_index)].copy()
        if set(a.matrix_index)!=set(expected.matrix_index):raise ValueError('Falta un balance de2025; no renormalizar.')
        a=a.merge(expected[['matrix_index','tipo_dia_publicado']],on='matrix_index',validate='one_to_one')
        for day,part in a.groupby('tipo_dia_publicado'):
            complete=bool(part.oferta_suficiente.all() and part.con_ambito_representado_mwh_periodo.notna().all())
            rows.append({'alternativa_procedencia':alt,'tipo_dia':day,'observaciones_esperadas':3,
                'observaciones_con_oferta_suficiente':int(part.oferta_suficiente.sum()),'dias_calendario':int(dias_por_tipo[day]),
                'sin_mwh_anio':float(part.sin_ambito_representado_mwh_periodo.mean()*dias_por_tipo[day]),
                'con_mwh_anio':float(part.con_ambito_representado_mwh_periodo.mean()*dias_por_tipo[day]) if complete else np.nan,
                'agregacion_completa':complete})
    detail=pd.DataFrame(rows);total=[]
    for alt,g in detail.groupby('alternativa_procedencia'):
        complete=bool(g.agregacion_completa.all())
        before=float(g.sin_mwh_anio.sum());after=float(g.con_mwh_anio.sum()) if complete else np.nan
        total.append({'alternativa_procedencia':alt,'sin_ambito_representado_mwh_anio':before,
            'con_ambito_representado_mwh_anio':after,'saldo_pareado_mwh_anio':before-after,
            'saldo_pareado_tep_anio':(before-after)/11.63,'agregacion_completa':complete,
            'cumplimiento_acreditado':False})
    return {'por_tipo':detail,'total':pd.DataFrame(total)}


def costes_movilidad_periodo(actividad_coches, actividad_otros, coeficientes):
    """Reaplicar costes físicos unitarios conservados a cantidades del periodo.

    Las cuotas/orígenes, factores y patrones deben ser los de la ejecución que
    originó los coeficientes. La cuota modal/cupo se recalculan antes, nunca se
    escala un saldo anual. La alimentación de otros modos mantiene1coche/persona.
    """
    keys=['origen_id','colectivo','sentido']
    _claves(actividad_coches,['rama',*keys],'Actividad de coches')
    _claves(actividad_otros,keys,'Actividad de otros modos')
    _claves(coeficientes,['alternativa_procedencia','rama',*keys],'Costes unitarios')
    if set(actividad_coches.rama)!={'antes','autorizados','transferidos'}:
        raise ValueError('Falta una rama de coches.')
    for data,field in [(actividad_coches,'recorridos_coche_periodo'),(actividad_otros,'personas_trayecto_periodo')]:
        if not np.isfinite(data[field]).all() or data[field].lt(0).any():
            raise ValueError('Cantidad del periodo ausente o negativa.')
    amounts=actividad_coches.pivot(index=keys,columns='rama',values='recorridos_coche_periodo')
    if amounts.isna().any().any() or not np.allclose(amounts.antes,amounts.autorizados+amounts.transferidos,rtol=1e-12,atol=1e-8):
        raise ValueError('Las ramas de coches no conservan la demanda del periodo.')
    costs=coeficientes.energia_mwh_por_vehiculo_sentido
    if costs.dropna().lt(0).any() or not np.isfinite(costs.dropna()).all():
        raise ValueError('Costes unitarios no válidos.')
    car=actividad_coches.merge(coeficientes,on=['rama',*keys],how='left',validate='one_to_many')
    alternatives=set(coeficientes.alternativa_procedencia)
    if set(car.alternativa_procedencia.dropna())!=alternatives or car.alternativa_procedencia.isna().any():
        raise ValueError('Falta una alternativa de coste.')
    expected=len(actividad_coches)*len(alternatives)
    if len(car)!=expected:raise ValueError('Coeficientes de cobertura incompleta.')
    positive=car.recorridos_coche_periodo.gt(0)
    if car.loc[positive,'energia_mwh_por_vehiculo_sentido'].isna().any():
        raise ValueError('Actividad positiva sin coste unitario; no asignar cero.')
    car['energia_mwh_periodo']=(car.recorridos_coche_periodo*car.energia_mwh_por_vehiculo_sentido).where(positive,0.)
    feed=actividad_otros.merge(coeficientes.loc[coeficientes.rama.eq('transferidos')].drop(columns='rama'),
        on=keys,how='left',validate='one_to_many')
    if len(feed)!=len(actividad_otros)*len(alternatives) or feed.alternativa_procedencia.isna().any():
        raise ValueError('Falta una referencia de alimentación.')
    positive=feed.personas_trayecto_periodo.gt(0)
    if feed.loc[positive,'energia_mwh_por_vehiculo_sentido'].isna().any():
        raise ValueError('Alimentación positiva sin referencia.')
    feed['energia_mwh_periodo']=(feed.personas_trayecto_periodo*feed.energia_mwh_por_vehiculo_sentido).where(positive,0.)
    rows=[]
    for alt,g in car.groupby('alternativa_procedencia'):
        rows.append({'alternativa_procedencia':alt,
            'coches_sin_mwh_periodo':float(g.loc[g.rama.eq('antes'),'energia_mwh_periodo'].sum()),
            'coches_con_objetivo_mwh_periodo':float(g.loc[g.rama.ne('antes'),'energia_mwh_periodo'].sum()),
            'alimentacion_otros_mwh_periodo':float(feed.loc[feed.alternativa_procedencia.eq(alt),'energia_mwh_periodo'].sum())})
    return {'resumen':pd.DataFrame(rows),'detalle_coches':car,'detalle_alimentacion':feed}
