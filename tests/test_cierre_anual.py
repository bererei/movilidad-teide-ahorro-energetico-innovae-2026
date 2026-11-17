"""Compruebo el calendario, la política global y los límites del cierre diario."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from movilidad_teide.demanda.calendario_anual import (
    CAMPOS, HipotesisModalNoAplicable, aplicar_cupo_global,
    construir_perfiles_anuales, crear_calendario,
)
from movilidad_teide.demanda.escenarios_2028 import calendario
from movilidad_teide.demanda.perfiles_operacion_2028 import COLECTIVOS
from movilidad_teide.flujos.cierre_anual import generar_cierre_anual
from movilidad_teide.operacion.jornada_anual import ComprobadorAnual


def muestra():
    filas = []
    for mes, nombre in [(3, 'Marzo'), (7, 'Julio'), (10, 'Octubre')]:
        for j, tipo in enumerate(['Laborable', 'Sábado', 'Domingo']):
            # Distintos pesos por mes, colectivo y hora, no una serie plana.
            for k, colectivo in enumerate(COLECTIVOS):
                for hora in [7, 10, 19]:
                    coche = 10. * (mes + j + k + hora)
                    titsa = mes / 10.
                    excursion = 2. * (mes + hora)
                    filas.append(dict(matrix_index=mes * 10 + j, anio_fuente=2025,
                        mes_publicado=nombre, tipo_dia_publicado=tipo,
                        access_corridor='A', colectivo=colectivo, hora_servicio=hora,
                        visitas_persona_dia=coche + titsa + excursion,
                        visitas_coche=coche, visitas_titsa=titsa,
                        visitas_excursiones_resto_colectivo=excursion))
    return pd.DataFrame(filas)


@pytest.mark.parametrize('metodo', ['Estacional', 'Media anual'])
def test_calendario_conserva_cada_aporte_anual_y_titsa(metodo):
    original = muestra()
    cal, h = construir_perfiles_anuales(original, metodo=metodo)
    assert len(cal) == cal.fecha.nunique() == 366
    assert cal.tipo_dia_publicado.value_counts().to_dict() == calendario(2028)
    assert h.groupby(['mes_modelo', 'tipo_dia_publicado']).ngroups == 36
    keys = ['access_corridor', 'colectivo', 'hora_servicio', 'tipo_dia_publicado']
    antes = original.copy()
    antes[CAMPOS] = antes[CAMPOS].multiply(antes.tipo_dia_publicado.map(calendario(2028)) / 3, axis=0)
    despues = h.copy()
    despues[CAMPOS] = despues[CAMPOS].multiply(despues.dias_calendario, axis=0)
    np.testing.assert_allclose(antes.groupby(keys)[CAMPOS].sum().sort_index(),
                               despues.groupby(keys)[CAMPOS].sum().sort_index(), rtol=0, atol=1e-8)
    if metodo == 'Estacional':
        assert set(h[h.mes_modelo.eq(1)].mes_publicado) == {'Marzo'}
        assert set(h[h.mes_modelo.eq(12)].mes_publicado) == {'Octubre'}
        n = cal.query('mes_referencia == 3 and tipo_dia_publicado == "Laborable"').shape[0]
        assert h.query('mes_modelo == 1 and tipo_dia_publicado == "Laborable"').factor_calendario.eq(260 / (3 * n)).all()


def test_no_se_convierte_otra_muestra_en_nueve_observaciones():
    h = muestra()
    with pytest.raises(ValueError, match='nueve'):
        construir_perfiles_anuales(h[h.matrix_index.ne(30)])
    with pytest.raises(ValueError):
        crear_calendario(2027)


def entrada_modal(escala=1.):
    h, o = [], []
    for i, (corredor, cabecera) in enumerate([
        ('A', 'Chío'), ('B', 'La Esperanza'), ('C', 'Aguamansa'), ('D', 'Vilaflor')]):
        for k, colectivo in enumerate(COLECTIVOS):
            coche = escala * (4 - i) * 800.
            excursion = escala * (k + 1) * 100.
            h.append(dict(access_corridor=corredor, colectivo=colectivo,
                tipo_dia_publicado='Laborable', dias_calendario=23, hora_servicio=10,
                visitas_persona_dia=coche + excursion, visitas_coche=coche,
                visitas_titsa=0., visitas_excursiones_resto_colectivo=excursion))
            o.append(dict(origen_id=f'{corredor}{k}', colectivo=colectivo,
                corredor_fuente=corredor, corredor_calculo=corredor,
                cabecera_calculo=cabecera, peso_origen_condicionado=1., en_ambito_anual=True))
    # Los corredores tienen que ser los de la interfaz territorial existente.
    from movilidad_teide.opciones import PUNTOS
    inverso = {p: c for c, p in PUNTOS.items()}
    puntos = {'A': 'CHIO', 'B': 'LAGUNA', 'C': 'OROTAVA', 'D': 'VILAFLOR'}
    nombres = {a: inverso[p] for a, p in puntos.items()}
    h, o = pd.DataFrame(h), pd.DataFrame(o)
    for campo in ['access_corridor']:
        h[campo] = h[campo].map(nombres)
    for campo in ['corredor_fuente', 'corredor_calculo']:
        o[campo] = o[campo].map(nombres)
    v = dict(ocupacion_coche=3.2, hora_inicio_acceso=7, hora_fin_acceso=19,
             captacion_extranjero=.1, captacion_nacional=.2,
             captacion_local=.3, captacion_frecuente=.4)
    return h, o, v


@pytest.mark.parametrize('escala', [1., .05])
def test_cupo_unico_reparto_od_y_transferencia_bruta_conservada(escala):
    h, o, v = entrada_modal(escala)
    z, _ = aplicar_cupo_global(h, o, v)
    p, x = z['escenarios_por_punto_dia'], z['por_origen_dia']
    q = p.set_index('punto').reparto_coches_estimado_OD.sort_index()
    assert p.cupo_global_maximo_coches_dia.eq(600).all()
    assert not p.reparto_es_cuota_regulatoria.any()
    usado = int(p.cupo_global_utilizado_coches_dia.iloc[0])
    assert q.sum() == usado <= 600
    # Reconstruyo mayores restos y elegibilidad sin llamar al asignador.
    pesos = x.groupby('punto').coches_sin_dia.sum().sort_index()
    def reparto(n):
        bruto = n * pesos / pesos.sum()
        entero = np.floor(bruto).astype(int)
        orden = (bruto - entero).sort_values(ascending=False, kind='stable').index
        entero.loc[orden[:n - entero.sum()]] += 1
        return entero
    np.testing.assert_array_equal(q, reparto(usado))
    ratio = (.15 * x.visitas_excursiones_resto_colectivo / x.visitas_coche).groupby(x.punto).max()
    maximo = np.floor(pesos * (1 - ratio) + 1e-12)
    for n in range(usado + 1, min(600, int(np.floor(pesos.sum()))) + 1):
        assert (reparto(n) > maximo).any()
    if escala < 1:
        assert usado < 600
    np.testing.assert_allclose(x.visitas_excursiones_con_intervencion_dia,
                               1.15 * x.visitas_excursiones_resto_colectivo, atol=1e-8, rtol=0)
    np.testing.assert_allclose(p.visitas_sin_dia, p.visitas_con_objetivo_dia, atol=1e-8, rtol=0)
    assert x.visitas_excursiones_transferidas_dia.sum() > 0
    assert x.visitas_coche_a_excursiones_dia.sum() > 0
    np.testing.assert_allclose(x.visitas_coche_transferidas_dia + x.visitas_coche_a_excursiones_dia,
                               x.visitas_coche_transferidas_dia_referencia, atol=1e-8, rtol=0)


def test_hipotesis_no_aplicable_es_explicita_y_no_elimina_demanda():
    h, o, v = entrada_modal()
    h.loc[0, 'visitas_coche'] = 0.
    with pytest.raises(HipotesisModalNoAplicable):
        aplicar_cupo_global(h, o, v)
    assert h.loc[0, 'visitas_excursiones_resto_colectivo'] > 0


def test_deficit_de_intervalo_no_se_disfraza_de_busqueda_de_flota():
    z = ComprobadorAnual.__new__(ComprobadorAnual)
    objetivo = pd.DataFrame({'punto': ['CHIO'], 'demanda_lanzadera_dia': [47.]})
    limites = pd.DataFrame({'punto': ['CHIO'], 'capacidad_maxima_intervalo_personas': [46.]})
    cierre, test, logs, info = z.comprobar(objetivo, limites, fin_bases_min=1200)
    assert cierre is None and not logs
    assert test.deficit_intervalo_personas.item() == 1
    assert np.isnan(info['mejores_cadenas_ensayadas'])


@pytest.mark.parametrize('fin', [1200, 1290])
def test_el_cierre_materializado_recibe_el_fin_estacional(monkeypatch, fin):
    z = ComprobadorAnual.__new__(ComprobadorAnual)
    z.red, z.caps, z.ids = SimpleNamespace(puntos=['CHIO']), {}, {}
    z.testigos = {}
    reloj = SimpleNamespace(v={})
    estado = {'curvas': [((27, 0, 'Control', 0.), [], [])], 'refinado': True}
    z.bus = SimpleNamespace(_estado=lambda *args: ('clave', reloj, estado, False))
    llamadas = []
    def cerrar(*args, **kw):
        llamadas.append(kw)
        return {'programadas': 27}
    monkeypatch.setattr('movilidad_teide.operacion.jornada_anual.cerrar_reloj_con_bases', cerrar)
    z.v = {}
    objetivo = pd.DataFrame({'punto': ['CHIO'], 'demanda_lanzadera_dia': [46.]})
    limites = pd.DataFrame({'punto': ['CHIO'], 'capacidad_maxima_intervalo_personas': [46.],
                            'limite_llegada_cabecera_min': [1088.]})
    cierre, _, _, _ = z.comprobar(objetivo, limites, fin_bases_min=fin)
    assert cierre['programadas'] == 27 and llamadas == [{'inicio': 420, 'fin': fin}]


@pytest.mark.parametrize('demanda,llegada,fin,hereda', [
    (46., 1015., 1200, True),
    (46., 999., 1200, False),
    (46., 1015., 1099, False),
    (47., 1015., 1200, False),
])
def test_reutiliza_solo_un_testigo_con_los_mismos_viajeros_y_ventanas_validas(
        monkeypatch, demanda, llegada, fin, hereda):
    z = ComprobadorAnual.__new__(ComprobadorAnual)
    previo = {'programadas': 27,
              'movimientos': pd.DataFrame({'llegada_min': [1100.]}),
              'viajes': pd.DataFrame({'destino': ['cabecera:CHIO'], 'llegada_min': [1000.]})}
    z.testigos = {(('CHIO', 46.),): [previo]}
    z.red, z.caps, z.ids, z.v = SimpleNamespace(puntos=['CHIO']), {}, {}, {}
    reloj = SimpleNamespace(v={})
    estado = {'curvas': [((28, 0, 'Control', 0.), [], [])], 'refinado': True}
    z.bus = SimpleNamespace(_estado=lambda *args: ('clave', reloj, estado, False))
    monkeypatch.setattr('movilidad_teide.operacion.jornada_anual.cerrar_reloj_con_bases', lambda *a, **kw: None)
    objetivo = pd.DataFrame({'punto': ['CHIO'], 'demanda_lanzadera_dia': [demanda]})
    limites = pd.DataFrame({'punto': ['CHIO'], 'capacidad_maxima_intervalo_personas': [100.],
                            'limite_llegada_cabecera_min': [llegada]})
    cierre, _, _, _ = z.comprobar(objetivo, limites, fin_bases_min=fin)
    assert (cierre is previo) == hereda


def test_no_sobrescribe_una_captura_o_una_fuente(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    with pytest.raises(ValueError):
        generar_cierre_anual(repo, repo / 'config')
    destino = tmp_path / 'captura'
    destino.mkdir()
    (destino / 'original').write_text('conservar')
    with pytest.raises(FileExistsError):
        generar_cierre_anual(repo, destino)
    assert (destino / 'original').read_text() == 'conservar'
