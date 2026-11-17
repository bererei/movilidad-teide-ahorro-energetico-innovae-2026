"""Reservas por tramo y ventanas de visita, con casos sintéticos de control."""
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from movilidad_teide.coordinacion_interior import (
    referenciar_paradas_del_eje, horario_en_paradas, cargas_por_tramos, coordinar_destino_por_tramos)


def datos_tramos():
    s=pd.DataFrame({'parada_id':['a','b','c','d'], 'lugar':['Boca Tauce','Parador','Teleférico','El Portillo'],
        'orden':range(4), 'posicion_m':[0.,1000.,2000.,3000.]})
    m=pd.DataFrame([
        ['u','SUR','ida','Cabecera','Boca Tauce',0.,30.,3.],
        ['back','SUR','vuelta','Boca Tauce','Cabecera',210.,240.,3.],
        ['i','INTERIOR','ida','Boca Tauce','El Portillo',45.,90.,3.],
        ['j','INTERIOR','vuelta','El Portillo','Boca Tauce',150.,195.,3.]],
        columns=['id_salida','punto','sentido','origen','destino','salida_min','llegada_min','km_por_recorrido'])
    m['componente']='comercial';m['tipo_dia']='Laborable'
    o=pd.DataFrame({'punto':['SUR'], 'corredor':['sur'], 'demanda_lanzadera_condicionada_dia':[3.]})
    return o,m,s,horario_en_paradas(m,s)


def coord(o,m,s,h,**kw):
    return coordinar_destino_por_tramos(o,m,s,h,capacidad=2,margen=10,estancia=120,espera_max=20,**kw)


def test_distribuir_tiempos_preserva_extremos_y_simetria_sin_inventar_paradas_medidas():
    o,m,s,h=datos_tramos()
    a=h.loc[h.id_salida.eq('i')].set_index('parada_id').paso_min
    b=h.loc[h.id_salida.eq('j')].set_index('parada_id').paso_min
    assert list(a)==[45.,60.,75.,90.]
    assert list(b)==[195.,180.,165.,150.]
    assert h.tiempo_parada_individualizado_min.isna().all()
    assert not h.horario_observado.any()


def test_dos_reservas_no_solapadas_reutilizan_la_misma_plaza():
    o,m,s,h=datos_tramos()
    bookings=pd.DataFrame([['i','a','b',2.],['i','b','d',2.]],
        columns=['id_salida','parada_origen','parada_destino','personas'])
    loads=cargas_por_tramos(h,s,bookings,capacidad=2)
    assert loads.loc[loads.id_salida.eq('i'),'personas_asignadas_prueba_dia'].tolist()==[2.,2.,2.]
    assert loads.demanda_real_otros_usuarios.isna().all()


def test_solapamiento_sobre_el_mismo_tramo_se_rechaza():
    o,m,s,h=datos_tramos()
    bookings=pd.DataFrame([['i','a','c',2.],['i','b','d',2.]],
        columns=['id_salida','parada_origen','parada_destino','personas'])
    with pytest.raises(ValueError,match='supera plazas'):
        cargas_por_tramos(h,s,bookings,capacidad=2)


def test_destino_intermedio_deja_libres_los_tramos_no_recorridos():
    o,m,s,h=datos_tramos();before=m.copy(deep=True)
    z=coord(o,m,s,h,destino='b',ventana_parada_min=120)
    assert z['resumen'].asignacion_constructiva_dia.item()==2
    assert z['resumen'].pendiente_constructivo_no_imposibilidad_dia.item()==1
    assert len(z['reservas_interiores'])==2
    assert z['asignaciones'].ventana_parada_min.item()==120
    assert z['asignaciones'].tiempo_actividad_util_validado_min.isna().all()
    assert z['cargas_tramos'].query('tramo_orden>0').personas_asignadas_prueba_dia.eq(0).all()
    assert_frame_equal(m,before)


def test_ventana_corta_en_extremo_no_cumple_contraste_120_aunque_cumpla_estancia_parque():
    o,m,s,h=datos_tramos()
    a=coord(o,m,s,h,destino='otro_terminal',ventana_parada_min=0)
    b=coord(o,m,s,h,destino='otro_terminal',ventana_parada_min=120)
    assert a['resumen'].asignacion_constructiva_dia.item()==2
    assert a['asignaciones'].ventana_parada_min.item()==60
    assert b['resumen'].asignacion_constructiva_dia.item()==0
    assert b['resumen'].demanda_real_interior_dia.isna().all()


def test_visita_al_terminal_no_consume_plazas_interiores():
    o,m,s,h=datos_tramos();z=coord(o,m,s,h,destino=None,ventana_parada_min=120)
    assert z['resumen'].asignacion_constructiva_dia.item()==2
    assert z['reservas_interiores'].empty
    assert z['cargas_tramos'].personas_asignadas_prueba_dia.eq(0).all()


def test_dos_accesos_comparten_capacidad_entre_paradas():
    o,m,s,h=datos_tramos()
    m=pd.concat([m,m.loc[m.punto.eq('SUR')].assign(punto='OESTE',id_salida=lambda x:x.id_salida+'2')],ignore_index=True)
    o=pd.concat([o,o.assign(punto='OESTE',corredor='oeste')],ignore_index=True)
    z=coord(o,m,s,h,destino='b')
    assert z['resumen'].asignacion_constructiva_dia.sum()==2
    assert z['resumen'].pendiente_constructivo_no_imposibilidad_dia.sum()==4


@pytest.mark.parametrize('error',['sentido','longitud','repetido','no_finito','destino','sin_horario','mismo_sentido'])
def test_no_se_fabrican_cadenas_con_entradas_incoherentes(error):
    o,m,s,h=datos_tramos()
    if error=='sentido':m.loc[m.id_salida.eq('i'),'sentido']='vuelta'
    if error=='longitud':m.loc[m.id_salida.eq('i'),'km_por_recorrido']=4
    if error=='repetido':m=pd.concat([m,m.iloc[[2]]])
    if error=='no_finito':m.loc[m.id_salida.eq('i'),'llegada_min']=np.nan
    if error in {'sentido','longitud','repetido','no_finito'}:
        with pytest.raises(ValueError):horario_en_paradas(m,s)
    elif error=='destino':
        with pytest.raises(ValueError):coord(o,m,s,h,destino='inventado')
    elif error=='sin_horario':
        with pytest.raises(ValueError):coord(o,m,s,h.iloc[:-1],destino='b')
    else:
        booking=pd.DataFrame([['i','c','b',1]],columns=['id_salida','parada_origen','parada_destino','personas'])
        with pytest.raises(ValueError):cargas_por_tramos(h,s,booking,capacidad=2)


def test_las_entradas_adoptadas_prevalecen_sobre_el_marcador_turistico_y_comparten_objetivos():
    import geopandas as gpd
    from shapely.geometry import LineString,Point
    crs='EPSG:4083'
    route=gpd.GeoDataFrame({'itinerary_id':['ida']},geometry=[LineString([(0,0),(3000,0)])],crs=crs)
    anchors=gpd.GeoDataFrame({'itinerary_id':['ida']*3,'anchor_id':['a','b','d'],
        'anchor_role':['origin','waypoint','destination'],'itinerary_measure_m':[0.,1000.,3000.],
        'label':['Boca','Entrada','Portillo']},geometry=[Point(0,0),Point(1000,0),Point(3000,0)],crs=crs)
    points=gpd.GeoDataFrame({'target_id':['roques','parador','mirador'],'lugar':['Roques','Parador','Mirador'],
        'adoptada_para_estudio':[True]*3},geometry=[Point(900,200),Point(950,300),Point(2000,10)],crs=crs)
    att=gpd.GeoDataFrame({'target_id':['roques','parador'],'anchor_id_referencia':['b','b']},
        geometry=[Point(1000,0),Point(1000,0)],crs=crs)
    s,c=referenciar_paradas_del_eje(route,anchors,att,points,itinerario_ida='ida')
    assert s.posicion_m.tolist()==[0.,1000.,2000.,3000.]
    assert c.loc[c.target_id.isin(['roques','parador']),'parada_id'].nunique()==1
    assert c.tiempo_acceso_peatonal_min.isna().all()
    assert not c.embarque_validado.any()
