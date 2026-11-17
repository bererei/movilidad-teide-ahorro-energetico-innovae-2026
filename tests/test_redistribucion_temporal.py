"""Compruebo la conservación ponderada y evito cambios de fecha duplicados."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from movilidad_teide.demanda.redistribucion_temporal import redistribuir_fechas, FLUJOS
from movilidad_teide.flujos.redistribucion_2028 import generar_redistribucion_2028


@pytest.fixture
def referencia():
    perfiles=pd.DataFrame({"observacion":[1,2,3],"mes":["Julio"]*3,"tipo":["Laborable","Sábado","Domingo"],"dias_equivalentes":[10.,2.,3.]})
    zs={}
    for obs in [1,2,3]:
        x=pd.DataFrame({"origen_id":["a","b"],"colectivo":["local","extranjero"],"punto":["P","P"],
            "visitas_coche_transferidas_dia":[60.*obs,40.*obs],"visitas_excursiones_transferidas_dia":[6.*obs,4.*obs]})
        lan=x[list(FLUJOS)].sum().sum()+5
        p=pd.DataFrame({"punto":["P"],"visitas_titsa":[5.],"coches_autorizados_dia":[10.],
            "visitas_coche_autorizadas_dia":[32.],"visitas_excursiones_con_intervencion_dia":[35.],"visitas_sin_dia":[32+35+lan]})
        zs[obs]={"por_origen_dia":x,"escenarios_por_punto_dia":p}
    return zs,perfiles


def aplicar(ref,q=.2):
    zs,p=ref
    return redistribuir_fechas(zs,p,{"Julio":q},ocupacion=3.2)


def test_traslado_ponderado_y_doble_conteo(referencia):
    zs,p=referencia;n,tr=aplicar(referencia)
    # 220*.2*2 + 330*.2*3 = 286 visitas cambian de fecha una vez.
    assert tr.visitas_persona_anio.sum()==pytest.approx(286.)
    assert n[1]["escenarios_por_punto_dia"].cambio_fecha_entrada_dia.item()==pytest.approx(28.6)
    assert n[2]["escenarios_por_punto_dia"].cambio_fecha_salida_dia.item()==pytest.approx(44.)
    assert n[3]["escenarios_por_punto_dia"].cambio_fecha_salida_dia.item()==pytest.approx(66.)
    for c in FLUJOS:
        before=sum(zs[o]["por_origen_dia"][c]*w for o,w in zip(p.observacion,p.dias_equivalentes))
        after=sum(n[o]["por_origen_dia"][c]*w for o,w in zip(p.observacion,p.dias_equivalentes))
        np.testing.assert_allclose(after,before,rtol=0,atol=1e-10)
    assert sum(n[o]["escenarios_por_punto_dia"].visitas_con_objetivo_dia.item()*w for o,w in zip(p.observacion,p.dias_equivalentes))==pytest.approx(
        sum(zs[o]["escenarios_por_punto_dia"].visitas_sin_dia.item()*w for o,w in zip(p.observacion,p.dias_equivalentes)))


def test_no_mutacion_y_modos_no_trasladados(referencia):
    original=deepcopy(referencia[0]);n,_=aplicar(referencia)
    for obs,z in referencia[0].items():
        for name,frame in z.items():pd.testing.assert_frame_equal(frame,original[obs][name])
        for c in ["visitas_titsa","visitas_coche_autorizadas_dia","visitas_excursiones_con_intervencion_dia","coches_autorizados_dia"]:
            pd.testing.assert_series_equal(n[obs]["escenarios_por_punto_dia"][c],z["escenarios_por_punto_dia"][c])


def test_cero_es_identidad(referencia):
    n,tr=aplicar(referencia,0.)
    assert tr.visitas_persona_anio.sum()==0
    for obs,z in referencia[0].items():
        pd.testing.assert_frame_equal(n[obs]["por_origen_dia"][z["por_origen_dia"].columns],z["por_origen_dia"])


@pytest.mark.parametrize("q",[-.01,1.01,float("nan"),float("inf"),True])
def test_rechaza_fraccion_invalida(referencia,q):
    with pytest.raises(ValueError,match="fracción"):aplicar(referencia,q)


def test_no_doble_aplicacion(referencia):
    n,_=aplicar(referencia)
    with pytest.raises(ValueError,match="ya está aplicada"):aplicar((n,referencia[1]))


def test_no_inventa_origenes_receptores(referencia):
    referencia[0][1]["por_origen_dia"].loc[0,"origen_id"]="otro"
    with pytest.raises(ValueError,match="ausentes"):aplicar(referencia)


def test_pesos_positivos_y_tipos_completos(referencia):
    referencia[1].loc[0,"dias_equivalentes"]=0
    with pytest.raises(ValueError,match="Días"):aplicar(referencia)
    referencia[1].loc[0,"dias_equivalentes"]=10
    referencia[1].loc[0,"tipo"]="festivo"
    with pytest.raises(ValueError,match="laborable"):aplicar(referencia)


def test_rechaza_demanda_negativa(referencia):
    referencia[0][2]["por_origen_dia"].loc[0,FLUJOS[0]]=-1
    with pytest.raises(ValueError,match="elegibles"):aplicar(referencia)


def test_sin_sobrescribir_capturas(tmp_path):
    root=tmp_path/"repo";root.mkdir()
    with pytest.raises(ValueError,match="fuentes"):generar_redistribucion_2028(root,root/"config")
    dest=tmp_path/"anterior";dest.mkdir();(dest/"dato.csv").write_text("conservar")
    with pytest.raises(FileExistsError):generar_redistribucion_2028(root,dest)
    assert (dest/"dato.csv").read_text()=="conservar"
