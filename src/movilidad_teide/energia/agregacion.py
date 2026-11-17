"""Síntesis anual de componentes objetivo y modulación por el Cabildo.

No convierte transferencia deseada en demanda servida ni completa con cero
la operación adicional pendiente. La oferta regular se contrasta por separado.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from movilidad_teide.validacion import comprobar_claves as _claves


CAMPOS_ENERGIA = ['coches_sin_mwh_periodo','coches_con_objetivo_mwh_periodo',
    'alimentacion_otros_mwh_periodo','servicios_comunes_sin_mwh_periodo','servicios_comunes_con_mwh_periodo']


def agregar_componentes_objetivo(coches, comunes, controles, indices, dias_por_tipo):
    """Media de tres observaciones2025 por tipo, con idénticos pesos sin/con.

    La insuficiencia de oferta no elimina coches o personas de la ponderación.
    Lo posterior sigue rotulado como objetivo, nunca como servicio acreditado.
    """
    ids=indices.loc[indices.anio.eq(2025),['matrix_index','mes_publicado','tipo_dia_publicado']]
    if (len(ids)!=9 or ids.matrix_index.duplicated().any() or ids.duplicated(['mes_publicado','tipo_dia_publicado']).any()
            or ids.mes_publicado.nunique()!=3 or set(dias_por_tipo)!=set(ids.tipo_dia_publicado)
            or any(isinstance(n,(bool,np.bool_)) or not isinstance(n,(int,np.integer)) or n<1 for n in dias_por_tipo.values())
            or sum(dias_por_tipo.values())!=366):
        raise ValueError('Se requieren nueve observaciones2025 y calendario2028 completo.')
    for name,t,keys in [('Coches',coches,['periodo_id','alternativa_procedencia']),('Comunes',comunes,['periodo_id']),('Controles',controles,['periodo_id'])]:
        _claves(t,keys,name)
        if t.empty:raise ValueError('No agregar tablas vacías.')
    c=controles.loc[controles.matrix_index.isin(ids.matrix_index)].copy()
    if c.matrix_index.duplicated().any() or set(c.matrix_index)!=set(ids.matrix_index):raise ValueError('Falta una observación o está duplicada.')
    if not c.conservacion_personas_comprobada.eq(True).all():raise ValueError('Demanda sin conservación comprobada.')
    if c.oferta_suficiente.isna().any() or not c.oferta_suficiente.map(lambda z:isinstance(z,(bool,np.bool_))).all():raise ValueError('Estado de capacidad no explícito.')
    c=c.merge(ids,on='matrix_index',validate='one_to_one')
    if not c.tipo_dia_fuente.eq(c.tipo_dia_publicado).all():raise ValueError('Tipo de día incompatible con la fuente.')
    selected=coches.loc[coches.periodo_id.isin(c.periodo_id)].copy()
    for _,g in selected.groupby('alternativa_procedencia'):
        if set(g.periodo_id)!=set(c.periodo_id):raise ValueError('Alternativa incompleta; no renormalizar.')
    if selected.empty or set(coches.alternativa_procedencia)!=set(selected.alternativa_procedencia):raise ValueError('Falta una alternativa.')
    x=selected.merge(comunes,on='periodo_id',validate='many_to_one',suffixes=('_coches','_comunes'))
    if len(x)!=len(selected):raise ValueError('Faltan componentes comunes; no descartar observaciones.')
    for field in ['demanda_referencia_id','unidad_periodo']:
        if x[[field+'_coches',field+'_comunes']].isna().any().any() or not x[field+'_coches'].eq(x[field+'_comunes']).all():
            raise ValueError('No mezclar demanda o unidades entre componentes.')
    if not x.unidad_periodo_coches.eq('dia').all():raise ValueError('La ponderación requiere componentes diarios.')
    if not np.isfinite(x[CAMPOS_ENERGIA]).all().all() or x[CAMPOS_ENERGIA].lt(0).any().any():raise ValueError('Energía ausente o negativa.')
    x=x.merge(c[['periodo_id','matrix_index','mes_publicado','tipo_dia_publicado','oferta_suficiente']],on='periodo_id',validate='many_to_one')
    counts=x.groupby(['alternativa_procedencia','tipo_dia_publicado']).periodo_id.transform('count')
    if not counts.eq(3).all():raise ValueError('Cada tipo exige sus tres observaciones.')
    x['dias_calendario']=x.tipo_dia_publicado.map(dias_por_tipo)
    x['peso_dias_equivalentes']=x.dias_calendario/3
    rows=[]
    for (alt,day),g in x.groupby(['alternativa_procedencia','tipo_dia_publicado']):
        row={'alternativa_procedencia':alt,'tipo_dia':day,'dias_calendario':int(dias_por_tipo[day]),'observaciones_fuente':3,
             'observaciones_con_oferta_D194':int(g.oferta_suficiente.sum())}
        row.update({f.replace('_periodo','_anio'):float((g[f]*g.peso_dias_equivalentes).sum()) for f in CAMPOS_ENERGIA})
        rows.append(row)
    detail=pd.DataFrame(rows)
    fields=[f.replace('_periodo','_anio') for f in CAMPOS_ENERGIA]
    total=detail.groupby('alternativa_procedencia',as_index=False)[fields].sum()
    demand_fields=['personas_referencia_dia','coches_sin_dia','coches_autorizados_dia','coches_transferidos_dia',
        'personas_transferidas_desde_coche_dia','personas_captadas_desde_otros_modos_dia','personas_lanzadera_dia']
    if not np.isfinite(c[demand_fields]).all().all() or c[demand_fields].lt(0).any().any():raise ValueError('Actividad de demanda inválida.')
    if not np.allclose(c.coches_sin_dia,c.coches_autorizados_dia+c.coches_transferidos_dia,rtol=0,atol=1e-8):raise ValueError('Las ramas no conservan coches.')
    demand=[]
    for day,g in c.groupby('tipo_dia_publicado'):
        demand.append({'tipo_dia':day,'dias_calendario':int(dias_por_tipo[day]),'observaciones_fuente':len(g),
            **{f.replace('_dia','_anio'):float(g[f].mean()*dias_por_tipo[day]) for f in demand_fields}})
    return {'por_tipo':detail,'total':total,'ponderacion':x,'demanda_por_tipo':pd.DataFrame(demand)}


def tabla_anual_de_trabajo(componentes, ofertas):
    """Sumas objetivo antes de operación adicional y correcciones no cuantificadas.

    Ninguna política de oferta se identifica aquí como calendario del Cabildo
    o como operación que atiende todo el año. Los resultados finales quedan NA.
    """
    _claves(componentes,['alternativa_procedencia'],'Componentes anuales')
    _claves(ofertas,['politica_oferta','tipo_dia'],'Oferta regular')
    fields=[f.replace('_periodo','_anio') for f in CAMPOS_ENERGIA]
    if componentes.empty or not np.isfinite(componentes[fields]).all().all() or componentes[fields].lt(0).any().any():raise ValueError('Componentes anuales inválidos.')
    if ofertas.empty or not np.isfinite(ofertas[['dias_calendario','guaguas_con_contraste_mwh_dia']]).all().all() or ofertas.guaguas_con_contraste_mwh_dia.lt(0).any():raise ValueError('Oferta anual inválida.')
    rows=[]
    for policy,g in ofertas.groupby('politica_oferta'):
        days=g.set_index('tipo_dia').dias_calendario.to_dict()
        if days!={'Laborable':260,'Sábado':53,'Domingo':53}:raise ValueError('Oferta sin calendario2028 del caso.')
        energy=float((g.dias_calendario*g.guaguas_con_contraste_mwh_dia).sum())
        for row in componentes.to_dict('records'):
            before=row['coches_sin_mwh_anio']+row['servicios_comunes_sin_mwh_anio']
            after=(row['coches_con_objetivo_mwh_anio']+row['alimentacion_otros_mwh_anio']+row['servicios_comunes_con_mwh_anio']+energy)
            rows.append({**row,'politica_oferta':policy,'guaguas_regulares_con_contraste_mwh_anio':energy,
                'sin_ambito_representado_mwh_anio':before,'con_componentes_objetivo_regular_mwh_anio':after,
                'saldo_componentes_objetivo_mwh_anio':before-after,'saldo_componentes_objetivo_tep_anio':(before-after)/11.63,
                'operacion_adicional_pendiente_mwh_anio':np.nan,'otros_cambios_netos_pendientes_mwh_anio':np.nan,
                'con_total_anual_mwh':np.nan,'ahorro_final_mwh_anio':np.nan,'ahorro_final_tep_anio':np.nan,
                'porcentaje_ahorro_final':np.nan,'operacion_anual_completa_comprobada':False,
                'modulacion_operativa':'Cabildo de Tenerife','cumplimiento_acreditado':False})
    return pd.DataFrame(rows)


def coeficientes_modulacion(coeficientes_calendario):
    """Coste de sustituir una fecha base por completa, no frecuencia prevista."""
    x=coeficientes_calendario.copy(deep=True)
    _claves(x,['referencia_id','tipo_dia_calendario_aproximado'],'Coeficientes')
    fields=['base_mwh_dia','completo_mwh_dia','incremento_por_dia_sustituido_mwh','dias_calendario']
    if x.empty or not np.isfinite(x[fields]).all().all() or x[fields[:2]].lt(0).any().any():raise ValueError('Costes de modulación ausentes o negativos.')
    if not np.allclose(x.completo_mwh_dia-x.base_mwh_dia,x.incremento_por_dia_sustituido_mwh,rtol=0,atol=1e-8):raise ValueError('El incremento duplica o pierde energía.')
    for _,g in x.groupby('referencia_id'):
        if g.set_index('tipo_dia_calendario_aproximado').dias_calendario.to_dict()!={'Laborable':260,'Sábado':53,'Domingo':53}:raise ValueError('Calendario incompleto.')
    x['fechas_activadas_por_cabildo']=np.nan
    x['consumo_adicional_fuera_catalogo_mwh_anio']=np.nan
    x['responsable_modulacion']='Cabildo de Tenerife'
    x['frecuencia_adoptada']=False
    return x


def limites_materialidad(tabla, *, objetivo_tep):
    """Umbrales algebraicos; no consumos previstos o bandas de confianza."""
    if isinstance(objetivo_tep,(bool,np.bool_)) or not np.isfinite(objetivo_tep) or objetivo_tep<=0:raise ValueError('Objetivo inválido.')
    _claves(tabla,['politica_oferta','alternativa_procedencia'],'Tabla anual')
    if tabla.empty or not np.isfinite(tabla.saldo_componentes_objetivo_mwh_anio).all():raise ValueError('Falta saldo de componentes.')
    x=tabla[['politica_oferta','alternativa_procedencia','saldo_componentes_objetivo_mwh_anio']].copy()
    x['cambio_neto_adicional_para_saldo_cero_mwh_anio']=x.saldo_componentes_objetivo_mwh_anio
    x['cambio_neto_adicional_admisible_para_objetivo_mwh_anio']=x.saldo_componentes_objetivo_mwh_anio-objetivo_tep*11.63
    x['objetivo_tep_anio']=float(objetivo_tep)
    x['lectura']='Positivo admite ese coste neto; negativo exige reducción neta. Condicionado a hipótesis y demanda atendida; no frecuencia, previsión o cumplimiento.'
    x['cumplimiento_acreditado']=False
    return x
