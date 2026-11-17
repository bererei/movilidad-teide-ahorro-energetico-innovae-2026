"""Reconstruir demanda desde Bronze y las decisiones del libro/configuración.

No importa flujos históricos ni lee Silver/Gold. Conserva las funciones de
transformación existentes, el volumen de planificación y las ausencias.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.image as mpimg
from movilidad_teide.fuentes.preparacion_demanda import extraer_visor,preparar_aforos,preparar_zonas,preparar_gtfs,preparar_od,parametros_de_origen_aforos
from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.configuracion.ordenacion import leer_ordenacion
from movilidad_teide.demanda.actividad import comparar_tendencias_aforos,estimar_reparto_personas_aforos,anualizar_referencias_visor,comparar_tendencias_personas_visor,adjuntar_formato_publicado
from movilidad_teide.demanda.asignacion import demanda_por_origen,reconstruir_cabeceras,construir_asignacion
from movilidad_teide.demanda.origenes import seleccionar_origenes_representativos
from movilidad_teide.demanda.titsa import leer_demanda_publica_titsa,resumir_pasajeros_titsa
from movilidad_teide.demanda.separacion_titsa import clasificar_frontera,anualizar_titsa,separar_modos
from movilidad_teide.demanda.referencia_oficial import normalizar_aportes,distribuir_origenes
from movilidad_teide.demanda.escenarios_2028 import proyectar_demanda,MODOS
from movilidad_teide.demanda.planificacion_2028 import distribuir_referencia
from movilidad_teide.demanda.p85_alternativas import reconstruir_muestra
from movilidad_teide.demanda.calendario_anual import construir_perfiles_anuales
from movilidad_teide.operacion.dimensionamiento import identificar_matrices_visor


def referencias_territoriales(demand,origins,configuration,catalog):
    """Aplicar la correspondencia geográfica elegida, sin estimar nuevas rutas.

    Los pesos se calculan de la captura nativa. Las cabeceras proceden de las
    decisiones declaradas y los identificadores de los itinerarios; no se usan
    longitudes, perfiles o cantidades de tablas Silver.
    """
    by_head={c['origin_anchor_id']:c for c in configuration['corredores']}
    by_comparison={};by_origin={}
    for collection in ['origin_access_comparisons','study_origin_access_comparisons','coastal_valley_comparisons']:
        for key,spec in catalog.get(collection,{}).items():
            head=by_head[spec['head_reference_anchor_id']]
            row=(head['corredor'],head['cabecera'].replace('La Esperanza TF24','La Esperanza'))
            by_comparison[key]=row;by_origin[spec['origin_id']]=row
    for case in configuration['aproximaciones_geograficas_estudio']['casos']:
        by_origin[case['origen_id']]=by_comparison[case['comparacion_referencia_id']]
    if set(origins.origen_id)-set(by_origin):raise ValueError('Origen sin correspondencia geográfica configurada.')
    out=demand.copy();lookup=origins.set_index('origen_id').corredor_candidato
    out['corredor_fuente']=out.origen_id.map(lookup)
    out['corredor_calculo']=out.origen_id.map(lambda k:by_origin[k][0])
    out['cabecera_calculo']=out.origen_id.map(lambda k:by_origin[k][1])
    return out


def preparar_demanda(root,*,referencia=None):
    root=Path(root).resolve();reference=referencia if referencia is not None else leer_ordenacion(root);base=reference['base'];cfg=reference['valores'];v=reference['valores_modelo']
    if cfg['visitas_anio']!=2500000:raise ValueError('Esta referencia conserva 2.500.000 visitas.')
    params={p['id']:p for p in base['parametros']};tables={}
    def add(name,df):tables[name]=df;return df
    print('Extracción del Visor...',flush=True);visor=extraer_visor(root);profiles=visor['perfiles']
    for k in ['perfiles','centroides','rutas','inventario','controles']:add('visor/'+k,visor[k])
    catalogue=visor['tablas_html']['tab-base_01.csv'].copy();catalogue['Año']=pd.to_numeric(catalogue['Año'])
    indices=add('visor/indices',adjuntar_formato_publicado(identificar_matrices_visor(profiles,catalogue),catalogue))
    print('Aforos y reparto modal...',flush=True);data,annual,monthly=preparar_aforos(root)
    add('aforos/resumen_anual',annual);add('aforos/resumen_mensual',monthly)
    add('aforos/comparacion_tendencias',comparar_tendencias_aforos(annual,anios_excluidos=params['anios_excluidos']['valor_utilizado']))
    keys=['ocupacion_coche','ocupacion_guagua_aforo'];pieces=[]
    aforo_proposals,aforo_chosen,aforo_case,aforo_book_hash=parametros_de_origen_aforos(root)
    for label,chosen in [('Elecciones del caso',True),('Aforos recientes con ocupaciones históricas: condicionado',False)]:
        occupancy=aforo_chosen if chosen else aforo_proposals
        result=estimar_reparto_personas_aforos(annual,ocupacion_coche=occupancy['ocupacion_coche'],ocupacion_guagua=occupancy['ocupacion_guagua_aforo'],anios=[2024,2025],puntos=sorted(data.punto.unique()))
        pieces.append(result['conjunto_por_sentido'].assign(tipo_calculo=label,caso_excel=aforo_case,sha256_libro=aforo_book_hash))
    modal_counts=add('aforos/reparto_personas_aforos_conjunto',pd.concat(pieces,ignore_index=True))
    selected=modal_counts[modal_counts.anio.eq(2025)&modal_counts.sentido.eq('entrada')&modal_counts.ocupacion_coche_aplicada.notna()]
    if len(selected)!=1:raise ValueError('Reparto modal 2025 no único.')
    share=float(selected.fraccion_personas_paso_en_coche.iloc[0])
    print('OD y referencias territoriales...',flush=True);od,od_profiles=preparar_od(root);add('od/resumen_consultas',od);add('od/perfiles_zonas',od_profiles)
    zones,intersections=preparar_zonas(root);add('zonas/referencias',zones.drop(columns='geometry'));add('zonas/municipios',intersections)
    stops,s341=preparar_gtfs(root)
    configuration=json.loads((root/'config/asignacion_demanda.json').read_text());catalog=json.loads((root/'config/itinerarios.json').read_text())
    raw=demanda_por_origen(visor['centroides'],zones.drop(columns='geometry'))
    image=mpimg.imread(root/'data/bronze/documentacion/visor_teide/20261022_mapas_medianias/31_mapa_acceso_dominante_origen_medianias.png')
    reading=reconstruir_cabeceras(image,zones,configuration['mapa']);assigned=construir_asignacion(raw,reading,configuration['corredores'])
    mapping,demand,origins=seleccionar_origenes_representativos(assigned,visor['centroides'],zones,stops)
    add('territorio/demanda_por_origen',demand);add('territorio/correspondencia',mapping);add('territorio/origenes',origins.drop(columns='geometry'))
    represented=referencias_territoriales(demand,origins,configuration,catalog)
    print('Matrices originales TITSA...',flush=True)
    manifest=root/'data/bronze/transporte_publico/pasajeros_titsa/2025/20261022T171917Z_f6db4cae/metadatos.json'
    passengers,coverage,_=leer_demanda_publica_titsa(manifest,s341,zones)
    add('titsa/cobertura',coverage);add('titsa/resumen_pasajeros',resumir_pasajeros_titsa(passengers))
    capture=json.loads(manifest.read_text());boundary=gpd.read_file(root/'data/bronze/documentacion/contexto_informe/cartografia_parque/PN_Teide/Limites/Limite_Teide.shp').to_crs(4326).geometry.union_all()
    stops_month=[]
    for month in capture['meses']:
        source=next(x for x in month['archivos'] if x['tipo']=='paradas_csv');s=pd.read_csv(manifest.parent/source['archivo'])
        used=passengers[passengers.mes.eq(month['mes'])];ids=set(used.parada_entrada_id)|set(used.parada_salida_id);s=s[s.parada_id.isin(ids)].copy()
        if set(s.parada_id)!=ids:raise ValueError('Parada utilizada sin coordenada nativa.')
        points=gpd.GeoSeries(gpd.points_from_xy(s.parada_longitud,s.parada_latitud),crs=4326);s['dentro_parque']=points.map(boundary.covers).to_numpy();s['mes']=month['mes'];stops_month.append(s[['mes','parada_id','dentro_parque']])
    classified=clasificar_frontera(passengers,pd.concat(stops_month,ignore_index=True));days,daily,year=anualizar_titsa(classified)
    add('titsa/referencias_diarias',daily);add('titsa/estimacion_anual',year)
    print('Normalización y calendario de 2.500.000 visitas...',flush=True)
    source=json.loads((root/'data/bronze/documentacion/visitas_parque/metadatos_2025.json').read_text())
    # Esta escala de 2025 pertenece a la preparación conservada. La referencia
    # de 2028 se normaliza después a 2.500.000, sin crecimiento adicional.
    ix=indices[indices.anio.eq(2025)];p=profiles[profiles.matrix_index.isin(ix.matrix_index)&profiles.direccion.eq('subida')].copy()
    p=p.merge(ix[['matrix_index','mes_publicado','tipo_dia_publicado']],on='matrix_index',validate='many_to_one')
    groups=['access_corridor','tipo_dia_publicado','hora_servicio'];cohorts=['extranjero','espana_no_tenerife','tenerife_no_frecuente','tenerife_resto']
    h=p.groupby(groups,as_index=False)[cohorts].sum().melt(id_vars=groups,value_vars=cohorts,var_name='colectivo',value_name='suma_tres_referencias')
    from .escenarios_2028 import calendario
    h['dias_calendario']=h.tipo_dia_publicado.map(calendario(2025));h['aporte_anual_od']=h.suma_tres_referencias*h.dias_calendario/3;h['sentido']='entrada';h['anio']=2025
    normalized=normalizar_aportes(h,source['visitas_anuales'],claves=groups+['colectivo'])
    modal=separar_modos(normalized,year,share);totals=normalized.groupby(['access_corridor','colectivo'],as_index=False).visitas_normalizadas_2025.sum().rename(columns={'access_corridor':'corredor_fuente'})
    origin=distribuir_origenes(represented,totals)
    origin=origin[['origen_id','colectivo','sentido','corredor_fuente','corredor_calculo','cabecera_calculo','viajes_persona_media_57_matrices','en_ambito_anual','peso_origen_condicionado','visitas_normalizadas_2025','estado']]
    total_modal=modal.groupby(['access_corridor','colectivo'],as_index=False)[['visitas_normalizadas_2025',*MODOS]].sum()
    names={c:'fraccion_'+c for c in MODOS}
    for c in MODOS:total_modal[names[c]]=total_modal[c]/total_modal.visitas_normalizadas_2025
    origin=origin.merge(total_modal[['access_corridor','colectivo',*names.values()]].rename(columns={'access_corridor':'corredor_fuente'}),on=['corredor_fuente','colectivo'],how='left',validate='many_to_one')
    for c in MODOS:origin[c]=origin.visitas_normalizadas_2025*origin[names[c]]
    origin['visitas_lanzadera_acceso_por_sustitucion_titsa']=origin.visitas_titsa;origin['modo_titsa_observado_en_origen']=False;origin['apto_para_calcular_km_titsa']=False
    add('territorio/origenes_por_modo_2025',origin)
    captation={c:params[k]['valor_utilizado'] for c,k in zip(cohorts,['captacion_extranjero','captacion_nacional','captacion_local','captacion_frecuente'])}
    annualized=[]
    for yy in [2025,2028]:annualized.append(anualizar_referencias_visor(profiles,indices,captation,anio_base=2025,anio_calendario=yy,criterio=params['anualizacion_personas']['valor_utilizado'],hora_inicio=int(params['hora_inicio_acceso']['valor_utilizado']),hora_fin=int(params['hora_fin_acceso']['valor_utilizado'])) )
    add('actividad/demanda_anual_referencia_visor',pd.concat([x['demanda_anual_referencia_visor'] for x in annualized],ignore_index=True))
    add('actividad/calendario_anualizacion',pd.concat([x['calendario_anualizacion'].assign(anio_calendario=yy) for yy,x in zip([2025,2028],annualized)],ignore_index=True))
    trends=comparar_tendencias_personas_visor(profiles,indices,captation);trend=add('actividad/tendencias_personas_visor',trends['tendencias_personas_visor'])
    chosen=trend[trend.colectivo.eq('total_sistema')&trend.metodo.eq('cagr_2024_2025_mismo_formato')]
    if len(chosen)!=1 or not chosen.aplicable_mismo_formato.all():raise ValueError('Falta una tasa comparable única del Visor.')
    projected=proyectar_demanda(modal,anio=2028,tasa=float(chosen.tasa_anual.iloc[0]));planned=distribuir_referencia(projected,cfg['visitas_anio'],share)
    sample,_=reconstruir_muestra(profiles,indices,planned,total=cfg['visitas_anio'],fraccion_coche=share,hora_inicio=cfg['hora_inicio_acceso'],hora_fin=v['hora_fin_acceso'])
    calendars=[]
    for method in ['Estacional','Media anual']:
        _,hh=construir_perfiles_anuales(sample,metodo=method);hh['id_perfil']=('E_' if method=='Estacional' else 'A_')+hh.id_perfil;calendars.append(hh)
    hourly=add('calendario/demanda_horaria_calendario',pd.concat(calendars,ignore_index=True))
    for method,g in hourly.groupby('metodo_calendario'):
        np.testing.assert_allclose((g.visitas_persona_dia*g.dias_calendario).sum(),cfg['visitas_anio'],atol=1e-8,rtol=0)
    return tables,{'visitas_sin_y_con':cfg['visitas_anio'],'restricciones':cfg,'filas_pasajeros_titsa':len(passengers),'origenes':len(origins),'fraccion_coche':share,'tasa_proyeccion_titsa':float(chosen.tasa_anual.iloc[0]),'parametros_modificados':False,'energia_recalculada':False,'geometria_y_perfiles_energeticos_reconstruidos':False}
