"""Preparar masas, perfiles y coeficientes sin cantidades de escenarios históricos."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from movilidad_teide.circulacion_turismos import cargar_y_clasificar_referencias
from movilidad_teide.energia.pendiente import (
    masas_grupos_desde_dgt, cargar_perfiles_completos, perfiles_visita_interior,
    preparar_curvas_convencionales, energia_pendiente_por_recorrido,
    coeficiente_por_recorrido,
)
from movilidad_teide.flujos.tipos import Etapa

CASOS_PENDIENTE = [
    ('Referencia del Excel', {}),
    ('Descenso sin reducción', {'tratamiento': 'Sin reducción de consumo en descenso'}),
    ('Tara P25', {'estadistico': 'Cuartil inferior (P25)'}),
    ('Tara P75', {'estadistico': 'Cuartil superior (P75)'}),
    ('Transmisión 0,95', {'multiplicador_eta': 0.95 / 0.85}),
]

def preparar_fisica(root, parametros):
    """Conservo las fuentes y controles físicos, separados de la anualización."""
    root_a = Path(root)
    params_a = parametros
    v_a = {p['id']: p['valor_utilizado'] for p in params_a['parametros']}
    read_a = lambda p: pd.read_csv(p, sep=';', float_precision='round_trip')
    paths_a = {'pesos': 'data/silver/vehiculos/ponderacion/pesos_curvas.csv', 'perfiles_stock': 'data/silver/vehiculos/ponderacion/perfiles_referencia.csv', 'factores': 'data/silver/vehiculos/ponderacion/factores.csv', 'diagnostico': 'data/silver/vehiculos/flota_teide/representacion_tecnica/perfiles_elegidos_diagnostico.csv', 'tamanos': 'data/silver/vehiculos/flota_teide/propuesta_tamanos_turismos_detalle.csv', 'municipios': 'data/silver/vehiculos/flota_teide/contraste_municipal_2025.csv', 'microdatos': 'data/bronze/vehiculos/dgt_microdatos_2025/provincia_38/38.SANTA_CRUZ_DE_TENERIFE.txt', 'equivalencias': 'data/bronze/documentacion/seleccion_vehiculos/20261024_microdatos_dgt/correspondencia_normas.json', 'biblioteca': 'data/silver/copert/factores/factores_turismos.parquet', 'patrones': 'data/silver/energia/turismos/visita_interior/recorridos_interiores.csv', 'recorridos': 'data/silver/demanda/asignacion/recorridos_referencia_calculo.csv', 'tipologias': 'data/silver/geografia/clases_via/recorridos_referencia/tipologia_por_componente.csv'}
    x_a = {k: read_a(root_a / p) for (k, p) in paths_a.items() if p.endswith('.csv') and k != 'tamanos'}
    print('Conciliación de perfiles completos y clases de vía existentes...', flush=True)
    geography_a = cargar_y_clasificar_referencias(root_a, por_arista=True)
    roads_a = geography_a['clasificacion']
    inventory_a = geography_a['inventario']
    keys_a = ['comparacion_id', 'itinerary_id', 'rol', 'clase_propuesta']
    totals_a = roads_a.groupby(keys_a).length_m.sum() / 1000
    saved_a = x_a['tipologias'].set_index(keys_a).longitud_clase_km
    assert set(totals_a.index) == set(saved_a.index)
    assert np.allclose(totals_a.sort_index(), saved_a.sort_index(), rtol=0, atol=1e-08)
    (profiles_a, physical_files_a) = cargar_perfiles_completos(root_a, roads_a, inventory_a)
    profiles_a = pd.concat([profiles_a, perfiles_visita_interior(root_a, x_a['patrones'])], ignore_index=True)
    assert profiles_a.groupby(['comparacion_id', 'itinerary_id', 'rol']).ngroups == 126
    sizes_a = pd.read_csv(root_a / paths_a['tamanos'], sep=';', dtype=str, keep_default_na=False)
    eq_a = json.loads((root_a / paths_a['equivalencias']).read_text())['equivalencias']
    masses_a = masas_grupos_desde_dgt(root_a / paths_a['microdatos'], x_a['municipios'].TERRITORIO.astype(int).astype(str).tolist(), eq_a, sizes_a, x_a['diagnostico'])
    assert int(masses_a.vehiculos.sum()) == 509459 and len(masses_a) == 816
    curves_a = preparar_curvas_convencionales(x_a['pesos'], x_a['perfiles_stock'], masses_a, pd.read_parquet(root_a / paths_a['biblioteca']), params_a)
    return dict(x=x_a, perfiles=profiles_a, masas=masses_a, curvas=curves_a,
                archivos_fisicos=physical_files_a)


def calcular_coeficientes_pendiente(root, parametros):
    """Valoro las claves de la demanda vigente; no leo cantidades anuales previas.

    Las claves se obtienen de las ofertas actuales. Las ramas distinguen acceso
    directo (incluida visita interior) y alimentación hasta cabecera. Sus valores
    son por vehículo y sentido; la actividad anual se aplica en su propio flujo.
    """
    root = Path(root)
    base = preparar_fisica(root, parametros)
    cfg = json.loads((root/'config/referencia_ordenacion_2028.json').read_text())
    paths = sorted((root/cfg['captura']/'ofertas').glob('*/*/*/origenes.csv'))
    if not paths: raise FileNotFoundError('Faltan las claves de demanda vigente.')
    keys = pd.concat([pd.read_csv(p, sep=';', usecols=['origen_id','colectivo']) for p in paths]).drop_duplicates().sort_values(['origen_id','colectivo'])
    routes = base['x']['recorridos'].set_index(['origen_id','sentido'])
    occ = {p['id']:p['valor_utilizado'] for p in parametros['parametros']}['ocupacion_coche']
    energies, units = [], []
    for case, overrides in CASOS_PENDIENTE:
        print('Coeficientes físicos:', case, flush=True)
        ee = pd.concat([energia_pendiente_por_recorrido(base['perfiles'],base['curvas'],base['x']['factores'],parametros,ocupacion=o,**overrides) for o in [occ,1.]],ignore_index=True)
        lookup = ee.set_index(['comparacion_id','itinerary_id','rol','grupo_servicio','ocupacion_coche'],verify_integrity=True)
        for alt in ['España no Tenerife: alquiler','España no Tenerife: particular']:
            for k in keys.itertuples():
                for direction in ['hacia_teide','desde_teide']:
                    rr = routes.loc[k.origen_id,direction]
                    for branch in ['antes','autorizados','transferidos','alimentacion_otros']:
                        occupancy = 1. if branch=='alimentacion_otros' else occ
                        vals, service = coeficiente_por_recorrido(rr,lookup,alternativa=alt,colectivo=k.colectivo,sentido=direction,rama=branch,ocupacion=occupancy)
                        units.append(dict(alternativa_procedencia=alt,origen_id=k.origen_id,colectivo=k.colectivo,sentido=direction,rama=branch,grupo_servicio=service,
                            componente='Alimentación adicional desde otros modos' if branch=='alimentacion_otros' else 'Coches del reparto modal',ocupacion_hipotesis=occupancy,
                            energia_base_mwh_por_vehiculo_sentido=vals[0]/3600,correccion_mwh_por_vehiculo_sentido=vals[2]/3600,caso_pendiente=case))
        energies.append(ee.assign(caso_pendiente=case))
    flat=base['perfiles'].copy();flat['elevation_end_m']=flat.elevation_start_m;flat['slope_pct']=0.
    check=energia_pendiente_por_recorrido(flat,base['curvas'],base['x']['factores'],parametros,ocupacion=occ)
    assert check.correccion_convencional_mj.abs().lt(1e-8).all()
    return Etapa({'masas_por_grupo':base['masas'],'energia_por_recorrido':pd.concat(energies,ignore_index=True),'correccion_por_origen_y_rama':pd.DataFrame(units)},
                 {'segmentos_por_via':base['perfiles'],'curvas_y_masas':base['curvas']})
