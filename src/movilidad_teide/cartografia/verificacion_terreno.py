"""Reconstruir los GeoTIFF de referencia desde las respuestas WCS originales."""
from pathlib import Path
import json
import numpy as np
import rasterio
from movilidad_teide.trazabilidad import sha256_archivo
from movilidad_teide.cartografia.terreno import convert_wcs_arcgrid_response


def verificar_terreno(root, destino):
    root,destino=Path(root).resolve(),Path(destino).resolve()
    if destino==root or (destino.is_relative_to(root) and not destino.is_relative_to(root/'data/silver')):
        raise ValueError('La comprobación requiere un destino nuevo en Silver o externo.')
    if destino.exists() and any(destino.iterdir()):raise FileExistsError('No sobrescribo una comprobación anterior.')
    spec=json.loads((root/'config/dependencias_publicacion.json').read_text())
    destino.mkdir(parents=True,exist_ok=True);checks=[]
    for i,row in enumerate(spec['terrenos_wcs']):
        for path,hash_key in [('respuesta_bronze','sha256_respuesta'),('metadatos_bronze','sha256_metadatos'),('raster_silver','sha256_raster')]:
            if sha256_archivo(root/row[path])!=row[hash_key]:raise ValueError('Fuente de terreno alterada: '+row[path])
        target=destino/('raster_'+str(i+1)+'.tif')
        convert_wcs_arcgrid_response(root/row['respuesta_bronze'],target,content_type=row['content_type'],expected_crs=row['crs_nativo'])
        cells=0;valid=0
        with rasterio.open(root/row['raster_silver']) as expected,rasterio.open(target) as actual:
            for name in ['crs','transform','width','height','count','dtypes','nodata','scales','offsets']:
                if getattr(expected,name)!=getattr(actual,name):raise ValueError('Propiedad del ráster diferente: '+name)
            for _,window in expected.block_windows(1):
                a,b=expected.read(1,window=window,masked=True),actual.read(1,window=window,masked=True)
                if not np.array_equal(np.ma.getmaskarray(a),np.ma.getmaskarray(b)) or not np.array_equal(a.data,b.data,equal_nan=True):
                    raise ValueError('Cambian cotas o ausencias del terreno.')
                cells+=a.size;valid+=int(a.count())
        checks.append({**row,'celdas_comparadas':cells,'celdas_validas':valid,'diferencia_maxima_cotas_m':0.,'malla_crs_y_ausencias_identicos':True,'sha256_raster_regenerado':sha256_archivo(target),'clasificacion_confirmada':'Silver: transformación local sin cambio de cotas'})
        print('Terreno comprobado:',row['raster_silver'],flush=True)
    (destino/'verificacion_terreno.json').write_text(json.dumps({'rasteres_comprobados':len(checks),'celdas_comparadas':sum(x['celdas_comparadas'] for x in checks),'capa_bronze':'Respuestas multipart originales y metadatos de adquisición','capa_silver':'Conversión GeoTIFF de malla y cotas idénticas','no_incluye':'No evalúa la incertidumbre del modelo de terreno ni resuelve diferencias históricas de interpretación del CRS de otras fuentes.','comprobaciones':checks},ensure_ascii=False,indent=2)+'\n')
    return checks
