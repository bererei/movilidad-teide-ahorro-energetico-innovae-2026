"""Actividad interior privada: ambos escenarios y frecuencias explícitas."""
from copy import deepcopy
import numpy as np
import pandas as pd
from movilidad_teide.energia.interior import coeficientes_hot_interior_coche
from movilidad_teide.energia.compatibilidad import verificar_representacion_tecnica
from movilidad_teide.energia.balance_condicionado_tipos import MAGNITUD_ANUAL
from movilidad_teide.energia.referencia import NUEVOS as REFERENCIA_NUEVOS, verificar_referencia
from movilidad_teide.opciones import PARTICULAR, ALQUILER
from movilidad_teide.opciones import PATRONES_INTERIORES as PATRONES


NUEVOS = {'patron_visita_coche_interior','fraccion_interior_sin','fraccion_interior_autorizados'}


def verificar_entradas_interior(anterior, actual):
    old={p['id']:p for p in anterior['parametros']};new={p['id']:p for p in actual['parametros']}
    if set(old)&NUEVOS or not NUEVOS<=set(new)-set(old):
        raise ValueError('Faltan las adiciones de circulación interior.')
    if new['patron_visita_coche_interior']['valor_utilizado'] not in PATRONES:
        raise ValueError('Patrón interior sin elegir.')
    for key in ['fraccion_interior_sin','fraccion_interior_autorizados']:
        value=new[key]['valor_utilizado']
        if value is not None and (not np.isfinite(value) or not 0<=value<=1):
            raise ValueError('Fracción interior no válida.')
    projected=deepcopy(actual)
    projected['parametros']=[p for p in projected['parametros'] if p['id'] not in NUEVOS]
    projected['elecciones_todos_los_casos']=[p for p in projected['elecciones_todos_los_casos'] if p['id'] not in NUEVOS]
    validator=verificar_representacion_tecnica if REFERENCIA_NUEVOS<=set(old) else verificar_referencia
    return validator(anterior,projected)|{'criterios_interiores_aplicados_aparte':sorted(NUEVOS)}


def ampliar_patron_proximo(recorridos):
    """Elegir el más corto de los dos núcleos conocidos, sin cuota observada."""
    keys=['terminal_calculo','patron_id']
    if recorridos.empty or recorridos.duplicated(keys).any():raise ValueError('Patrones vacíos o duplicados.')
    if (not np.isfinite(recorridos.longitud_interior_ida_vuelta_km).all()
            or recorridos.longitud_interior_ida_vuelta_km.lt(0).any()):
        raise ValueError('Distancias interiores inválidas.')
    candidates=recorridos.loc[recorridos.patron_id.isin(['zona_parador','zona_teleferico'])]
    if not candidates.groupby('terminal_calculo').size().eq(2).all() or set(candidates.terminal_calculo)!=set(recorridos.terminal_calculo):
        raise ValueError('Falta un núcleo documentado en alguna entrada.')
    picked=candidates.sort_values(['longitud_interior_ida_vuelta_km','patron_id']).groupby('terminal_calculo',sort=False).head(1).copy()
    picked['patron_fuente']=picked.patron_id;picked['patron_id']='zona_proxima'
    picked['patron_visita']='Una zona: núcleo próximo entre Parador/Roques y Teleférico'
    picked['criterio']='Menor distancia entre dos núcleos documentados; no comportamiento observado o hipótesis conservadora del ahorro'
    if 'zona_proxima' in set(recorridos.patron_id):raise ValueError('La ampliación ya existe.')
    return pd.concat([recorridos.assign(patron_fuente=recorridos.patron_id),picked],ignore_index=True)


def coeficientes_interior_mezcla(actividad_asignada, referencias, recorridos, factores, *, velocidad_rural):
    """Conservar mezcla por colectivo y contar la visita una vez, desde subida."""
    if not set(actividad_asignada.servicio_asignado)<={PARTICULAR,ALQUILER}:
        raise ValueError('Servicio desconocido.')
    visits=[];details=[]
    for service in [PARTICULAR,ALQUILER]:
        a=actividad_asignada.copy(deep=True)
        a[MAGNITUD_ANUAL]=a[MAGNITUD_ANUAL].where(a.servicio_asignado.eq(service),0.)
        f=factores.loc[factores.grupo_servicio.eq(service)]
        if f.empty or not np.allclose(f.aporte_conjunto_condicionado_min_mj_km,f.aporte_conjunto_condicionado_max_mj_km,rtol=1e-12):
            raise ValueError('El consumo principal debe ser único por condición.')
        result=coeficientes_hot_interior_coche(a,referencias,recorridos,f,velocidad_rural=velocidad_rural)
        z=result['detalle'].drop(columns='referencia_tecnica_turismos')
        unique=z.drop_duplicates()
        if len(unique)*2!=len(z):raise ValueError('Las dos etiquetas históricas no representan el mismo factor.')
        details.append(unique)
        visits.append(result['visitas_por_entrada'].assign(grupo_servicio=service))
    detail=pd.concat(details,ignore_index=True)
    annual=detail.groupby(['patron_id','patron_visita','rama'],as_index=False).coeficiente_hot_mwh_anio_por_fraccion_unidad.sum()
    annual=annual.pivot(index=['patron_id','patron_visita'],columns='rama',values='coeficiente_hot_mwh_anio_por_fraccion_unidad').reset_index().rename_axis(columns=None)
    annual=annual.rename(columns={k:'K_'+k+'_mwh_anio' for k in ['antes','autorizados','transferidos']})
    if not np.allclose(annual.K_antes_mwh_anio,annual.K_autorizados_mwh_anio+annual.K_transferidos_mwh_anio,rtol=1e-12,atol=1e-8):
        raise ValueError('No se conserva antes = autorizados + transferidos.')
    unit=detail[['terminal_calculo','patron_id','patron_visita','grupo_servicio','longitud_interior_ida_vuelta_km',
        'velocidad_rural_propuesta_kmh','aporte_hot_ponderado_mj_km','aporte_hot_por_visita_mj']].drop_duplicates()
    unit['aporte_hot_por_visita_kwh']=unit.aporte_hot_por_visita_mj/3.6
    return {'coeficientes':annual,'detalle':detail,'visitas':pd.concat(visits,ignore_index=True),'por_visita':unit}


def evaluar_interior(comparacion, coeficientes, *, fraccion_sin, fraccion_autorizados, patron_id=None):
    """Sumar el cambio interior; las fracciones son condiciones, no mediciones."""
    if any(x is None or not np.isfinite(x) or not 0<=x<=1 for x in [fraccion_sin,fraccion_autorizados]):
        raise ValueError('Elegir ambas fracciones entre cero y uno; Pendiente no es cero.')
    keys=['alternativa_procedencia','referencia_acceso','referencia_interior']
    if comparacion.duplicated(keys).any() or coeficientes.duplicated(['alternativa_procedencia','patron_id']).any():
        raise ValueError('Alternativas o coeficientes duplicados.')
    for c in ['K_antes_mwh_anio','K_autorizados_mwh_anio','K_transferidos_mwh_anio']:
        if not np.isfinite(coeficientes[c]).all() or coeficientes[c].lt(0).any():raise ValueError('Coeficiente inválido.')
    if not np.allclose(coeficientes.K_antes_mwh_anio,coeficientes.K_autorizados_mwh_anio+coeficientes.K_transferidos_mwh_anio,rtol=1e-12,atol=1e-8):
        raise ValueError('Los coeficientes no conservan antes = autorizados + transferidos.')
    c=coeficientes if patron_id is None else coeficientes.loc[coeficientes.patron_id.eq(patron_id)]
    if c.empty or set(c.alternativa_procedencia)!=set(comparacion.alternativa_procedencia):
        raise ValueError('Falta un patrón o alternativa de procedencia.')
    result=comparacion.merge(c,on='alternativa_procedencia',how='left',validate='many_to_many')
    result['fraccion_interior_sin']=fraccion_sin;result['fraccion_interior_autorizados']=fraccion_autorizados
    result['aporte_interior_sin_mwh_anio']=fraccion_sin*result.K_antes_mwh_anio
    result['aporte_interior_con_mwh_anio']=fraccion_autorizados*result.K_autorizados_mwh_anio
    result['diferencia_interior_mwh_anio']=result.aporte_interior_sin_mwh_anio-result.aporte_interior_con_mwh_anio
    result['diferencia_previa_sin_interior_mwh_anio']=result.diferencia_hot_identificada_mwh_anio
    for scenario,source in [('sin','aporte_interior_sin_mwh_anio'),('con','aporte_interior_con_mwh_anio')]:
        result[scenario+'_subtotal_hot_identificado_mj_anio']+=result[source]*3600
    result['diferencia_hot_identificada_mj_anio']=result.sin_subtotal_hot_identificado_mj_anio-result.con_subtotal_hot_identificado_mj_anio
    for stem in ['sin_subtotal_hot_identificado','con_subtotal_hot_identificado','diferencia_hot_identificada']:
        for unit,divisor in [('kwh',3.6),('mwh',3600.),('tep',41868.)]:result[stem+'_'+unit+'_anio']=result[stem+'_mj_anio']/divisor
    result['alcance']='Condición explícita de circulación privada interior; no frecuencia observada o ahorro total'
    result['capacidad_extra_por_autorizados_validada']=False
    return result
