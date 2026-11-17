"""energia: interior. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import numpy as np
import pandas as pd
from movilidad_teide.energia.balance_condicionado_tipos import MAGNITUD_ANUAL
from movilidad_teide.energia.balance_condicionado_tipos import SENTIDOS


def recorridos_interiores_coche(paradas, patrones, entradas):
    """Contrastes de visita parcial/múltiple sobre el eje, con regreso a entrada.

    Los destinos se ordenan sobre el eje desde cada extremo. No se suman varias
    excursiones completas ni se añaden ramales a aparcamientos no trazados.
    No estima frecuencias de visita o una ruta observada.
    """
    from movilidad_teide.validacion import _claves
    _claves(paradas,['parada_id'],'Referencias interiores')
    positions=paradas.set_index('parada_id').posicion_m
    if (not np.isfinite(positions).all() or positions.lt(0).any()
            or positions.max()<=positions.min() or len(set(entradas.values()))!=len(entradas)):
        raise ValueError('Eje interior o entradas no válidos.')
    if not set(entradas.values())<=set(positions.index):
        raise ValueError('Entrada sin referencia sobre el eje.')
    if any(positions[p] not in {positions.min(),positions.max()} for p in entradas.values()):
        raise ValueError('Este contraste exige entradas en los extremos del eje.')
    if len({p['patron_id'] for p in patrones})!=len(patrones) or not patrones:
        raise ValueError('Patrones vacíos o repetidos.')
    rows=[]
    for terminal,entry in entradas.items():
        start=float(positions[entry])
        for pattern in patrones:
            ids=pattern['destinos']
            if not ids or len(set(ids))!=len(ids) or not set(ids)<=set(positions.index):
                raise ValueError('Destinos vacíos, repetidos o sin referencia.')
            ordered=sorted(ids,key=lambda p:abs(positions[p]-start))
            chain=[entry,*ordered,entry]
            km=sum(abs(positions[b]-positions[a]) for a,b in zip(chain,chain[1:]))/1000
            rows.append({'terminal_calculo':terminal,'patron_id':pattern['patron_id'],
                'patron_visita':pattern['nombre'],'secuencia_referencias':' → '.join(chain),
                'destinos_distintos':len(ids),'longitud_interior_ida_vuelta_km':km,
                'criterio':'Sobre eje principal, orden desde entrada y regreso a la misma; sin retrocesos adicionales',
                'frecuencia_observada':False,'fraccion_visitas_elegida':np.nan})
    return pd.DataFrame(rows)



def coeficientes_hot_interior_coche(actividad, referencias, recorridos, factores, *, velocidad_rural):
    """Aportes por visita y coeficientes anuales, manteniendo las cuotas ausentes.

    Solo las subidas cuentan visitas; el recorrido interior ya incluye regreso.
    Las ramas antes/autorizados se muestran por separado: su cancelación exige
    igual patrón y frecuencia, que aquí solo se contrastan condicionalmente.
    """
    from movilidad_teide.validacion import _claves
    _claves(actividad,['rama','origen_id','colectivo','sentido'],'Actividad interior')
    _claves(referencias,['origen_id','sentido'],'Terminales')
    _claves(recorridos,['terminal_calculo','patron_id'],'Patrones interiores')
    _claves(factores,['grupo_servicio','modo','velocidad_kmh'],'Factores interiores')
    a=actividad.loc[actividad.en_ambito_anual].copy()
    if set(a.rama)!={'antes','autorizados','transferidos'} or set(a.sentido)!=set(SENTIDOS):
        raise ValueError('Ramas o sentidos incompletos.')
    quantities=a[MAGNITUD_ANUAL].to_numpy(dtype=float)
    if not np.isfinite(quantities).all() or (quantities<0).any():
        raise ValueError('Actividad interior desconocida o negativa.')
    paired=a.pivot(index=['rama','origen_id','colectivo'],columns='sentido',values=MAGNITUD_ANUAL)
    if paired.isna().any().any() or not np.allclose(paired.hacia_teide,paired.desde_teide,rtol=1e-12,atol=1e-8):
        raise ValueError('El contraste requiere regreso emparejado por origen.')
    # La vuelta debe corresponder al mismo extremo, no solo al mismo número.
    geography=a[['origen_id','sentido']].drop_duplicates().merge(
        referencias[['origen_id','sentido','terminal_calculo']],on=['origen_id','sentido'],how='left',validate='one_to_one')
    terminals=geography.pivot(index='origen_id',columns='sentido',values='terminal_calculo')
    if terminals.isna().any().any() or not terminals.hacia_teide.eq(terminals.desde_teide).all():
        raise ValueError('La entrada y el regreso no coinciden por origen.')
    branches=a.pivot(index=['origen_id','colectivo','sentido'],columns='rama',values=MAGNITUD_ANUAL)
    if branches.isna().any().any() or not np.allclose(branches.antes,branches.autorizados+branches.transferidos,rtol=1e-12,atol=1e-8):
        raise ValueError('Las ramas no conservan visitas por origen y sentido.')
    up=a.loc[a.sentido.eq('hacia_teide')].drop(columns='terminal_calculo',errors='ignore').merge(
        referencias[['origen_id','sentido','terminal_calculo']],on=['origen_id','sentido'],how='left',validate='many_to_one')
    if up.terminal_calculo.isna().any() or not set(up.terminal_calculo)<=set(recorridos.terminal_calculo):
        raise ValueError('Falta entrada para alguna actividad representada.')
    if (not np.isfinite(recorridos.longitud_interior_ida_vuelta_km).all()
            or recorridos.longitud_interior_ida_vuelta_km.lt(0).any()):
        raise ValueError('Longitud interior inválida.')
    sets=recorridos.groupby('terminal_calculo').patron_id.agg(set)
    if any(ids!=sets.iloc[0] for ids in sets):
        raise ValueError('Falta un patrón en alguna entrada.')
    visits=up.groupby(['terminal_calculo','rama'],as_index=False)[MAGNITUD_ANUAL].sum()
    p=visits.pivot(index='terminal_calculo',columns='rama',values=MAGNITUD_ANUAL)
    if p.isna().any().any() or not np.allclose(p.antes,p.autorizados+p.transferidos,rtol=1e-12,atol=1e-8):
        raise ValueError('Las visitas no conservan antes = autorizados + transferidos.')
    selected=factores.loc[factores.modo.eq('rural')&factores.velocidad_kmh.eq(velocidad_rural)]
    if set(selected.grupo_servicio)!=set(factores.grupo_servicio):
        raise ValueError('Velocidad rural sin factor para todos los servicios.')
    rows=[]
    for f in selected.to_dict('records'):
        low=f['aporte_conjunto_condicionado_min_mj_km'];high=f['aporte_conjunto_condicionado_max_mj_km']
        if not np.isfinite([low,high]).all() or low<0 or low>high:
            raise ValueError('Referencias Hot por kilómetro incoherentes.')
        for column,label in [('min','Factores técnicos bajos por clase'),('max','Factores técnicos altos por clase')]:
            factor=f['aporte_conjunto_condicionado_'+column+'_mj_km']
            for row in recorridos.merge(visits,on='terminal_calculo',validate='many_to_many').to_dict('records'):
                energy=row['longitud_interior_ida_vuelta_km']*factor
                rows.append(row|{'grupo_servicio':f['grupo_servicio'],'referencia_tecnica_turismos':label,
                    'velocidad_rural_propuesta_kmh':velocidad_rural,'aporte_hot_ponderado_mj_km':factor,
                    'aporte_hot_por_visita_mj':energy,
                    'coeficiente_hot_mwh_anio_por_fraccion_unidad':energy*row[MAGNITUD_ANUAL]/3600})
    detail=pd.DataFrame(rows)
    grouped=detail.groupby(['patron_id','patron_visita','grupo_servicio','referencia_tecnica_turismos','rama'],as_index=False).coeficiente_hot_mwh_anio_por_fraccion_unidad.sum()
    annual=grouped.pivot(index=['patron_id','patron_visita','grupo_servicio','referencia_tecnica_turismos'],columns='rama',values='coeficiente_hot_mwh_anio_por_fraccion_unidad').reset_index().rename_axis(columns=None)
    annual=annual.rename(columns={r:'coeficiente_'+r+'_mwh_anio' for r in ['antes','autorizados','transferidos']})
    if not np.allclose(annual.coeficiente_antes_mwh_anio,annual.coeficiente_autorizados_mwh_anio+annual.coeficiente_transferidos_mwh_anio,rtol=1e-12,atol=1e-8):
        raise ValueError('Los coeficientes interiores no concilian.')
    annual['q_sin_elegida']=np.nan;annual['q_autorizados_elegida']=np.nan
    annual['aporte_interior_sin_mwh_anio']=np.nan;annual['aporte_interior_con_mwh_anio']=np.nan
    annual['ecuacion']='Diferencia interior = q_sin × K_antes − q_autorizados × K_autorizados; cuotas no elegidas'
    annual['alcance']='Aportes de stock representado; no promedio del parque completo ni ahorro total; oferta de lanzaderas ya incluida en D162'
    return {'visitas_por_entrada':visits,'detalle':detail,'coeficientes':annual}

def contraste_umbral_interior_hot(coeficientes, comparacion):
    """Diagnóstico algebraico con MISMA cuota y patrón antes/de autorizados.

    La cuota necesaria para saldo identificado cero no se adopta como previsión.
    Un valor superior a uno se conserva; no se recorta para aparentar viabilidad.
    """
    from movilidad_teide.validacion import _claves
    keys=['grupo_servicio','referencia_tecnica_turismos']
    _claves(coeficientes,keys+['patron_id'],'Coeficientes interiores')
    _claves(comparacion,keys+['referencia_interior','referencia_acceso'],'Comparación Hot')
    if any(coeficientes[c].notna().any() for c in ['q_sin_elegida','q_autorizados_elegida']):
        raise ValueError('Este contraste no admite cuotas adoptadas como si fueran desconocidas.')
    x=coeficientes.merge(comparacion[keys+['referencia_interior','referencia_acceso','diferencia_hot_identificada_mwh_anio']],on=keys,how='outer',indicator=True)
    if x._merge.ne('both').any():raise ValueError('Alternativas técnicas sin correspondencia.')
    x=x.drop(columns='_merge')
    k=x.coeficiente_antes_mwh_anio-x.coeficiente_autorizados_mwh_anio
    base=x.diferencia_hot_identificada_mwh_anio
    if not np.isfinite(k).all() or not np.isfinite(base).all() or k.lt(-1e-8).any():
        raise ValueError('Coeficientes o saldos incompatibles.')
    x['coeficiente_diferencia_con_igual_cuota_mwh_anio']=k
    ratio=np.divide(-base.to_numpy(),k.to_numpy(),out=np.full(len(x),np.nan),where=k.to_numpy()>0)
    x['q_condicionada_para_saldo_identificado_cero']=np.where(base.ge(0),0.,ratio)
    x['condicion_algebraica']=np.select([base.ge(0),k.le(0),x.q_condicionada_para_saldo_identificado_cero.gt(1)],
        ['Saldo identificado ya no negativo; no acredita balance total','Sin respuesta interior en este contraste','Exigiría más del 100 %: no se resuelve con este patrón'],
        default='Se obtiene una condición entre 0 y 100 %; uso y viabilidad no acreditados')
    x['ecuacion_saldo']='Diferencia identificada D162 + q × K_transferidos, solo si q_sin = q_autorizados y mismo patrón'
    x['q_adoptada']=np.nan;x['ahorro_total_energia_final_mwh_anio']=np.nan
    return x
