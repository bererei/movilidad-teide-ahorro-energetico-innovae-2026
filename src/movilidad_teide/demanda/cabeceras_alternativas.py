"""Conservo el origen del viajero al cambiar su cabecera de reserva."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from movilidad_teide.trazabilidad import sha256_archivo

FUENTE='data/bronze/geografia/rutas_cabeceras/20261108_osrm'
PAREJAS={'OROTAVA':'LAGUNA','LAGUNA':'OROTAVA','CHIO':'VILAFLOR','VILAFLOR':'CHIO'}


def leer_catalogo(root):
    """Acepto ida y vuelta propias, fuera del Parque y sin accesos inventados."""
    folder=Path(root)/FUENTE
    t=pd.read_csv(folder/'catalogo.csv',sep=';',float_precision='round_trip')
    if t.duplicated(['origen_id','sentido']).any() or not set(t.sentido)=={'ida','vuelta'}:
        raise ValueError('Catálogo de alimentación repetido o incompleto.')
    if (not np.isfinite(t[['km','minutos','alimentador_km','extra_km']]).all().all()
        or t[['km','minutos','alimentador_km']].le(0).any().any()
        or t.interseccion_parque_m.gt(1e-8).any()
        or t[['ajuste_inicio_m','ajuste_final_m']].gt(1).any().any()):
        raise ValueError('Conexión sin longitud, fuera de precisión cartográfica o dentro del Parque.')
    for a in t.itertuples():
        if PAREJAS.get(a.cabecera_origen)!=a.cabecera_reserva or sha256_archivo(folder/a.archivo)!=a.sha256:
            raise ValueError('Pareja o respuesta de rutas alterada.')
        raw=json.loads((folder/a.archivo).read_text())
        if raw['code']!='Ok' or abs(raw['routes'][0]['distance']/1000-a.km)>1e-8:
            raise ValueError('La longitud no corresponde a la respuesta conservada.')
    for _,g in t.groupby('origen_id'):
        if len(g)!=2 or g.cabecera_origen.nunique()!=1 or g.cabecera_reserva.nunique()!=1:
            raise ValueError('Falta una cadena de alimentación de ida y vuelta propia.')
    return t


def capacidad_elegible(modal,catalogo):
    x=modal['por_origen_dia'];ids=set(catalogo.origen_id)
    return x[x.origen_id.isin(ids)].groupby('punto').visitas_coche_transferidas_dia.sum()


def trasladar_reservas(modal,catalogo,traslados,*,ocupacion):
    """Traslado solo coche→lanzadera; TITSA y permisos de coche no cambian.

    La elección territorial ordena el incremento de km de ida+vuelta. Dentro
    de cada origen conservo proporcionalmente sus colectivos. El regreso es
    a la misma cabecera donde queda el coche; el interior de cada pareja es igual.
    """
    x=modal['por_origen_dia'];p=modal['escenarios_por_punto_dia'].copy()
    p['demanda_lanzadera_origen_dia']=p.demanda_lanzadera_dia
    costs=catalogo.groupby(['origen_id','cabecera_origen','cabecera_reserva'],as_index=False).agg(extra_km_ida_vuelta=('extra_km','sum'),km_ida_vuelta=('km','sum'),min_osrm_ida_vuelta=('minutos','sum'),km_original_ida_vuelta=('alimentador_km','sum'))
    rows=[]
    for origen,destino,n in traslados:
        if PAREJAS.get(origen)!=destino or not np.isfinite(n) or n<0:raise ValueError('Traslado de cabecera no admisible.')
        pending=float(n)
        own=costs[costs.cabecera_origen.eq(origen)&costs.cabecera_reserva.eq(destino)].sort_values(['extra_km_ida_vuelta','origen_id'],kind='stable')
        for cost in own.itertuples():
            g=x[x.origen_id.eq(cost.origen_id)&x.punto.eq(origen)];eligible=float(g.visitas_coche_transferidas_dia.sum())
            moved=min(pending,eligible)
            if moved<=0:continue
            for a in g.itertuples():
                people=moved*a.visitas_coche_transferidas_dia/eligible
                if people<=0:continue
                rows.append({'origen_id':a.origen_id,'colectivo':a.colectivo,'corredor_fuente':a.corredor_fuente,'punto_original':origen,'punto_reserva':destino,'punto_regreso':destino,
                    'visitas_persona_dia':people,'vehiculos_alimentadores_dia':people/ocupacion,'extra_vehiculo_km_dia':people/ocupacion*cost.extra_km_ida_vuelta,
                    'km_alimentador_nuevo_ida_vuelta':cost.km_ida_vuelta,'km_alimentador_original_ida_vuelta':cost.km_original_ida_vuelta,
                    'extra_km_ida_vuelta':cost.extra_km_ida_vuelta,'min_osrm_nuevo_ida_vuelta':cost.min_osrm_ida_vuelta,
                    'extra_min_ida_vuelta_a_40_kmh':cost.extra_km_ida_vuelta*1.5,
                    'extra_persona_min_dia_a_40_kmh':people*cost.extra_km_ida_vuelta*1.5,
                    'modo_previo':'coche','modo_con':'lanzadera','interior_y_destino_conservados':True})
            pending-=moved
            if pending<1e-10:break
        if pending>1e-8:raise ValueError('No hay viajeros con alimentador propio para este traslado.')
        p.loc[p.punto.eq(origen),'demanda_lanzadera_dia']-=n
        p.loc[p.punto.eq(destino),'demanda_lanzadera_dia']+=n
    p['saldo_reasignacion_cabecera_personas_dia']=p.demanda_lanzadera_dia-p.demanda_lanzadera_origen_dia
    p['regresos_lanzadera_pareados_dia']=p.demanda_lanzadera_dia
    # SIN conserva el origen; CON distingue el acceso efectivo tras el traslado.
    p['visitas_con_objetivo_dia']+=p.saldo_reasignacion_cabecera_personas_dia
    if abs(p.saldo_reasignacion_cabecera_personas_dia.sum())>1e-8 or p.demanda_lanzadera_dia.lt(-1e-8).any():
        raise ValueError('El cambio de cabecera pierde visitantes.')
    return {**modal,'escenarios_por_punto_dia':p},pd.DataFrame(rows)
