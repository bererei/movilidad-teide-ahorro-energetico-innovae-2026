"""Contratos que impiden confundir coeficientes, actividad histórica y biblioteca."""
from pathlib import Path
import json
import os
import subprocess
import sys
import pandas as pd
import pytest
from movilidad_teide.energia.pendiente import coeficiente_por_recorrido
from movilidad_teide.publicacion.bibliotecas import comparar_biblioteca
from movilidad_teide.publicacion.dependencias import cargar_especificacion
from movilidad_teide.trazabilidad import sha256_archivo


def test_comprobar_copert_no_importa_los_balances_historicos():
    code="import sys;import movilidad_teide.flujos.copert_publico;assert not any(n in sys.modules for n in ['movilidad_teide.flujos.estudio','movilidad_teide.flujos.pendiente'])"
    subprocess.run([sys.executable,'-B','-c',code],check=True,env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')})


@pytest.mark.parametrize('rama,sentido,ocupacion,esperado',[
    ('antes','hacia_teide',3.2,15.),('autorizados','hacia_teide',3.2,15.),
    ('antes','desde_teide',3.2,10.),('transferidos','hacia_teide',3.2,3.),
    ('alimentacion_otros','hacia_teide',1.,2.),
])
def test_el_interior_se_cuenta_una_vez_y_la_alimentacion_no_lo_incluye(rama,sentido,ocupacion,esperado):
    from movilidad_teide.opciones import PARTICULAR
    route=pd.Series({'comparacion_calculo_id':'ruta','itinerario_alimentador_id':'cabecera','itinerario_referencia_id':'parque','terminal_calculo':'terminal'})
    rows=[]
    for comparison,it,role,occ,value in [('ruta','parque','directa',3.2,10.),('ruta','cabecera','alimentador',3.2,3.),('ruta','cabecera','alimentador',1.,2.),('visita_proxima_terminal','visita_proxima_terminal','interior',3.2,5.)]:
        rows.append(dict(comparacion_id=comparison,itinerary_id=it,rol=role,grupo_servicio=PARTICULAR,ocupacion_coche=occ,energia_base_mj_recorrido=value,energia_base_convencional_mj=value,correccion_convencional_mj=0.,energia_base_otras_tecnologias_mj=0.))
    values=pd.DataFrame(rows).set_index(['comparacion_id','itinerary_id','rol','grupo_servicio','ocupacion_coche'])
    result,_=coeficiente_por_recorrido(route,values,alternativa='España no Tenerife: particular',colectivo='tenerife_resto',sentido=sentido,rama=rama,ocupacion=ocupacion)
    assert result[0]==esperado


def biblioteca():
    return pd.DataFrame([{'Category':'Buses','Fuel':'Diesel','Segment':'Coaches Standard <=18 t','Euro Standard':'Euro VI D/E','year':2028,'speed_kmh':34.,'rural_speed_kmh':34.,'slope_class_pct':0.,'load_fraction':.5,'hot_ec_mj_per_km':4.}])


@pytest.mark.parametrize('cambio',['factor','clave_ausente','duplicada','velocidad'])
def test_no_se_tolera_una_biblioteca_de_otro_alcance(cambio):
    previous=biblioteca();current=previous.copy()
    if cambio=='factor':current.loc[0,'hot_ec_mj_per_km']+=1e-8
    elif cambio=='clave_ausente':current.loc[0,'load_fraction']=0.
    elif cambio=='duplicada':current=pd.concat([current,current])
    else:current.loc[0,'speed_kmh']=100.
    with pytest.raises((ValueError,AssertionError)):
        comparar_biblioteca(previous,current,familia='autocar')


def test_una_categoria_ajena_se_identifica_como_fuera_de_alcance():
    active=biblioteca();other=active.copy();other.loc[0,'Segment']='Urban Buses Standard 15 - 18 t'
    check=comparar_biblioteca(pd.concat([active,other]),active,familia='autocar')
    assert check['filas_fuera_de_alcance']==1 and check['filas_en_alcance']==1


def test_la_especificacion_detecta_una_entrada_alterada(tmp_path):
    p=tmp_path/'data/silver/entrada.csv';p.parent.mkdir(parents=True);p.write_text('dato\n1\n')
    entry={'ruta':str(p.relative_to(tmp_path)),'bytes':p.stat().st_size,'sha256':sha256_archivo(p)}
    cfg=tmp_path/'config/dependencias_publicacion.json';cfg.parent.mkdir();cfg.write_text(json.dumps({'version':'1.0','referencia':{'visitas_sin_y_con':2500000},'entradas':[entry]}))
    p.write_text('dato\n2\n')
    with pytest.raises(ValueError,match='modificada'):cargar_especificacion(tmp_path)


def test_el_preparador_verifica_la_biblioteca_sin_leer_antecedentes(tmp_path):
    from movilidad_teide.publicacion.bibliotecas import verificar_bibliotecas_vigentes
    current=tmp_path/'data/silver/vigente.parquet';current.parent.mkdir(parents=True);biblioteca().to_parquet(current)
    cfg=tmp_path/'config/dependencias_publicacion.json';cfg.parent.mkdir()
    cfg.write_text(json.dumps({'bibliotecas':[{'archivo_antecedente':'no_distribuido.parquet','archivo_vigente':'data/silver/vigente.parquet','equivalencia_verificada':{'equivalente_por_clave':True,'tolerancia_mj_km':1e-12,'maxima_diferencia_mj_km':0.,'sha256_vigente':sha256_archivo(current)}}]}))
    assert verificar_bibliotecas_vigentes(tmp_path)[0]['antecedente_leido_durante_preparacion'] is False
    biblioteca().assign(hot_ec_mj_per_km=6.).to_parquet(current)
    with pytest.raises(ValueError,match='difiere'):verificar_bibliotecas_vigentes(tmp_path)
