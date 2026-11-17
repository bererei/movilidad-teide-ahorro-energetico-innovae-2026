"""energia: balance. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import numpy as np
import pandas as pd
from movilidad_teide.energia.circulacion import MODOS
from movilidad_teide.energia.balance_condicionado_tipos import MAGNITUD_ANUAL


def calcular_aportes_anuales(reparto, recorridos, clasificacion, factores, velocidades, *, fraccion_coche_alimentador):
    """Aplicar los mismos aportes por clase antes/después a movimientos condicionados.

    Resto longitudes por clase antes de seleccionar extremos para no restar
    factores incompatibles a viajes comunes. No asigno energía al resto sin
    referencia ni convierto estos extremos en flotas reales o límites físicos.
    """
    from movilidad_teide.validacion import _claves
    a = fraccion_coche_alimentador
    if isinstance(a, bool) or not isinstance(a, (float, int)) or not np.isfinite(a) or not 0 <= a <= 1:
        raise ValueError('Fracción de alimentación en coche fuera de [0, 1].')
    _claves(reparto, ['origen_id', 'colectivo', 'sentido'], 'Reparto')
    _claves(recorridos, ['origen_id', 'sentido'], 'Recorridos')
    _claves(clasificacion, ['comparacion_id', 'itinerary_id', 'rol', 'clase_propuesta'], 'Tipologías')
    _claves(factores, ['grupo_servicio', 'modo', 'velocidad_kmh'], 'Factores')
    medidas = ['aporte_conjunto_condicionado_min_mj_km', 'aporte_conjunto_condicionado_max_mj_km']
    f = factores[medidas].to_numpy(dtype=float)
    if np.isinf(f).any() or (f[np.isfinite(f)] < 0).any() or (f[:, 0] > f[:, 1]).any():
        raise ValueError('Aportes por kilómetro negativos, no finitos o desordenados.')
    for speed in velocidades.values():
        if speed is not None and (isinstance(speed, bool) or not np.isfinite(speed) or speed not in set(factores.velocidad_kmh)):
            raise ValueError('Velocidad sin nodo consultado; no interpolar.')
    actividad = pd.to_numeric(reparto[MAGNITUD_ANUAL], errors='raise')
    if (actividad.dropna() < 0).any() or not np.isfinite(actividad.dropna()).all():
        raise ValueError('Actividad anual negativa o no finita.')
    nombres = ['comparacion_calculo_id', 'tipo_representacion_calculo', 'itinerario_referencia_id',
               'itinerario_alimentador_id', 'directa_km', 'alimentador_km']
    # El reparto ya conserva atributos geográficos: usar la tabla física como autoridad.
    datos = reparto.drop(columns=[x for x in nombres if x in reparto]).merge(
        recorridos[['origen_id', 'sentido'] + nombres], on=['origen_id', 'sentido'],
        how='left', validate='many_to_one', indicator=True)
    if datos._merge.ne('both').any():
        raise ValueError('Falta un origen/sentido en los recorridos; no descartarlo.')
    filas = []
    for row in datos.to_dict('records'):
        longitudes = {}
        for rol, campo, largo in [('directa', 'itinerario_referencia_id', 'directa_km'),
                                   ('alimentador', 'itinerario_alimentador_id', 'alimentador_km')]:
            x = clasificacion.loc[clasificacion.comparacion_id.eq(row['comparacion_calculo_id']) &
                clasificacion.itinerary_id.eq(row[campo]) & clasificacion.rol.eq(rol)]
            if not x.empty:
                if (not np.isfinite(x.longitud_clase_km).all() or (x.longitud_clase_km < 0).any() or
                    not np.isfinite(row[largo]) or not np.isclose(x.longitud_clase_km.sum(), row[largo], rtol=0, atol=1e-8)):
                    raise ValueError('Longitud de tipología incompatible con el recorrido original.')
                longitudes[rol] = x.set_index('clase_propuesta').longitud_clase_km.to_dict()
            elif row['tipo_representacion_calculo'] != 'condicional_media_nula':
                raise ValueError('Falta tipología de un componente físico.')
        clases = sorted(set(MODOS) | {c for x in longitudes.values() for c in x})
        for servicio in sorted(factores.grupo_servicio.unique()):
            for clase in clases:
                ld = longitudes.get('directa', {}).get(clase, 0.) if 'directa' in longitudes else np.nan
                la = longitudes.get('alimentador', {}).get(clase, 0.) if 'alimentador' in longitudes else np.nan
                n = row[MAGNITUD_ANUAL]
                neto = n * (ld - a * la)
                x = factores.loc[factores.grupo_servicio.eq(servicio) & factores.modo.eq(MODOS.get(clase)) &
                                 factores.velocidad_kmh.eq(velocidades.get(clase))]
                lo = hi = np.nan
                # Longitud cero documentada no requiere un factor; una ausencia sí.
                if np.isfinite(neto) and ld == 0 and la == 0:
                    lo = hi = 0.
                elif np.isfinite(neto) and len(x) == 1 and x[medidas].notna().all().all():
                    fmin, fmax = x[medidas].iloc[0]
                    lo, hi = (neto * fmin, neto * fmax) if neto >= 0 else (neto * fmax, neto * fmin)
                filas.append({k: row[k] for k in ['origen_id', 'colectivo', 'sentido', 'corredor_fuente',
                    'corredor_calculo', 'tipo_representacion_calculo', 'en_ambito_anual', 'estado_reparto']} | {
                    'grupo_servicio': servicio, 'fraccion_coche_alimentador': a, 'clase_propuesta': clase,
                    MAGNITUD_ANUAL: n, 'longitud_directa_km': ld, 'longitud_alimentador_km': la,
                    'vehiculo_km_directa_anio': n * ld, 'vehiculo_km_alimentador_anio': n * a * la,
                    'vehiculo_km_diferencia_anio': neto, 'aporte_diferencia_menor_mj_anio': lo,
                    'aporte_diferencia_mayor_mj_anio': hi})
    detalle = pd.DataFrame(filas)
    sumables = ['vehiculo_km_directa_anio', 'vehiculo_km_alimentador_anio', 'vehiculo_km_diferencia_anio',
                'aporte_diferencia_menor_mj_anio', 'aporte_diferencia_mayor_mj_anio']
    res = []
    for (servicio, sentido), g in detalle.loc[detalle.en_ambito_anual].groupby(['grupo_servicio', 'sentido']):
        res.append({'grupo_servicio': servicio, 'sentido': sentido, 'fraccion_coche_alimentador': a} |
                   {k: g[k].sum(min_count=len(g)) for k in sumables})
    por_sentido = pd.DataFrame(res)
    total = por_sentido.groupby(['grupo_servicio', 'fraccion_coche_alimentador'], as_index=False)[sumables].agg(
        lambda x: x.sum(min_count=len(x)))
    return {'detalle': detalle, 'por_sentido': por_sentido, 'total_ambito_anual': total}

def comparar_con_lanzaderas(aportes_anuales, lanzaderas):
    """Restar cada referencia completa de Hot identificado de las nuevas lanzaderas.

    No suma tecnologías alternativas, multiplica otra vez por flota o atribuye
    energía cero a componentes del sistema que siguen pendientes.
    """
    from movilidad_teide.validacion import _claves
    _claves(aportes_anuales, ['grupo_servicio', 'fraccion_coche_alimentador'], 'Aportes anuales')
    _claves(lanzaderas, ['referencia_id'], 'Lanzaderas')
    energia = lanzaderas.energia_identificada_mj_anio
    if not np.isfinite(energia).all() or (energia < 0).any():
        raise ValueError('Energía identificada de lanzaderas inválida.')
    x = aportes_anuales.merge(lanzaderas[['referencia_id', 'referencia', 'energia_identificada_mj_anio']], how='cross')
    for sufijo in ['menor', 'mayor']:
        campo = 'diferencia_parcial_' + sufijo
        x[campo + '_mj_anio'] = x['aporte_diferencia_' + sufijo + '_mj_anio'] - x.energia_identificada_mj_anio
        x[campo + '_mwh_anio'] = x[campo + '_mj_anio'] / 3600
        x[campo + '_tep_anio'] = x[campo + '_mj_anio'] / 41868
    x['energia_total_sistema_sin_mj_anio'] = np.nan
    x['energia_total_sistema_con_mj_anio'] = np.nan
    x['ahorro_total_sistema_mj_anio'] = np.nan
    x['ahorro_total_sistema_porcentaje'] = np.nan
    x['alcance'] = ('Diferencia parcial condicionada del ámbito anual de cuatro corredores; '
        'positivo indica menor aporte identificado con actuación, negativo mayor. '
        'No ahorro completo, caso central, límites físicos o intervalo estadístico.')
    return x

def comparar_anualmente_hot(actividad,recorridos,clasificacion,factores,velocidades,energia_buses,*,referencia_acceso):
    """Comparación de contribuciones Hot representadas, con antes y después.

    Dos vectores técnicos (bajo/alto por clase) se aplican idénticos a ambos
    escenarios. No son extremos garantizados del ahorro o una flota fija elegida.
    El aporte de turismos sigue ponderado por stock original, sin renormalizar el
    resto desconocido. Los servicios DGT y referencias interiores son alternativas.
    """
    from movilidad_teide.validacion import _claves
    _claves(actividad,['rama','origen_id','colectivo','sentido'],'Ramas')
    _claves(recorridos,['origen_id','sentido'],'Recorridos')
    _claves(factores,['grupo_servicio','modo','velocidad_kmh'],'Factores')
    _claves(clasificacion,['comparacion_id','itinerary_id','rol','clase_propuesta'],'Tipologías')
    if set(actividad.rama)!={'antes','autorizados','transferidos'}:
        raise ValueError('Falta alguna rama de la comparación.')
    if set(velocidades)!=set(MODOS) or any(v is None for v in velocidades.values()):
        raise ValueError('Condiciones de velocidad incompletas.')
    names=['comparacion_calculo_id','tipo_representacion_calculo','itinerario_referencia_id','itinerario_alimentador_id','directa_km','alimentador_km']
    d=actividad.drop(columns=[c for c in names if c in actividad]).merge(
        recorridos[['origen_id','sentido']+names],on=['origen_id','sentido'],how='left',validate='many_to_one',indicator=True)
    if d._merge.ne('both').any():raise ValueError('Falta una representación geográfica.')
    factors={}
    for service in factores.grupo_servicio.unique():
        for road,mode in MODOS.items():
            x=factores.loc[factores.grupo_servicio.eq(service)&factores.modo.eq(mode)&factores.velocidad_kmh.eq(velocidades[road])]
            if len(x)!=1:raise ValueError('Condición de factor no consultada.')
            pair=x[['aporte_conjunto_condicionado_min_mj_km','aporte_conjunto_condicionado_max_mj_km']].iloc[0].to_numpy(dtype=float)
            if not np.isfinite(pair).all() or (pair<0).any() or pair[0]>pair[1]:
                raise ValueError('Aportes Hot incompletos o incoherentes.')
            factors[service,road]=pair
    rows=[]
    for row in d.loc[d.en_ambito_anual].to_dict('records'):
        n=row[MAGNITUD_ANUAL]
        if not np.isfinite(n) or n<0:raise ValueError('Actividad anual no válida.')
        roles=['directa','alimentador'] if row['rama']=='transferidos' else ['directa']
        for role in roles:
            field='itinerario_referencia_id' if role=='directa' else 'itinerario_alimentador_id'
            length_field='directa_km' if role=='directa' else 'alimentador_km'
            c=clasificacion.loc[clasificacion.comparacion_id.eq(row['comparacion_calculo_id']) &
                clasificacion.itinerary_id.eq(row[field]) & clasificacion.rol.eq(role)]
            if (c.empty or not np.isfinite(c.longitud_clase_km).all() or c.longitud_clase_km.lt(0).any()
                    or not set(c.clase_propuesta)<=set(MODOS)
                    or not np.isclose(c.longitud_clase_km.sum(),row[length_field],rtol=0,atol=1e-8)):
                raise ValueError('Tipologías ausentes o incompatibles con el recorrido.')
            lengths=c.set_index('clase_propuesta').longitud_clase_km.to_dict()
            for service in factores.grupo_servicio.unique():
                for index,label in [(0,'Factores técnicos bajos por clase'),(1,'Factores técnicos altos por clase')]:
                    energy=sum(n*lengths.get(road,0.)*factors[service,road][index] for road in MODOS)
                    rows.append({'origen_id':row['origen_id'],'colectivo':row['colectivo'],'sentido':row['sentido'],
                        'rama':row['rama'],'rol':role,'grupo_servicio':service,'referencia_tecnica_turismos':label,
                        'recorridos_condicionados_anio':n,'energia_hot_aporte_mj_anio':energy})
    detail=pd.DataFrame(rows)
    car=detail.groupby(['grupo_servicio','referencia_tecnica_turismos','rama','rol'],as_index=False).energia_hot_aporte_mj_anio.sum()
    required_bus={'punto','componente','tipo_dia','sentido','referencia_id','energia_mj_anio','vehiculo_km_anio'}
    if not required_bus<=set(energia_buses):raise ValueError('Detalle energético de lanzaderas incompleto.')
    if energia_buses.duplicated(['punto','componente','tipo_dia','sentido','referencia_id']).any():
        raise ValueError('Movimientos de lanzadera duplicados.')
    bus=energia_buses.copy()
    if referencia_acceso not in set(bus.referencia_id):raise ValueError('Referencia de acceso ausente.')
    known=bus.energia_mj_anio.notna()
    if (not np.isfinite(bus.loc[known,'energia_mj_anio']).all() or bus.loc[known,'energia_mj_anio'].lt(0).any()
            or bus.loc[~known,'vehiculo_km_anio'].fillna(0).gt(0).any()):
        raise ValueError('Energía de recorridos identificados inválida; no ocultar actividad positiva sin consumo.')
    components=[];summaries=[]
    for (service,tech),g in car.groupby(['grupo_servicio','referencia_tecnica_turismos']):
        values={(r.rama,r.rol):r.energia_hot_aporte_mj_anio for r in g.itertuples()}
        before=values['antes','directa'];authorized=values['autorizados','directa']
        transferred=values['transferidos','directa'];feeder=values['transferidos','alimentador']
        if not np.isclose(before,authorized+transferred,rtol=1e-12,atol=1e-6):
            raise ValueError('El consumo de coches antes no conserva sus grupos.')
        for interior in sorted(bus.loc[bus.punto.eq('INTERIOR'),'referencia_id'].unique()):
            identity={'grupo_servicio':service,'referencia_tecnica_turismos':tech,
                'referencia_acceso':referencia_acceso,'referencia_interior':interior}
            entries=[('Coches autorizados: recorrido directo',authorized,authorized),
                ('Coches transferidos: directa antes / alimentación después',transferred,feeder)]
            selected=bus.loc[known & ((bus.punto.ne('INTERIOR')&bus.referencia_id.eq(referencia_acceso)) |
                (bus.punto.eq('INTERIOR')&bus.referencia_id.eq(interior)))]
            for area,mask in [('Accesos',selected.punto.ne('INTERIOR')),('Interior',selected.punto.eq('INTERIOR'))]:
                for movement,cmask in [('servicio comercial',selected.componente.str.startswith('comercial')),
                        ('vacíos modelizados',~selected.componente.str.startswith('comercial'))]:
                    amount=selected.loc[mask&cmask,'energia_mj_anio'].sum()
                    entries.append((area+': '+movement,0.,amount))
            after=authorized+feeder+selected.energia_mj_anio.sum()
            difference=before-after
            for component,b,c in entries:
                components.append(identity|{'componente':component,'sin_aporte_hot_mj_anio':b,
                    'con_aporte_hot_mj_anio':c,'diferencia_hot_mj_anio':b-c,
                    'alcance':'Contribución identificada; los cero de nuevas lanzaderas sin actuación describen ausencia del servicio, no datos faltantes'})
            summaries.append(identity|{'sin_subtotal_hot_identificado_mj_anio':before,
                'con_subtotal_hot_identificado_mj_anio':after,'diferencia_hot_identificada_mj_anio':difference,
                'energia_total_sistema_sin_mj_anio':np.nan,'energia_total_sistema_con_mj_anio':np.nan,
                'ahorro_total_energia_final_mj_anio':np.nan,'porcentaje_ahorro_total':np.nan,
                'cumplimiento_minimo_acreditado':None,
                'alcance':'Hot de componentes representados; ensayo modal condicionado y alternativas técnicas, no balance completo o flota central'})
    summary=pd.DataFrame(summaries);comp=pd.DataFrame(components)
    for frame in [summary,comp]:
        for column in list(frame.columns):
            if column.endswith('_mj_anio') and not column.startswith(('energia_total','ahorro_total')):
                for unit,factor in [('kwh',3.6),('mwh',3600.),('tep',41868.)]:
                    frame[column.replace('_mj_anio','_'+unit+'_anio')]=frame[column]/factor
    return {'detalle_coches':detail,'coches_por_rama':car,'componentes':comp,'comparacion':summary}

def impacto_separacion_turismos(actividad, recorridos, clasificacion, perfiles_factores, velocidades):
    """Atribuir la separación entre vectores a grupos de stock, no a probabilidades."""
    from movilidad_teide.validacion import _claves
    _claves(actividad,['rama','origen_id','colectivo','sentido'],'Actividad')
    _claves(recorridos,['origen_id','sentido'],'Recorridos')
    _claves(clasificacion,['comparacion_id','itinerary_id','rol','clase_propuesta'],'Clases')
    _claves(perfiles_factores,['grupo_id','modo','velocidad_kmh'],'Factores de perfil')
    a=actividad.loc[actividad.en_ambito_anual & actividad.rama.eq('transferidos')]
    if a.empty or not np.isfinite(a[MAGNITUD_ANUAL]).all() or a[MAGNITUD_ANUAL].lt(0).any():
        raise ValueError('Actividad transferida no válida.')
    needed=['comparacion_calculo_id','itinerario_referencia_id','itinerario_alimentador_id','directa_km','alimentador_km']
    merged=a.merge(recorridos[['origen_id','sentido']+needed],on=['origen_id','sentido'],how='left',validate='many_to_one',indicator=True)
    if merged._merge.ne('both').any():raise ValueError('Origen sin referencia.')
    exposures=[]
    for row in merged.to_dict('records'):
        for role,itinerary,km,sign in [('directa',row['itinerario_referencia_id'],row['directa_km'],1),
                ('alimentador',row['itinerario_alimentador_id'],row['alimentador_km'],-1)]:
            c=clasificacion.loc[clasificacion.comparacion_id.eq(row['comparacion_calculo_id']) &
                clasificacion.itinerary_id.eq(itinerary) & clasificacion.rol.eq(role)]
            if (c.empty or not np.isfinite(c.longitud_clase_km).all() or c.longitud_clase_km.lt(0).any()
                    or not set(c.clase_propuesta)<=set(MODOS) or not np.isclose(c.longitud_clase_km.sum(),km,atol=1e-8,rtol=0)):
                raise ValueError('Clases incompatibles con longitud del recorrido.')
            for road in MODOS:
                length=c.loc[c.clase_propuesta.eq(road),'longitud_clase_km'].sum()
                exposures.append({'origen_id':row['origen_id'],'colectivo':row['colectivo'],'sentido':row['sentido'],
                    'rol':role,'clase_propuesta':road,'coeficiente_veh_km_anio':sign*row[MAGNITUD_ANUAL]*length})
    exposure=pd.DataFrame(exposures)
    global_byroad=exposure.groupby('clase_propuesta',as_index=False).coeficiente_veh_km_anio.sum()
    rows=[]
    for road,mode in MODOS.items():
        part=perfiles_factores.loc[perfiles_factores.modo.eq(mode)&perfiles_factores.velocidad_kmh.eq(velocidades[road])].copy()
        if part.empty:raise ValueError('Falta una condición de circulación.')
        delta=global_byroad.loc[global_byroad.clase_propuesta.eq(road),'coeficiente_veh_km_anio'].item()
        part['clase_propuesta']=road;part['coeficiente_veh_km_anio']=delta
        part['separacion_aporte_anual_mwh']=delta*part.separacion_referencias_mj_km/3600
        rows.append(part)
    detail=pd.concat(rows,ignore_index=True)
    summary=detail.groupby(['grupo_servicio','familia_copert'],as_index=False).separacion_aporte_anual_mwh.sum()
    summary['alcance']='Separación entre vectores técnicos bajo actividad condicionada; no incertidumbre estadística o contribución de ahorro observada'
    return {'exposicion_por_origen':exposure,'exposicion_por_clase':global_byroad,'detalle':detail,'por_tecnologia':summary}
