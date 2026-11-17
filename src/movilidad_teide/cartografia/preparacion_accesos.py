"""Reconstrucción de accesos reasignados y TITSA desde geometrías y MDT nativos."""
from pathlib import Path
import json
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import shape,box
from movilidad_teide.cartografia.perfiles import make_sampling_distances,calculate_segments
from movilidad_teide.cartografia.terreno import sample_dem_points
from movilidad_teide.trazabilidad import sha256_archivo


class MuestreadorCoberturas:
    """Primera cobertura de menor área con soporte bilineal completo.

    Se conserva el criterio del productor de accesos: área y nombre estables,
    sin rellenar NoData ni usar una interpolación distinta cuando falta soporte.
    """
    def __init__(self,preparador):
        self.prep=preparador;self.extra={};self.base=[]
        dem=preparador.dem
        for name,cfg in dem.recipes.items():
            p=dem.obtener(name)
            with rasterio.open(p) as ds:
                if ds.crs.to_epsg()==4083:self.base.append((cfg['dem_path'],p))
            if cfg.get('dem_origin')=='native_extension':
                p=dem.extensions[name]
                self.base.append((cfg['extension_dem_path'],p))

    def complementos(self,kind):
        if kind in self.extra:return self.extra[kind]
        root=self.prep.root;dem=self.prep.dem;rows=[]
        if kind in ['ampliaciones','refuerzos']:
            directory=('ampliaciones_cabeceras_20261109' if kind=='ampliaciones' else 'refuerzos_cabeceras_20261109')
            folder=root/'data/bronze/geografia/mdt05'/directory
            names=['fuentes.json','fuentes_soporte.json'] if kind=='ampliaciones' else ['fuentes.json']
            for name in names:
                for source in json.loads((folder/name).read_text()):
                    ident=source.get('nombre',Path(source.get('archivo_tif','')).stem)
                    raw=folder/(ident+'.multipart')
                    if sha256_archivo(raw)!=source['sha256_respuesta']:raise ValueError('Respuesta de ampliación alterada.')
                    p=dem.destino/'terrenos'/(directory+'_'+ident+'.tif')
                    dem.convertir(raw.relative_to(root),p,'EPSG:4083')
                    expected=source.get('sha256_tif')
                    if expected and sha256_archivo(p)!=expected:raise ValueError('Ampliación reconstruida distinta.')
                    label='data/silver/geografia/mdt05/'+directory+'/'+ident+'.tif'
                    rows.append((label,p));dem.products.append({'referencia':kind+'/'+ident,'ruta_de_configuracion':label,'sha256':sha256_archivo(p),'fuente':str(raw.relative_to(root)),'salida_relativa':str(p.relative_to(dem.destino))})
        else:
            folder=root/'data/bronze/geografia/mdt05/20261110_titsa_342_348'
            for source in json.loads((folder/'metadatos.json').read_text()):
                ident='mdt05_titsa_'+source['linea'];raw=folder/(ident+'.multipart')
                if sha256_archivo(raw)!=source['sha256_respuesta']:raise ValueError('Respuesta TITSA alterada.')
                p=dem.destino/'terrenos'/(ident+'.tif');dem.convertir(raw.relative_to(root),p,'EPSG:4083')
                if sha256_archivo(p)!=source['sha256_raster']:raise ValueError('Terreno TITSA distinto.')
                label='data/silver/geografia/mdt05/titsa_342_348/'+ident+'.tif'
                rows.append((label,p));dem.products.append({'referencia':'TITSA/'+ident,'ruta_de_configuracion':label,'sha256':sha256_archivo(p),'fuente':str(raw.relative_to(root)),'salida_relativa':str(p.relative_to(dem.destino))})
        self.extra[kind]=rows
        return rows

    def pool(self,role):
        items=self.base+(self.complementos('titsa') if role=='titsa' else self.complementos('ampliaciones')+(self.complementos('refuerzos') if role=='refuerzos' else []))
        unique={label:p for label,p in items};pool=[]
        for label,p in unique.items():
            with rasterio.open(p) as ds:extent=box(*ds.bounds)
            pool.append((extent.area,label,p,extent))
        return sorted(pool,key=lambda x:(x[0],x[1]))

    def perfil(self,line,pool,label_column):
        d=make_sampling_distances(line.length,self.prep.interval)
        points=gpd.GeoDataFrame({'sample_id':range(len(d)),'distance_m':d,'geometry':[line.interpolate(k) for k in d]},crs=4083)
        rows=[]
        for index,point in points.iterrows():
            for _,label,path,extent in pool:
                if not extent.contains(point.geometry):continue
                try:part=sample_dem_points(points.loc[[index]],path,method='bilinear')
                except ValueError:continue
                part[label_column]=label;rows.append(part);break
            else:raise ValueError('No hay soporte bilineal nativo para la muestra '+str(index))
        return gpd.GeoDataFrame(pd.concat(rows,ignore_index=True),crs=4083)


def preparar_accesos(preparador,selection):
    sample=MuestreadorCoberturas(preparador);tables=preparador.tables
    folder=preparador.root/'data/bronze/geografia/rutas_cabeceras/20261108_osrm'
    catalog=pd.read_csv(folder/'catalogo.csv',sep=';',float_precision='round_trip')
    lines={};lengths=[]
    for row in catalog.itertuples():
        raw=json.loads((folder/row.archivo).read_text());r=raw['routes'][0]
        if raw['code']!='Ok':raise ValueError('Respuesta de ruta inválida.')
        line=gpd.GeoSeries([shape(r['geometry'])],crs=4326).to_crs(4083).iloc[0];lines[row.archivo]=line
        lengths.append({'archivo':row.archivo,'km':r['distance']/1000,'minutos':r['duration']/60,'km_geometria':line.length/1000,'sha256':sha256_archivo(folder/row.archivo)})
    tables['cabeceras/catalogo_longitudes']=pd.DataFrame(lengths)
    for group,column in [('ordinarias','mdt'),('refuerzos','fuente_mdt')]:
        pool=sample.pool('refuerzos' if group=='refuerzos' else 'ordinarias');profiles=[];segments=[]
        for name in selection[group]:
            print('Acceso reasignado:',name,flush=True)
            p=sample.perfil(lines[name],pool,column);p['itinerary_id']=name
            s=calculate_segments(p);s['itinerary_id']=name
            profiles.append(p);segments.append(s)
        tables['cabeceras/'+group+'/perfiles']=gpd.GeoDataFrame(pd.concat(profiles,ignore_index=True),crs=4083)
        tables['cabeceras/'+group+'/segmentos']=pd.concat(segments,ignore_index=True)
    pool=sample.pool('titsa');trips=preparador.gtfs['trips'];routes=preparador.gtfs['routes']
    profiles=[];segments=[]
    for line_id in ['342','348']:
        ids=set(routes.loc[routes.route_short_name.eq(line_id),'route_id'])
        shapes=sorted(set(trips.loc[trips.route_id.isin(ids),'shape_id']))
        if len(shapes)!=2:raise ValueError('No se conservan dos sentidos TITSA propios.')
        for ident in shapes:
            print('TITSA:',line_id,ident,flush=True)
            line=preparador.sources['titsa_route_references'].set_index('shape_id').loc[ident].geometry
            line=gpd.GeoSeries([line],crs=4326).to_crs(4083).iloc[0]
            p=sample.perfil(line,pool,'mdt_archivo');p['interpretacion_provisional_crs']=False;p['linea']=line_id;p['shape_id']=ident
            s=calculate_segments(p);s['linea']=line_id;s['shape_id']=ident
            profiles.append(p);segments.append(s)
    tables['titsa/perfiles']=gpd.GeoDataFrame(pd.concat(profiles,ignore_index=True),crs=4083)
    tables['titsa/segmentos_fisicos']=pd.concat(segments,ignore_index=True)
