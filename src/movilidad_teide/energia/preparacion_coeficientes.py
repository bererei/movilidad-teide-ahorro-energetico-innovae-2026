"""Conectar perfiles y vías reconstruidos con las unidades del balance vigente.

Los programas y la representación técnica elegida del parque son decisiones
fijas, no resultados energéticos. Los factores COPERT son los ya certificados.
No se leen coeficientes físicos anteriores ni salidas anuales de Gold.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from movilidad_teide.energia.pendiente import (masas_grupos_desde_dgt,perfiles_visita_interior,
    preparar_curvas_convencionales,energia_pendiente_por_recorrido,coeficiente_por_recorrido,recortar_intervalos)
from movilidad_teide.energia.preparacion_pendiente import CASOS_PENDIENTE
from movilidad_teide.energia.referencia import referencia_ponderada
from movilidad_teide.energia.interior import recorridos_interiores_coche
from movilidad_teide.energia.visita_privada import ampliar_patron_proximo
from movilidad_teide.opciones import METODO_CONSUMO
from movilidad_teide.vehiculos.copert_factores import apply_reference_factors_by_segment
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.flujos.compartida_2028 import BASE,PARADAS
from movilidad_teide.demanda.calendario_anual import aplicar_cupo_global
from movilidad_teide.flujos.operacion_2028 import FUENTES

PENDIENTE='data/silver/energia/referencias_unitarias/pendiente_turismos'
ENERGIA='data/silver/energia/lanzaderas/referencias_por_servicio'
EXCEPCIONES='data/silver/energia/coche_hasta_cabeceras/reasignaciones'
VEHICULO=('Buses','Diesel','Coaches Standard <=18 t','Euro VI D/E')


def leer(path):
    return pd.read_csv(path,sep=';',float_precision='round_trip',low_memory=False)


def guardar(root,name,table):
    p=Path(root)/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.suffix=='.parquet':table.to_parquet(p,index=False)
    else:table.to_csv(p,sep=';',index=False,float_format='%.17g')


def patrones_interiores(paradas):
    specs=[('zona_parador','Zona Parador / Cañada Blanca / Roques, referencia en carretera',['entrada_parador_tf21']),
        ('zona_teleferico','Acceso al Teleférico, referencia en carretera',['entrada_teleferico_tf21']),
        ('ambas_zonas','Ambas zonas en orden sobre el eje, sin retrocesos adicionales',['entrada_parador_tf21','entrada_teleferico_tf21']),
        ('eje_completo','Todo el eje y regreso, solo contraste de distancia',['interior_boca_eje_principal','interior_portillo_eje_principal'])]
    return ampliar_patron_proximo(recorridos_interiores_coche(paradas,
        [dict(patron_id=k,nombre=n,destinos=d) for k,n,d in specs],
        {'Boca Tauce':'interior_boca_eje_principal','El Portillo':'interior_portillo_eje_principal'}))


def preparar_turismos(root,calc,prep,segmentos,demanda,parametros,*,factores=None,flota=None,operacion=None):
    root,calc=Path(root),Path(calc);v={p['id']:p['valor_utilizado'] for p in parametros['parametros']}
    fleet=Path(flota) if flota is not None else root/'data/silver/vehiculos/flota_teide';diag=leer(fleet/'representacion_tecnica/perfiles_elegidos_diagnostico.csv')
    origen_factores=Path(factores) if factores is not None else root/'data/silver/copert/factores'
    main=pd.read_parquet(origen_factores/'factores_turismos.parquet');main['primary_control_fraction']=np.nan
    multi=pd.read_parquet(origen_factores/'factores_multienergia.parquet')
    weights=referencia_ponderada(diag,pd.concat([main,multi],ignore_index=True),leer(fleet/'representacion_tecnica/factores_elegidos_resumen.csv'),
        metodo=METODO_CONSUMO,control_primario=v['control_primario_referencia'])
    for k,t in weights.items():guardar(calc,'data/silver/vehiculos/ponderacion/'+k+'.csv',t)
    sizes=pd.read_csv(fleet/'propuesta_tamanos_turismos_detalle.csv',sep=';',dtype=str,keep_default_na=False)
    eq=json.loads((root/'data/bronze/documentacion/seleccion_vehiculos/20261024_microdatos_dgt/correspondencia_normas.json').read_text())['equivalencias']
    masses=masas_grupos_desde_dgt(root/'data/bronze/vehiculos/dgt_microdatos_2025/provincia_38/38.SANTA_CRUZ_DE_TENERIFE.txt',
        leer(fleet/'contraste_municipal_2025.csv').TERRITORIO.astype(int).astype(str).tolist(),eq,sizes,diag)
    if len(masses)!=816 or masses.vehiculos.sum()!=509459:raise ValueError('El parque de referencia no concilia.')
    curves=preparar_curvas_convencionales(weights['pesos_curvas'],weights['perfiles_referencia'],masses,main,parametros)
    patterns=patrones_interiores(leer((Path(operacion) if operacion is not None else root)/PARADAS))
    guardar(calc,'data/silver/energia/turismos/visita_interior/recorridos_interiores.csv',patterns)
    for k,t in prep.tables.items():
        if k.startswith('operativos/'):
            guardar(calc,'data/silver/geografia/perfiles_altimetricos/'+k.removeprefix('operativos/')+'.parquet',t)
    profiles=pd.concat([segmentos,perfiles_visita_interior(calc,patterns)],ignore_index=True)
    if profiles.groupby(['comparacion_id','itinerary_id','rol']).ngroups!=126:raise ValueError('Faltan componentes físicos de turismo.')
    routes=prep.tables['referencias/recorridos_referencia_calculo'].copy()
    # El terminal sigue la referencia territorial del catálogo; no se elige
    # según el resultado energético ni se añade una nueva visita interior.
    def terminal(row):
        key=row.comparacion_calculo_id
        if pd.isna(key):return np.nan
        if key in prep.cat['coastal_valley_comparisons']:
            key=prep.cat['coastal_valley_comparisons'][key]['reused_comparison_id']
        spec=prep.cat['origin_access_comparisons'].get(key,prep.cat['study_origin_access_comparisons'].get(key))
        return spec['terminal_label']
    routes['terminal_calculo']=routes.apply(terminal,axis=1)
    guardar(calc,'data/silver/demanda/asignacion/recorridos_referencia_calculo.csv',routes)
    origins=demanda['territorio/origenes_por_modo_2025']
    keys=origins.loc[origins.en_ambito_anual,['origen_id','colectivo']].drop_duplicates().sort_values(['origen_id','colectivo'])
    routes=routes.set_index(['origen_id','sentido']);occ=v['ocupacion_coche'];energies=[];units=[]
    for case,overrides in CASOS_PENDIENTE:
        print('Coeficientes de turismo:',case,flush=True)
        ee=pd.concat([energia_pendiente_por_recorrido(profiles,curves,weights['factores'],parametros,ocupacion=o,**overrides) for o in [occ,1.]],ignore_index=True)
        lookup=ee.set_index(['comparacion_id','itinerary_id','rol','grupo_servicio','ocupacion_coche'],verify_integrity=True)
        for alt in ['España no Tenerife: alquiler','España no Tenerife: particular']:
            for k in keys.itertuples():
                for direction in ['hacia_teide','desde_teide']:
                    rr=routes.loc[k.origen_id,direction]
                    for branch in ['antes','autorizados','transferidos','alimentacion_otros']:
                        occupancy=1. if branch=='alimentacion_otros' else occ
                        vals,service=coeficiente_por_recorrido(rr,lookup,alternativa=alt,colectivo=k.colectivo,sentido=direction,rama=branch,ocupacion=occupancy)
                        units.append(dict(alternativa_procedencia=alt,origen_id=k.origen_id,colectivo=k.colectivo,sentido=direction,rama=branch,grupo_servicio=service,
                            componente='Alimentación adicional desde otros modos' if branch=='alimentacion_otros' else 'Coches del reparto modal',ocupacion_hipotesis=occupancy,
                            energia_base_mwh_por_vehiculo_sentido=vals[0]/3600,correccion_mwh_por_vehiculo_sentido=vals[2]/3600,caso_pendiente=case))
        energies.append(ee.assign(caso_pendiente=case))
    for name,t in [('masas_por_grupo.csv',masses),('curvas_y_masas.parquet',curves),('segmentos_por_via.parquet',profiles),
            ('energia_por_recorrido.csv',pd.concat(energies,ignore_index=True)),('correccion_por_origen_y_rama.csv',pd.DataFrame(units))]:guardar(calc,PENDIENTE+'/'+name,t)
    return dict(curvas=curves,factores=weights['factores'],patrones=patterns,recorridos=routes,claves=keys)


def valorar_bus(segments,load,library,v):
    conditions=segments[['segment_id']].assign(velocidad_media_kmh=v['velocidad_copert'],carga_fisica=load,
        bloque_velocidad_id='ensayo_uniforme',fuente_velocidad='Hipótesis vigente del libro',tipo_via='rural')
    return apply_reference_factors_by_segment(segments,conditions,library,VEHICULO)


def preparar_autobuses(root,calc,prep,parametros,*,factores=None,operacion=None):
    root,calc=Path(root),Path(calc);v={p['id']:p['valor_utilizado'] for p in parametros['parametros']}
    library=(Path(factores) if factores is not None else root/'data/silver/copert/factores')/'factores_autocar.parquet'
    points={'chio_boca_tauce':'CHIO','aguamansa_el_portillo':'OROTAVA','la_esperanza_el_portillo':'LAGUNA','vilaflor_boca_tauce':'VILAFLOR','interior_boca_tauce_el_portillo':'INTERIOR'}
    allseg=[];summary=[]
    for k,s in prep.tables.items():
        if not k.startswith('operativos/') or '/tramos_' not in k:continue
        point=points[k.split('/')[1]];direction='ida' if '_ida_' in k else 'vuelta'
        for load in [0.,v['carga_copert']]:
            val=valorar_bus(s,load,library,v);val['punto']=point;val['sentido']=direction;val['carga_fisica']=load;val['referencia_id']='referencia_guagua_2';allseg.append(val)
            summary.append(dict(punto=point,sentido=direction,carga_fisica=load,longitud_km=float(s.length_m.sum()/1000),energia_mj_recorrido=float(val.energia_mj.sum())))
    segments=pd.concat(allseg,ignore_index=True);summary=pd.DataFrame(summary)
    guardar(calc,'data/silver/geografia/segmentos_lanzaderas.parquet',segments)
    origen_operacion=Path(operacion) if operacion is not None else root
    red=RedOperativa(leer(origen_operacion/BASE/'movimientos_diagnosticos.csv'),leer(origen_operacion/BASE/'pares_diagnosticos.csv'),leer(origen_operacion/PARADAS))
    lo,hi=min(red.posiciones.values()),max(red.posiciones.values());rows=[]
    for (origin,destination),(minutes,km) in red.arcos.items():
        for load in [0.,v['carga_copert']]:
            if origin.startswith('cabecera:') or destination.startswith('cabecera:'):
                point=(origin if origin.startswith('cabecera:') else destination).split(':')[1];direction='ida' if origin.startswith('cabecera:') else 'vuelta'
                f=summary[summary.punto.eq(point)&summary.sentido.eq(direction)&summary.carga_fisica.eq(load)].iloc[0]
                if abs(f.longitud_km-km)>1e-8:raise ValueError('Distancia de acceso incompatible con el arco.')
                energy=float(f.energia_mj_recorrido);category='acceso'
            else:
                direction='ida' if red.posiciones[destination]>red.posiciones[origin] else 'vuelta'
                f=summary[summary.punto.eq('INTERIOR')&summary.sentido.eq(direction)&summary.carga_fisica.eq(load)].iloc[0]
                raw=segments[segments.punto.eq('INTERIOR')&segments.sentido.eq(direction)&segments.carga_fisica.eq(load)].copy()
                a,b=(red.posiciones[origin]-lo)/(hi-lo),(red.posiciones[destination]-lo)/(hi-lo)
                if direction=='vuelta':a,b=1-a,1-b
                start,end=a*f.longitud_km*1000,b*f.longitud_km*1000
                cut=recortar_intervalos(raw,pd.DataFrame([dict(distance_start_m=start,distance_end_m=end)]))
                source=raw.assign(source_key=raw.segment_id.map(str)).set_index('source_key').hot_ec_mj_per_km
                energy=float((cut.length_m/1000*cut.segment_id_fuente.map(source)).sum());category='interior'
                if abs((end-start)/1000-km)>1e-8:raise ValueError('Distancia interior incompatible con el arco.')
            rows.append(dict(origen=origin,destino=destination,carga_copert=load,categoria=category,km=km,energia_hot_mj=energy))
    arcs=pd.DataFrame(rows);guardar(calc,ENERGIA+'/factores_por_arco_operativo.csv',arcs)
    # Solo se leen actividad y ponderaciones de la referencia de posicionamiento.
    # Se descartan explícitamente todas sus columnas energéticas anteriores.
    cols=['id_perfil','mes_modelo','id_salida','unidad_fisica_id','componente','categoria','origen_arco','destino_arco','carga_copert','peso_dias','km_arco']
    activity=pd.read_csv(origen_operacion/'data/silver/operacion/referencias_actividad/actividad_para_factor_posicionamiento.csv',sep=';',float_precision='round_trip',usecols=cols)
    activity=activity.merge(arcs.rename(columns={'origen':'origen_arco','destino':'destino_arco'}),on=['origen_arco','destino_arco','carga_copert','categoria'],validate='many_to_one')
    if activity.energia_hot_mj.isna().any() or (activity.km-activity.km_arco).abs().max()>1e-8:raise ValueError('Actividad técnica sin arco físico equivalente.')
    activity['vehiculo_km_anio']=activity.km_arco*activity.peso_dias;activity['hot_mwh_anio']=activity.energia_hot_mj*activity.peso_dias/3600
    summed=activity.groupby(['categoria','componente'],as_index=False)[['vehiculo_km_anio','hot_mwh_anio']].sum()
    summed['contraste_FTA_mwh_anio']=summed.hot_mwh_anio/(1-v['perdida_rendimiento_guaguas_contraste'])
    guardar(calc,ENERGIA+'/lanzaderas_resumen_energetico.csv',summed)
    titsa=[]
    for (line,shape),s in prep.tables['titsa/segmentos_fisicos'].groupby(['linea','shape_id'],sort=True):
        val=valorar_bus(s,v['carga_copert'],library,v)
        titsa.append(dict(linea=line,shape_id=shape,kilometros=float(s.length_m.sum()/1000),mwh_por_expedicion=float(val.energia_mj.sum()/3600)))
    guardar(calc,'data/silver/energia/titsa/perfiles.parquet',prep.tables['titsa/perfiles'])
    guardar(calc,'data/silver/energia/titsa/resumen_recorridos.csv',pd.DataFrame(titsa))
    b=pd.read_parquet(library);mask=pd.Series(True,index=b.index)
    for col,value in zip(['Category','Fuel','Segment','Euro Standard'],VEHICULO):mask&=b[col].eq(value)
    b=b[mask&b.rural_speed_kmh.eq(v['velocidad_copert'])&b.load_fraction.eq(v['carga_copert'])].copy()
    guardar(calc,'data/silver/energia/titsa/factores_utilizados.parquet',b)
    return arcs


def preparar_excursiones(calc,base,parametros):
    v={p['id']:p['valor_utilizado'] for p in parametros['parametros']};r=base['recorridos'].reset_index();patterns=base['patrones'].query("patron_id=='zona_proxima'").set_index('terminal_calculo')
    # El factor de excursiones mantiene pendiente cero en los dos escenarios.
    factors=pd.read_parquet(Path(calc)/'data/silver/energia/titsa/factores_utilizados.parquet')
    factor=factors.loc[factors.slope_class_pct.eq(0),'hot_ec_mj_per_km'].item()
    rows=[]
    for k in base['claves'].itertuples():
        for direction in ['hacia_teide','desde_teide']:
            rr=r[r.origen_id.eq(k.origen_id)&r.sentido.eq(direction)].iloc[0]
            km=rr.directa_km
            km+=patterns.loc[rr.terminal_calculo,'longitud_interior_ida_vuelta_km']/2
            rows.append(dict(origen_id=k.origen_id,colectivo=k.colectivo,sentido=direction,longitud_referencia_sentido_km=km,factor_hot_referencia_mj_km=factor))
    guardar(calc,'data/silver/energia/excursiones/referencias_por_origen.csv',pd.DataFrame(rows))


def preparar_alimentacion_titsa(root,calc,demanda,parametros,*,operacion=None):
    root,calc=Path(root),Path(calc);v={p['id']:p['valor_utilizado'] for p in parametros['parametros']}
    cfg=json.loads((root/'config/referencia_ordenacion_2028.json').read_text());cal=leer((Path(operacion) if operacion is not None else root)/cfg['captura']/'calendario.csv');weights=cal.target.value_counts()
    hh=demanda['calendario/demanda_horaria_calendario'];hh=hh[hh.metodo_calendario.eq('Estacional')];origins=demanda['territorio/origenes_por_modo_2025']
    xx=[];tt=[]
    for profile in weights.index:
        h=hh[hh.id_perfil.eq(profile)];z,_=aplicar_cupo_global(h,origins,v,cupo=650,incremento=0.)
        for name,acc in [('por_origen_dia',xx),('titsa_por_corredor_colectivo_dia',tt)]:
            a=z[name].copy();a['id_perfil']=profile;a['metodo_calendario']='Estacional';a['ambito']='Calendario';a['mes_modelo']=int(h.mes_modelo.iloc[0]);a['peso_dias']=int(weights[profile]);acc.append(a)
    x=pd.concat(xx,ignore_index=True);t=pd.concat(tt,ignore_index=True);keys=['id_perfil','punto','colectivo']
    x['demanda_OD_sin_TITSA']=x.visitas_coche+x.visitas_excursiones_resto_colectivo
    od=x.groupby(keys+['origen_id'],as_index=False).demanda_OD_sin_TITSA.sum();od['total_OD_cabecera']=od.groupby(keys).demanda_OD_sin_TITSA.transform('sum');od['peso_origen_condicionado']=od.demanda_OD_sin_TITSA/od.total_OD_cabecera
    if od.total_OD_cabecera.le(0).any():raise ValueError('TITSA sin distribución territorial condicionada.')
    z=t.merge(od,on=keys,validate='one_to_many');z['visitas_titsa_asignadas_dia']=z.visitas_titsa*z.peso_origen_condicionado;z['coches_alimentadores_dia']=z.visitas_titsa_asignadas_dia/v['ocupacion_coche']
    np.testing.assert_allclose(z.groupby(keys).visitas_titsa_asignadas_dia.sum().sort_index(),t.set_index(keys).visitas_titsa.sort_index(),atol=1e-10,rtol=0)
    coef=leer(calc/PENDIENTE/'correccion_por_origen_y_rama.csv');coef=coef[coef.caso_pendiente.eq('Referencia del Excel')&coef.rama.eq('transferidos')].copy();coef['mwh_unitario']=coef.energia_base_mwh_por_vehiculo_sentido+coef.correccion_mwh_por_vehiculo_sentido
    q=pd.concat([z.assign(sentido=d) for d in ['hacia_teide','desde_teide']],ignore_index=True).merge(coef[['origen_id','colectivo','sentido','alternativa_procedencia','mwh_unitario']],on=['origen_id','colectivo','sentido'],validate='many_to_many')
    if len(q)!=4*len(z) or q.mwh_unitario.isna().any():raise ValueError('Falta la alimentación privada de viajeros TITSA.')
    q['energia_mwh_anio']=q.coches_alimentadores_dia*q.peso_dias*q.mwh_unitario
    guardar(calc,ENERGIA+'/alimentacion_coche_TITSA_hipotesis_usuario.csv',q)


def preparar_unidades_reasignadas(root,calc,prep,segments,base,parametros):
    """Conservar las tres clases del residuo y la envolvente de los refuerzos."""
    root,calc=Path(root),Path(calc);v={p['id']:p['valor_utilizado'] for p in parametros['parametros']};curves=base['curvas'];factors=base['factores'];units=[]
    catalog=leer(root/'data/bronze/geografia/rutas_cabeceras/20261108_osrm/catalogo.csv').set_index('archivo')
    for resid,seg in segments.groupby('clase_sensibilidad_residuo',sort=False):
        ee=energia_pendiente_por_recorrido(seg,curves,factors,parametros,ocupacion=v['ocupacion_coche'])
        for x in ee.itertuples():units.append(dict(itinerary_id=x.itinerary_id,grupo_servicio=x.grupo_servicio,min_mj=x.energia_con_ajuste_convencional_mj,max_mj=x.energia_con_ajuste_convencional_mj))
    known=pd.DataFrame(units).groupby(['itinerary_id','grupo_servicio'],as_index=False).agg(min_mj=('min_mj','min'),max_mj=('max_mj','max'));units=known.to_dict('records')
    profiles=prep.tables['cabeceras/refuerzos/perfiles']
    for ident,p in profiles.groupby('itinerary_id',sort=False):
        p=p.sort_values('distance_m');km=np.diff(p.distance_m.to_numpy())/1000;km*=catalog.loc[ident,'km']/km.sum();dh=np.diff(p.elevation_m.to_numpy())
        for service in curves.grupo_servicio.unique():
            values=[]
            for road,mode in [('local','urban_off_peak'),('convencional','rural'),('rapida','highway')]:
                x=curves[curves.grupo_servicio.eq(service)&curves.clase_propuesta.eq(road)]
                mass=x.tara_mediana_kg.to_numpy()+v['ocupacion_coche']*v['masa_persona_turismo_kg']+v['equipaje_turismo_kg_coche']
                eta=np.where(x.familia_copert.eq('Petrol'),v['eficiencia_incremental_gasolina_pendiente'],v['eficiencia_incremental_diesel_pendiente'])
                flat=km[:,None]*x.hot_ec_mj_per_km.to_numpy()[None,:];gravity=dh[:,None]*mass[None,:]*9.81/1e6/eta[None,:]
                corrected=np.maximum(flat+gravity,0)
                f=factors[factors.grupo_servicio.eq(service)&factors.modo.eq(mode)&factors.velocidad_kmh.eq(v['velocidad_turismo_'+road])].aporte_conjunto_condicionado_min_mj_km.item()
                values.append(km*f+(corrected-flat)@x.peso_total.to_numpy())
            a=np.array(values);units.append(dict(itinerary_id=ident,grupo_servicio=service,min_mj=a.min(axis=0).sum(),max_mj=a.max(axis=0).sum()))
    uu=pd.DataFrame(units).merge(catalog.reset_index()[['archivo','origen_id','sentido']],left_on='itinerary_id',right_on='archivo',validate='many_to_one').drop(columns='archivo')
    if len(uu)!=78 or uu.duplicated(['itinerary_id','grupo_servicio']).any() or (uu.min_mj>uu.max_mj).any():raise ValueError('Unidades reasignadas incompletas o incoherentes.')
    uu['criterio']='Perfil dirigido y distancia OSRM; clase conocida o envolvente explícita de las clases no resueltas'
    guardar(calc,EXCEPCIONES+'/unidades_alimentadores_excepciones.csv',uu)
    guardar(calc,EXCEPCIONES+'/perfiles_alimentadores_excepciones.parquet',profiles)
    guardar(calc,ENERGIA+'/segmentos_por_via_para_valorar_alimentadores.parquet',segments)
    return uu
