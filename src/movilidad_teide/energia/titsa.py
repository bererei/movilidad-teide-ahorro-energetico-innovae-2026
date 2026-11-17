"""Consumo de acceso TITSA con pendiente y la referencia técnica del libro."""
from pathlib import Path
import numpy as np
import pandas as pd
from movilidad_teide.cartografia.perfiles import calculate_segments
from movilidad_teide.vehiculos.copert_factores import apply_reference_factors_by_segment


def recalcular_titsa(root,referencia):
    """Reconstruir segmentos y energía desde perfiles y siete factores sellados."""
    root=Path(root);key=referencia['indice'].get('titsa_pendiente')
    if not key:return None
    folder=root/key['directorio'];v=referencia['valores_modelo']
    profiles=pd.read_parquet(folder/'perfiles.parquet');summary=pd.read_csv(folder/'resumen_recorridos.csv',sep=';',float_precision='round_trip')
    factors=pd.read_parquet(folder/'factores_utilizados.parquet')
    assert factors.rural_speed_kmh.eq(v['velocidad_copert']).all() and factors.load_fraction.eq(v['carga_copert']).all()
    vehicle=tuple(factors[['Category','Fuel','Segment','Euro Standard']].drop_duplicates().iloc[0])
    if factors[['Category','Fuel','Segment','Euro Standard']].drop_duplicates().shape[0]!=1:raise ValueError('Referencia TITSA no unívoca.')
    rows=[]
    for (line,shape),p in profiles.groupby(['linea','shape_id'],sort=True):
        p=p.sort_values('distance_m');s=calculate_segments(p)
        cond=s[['segment_id']].assign(velocidad_media_kmh=v['velocidad_copert'],carga_fisica=v['carga_copert'],bloque_velocidad_id='Referencia de estudio',fuente_velocidad='Hipótesis del libro; no velocidad GTFS medida',tipo_via='rural')
        val=apply_reference_factors_by_segment(s,cond,folder/'factores_utilizados.parquet',vehicle)
        energy=float(val.energia_mj.sum()/3600);q=summary[summary.linea.astype(str).eq(str(line))&summary.shape_id.astype(str).eq(str(shape))].iloc[0]
        np.testing.assert_allclose([energy,s.length_m.sum()/1000],[q.mwh_por_expedicion,q.kilometros],atol=1e-10,rtol=0)
        for month in range(1,13):
            days=pd.Period(f'2028-{month:02d}').days_in_month
            rows.append({'mes':month,'linea':int(line),'shape_id':int(shape),'dias':days,'expediciones_dia':1,'longitud_km':q.kilometros,'mwh_por_expedicion':energy,'energia_hot_mwh_anio':energy*days})
    out=pd.DataFrame(rows);np.testing.assert_allclose(out.energia_hot_mwh_anio.sum(),key['consumo_mwh_anio'],atol=1e-8,rtol=0)
    return out


def ruta_producto(root,referencia,nombre):
    return Path(root)/referencia['indice'].get('productos_actualizados',{}).get(nombre,str(Path(referencia['indice']['captura'])/nombre))


def leer_producto(root,referencia,nombre):
    return pd.read_csv(ruta_producto(root,referencia,nombre),sep=';',float_precision='round_trip',low_memory=False)
