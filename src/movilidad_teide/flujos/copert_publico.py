"""Comprobar el balance vigente con bibliotecas de COPERT recién ejecutadas.

La prueba utiliza una copia temporal de entradas y sustituye en ella las
bibliotecas y sus coeficientes derivados. Los originales nunca se escriben.
"""
from pathlib import Path
import json,hashlib,shutil
import numpy as np
import pandas as pd
from movilidad_teide.vehiculos.copert_publico import new_directory,dump,digest
from movilidad_teide.energia.referencia import referencia_ponderada
from movilidad_teide.opciones import METODO_CONSUMO
from movilidad_teide.energia.preparacion_pendiente import calcular_coeficientes_pendiente
from movilidad_teide.flujos.comprobaciones import comparar_tablas
from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.flujos.ordenacion_vigente import consultar_ordenacion,reproducir_ordenacion
from movilidad_teide.informe.sensibilidad_actual import calcular_sensibilidad_fisica
from movilidad_teide.flujos.compartida_2028 import BASE,PARADAS
from movilidad_teide.operacion.red_compartida import RedOperativa

def verify_study(root,copert_results,destination):
    root=Path(root).resolve();fresh=Path(copert_results).resolve();out=new_directory(destination)
    if out==root or out.is_relative_to(root):raise ValueError('La comprobación debe quedar fuera del repositorio.')
    source=json.loads((fresh/'verificacion_copert.json').read_text())
    assert source['motor_copert_ejecutado'] and source['consultas']==34 and source['maxima_diferencia_mj_km']<=1e-12
    shadow=out/'copia_entradas';shadow.mkdir()
    # Solo se crean enlaces nuevos en la copia temporal; nunca se reemplaza un
    # directorio o archivo original. Las sustituciones rompen antes el enlace.
    for area in ['config','data']:
        for p in (root/area).rglob('*'):
            if not p.is_file():continue
            target=shadow/p.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(p)
    changes=[]
    def replace(name,writer):
        p=shadow/name;p.parent.mkdir(parents=True,exist_ok=True)
        old=digest(p) if p.exists() else None
        if p.is_symlink():p.unlink()
        writer(p)
        changes.append({'archivo':name,'sha256_original':old,'sha256_nuevo':digest(p)})
    def save_csv(name,table):replace(name,lambda p:table.to_csv(p,sep=';',index=False,float_format='%.17g'))
    def save_parquet(name,table):replace(name,lambda p:table.to_parquet(p,index=False))
    def rd(name):return pd.read_csv(shadow/name,sep=';',float_precision='round_trip')
    idx=json.loads((root/'config/referencia_ordenacion_2028.json').read_text())
    F='data/silver/vehiculos/ponderacion'
    P='data/silver/energia/referencias_unitarias/pendiente_turismos';E=idx['energia'];X=idx['excepciones']
    factor_root=fresh
    if fresh==(root/'data/silver/copert/ejecuciones').resolve():
        factor_root=root/'data/silver/copert/factores'
    main=pd.read_parquet(factor_root/'factores_turismos.parquet');multi=pd.read_parquet(factor_root/'factores_multienergia.parquet');bus=pd.read_parquet(factor_root/'factores_autocar.parquet')
    save_parquet('data/silver/copert/factores/factores_turismos.parquet',main)
    save_parquet('data/silver/copert/factores/factores_multienergia.parquet',multi)
    save_parquet('data/silver/copert/factores/factores_autocar.parquet',bus)
    main['primary_control_fraction']=np.nan
    print('Reconstruyendo ponderación con factores COPERT nuevos...',flush=True)
    weights=referencia_ponderada(rd('data/silver/vehiculos/flota_teide/representacion_tecnica/perfiles_elegidos_diagnostico.csv'),
        pd.concat([main,multi],ignore_index=True),rd('data/silver/vehiculos/flota_teide/representacion_tecnica/factores_elegidos_resumen.csv'),
        metodo=METODO_CONSUMO,control_primario=.5)
    for name,t in weights.items():save_csv(F+'/'+name+'.csv',t)
    print('Reconstruyendo masas, pendiente y coeficientes privados...',flush=True)
    stage=calcular_coeficientes_pendiente(shadow,leer_parametros(shadow))
    private_checks=comparar_tablas(root/P,stage,nombre='coeficientes_pendiente',
        columnas_por_tabla={'correccion_por_origen_y_rama':list(stage.tablas['correccion_por_origen_y_rama'])},
        claves_por_tabla={'correccion_por_origen_y_rama':['caso_pendiente','alternativa_procedencia','origen_id','colectivo','sentido','rama']})
    for name,t in stage.tablas.items():save_csv(P+'/'+name+'.csv',t)
    for name,t in stage.auxiliares.items():save_parquet(P+'/'+name+'.parquet',t)

    # Sustituir los siete factores de TITSA y valorar todos los arcos de
    # lanzadera desde los factores nuevos por segmento y carga.
    save_parquet(idx['titsa_pendiente']['directorio']+'/factores_utilizados.parquet',bus[bus.load_fraction.eq(.5)].copy())
    segment_path='data/silver/geografia/segmentos_lanzaderas.parquet'
    seg=pd.read_parquet(shadow/segment_path);seg=seg[seg.referencia_id.eq('referencia_guagua_2')].copy()
    for load in [0.,.5]:
        mask=seg.carga_fisica.eq(load);f=bus[bus.load_fraction.eq(load)].sort_values('slope_class_pct')
        seg.loc[mask,'hot_ec_mj_per_km']=np.interp(seg.loc[mask,'slope_pct'],f.slope_class_pct,f.hot_ec_mj_per_km)
    seg['energia_mj']=seg.length_m/1000*seg.hot_ec_mj_per_km
    red=RedOperativa(rd(BASE+'/movimientos_diagnosticos.csv'),rd(BASE+'/pares_diagnosticos.csv'),rd(PARADAS))
    low,high=min(red.posiciones.values()),max(red.posiciones.values())
    arcs=rd(E+'/factores_por_arco_operativo.csv');energy=[]
    for a in arcs.itertuples():
        if a.categoria=='acceso':
            point=(a.origen if a.origen.startswith('cabecera:') else a.destino).split(':')[1]
            direction='ida' if a.origen.startswith('cabecera:') else 'vuelta'
            s=seg[seg.punto.eq(point)&seg.sentido.eq(direction)&seg.carga_fisica.eq(a.carga_copert)]
            val=float(s.energia_mj.sum())
        else:
            direction='ida' if red.posiciones[a.destino]>red.posiciones[a.origen] else 'vuelta'
            s=seg[seg.punto.eq('INTERIOR')&seg.sentido.eq(direction)&seg.carga_fisica.eq(a.carga_copert)]
            length=s.length_m.sum();u=(red.posiciones[a.origen]-low)/(high-low);v=(red.posiciones[a.destino]-low)/(high-low)
            if direction=='vuelta':u,v=1-u,1-v
            overlap=np.maximum(0,np.minimum(s.distance_end_m,v*length)-np.maximum(s.distance_start_m,u*length))
            val=float((overlap/1000*s.hot_ec_mj_per_km).sum())
        energy.append(val)
    np.testing.assert_allclose(arcs.energia_hot_mj,energy,rtol=0,atol=1e-8);arcs.energia_hot_mj=energy;save_csv(E+'/factores_por_arco_operativo.csv',arcs)
    moves=rd(E+'/lanzaderas_por_movimiento_y_arco.csv');lookup=arcs.set_index(['origen','destino','carga_copert']).energia_hot_mj
    moves['hot_mj_arco']=[lookup.loc[a.origen_arco,a.destino_arco,a.carga_copert] for a in moves.itertuples()]
    moves['hot_mwh_anio']=moves.hot_mj_arco*moves.peso_dias/3600
    summary=rd(E+'/lanzaderas_resumen_energetico.csv');g=moves.groupby(['categoria','componente']).hot_mwh_anio.sum()
    summary['hot_mwh_anio']=[g.loc[a.categoria,a.componente] for a in summary.itertuples()]
    summary['contraste_FTA_mwh_anio']=summary.hot_mwh_anio/.9;save_csv(E+'/lanzaderas_resumen_energetico.csv',summary)

    # Las excursiones mantienen el factor plano de la referencia, ahora salido
    # de la consulta nueva. Los recorridos y la actividad no se cambian.
    common_path='data/silver/energia/excursiones/referencias_por_origen.csv'
    common=rd(common_path);flat=bus[bus.load_fraction.eq(.5)&bus.slope_class_pct.eq(0)].hot_ec_mj_per_km.item()
    common.factor_hot_referencia_mj_km=flat;save_csv(common_path,common)
    coef=stage.tablas['correccion_por_origen_y_rama'];co=coef[coef.caso_pendiente.eq('Referencia del Excel')&coef.rama.eq('transferidos')].copy()
    co['unit']=co.energia_base_mwh_por_vehiculo_sentido+co.correccion_mwh_por_vehiculo_sentido
    lookup=co.set_index(['origen_id','colectivo','sentido','alternativa_procedencia']).unit
    feed=rd(E+'/alimentacion_coche_TITSA_hipotesis_usuario.csv')
    feed['mwh_unitario']=[lookup.loc[a.origen_id,a.colectivo,a.sentido,a.alternativa_procedencia] for a in feed.itertuples()]
    feed['energia_mwh_anio']=feed.coches_alimentadores_dia*feed.peso_dias*feed.mwh_unitario;save_csv(E+'/alimentacion_coche_TITSA_hipotesis_usuario.csv',feed)
    data=consultar_ordenacion(root)
    print('Reconstruyendo alimentadores reasignados con las curvas nuevas...',flush=True)
    sens,units=calcular_sensibilidad_fisica(shadow,data)
    expected,_=calcular_sensibilidad_fisica(root,data)
    pd.testing.assert_frame_equal(sens,expected,check_dtype=False,check_exact=False,rtol=0,atol=1e-8)
    refunits=units[units.contraste.eq('Mediana, transmisión 0,85 y reducción en descenso')].set_index(['itinerary_id','grupo_servicio'])
    feeders=rd(X+'/unidades_alimentadores_excepciones.csv')
    for col in ['min_mj','max_mj']:feeders[col]=[refunits.loc[a.itinerary_id,a.grupo_servicio][col] for a in feeders.itertuples()]
    save_csv(X+'/unidades_alimentadores_excepciones.csv',feeders)
    # Las únicas modificaciones del índice temporal son huellas de las nuevas
    # entradas equivalentes; los valores/decisiones del estudio son idénticos.
    for row in changes:
        if row['archivo'] in idx['entradas_sha256']:idx['entradas_sha256'][row['archivo']]=row['sha256_nuevo']
    replace('config/referencia_ordenacion_2028.json',lambda p:dump(p,idx))
    print('Reproducción anual con coeficientes recién reconstruidos...',flush=True)
    _,checks=reproducir_ordenacion(shadow,out/'reproduccion_anual')
    checks.to_csv(out/'comparacion_anual.csv',sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
    pd.DataFrame(private_checks).to_csv(out/'comparacion_coeficientes_privados.csv',sep=';',index=False,encoding='utf-8-sig')
    sens.to_csv(out/'sensibilidad_fisica_reproducida.csv',sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
    dump(out/'sustituciones_en_copia_temporal.json',changes)
    verification={'visitas_sin_y_con':2500000,'bibliotecas_recien_ejecutadas':True,'coeficientes_privados_reconstruidos':True,
        'coeficientes_autocar_reconstruidos':True,'agregaciones_historicas_recalculadas':False,'productos_fisicos_comparados':len(private_checks),'sensibilidad_fisica_equivalente':True,'productos_anuales_comparados':len(checks),
        'maxima_diferencia_absoluta_anual':float(checks.maxima_diferencia_absoluta.max()),'tolerancia_absoluta_anual':1e-8,
        'informe_anexos_y_originales_modificados':False,'prueba_en_instalacion_publica_limpia':False,
        'alcance':'Copia temporal con datos locales y bibliotecas nuevas; mismos parámetros, visitas y restricciones; no nueva búsqueda de horarios',
        'verificacion_copert_sha256':digest(fresh/'verificacion_copert.json')}
    dump(out/'verificacion_estudio.json',verification);return verification
