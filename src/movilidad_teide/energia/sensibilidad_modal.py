"""Sensibilidad condicionada de ocupación y umbrales de consumo común.

Reutiliza el reparto modal y la operación existentes. Las referencias históricas
no constituyen una distribución de 2028 ni límites probables de su ocupación.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from movilidad_teide.operacion.interior import horario_en_paradas, cargas_por_tramos
from movilidad_teide.energia.mezcla import asignar_servicio_colectivos, comparar_mezcla_anual
from movilidad_teide.energia.visita_privada import coeficientes_interior_mezcla
from movilidad_teide.opciones import HYBRID_ID
from movilidad_teide.operacion.criterios_estudio import balance_con_aparcamiento


def referencias_ocupacion(tabla, *, ocupacion_base):
    """Leer el promedio publicado y la reconstrucción anual, sin mezclarlos."""
    fields=['anio_memoria','personas_por_coche','tipo_valor','periodo_datos','paginas_impresas']
    if not set(fields)<=set(tabla) or tabla.anio_memoria.duplicated().any():
        raise ValueError('Referencias de ocupación incompletas o duplicadas.')
    if isinstance(ocupacion_base,bool) or not np.isfinite(ocupacion_base) or ocupacion_base<1:
        raise ValueError('La referencia del Excel no es una ocupación válida.')
    rows=[{'caso_ocupacion':'referencia_excel','ocupacion_coche':float(ocupacion_base),
        'origen_valor':'Propuesta de ocupación del Excel, mantenida como condición',
        'periodo_datos':'Referencia de estudio, no medición2025/2028','paginas_fuente':'Referencias y fundamento del Excel'}]
    for year in [2012,2019]:
        x=tabla.loc[tabla.anio_memoria.eq(year)]
        if len(x)!=1:raise ValueError('Falta una referencia histórica prevista.')
        x=x.iloc[0];n=x.personas_por_coche
        if not np.isfinite(n) or n<1:raise ValueError('La fuente no aporta ocupación válida.')
        rows.append({'caso_ocupacion':f'referencia_{year}','ocupacion_coche':float(n),
            'origen_valor':str(x.tipo_valor),'periodo_datos':str(x.periodo_datos),'paginas_fuente':str(x.paginas_impresas)})
    return pd.DataFrame(rows)


def reasignar_en_horario_conservado(movimientos, pares, objetivos, paradas, *, capacidad,
                                   margen, espera, estancia):
    """Comprobar nueva demanda en las mismas salidas, sin optimizar por rutina.

    Redistribuyo las reservas uniformemente, como en D178. Reconstruyo pasos y
    plazas por tramo; si no caben, el llamante debe planificar refuerzos, nunca
    recortar demanda o conservar un resultado operativo ficticio.
    """
    if not np.isfinite([capacidad,margen,espera,estancia]).all() or capacidad<=0 or margen<0 or espera<margen or estancia<0:
        raise ValueError('Capacidad o condiciones de conexión inválidas.')
    if (objetivos.duplicated(['tipo_dia','punto']).any() or pares.duplicated(['tipo_dia','id_subida']).any()
            or pares.duplicated(['tipo_dia','id_regreso']).any()
            or movimientos.duplicated(['tipo_dia','id_salida']).any()):
        raise ValueError('Objetivos, parejas o movimientos repetidos.')
    keys=['tipo_dia','punto']
    if set(map(tuple,objetivos[keys].to_numpy()))!=set(map(tuple,pares[keys].drop_duplicates().to_numpy())):
        raise ValueError('Falta un objetivo o pareja de regreso.')
    quantities=objetivos.set_index(keys).demanda_lanzadera_condicionada_dia
    if not np.isfinite(quantities).all() or quantities.lt(0).any():raise ValueError('Demanda inválida.')
    parts=[];loads=[]
    for day,block in pares.groupby('tipo_dia'):
        moves=movimientos.loc[movimientos.tipo_dia.eq(day)]
        times=horario_en_paradas(moves,paradas)
        clock=times.set_index(['id_salida','parada_id']).paso_min
        actual=moves.set_index('id_salida')
        reservations=[];fresh=block.copy(deep=True)
        # Los CSV con cadenas llenas pueden traer enteros; la demanda admite fracciones.
        fresh['personas_asignadas_dia_tipo']=fresh.personas_asignadas_dia_tipo.astype(float)
        for point,indexes in fresh.groupby('punto').groups.items():
            qty=float(quantities.loc[day,point])/len(indexes)
            if qty>capacidad+1e-8:raise ValueError('La nueva demanda supera las plazas del horario conservado.')
            fresh.loc[indexes,'personas_asignadas_dia_tipo']=qty
        for x in fresh.itertuples():
            u,b=actual.loc[x.id_subida],actual.loc[x.id_regreso]
            out,back=x.id_interior_ida,x.id_interior_regreso
            wa=clock.loc[out,x.parada_entrada]-u.llegada_min
            wr=b.salida_min-clock.loc[back,x.parada_entrada]
            if (u.destino!=b.origen or min(wa,wr)<margen-1e-8 or max(wa,wr)>espera+1e-8
                    or b.salida_min-u.llegada_min<estancia-1e-8
                    or clock.loc[back,x.parada_destino]<clock.loc[out,x.parada_destino]-1e-8):
                raise ValueError('La nueva reserva no tiene conexión y regreso compatibles.')
            reservations.extend([
                {'id_salida':out,'parada_origen':x.parada_entrada,'parada_destino':x.parada_destino,'personas':x.personas_asignadas_dia_tipo},
                {'id_salida':back,'parada_origen':x.parada_destino,'parada_destino':x.parada_entrada,'personas':x.personas_asignadas_dia_tipo}])
        load=cargas_por_tramos(times,paradas,pd.DataFrame(reservations),capacidad=capacidad)
        if load.personas_asignadas_prueba_dia.gt(capacidad+1e-8).any():raise ValueError('La nueva demanda supera capacidad interior por tramo.')
        parts.append(fresh);loads.append(load.assign(tipo_dia=day,dias_calendario=int(objetivos.loc[objetivos.tipo_dia.eq(day),'dias_calendario'].iloc[0])))
    return {'pares':pd.concat(parts,ignore_index=True),'cargas_tramos':pd.concat(loads,ignore_index=True)}


def comparar_modal_con_interior(actividad, recorridos, tipologias, factores, patrones,
                               energia_buses, valores, propuestas):
    """Recalcular coches e interior en ambas asignaciones del grupo nacional."""
    speeds={q:propuestas['velocidad_turismo_'+q] for q in ['local','convencional','rapida']}
    bases=[];coefficients=[]
    for national in [0,1]:
        label='España no Tenerife: '+('alquiler' if national else 'particular')
        assigned=asignar_servicio_colectivos(actividad,alquiler_fuera=valores['criterio_alquiler_procedencia'],
            residentes=valores['criterio_residentes_coche'],alquiler_espana=national)
        result=comparar_mezcla_anual(assigned,recorridos,tipologias,factores,speeds,energia_buses,referencia_acceso=HYBRID_ID)
        table=result['comparacion'].drop(columns='referencia_tecnica_turismos');unique=table.drop_duplicates().copy()
        if len(unique)*2!=len(table):raise ValueError('La referencia principal no produce un consumo único.')
        bases.append(unique.assign(referencia_tecnica_turismos='Consumo técnico ponderado',alternativa_procedencia=label))
        c=coeficientes_interior_mezcla(assigned,recorridos,patrones,factores,velocidad_rural=speeds['convencional'])['coeficientes']
        coefficients.append(c.assign(alternativa_procedencia=label))
    coef=pd.concat(coefficients,ignore_index=True)
    comparison=balance_con_aparcamiento(pd.concat(bases,ignore_index=True),coef,
        primera=valores['fraccion_visita_primera_zona'],segunda=valores['fraccion_visita_segunda_zona'],
        aparcamiento=valores['aparcamiento_reservado_referencia'])
    bus=float(energia_buses.energia_mj_anio.sum()/3600)
    comparison['energia_lanzaderas_mwh_anio']=bus
    loss=propuestas['perdida_rendimiento_guaguas_contraste']
    comparison['recargo_operativo_contraste_mwh_anio']=bus*(1/(1-loss)-1)
    comparison['saldo_parcial_tras_contraste_mwh_anio']=comparison.diferencia_hot_identificada_mwh_anio-comparison.recargo_operativo_contraste_mwh_anio
    return {'comparacion':comparison,'coeficientes':coef}


def umbrales_consumo_comun(comparacion, *, perdida_rendimiento, objetivo_tep):
    """Resolver factores críticos sin inventar una previsión de renovación.

    g multiplica solo consumos de coches y se aplica por igual antes/después.
    Los horarios y la demanda quedan fijos en cada caso. Los demás cambios C
    permanecen desconocidos: el umbral es del balance parcial, no cumplimiento.
    """
    if (isinstance(perdida_rendimiento,bool) or isinstance(objetivo_tep,bool)
            or not np.isfinite([perdida_rendimiento,objetivo_tep]).all()
            or not 0<=perdida_rendimiento<1 or objetivo_tep<=0):
        raise ValueError('Contraste u objetivo inválidos.')
    fields=['diferencia_hot_identificada_mwh_anio','energia_lanzaderas_mwh_anio']
    if not np.isfinite(comparacion[fields]).all().all() or comparacion.energia_lanzaderas_mwh_anio.lt(0).any():
        raise ValueError('Energías parciales inválidas.')
    d=comparacion[fields].copy(deep=True)
    delta=d.diferencia_hot_identificada_mwh_anio+d.energia_lanzaderas_mwh_anio
    buses=d.energia_lanzaderas_mwh_anio/(1-perdida_rendimiento)
    positive=delta>0
    d['diferencia_coche_mwh_anio']=delta
    d['consumo_lanzaderas_tras_contraste_mwh_anio']=buses
    d['objetivo_tep_anio']=objetivo_tep;d['objetivo_mwh_anio']=objetivo_tep*11.63
    d['saldo_parcial_g_igual_1_mwh_anio']=delta-buses
    d['factor_comun_g_para_equilibrio']=np.where(positive,buses/delta,np.nan)
    d['factor_comun_g_para_objetivo_parcial']=np.where(positive,(buses+objetivo_tep*11.63)/delta,np.nan)
    d['reduccion_comun_max_para_objetivo_parcial']=1-d.factor_comun_g_para_objetivo_parcial
    d['cambio_neto_otros_componentes_C_mwh_anio']=np.nan
    d['coeficiente_g_por_mwh_de_C']=np.where(positive,1/delta,np.nan)
    d['estado_umbral']=np.where(positive,'Umbral condicionado del ámbito parcial; no tasa prevista o cumplimiento',
        'Sin umbral favorable para un factor positivo: diferencia de coche no positiva')
    d['formula']='Saldo parcial(g,C) = g × diferencia_coche − consumo_buses_tras_contraste − C; C sigue desconocido'
    d['ahorro_total_sistema_mwh_anio']=np.nan;d['cumplimiento_acreditado']=False
    return d


def componentes_y_umbrales_balance(comparacion, *, comun_mwh_anio, objetivo_tep):
    """Separar coches/guaguas y calcular límites, sin inventar escenarios futuros.

    Incluyo el coche adicional de otros modos en ambos análisis de consumo.
    La retención de energía evitada es un diagnóstico de atribución, no una
    probabilidad de usar la lanzadera ni un porcentaje observado de coches.
    """
    from movilidad_teide.validacion import comprobar_claves as _claves
    _claves(comparacion,['caso_sensibilidad','alternativa_procedencia'],'Casos de sensibilidad')
    for value,positive in [(comun_mwh_anio,False),(objetivo_tep,True)]:
        if (isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,float,np.integer,np.floating))
                or not np.isfinite(value) or (value<=0 if positive else value<0)):
            raise ValueError('Consumo común u objetivo inválido.')
    columns=['sin_subtotal_hot_identificado_mwh_anio','con_subtotal_hot_identificado_mwh_anio',
             'energia_lanzaderas_mwh_anio','recargo_operativo_contraste_mwh_anio',
             'consumo_ensayo_mwh_anio','cambio_neto_servicios_existentes_sup_mwh_anio',
             'diferencia_condicionada_transporte_mwh_anio']
    if (comparacion.empty or not np.isfinite(comparacion[columns]).all().all()
            or comparacion[columns[:5]].lt(0).any().any()):
        raise ValueError('Faltan energías comparables o hay consumos negativos.')
    x=comparacion.copy(deep=True)
    x['coches_sin_mwh_anio']=x.sin_subtotal_hot_identificado_mwh_anio
    x['coches_con_mwh_anio']=x.con_subtotal_hot_identificado_mwh_anio-x.energia_lanzaderas_mwh_anio+x.consumo_ensayo_mwh_anio
    if x.coches_con_mwh_anio.lt(0).any():raise ValueError('Las guaguas no pueden superar el subtotal con actuación.')
    x['guaguas_con_contraste_mwh_anio']=x.energia_lanzaderas_mwh_anio+x.recargo_operativo_contraste_mwh_anio
    x['diferencia_neta_coches_mwh_anio']=x.coches_sin_mwh_anio-x.coches_con_mwh_anio
    x['energia_coche_evitada_antes_de_otros_modos_mwh_anio']=x.diferencia_neta_coches_mwh_anio+x.consumo_ensayo_mwh_anio
    x['comun_representado_mwh_anio']=float(comun_mwh_anio)
    delta=x.diferencia_neta_coches_mwh_anio
    buses=x.guaguas_con_contraste_mwh_anio
    net=x.cambio_neto_servicios_existentes_sup_mwh_anio
    saldo=delta-buses-net
    if not np.allclose(saldo,x.diferencia_condicionada_transporte_mwh_anio,rtol=1e-12,atol=1e-8):
        raise ValueError('El desglose no reproduce el saldo de partida; posible doble cómputo.')
    target=float(objetivo_tep)*11.63
    x['objetivo_mwh_anio']=target
    x['margen_sobre_objetivo_mwh_anio']=saldo-target
    # No recorto a 0/1: un límite fuera del dominio sigue siendo un resultado adverso.
    x['factor_coche_minimo_para_objetivo']=np.nan
    good=delta>0
    x.loc[good,'factor_coche_minimo_para_objetivo']=(buses[good]+net[good]+target)/delta[good]
    x['reduccion_coche_hasta_objetivo_pct']=100*(1-x.factor_coche_minimo_para_objetivo)
    x['factor_guagua_maximo_para_objetivo']=np.nan
    good=buses>0
    x.loc[good,'factor_guagua_maximo_para_objetivo']=(delta[good]-net[good]-target)/buses[good]
    x['incremento_guagua_hasta_objetivo_pct']=100*(x.factor_guagua_maximo_para_objetivo-1)
    x['fraccion_energia_evitada_minima_para_objetivo']=np.nan
    e=x.energia_coche_evitada_antes_de_otros_modos_mwh_anio;good=e>0
    x.loc[good,'fraccion_energia_evitada_minima_para_objetivo']=(x.loc[good,'consumo_ensayo_mwh_anio']+buses[good]+net[good]+target)/e[good]
    x['cambio_adicional_no_representado_real_mwh_anio']=np.nan
    x['cumplimiento_formal_acreditado']=False
    x['alcance_umbral']='Un límite por vez con oferta fija verificada; combinar variaciones consume el mismo margen. Retención de energía no es cuota modal o escenario operativo.'
    return x


def evaluar_factores_balance(componentes, *, factor_coche, factor_guagua):
    """Evaluar el ámbito representado con la misma oferta y actividad.

    g modifica todos los coches sin/con, incluido el alimentador adicional.
    h modifica las guaguas con el contraste ya incluido; no se suma de nuevo.
    El consumo común se mantiene igual y se cancela en la diferencia.
    """
    for value in [factor_coche,factor_guagua]:
        if (isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,float,np.integer,np.floating))
                or not np.isfinite(value) or value<0):
            raise ValueError('Factor técnico negativo o no finito.')
    fields=['coches_sin_mwh_anio','coches_con_mwh_anio','guaguas_con_contraste_mwh_anio',
            'comun_representado_mwh_anio','cambio_neto_servicios_existentes_sup_mwh_anio','objetivo_mwh_anio']
    if componentes.empty or not np.isfinite(componentes[fields]).all().all():
        raise ValueError('Componentes del ámbito representado incompletos.')
    x=componentes.copy(deep=True)
    x['factor_coche_ensayo']=float(factor_coche);x['factor_guagua_ensayo']=float(factor_guagua)
    x['sin_estimado_mwh_anio']=factor_coche*x.coches_sin_mwh_anio+x.comun_representado_mwh_anio
    x['con_estimado_mwh_anio']=factor_coche*x.coches_con_mwh_anio+factor_guagua*x.guaguas_con_contraste_mwh_anio+x.comun_representado_mwh_anio+x.cambio_neto_servicios_existentes_sup_mwh_anio
    if x.con_estimado_mwh_anio.lt(0).any():raise ValueError('El cambio neto produce un consumo total negativo.')
    x['ahorro_modelizado_mwh_anio']=x.sin_estimado_mwh_anio-x.con_estimado_mwh_anio
    x['ahorro_modelizado_tep_anio']=x.ahorro_modelizado_mwh_anio/11.63
    # La tolerancia numérica solo trata el punto calculado exactamente en el umbral.
    x['supera_minimo_en_caso_calculado']=(x.ahorro_modelizado_mwh_anio>=x.objetivo_mwh_anio)|np.isclose(x.ahorro_modelizado_mwh_anio,x.objetivo_mwh_anio,rtol=0,atol=1e-8)
    x['porcentaje_ambito_representado']=np.nan
    good=x.sin_estimado_mwh_anio>0
    x.loc[good,'porcentaje_ambito_representado']=100*x.loc[good,'ahorro_modelizado_mwh_anio']/x.loc[good,'sin_estimado_mwh_anio']
    return x


def limites_consumo_guaguas(componentes, diagnostico, *, perdida_rendimiento, objetivo_tep):
    """Invertir el balance para definir el consumo admisible, no asignarlo.

    Mantengo coches, demanda y oferta. El techo Hot reserva el contraste externo
    una vez: E_hot_max = (diferencia_coches - cambio_servicios - objetivo)*(1-p).
    Los cocientes entre categorías son diagnósticos; no ventajas híbridas medidas.
    """
    from movilidad_teide.validacion import comprobar_claves as _claves
    for value in [perdida_rendimiento,objetivo_tep]:
        if (isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,float,np.integer,np.floating))
                or not np.isfinite(value)):
            raise ValueError('Pérdida u objetivo no finito o inválido.')
    if not 0<=perdida_rendimiento<1 or objetivo_tep<=0:
        raise ValueError('Pérdida u objetivo fuera de dominio.')
    _claves(componentes,['alternativa_procedencia'],'Componentes de una referencia')
    _claves(diagnostico,['alternativa_procedencia','referencia_id'],'Diagnóstico de categorías')
    fields=['diferencia_neta_coches_mwh_anio','cambio_neto_servicios_existentes_sup_mwh_anio']
    native=['bus_hot_mwh_anio','km_bus_anio']
    if (componentes.empty or diagnostico.empty or not np.isfinite(componentes[fields]).all().all()
            or not np.isfinite(diagnostico[native]).all().all() or diagnostico[native].le(0).any().any()
            or set(componentes.alternativa_procedencia)!=set(diagnostico.alternativa_procedencia)):
        raise ValueError('Componentes, categorías o kilómetros incompletos.')
    rows=[]
    for c in componentes.itertuples():
        d=diagnostico.loc[diagnostico.alternativa_procedencia.eq(c.alternativa_procedencia)]
        if d.km_bus_anio.nunique()!=1:raise ValueError('Las categorías deben comparar la misma oferta y kilómetros.')
        km=float(d.km_bus_anio.iloc[0]);available=c.diferencia_neta_coches_mwh_anio-c.cambio_neto_servicios_existentes_sup_mwh_anio-objetivo_tep*11.63
        hot=available*(1-perdida_rendimiento)
        for z in d.itertuples():
            rows.append({'alternativa_procedencia':c.alternativa_procedencia,'referencia_id':z.referencia_id,
                'categoria_diagnostico':z.categoria,'km_bus_anio':km,'objetivo_tep_anio':objetivo_tep,
                'consumo_total_max_para_objetivo_mwh_anio':available,'hot_max_para_objetivo_mwh_anio':hot,
                'hot_medio_max_para_objetivo_mj_km':hot*3600/km,
                'total_medio_max_para_objetivo_mj_km':available*3600/km,
                'bus_hot_referencia_mwh_anio':z.bus_hot_mwh_anio,
                'variacion_hot_requerida_respecto_diagnostico_pct':100*(hot/z.bus_hot_mwh_anio-1),
                'necesita_reducir_respecto_diagnostico':bool(hot<z.bus_hot_mwh_anio),
                'consumo_compatible_no_negativo_posible':bool(hot>=0),
                'ahorro_real_tecnologia_hibrida_pct':np.nan,
                'alcance':'Techo medio anual ponderado por km comerciales y vacíos, con oferta fija; no factor elegido, porcentaje observado o garantía de vehículo concreto.'})
    return pd.DataFrame(rows)
