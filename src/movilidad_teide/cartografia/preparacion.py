"""Reconstruir geometrías y perfiles desde fuentes nativas, sin leer Silver.

Se conservan el catálogo, las fases de muestreo, los métodos y los CRS elegidos.
Las referencias auxiliares de TITSA se resuelven desde su GTFS original.
"""
from pathlib import Path
from copy import deepcopy
import json
import zipfile
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shutil
from shapely.geometry import LineString, Point
from movilidad_teide.cartografia.fuentes_rutas import build_source_inventory, read_geospatial_source
from movilidad_teide.cartografia.extraccion import extract_configured_itinerary, resolve_anchor
from movilidad_teide.cartografia.auditoria_rutas import partition_itinerary_at_anchor
from movilidad_teide.cartografia.perfiles import sample_elevation_profile, calculate_segments, locate_profile_segments
from movilidad_teide.cartografia.terreno import convert_wcs_arcgrid_response, extend_native_dem
from movilidad_teide.trazabilidad import sha256_archivo
from movilidad_teide.fuentes.preparacion_demanda import GTFS


def catalogo_nativo(root):
    """Resolver tres auxiliares GTFS, sin cambiar decisiones del catálogo maestro."""
    root=Path(root)
    cat=json.loads((root/'config/itinerarios.json').read_text())
    cat=deepcopy(cat)
    with zipfile.ZipFile(root/GTFS) as z:
        tables={n:pd.read_csv(z.open(n+'.txt'),dtype=str,keep_default_na=False)
                for n in ['stops','routes','trips','shapes']}
    s=tables['stops']
    stops=gpd.GeoDataFrame(s,geometry=gpd.points_from_xy(s.stop_lon.astype(float),s.stop_lat.astype(float)),crs=4326)
    stops['source_feature_index']=stops.index.map(str)
    shapes=tables['shapes'].copy()
    shapes['shape_pt_sequence']=shapes.shape_pt_sequence.astype(int)
    geometries=[]
    for ident,g in shapes.groupby('shape_id',sort=True):
        g=g.sort_values('shape_pt_sequence')
        geometries.append({'shape_id':ident,'geometry':LineString(zip(g.shape_pt_lon.astype(float),g.shape_pt_lat.astype(float)))})
    routes=gpd.GeoDataFrame(geometries,crs=4326)
    routes['source_feature_index']=routes.index.map(str)
    resolution=[]
    for key in ['titsa_stop_references','titsa_route_references','titsa_route_metadata']:
        source=cat['sources'][key]
        resolution.append({'source_id':key,'referencia_preparada_original':source['path'],
                           'fuente_nativa':GTFS,'sha256_nativo':sha256_archivo(root/GTFS)})
        source.update(path=GTFS,expected_sha256=sha256_archivo(root/GTFS),
                      provider='TITSA; lectura del GTFS nativo en memoria')
    return cat,{'titsa_stop_references':stops,'titsa_route_references':routes},tables,resolution


class Terrenos:
    """Convertir respuestas originales y extensiones de celdas, en destino nuevo."""
    def __init__(self,root,destino,config):
        self.root=Path(root);self.destino=Path(destino);self.config=config
        self.recipes={**config['operational_profiles'],**config['origin_access_profiles']}
        self.cache={};self.extensions={};self.products=[]

    def convertir(self,raw,target,crs):
        raw=self.root/raw
        with raw.open('rb') as f:boundary=f.read(4096).lstrip().splitlines()[0][2:].decode('ascii')
        convert_wcs_arcgrid_response(raw,target,content_type='multipart/mixed; boundary="'+boundary+'"',expected_crs=crs)
        return target

    def obtener(self,name):
        cfg=self.recipes[name]
        if name in self.cache:return self.cache[name]
        if cfg['dem_path'].startswith('data/bronze/'):
            p=self.root/cfg['dem_path']
        else:
            p=self.destino/'terrenos'/(name+'.tif')
            if cfg.get('dem_origin')=='native_extension':
                extension=self.destino/'terrenos'/(name+'_extension.tif')
                self.convertir(cfg['raw_dem_path'],extension,cfg['native_crs'])
                base=self.obtener(cfg['base_dem_profile_reference'])
                compatible=extension
                with rasterio.open(base) as a,rasterio.open(extension) as b:
                    # Una ampliación ya creada puede declarar NaN; la nueva
                    # respuesta completa no declara NoData. Igualar solo esa
                    # representación, sin cambiar ninguna celda o máscara.
                    normalizar=(a.nodata is not None and np.isnan(a.nodata) and b.nodata is None)
                if normalizar:
                    compatible=extension.with_name(extension.stem+'_nodata.tif')
                    shutil.copy2(extension,compatible)
                    with rasterio.open(compatible,'r+') as ds:ds.nodata=np.nan
                    with rasterio.open(extension) as a,rasterio.open(compatible) as b:
                        for _,window in a.block_windows(1):
                            x,y=a.read(1,window=window,masked=True),b.read(1,window=window,masked=True)
                            if not np.array_equal(x.data,y.data,equal_nan=True) or not np.array_equal(np.ma.getmaskarray(x),np.ma.getmaskarray(y)):
                                raise ValueError('La compatibilidad de NoData cambia celdas.')
                if sha256_archivo(compatible)!=cfg['expected_extension_dem_sha256']:raise ValueError('Extensión distinta del sello configurado tras la representación NoData.')
                self.extensions[name]=compatible
                self.products.append({'referencia':name+'/extension','ruta_de_configuracion':cfg['extension_dem_path'],'sha256':sha256_archivo(compatible),'fuente':cfg['raw_dem_path'],'salida_relativa':str(compatible.relative_to(self.destino))})
                extend_native_dem(base,compatible,p)
            else:self.convertir(cfg['raw_dem_path'],p,cfg['native_crs'])
        if sha256_archivo(p)!=cfg['expected_dem_sha256']:
            raise ValueError('El terreno reconstruido difiere del sello configurado: '+name)
        self.cache[name]=p
        self.products.append({'referencia':name,'ruta_de_configuracion':cfg['dem_path'],
                              'sha256':sha256_archivo(p),'fuente':cfg.get('raw_dem_path',cfg['dem_path']),
                              'salida_relativa':str(p.relative_to(self.destino)) if p.is_relative_to(self.destino) else None})
        return p


class Preparador:
    def __init__(self,root,destino,*,demanda=None):
        self.root=Path(root);self.destino=Path(destino);self.demanda_conectada=demanda
        self.master=json.loads((self.root/'config/itinerarios.json').read_text())
        self.profile=json.loads((self.root/'config/perfil_altimetrico.json').read_text())
        self.cat,self.sources,self.gtfs,self.resolution=catalogo_nativo(root)
        self.inventory=build_source_inventory(self.cat,root)
        self.components={};self.routes={};self.parts={};self.tables={}
        self.dem=Terrenos(root,destino,self.profile)
        self.interval=float(self.profile['baseline_interval_m'])

    def ruta(self,ident):
        if ident not in self.routes:
            r=extract_configured_itinerary(ident,self.cat,self.root,
                config_sha256=sha256_archivo(self.root/'config/itinerarios.json'),
                source_inventory=self.inventory,source_frames=self.sources,component_frames=self.components)
            if not r.validations.passed.all():raise ValueError('Validación de geometría fallida: '+ident)
            self.routes[ident]=r
        return self.routes[ident].route.geometry.item()

    def punto(self,ident):
        spec=self.cat['anchors'][ident];sid=spec.get('source_id')
        if sid and sid not in self.sources:self.sources[sid]=read_geospatial_source(sid,self.cat,self.root)
        return resolve_anchor(ident,spec,self.sources,self.cat['metric_crs'],anchor_specs=self.cat['anchors']).geometry.item()

    def partir(self,ident,point):
        line=self.ruta(ident);spec=self.cat['itineraries'][ident]
        ctx={'lineage':self.routes[ident].lineage,'itinerary':spec,'config':self.cat,'project_root':self.root}
        return partition_itinerary_at_anchor(line,point,self.cat['parameters']['anchor_axis_tolerance_m'],osm_grade_context=ctx if spec.get('osm_grade_separation_audit') else None)

    def muestrear(self,line,dem_name,reference,*,method='bilinear'):
        cfg=self.dem.recipes[dem_name];phase=line.length%self.interval if Point(line.coords[-1]).distance(reference)<1e-6 else 0.
        route=gpd.GeoDataFrame({'geometry':[line]},crs=self.cat['metric_crs'])
        p=sample_elevation_profile(route,self.dem.obtener(dem_name),self.interval,method=method,
                                   station_offset_m=phase,assumed_raster_crs=cfg.get('assumed_raster_crs'))
        s=calculate_segments(p)
        if abs(s.length_m.sum()-line.length)>self.profile['length_tolerance_m']:raise ValueError('Se pierde longitud al muestrear.')
        return p,locate_profile_segments(route,s)

    def operativos(self):
        for key,cfg in self.profile['operational_profiles'].items():
            print('Lanzadera:',key,flush=True)
            for ident in cfg['itinerary_ids']:
                spec=self.cat['itineraries'][ident]
                ref=cfg.get('sampling_reference_anchor_ids',{}).get(ident,cfg['sampling_reference_anchor_id'])
                p,s=self.muestrear(self.ruta(ident),key,self.punto(ref),method=cfg['sampling_method'])
                p['itinerary_id']=ident
                p['distance_from_reference_m']=self.ruta(ident).length-p.distance_m if spec['destination_anchor_id']==ref else p.distance_m
                s['itinerary_id']=ident;s['outside_copert_reference']=s.slope_pct.abs()>self.profile['slope_reference_pct']
                self.tables['operativos/'+key+'/perfil_'+ident]=p
                self.tables['operativos/'+key+'/tramos_'+ident]=s

    def origen(self,key,collections):
        if key in self.parts:return self.parts[key]
        spec=collections[key];independent=spec.get('geometry_mode')=='independent_reference_and_feeders'
        parent=self.origen(spec['reused_mountain_comparison_id'],collections) if independent else None
        parts=[];rows=[];profiles=[];segments=[]
        dem_name=spec['dem_profile_reference'];dcfg=self.dem.recipes[dem_name]
        for direction,ident in enumerate(spec['itinerary_ids']):
            head=self.punto(spec.get('head_axis_anchor_ids',{}).get(ident,spec['head_axis_anchor_id']))
            direct=self.ruta(ident)
            if independent:
                feeder=self.ruta(spec['feeder_itinerary_ids'][direction])
                mountain=parent[direction]['cabecera_teide']
            else:
                a,b=self.partir(ident,head);feeder,mountain=(a,b) if direction==0 else (b,a)
            parts.append({'origen_cabecera':feeder,'cabecera_teide':mountain})
            row={'origen_id':spec['origin_id'],'itinerary_id':ident,'sentido':'Hacia el Teide' if direction==0 else 'Regreso',
                 'referencia_coche_hasta_terminal_km':direct.length/1000,'acceso_cabecera_en_coche_si_se_elige_km':feeder.length/1000,
                 'tramo_cabecera_terminal_km':mountain.length/1000}
            if independent:row['recorrido_encadenado_hasta_terminal_km']=(feeder.length+mountain.length)/1000
            rows.append(row)
            components=[('origen_cabecera',feeder),('cabecera_teide',mountain)]
            if independent:components.append(('referencia_directa',direct))
            for role,line in components:
                reference=Point(line.coords[0]) if role=='referencia_directa' else head
                if role=='cabecera_teide' and dcfg.get('mountain_sampling_reference_anchor_id'):
                    reference=self.punto(dcfg['mountain_sampling_reference_anchor_id'])
                selected=dcfg.get('component_dem_profile_references',{}).get(role,dem_name)
                p,s=self.muestrear(line,selected,reference)
                for df in [p,s]:df['itinerary_id']=ident;df['componente']=role
                p['distancia_desde_cabecera_m']=line.length-p.distance_m if Point(line.coords[-1]).distance(head)<1e-6 else p.distance_m
                s['outside_copert_reference']=s.slope_pct.abs()>self.profile['slope_reference_pct']
                profiles.append(p);segments.append(s)
        self.parts[key]=parts
        self.tables['origenes/'+key+'/perfiles']=gpd.GeoDataFrame(pd.concat(profiles,ignore_index=True),crs=self.cat['metric_crs'])
        self.tables['origenes/'+key+'/segmentos']=gpd.GeoDataFrame(pd.concat(segments,ignore_index=True),crs=self.cat['metric_crs'])
        self.tables['origenes/'+key+'/longitudes']=pd.DataFrame(rows)
        return parts

    def origenes(self):
        collections={**self.cat['origin_access_comparisons'],**self.cat['study_origin_access_comparisons']}
        for key in collections:
            print('Coche:',key,flush=True);self.origen(key,collections)

    def costa(self):
        profiles=[];segments=[];rows=[]
        for key,spec in self.cat['coastal_valley_comparisons'].items():
            print('Valle:',key,flush=True)
            for d,sense in enumerate(['Hacia el Teide','Regreso']):
                ident=spec['costera_itinerary_ids'][d];head=self.punto(spec['head_axis_anchor_ids'][d])
                a,b=self.partir(ident,head);feeder,mountain=(a,b) if d==0 else (b,a)
                direct=self.ruta(spec['directa_itinerary_ids'][d])
                rows.append({'caso':key,'sentido':sense,'directa_tf523_km':direct.length/1000,'alimentador_costero_km':feeder.length/1000,'montana_km':mountain.length/1000,'cadena_costera_km':self.ruta(ident).length/1000})
                for role,line,dem,anchor in [('directa_tf523',direct,spec['direct_dem_profile_reference'],spec['origin_axis_anchor_id']),
                    ('alimentador_costero',feeder,spec['coastal_dem_profile_reference'],spec['head_axis_anchor_ids'][d]),
                    ('montana',mountain,spec['direct_dem_profile_reference'],spec['terminal_axis_anchor_id'])]:
                    p,s=self.muestrear(line,dem,self.punto(anchor))
                    for df in [p,s]:df['caso']=key;df['sentido']=sense;df['alternativa']=role
                    s['outside_copert_reference']=s.slope_pct.abs()>self.profile['slope_reference_pct']
                    profiles.append(p);segments.append(s)
        self.tables['costa/perfiles']=gpd.GeoDataFrame(pd.concat(profiles,ignore_index=True),crs=self.cat['metric_crs'])
        self.tables['costa/segmentos']=gpd.GeoDataFrame(pd.concat(segments,ignore_index=True),crs=self.cat['metric_crs'])
        self.tables['costa/longitudes']=pd.DataFrame(rows)

    def preparar(self):
        self.operativos();self.origenes();self.costa()
        from movilidad_teide.cartografia.preparacion_accesos import preparar_accesos
        selection=json.loads((self.root/'manifiestos/preparacion_geografia_bronze.json').read_text())['cabeceras']
        preparar_accesos(self,selection)
        from movilidad_teide.cartografia.preparacion_referencias import reconstruir_referencias
        reconstruir_referencias(self)
        return self.tables,{'catalogo_gtfs_resuelto_desde_bronze':self.resolution,'terrenos':self.dem.products,
            'itinerarios_extraidos':len(self.routes),'visitas_sin_y_con':2500000,'energia_recalculada':False}
