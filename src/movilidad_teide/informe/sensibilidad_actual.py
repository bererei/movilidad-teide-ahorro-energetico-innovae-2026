"""Sensibilidad con actividad vigente y coeficientes físicos conservados.

No modifica el escenario principal ni vuelve a consultar COPERT. Reconstruye
los alimentadores reasignados con las mismas geometrías y reglas vigentes.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from movilidad_teide.energia.pendiente import energia_pendiente_por_recorrido


def calcular_sensibilidad_fisica(root, datos):
    root = Path(root)
    ref = datos['referencia']; cfg = ref['valores']; params = ref['base']
    v = ref['valores_modelo']; cal = datos['tablas']['calendario_operativo']
    read = lambda p: pd.read_csv(p, sep=';', float_precision='round_trip')
    old = root/'data/silver/energia/referencias_unitarias/pendiente_turismos'
    energy = root/ref['indice']['energia']; extra = root/ref['indice']['excepciones']
    capture = root/ref['indice']['captura']
    co = read(old/'correccion_por_origen_y_rama.csv')
    curves = pd.read_parquet(old/'curvas_y_masas.parquet')
    factors = read(root/'data/silver/vehiculos/ponderacion/factores.csv')
    segments = pd.read_parquet(energy/'segmentos_por_via_para_valorar_alimentadores.parquet')
    profiles = pd.read_parquet(extra/'perfiles_alimentadores_excepciones.parquet')
    catalog = read(root/ref['indice']['catalogo_cabeceras']/'catalogo.csv').set_index('archivo')
    saved = read(extra/'unidades_alimentadores_excepciones.csv')
    titsa = read(energy/'alimentacion_coche_TITSA_hipotesis_usuario.csv')
    weights = cal.perfil.value_counts()
    titsa = titsa[titsa.id_perfil.isin(weights.index)].copy()
    titsa['coches_anio'] = titsa.coches_alimentadores_dia*titsa.id_perfil.map(weights)
    native, moved = [], []
    for (q,mx,profile), days in cal.groupby(['cupo','max_programadas_programa','perfil']):
        folder = capture/'ofertas'/str(q)/str(mx)/profile
        x = read(folder/'origenes.csv'); x['peso_fechas'] = len(days); native.append(x)
        path = folder/'traslados.csv'
        if path.stat().st_size > 3:
            z = read(path); z['coches_anio'] = z.visitas_persona_dia/cfg['ocupacion_coche']*len(days); moved.append(z)
    native = pd.concat(native,ignore_index=True)
    for c in ['coches_sin_dia','coches_autorizados_dia','visitas_coche_transferidas_dia']:
        native[c] *= native.peso_fechas
    activity = native.groupby(['origen_id','colectivo'])[['coches_sin_dia','coches_autorizados_dia','visitas_coche_transferidas_dia']].sum()
    moved = pd.concat(moved,ignore_index=True)
    moved = moved.groupby(['origen_id','colectivo'],as_index=False).coches_anio.sum()
    methods = [('Referencia del Excel','Mediana, transmisión 0,85 y reducción en descenso',{}),
        ('Tara P25','Tara del cuartil inferior',{'estadistico':'Cuartil inferior (P25)'}),
        ('Tara P75','Tara del cuartil superior',{'estadistico':'Cuartil superior (P75)'}),
        ('Transmisión 0,95','Transmisión 0,95',{'multiplicador_eta':0.95/0.85}),
        ('Descenso sin reducción','Sin reducción de consumo en descenso',{'tratamiento':'Sin reducción de consumo en descenso'}),
        ('Sin corrección','Sin ajuste gravitatorio convencional',{})]
    results=[]; unit_records=[]
    for case,label,overrides in methods:
        print('Sensibilidad física vigente:',label,flush=True)
        units=[]
        # Las rutas ya clasificadas conservan tres alternativas para el residuo.
        for resid, seg in segments.groupby('clase_sensibilidad_residuo',sort=False):
            ee=energia_pendiente_por_recorrido(seg,curves,factors,params,ocupacion=cfg['ocupacion_coche'],**overrides)
            for x in ee.itertuples():
                val=x.energia_base_mj_recorrido if case=='Sin corrección' else x.energia_con_ajuste_convencional_mj
                units.append(dict(itinerary_id=x.itinerary_id,grupo_servicio=x.grupo_servicio,min_mj=val,max_mj=val))
        known=pd.DataFrame(units)
        known=known.groupby(['itinerary_id','grupo_servicio'],as_index=False).agg(min_mj=('min_mj','min'),max_mj=('max_mj','max'))
        units=known.to_dict('records')
        for ident,profile in profiles.groupby('itinerary_id',sort=False):
            p=profile.sort_values('distance_m');km=np.diff(p.distance_m.to_numpy())/1000
            km*=catalog.loc[ident,'km']/km.sum()
            dh=np.diff(p.elevation_m.to_numpy())
            for service in curves.grupo_servicio.unique():
                values=[]
                for road,mode in [('local','urban_off_peak'),('convencional','rural'),('rapida','highway')]:
                    x=curves[curves.grupo_servicio.eq(service)&curves.clase_propuesta.eq(road)]
                    tara={'Tara P25':'tara_p25_kg','Tara P75':'tara_p75_kg'}.get(case,'tara_mediana_kg')
                    mass=x[tara].to_numpy()+cfg['ocupacion_coche']*v['masa_persona_turismo_kg']+v['equipaje_turismo_kg_coche']
                    eta=np.where(x.familia_copert.eq('Petrol'),v['eficiencia_incremental_gasolina_pendiente'],v['eficiencia_incremental_diesel_pendiente'])*overrides.get('multiplicador_eta',1)
                    base=km[:,None]*x.hot_ec_mj_per_km.to_numpy()[None,:]
                    gravity=dh[:,None]*mass[None,:]*9.81/1e6/eta[None,:]
                    corrected=base+np.maximum(gravity,0) if case=='Descenso sin reducción' else np.maximum(base+gravity,0)
                    f=factors[factors.grupo_servicio.eq(service)&factors.modo.eq(mode)&factors.velocidad_kmh.eq(v['velocidad_turismo_'+road])].aporte_conjunto_condicionado_min_mj_km.item()
                    value=km*f
                    if case!='Sin corrección': value=value+(corrected-base)@x.peso_total.to_numpy()
                    values.append(value)
                a=np.array(values)
                units.append(dict(itinerary_id=ident,grupo_servicio=service,min_mj=a.min(axis=0).sum(),max_mj=a.max(axis=0).sum()))
        uu=pd.DataFrame(units)
        if uu.duplicated(['itinerary_id','grupo_servicio']).any(): raise ValueError('Alimentador duplicado.')
        unit_records.append(uu.assign(contraste=label))
        if case=='Referencia del Excel':
            merged=saved.merge(uu,on=['itinerary_id','grupo_servicio'],suffixes=('_guardado','_reconstruido'),validate='one_to_one')
            assert len(merged)==len(saved)
            for c in ['min_mj','max_mj']:
                np.testing.assert_allclose(merged[c+'_guardado'],merged[c+'_reconstruido'],atol=1e-8,rtol=0)
        uu=uu.merge(catalog.reset_index()[['archivo','origen_id']],left_on='itinerary_id',right_on='archivo',validate='many_to_one')
        lookup=uu.groupby(['origen_id','grupo_servicio'])[['min_mj','max_mj']].sum()/3600
        z=co[co.caso_pendiente.eq('Referencia del Excel' if case=='Sin corrección' else case)].copy()
        z['unit']=z.energia_base_mwh_por_vehiculo_sentido
        if case!='Sin corrección':z['unit']+=z.correccion_mwh_por_vehiculo_sentido
        for alt in datos['tablas']['central'].asignacion_turismos:
            a=z[z.alternativa_procedencia.eq(alt)]
            rates=a.groupby(['origen_id','colectivo','rama']).unit.sum().unstack('rama')
            act=activity.join(rates,validate='one_to_one')
            if act[['antes','autorizados','transferidos']].isna().any().any():raise ValueError('Actividad sin coeficiente.')
            sin_car=float((act.coches_sin_dia*act.antes).sum())
            con_car=float((act.coches_autorizados_dia*act.autorizados).sum())
            feed=float((act.visitas_coche_transferidas_dia/cfg['ocupacion_coche']*act.transferidos).sum())
            removed=newlo=newhi=0.
            for m in moved.itertuples():
                removed+=rates.loc[m.origen_id,m.colectivo]['transferidos']*m.coches_anio
                service='Alquiler sin conductor (A01)' if m.colectivo=='extranjero' or (m.colectivo=='espana_no_tenerife' and alt.endswith('alquiler')) else 'Particular sin especificar (B00)'
                u=lookup.loc[m.origen_id,service];newlo+=u.min_mj*m.coches_anio;newhi+=u.max_mj*m.coches_anio
            # La alimentación TITSA usa el mismo coeficiente por origen/sentido.
            rate=a[a.rama.eq('transferidos')].set_index(['origen_id','colectivo','sentido']).unit
            tt=titsa[titsa.alternativa_procedencia.eq(alt)].copy()
            tt['unit']=rate.reindex(pd.MultiIndex.from_frame(tt[['origen_id','colectivo','sentido']])).to_numpy()
            if tt.unit.isna().any():raise ValueError('Alimentación TITSA sin referencia.')
            ft=float((tt.coches_anio*tt.unit).sum())
            daily=datos['tablas']['actividad_diaria'];dd=daily[daily.asignacion_turismos.eq(alt)]
            base=datos['tablas']['central'].set_index('asignacion_turismos').loc[alt]
            sin=sin_car+dd[['sin_excursion_mwh_dia','sin_TITSA_mwh_dia']].sum().sum()
            common=float(dd[['con_excursion_mwh_dia','con_lanzadera_comercial_mwh_dia','con_lanzadera_vacia_mwh_dia']].sum().sum())+base.posicionamiento_mwh
            lo=con_car+feed-removed+newlo+ft+common
            hi=con_car+feed-removed+newhi+ft+common
            if case=='Referencia del Excel':
                np.testing.assert_allclose([sin,lo,hi],[base.sin_identificado_mwh,base.con_identificado_min_mwh,base.con_identificado_max_mwh],atol=1e-8,rtol=0)
            for treatment,delta in [('Consumo en caliente',0.),('Contraste FTA de lanzaderas y posicionamiento',float(dd[['con_lanzadera_comercial_mwh_dia','con_lanzadera_vacia_mwh_dia']].sum().sum()+base.posicionamiento_mwh)/9)]:
                results.append({'Contraste físico':label,'Asignación de turismos':alt.replace(': ',' en '),'Tratamiento energético':treatment,'Visitas totales':cfg['visitas_anio'],'Sin (MWh)':sin,'Con mínimo (MWh)':lo+delta,'Con máximo (MWh)':hi+delta,'Ahorro mínimo (MWh)':sin-hi-delta,'Ahorro máximo (MWh)':sin-lo-delta})
    result=pd.DataFrame(results)
    for name in ['Sin','Con mínimo','Con máximo','Ahorro mínimo','Ahorro máximo']:
        result[name+' (tep)']=result[name+' (MWh)']/cfg['mwh_por_tep']
        result[name+' (kWh/visita)']=1000*result[name+' (MWh)']/cfg['visitas_anio']
    return result,pd.concat(unit_records,ignore_index=True)
