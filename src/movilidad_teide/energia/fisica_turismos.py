"""Revisión física y propuestas de consumo en pendiente, separadas de COPERT.

Las funciones distinguen trabajo mecánico, diagnóstico de una regresión publicada
y ensayo de un balance incremental sin calibración para la flota visitante.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def trabajo_gravitatorio_por_tonelada(segmentos, *, gravedad_m_s2=9.81):
    """Calcular m·g·Δh para una tonelada; nunca convertirlo en combustible."""
    required={'segment_id','length_m','slope_pct','elevation_start_m','elevation_end_m'}
    if (not required<=set(segmentos) or segmentos.empty or segmentos.segment_id.isna().any()
            or segmentos.segment_id.duplicated().any()):
        raise ValueError('Segmentos físicos ausentes o con identificadores no únicos.')
    values=segmentos[['length_m','slope_pct','elevation_start_m','elevation_end_m']].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:,0]<=0).any() or not np.isfinite(gravedad_m_s2) or gravedad_m_s2<=0:
        raise ValueError('Longitudes, pendientes, cotas o gravedad no válidas.')
    # La consulta conserva el signo del desnivel original.
    dh=values[:,3]-values[:,2]
    if not np.allclose(100*dh/values[:,0],values[:,1],rtol=0,atol=1e-8):
        raise ValueError('Pendiente, longitud y desnivel no son coherentes; no se corrigen los originales.')
    out=segmentos.copy(deep=True)
    out['trabajo_gravitatorio_mj_por_t']=1000*gravedad_m_s2*dh/1e6
    out['trabajo_ascenso_mj_por_t']=out.trabajo_gravitatorio_mj_por_t.clip(lower=0)
    out['energia_liberada_descenso_mj_por_t']=(-out.trabajo_gravitatorio_mj_por_t).clip(lower=0)
    out['trabajo_gravitatorio_kwh_por_t']=out.trabajo_gravitatorio_mj_por_t/3.6
    out['alcance_trabajo']='Energía mecánica por tonelada; no combustible, electricidad recuperada o ahorro'
    return out


def diagnosticar_ece_upm(segmentos, factor_base_mj_km, poder_calorifico_mj_kg, *, combustible='Diesel'):
    """Reproducir ECE, UPM2015, ec.4-2 p.42: solo diagnóstico de transferencia.

    La ecuación se ajustó a un Peugeot406 diésel1997, con medias de500 m.
    Se conserva todo valor negativo y la pendiente como fracción en la consulta.
    No se adopta la regresión, no se recorta y no se presupone su dominio para Teide.
    """
    if combustible!='Diesel':raise ValueError('La fuente ECE revisada corresponde a un vehículo diésel, no a otras tecnologías.')
    if (not np.isfinite(factor_base_mj_km) or factor_base_mj_km<=0
            or not np.isfinite(poder_calorifico_mj_kg) or poder_calorifico_mj_kg<=0):
        raise ValueError('Factor base o poder calorífico ausente/no positivo.')
    out=trabajo_gravitatorio_por_tonelada(segmentos)
    base_g_km=factor_base_mj_km*1000/poder_calorifico_mj_kg
    raw_g_km=-0.859161+866.936*(out.slope_pct.to_numpy()/100)+1.02279*base_g_km
    out['factor_base_mj_km_diagnostico']=factor_base_mj_km
    out['ece_bruta_g_km_diagnostico']=raw_g_km
    out['ece_bruta_mj_km_diagnostico']=raw_g_km*poder_calorifico_mj_kg/1000
    out['ece_resultado_negativo']=raw_g_km<0
    out['ece_desvio_plano_mj_km_diagnostico']=(-0.859161+1.02279*base_g_km)*poder_calorifico_mj_kg/1000-factor_base_mj_km
    out['ece_adoptada']=False
    out['limite_transferencia']='Vehículo/masa/ciclo, COPERT4 y agregación500 m distintos; dominio empírico Teide no acreditado'
    return out


def ensayar_balance_incremental_no_regenerativo(segmentos, base, parametros, *, combustible):
    """Ensayar una propuesta física que reproduce el caso sin desnivel.

    E_propuesta[MJ] = E_min + max(E_base-E_min+Wg/eta,0).
    Wg[MJ] = m[kg]·g[m/s²]·Δh[m]/1.000.000.
    Masa total, eficiencia incremental y mínimo necesitan fuente y calibración;
    no tienen valores por defecto. No es una ecuación nativa COPERT ni una
    reproducción literal de los modelos bibliográficos. No admite híbridos.
    """
    if combustible not in {'Petrol','Diesel'}:
        raise ValueError('La propuesta no representa regeneración ni otras tecnologías.')
    out=trabajo_gravitatorio_por_tonelada(segmentos)
    required_base={'segment_id','factor_base_hot_ec_mj_km'}
    required_parameters={'segment_id','masa_total_kg','eficiencia_incremental','consumo_minimo_mj_km',
                         'fuente_masa','fuente_eficiencia','fuente_minimo'}
    for table,required in [(base,required_base),(parametros,required_parameters)]:
        if (not required<=set(table) or table.segment_id.isna().any() or table.segment_id.duplicated().any()
                or set(table.segment_id)!=set(out.segment_id)):
            raise ValueError('Faltan o sobran parámetros/base con identificación única para cada segmento.')
    b=base.set_index('segment_id').loc[out.segment_id]
    p=parametros.set_index('segment_id').loc[out.segment_id]
    for name in ['fuente_masa','fuente_eficiencia','fuente_minimo']:
        if any(not isinstance(v,str) or not v.strip() for v in p[name]):
            raise ValueError('Falta justificar '+name)
    values=p[['masa_total_kg','eficiencia_incremental','consumo_minimo_mj_km']].to_numpy(dtype=float)
    f=b.factor_base_hot_ec_mj_km.to_numpy(dtype=float)
    if (not np.isfinite(values).all() or not np.isfinite(f).all() or (f<=0).any()
            or (values[:,0]<=0).any() or (values[:,1]<=0).any() or (values[:,1]>1).any()
            or (values[:,2]<0).any() or (values[:,2]>f).any()):
        raise ValueError('Masa/eficiencia/mínimo o factor no válidos; no se rellenan vacíos.')
    mass,eta,minimum=values.T;length=out.length_m.to_numpy()/1000
    for name in required_parameters-{'segment_id'}:out[name]=p[name].to_numpy()
    out['energia_base_mj_propuesta']=length*f
    out['energia_minima_mj_propuesta']=length*minimum
    out['trabajo_gravitatorio_mj_propuesta']=out.trabajo_gravitatorio_mj_por_t.to_numpy()*mass/1000
    # El trabajo sobrante en descenso se disipa; no es combustible exportado.
    demand=eta*(out.energia_base_mj_propuesta-out.energia_minima_mj_propuesta)+out.trabajo_gravitatorio_mj_propuesta
    out['demanda_trabajo_mj_propuesta']=demand
    out['trabajo_positivo_mj_propuesta']=np.maximum(demand,0)
    out['disipacion_mecanica_mj_propuesta']=np.maximum(-demand,0)
    out['energia_combustible_mj_propuesta']=out.energia_minima_mj_propuesta+out.trabajo_positivo_mj_propuesta/eta
    out['residuo_balance_mj_propuesta']=out.trabajo_positivo_mj_propuesta-out.disipacion_mecanica_mj_propuesta-demand
    out['estado_propuesta']='NO_CALIBRADA_NO_ADOPTADA; eficiencia constante, mínimo explícito y sin regeneración'
    return out


def completar_masas_turismos(referencias, parametros):
    """Resolver masa cargada desde el Excel; conservar ausencias y propuestas.

    Una referencia con una persona de masa propuesta se muestra aparte del
    escenario elegido. La ocupación incluye conductor y no se añade dos veces.
    """
    required={'tara_p25_kg','tara_mediana_kg','tara_p75_kg'}
    if referencias.empty or not required<=set(referencias):
        raise ValueError('Faltan las distribuciones de tara de las referencias.')
    q=referencias[['tara_p25_kg','tara_mediana_kg','tara_p75_kg']].to_numpy(dtype=float)
    if not np.isfinite(q).all() or (q<=0).any() or (np.diff(q,axis=1)<0).any():
        raise ValueError('La referencia de tara debe ser positiva, finita y ordenada.')
    rows={x['id']:x for x in parametros['parametros']}
    keys=['criterio_tara_turismos','masa_persona_turismo_kg','ocupacion_coche','equipaje_turismo_kg_coche']
    if not set(keys)<=set(rows):raise ValueError('Faltan las elecciones de masa del libro.')
    chosen={k:rows[k]['valor_utilizado'] for k in keys}
    columns={'Mediana (P50)':'tara_mediana_kg','Cuartil inferior (P25)':'tara_p25_kg','Cuartil superior (P75)':'tara_p75_kg'}
    if chosen[keys[0]] is not None and chosen[keys[0]] not in columns:
        raise ValueError('Criterio de tara no reconocido.')
    for k,minimum in [('masa_persona_turismo_kg',0),('ocupacion_coche',1),('equipaje_turismo_kg_coche',0)]:
        value=chosen[k]
        if value is not None and (not np.isfinite(value) or value<minimum or (k=='masa_persona_turismo_kg' and value==0)):
            raise ValueError('Parámetro de masa no válido: '+k)
    out=referencias.copy(deep=True)
    out['tara_elegida_kg']=out[columns[chosen[keys[0]]]] if chosen[keys[0]] is not None else np.nan
    for k in keys[1:]:out[k]=chosen[k] if chosen[k] is not None else np.nan
    # Esta referencia técnica no sustituye la elección ni representa una visita.
    proposal=rows['masa_persona_turismo_kg']['propuesta']['valor']
    if proposal is None or not np.isfinite(proposal) or proposal<=0:
        raise ValueError('Falta la referencia propuesta de masa de una persona.')
    out['masa_referencia_p50_una_persona_propuesta_kg']=out.tara_mediana_kg+proposal
    missing=[k for k,v in chosen.items() if v is None]
    out['masa_total_elegida_kg']=np.nan
    if not missing:
        out['masa_total_elegida_kg']=out.tara_elegida_kg+chosen['ocupacion_coche']*chosen['masa_persona_turismo_kg']+chosen['equipaje_turismo_kg_coche']
    out['pendientes_masa']='; '.join(missing)
    out['estado_masa']='Pendiente; no se calcula combustible' if missing else 'Hipótesis de masa resuelta; no valida combustible, plazas o MMA de cada vehículo'
    return out


def acotar_balance_sin_minimo_identificado(segmentos, base, parametros, *, combustible):
    """Calcular límites internos de H083, sin elegir un mínimo de combustible.

    Para 0<=Emin<=Ebase y A=Wg/eta, la envolvente exacta es:
    inferior=max(Ebase+A,0); superior=Ebase+max(A,0).
    Son límites del modelo y sus supuestos, no del consumo real ni de su error.
    La masa/eficiencia y sus fuentes siguen siendo obligatorias. No hay una
    estimación central o mínimo adoptado; tampoco representa regeneración.
    """
    if {'consumo_minimo_mj_km','fuente_minimo'} & set(parametros):
        raise ValueError('La envolvente no adopta un mínimo; usar el balance explícito si ya está justificado.')
    if not {'segment_id','masa_total_kg','eficiencia_incremental','fuente_masa','fuente_eficiencia'}<=set(parametros):
        raise ValueError('Faltan masa, rendimiento o sus fuentes por segmento.')
    if not {'segment_id','factor_base_hot_ec_mj_km'}<=set(base):
        raise ValueError('Faltan los factores base por segmento.')
    # Construir extremos matemáticos; las validaciones físicas y de fuentes se reutilizan.
    baja=parametros.copy(deep=True);alta=parametros.copy(deep=True)
    baja['consumo_minimo_mj_km']=0.
    baja['fuente_minimo']='Extremo matemático Emin=0; no mínimo de combustible adoptado'
    upper=base[['segment_id','factor_base_hot_ec_mj_km']].rename(
        columns={'factor_base_hot_ec_mj_km':'consumo_minimo_mj_km'})
    alta=alta.merge(upper,on='segment_id',how='left',validate='one_to_one')
    alta['fuente_minimo']='Extremo matemático Emin=Ebase; sin reducción por descenso, no consumo real'
    lower=ensayar_balance_incremental_no_regenerativo(segmentos,base,baja,combustible=combustible)
    upper=ensayar_balance_incremental_no_regenerativo(segmentos,base,alta,combustible=combustible)
    out=segmentos.copy(deep=True)
    for col in ['masa_total_kg','eficiencia_incremental','fuente_masa','fuente_eficiencia']:
        out[col]=lower[col]
    out['energia_base_mj']=lower.energia_base_mj_propuesta
    out['trabajo_gravitatorio_mj']=lower.trabajo_gravitatorio_mj_propuesta
    out['incremento_gravitatorio_condicionado_mj']=out.trabajo_gravitatorio_mj/out.eficiencia_incremental
    out['energia_limite_inferior_modelo_mj']=lower.energia_combustible_mj_propuesta
    out['energia_limite_superior_modelo_mj']=upper.energia_combustible_mj_propuesta
    out['separacion_limites_modelo_mj']=out.energia_limite_superior_modelo_mj-out.energia_limite_inferior_modelo_mj
    out['limite_inferior_nulo']=out.energia_limite_inferior_modelo_mj.eq(0)
    for key in ['inferior','superior']:
        out[f'energia_limite_{key}_modelo_kwh']=out[f'energia_limite_{key}_modelo_mj']/3.6
    if (out.separacion_limites_modelo_mj.lt(-1e-10).any()
            or out.separacion_limites_modelo_mj.gt(out.energia_base_mj+1e-10).any()):
        raise ValueError('Los extremos no son coherentes con la envolvente analítica.')
    out['alcance_limites']='Límites internos de H083 condicionado; no intervalo de consumo real, incertidumbre o ahorro'
    out['consumo_montana_adoptado']=False
    return out


def ensayar_pendiente_elegida(segmentos, base, parametros, *, masa_total_kg, combustible):
    """Aplicar las elecciones explícitas del libro a una referencia convencional.

    No incorpora el resultado al balance de toda la flota. La masa procede de la
    referencia compatible y la ocupación elegida, sin duplicar al conductor.
    """
    keys = {'Petrol': 'eficiencia_incremental_gasolina_pendiente',
            'Diesel': 'eficiencia_incremental_diesel_pendiente'}
    if combustible not in keys:
        raise ValueError('La sensibilidad elegida solo admite gasolina o diésel convencionales.')
    rows = {p['id']: p for p in parametros['parametros']}
    if not {keys[combustible], 'tratamiento_descenso_turismos'} <= set(rows):
        raise ValueError('Faltan las elecciones de pendiente del libro.')
    eta = rows[keys[combustible]]['valor_utilizado']
    rule = rows['tratamiento_descenso_turismos']['valor_utilizado']
    if (isinstance(masa_total_kg, (bool, np.bool_)) or not np.isfinite(masa_total_kg)
            or masa_total_kg <= 0 or eta is None or isinstance(eta, (bool, np.bool_))
            or not np.isfinite(eta) or not 0 < eta <= 1):
        raise ValueError('Masa o conversión incremental pendiente/inválida.')
    if rule not in {'Corte ideal de inyección', 'Sin reducción de consumo en descenso'}:
        raise ValueError('Tratamiento del descenso pendiente o no implementado.')
    values = pd.DataFrame({'segment_id': segmentos.segment_id,
        'masa_total_kg': masa_total_kg, 'eficiencia_incremental': eta,
        'fuente_masa': 'D212: masa resuelta del perfil mediante tara, ocupación, masa por persona y equipaje del Excel',
        'fuente_eficiencia': rows[keys[combustible]]['justificacion_utilizada'],
        'fuente_minimo': rows['tratamiento_descenso_turismos']['justificacion_utilizada']})
    if rule == 'Corte ideal de inyección':
        values['consumo_minimo_mj_km'] = 0.
    else:
        values = values.merge(base[['segment_id','factor_base_hot_ec_mj_km']].rename(
            columns={'factor_base_hot_ec_mj_km':'consumo_minimo_mj_km'}),
            on='segment_id', how='left', validate='one_to_one')
    result = ensayar_balance_incremental_no_regenerativo(segmentos, base, values, combustible=combustible)
    result['tratamiento_descenso_elegido'] = rule
    result['correccion_global_adoptada'] = False
    return result
