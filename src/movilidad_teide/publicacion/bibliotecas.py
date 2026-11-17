"""Comprobar alcances de bibliotecas; no confundir identidad de bytes y factores."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from movilidad_teide.trazabilidad import sha256_archivo


def comparar_biblioteca(antecedente, vigente, *, familia):
    campos=['Category','Fuel','Segment','Euro Standard','year']
    old=antecedente.copy();new=vigente.copy()
    total=len(old)
    if familia=='autocar':
        mask=old['Category'].eq('Buses') & old['Fuel'].eq('Diesel') & old['Segment'].eq('Coaches Standard <=18 t') & old['Euro Standard'].eq('Euro VI D/E')
        mask &= old.rural_speed_kmh.eq(34.)
        if not new.speed_kmh.eq(34.).all():raise ValueError('La velocidad de autocar no corresponde a la referencia de 34 km/h.')
        old=old[mask].copy();old['speed_kmh']=old.rural_speed_kmh
        campos+=['speed_kmh','slope_class_pct','load_fraction']
    elif familia in {'turismos','multienergia'}:
        campos+=['driving_mode','speed_kmh']
        if familia=='multienergia':campos+=['primary_control_fraction']
    else:raise ValueError('Familia COPERT desconocida.')
    if old.duplicated(campos).any() or new.duplicated(campos).any():
        raise ValueError('Clave de biblioteca repetida o insuficiente.')
    compared=old[campos+['hot_ec_mj_per_km']].merge(new[campos+['hot_ec_mj_per_km']],on=campos,how='outer',suffixes=('_anterior','_vigente'),indicator=True,validate='one_to_one')
    if compared._merge.ne('both').any():raise ValueError('Faltan o sobran claves aplicadas en la biblioteca vigente.')
    if not np.isfinite(compared[['hot_ec_mj_per_km_anterior','hot_ec_mj_per_km_vigente']].to_numpy()).all():
        raise ValueError('Factor COPERT ausente o no finito.')
    np.testing.assert_allclose(compared.hot_ec_mj_per_km_anterior,compared.hot_ec_mj_per_km_vigente,rtol=0,atol=1e-12)
    return {'familia':familia,'filas_antecedente':total,'filas_en_alcance':len(old),'filas_fuera_de_alcance':total-len(old),'filas_vigentes':len(new),'claves':campos,
        'maxima_diferencia_mj_km':float((compared.hot_ec_mj_per_km_anterior-compared.hot_ec_mj_per_km_vigente).abs().max()),'tolerancia_mj_km':1e-12,'equivalente_por_clave':True,'identidad_de_archivos_exigida':False}


def verificar_bibliotecas(root):
    root=Path(root)
    spec=json.loads((root/'config/dependencias_publicacion.json').read_text())
    checks=[]
    for row in spec['bibliotecas']:
        previous,current=root/row['archivo_antecedente'],root/row['archivo_vigente']
        check=comparar_biblioteca(pd.read_parquet(previous),pd.read_parquet(current),familia=row['familia'])
        checks.append({**row,**check,'sha256_antecedente':sha256_archivo(previous),'sha256_vigente':sha256_archivo(current)})
    return checks


def verificar_bibliotecas_vigentes(root):
    """Validar el cierre certificado sin exigir bibliotecas históricas al lector.

    La comparación por claves se realiza al cerrar la referencia y conserva
    ambas huellas. Preparar otra copia verifica la biblioteca vigente completa;
    no vuelve a necesitar el archivo histórico ni afirma que sea idéntico.
    """
    root=Path(root).resolve()
    spec=json.loads((root/'config/dependencias_publicacion.json').read_text())
    checks=[]
    for row in spec['bibliotecas']:
        name=Path(row['archivo_vigente']);path=root/name
        if name.is_absolute() or '..' in name.parts or not path.resolve().is_relative_to(root):
            raise ValueError('Biblioteca vigente no portable.')
        previous=row['equivalencia_verificada']
        if not previous['equivalente_por_clave'] or previous['tolerancia_mj_km']!=1e-12 or previous['maxima_diferencia_mj_km']>1e-12:
            raise ValueError('La biblioteca carece de un cierre numérico válido.')
        if sha256_archivo(path)!=previous['sha256_vigente']:
            raise ValueError('La biblioteca vigente difiere de la referencia cerrada.')
        checks.append({**previous,'huella_vigente_comprobada':True,'antecedente_leido_durante_preparacion':False})
    return checks
