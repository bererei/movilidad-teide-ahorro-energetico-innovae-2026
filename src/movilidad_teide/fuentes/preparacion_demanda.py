"""Preparaciones de fuentes nativas: extracción sin consultar tablas Silver.

Conserva las reglas de los cuadernos anteriores a bb1bc06, ahora como funciones
explícitas. Las consultas de Internet no forman parte de esta reconstrucción.
"""
from pathlib import Path
import csv,json,math,re,zipfile
import numpy as np
import pandas as pd
import geopandas as gpd
from openpyxl import load_workbook
from .visor import Documento,recorrer,texto,constante_literal
from .aforos import leer_filas_aforo,leer_csv_aforos,normalizar_horas_aforo,resumir_aforos
from .zonas import leer_poligonos,cruzar_referencias


VISOR='data/bronze/documentacion/visor_teide/20261016T154507Z_a35edd7a'
ZONAS='data/bronze/demanda/odviewer/20261016T101617Z/zonificaciones/zonificaciones_odviewer.zip'
GTFS='data/bronze/transporte_publico/gtfs/20261016T093551Z_2d6681e8/001_fichero_zip_de_google_tr_9f291323.zip'


def extraer_visor(root):
    root=Path(root);folder=root/VISOR;parser=Documento()
    parser.feed((folder/'index.html').read_text())
    tables={};inventory=[]
    for panel in recorrer(parser.raiz):
        if 'data-tab-panel' not in panel['attrs']:continue
        section=panel['attrs']['id'];title='';number=0
        for node in recorrer(panel):
            if node['tag'] in {'h2','h3','h4'}:title=' '.join(texto(node).split())
            if node['tag']!='table':continue
            number+=1;rows=[]
            for tr in recorrer(node):
                if tr['tag']=='tr':rows.append([' '.join(texto(c).split()) for c in tr['children'] if isinstance(c,dict) and c['tag'] in {'th','td'}])
            if not rows or any(len(x)!=len(rows[0]) for x in rows):raise ValueError('Tabla HTML irregular.')
            name=f'{section}_{number:02d}.csv' if len(rows)>1 else None
            if name:tables[name]=pd.DataFrame(rows[1:],columns=rows[0])
            inventory.append(dict(seccion=section,tabla=number,titulo=title,filas=len(rows)-1,archivo=name,tipo='estatica' if name else 'dinamica_sin_filas_en_html',url='https://mp3net.org/dimServTeide/#'+section))
    javascript=(folder/'coeficientes_servicio_teide.js').read_text();marker='window.TEIDE_COEF_APP_DATA_BY_ARCH = '
    start=javascript.index(marker)+len(marker);native,length=json.JSONDecoder().raw_decode(javascript[start:]);code=javascript[start+length:]
    profiles={};checks=[]
    for architecture,content in native.items():
        meta=content['meta'];p=pd.DataFrame(content['rows'],columns=meta['columns'])
        keys=['direccion','access_corridor','hora_servicio','matrix_index'];segments=['extranjero','espana_no_tenerife','tenerife_no_frecuente','tenerife_resto']
        if len(p)!=meta['records'] or p.duplicated(keys).any() or p[keys].isna().any().any():raise ValueError('Claves de Visor inválidas.')
        if not p.hora_servicio.between(0,23).all() or p.matrix_index.nunique()!=57 or not np.isfinite(p[segments]).all().all() or p[segments].lt(0).any().any():raise ValueError('Demanda de Visor inválida.')
        p['arquitectura']=architecture;profiles[architecture]=p
        checks.append(dict(control='datos_'+architecture,resultado='correcto',registros=len(p),matrices=p.matrix_index.nunique()))
    routes=[]
    for architecture,models in constante_literal('routeModels',codigo=code).items():
        for corridor,v in models.items():routes.append(dict(arquitectura=architecture,corredor=corridor,etiqueta=v['label'],km_un_sentido_modelo=v['kmOneWay'],min_subida_modelo=v['subidaMin'],min_bajada_modelo=v['bajadaMin']))
    raw=(folder/'heatmap_od_data.js').read_text();marker='window.TEIDE_OD_HEATMAP = ';heat,_=json.JSONDecoder().raw_decode(raw[raw.index(marker)+len(marker):])
    centroids=pd.DataFrame(heat['points'],columns=heat['meta']['point_columns'])
    if len(centroids)!=heat['meta']['point_count'] or not np.isfinite(centroids[['lon','lat']]).all().all():raise ValueError('Centroides inválidos.')
    for segment in heat['segments']:
        for prefix,total in [('gen_','generated_sum'),('attr_','attracted_sum')]:
            if not math.isclose(centroids[prefix+segment['id']].sum(),segment[total],rel_tol=1e-5,abs_tol=.01):raise ValueError('Suma de centroides incompatible con su redondeo.')
    checks.append(dict(control='centroides_calor_teide',resultado='correcto',registros=len(centroids),matrices=heat['meta']['matrix_count']))
    return {'perfiles':profiles['medianias'],'centroides':centroids,'rutas':pd.DataFrame(routes),'inventario':pd.DataFrame(inventory),'controles':pd.DataFrame(checks),'tablas_html':tables}


def preparar_aforos(root):
    """Conservar valores y corregir solo el patrón temporal documentado de 2025."""
    rows=[];measures=['ecoches','eguaguas','scoches','sguaguas']
    for p in sorted((Path(root)/'data/bronze/aforos').iterdir()):
        if p.suffix not in {'.csv','.xlsx'}:continue
        years=re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)',p.name)
        if len(years)!=1:raise ValueError('Año de aforo no inequívoco.')
        year=int(years[0])
        if p.suffix=='.xlsx':
            book=load_workbook(p,read_only=True,data_only=True)
            try:parts=[leer_filas_aforo(p,s.title,s.iter_rows(values_only=True))[0] for s in book]
            finally:book.close()
        else:parts=[leer_csv_aforos(p)[0]]
        for df in parts:
            if not df.empty:rows.append(df.assign(anio_archivo=year))
    raw=pd.concat(rows,ignore_index=True);raw['punto']=raw.punto.astype('string').str.strip()
    raw['fecha']=pd.to_datetime(raw.fecha,format='mixed',dayfirst=True,errors='raise')
    raw['timestamp_local']=raw.fecha+normalizar_horas_aforo(raw.hora)
    if not raw.fecha.dt.year.eq(raw.anio_archivo).all():raise ValueError('Fecha de aforo incompatible con año de archivo.')
    for k,values in {'anio':raw.fecha.dt.year,'mes':raw.fecha.dt.month,'dia':raw.fecha.dt.day}.items():
        if k in raw:
            present=raw[k].notna()&raw[k].astype(str).str.strip().ne('')
            if not pd.to_numeric(raw.loc[present,k]).eq(values[present]).all():raise ValueError('Calendario declarado incompatible.')
        raw[k]=values
    for c in measures:raw[c]=pd.to_numeric(raw[c],errors='raise')
    raw['hora']=raw.timestamp_local.dt.strftime('%H:%M:%S')
    data=raw.melt(id_vars=['punto','fecha','dia','mes','anio','hora','timestamp_local','archivo_origen','hoja_origen','fila_origen'],value_vars=measures,var_name='campo_origen',value_name='n_vehiculos_corregido')
    data=data.assign(sentido=data.campo_origen.str[0].map({'e':'entrada','s':'salida'}),tipo_vehiculo=data.campo_origen.str[1:].map({'coches':'coche','guaguas':'guagua'}),hora_num=data.timestamp_local.dt.hour,timestamp_original=data.timestamp_local,correccion_temporal_aplicada=False)
    x=data[data.anio.eq(2025)].copy();group=['punto','sentido','tipo_vehiculo']
    if len(x.groupby(group).size())!=16 or not x.groupby(group).size().eq(8760).all():raise ValueError('Cobertura 2025 distinta de la corrección documentada.')
    expected=pd.Timestamp('2025-01-01')+pd.to_timedelta(x.groupby(group,sort=False).cumcount(),unit='h');bad=x.timestamp_local.ne(expected)
    pattern=(expected-x.timestamp_local).eq(pd.Timedelta(days=1))&expected.dt.month.isin([10,11,12])&expected.dt.day.gt(1)&expected.dt.hour.eq(0)&x.timestamp_local.dt.hour.eq(0)
    if not bad.eq(pattern).all() or not x[bad].groupby(group).size().eq(89).all():raise ValueError('La corrección temporal no explica todas las discrepancias.')
    x.loc[bad,'timestamp_local']=expected[bad].to_numpy();x['correccion_temporal_aplicada']=bad
    x['fecha']=x.timestamp_local.dt.normalize();x['dia']=x.timestamp_local.dt.day;x['mes']=x.timestamp_local.dt.month;x['anio']=x.timestamp_local.dt.year;x['hora_num']=x.timestamp_local.dt.hour;x['hora']=x.timestamp_local.dt.strftime('%H:%M:%S')
    data=pd.concat([data[data.anio.ne(2025)],x],ignore_index=True)
    data['valor_negativo']=data.n_vehiculos_corregido.lt(0);data['valor_ausente']=data.n_vehiculos_corregido.isna();v=data.n_vehiculos_corregido.to_numpy(dtype=float)
    data['valor_decimal']=np.isfinite(v)&~np.isclose(v,np.rint(v),atol=1e-9,rtol=0)
    if data.duplicated(group+['timestamp_local']).any():raise ValueError('Horas repetidas tras preparar aforos.')
    data=data.sort_values(['anio',*group,'timestamp_local'],kind='stable').reset_index(drop=True)
    annual=resumir_aforos(data,['anio',*group]);monthly=resumir_aforos(data,['anio','mes',*group],mensual=True)
    return data,annual,monthly


def parametros_de_origen_aforos(root):
    """Leer solo las dos ocupaciones del libro original, identificado por hash.

    Es un documento de procedencia inmutable de la preparación, distribuido en
    Bronze. Las hipótesis vigentes se siguen editando solo en config/.
    """
    import hashlib
    folder=Path(root)/'data/bronze/documentacion/preparacion_aforos'
    record=json.loads((folder/'procedencia.json').read_text());path=folder/record['archivo']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Libro de origen de aforos alterado.')
    book=load_workbook(path,data_only=False);case=book['Inicio']['B5'].value;keys={'ocupacion_coche','ocupacion_guagua_aforo'}
    proposals={r[7]:r[3] for r in book['Propuestas'].iter_rows(min_row=7,values_only=True) if r[7] in keys}
    chosen={}
    for row in book['Escenarios'].iter_rows(min_row=7,values_only=True):
        if row[0]!=case or row[12] not in keys:continue
        key,mode=row[12],row[6]
        if mode=='Pendiente':chosen[key]=None
        elif mode=='Manual':chosen[key]=row[7]
        elif mode=='Propuesta':chosen[key]=proposals[key]
        else:raise ValueError('Elección de origen de aforos no reconocida: '+str(mode))
    book.close()
    if set(chosen)!=keys or set(proposals)!=keys:raise ValueError('Faltan ocupaciones del productor de aforos.')
    return proposals,chosen,case,record['sha256']


def preparar_zonas(root):
    incidents=[];options=dict(zip_zonas=Path(root)/ZONAS,crs_metrico='EPSG:32628',incidencias=incidents)
    zones=leer_poligonos('zonas_transporte_2025',**options).rename(columns={'ID':'zona_id'})
    municipalities=leer_poligonos('municipios',**options).rename(columns={'ID':'municipio_id','nombre':'municipio'})
    macros=leer_poligonos('macrozonas',**options).rename(columns={'ID':'macrozona_id','nombre':'macrozona'})
    zones['es_teide']=zones.zona_id.isin([187,222]);m,intersection=cruzar_referencias(municipalities,'municipio_id','municipio',zonas=zones)
    ma,_=cruzar_referencias(macros,'macrozona_id','macrozona',zonas=zones)
    zones=zones.merge(m,on='zona_id',validate='one_to_one').merge(ma,on='zona_id',validate='one_to_one')
    zones['etiqueta_referencia']='Zona '+zones.zona_id.astype(str)+' · '+zones.municipio_principal
    return zones,intersection


def preparar_gtfs(root):
    with zipfile.ZipFile(Path(root)/GTFS) as z:
        tables={n:pd.read_csv(z.open(n+'.txt'),dtype=str,keep_default_na=False) for n in ['routes','trips','stop_times','stops']}
    route=tables['routes'];trips=tables['trips'];times=tables['stop_times'];stops=tables['stops']
    rid=set(route.loc[route.route_short_name.isin(['341','342','348']),'route_id'])
    tids=set(trips.loc[trips.route_id.isin(rid),'trip_id']);selected=set(times.loc[times.trip_id.isin(tids),'stop_id'])
    s=stops[stops.stop_id.isin(selected)].copy()
    p=gpd.GeoDataFrame(s,geometry=gpd.points_from_xy(s.stop_lon.astype(float),s.stop_lat.astype(float)),crs=4326)
    ids341=set(route.loc[route.route_short_name.eq('341'),'route_id']);t341=set(trips.loc[trips.route_id.isin(ids341),'trip_id']);s341=set(times.loc[times.trip_id.isin(t341),'stop_id'].astype(int))
    return p,s341


def preparar_od(root):
    root=Path(root);rows=[];tables=[]
    selected={}
    for p in sorted((root/'data/bronze/demanda/odviewer/api').glob('matriz_*/*/*/metadata.json')):
        m=json.loads(p.read_text());requested={'id_matriz2025':m['matriz']['idMatriz'],('destino2025' if m['sentido']=='hacia_teide' else 'origen2025'):'[187,222]'}
        if m['modo']=='privado':requested['modo2025']=2
        if m['modo'] not in {'privado','todos_modos'} or m['parametros']!=requested:continue
        selected[m['matriz']['idMatriz'],m['sentido'],m['modo']]=p
    for key,p in sorted(selected.items()):
        m=json.loads(p.read_text());matrix=m['matriz']
        if matrix['anio']!=2025:continue
        od=pd.DataFrame(json.loads((p.parent/'viajes_od.json').read_bytes()),columns=['origen','destino','viajes']);hour=pd.DataFrame(json.loads((p.parent/'viajes_horarios.json').read_bytes()),columns=['origen','destino','id_periodo','viajes'])
        keys=['origen','destino'];h=hour.groupby(keys).viajes.sum();o=od.set_index(keys).viajes
        if set(h.index)!=set(o.index) or not np.allclose(o,h.reindex(o.index),atol=1e-8,rtol=1e-9):raise ValueError('OD y horario no conservan viajes.')
        inside=od.origen.isin([187,222])&od.destino.isin([187,222]);total=math.fsum(od.viajes)
        common=dict(id_matriz=matrix['idMatriz'],matriz=matrix['nombreDia'],anio=matrix['anio'],mes=matrix['mes'],tipo_dia=matrix['tipoDia'],sentido=m['sentido'],modo=m['modo'],fuente=str(p.parent.relative_to(root)))
        rows.append({**common,'relaciones_od':len(od),'registros_horarios':len(hour),'viajes_total':total,'viajes_internos':math.fsum(od.loc[inside,'viajes']),'viajes_externos':math.fsum(od.loc[~inside,'viajes']),'control_od_horario':True})
        tables.append(od.assign(**common,grupo=inside.map({True:'interno_teide',False:'externo'})))
    if len(rows)!=36:raise ValueError('No se conservan las 36 consultas OD de 2025.')
    all_od=pd.concat(tables,ignore_index=True);external=all_od[all_od.grupo.eq('externo')].copy();external['zona_externa']=external.origen.where(external.sentido.eq('hacia_teide'),external.destino)
    keys=['id_matriz','matriz','anio','mes','tipo_dia','sentido','modo','fuente','zona_externa'];profiles=external.groupby(keys,as_index=False).viajes.sum()
    den=profiles.groupby(['id_matriz','sentido','modo']).viajes.transform('sum');profiles['porcentaje']=100*profiles.viajes/den.where(den>0)
    return pd.DataFrame(rows),profiles
