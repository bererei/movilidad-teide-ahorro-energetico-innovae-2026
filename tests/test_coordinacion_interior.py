"""Capacidad conjunta, regreso a la misma cabecera y visitas sin duplicar."""
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from movilidad_teide.coordinacion_interior import cotas_capacidad_interior,coordinar_visitas_completas


def datos():
    rows=[['u','SUR','ida','Cabecera','Boca',420.,450.],
          ['b','SUR','vuelta','Boca','Cabecera',610.,640.],
          ['i','INTERIOR','ida','Boca','Portillo',465.,510.],
          ['j','INTERIOR','vuelta','Portillo','Boca',550.,595.]]
    m=pd.DataFrame(rows,columns=['id_salida','punto','sentido','origen','destino','salida_min','llegada_min'])
    m['componente']='comercial';m['tipo_dia']='Laborable'
    o=pd.DataFrame({'punto':['SUR'],'corredor':['sur'],'tipo_dia':['Laborable'],
        'demanda_lanzadera_condicionada_dia':[2.],'coches_autorizados_condicionados_dia':[1.], 'dias_calendario':[100]})
    p=pd.DataFrame({'id_subida':['u'],'id_regreso':['b'],'plazas_vinculadas':[2.]})
    return o,m,p


def test_una_visita_consume_dos_trayectos_interiores_sin_duplicar_personas():
    o,m,p=datos();x=cotas_capacidad_interior(o,m,capacidad=2,ocupacion_coche=3.2).iloc[0]
    assert x.plazas_trayecto_totales_dia==4 and x.cota_visitas_dos_trayectos_dia==2
    assert x.fraccion_maxima_solo_por_capacidad_accesos==1
    assert x.fraccion_maxima_pool_accesos_y_coches==pytest.approx(2/5.2)
    assert np.isnan(x.demanda_real_interior_dia) and np.isnan(x.demanda_otros_modos_interior_dia)


def test_cadena_de_cuatro_viajes_conserva_margenes_y_estancia_total():
    o,m,p=datos();before=m.copy(deep=True)
    x=coordinar_visitas_completas(o,m,p,capacidad=2,margen=10,estancia=120,espera_max=20)
    assert x['resumen'].asignacion_constructiva_dia.item()==2
    assert x['asignaciones'].tiempo_en_otro_terminal_min.item()==40  # No exige otras120min en el extremo.
    assert x['cargas'].loc[x['cargas'].punto.eq('INTERIOR'),'personas_asignadas_dia_tipo'].sum()==4
    assert x['cargas'].personas_asignadas_dia_tipo.le(2).all()
    assert_frame_equal(m,before)


def test_recoordinar_billete_permite_bajada_posterior_de_la_misma_cabecera():
    o,m,p=datos();m.loc[m.id_salida.eq('b'),'salida_min']=570.;m.loc[m.id_salida.eq('b'),'llegada_min']=600.
    later=m.loc[m.id_salida.eq('b')].assign(id_salida='tarde',salida_min=610.,llegada_min=640.)
    m=pd.concat([m,later],ignore_index=True)
    fixed=coordinar_visitas_completas(o,m,p,capacidad=2,margen=10,estancia=120)
    free=coordinar_visitas_completas(o,m,p,capacidad=2,margen=10,estancia=120,mantener_pares=False)
    assert fixed['resumen'].asignacion_constructiva_dia.item()==0
    assert free['resumen'].asignacion_constructiva_dia.item()==2
    assert free['asignaciones'].id_bajada_acceso.item()=='tarde'


def test_dos_accesos_comparten_plazas_del_mismo_interior():
    o,m,p=datos();extra=m.loc[m.punto.eq('SUR')].assign(punto='OESTE',id_salida=lambda x:x.id_salida+'2')
    m=pd.concat([m,extra],ignore_index=True)
    o=pd.concat([o,o.assign(punto='OESTE',corredor='oeste')],ignore_index=True)
    p=pd.concat([p,p.assign(id_subida='u2',id_regreso='b2')],ignore_index=True)
    x=coordinar_visitas_completas(o,m,p,capacidad=2,margen=10,estancia=120)
    assert x['resumen'].asignacion_constructiva_dia.sum()==2
    assert x['resumen'].pendiente_no_certifica_imposibilidad_dia.sum()==2
    assert x['cargas'].loc[x['cargas'].punto.eq('INTERIOR'),'personas_asignadas_dia_tipo'].max()==2


def test_espera_y_margen_se_cuentan_desde_la_llegada_no_se_suman_dos_veces():
    o,m,p=datos();m.loc[m.id_salida.eq('i'),'salida_min']=475.
    x=coordinar_visitas_completas(o,m,p,capacidad=2,margen=10,estancia=120,espera_max=20)
    y=coordinar_visitas_completas(o,m,p,capacidad=2,margen=10,estancia=120,espera_max=None)
    assert x['resumen'].asignacion_constructiva_dia.item()==0
    assert y['resumen'].asignacion_constructiva_dia.item()==2


@pytest.mark.parametrize('error',['capacidad','duplicado','margen','par_duplicado','cabecera'])
def test_no_se_relajan_entradas_para_obtener_capacidad(error):
    o,m,p=datos();cap=2;wait=20
    if error=='capacidad':cap=0
    if error=='duplicado':m=pd.concat([m,m.iloc[[0]]])
    if error=='margen':wait=5
    if error=='par_duplicado':p=pd.concat([p,p])
    if error=='cabecera':m.loc[m.id_salida.eq('b'),'punto']='OTRA'
    with pytest.raises(ValueError):coordinar_visitas_completas(o,m,p,capacidad=cap,margen=10,estancia=120,espera_max=wait)


def test_demanda_no_asignada_no_se_convierte_en_transporte_o_ahorro():
    o,m,p=datos();m.loc[m.id_salida.eq('j'),'salida_min']=700.;m.loc[m.id_salida.eq('j'),'llegada_min']=745.
    x=coordinar_visitas_completas(o,m,p,capacidad=2,margen=10,estancia=120)
    assert x['resumen'].asignacion_constructiva_dia.item()==0
    assert x['resumen'].demanda_real_interior_dia.isna().all()
    assert not x['resumen'].operacion_validada.any()
