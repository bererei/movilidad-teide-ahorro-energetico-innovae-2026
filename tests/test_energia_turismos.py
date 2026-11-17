"""Controles físicos y de transferencia; los ejemplos no son datos del estudio."""
import numpy as np
import pandas as pd
import pytest
from movilidad_teide.energia_turismos import (
    trabajo_gravitatorio_por_tonelada,diagnosticar_ece_upm,ensayar_balance_incremental_no_regenerativo,
)


def segments():
    return pd.DataFrame({'segment_id':['a','b'],'length_m':[1000.,1000.],
        'slope_pct':[10.,-10.],'elevation_start_m':[0.,100.],'elevation_end_m':[100.,0.]},index=[9,3])


def inputs():
    s=segments();b=pd.DataFrame({'segment_id':['a','b'],'factor_base_hot_ec_mj_km':[2.,2.]})
    p=pd.DataFrame({'segment_id':['b','a'],'masa_total_kg':[1000.,1000.],
        'eficiencia_incremental':[.25,.25],'consumo_minimo_mj_km':[0.,0.],
        'fuente_masa':['Ejemplo unitario']*2,'fuente_eficiencia':['Ejemplo unitario']*2,
        'fuente_minimo':['Ejemplo unitario']*2})
    return s,b,p


def test_gravity_is_signed_mechanical_energy_per_tonne_and_keeps_originals():
    s=segments();old=s.copy();r=trabajo_gravitatorio_por_tonelada(s)
    assert r.trabajo_gravitatorio_mj_por_t.tolist()==pytest.approx([.981,-.981])
    assert r.trabajo_gravitatorio_mj_por_t.sum()==pytest.approx(0)
    assert r.trabajo_ascenso_mj_por_t.sum()==pytest.approx(.981)
    assert r.energia_liberada_descenso_mj_por_t.sum()==pytest.approx(.981)
    pd.testing.assert_frame_equal(s,old);pd.testing.assert_frame_equal(r[s.columns],old)


def test_round_trip_zero_net_height_does_not_force_zero_fuel_effect():
    s,b,p=inputs();r=ensayar_balance_incremental_no_regenerativo(s,b,p,combustible='Diesel')
    assert r.energia_combustible_mj_propuesta.tolist()==pytest.approx([5.924,0])
    assert r.disipacion_mecanica_mj_propuesta.tolist()==pytest.approx([0,.481])
    assert r.energia_combustible_mj_propuesta.sum()>r.energia_base_mj_propuesta.sum()
    assert np.allclose(r.residuo_balance_mj_propuesta,0,rtol=0,atol=1e-12)
    assert r.index.tolist()==[9,3] and r.masa_total_kg.eq(1000).all()


def test_zero_grade_reproduces_baseline_with_an_explicit_fuel_floor():
    s,b,p=inputs();s['elevation_start_m']=0.;s['elevation_end_m']=0.;s['slope_pct']=0.;p['consumo_minimo_mj_km']=.2
    r=ensayar_balance_incremental_no_regenerativo(s,b,p,combustible='Petrol')
    assert r.energia_combustible_mj_propuesta.tolist()==pytest.approx([2,2])


@pytest.mark.parametrize('field,value',[
    ('masa_total_kg',0),('masa_total_kg',None),('eficiencia_incremental',0),
    ('eficiencia_incremental',1.1),('eficiencia_incremental',None),
    ('consumo_minimo_mj_km',-1),('consumo_minimo_mj_km',3),('fuente_eficiencia','')])
def test_balance_has_no_implicit_vehicle_or_efficiency_defaults(field,value):
    s,b,p=inputs();p.loc[0,field]=value
    with pytest.raises(ValueError):ensayar_balance_incremental_no_regenerativo(s,b,p,combustible='Diesel')


@pytest.mark.parametrize('fuel',['Petrol Hybrid','Battery electric','Diesel PHEV'])
def test_nonregenerative_model_rejects_unsupported_powertrains(fuel):
    s,b,p=inputs()
    with pytest.raises(ValueError,match='regeneración'):ensayar_balance_incremental_no_regenerativo(s,b,p,combustible=fuel)


def test_balance_requires_exact_segment_ids_and_sources():
    s,b,p=inputs();p.loc[0,'segment_id']='ausente'
    with pytest.raises(ValueError):ensayar_balance_incremental_no_regenerativo(s,b,p,combustible='Diesel')


@pytest.mark.parametrize('problem',['slope','length','height','duplicate'])
def test_physical_diagnostics_reject_incoherent_or_missing_profiles(problem):
    s=segments()
    if problem=='slope':s.loc[9,'slope_pct']=1
    if problem=='length':s.loc[9,'length_m']=0
    if problem=='height':s.loc[9,'elevation_end_m']=np.nan
    if problem=='duplicate':s.loc[3,'segment_id']='a'
    with pytest.raises(ValueError):trabajo_gravitatorio_por_tonelada(s)


def test_ece_preserves_negative_diagnostics_and_fractional_grade_units():
    s=segments();r=diagnosticar_ece_upm(s,1.91953,42.695)
    base_g=1.91953*1000/42.695
    assert r.ece_bruta_g_km_diagnostico.to_numpy()==pytest.approx(-.859161+866.936*np.array([.1,-.1])+1.02279*base_g)
    assert r.ece_resultado_negativo.tolist()==[False,True]
    assert not r.ece_adoptada.any() and r.ece_bruta_mj_km_diagnostico.iloc[1]<0
    assert r.ece_desvio_plano_mj_km_diagnostico.iloc[0]!=0


def test_ece_rejects_transfer_to_gasoline_or_hybrid():
    with pytest.raises(ValueError):diagnosticar_ece_upm(segments(),2,43.774,combustible='Petrol')


def _elecciones_masa(**cambios):
    valores={'criterio_tara_turismos':None,'masa_persona_turismo_kg':None,
             'ocupacion_coche':None,'equipaje_turismo_kg_coche':None}
    valores.update(cambios)
    return {'parametros':[{'id':k,'valor_utilizado':v,'propuesta':{'valor':75 if k=='masa_persona_turismo_kg' else None}}
                          for k,v in valores.items()]}


def test_masa_pendiente_conserva_ausencias_y_referencia_separada():
    from movilidad_teide.energia_turismos import completar_masas_turismos
    ref=pd.DataFrame({'tara_p25_kg':[1000],'tara_mediana_kg':[1100],'tara_p75_kg':[1200]})
    out=completar_masas_turismos(ref,_elecciones_masa())
    assert out.masa_total_elegida_kg.isna().all()
    assert out.masa_referencia_p50_una_persona_propuesta_kg.iloc[0]==1175
    assert 'ocupacion_coche' in out.pendientes_masa.iloc[0]
    assert out.tara_elegida_kg.isna().all()


@pytest.mark.parametrize('criterio,tara',[('Mediana (P50)',1100),('Cuartil inferior (P25)',1000),('Cuartil superior (P75)',1200)])
def test_masa_incluye_conductor_una_vez_y_equipaje_por_coche(criterio,tara):
    from movilidad_teide.energia_turismos import completar_masas_turismos
    ref=pd.DataFrame({'tara_p25_kg':[1000],'tara_mediana_kg':[1100],'tara_p75_kg':[1200]})
    # Fixture sintético: tres personas ya incluyen conductor y 10 kg son por coche.
    p=_elecciones_masa(criterio_tara_turismos=criterio,masa_persona_turismo_kg=75,ocupacion_coche=3,equipaje_turismo_kg_coche=10)
    out=completar_masas_turismos(ref,p)
    assert out.masa_total_elegida_kg.iloc[0]==tara+3*75+10
    p['parametros'][-1]['valor_utilizado']=None
    assert completar_masas_turismos(ref,p).masa_total_elegida_kg.isna().all()


@pytest.mark.parametrize('cambio',[{'ocupacion_coche':0},{'masa_persona_turismo_kg':0},{'equipaje_turismo_kg_coche':-1},{'criterio_tara_turismos':'promedio inventado'}])
def test_rechaza_elecciones_de_masa_imposibles(cambio):
    from movilidad_teide.energia_turismos import completar_masas_turismos
    ref=pd.DataFrame({'tara_p25_kg':[1000],'tara_mediana_kg':[1100],'tara_p75_kg':[1200]})
    with pytest.raises(ValueError):completar_masas_turismos(ref,_elecciones_masa(**cambio))


def test_masa_no_declara_resuelto_un_perfil_con_tara_ausente():
    from movilidad_teide.energia_turismos import completar_masas_turismos
    ref=pd.DataFrame({'tara_p25_kg':[1000.],'tara_mediana_kg':[float('nan')],'tara_p75_kg':[1200.]})
    with pytest.raises(ValueError,match='tara'):
        completar_masas_turismos(ref,_elecciones_masa(criterio_tara_turismos='Mediana (P50)',masa_persona_turismo_kg=75,ocupacion_coche=3,equipaje_turismo_kg_coche=10))


def test_envolvente_coincide_con_formula_cerrada_y_preserva_originales():
    from movilidad_teide.energia_turismos import acotar_balance_sin_minimo_identificado
    s,b,p=inputs();p=p.drop(columns=['consumo_minimo_mj_km','fuente_minimo'])
    old=s.copy();out=acotar_balance_sin_minimo_identificado(s,b,p,combustible='Diesel')
    assert out.energia_limite_inferior_modelo_mj.tolist()==pytest.approx([5.924,0.])
    assert out.energia_limite_superior_modelo_mj.tolist()==pytest.approx([5.924,2.])
    assert not out.consumo_montana_adoptado.any()
    assert out.limite_inferior_nulo.tolist()==[False,True]
    pd.testing.assert_frame_equal(old,s);pd.testing.assert_frame_equal(out[s.columns],s)


@pytest.mark.parametrize('fraccion_minimo',[0,.1,.5,.9,1])
def test_envolvente_contiene_cada_minimo_permitido_del_modelo(fraccion_minimo):
    from movilidad_teide.energia_turismos import acotar_balance_sin_minimo_identificado
    s,b,p=inputs();p['consumo_minimo_mj_km']=2*fraccion_minimo
    bounds=acotar_balance_sin_minimo_identificado(s,b,p.drop(columns=['consumo_minimo_mj_km','fuente_minimo']),combustible='Petrol')
    trial=ensayar_balance_incremental_no_regenerativo(s,b,p,combustible='Petrol')
    assert (trial.energia_combustible_mj_propuesta>=bounds.energia_limite_inferior_modelo_mj-1e-12).all()
    assert (trial.energia_combustible_mj_propuesta<=bounds.energia_limite_superior_modelo_mj+1e-12).all()


def test_envolvente_en_plano_colapsa_a_la_base_sin_elegir_minimo():
    from movilidad_teide.energia_turismos import acotar_balance_sin_minimo_identificado
    s,b,p=inputs();s['slope_pct']=0.;s['elevation_start_m']=s['elevation_end_m']=0.
    out=acotar_balance_sin_minimo_identificado(s,b,p.drop(columns=['consumo_minimo_mj_km','fuente_minimo']),combustible='Diesel')
    assert out.energia_limite_inferior_modelo_mj.tolist()==pytest.approx([2,2])
    assert out.energia_limite_superior_modelo_mj.tolist()==pytest.approx([2,2])


def test_envolvente_no_acepta_un_minimo_silencioso():
    from movilidad_teide.energia_turismos import acotar_balance_sin_minimo_identificado
    s,b,p=inputs()
    with pytest.raises(ValueError,match='no adopta un mínimo'):
        acotar_balance_sin_minimo_identificado(s,b,p,combustible='Diesel')


@pytest.mark.parametrize('problem',['masa','fuente','hibrido','identificadores'])
def test_envolvente_conserva_rechazos_de_parametros_y_tecnologias(problem):
    from movilidad_teide.energia_turismos import acotar_balance_sin_minimo_identificado
    s,b,p=inputs();p=p.drop(columns=['consumo_minimo_mj_km','fuente_minimo']);fuel='Diesel'
    if problem=='masa':p.loc[0,'masa_total_kg']=np.nan
    elif problem=='fuente':p.loc[0,'fuente_eficiencia']=''
    elif problem=='hibrido':fuel='Petrol Hybrid'
    elif problem=='identificadores':p.loc[0,'segment_id']='desconocido'
    with pytest.raises(ValueError):acotar_balance_sin_minimo_identificado(s,b,p,combustible=fuel)
