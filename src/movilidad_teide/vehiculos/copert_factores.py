"""vehiculos: copert factores. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import math
from movilidad_teide.vehiculos.copert_cli_tipos import CAR_MODES
from movilidad_teide.vehiculos.copert_cli_tipos import CAR_BIFUEL_PAIRS


def read_reference_library(path, vehicle, *, speed_kmh, load_fraction, year=2028):
    """Seleccionar siete factores por clave y condiciones, sin sustituciones tácitas."""
    import pandas as pd
    table = pd.read_parquet(path)
    required = {'Category','Fuel','Segment','Euro Standard','rural_speed_kmh','load_fraction',
                'slope_class_pct','hot_ec_mj_per_km','unit','year'}
    if not required <= set(table):
        raise ValueError('La biblioteca no identifica vehículo, condiciones y unidades.')
    if len(vehicle) != 4:
        raise ValueError('La clave del vehículo debe tener cuatro etiquetas completas.')
    mask = table['year'].eq(year) & table.rural_speed_kmh.eq(speed_kmh) & table.load_fraction.eq(load_fraction)
    for field, value in zip(['Category','Fuel','Segment','Euro Standard'],vehicle):
        mask &= table[field].eq(value)
    chosen = table.loc[mask].sort_values('slope_class_pct').copy()
    if len(chosen) != 7 or chosen.slope_class_pct.tolist() != [-6,-4,-2,0,2,4,6]:
        raise ValueError('No hay siete factores únicos para las condiciones elegidas; ejecutar referencias compatibles.')
    if set(chosen.unit) != {'MJ/km'} or any(not math.isfinite(v) or v <= 0 for v in chosen.hot_ec_mj_per_km):
        raise ValueError('Factores ausentes/no positivos o unidades incompatibles.')
    return chosen.reset_index(drop=True)

def apply_reference_factors_by_segment(segments, conditions, library, vehicle, *, year=2028):
    """Calcular Hot EC con condiciones explícitas por segmento y medias por bloque.

    La discretización de pendiente no decide las velocidades. Cada bloque de
    circulación puede cubrir varios segmentos. Solo se admiten combinaciones
    exactas presentes en la biblioteca rural; no se interpola en velocidad.
    """
    import numpy as np
    import pandas as pd
    required_segments = {'segment_id','length_m','slope_pct'}
    required_conditions = {'segment_id','velocidad_media_kmh','carga_fisica',
                           'bloque_velocidad_id','fuente_velocidad','tipo_via'}
    if not required_segments <= set(segments) or not required_conditions <= set(conditions):
        raise ValueError('Faltan segmentos físicos o condiciones de velocidad/carga identificadas.')
    for table in [segments, conditions]:
        if table.empty or table.segment_id.isna().any() or table.segment_id.duplicated().any():
            raise ValueError('Los segmentos deben tener identificadores presentes, únicos y no vacíos.')
    if set(segments.segment_id) != set(conditions.segment_id):
        raise ValueError('Faltan o sobran condiciones: se exige una por cada segmento físico.')
    for name in ['bloque_velocidad_id','fuente_velocidad','tipo_via']:
        if any(not isinstance(v,str) or not v.strip() for v in conditions[name]):
            raise ValueError(f'{name}: cada condición necesita identificación y fuente.')
    if set(conditions.tipo_via) != {'rural'}:
        raise ValueError('La biblioteca actual es rural; preparar factores del entorno solicitado.')
    values = segments[['length_m','slope_pct']].to_numpy(dtype=float)
    cc = conditions[['velocidad_media_kmh','carga_fisica']].to_numpy(dtype=float)
    if (not np.isfinite(values).all() or not np.isfinite(cc).all()
            or (values[:,0] <= 0).any() or (cc[:,0] <= 0).any()
            or (cc[:,1] < 0).any() or (cc[:,1] > 1).any()):
        raise ValueError('Longitudes, pendientes, velocidades o cargas ausentes/no válidas.')
    # Una misma etiqueta de bloque no puede ocultar medias o fuentes contradictorias.
    for _, block in conditions.groupby('bloque_velocidad_id'):
        if any(block[c].nunique(dropna=False) != 1 for c in
               ['velocidad_media_kmh','carga_fisica','fuente_velocidad','tipo_via']):
            raise ValueError('Un bloque de circulación contiene condiciones contradictorias.')
    result = segments.copy(deep=True)
    aligned = conditions.set_index('segment_id').loc[result.segment_id]
    for c in required_conditions - {'segment_id'}:
        result[c] = aligned[c].to_numpy()
    result['pendiente_real_pct'] = result.slope_pct.astype(float)
    result['pendiente_asignacion_pct'] = result.slope_pct.clip(-6,6).astype(float)
    result['fuera_dominio'] = result.slope_pct.abs() > 6
    result['criterio_asignacion'] = np.select(
        [result.slope_pct < -6,result.slope_pct > 6,result.slope_pct.isin([-6,-4,-2,0,2,4,6])],
        ['extremo_-6_exploratorio','extremo_+6_exploratorio','factor_cli_en_nodo'],
        default='interpolacion_lineal_interior')
    factors = np.empty(len(result),dtype=float)
    # Seleccionar antes de sumar: no promediar velocidades ni factores de varios bloques.
    for (speed,load), subset in result.groupby(['velocidad_media_kmh','carga_fisica'],sort=False):
        chosen = read_reference_library(library,vehicle,speed_kmh=speed,load_fraction=load,year=year)
        positions = np.flatnonzero((result.velocidad_media_kmh.to_numpy()==speed)
                                  & (result.carga_fisica.to_numpy()==load))
        factors[positions] = np.interp(subset.pendiente_asignacion_pct,
                                      chosen.slope_class_pct,chosen.hot_ec_mj_per_km)
    result['hot_ec_mj_per_km'] = factors
    result['length_km'] = result.length_m/1000
    result['energia_mj'] = result.length_km*result.hot_ec_mj_per_km
    result['energia_kwh'] = result.energia_mj/3.6
    result['tiempo_a_media_elegida_min'] = result.length_km/result.velocidad_media_kmh*60
    result['estado_calculo'] = 'EXPLORATORIO_PROVISIONAL; condiciones explícitas, validación física pendiente'
    return result


def read_car_reference_library(path,vehicle,*,driving_mode,speed_kmh,year=2028):
    """Leer un factor base exacto; no admitirlo como corrección de montaña."""
    import pandas as pd
    df=pd.read_parquet(path)
    needed={'Category','Fuel','Segment','Euro Standard','year','driving_mode','speed_kmh','hot_ec_mj_per_km','unit','slope_correction'}
    if not needed<=set(df) or len(vehicle)!=4 or driving_mode not in CAR_MODES:
        raise ValueError('Biblioteca, clave o modo de turismo no reconocido.')
    mask=df.year.eq(year)&df.driving_mode.eq(driving_mode)&df.speed_kmh.eq(speed_kmh)
    for field,value in zip(['Category','Fuel','Segment','Euro Standard'],vehicle):mask &= df[field].eq(value)
    chosen=df.loc[mask]
    if len(chosen)!=1:raise ValueError('Falta un factor único para vehículo, año, modo y velocidad.')
    r=chosen.iloc[0]
    if r.unit!='MJ/km' or not math.isfinite(r.hot_ec_mj_per_km) or r.hot_ec_mj_per_km<=0:
        raise ValueError('Factor o unidad no válido.')
    return r.copy()


def seleccionar_referencia_multienergia(biblioteca, vehicle, *, driving_mode, speed_kmh,
                                       primary_fuel_share=None, year=2028):
    """Combinar extremos solo con un control explícito y contraste lineal previo.

    No interpola velocidades, adopta utilización ni descompone Hot a partir
    del desglose TOTAL. Los PHEV pueden conservar combustible en ambos extremos.
    """
    from movilidad_teide.vehiculos.copert_entrada import _car_energy_condition
    import pandas as pd
    key=tuple(vehicle)
    if len(key)!=4 or key[0]!='Passenger Cars' or driving_mode not in CAR_MODES:
        raise ValueError('Clave o modo de referencia multienergía no reconocido.')
    _car_energy_condition([key],primary_fuel_share)
    fields=['Category','Fuel','Segment','Euro Standard']
    needed=set(fields+['year','driving_mode','speed_kmh','primary_control_fraction',
        'hot_ec_mj_per_km','unit','linearity_verified','reference_kind'])
    if not needed<=set(biblioteca):raise ValueError('Biblioteca multienergía sin condiciones o comprobaciones.')
    mask=biblioteca.year.eq(year)&biblioteca.driving_mode.eq(driving_mode)&biblioteca.speed_kmh.eq(speed_kmh)
    for field,value in zip(fields,key):mask &= biblioteca[field].eq(value)
    rows=biblioteca.loc[mask].copy()
    f=pd.to_numeric(rows.hot_ec_mj_per_km,errors='coerce')
    if rows.empty or not rows.unit.eq('MJ/km').all() or f.isna().any() or not f.map(math.isfinite).all() or f.le(0).any():
        raise ValueError('Factores energéticos ausentes, no positivos o unidad incompatible.')
    if key[1]=='Battery electric':
        if len(rows)!=1 or rows.primary_control_fraction.notna().any() or not rows.reference_kind.eq('BEV nativo').all():
            raise ValueError('Referencia eléctrica ambigua o con reparto bifuel indebido.')
        result=float(f.iloc[0])
    elif key[1] in CAR_BIFUEL_PAIRS:
        controls=rows.primary_control_fraction
        if (len(rows)!=2 or controls.duplicated().any() or set(controls)!={0.,1.}
                or not rows.linearity_verified.map(lambda v:isinstance(v,bool) and v).all()
                or not rows.reference_kind.eq('Extremos de control nativo').all()):
            raise ValueError('Faltan extremos exactos o contraste de linealidad del control nativo.')
        values=rows.set_index('primary_control_fraction').hot_ec_mj_per_km
        result=float((1-primary_fuel_share)*values.loc[0.]+primary_fuel_share*values.loc[1.])
    else:raise ValueError('Usar la biblioteca principal para tecnologías sin reparto multienergía.')
    return {'vehicle':list(key),'year':year,'driving_mode':driving_mode,'speed_kmh':speed_kmh,
        'primary_control_fraction':primary_fuel_share,'hot_ec_mj_per_km':result,'unit':'MJ/km',
        'scope':'Referencia condicionada al control nativo; no cuota de energía, UF observado o factor representativo elegido'}
