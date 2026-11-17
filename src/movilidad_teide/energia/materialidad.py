"""energia: materialidad. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import numpy as np
import pandas as pd
from movilidad_teide.energia.balance_condicionado_tipos import MAGNITUD_ANUAL


def componentes_pendientes():
    """Lista concreta de límites materiales, sin completar ningún consumo con cero."""
    return pd.DataFrame([
        ('Turismos captables de origen coche', 'Aportes Hot parciales condicionados',
         'Referencia modal histórica, retirada de grupos y transporte efectivo sin acreditar; composición visitante y uso pendientes.'),
        ('Resto del parque sin referencia', 'Pendiente; no energía cero',
         '5.772 registros DGT sin referencia y claves sin malla; no se conoce su contribución energética.'),
        ('Nuevas lanzaderas', 'Hot comercial y vacíos modelizados identificados',
         'Accesos: autocar provisional elegido para estudio D157; interior: tres alternativas sin elegir. No sumar tecnologías ni multiplicar por flota otra vez.'),
        ('Cocheras y otros vacíos de lanzaderas', 'Pendiente; no energía cero',
         'Cuantificar o justificar simplificación por su materialidad.'),
        ('Alimentación distinta del coche', 'Pendiente; no energía cero',
         'El extremo sin coche hasta cabecera no supone transporte público gratuito en energía; estudiar actividad incremental.'),
        ('Servicios TITSA existentes y otros modos afectados', 'Pendiente; no cancelación automática',
         'Oferta constante no acredita igual carga/consumo; excursiones y otros vehículos tampoco se suponen comunes sin justificación.'),
        ('Coches no captados, reservas y demanda restante', 'Pendiente; no retirada automática',
         'El cupo global de 500 coches/día no identifica coches eliminados, reparto territorial, visitas canceladas o inducidas.'),
        ('Orígenes sin asignación anual', 'Media territorial conservada; actividad anual ausente',
         'Los orígenes fuera de las cuatro referencias anuales no se eliminan ni se completan con cero.'),
        ('Cobertura de energía final', 'Verificar alcance antes de completar el balance',
         'Contrastar frío, auxiliares y frontera de electricidad/recarga sin sumar dos veces componentes ya incluidos en Hot EC.'),
        ('Método COPERT y validación operativa', 'Limitaciones conservadas',
         'Turismos sin corrección externa de desnivel; guaguas con extremos ±6 % provisionales y error desconocido; MDT norte pendiente del CNIG.')
    ], columns=['componente', 'estado', 'tratamiento'])

def revisar_elecciones_para_cierre(parametros):
    """Agrupar las ausencias del Excel sin adoptar referencias o crear elecciones.

    Las categorías corresponden al flujo actual D157–D159. Una elección pendiente
    nueva debe revisarse explícitamente; no se clasifica como inocua por defecto.
    """
    groups = {
        'Demanda y respuesta al cupo': (
            ['ocupacion_coche','fraccion_captados_coche','transferencia_lanzadera','induccion'],
            'Decisión esencial',
            'Mantener las referencias históricas como condiciones de ensayo; contrastar aforos recientes sin convertir pasos en visitas.',
            'Separar conversión, aceptación de la lanzadera y visitas inducidas; conservar el caso central pendiente.'),
        'Representación de turismos': (
            ['criterio_pesos_turismos','criterio_tamanos_turismos',
             'criterio_categoria_incompleta_turismos','criterio_norma_incompleta_turismos'],
            'Decisión esencial',
            'Proponer criterios DGT/COPERT existentes; conservar servicios A01/B00 separados y factores ausentes sin imputar cero.',
            'Adoptar una representación solo como hipótesis de actividad; justificar o acotar la parte sin referencia, sin renormalizarla.'),
        'Velocidades de turismos': (
            ['velocidad_turismo_local','velocidad_turismo_convencional','velocidad_turismo_rapida'],
            'Decisión esencial',
            'Revisar la propuesta por tipología viaria; usar nodos COPERT consultados y condiciones iguales en tramos comunes.',
            'Justificar las velocidades como hipótesis; no tratarlas como medidas, límites legales o velocidades de guaguas.'),
        'Distribución anual entre orígenes': (
            ['criterio_reparto_territorial_anual'],
            'Decisión esencial',
            'Usar cuotas territoriales existentes dentro de cada corredor fuente/colectivo; conservar toda la demanda representada.',
            'Adoptar o contrastar la hipótesis espacial, sin anualizar las 57 matrices o repartir equitativamente.'),
        'Llegada a cabeceras': (
            ['alimentacion_coche'],
            'Decisión esencial',
            'Conservar el coche hasta cabecera para el grupo condicionado que procede del coche; separar otros modos.',
            'Cuantificar actividad incremental de alternativas antes de atribuirles menor consumo; no suponer transporte gratuito.'),
        'Circulación privada interior': (
            ['fraccion_interior_sin','fraccion_interior_autorizados'],
            'Decisión esencial',
            'Conservar ambas cuotas pendientes y contrastar frecuencias explícitas con los recorridos documentados; no suponer100% o0 de uso real.',
            'Elegir frecuencias justificadas para caso principal; diferenciar regla de autorizados pendiente y comprobar demanda/capacidad interior adicional.'),
        'Criterios de visita y enlace': (
            ['espera_max_lanzadera_min','estancia_min_visita_min'],
            'Revisión operativa',
            'Mantener las referencias del Excel en los contrastes, sin acreditar tiempos útiles de visita.',
            'Distinguir espera, margen, estancia total y ventana en parada; la oferta completa sigue contándose en energía.'),
        'Sensibilidad de funcionamiento de guaguas': (
            ['perdida_rendimiento_guaguas_contraste'],
            'Referencia de sensibilidad, no caso central',
            'Contrastar la referencia FTA2007 sin trasladarla a consumo real del Teide ni sumarla a otra estimación de los mismos auxiliares.',
            'Mantenerla como prueba externa; documentar pérdida de km/unidad e incremento recíproco por km, con límites de aplicabilidad.'),
        'Calendario manual no seleccionado': (
            ['dias_servicio'],
            'Alternativa inactiva',
            'Conservar la ausencia mientras el calendario elegido sea todo el año.',
            'No exigir días manuales para una alternativa no seleccionada.'),
        'Cuotas manuales no seleccionadas': (
            [f'{prefix}_{point}' for prefix in ['cuota','personas'] for point in ['OROTAVA','VILAFLOR','LAGUNA','CHIO']],
            'Alternativa inactiva',
            'Conservar ausencias de cuotas manuales; la propuesta reservada usa distribución derivada y explícita.',
            'Distinguir reparto de aforos del Excel y reparto de la propuesta D157; no son aprobación del cupo por acceso.'),
        'Masa del ensayo externo excluido': (
            ['criterio_tara_turismos','masa_persona_turismo_kg','equipaje_turismo_kg_coche'],
            'Exploración excluida',
            'No activar el ajuste externo de desnivel para completar el cálculo principal.',
            'Una evaluación futura necesita fundamento independiente del saldo; no bloquea COPERT nativo.'),
        'Ocupación de guaguas aforadas': (
            ['ocupacion_guagua_aforo'],
            'Diagnóstico auxiliar',
            'Conservar referencia histórica para contraste de aforos, separada de la carga de las nuevas lanzaderas.',
            'No convertir esta referencia en ocupación actual, carga COPERT o demanda del interior.'),
        'Consumo común fuera de las visitas representadas': (
            ['consumo_comun_complementario_mwh_anio'],
            'Total del ámbito ampliado pendiente',
            'Mantener desconocido el consumo común no representado; no sustituirlo por cero.',
            'Estimar y justificar el complemento antes de publicar totales o porcentaje de un ámbito ampliado; no bloquea el porcentaje del ámbito representado.'),
        'Referencia de guaguas comunes': (
            ['criterio_guaguas_comunes'],
            'Decisión esencial',
            'Revisar la categoría y condiciones COPERT existentes como aproximación del consumo común.',
            'Elegir con motivo una referencia compatible antes de calcular el consumo común; no identificarla como flota medida.'),
        'Diseño detallado de reservas': (
            ['permanencia_min','franja_reserva_min'],
            'Diseño posterior del sistema',
            'Conservar duración/franja no definidas; la prueba actual vincula salidas y regresos concretos.',
            'Su ausencia no impide sumar la oferta existente; no acredita reservas reales o cumplimiento en cada fecha.')
    }
    bykey = {}
    for group,(keys,status,proposal,action) in groups.items():
        for key in keys:
            if key in bykey: raise ValueError('Clasificación repetida: '+key)
            bykey[key] = (group,status,proposal,action)
    rows = parametros['parametros']
    if len({x['id'] for x in rows}) != len(rows):
        raise ValueError('Parámetros repetidos.')
    values={p['id']:p['valor_utilizado'] for p in rows}
    pending=[]
    for p in rows:
        if p['valor_utilizado'] is not None:
            continue
        if p['id'] not in bykey:
            raise ValueError('Parámetro pendiente sin revisión: '+p['id'])
        group,status,proposal,action=bykey[p['id']]
        if p['id']=='dias_servicio' and values.get('calendario')!='Todo el año':
            status='Decisión esencial'
            proposal='Revisar los días de servicio: el calendario anual no está seleccionado.'
            action='Completar o justificar el calendario antes de anualizar.'
        if p['id'].startswith('cuota_') and values.get('reparto_cupo')=='Porcentajes manuales':
            status='Decisión esencial'
            proposal='Completar las cuotas de la alternativa manual seleccionada.'
            action='Comprobar cuotas no negativas y suma uno antes de aplicar el cupo.'
        if p['id'] in {'fraccion_interior_sin','fraccion_interior_autorizados'} and values.get('referencia_guagua_interior') is not None:
            group='Contraste interior anterior a respuesta de Luis'
            status='Antecedente sustituido'
            proposal='Conservar las cuotas globales históricas sin adoptarlas; el modelo actual separa acceso al aparcamiento y movilidad entre zonas.'
            action='Usar primera/segunda zona y aparcamiento en la revisión D172; no exigir resolver estas dos cuotas para el caso actual.'
        # Mostrar propuesta y estado en campos distintos evita activarla al leer.
        pending.append({'id':p['id'],'parametro':p['parametro'],'unidad':p['unidad'],
            'bloque_de_revision':group,'tratamiento_actual':status,'valor_efectivo':None,
            'referencia_en_excel':p['propuesta']['valor'],'fuente_referencia':p['propuesta']['fuente'],
            'propuesta_para_revision':proposal,'criterio_para_cerrar':action,
            'eleccion_activada_por_esta_revision':False})
    return pd.DataFrame(pending)

def umbral_aporte_para_equilibrio(comparacion):
    """Cociente energético, no multiplicador validado de pasajeros o coches.

    Mantiene fija la oferta. Si aumenta la demanda puede requerir más servicio,
    de modo que este cociente por sí solo no demuestra una solución viable.
    """
    x=comparacion.copy(deep=True)
    for extremo in ['menor','mayor']:
        aporte=x['aporte_diferencia_'+extremo+'_mj_anio']
        x['multiplicador_aporte_'+extremo+'_para_equilibrio']=x.energia_identificada_mj_anio/aporte.where(aporte>0)
    return x

def margen_para_componentes_pendientes(comparaciones, *, objetivo_tep_anio):
    """Invertir el saldo parcial sin asignar cero al resto del sistema.

    Defino C = (consumo con - consumo sin) de todo lo aún no cuantificado o
    corregido. A_total = A_parcial - C. Para alcanzar T se necesita C <= A_parcial-T.
    La desigualdad no determina C, la flota central o el cumplimiento. Los dos
    extremos siguen siendo alternativas técnicas, nunca un intervalo estadístico.
    """
    if (isinstance(objetivo_tep_anio,bool) or not np.isfinite(objetivo_tep_anio)
            or objetivo_tep_anio<=0):
        raise ValueError('Objetivo de ahorro positivo requerido.')
    keys=['grupo_servicio','referencia_id','fraccion_coche_alimentador']
    if comparaciones.empty or comparaciones.duplicated(keys).any():
        raise ValueError('Comparaciones ausentes o repetidas.')
    numbers=['aporte_diferencia_menor_mj_anio','aporte_diferencia_mayor_mj_anio',
        'energia_identificada_mj_anio','diferencia_parcial_menor_mj_anio','diferencia_parcial_mayor_mj_anio']
    if not np.isfinite(comparaciones[numbers].to_numpy(dtype=float)).all():
        raise ValueError('Saldo parcial incompleto o no finito; no inventar márgenes.')
    x=comparaciones.copy(deep=True)
    if (x.aporte_diferencia_menor_mj_anio.gt(x.aporte_diferencia_mayor_mj_anio).any()
            or x.energia_identificada_mj_anio.lt(0).any()
            or not x.fraccion_coche_alimentador.between(0,1).all()):
        raise ValueError('Alternativas o energía incoherentes.')
    total_columns=[c for c in x if c.startswith(('energia_total_sistema','ahorro_total_sistema'))]
    if total_columns and x[total_columns].notna().any().any():
        raise ValueError('Este control corresponde al saldo parcial, no a un balance completo.')
    target=float(objetivo_tep_anio)*41868.
    x['objetivo_tep_anio']=float(objetivo_tep_anio)
    x['objetivo_mwh_anio']=target/3600
    for side in ['menor','mayor']:
        partial=x['aporte_diferencia_'+side+'_mj_anio']-x.energia_identificada_mj_anio
        if not np.allclose(partial,x['diferencia_parcial_'+side+'_mj_anio'],rtol=1e-12,atol=1e-7):
            raise ValueError('El saldo no concilia con sus aportes.')
        x['limite_C_para_objetivo_'+side+'_mwh_anio']=(partial-target)/3600
    x['cambio_neto_pendiente_C_mwh_anio']=np.nan
    x['cumplimiento_objetivo_acreditado']=None
    x['ahorro_total_sistema_mj_anio']=np.nan
    x['interpretacion_limite_C']=(
        'Condición algebraica C <= saldo parcial - objetivo; C es consumo con menos sin de lo pendiente. '
        'Un límite negativo exige ahorro adicional neto; uno positivo permite ese incremento como máximo '
        'solo bajo la alternativa técnica evaluada. C sigue desconocido; no es margen garantizado o cumplimiento.')
    return x

def desglosar_resto_sin_referencia(diagnostico):
    """Separar el resto real de lo representado previamente o por contraste.

    Las fracciones son del stock por servicio. No acreditan actividad visitante
    ni energía cubierta. Un registro previo no necesita otra referencia nueva.
    """
    required={'grupo_id','grupo_servicio','vehiculos','representado_en_contraste',
        'referencia_condicionada_disponible','estado_incompletos'}
    if (not required<=set(diagnostico) or diagnostico.empty
            or diagnostico.grupo_id.duplicated().any()):
        raise ValueError('Diagnóstico de perfiles ausente o repetido.')
    d=diagnostico.copy(deep=True)
    n=pd.to_numeric(d.vehiculos,errors='raise')
    if not np.isfinite(n).all() or (n<=0).any() or not np.equal(n,np.floor(n)).all():
        raise ValueError('Conteos de stock no válidos.')
    flags=['representado_en_contraste','referencia_condicionada_disponible']
    if any(not d[k].isin([True,False]).all() for k in flags):
        raise ValueError('Estados de cobertura no booleanos.')
    if (d[flags[0]] & d[flags[1]]).any():
        raise ValueError('Un perfil no puede contarse dos veces.')
    d['incluido_en_resto']=~d[flags[0]] & ~d[flags[1]]
    rest=d.loc[d.incluido_en_resto].copy()
    if rest.estado_incompletos.isna().any():
        raise ValueError('Falta el motivo del resto.')
    by_reason=rest.groupby(['grupo_servicio','estado_incompletos'],as_index=False,dropna=False).vehiculos.sum()
    totals=[]
    for service,g in d.groupby('grupo_servicio',sort=True):
        total=int(g.vehiculos.sum())
        previous=int(g.loc[g[flags[0]],'vehiculos'].sum())
        new=int(g.loc[g[flags[1]],'vehiculos'].sum())
        pending=int(g.loc[g.incluido_en_resto,'vehiculos'].sum())
        if previous+new+pending!=total:raise ValueError('La cobertura no conserva el stock.')
        totals.append({'grupo_servicio':service,'vehiculos_stock':total,
            'vehiculos_representados_previamente':previous,'vehiculos_con_referencia_condicionada':new,
            'vehiculos_aun_sin_referencia':pending,'fraccion_stock_sin_referencia':pending/total,
            'fraccion_energia_sin_referencia':np.nan})
    return {'resto':rest,'por_motivo_servicio':by_reason,'resumen':pd.DataFrame(totals)}


def coeficientes_energia_resto(reparto,recorridos,clasificacion,cobertura,*,fraccion_coche_alimentador):
    """Cuantificar actividad que multiplica factores desconocidos, sin elegirlos.

    Bajo el criterio de igual kilometraje dentro del servicio (H009),
    K = cuota_stock_resto * recorridos_condicionados * (km_directa-a*km_alimentador).
    El aporte desconocido sería suma(K_clase * factor_resto_clase). No es cero
    ni un factor supuesto; K conserva desvíos negativos y condiciones por clase.
    """
    from movilidad_teide.validacion import _claves
    a=fraccion_coche_alimentador
    if isinstance(a,bool) or not np.isfinite(a) or not 0<=a<=1:
        raise ValueError('Fracción de alimentación inválida.')
    _claves(reparto,['origen_id','colectivo','sentido'],'Reparto')
    _claves(recorridos,['origen_id','sentido'],'Recorridos')
    _claves(clasificacion,['comparacion_id','itinerary_id','rol','clase_propuesta'],'Tipologías')
    _claves(cobertura,['grupo_servicio'],'Cobertura')
    if (cobertura.vehiculos_stock.le(0).any() or cobertura.vehiculos_aun_sin_referencia.lt(0).any()
            or cobertura.vehiculos_aun_sin_referencia.gt(cobertura.vehiculos_stock).any()
            or not np.isfinite(cobertura[['vehiculos_stock','vehiculos_aun_sin_referencia']]).all().all()):
        raise ValueError('Cobertura de stock incoherente.')
    classes=['local','convencional','rapida']
    if not set(clasificacion.clase_propuesta)<=set(classes):
        raise ValueError('Clase viaria no revisada.')
    names=['comparacion_calculo_id','tipo_representacion_calculo','itinerario_referencia_id',
        'itinerario_alimentador_id','directa_km','alimentador_km']
    d=reparto.drop(columns=[c for c in names if c in reparto]).merge(
        recorridos[['origen_id','sentido']+names],on=['origen_id','sentido'],validate='many_to_one',how='left',indicator=True)
    if d._merge.ne('both').any():raise ValueError('Falta la representación de algún origen.')
    rows=[]
    for r in d.to_dict('records'):
        n=r[MAGNITUD_ANUAL]
        if pd.notna(n) and (not np.isfinite(n) or n<0):raise ValueError('Actividad condicionada inválida.')
        lengths={}
        for role,field,span in [('directa','itinerario_referencia_id','directa_km'),
                ('alimentador','itinerario_alimentador_id','alimentador_km')]:
            x=clasificacion.loc[clasificacion.comparacion_id.eq(r['comparacion_calculo_id']) &
                clasificacion.itinerary_id.eq(r[field]) & clasificacion.rol.eq(role)]
            if len(x):
                if (not np.isfinite(x.longitud_clase_km).all() or x.longitud_clase_km.lt(0).any()
                        or not np.isclose(x.longitud_clase_km.sum(),r[span],rtol=0,atol=1e-8)):
                    raise ValueError('Tipologías incompatibles con los recorridos.')
                lengths[role]=x.set_index('clase_propuesta').longitud_clase_km.to_dict()
            elif r['tipo_representacion_calculo']=='condicional_media_nula':
                lengths[role]=None
            else:raise ValueError('Faltan tipologías; no imputar cero.')
        for service in cobertura.to_dict('records'):
            weight=service['vehiculos_aun_sin_referencia']/service['vehiculos_stock']
            for road in classes:
                direct=lengths['directa'].get(road,0.) if lengths['directa'] is not None else np.nan
                feed=lengths['alimentador'].get(road,0.) if lengths['alimentador'] is not None else np.nan
                coefficient=weight*n*(direct-a*feed)
                rows.append({k:r[k] for k in ['origen_id','colectivo','sentido','en_ambito_anual']}|{
                    'grupo_servicio':service['grupo_servicio'],'clase_propuesta':road,
                    'fraccion_stock_sin_referencia':weight,'coeficiente_veh_km_condicionados_anio':coefficient,
                    'factor_resto_mj_km':np.nan,'aporte_energetico_resto_mj_anio':np.nan})
    detail=pd.DataFrame(rows)
    grouped=detail.loc[detail.en_ambito_anual].groupby(['grupo_servicio','sentido','clase_propuesta'],as_index=False).agg(
        coeficiente_veh_km_condicionados_anio=('coeficiente_veh_km_condicionados_anio',lambda x:x.sum(min_count=len(x))))
    grouped['factor_resto_mj_km']=np.nan;grouped['aporte_energetico_resto_mj_anio']=np.nan
    total=grouped.groupby('grupo_servicio',as_index=False).agg(
        coeficiente_veh_km_condicionados_anio=('coeficiente_veh_km_condicionados_anio',lambda x:x.sum(min_count=len(x))))
    total['respuesta_mwh_anio_por_incremento_comun_de_1_mj_km']=total.coeficiente_veh_km_condicionados_anio/3600
    total['factor_resto_elegido']=False;total['aporte_energetico_resto_mwh_anio']=np.nan
    total['alcance']='Coeficiente algebraico bajo reparto condicionado y pesos de stock H009; no consumo previsto o cuota energética'
    return {'detalle':detail,'por_clase_sentido':grouped,'resumen':total}

def exposicion_lanzaderas_materialidad(vehiculos, horarios):
    """Medir vehículos-día, km y horas en movimiento del horario conservado.

    Una guagua activa cuenta una vez por fecha, con independencia de cuántas
    expediciones realiza. Las horas no representan motor encendido o auxiliares.
    """
    from movilidad_teide.validacion import _claves
    keys = ['tipo_dia', 'punto', 'vehiculo_id']
    _claves(vehiculos, keys, 'Guaguas activas')
    _claves(horarios, keys + ['id_salida'], 'Salidas por vehículo')
    if vehiculos.empty or horarios.empty:
        raise ValueError('Oferta ausente para calcular exposición.')
    v = vehiculos.copy(deep=True)
    h = horarios.copy(deep=True)
    if any(frame[keys].isna().any().any() for frame in [v, h]):
        raise ValueError('Identificación de oferta incompleta.')
    for field in ['km_por_recorrido', 'tiempo_recorrido_min', 'dias_calendario']:
        x = h[field].to_numpy(dtype=float)
        if not np.isfinite(x).all() or (x < 0).any():
            raise ValueError('Recorridos o calendario inválidos: ' + field)
    if (h.dias_calendario.le(0).any()
            or not h.dias_calendario.eq(np.floor(h.dias_calendario)).all()
            or h.groupby('tipo_dia').dias_calendario.nunique().ne(1).any()):
        raise ValueError('Calendario incoherente por tipo de día.')
    distance = v.kilometros_dia.to_numpy(dtype=float)
    if not np.isfinite(distance).all() or (distance < 0).any():
        raise ValueError('Kilómetros de vehículos no válidos.')
    by_vehicle = h.groupby(keys, as_index=False).agg(
        km_horario_dia=('km_por_recorrido', 'sum'),
        minutos_movimiento_dia=('tiempo_recorrido_min', 'sum'),
        dias_calendario=('dias_calendario', 'first'))
    joined = v[keys + ['kilometros_dia']].merge(
        by_vehicle, on=keys, how='outer', validate='one_to_one', indicator=True)
    if (joined._merge.ne('both').any()
            or not np.allclose(joined.kilometros_dia, joined.km_horario_dia, rtol=1e-12, atol=1e-8)):
        raise ValueError('La relación vehículos/horarios no concilia.')
    joined['vehiculos_dia_anio'] = joined.dias_calendario
    joined['vehiculo_km_identificados_anio'] = joined.km_horario_dia * joined.dias_calendario
    joined['horas_movimiento_anio'] = joined.minutos_movimiento_dia * joined.dias_calendario / 60
    summary = joined.groupby(['tipo_dia', 'punto'], as_index=False).agg(
        vehiculos_activos=('vehiculo_id', 'size'), dias_calendario=('dias_calendario', 'first'),
        vehiculos_dia_anio=('vehiculos_dia_anio', 'sum'),
        vehiculo_km_identificados_anio=('vehiculo_km_identificados_anio', 'sum'),
        horas_movimiento_anio=('horas_movimiento_anio', 'sum'))
    summary['km_cochera_reales_dia_vehiculo'] = np.nan
    summary['incremento_auxiliar_real_mj_km'] = np.nan
    return summary

def coeficientes_cocheras_auxiliares(exposicion, factores_guaguas, referencias, *, referencia_acceso, velocidad):
    """Respuesta unitaria; cochera rural llana/vacía solo como referencia técnica.

    d es la suma diaria de ida y regreso a cochera por guagua activa, no distancia
    por expedición. u es energía final ADICIONAL no incluida ya en Hot, en MJ/km.
    Se conserva el término d*u: los kilómetros adicionales también podrían tener
    ese consumo. No se eligen d/u ni se supone que el factor describe la cochera.
    """
    from movilidad_teide.validacion import _claves
    _claves(exposicion, ['tipo_dia', 'punto'], 'Exposición')
    identity = ['Category', 'Fuel', 'Segment', 'Euro Standard']
    _claves(referencias, ['referencia_id'], 'Identidades COPERT')
    _claves(factores_guaguas, identity + ['rural_speed_kmh', 'load_fraction', 'slope_class_pct'], 'Factores de guagua')
    if 'INTERIOR' not in set(exposicion.punto) or referencia_acceso not in set(referencias.referencia_id):
        raise ValueError('Falta interior o referencia de acceso.')
    numeric = exposicion[['vehiculos_activos', 'dias_calendario', 'vehiculos_dia_anio', 'vehiculo_km_identificados_anio']].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (numeric < 0).any():
        raise ValueError('Exposición no finita o negativa.')
    if not np.allclose(exposicion.vehiculos_activos * exposicion.dias_calendario, exposicion.vehiculos_dia_anio):
        raise ValueError('Vehículos-día incompatibles con flota/calendario.')
    f = factores_guaguas.loc[factores_guaguas.rural_speed_kmh.eq(velocidad)
        & factores_guaguas.load_fraction.eq(0) & factores_guaguas.slope_class_pct.eq(0)]
    ref = referencias.merge(f[identity + ['hot_ec_mj_per_km']], on=identity, how='left', validate='one_to_one')
    if (ref.hot_ec_mj_per_km.isna().any() or not np.isfinite(ref.hot_ec_mj_per_km).all()
            or ref.hot_ec_mj_per_km.lt(0).any()):
        raise ValueError('Falta factor nativo para vacío, velocidad y pendiente explícitos.')
    lookup = ref.set_index('referencia_id').hot_ec_mj_per_km.to_dict()
    rows = []
    for interior in referencias.referencia_id:
        for row in exposicion.to_dict('records'):
            reference = interior if row['punto'] == 'INTERIOR' else referencia_acceso
            days = row['vehiculos_dia_anio']
            rows.append(row | {'referencia_acceso': referencia_acceso, 'referencia_interior': interior,
                'referencia_copert_del_punto': reference, 'factor_vacio_llano_hot_mj_km': lookup[reference],
                'velocidad_referencia_kmh': velocidad, 'pendiente_referencia_pct': 0., 'carga_referencia': 0.,
                'K_cochera_mwh_por_km_diario_vehiculo': days * lookup[reference] / 3600,
                'K_auxiliar_mwh_por_mj_km': row['vehiculo_km_identificados_anio'] / 3600,
                'K_interaccion_d_u': days / 3600,
                'alcance': 'Respuesta unitaria, no distancia/consumo real o referencia conservadora; cochera sin trazado'})
    detail = pd.DataFrame(rows)
    sums = ['vehiculos_dia_anio', 'vehiculo_km_identificados_anio',
        'K_cochera_mwh_por_km_diario_vehiculo', 'K_auxiliar_mwh_por_mj_km', 'K_interaccion_d_u']
    total = detail.groupby(['referencia_acceso', 'referencia_interior'], as_index=False)[sums].sum()
    total['d_cochera_elegida'] = np.nan
    total['u_auxiliar_elegido'] = np.nan
    total['energia_cocheras_auxiliares_real_mwh_anio'] = np.nan
    total['ecuacion_incremento'] = 'd × K_cochera + u × K_auxiliar + d × u × K_interaccion; d/u desconocidos'
    return {'detalle': detail, 'resumen': total}

def integrar_coeficientes_materialidad(comparacion, interior, lanzaderas):
    """Reunir la ecuación Hot completa en sus incógnitas, sin inventar un central.

    C_otros = consumo con menos sin de lo pendiente restante: puede tener ambos
    signos. No se da por cancelado al mostrar la respuesta de una sola pieza.
    """
    from movilidad_teide.validacion import _claves
    keys = ['grupo_servicio', 'referencia_tecnica_turismos']
    bus_keys = ['referencia_acceso', 'referencia_interior']
    _claves(comparacion, keys + bus_keys, 'Comparación anual')
    _claves(interior, keys + ['patron_id'], 'Coeficientes interiores')
    _claves(lanzaderas, bus_keys, 'Coeficientes de lanzaderas')
    # Este bloque reúne coeficientes; una elección real requiere otro cálculo.
    for table, fields in [(interior, ['q_sin_elegida', 'q_autorizados_elegida']),
            (lanzaderas, ['d_cochera_elegida', 'u_auxiliar_elegido'])]:
        if any(table[field].notna().any() for field in fields if field in table):
            raise ValueError('No presentar elecciones adoptadas como incógnitas de materialidad.')
    x = comparacion.merge(interior, on=keys, how='outer', indicator=True)
    if x._merge.ne('both').any():
        raise ValueError('Alternativas de interior sin correspondencia.')
    x = x.drop(columns='_merge').merge(lanzaderas, on=bus_keys, how='left', validate='many_to_one', indicator=True)
    if x._merge.ne('both').any():
        raise ValueError('Alternativas de lanzaderas sin correspondencia.')
    x = x.drop(columns='_merge')
    columns = ['diferencia_hot_identificada_mwh_anio', 'coeficiente_antes_mwh_anio',
        'coeficiente_autorizados_mwh_anio', 'coeficiente_transferidos_mwh_anio',
        'K_cochera_mwh_por_km_diario_vehiculo', 'K_auxiliar_mwh_por_mj_km', 'K_interaccion_d_u']
    if not np.isfinite(x[columns].to_numpy(dtype=float)).all():
        raise ValueError('Faltan coeficientes o saldo identificado.')
    coefficients = [c for c in columns if c != 'diferencia_hot_identificada_mwh_anio']
    if x[coefficients].lt(0).any().any() or not np.allclose(
            x.coeficiente_antes_mwh_anio - x.coeficiente_autorizados_mwh_anio,
            x.coeficiente_transferidos_mwh_anio, rtol=1e-12, atol=1e-8):
        raise ValueError('Coeficientes no conservan las ramas.')
    x['respuesta_por_punto_porcentual_q_sin_mwh_anio'] = x.coeficiente_antes_mwh_anio / 100
    x['respuesta_por_punto_porcentual_q_autorizados_mwh_anio'] = -x.coeficiente_autorizados_mwh_anio / 100
    x['respuesta_por_punto_porcentual_cuota_igual_mwh_anio'] = x.coeficiente_transferidos_mwh_anio / 100
    x['cambio_neto_otros_C_mwh_anio'] = np.nan
    x['ahorro_total_hot_mwh_anio'] = np.nan
    x['ecuacion_conjunta'] = ('A = A_D162 + q_sin × K_antes − q_autorizados × K_autorizados '
        '− d × K_cochera − u × K_auxiliar − d × u × K_interaccion − C_otros')
    x['lectura'] = ('Cuotas/d/u/C_otros sin elegir. La respuesta de una unidad no es incertidumbre estimada, '
        'ahorro previsto o presupuesto garantizado. No sumar patrones, servicios DGT o tecnologías alternativas.')
    return x

def comprobar_cocheras_en_extremos(vehiculos, horarios, bases_por_servicio, *, criterio):
    """Distancia base-extremo nula por hipótesis, tras comprobar circulación.

    Permite intercambiar guaguas entre los dos extremos interiores si las
    cantidades estacionadas se conservan para todos los tipos de día. No exige
    que cada identificador vuelva al mismo extremo ni omite un traslado necesario.
    """
    if criterio != 'Cabeceras de acceso y extremos del interior':
        raise ValueError('La hipótesis de estacionamiento no está adoptada.')
    # Reutilizo la conciliación de salidas/km; no sustituyo sus controles.
    exposicion_lanzaderas_materialidad(vehiculos, horarios)
    keys = ['tipo_dia', 'punto', 'vehiculo_id']
    if not set(horarios.punto) <= set(bases_por_servicio):
        raise ValueError('Servicio sin bases de estacionamiento definidas.')
    if horarios[['origen', 'destino', 'salida_min', 'llegada_min']].isna().any().any():
        raise ValueError('Extremos u horas de circulación incompletos.')
    times = horarios[['salida_min', 'llegada_min']].to_numpy(dtype=float)
    if not np.isfinite(times).all() or horarios.llegada_min.lt(horarios.salida_min).any():
        raise ValueError('Horas no válidas para identificar inicio y final.')
    rows = []
    for group, h in horarios.groupby(keys):
        day, point, vehicle = group
        h = h.sort_values(['salida_min', 'llegada_min'])
        if (h.salida_min.iloc[1:].to_numpy() < h.llegada_min.iloc[:-1].to_numpy() - 1e-9).any():
            raise ValueError('Una guagua tiene recorridos solapados.')
        if not np.array_equal(h.destino.iloc[:-1].to_numpy(), h.origen.iloc[1:].to_numpy()):
            raise ValueError('La circulación contiene un traslado no representado.')
        first, last = h.iloc[0], h.iloc[-1]
        bases = bases_por_servicio[point]
        if not bases or first.origen not in bases or last.destino not in bases:
            raise ValueError('Falta traslado entre base y extremo del servicio.')
        registered = vehiculos.loc[vehiculos.tipo_dia.eq(day) & vehiculos.punto.eq(point)
            & vehiculos.vehiculo_id.eq(vehicle), 'terminal_inicial'].item()
        if registered != first.origen:
            raise ValueError('La base inicial contradice la circulación conservada.')
        rows.append({'tipo_dia': day, 'punto': point, 'vehiculo_id': vehicle,
            'base_inicio_modelizada': first.origen, 'base_final_modelizada': last.destino,
            'primera_salida_min': first.salida_min, 'ultima_llegada_min': last.llegada_min,
            'dias_calendario': int(first.dias_calendario),
            'km_adicional_cochera_dia': 0., 'km_adicional_cochera_anio': 0.,
            'aporte_hot_cochera_adicional_mj_anio': 0.,
            'estado': 'Cero por hipótesis de base en extremo y circulación comprobada; no medición o ausencia de maniobras/parado'})
    detail = pd.DataFrame(rows)
    balances = []
    for (day, point), g in detail.groupby(['tipo_dia', 'punto']):
        for base in sorted(bases_por_servicio[point]):
            initial = int(g.base_inicio_modelizada.eq(base).sum())
            final = int(g.base_final_modelizada.eq(base).sum())
            if initial != final:
                raise ValueError('Estacionamiento desequilibrado: requiere revisar reposición o flota.')
            balances.append({'tipo_dia': day, 'punto': point, 'base_modelizada': base,
                'guaguas_inicio': initial, 'guaguas_final': final, 'equilibrio_comprobado': True})
    balance = pd.DataFrame(balances)
    if balance.groupby(['punto', 'base_modelizada']).guaguas_inicio.nunique().gt(1).any():
        raise ValueError('La distribución cambia entre tipos de día; revisar el traslado entre jornadas.')
    return {'detalle': detail, 'equilibrio': balance}

def incremento_por_perdida_rendimiento(perdida):
    """Convertir pérdida de km/unidad de combustible a incremento por km."""
    if isinstance(perdida, (bool, np.bool_)) or not np.isfinite(perdida) or not 0 <= perdida < 1:
        raise ValueError('La pérdida de rendimiento debe estar entre0 incluido y1 excluido.')
    return float(perdida / (1 - perdida))

def sensibilidad_interior_y_operacion(comparacion, componentes, coeficientes_interior, *, perdida_rendimiento):
    """Contrastar el dominio completo de cuotas y un recargo operativo externo.

    No estima cuotas o sobrecostes reales. El recargo se aplica una sola vez al
    Hot de todas las nuevas guaguas identificadas, sin multiplicar por flota.
    No se suma a u u otra estimación de los mismos auxiliares/ralentí.
    """
    from movilidad_teide.validacion import _claves
    ratio = incremento_por_perdida_rendimiento(perdida_rendimiento)
    keys = ['grupo_servicio', 'referencia_tecnica_turismos', 'referencia_acceso', 'referencia_interior']
    _claves(comparacion, keys, 'Comparación Hot')
    _claves(componentes, keys + ['componente'], 'Componentes Hot')
    _claves(coeficientes_interior, keys[:2] + ['patron_id'], 'Patrones interiores')
    expected = {'Accesos: servicio comercial', 'Accesos: vacíos modelizados',
        'Interior: servicio comercial', 'Interior: vacíos modelizados'}
    bus = componentes.loc[componentes.componente.isin(expected)].copy()
    for _, group in bus.groupby(keys):
        if set(group.componente) != expected:
            raise ValueError('Falta un componente de lanzaderas.')
    numbers = ['sin_aporte_hot_mwh_anio', 'con_aporte_hot_mwh_anio']
    if (not np.isfinite(bus[numbers].to_numpy(dtype=float)).all() or bus[numbers].lt(0).any().any()
            or not bus.sin_aporte_hot_mwh_anio.eq(0).all()):
        raise ValueError('No se puede aplicar el recargo a servicios ausentes o comunes desconocidos.')
    amounts = bus.groupby(keys, as_index=False).con_aporte_hot_mwh_anio.sum().rename(
        columns={'con_aporte_hot_mwh_anio': 'hot_nuevas_guaguas_mwh_anio'})
    x = comparacion.merge(amounts, on=keys, how='outer', indicator=True, validate='one_to_one')
    if x._merge.ne('both').any():
        raise ValueError('Alternativas y componentes de guagua sin correspondencia.')
    x = x.drop(columns='_merge').merge(coeficientes_interior, on=keys[:2], how='outer', indicator=True)
    if x._merge.ne('both').any():
        raise ValueError('Patrones y comparaciones sin correspondencia.')
    x = x.drop(columns='_merge')
    wanted = ['diferencia_hot_identificada_mwh_anio', 'hot_nuevas_guaguas_mwh_anio',
        'coeficiente_antes_mwh_anio', 'coeficiente_autorizados_mwh_anio', 'coeficiente_transferidos_mwh_anio']
    if not np.isfinite(x[wanted].to_numpy(dtype=float)).all():
        raise ValueError('Faltan contribuciones para la sensibilidad.')
    if (x[['coeficiente_antes_mwh_anio','coeficiente_autorizados_mwh_anio','coeficiente_transferidos_mwh_anio']].lt(0).any().any()
            or not np.allclose(x.coeficiente_antes_mwh_anio-x.coeficiente_autorizados_mwh_anio,
                x.coeficiente_transferidos_mwh_anio,rtol=1e-12,atol=1e-8)):
        raise ValueError('Los patrones interiores no conservan las ramas.')
    rows = []
    for label, loss, surcharge in [('Hot nativo sin recargo externo', 0., 0.),
            ('Recargo exploratorio FTA2007, sin calibración local', perdida_rendimiento, ratio)]:
        g = x.copy(deep=True)
        g['contraste_operativo'] = label
        g['perdida_rendimiento_contrastada'] = loss
        g['incremento_consumo_contrastado'] = surcharge
        g['recargo_exploratorio_guaguas_mwh_anio'] = g.hot_nuevas_guaguas_mwh_anio * surcharge
        g['saldo_identificado_sin_circuitos_mwh_anio'] = g.diferencia_hot_identificada_mwh_anio - g.recargo_exploratorio_guaguas_mwh_anio
        base = g.saldo_identificado_sin_circuitos_mwh_anio
        k = g.coeficiente_transferidos_mwh_anio
        # q=0/q=1 son extremos del dominio, no porcentajes previstos o elegidos.
        g['saldo_dominio_cuota_igual_q0_mwh_anio'] = base
        g['saldo_dominio_cuota_igual_q1_mwh_anio'] = base + k
        quotient = np.divide(-base.to_numpy(), k.to_numpy(), out=np.full(len(g), np.nan), where=k.to_numpy()>0)
        g['q_para_saldo_identificado_cero_con_cuota_igual'] = np.where(base.ge(0), 0., quotient)
        g['lectura_cuota_igual'] = np.select([base.ge(0),(base+k).lt(0),k.le(0)],
            ['Saldo identificado no negativo en este dominio; otros consumos pendientes',
             'Saldo identificado negativo en todo este dominio',
             'Sin respuesta interior en este contraste'], default='El signo depende de la cuota; no es una previsión')
        g['saldo_dominio_cuotas_independientes_min_mwh_anio'] = base - g.coeficiente_autorizados_mwh_anio
        g['saldo_dominio_cuotas_independientes_max_mwh_anio'] = base + g.coeficiente_antes_mwh_anio
        g['fracciones_interiores_elegidas'] = np.nan
        g['incremento_operativo_real_estimado'] = np.nan
        g['ahorro_total_hot_mwh_anio'] = np.nan
        g['alcance_sensibilidad'] = ('Dominio matemático de cuotas y recargo externo de referencia; no intervalo probabilístico, '
            'caso central, límite físico o ahorro total. Resto Hot desconocido, no cancelado.')
        rows.append(g)
    return pd.concat(rows, ignore_index=True)
