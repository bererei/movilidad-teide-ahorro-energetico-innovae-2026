"""Propuestas de activación por reservas, con demanda y reglas conservadas.

La suficiencia de plazas, el reloj, la flota diaria y el pool por bases son
comprobaciones distintas. Ningún saldo diagnóstico acredita oferta viable.
"""
import math
import numpy as np
import pandas as pd
from movilidad_teide.operacion.reservas import ordenar_cadenas_refuerzo, construir_perfil_refuerzos
from movilidad_teide.operacion.circulacion import programar_circulacion
from movilidad_teide.energia.sensibilidad_modal import reasignar_en_horario_conservado
from movilidad_teide.operacion.ampliacion import _minimo_vehiculos


def modular_por_reservas(movimientos, pares, objetivos, paradas, valores, *, interior_solo_reservas):
    """Conservar primeras/últimas cadenas y activar suficientes plazas completas.

    Propuesta previa a publicar y confirmar reservas, no permiso para cancelar
    billetes existentes. El interior conserva recorridos completos y tiempos;
    la variante selectiva omite únicamente salidas sin ninguna cadena asignada.
    """
    if not isinstance(interior_solo_reservas,bool):raise ValueError('Política interior no válida.')
    if objetivos.tipo_dia.nunique()!=1 or objetivos.punto.duplicated().any():raise ValueError('Seleccionar un solo periodo.')
    day=objetivos.tipo_dia.iloc[0];cap=int(valores['plazas_guagua']*valores['ocupacion_diseno'])
    if not np.isfinite(objetivos.demanda_lanzadera_condicionada_dia).all() or objetivos.demanda_lanzadera_condicionada_dia.lt(0).any():raise ValueError('Demanda inválida.')
    counts={r.punto:max(3,math.ceil(max(0,r.demanda_lanzadera_condicionada_dia-1e-8)/cap)) for r in objetivos.itertuples()}
    z=construir_perfil_refuerzos(movimientos,pares,ordenar_cadenas_refuerzo(pares),counts,valores)
    if interior_solo_reservas:
        mm=z['movimientos'];links=z['pares'];ids=set(links.id_interior_ida)|set(links.id_interior_regreso)
        plan=mm.loc[mm.componente.str.startswith('comercial')&(mm.punto.ne('INTERIOR')|mm.id_salida.isin(ids))].copy()
        rows=[]
        for q,g in plan.groupby('punto'):
            rows.append({'punto':q,'salidas_ida_dia':int(g.sentido.eq('ida').sum()),'salidas_vuelta_dia':int(g.sentido.eq('vuelta').sum()),
                **{'longitud_'+s+'_km':float(g.loc[g.sentido.eq(s),'km_por_recorrido'].iloc[0]) for s in ['ida','vuelta']}})
        geo=mm[['punto','sentido','origen','destino','itinerary_id']].drop_duplicates()
        z=programar_circulacion(pd.DataFrame(rows),pd.DataFrame(),pd.DataFrame(),geo,valores,
            salidas_propuestas=plan[['punto','sentido','salida_min','id_salida']],plan_completo_reservas=True)
        z['pares']=links
    z['movimientos']=z['movimientos'].assign(tipo_dia=day,dias_calendario=1)
    check=reasignar_en_horario_conservado(z['movimientos'],z['pares'],objetivos,paradas,capacidad=cap,
        margen=valores['margen_enlace_interior_min'],espera=valores['espera_max_lanzadera_min'],estancia=valores['estancia_min_visita_min'])
    z['pares']=check['pares'];z['cargas_tramos']=check['cargas_tramos']
    # Volver a llenar las cadenas demuestra que no se duplica capacidad interior.
    full=objetivos.copy();full['demanda_lanzadera_condicionada_dia']=full.punto.map(z['pares'].groupby('punto').size())*cap
    reasignar_en_horario_conservado(z['movimientos'],z['pares'],full,paradas,capacidad=cap,
        margen=valores['margen_enlace_interior_min'],espera=valores['espera_max_lanzadera_min'],estancia=valores['estancia_min_visita_min'])
    intervals=[];lower=[]
    for q,g in z['movimientos'].groupby('punto'):
        commercial=g.loc[g.componente.str.startswith('comercial')]
        d={s:float(g.loc[g.sentido.eq(s),'tiempo_recorrido_min'].unique().item()) for s in ['ida','vuelta']}
        n=_minimo_vehiculos(list(zip(commercial.sentido,commercial.salida_min)),d,valores['regulacion_min'])
        lower.append({'punto':q,'cota_vehiculos_para_reloj_fijo':n,'vehiculos_construidos':int(z['vehiculos'].punto.eq(q).sum())})
        if q!='INTERIOR':
            gaps=commercial.loc[commercial.sentido.eq('ida')].salida_min.sort_values().diff().dropna()
            intervals.append(float(gaps.min()) if len(gaps) else np.inf)
    active=len(z['vehiculos']);reserve=math.ceil(active*valores['reserva_flota']);contract=valores['vehiculos_contrato_contraste']
    interval=min(intervals);lower_total=sum(t['cota_vehiculos_para_reloj_fijo'] for t in lower)
    z['cota_por_servicio']=pd.DataFrame(lower)
    z['diagnostico']={'vehiculos_operativos':active,'vehiculos_reserva':reserve,'vehiculos_totales':active+reserve,
        'cabe_en_30':active+reserve<=contract,'intervalo_minimo_real_subidas_min':interval,
        'cumple_intervalo_vigente':interval>=valores['intervalo_minimo_subidas_min']-1e-8,
        'demanda_completa_comprobada':True,'cota_vehiculos_para_reloj_fijo':lower_total,
        'imposible_25_con_reloj_fijo':lower_total>max(n for n in range(1,int(contract)+1) if n+math.ceil(n*valores['reserva_flota'])<=contract),
        'minimo_global_de_cualquier_horario_demostrado':False,'propuesta_adoptada':False}
    return z


def pool_fijo_por_bases(vehiculos, *, reserva, contrato):
    """No suponer traslados gratuitos entre bases al cambiar de observación."""
    keys=['politica','observacion','punto','terminal_inicial']
    if vehiculos.empty or not set(keys+['vehiculo_id'])<=set(vehiculos):raise ValueError('Falta la localización de la flota.')
    counts=vehiculos.groupby(keys).size().rename('vehiculos').reset_index()
    pool=counts.groupby(['politica','punto','terminal_inicial'],as_index=False).vehiculos.max()
    totals=pool.groupby('politica',as_index=False).vehiculos.sum().rename(columns={'vehiculos':'vehiculos_operativos_pool'})
    totals['vehiculos_reserva']=totals.vehiculos_operativos_pool.map(lambda n:math.ceil(n*reserva))
    totals['vehiculos_totales_pool']=totals.vehiculos_operativos_pool+totals.vehiculos_reserva
    totals['cabe_en_30_sin_traslados_entre_bases']=totals.vehiculos_totales_pool.le(contrato)
    return pool,totals


def balance_modulacion(base, costes, factibilidad, energia_previa, *, perdida):
    """Cuantificar la construcción completa; ahorro viable queda ausente si falla.

    Los coches sin/con, pendiente y demanda proceden del mismo balance D213.
    Solo se sustituye una vez el consumo de las nuevas guaguas.
    """
    if (isinstance(perdida,(bool,np.bool_)) or not np.isfinite(perdida) or not 0<=perdida<1
            or not np.isfinite(costes.hot_mwh_anio).all() or costes.hot_mwh_anio.lt(0).any()
            or set(costes.referencia_id)!=set(base.referencia_id)):
        raise ValueError('Contraste, costes o referencias incompatibles.')
    rows=[]
    if costes.duplicated(['politica','referencia_id']).any():raise ValueError('Coste anual repetido.')
    for z in costes.itertuples():
        valid=bool(factibilidad.loc[factibilidad.politica.eq(z.politica),'oferta_anual_30_reglas_vigentes_demostrada'].item())
        for b in base.loc[base.referencia_id.eq(z.referencia_id)].itertuples():
            hot=b.tratamiento_operativo=='Hot COPERT'
            old=energia_previa.loc[lambda t:t.referencia_id.eq(z.referencia_id)].iloc[0]
            previous=old.hot_mwh_anio if hot else old.con_contraste_mwh_anio
            energy=z.hot_mwh_anio if hot else z.hot_mwh_anio/(1-perdida)
            saldo=b.saldo_con_ajuste_convencional_mwh_anio+previous-energy
            rows.append({'politica':z.politica,'caso_pendiente':b.caso_pendiente,'alternativa_procedencia':b.alternativa_procedencia,
                'referencia_id':z.referencia_id,'es_referencia_guagua_elegida':b.es_referencia_guagua_elegida,'tratamiento_operativo':b.tratamiento_operativo,
                'sin_componentes_mwh_anio':b.sin_con_ajuste_convencional_mwh_anio,
                'con_construccion_condicionada_mwh_anio':b.con_con_ajuste_convencional_mwh_anio-previous+energy,
                'guaguas_mwh_anio':energy,'reduccion_guaguas_mwh_anio':previous-energy,
                'saldo_construccion_condicionada_mwh_anio':saldo,'saldo_construccion_condicionada_tep_anio':saldo/11.63,
                'oferta_anual_30_reglas_vigentes_demostrada':valid,'saldo_oferta_viable_30_mwh_anio':saldo if valid else np.nan,
                'alcanza_60_en_construccion_condicionada':saldo>=60*11.63,'cumplimiento_acreditado':False,
                'otras_tecnologias_y_terminos_pendientes_resueltos':False,'intervalo_confianza':False})
    return pd.DataFrame(rows)
