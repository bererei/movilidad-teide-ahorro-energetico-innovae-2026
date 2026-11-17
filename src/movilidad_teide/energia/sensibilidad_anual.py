"""Sensibilidad anual acotada: hipótesis documentadas y umbrales algebraicos."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from movilidad_teide.validacion import comprobar_claves as _claves
from movilidad_teide.opciones import PUNTOS


def seleccionar_componente_catalogo(demanda, catalogo, bases, *, tipo_dia, capacidad):
    """Valorar la parte conocida sin dar por atendido un exceso de demanda.

    Conservo mínimos del tipo y las cadenas anidadas D193. El perfil limita
    únicamente la parte calculable; no cancela personas fuera del catálogo.
    """
    points=set(PUNTOS.values())
    if (isinstance(capacidad,(bool,np.bool_)) or not np.isfinite(capacidad) or capacidad<=0
            or capacidad!=int(capacidad) or set(demanda)!=points
            or any(isinstance(n,(bool,np.bool_)) or not np.isfinite(n) or n<0 for n in demanda.values())):
        raise ValueError('Demanda o capacidad inválida.')
    _claves(catalogo,['perfil_id'],'Catálogo')
    if catalogo.empty or not catalogo.perfil_comprobado.eq(True).all():raise ValueError('Catálogo vacío o no comprobado.')
    maximum={q:int(catalogo['parejas_'+q].max()) for q in points}
    if tipo_dia=='Festivo/especial':minimum=maximum
    elif tipo_dia in bases:minimum=bases[tipo_dia]
    else:raise ValueError('Tipo de día no reconocido; no imputar domingo.')
    if set(minimum)!=points or any(isinstance(n,(bool,np.bool_)) or not isinstance(n,(int,np.integer)) or n<1 or n>maximum[q] for q,n in minimum.items()):
        raise ValueError('Base de oferta inválida.')
    required={q:max(minimum[q],math.ceil(max(0,demanda[q]-1e-8)/capacidad)) for q in points}
    counts={q:min(required[q],maximum[q]) for q in points}
    selected=catalogo.loc[np.logical_and.reduce([catalogo['parejas_'+q].eq(n) for q,n in counts.items()])]
    if len(selected)!=1:raise ValueError('No existe un perfil único para el componente conocido.')
    deficit={q:max(0.,demanda[q]-counts[q]*capacidad) for q in points}
    return {'perfil_id':selected.perfil_id.iloc[0],'parejas_por_corredor':counts,
        'parejas_necesarias_por_corredor':required,'exceso_personas_por_corredor':deficit,
        'cabe_por_volumen_diario':bool(max(deficit.values())<=1e-8),
        'actividad_fuera_catalogo_cuantificada':False,'frecuencia_futura_confirmada':False}


def sensibilidad_componentes(tabla, *, perdida_rendimiento, objetivo_tep):
    """Separar contraste externo, respuesta unitaria y umbrales de signo.

    No cambia personas o expediciones y no pretende representar una respuesta
    modal real. Los factores comunes afectan ambos escenarios, alimentación
    incluida. La operación adicional no cuantificada sigue fuera del saldo.
    """
    for value,name in [(perdida_rendimiento,'Pérdida'),(objetivo_tep,'Objetivo')]:
        if isinstance(value,(bool,np.bool_)) or not np.isfinite(value):raise ValueError(name+' inválido.')
    if not 0<=perdida_rendimiento<1 or objetivo_tep<=0:raise ValueError('Dominio de contraste inválido.')
    keys=['politica_oferta','alternativa_procedencia']
    if 'caso_sensibilidad' in tabla:keys=['caso_sensibilidad',*keys]
    _claves(tabla,keys,'Componentes')
    fields=['coches_sin_mwh_anio','coches_con_objetivo_mwh_anio','alimentacion_otros_mwh_anio',
        'servicios_comunes_sin_mwh_anio','servicios_comunes_con_mwh_anio','guaguas_regulares_con_contraste_mwh_anio','saldo_componentes_objetivo_mwh_anio']
    if tabla.empty or not np.isfinite(tabla[fields]).all().all() or tabla[fields[:-1]].lt(0).any().any():raise ValueError('Componentes ausentes o negativos.')
    controls=[];limits=[]
    for row in tabla.to_dict('records'):
        ident={k:row[k] for k in keys}
        before=row['coches_sin_mwh_anio'];after=row['coches_con_objetivo_mwh_anio'];feed=row['alimentacion_otros_mwh_anio']
        common_delta=row['servicios_comunes_sin_mwh_anio']-row['servicios_comunes_con_mwh_anio']
        car_delta=before-after-feed;bus=row['guaguas_regulares_con_contraste_mwh_anio']
        saldo=car_delta+common_delta-bus
        if not np.isclose(saldo,row['saldo_componentes_objetivo_mwh_anio'],rtol=0,atol=1e-8):raise ValueError('Los componentes no concilian.')
        hot=bus*(1-perdida_rendimiento)
        for name,energy in [('Hot con contraste operativo elegido',bus),('Solo Hot: control de alcance',hot)]:
            known=car_delta+common_delta-energy
            controls.append({**ident,'control_consumo_guaguas':name,'guaguas_mwh_anio':energy,
                'saldo_componentes_antes_adicionales_mwh_anio':known,'saldo_componentes_antes_adicionales_tep_anio':known/11.63,
                'contraste_externo_mwh_anio':bus-hot,'ahorro_final_mwh_anio':np.nan,'escenario_futuro_adoptado':False,
                'lectura':'Misma actividad física; retirar contraste externo no demuestra menor consumo real de montaña.'})
        limits.append({**ident,'saldo_antes_adicionales_mwh_anio':saldo,
            'cambio_saldo_por_menos_1pct_consumo_todos_coches_mwh_anio':-.01*car_delta,
            'cambio_saldo_por_mas_1pct_consumo_nuevas_guaguas_mwh_anio':-.01*bus,
            'reduccion_uniforme_coches_para_saldo_cero_pct':100*(1-(bus-common_delta)/car_delta) if car_delta>0 else np.nan,
            'incremento_nuevas_guaguas_para_saldo_cero_pct':100*((car_delta+common_delta)/bus-1) if bus>0 else np.nan,
            'fraccion_energia_coche_evitada_para_saldo_cero':(feed+bus-common_delta)/(before-after) if before>after else np.nan,
            'coste_neto_adicional_para_saldo_cero_mwh_anio':saldo,
            'coste_neto_adicional_para_objetivo_mwh_anio':saldo-objetivo_tep*11.63,
            'objetivo_tep_anio':float(objetivo_tep),'probabilidad_asignada':np.nan,
            'lectura':'Umbrales condicionados sin adicionales; retención energética no es porcentaje de viajeros o adopción modal.'})
    return {'controles_consumo':pd.DataFrame(controls),'respuesta_y_umbrales':pd.DataFrame(limits)}


def limites_catalogo_por_tipo(catalogo, energia, bases, dias_por_tipo):
    """Extremos físicos del catálogo compatible; no frecuencia o banda estadística.

    Cada tipo conserva su base. Reviso todos los perfiles, sin presumir que
    más parejas tengan siempre mayor consumo; fuera del catálogo queda ausente.
    """
    _claves(catalogo,['perfil_id'],'Catálogo');_claves(energia,['perfil_id','referencia_id'],'Energía')
    if set(bases)!=set(dias_por_tipo) or any(isinstance(n,(bool,np.bool_)) or not isinstance(n,(int,np.integer)) or n<1 for n in dias_por_tipo.values()) or sum(dias_por_tipo.values())!=366:
        raise ValueError('Calendario o bases inválidos.')
    if catalogo.empty or not catalogo.perfil_comprobado.eq(True).all():raise ValueError('Catálogo no comprobado.')
    fields=['con_contraste_mwh_dia']
    if not np.isfinite(energia[fields]).all().all() or energia[fields].lt(0).any().any():raise ValueError('Energía inválida.')
    rows=[]
    for day,minimum in bases.items():
        if set(minimum)!=set(PUNTOS.values()):raise ValueError('Falta corredor en la base.')
        mask=np.logical_and.reduce([catalogo['parejas_'+q].ge(n) for q,n in minimum.items()])
        compatible=catalogo.loc[mask]
        base=catalogo.loc[np.logical_and.reduce([catalogo['parejas_'+q].eq(n) for q,n in minimum.items()])]
        if compatible.empty or len(base)!=1:raise ValueError('Base fuera del catálogo.')
        for ref,g in energia.groupby('referencia_id'):
            if set(g.perfil_id)!=set(catalogo.perfil_id):raise ValueError('Energía sin todos los perfiles.')
            costs=g.set_index('perfil_id').con_contraste_mwh_dia
            low=costs.loc[compatible.perfil_id].min();high=costs.loc[compatible.perfil_id].max();b=costs[base.perfil_id.iloc[0]]
            rows.append({'tipo_dia':day,'referencia_id':ref,'dias_calendario':dias_por_tipo[day],
                'perfiles_compatibles':len(compatible),'base_mwh_dia':float(b),'minimo_catalogo_mwh_dia':float(low),'maximo_catalogo_mwh_dia':float(high),
                'incremento_anual_minimo_dentro_catalogo_mwh':float((low-b)*dias_por_tipo[day]),
                'incremento_anual_maximo_dentro_catalogo_mwh':float((high-b)*dias_por_tipo[day]),
                'energia_fuera_catalogo_mwh_anio':np.nan,'frecuencia_cabildo_confirmada':False})
    return pd.DataFrame(rows)
