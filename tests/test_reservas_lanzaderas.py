"""La reserva favorable no duplica plazas ni demuestra operación observada."""
import pandas as pd
import numpy as np
import pytest
from movilidad_teide.reservas_lanzaderas import asignar_reservas_favorables


def datos():
    d=pd.DataFrame({'hora_servicio':[7,8],'personas_dia_tipo_condicionadas':[1.,1.]})
    m=pd.DataFrame({'id_salida':['temprana','compartida','regreso1','regreso2'],
        'sentido':['ida','ida','vuelta','vuelta'],'componente':['comercial']*4,
        'salida_min':[450.,480.,660.,670.],'llegada_min':[480.,510.,690.,700.]})
    return d,m


def test_reasignacion_global_conserva_plazas_y_cohortes():
    d,m=datos();x=asignar_reservas_favorables(d,m,capacidad=1,espera_min=20,estancia_min=120)
    assert x['asignable']==2 and x['pendiente']==0
    assert x['por_salida'].groupby('sentido').personas_asignadas_favorables.sum().tolist()==[2,2]
    assert (x['por_salida'].personas_asignadas_favorables<=1).all()


def test_un_regreso_no_puede_servir_dos_cohortes_completas():
    d,m=datos();m=m.iloc[:-1]
    x=asignar_reservas_favorables(d,m,capacidad=1,espera_min=20,estancia_min=120)
    assert x['asignable']==1 and x['pendiente']==1


def test_llegada_a_limite_horario_y_visita_no_se_eliminan():
    d,m=datos();d.loc[0,'hora_servicio']=6
    x=asignar_reservas_favorables(d,m,capacidad=1,espera_min=20,estancia_min=120)
    assert x['por_hora'].loc[x['por_hora'].hora_servicio.eq(6),'sin_asignacion_incluso_favorable'].item()==1
    y=asignar_reservas_favorables(d,m,capacidad=1,espera_min=20,estancia_min=999)
    assert y['asignable']==0 and y['pendiente']==2


def test_no_se_imputa_demanda_atendida_a_falta_de_salidas():
    d,m=datos();x=asignar_reservas_favorables(d,m.iloc[:0],capacidad=1,espera_min=20,estancia_min=120)
    assert x['asignable']==0 and x['pendiente']==2


@pytest.mark.parametrize('cambio',['duplicado','hora','demanda','tiempo','capacidad'])
def test_rechazo_de_entradas_incoherentes(cambio):
    d,m=datos();cap=1
    if cambio=='duplicado':m=pd.concat([m,m.iloc[[0]]])
    if cambio=='hora':d.loc[0,'hora_servicio']=24
    if cambio=='demanda':d.loc[0,'personas_dia_tipo_condicionadas']=np.nan
    if cambio=='tiempo':m.loc[0,'llegada_min']=0
    if cambio=='capacidad':cap=0
    with pytest.raises(ValueError):asignar_reservas_favorables(d,m,capacidad=cap,espera_min=20,estancia_min=120)


def perfil_minimo():
    rows=[];indices=[]
    for i in range(9):
        indices.append({'matrix_index':i,'anio':2025,'mes_publicado':['Marzo','Julio','Octubre'][i//3],
            'tipo_dia_publicado':['Laborable','Sábado','Domingo'][i%3]})
        for hour in [8,9]:rows.append({'matrix_index':i,'access_corridor':'a','direccion':'subida','hora_servicio':hour,
            'extranjero':1.,'espana_no_tenerife':0.,'tenerife_no_frecuente':0.,'tenerife_resto':0.})
    return pd.DataFrame(rows),pd.DataFrame(indices),pd.DataFrame({'corredor':['a'],'plazas_necesarias_subida_si_transferencia_completa':[1000.]})


def test_forma_temporal_conserva_objetivo_y_calendario_no_percentiles():
    from movilidad_teide.reservas_lanzaderas import repartir_perfil_horario
    p,i,o=perfil_minimo();x=repartir_perfil_horario(p,i,o)
    assert x.personas_anuales_condicionadas.sum()==pytest.approx(1000)
    assert x[['tipo_dia_publicado','dias_calendario']].drop_duplicates().dias_calendario.sum()==366
    assert x.matrices_con_registro.eq(3).all()
    assert set(x.hora_servicio)=={8,9}  # No fabrica horas no publicadas con demanda cero.


def test_cobertura_parcial_de_una_hora_permanece_identificada():
    from movilidad_teide.reservas_lanzaderas import repartir_perfil_horario
    p,i,o=perfil_minimo();p=p.loc[~(p.matrix_index.eq(0)&p.hora_servicio.eq(8))]
    x=repartir_perfil_horario(p,i,o)
    assert x.matrices_con_registro.min()==2
    assert x.personas_anuales_condicionadas.sum()==pytest.approx(1000)
    with pytest.raises(ValueError):repartir_perfil_horario(p,pd.concat([i,i.iloc[[0]]]),o)


def test_reserva_anticipada_permite_otra_franja_sin_duplicar_regreso():
    d,m=datos();d['hora_servicio']=[0,1]
    old=asignar_reservas_favorables(d,m,capacidad=1,espera_min=20,estancia_min=120)
    new=asignar_reservas_favorables(d,m,capacidad=1,espera_min=20,estancia_min=120,cambio_franja=True)
    assert old['asignable']==0 and new['asignable']==2
    assert new['pares'].plazas_vinculadas.sum()==2
    assert (new['pares'].salida_regreso_min-new['pares'].llegada_parque_min>=120).all()


def test_refuerzos_conservan_horarios_y_capacidad_entera_vinculada():
    from movilidad_teide.reservas_lanzaderas import proponer_refuerzos_reservados
    d,m=datos();m['punto']='p'
    o=pd.DataFrame({'corredor':['a','a'],'demanda_lanzadera_condicionada_dia':[2.,3.1]})
    x=proponer_refuerzos_reservados(o,m,{'a':'p'},capacidad=1,estancia_min=120)
    assert x['resumen'].pares_adicionales_por_dia.item()==2
    assert set(m.id_salida)<=set(x['salidas'].id_salida)
    assert set(x['salidas'].salida_min)<=set(m.salida_min)
    assert x['pares'].plazas_vinculadas.sum()==4
    with pytest.raises(ValueError):proponer_refuerzos_reservados(o,m,{'a':'p'},capacidad=.85,estancia_min=120)


def test_objetivos_diarios_respetan_un_solo_cupo_entero_y_no_duplican_captacion():
    from movilidad_teide.reservas_lanzaderas import objetivos_reservados_por_dia
    r=pd.DataFrame({'matrix_index':[0,0,1,1,2,2],'access_corridor':['a','b']*3,'colectivo':['c']*6,
        'direccion':['subida']*6,'tipo_dia_publicado':['Laborable']*6,
        'viajes_persona_dia_referencia':[2400.,1200.]*3,'viajes_persona_captables_dia_referencia':[600.,300.]*3})
    x=objetivos_reservados_por_dia(r,{'Laborable':100},crecimiento=1,ocupacion=3,fraccion_coche=.75,cupo=200)
    assert x['resumen'].cupo_coches_propuesto_dia.sum()==200
    assert x['resumen'].cupo_coches_propuesto_dia.tolist()==[133,67]
    assert x['detalle'].recorridos_coche_retirados_condicionados_anio.sum()==70000
    assert x['resumen'].demanda_lanzadera_condicionada_dia.sum()==2325


def test_cupo_diario_holgado_no_fabrica_retiradas():
    from movilidad_teide.reservas_lanzaderas import objetivos_reservados_por_dia
    r=pd.DataFrame({'matrix_index':[0],'access_corridor':['a'],'colectivo':['c'],'direccion':['subida'],
        'tipo_dia_publicado':['Laborable'],'viajes_persona_dia_referencia':[300.],
        'viajes_persona_captables_dia_referencia':[60.]})
    x=objetivos_reservados_por_dia(r,{'Laborable':100},crecimiento=1,ocupacion=3,fraccion_coche=1,cupo=500)
    assert x['detalle'].recorridos_coche_retirados_condicionados_anio.sum()==0
    assert x['resumen'].cupo_coches_propuesto_dia.sum()==100
