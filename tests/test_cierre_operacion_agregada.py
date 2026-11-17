import numpy as np
import pandas as pd
import pytest

from movilidad_teide.cierre_operacion_agregada import (
    necesidades_comerciales, valorar_movimientos, valorar_suelo_accesos,
)


def inputs():
    goals = []; moves = []; pairs = []; factors = []
    for point in ['VILAFLOR', 'OROTAVA', 'LAGUNA', 'CHIO']:
        goals.append({'punto': point, 'demanda_lanzadera_condicionada_dia': 93.})
        pairs.append({'punto': point, 'id_subida': point+'_ida_0',
            'id_regreso': point+'_vuelta_0', 'plazas_vinculadas': 46})
        for sense in ['ida', 'vuelta']:
            for i in range(1 if sense == 'ida' else 2):
                moves.append({'id_salida': f'{point}_{sense}_{i}', 'punto': point,
                    'sentido': sense, 'componente': 'comercial' if i == 0 else 'comercial_refuerzo_regreso',
                    'km_por_recorrido': 10.})
            for ref, e in [('hibrida', 360.), ('autocar_diagnostico', 720.)]:
                for load in [0., .5]:
                    factors.append({'punto': point, 'sentido': sense, 'referencia_id': ref,
                        'carga_fisica': load, 'energia_mj_recorrido': e if load else e/2,
                        'longitud_km': 10.})
    moves.append({'id_salida': 'vacio', 'punto': 'VILAFLOR', 'sentido': 'ida',
        'componente': 'reposicion_por_horario', 'km_por_recorrido': 10.})
    return tuple(pd.DataFrame(x) for x in [goals, moves, pairs, factors])


def test_distingue_cadenas_completas_y_viajes_por_sentido_sin_duplicar_regresos():
    goals, moves, pairs, factors = inputs()
    result = necesidades_comerciales(goals, moves, pairs, capacidad=46)
    assert result.exceso_sobre_cadenas_personas_dia.eq(47).all()
    assert result.parejas_adicionales_por_volumen.eq(2).all()
    assert result.minimo_comerciales_adicionales_ida.eq(2).all()
    assert result.minimo_comerciales_adicionales_vuelta.eq(1).all()
    priced = valorar_suelo_accesos(result, factors, carga_comercial=.5, perdida_rendimiento=.1).set_index('referencia_id')
    assert priced.loc['hibrida', 'suelo_comerciales_adicionales_mwh_dia'] == pytest.approx(12*.1/.9)
    assert priced.loc['autocar_diagnostico', 'suelo_comerciales_adicionales_mwh_dia'] == pytest.approx(12*.2/.9)
    assert priced.otros_refuerzos_mwh_dia.isna().all()
    assert not priced.operacion_completa_demostrada.any()


def test_valoracion_incluye_vacios_y_contraste_una_sola_vez():
    _, moves, _, factors = inputs()
    result = valorar_movimientos(moves, factors, carga_comercial=.5, perdida_rendimiento=.1)
    for ref, e in [('hibrida', .1), ('autocar_diagnostico', .2)]:
        group = result.loc[result.referencia_id.eq(ref)]
        assert group.hot_mwh.sum() == pytest.approx(12*e+e/2)
        assert group.con_contraste_mwh.sum() == pytest.approx((12*e+e/2)/.9)
        assert group.km_recorrido.sum() == 130
        assert group.loc[group.id_salida.eq('vacio'), 'carga_fisica'].item() == 0


def test_cota_nula_no_imputa_otros_refuerzos_cero():
    goals, moves, pairs, factors = inputs()
    goals['demanda_lanzadera_condicionada_dia'] = 46.
    needs = necesidades_comerciales(goals, moves, pairs, capacidad=46)
    result = valorar_suelo_accesos(needs, factors, carga_comercial=.5, perdida_rendimiento=.1)
    assert result.suelo_comerciales_adicionales_mwh_dia.eq(0).all()
    assert result.otros_refuerzos_mwh_dia.isna().all()
    assert not result.operacion_completa_demostrada.any()


@pytest.mark.parametrize('capacity', [0, 46.5, True, np.nan])
def test_rechaza_capacidad_invalida(capacity):
    goals, moves, pairs, _ = inputs()
    with pytest.raises(ValueError):
        necesidades_comerciales(goals, moves, pairs, capacidad=capacity)


@pytest.mark.parametrize('mutation', ['factor_ausente', 'distancia', 'componente', 'id_duplicado', 'energia_negativa'])
def test_rechaza_valoracion_incompatible(mutation):
    _, moves, _, factors = inputs()
    if mutation == 'factor_ausente':
        factors = factors.loc[~(factors.punto.eq('CHIO') & factors.sentido.eq('ida') & factors.carga_fisica.eq(.5))]
    elif mutation == 'distancia':
        moves.loc[0, 'km_por_recorrido'] = 20
    elif mutation == 'componente':
        moves.loc[0, 'componente'] = 'desconocido'
    elif mutation == 'id_duplicado':
        moves = pd.concat([moves, moves.iloc[:1]], ignore_index=True)
    else:
        factors.loc[0, 'energia_mj_recorrido'] = -1
    with pytest.raises(ValueError):
        valorar_movimientos(moves, factors, carga_comercial=.5, perdida_rendimiento=.1)


def test_cadena_con_viaje_incompatible_no_se_cuenta_como_capacidad():
    goals, moves, pairs, _ = inputs()
    pairs.loc[0, 'id_regreso'] = 'OROTAVA_vuelta_0'
    with pytest.raises(ValueError):
        necesidades_comerciales(goals, moves, pairs, capacidad=46)


def test_demanda_exactamente_a_capacidad_no_crea_otra_expedicion():
    goals, moves, pairs, _ = inputs()
    goals['demanda_lanzadera_condicionada_dia'] = 92.
    result = necesidades_comerciales(goals, moves, pairs, capacidad=46)
    assert result.parejas_necesarias_por_volumen.eq(2).all()
    assert result.minimo_comerciales_adicionales_vuelta.eq(0).all()
