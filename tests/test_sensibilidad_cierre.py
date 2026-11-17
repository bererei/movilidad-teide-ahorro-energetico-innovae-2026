"""La sensibilidad conserva la comparación de ambos escenarios, sin doble conteo."""
import pytest
from movilidad_teide.informe.cierre import balance_perturbado


def test_variacion_comun_no_crea_ahorro_de_un_servicio_que_permanece():
    base=balance_perturbado(120,70,30,15,15)
    otro=balance_perturbado(120,70,30,15,15,dt=.5)
    assert otro[0]-base[0]==otro[1]-base[1]==7.5
    assert otro[2]==base[2]==20


def test_coches_perturbados_en_ambas_ramas_y_no_solo_en_el_consumo_evitado():
    sin,con,ahorro=balance_perturbado(120,70,30,15,15,ds=.1,dc=.1)
    assert sin==147 and con==122 and ahorro==25


def test_inclinacion_adversa_reduce_ahorro_por_suma_de_las_tres_exposiciones():
    base=balance_perturbado(120,70,30,15,15)[2]
    stressed=balance_perturbado(120,70,30,15,15,ds=-.01,dc=.01,db=.01)[2]
    assert base-stressed==pytest.approx(.01*(120+70+30),abs=1e-12)


@pytest.mark.parametrize('bad',[-1,float('nan'),float('inf')])
def test_rechaza_variaciones_incompatibles_con_consumos_fisicos(bad):
    with pytest.raises(ValueError):balance_perturbado(120,70,30,15,15,db=bad)
