"""Resto del parque, coeficientes firmados y alcance técnico Hot/frío/total."""
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from openpyxl import Workbook,load_workbook
from movilidad_teide.balance_condicionado import desglosar_resto_sin_referencia,coeficientes_energia_resto,MAGNITUD_ANUAL
from movilidad_teide.copert_cli import auditar_alcance_energia


def diagnostico():
    return pd.DataFrame({'grupo_id':[0,1,2],'grupo_servicio':['B00']*3,'vehiculos':[70,10,20],
        'representado_en_contraste':[True,False,False],
        'referencia_condicionada_disponible':[False,True,False],
        'estado_incompletos':['Representado previamente','Referencia condicionada','Norma no revisada']})


def test_resto_excluye_lo_previo_aunque_no_tenga_referencia_nueva():
    d=diagnostico();before=d.copy(deep=True);z=desglosar_resto_sin_referencia(d)
    assert z['resto'].grupo_id.tolist()==[2]
    s=z['resumen'].iloc[0]
    assert s.vehiculos_stock==100 and s.vehiculos_aun_sin_referencia==20
    assert s.fraccion_stock_sin_referencia==.2 and pd.isna(s.fraccion_energia_sin_referencia)
    assert_frame_equal(d,before)


@pytest.mark.parametrize('fallo',['duplicado','doble_conteo','negativo','fraccionario','no_finito','bandera'])
def test_cobertura_no_oculta_perdidas_o_doble_conteo(fallo):
    d=diagnostico()
    if fallo=='duplicado':d=pd.concat([d,d.iloc[[0]]])
    if fallo=='doble_conteo':d.loc[0,'referencia_condicionada_disponible']=True
    if fallo=='negativo':d.loc[0,'vehiculos']=-1
    if fallo=='fraccionario':d['vehiculos']=d.vehiculos.astype(float);d.loc[0,'vehiculos']=.5
    if fallo=='no_finito':d['vehiculos']=d.vehiculos.astype(float);d.loc[0,'vehiculos']=np.inf
    if fallo=='bandera':d['representado_en_contraste']=d.representado_en_contraste.astype(object);d.loc[0,'representado_en_contraste']='False'
    with pytest.raises(ValueError):desglosar_resto_sin_referencia(d)


def entradas_coeficiente():
    p=pd.DataFrame({'origen_id':['a','fuera'],'colectivo':['c','c'],'sentido':['hacia_teide']*2,
        'en_ambito_anual':[True,False],MAGNITUD_ANUAL:[10.,np.nan]})
    r=pd.DataFrame({'origen_id':['a','fuera'],'sentido':['hacia_teide']*2,
        'comparacion_calculo_id':['r','r'],'tipo_representacion_calculo':['perfil_propio']*2,
        'itinerario_referencia_id':['directa']*2,'itinerario_alimentador_id':['alimento']*2,
        'directa_km':[10.,10.],'alimentador_km':[12.,12.]})
    c=pd.DataFrame({'comparacion_id':['r','r'],'itinerary_id':['directa','alimento'],
        'rol':['directa','alimentador'],'clase_propuesta':['convencional']*2,'longitud_clase_km':[10.,12.]})
    cov=desglosar_resto_sin_referencia(diagnostico())['resumen']
    return p,r,c,cov


def test_coeficiente_conserva_desvio_negativo_y_ausencias_sin_inventar_factor():
    p,r,c,cov=entradas_coeficiente();z=coeficientes_energia_resto(p,r,c,cov,fraccion_coche_alimentador=1)
    assert z['resumen'].coeficiente_veh_km_condicionados_anio.item()==-4
    assert z['resumen'].respuesta_mwh_anio_por_incremento_comun_de_1_mj_km.item()==pytest.approx(-4/3600)
    assert z['detalle'].loc[~z['detalle'].en_ambito_anual,'coeficiente_veh_km_condicionados_anio'].isna().all()
    assert z['detalle'].factor_resto_mj_km.isna().all()
    assert z['resumen'].aporte_energetico_resto_mwh_anio.isna().all()


def test_coeficiente_cancela_longitud_comun_antes_de_usar_cualquier_factor():
    p,r,c,cov=entradas_coeficiente();r['alimentador_km']=10.;c['longitud_clase_km']=10.
    z=coeficientes_energia_resto(p,r,c,cov,fraccion_coche_alimentador=1)
    assert z['resumen'].coeficiente_veh_km_condicionados_anio.item()==0


@pytest.mark.parametrize('fallo',['tipologia','longitud','origen','stock','actividad'])
def test_coeficiente_rechaza_incoherencias(fallo):
    p,r,c,cov=entradas_coeficiente()
    if fallo=='tipologia':c.loc[0,'clase_propuesta']='inventada'
    if fallo=='longitud':c.loc[0,'longitud_clase_km']=99
    if fallo=='origen':r=r.iloc[:1]
    if fallo=='stock':cov['vehiculos_stock']=0
    if fallo=='actividad':p.loc[0,MAGNITUD_ANUAL]=-1
    with pytest.raises(ValueError):coeficientes_energia_resto(p,r,c,cov,fraccion_coche_alimentador=1)


KEY=('Passenger Cars','Petrol','Small','Euro 4')


def libros(tmp_path,cold=2e-6):
    inp=Workbook();inp.remove(inp.active)
    for name,value in [('STOCK',1),('MEAN_ACTIVITY',17)]:
        s=inp.create_sheet(name);s.append(['Category','Fuel','Segment','Euro Standard','2028']);s.append([*KEY,value])
    for name in ['AC_EFFECT','FB~FUEL_BALANCE']:
        s=inp.create_sheet(name);s.append(['2028']);s.append([0])
    a=tmp_path/'entrada.xlsx';inp.save(a)
    out=Workbook();out.active.title='SHEETS';out.active.append(['Sheet','Unit'])
    total=1e-5+(cold if cold is not None else 0)
    for sheet,indicator,value in [('EC_HOT','Hot',1e-5),('EC_COLD','Cold',cold),('EC_TOTAL','Total',total)]:
        out['SHEETS'].append([sheet,'[TJ]']);s=out.create_sheet(sheet)
        s.append(['Category','Fuel','Segment','Euro Standard','Emission','Pollutant\n[TJ]','2028_T'])
        s.append([*KEY,indicator,'EC',value])
    b=tmp_path/'resultado.xlsx';out.save(b);return a,b


def test_exportacion_distingue_hot_frio_y_total_sin_suma_duplicada(tmp_path):
    a,b=libros(tmp_path);z=auditar_alcance_energia(b,a)['energia'].iloc[0]
    assert z.hot_mj_consulta==10 and z.cold_mj_consulta==2 and z.total_mj_consulta==pytest.approx(12)
    assert z.total_conciliado_con_hot_y_cold and z.fraccion_cold_sobre_hot_consulta==pytest.approx(.2)
    assert pd.isna(z.aporte_cold_anual_al_estudio_mj)


def test_frio_ausente_no_se_rellena_con_cero_aunque_total_iguale_hot(tmp_path):
    a,b=libros(tmp_path,cold=None);z=auditar_alcance_energia(b,a)['energia'].iloc[0]
    assert not z.cold_informado and pd.isna(z.cold_mj_consulta)
    assert z.total_menos_hot_mj_consulta==0 and pd.isna(z.total_conciliado_con_hot_y_cold)


def test_cero_nativo_informado_se_distingue_del_vacio(tmp_path):
    a,b=libros(tmp_path,cold=0.);z=auditar_alcance_energia(b,a)['energia'].iloc[0]
    assert z.cold_informado and z.cold_mj_consulta==0


@pytest.mark.parametrize('fallo',['unidad','categoria','negativo','total_menor','balance'])
def test_alcance_no_acepta_exportaciones_incoherentes(tmp_path,fallo):
    a,b=libros(tmp_path)
    if fallo=='balance':
        w=load_workbook(a);w['FB~FUEL_BALANCE']['A2']=2;w.save(a)
    else:
        w=load_workbook(b)
        if fallo=='unidad':w['SHEETS']['B2']='[kg]'
        if fallo=='categoria':w['EC_TOTAL']['B2']='Diesel'
        if fallo=='negativo':w['EC_COLD']['G2']=-1
        if fallo=='total_menor':w['EC_TOTAL']['G2']=1e-8
        w.save(b)
    with pytest.raises(ValueError):auditar_alcance_energia(b,a)
