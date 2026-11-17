"""Conservación de demanda y límites de lectura cartográfica y temporal."""
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from movilidad_teide.asignacion import (
    seleccionar_origenes_representativos, contexto_od_por_origen, cribar_conexiones_titsa,
    conciliar_aforos_anuales,
    SEGMENTOS, ErrorAsignacion, PENDIENTE, construir_asignacion,
    agrupar_origenes, resumir_discrepancia_repartos,
    clasificar_pasajeros_titsa, resumir_pasajeros_titsa, ubicar_paradas_titsa,
    contrastar_corredores, contrastar_totales, demanda_por_corredor,
    demanda_por_origen, reconstruir_cabeceras, resolver_puntos_cabecera,
)


def ejemplo_origen():
    # Datos sintéticos exclusivos de pruebas; no son entradas ni resultados del estudio.
    fila = {'zone_id': 10, 'centroid_id': 1}
    fila.update({f'{p}_{s}': i + 1 for p in ['gen', 'attr'] for i, s in enumerate(SEGMENTOS)})
    return pd.DataFrame([fila]), pd.DataFrame([{'zona_id': 10, 'municipio_principal': 'Referencia de prueba'}])


def ejemplo_perfiles():
    return pd.DataFrame([{'access_corridor': c, 'direccion': d, 'matrix_index': m, 'hora_servicio': 12,
                          **{s: 1.0 for s in SEGMENTOS}}
                         for c in ['a', 'b', 'c', 'd'] for d in ['subida', 'bajada'] for m in range(57)])


def test_origenes_conservan_colectivos_sentidos_y_pesos():
    c, r = ejemplo_origen()
    t = demanda_por_origen(c, r)
    assert len(t) == 8
    assert t.groupby('sentido').viajes_persona_media_57_matrices.sum().to_dict() == {'desde_teide': 10, 'hacia_teide': 10}
    assert np.allclose(t.groupby('sentido').peso_en_sentido.sum(), 1)
    assert t.peso_en_colectivo_sentido.eq(1).all()


@pytest.mark.parametrize('tipo', ['duplicado', 'negativo', 'ausente', 'sin_referencia', 'teide'])
def test_origenes_rechazan_datos_que_impiden_conservacion(tipo):
    c, r = ejemplo_origen()
    if tipo == 'duplicado': c = pd.concat([c, c], ignore_index=True)
    elif tipo == 'negativo': c.loc[0, 'gen_extranjero'] = -1
    elif tipo == 'ausente': c.loc[0, 'gen_extranjero'] = np.nan
    elif tipo == 'sin_referencia': r.loc[0, 'zona_id'] = 11
    elif tipo == 'teide': c.loc[0, 'zone_id'] = 187
    with pytest.raises(ErrorAsignacion): demanda_por_origen(c, r)


def test_media_de_matrices_no_es_suma_ni_demanda_anual():
    t = demanda_por_corredor(ejemplo_perfiles(), ['a', 'b', 'c', 'd'])
    assert len(t) == 32
    assert t.viajes_persona_media_57_matrices.eq(1).all()
    assert t.matrices.eq(57).all()
    assert not any('anual' in c for c in t.columns)


@pytest.mark.parametrize('tipo', ['matriz_ausente', 'duplicado', 'hora_fraccionaria', 'sentido', 'negativo'])
def test_perfiles_no_rellenan_cobertura_o_demanda_invalida(tipo):
    t = ejemplo_perfiles()
    if tipo == 'matriz_ausente': t = t.iloc[1:]
    elif tipo == 'duplicado': t = pd.concat([t, t.iloc[[0]]], ignore_index=True)
    elif tipo == 'hora_fraccionaria': t['hora_servicio'] = 12.5
    elif tipo == 'sentido': t.loc[0, 'direccion'] = 'otro'
    elif tipo == 'negativo': t.loc[0, 'extranjero'] = -1
    with pytest.raises(ErrorAsignacion): demanda_por_corredor(t, ['a', 'b', 'c', 'd'])


def test_totales_compatibles_toleran_solo_redondeo():
    t = demanda_por_origen(*ejemplo_origen())
    assert len(contrastar_totales(t, t)) == 8
    otro = t.copy(); otro.loc[0, 'viajes_persona_media_57_matrices'] += 1
    with pytest.raises(ErrorAsignacion): contrastar_totales(t, otro)


def ejemplo_mapa():
    z = gpd.GeoDataFrame({'zona_id': [10, 11], 'geometry': [box(0, 0, 2, 4), box(2, 0, 4, 4)]}, crs=4326)
    a = np.zeros((4, 4, 3), dtype=np.uint8)
    a[:, :2] = [40, 120, 181]; a[:, 2:] = [208, 122, 40]
    cfg = {'forma_imagen': [4, 4], 'leyenda_pixeles': [0, 0, 0, 0],
           'envolvente_pixeles': [0, 0, 3, 3], 'crs_georreferencia': 'EPSG:4326', 'pureza_minima': .9,
           'colores': [{'rgb': [40, 120, 181], 'corredor': 'norte'}, {'rgb': [208, 122, 40], 'corredor': 'oeste'}]}
    return a, z, cfg


def test_lectura_cartografica_identifica_colores_y_separa_calidad_de_demanda():
    a, z, cfg = ejemplo_mapa()
    t = reconstruir_cabeceras(a, z, cfg)
    assert t.corredor_candidato.to_list() == ['norte', 'oeste']
    assert t.fraccion_color_dominante.eq(1).all()
    assert t.estado_lectura.eq('reconstruccion_cartografica_provisional').all()
    assert not any('viajes' in c for c in t.columns)


def test_lectura_insuficiente_no_inventa_una_cabecera():
    a, z, cfg = ejemplo_mapa()
    a[::2, :, :] = [40, 120, 181]
    a[1::2, :, :] = [208, 122, 40]
    t = reconstruir_cabeceras(a, z, cfg)
    assert t.loc[t.zona_id.eq(10), 'corredor_candidato'].iloc[0] == PENDIENTE


def test_captura_distinta_exige_revisar_georreferencia():
    a, z, cfg = ejemplo_mapa()
    cfg['envolvente_pixeles'] = [0, 0, 2, 3]
    with pytest.raises(ErrorAsignacion, match='envolvente'):
        reconstruir_cabeceras(a, z, cfg)


def test_demanda_sin_cabecera_se_conserva_y_modos_futuros_quedan_ausentes():
    t = demanda_por_origen(*ejemplo_origen())
    l = pd.DataFrame([{'zona_id': 10, 'corredor_candidato': PENDIENTE}])
    a = construir_asignacion(t, l, [{'corredor': 'a', 'cabecera': 'Cabecera', 'terminal': 'Terminal'}])
    assert len(a) == len(t)
    assert a.viajes_persona_media_57_matrices.sum() == t.viajes_persona_media_57_matrices.sum()
    assert a.cabecera.isna().all()
    assert a[['modo_sin_actuacion', 'modo_hasta_cabecera_con_actuacion', 'fraccion_transferida', 'viajes_persona_anuales']].isna().all().all()


def test_diferencias_con_el_perfil_no_se_calibran_silenciosamente():
    a = pd.DataFrame([{'sentido': 'hacia_teide', 'colectivo': 'extranjero', 'corredor_candidato': 'norte', 'viajes_persona_media_57_matrices': 10}])
    b = pd.DataFrame([{'sentido': 'hacia_teide', 'colectivo': 'extranjero', 'corredor': 'norte', 'viajes_persona_media_57_matrices': 7}])
    t = contrastar_corredores(a, b)
    assert t.diferencia.iloc[0] == 3
    assert a.viajes_persona_media_57_matrices.iloc[0] == 10


def ejemplo_cabecera_fijada():
    _, zonas, mapa = ejemplo_mapa()
    corredores = [{'corredor': 'oeste', 'cabecera': 'Cabecera de prueba', 'origin_anchor_id': 'punto'}]
    catalogo = {'anchors': {'punto': {'type': 'coordinate', 'coordinates': [1.0, 3.0],
                                   'crs': 'EPSG:4326', 'validation_status': 'source_verified',
                                   'label': 'Punto de prueba'}}}
    return zonas.to_crs(3857), corredores, mapa, catalogo


def test_cabecera_fijada_conserva_lon_lat_y_crs_sin_ajustarse_al_mapa():
    z, c, m, catalogo = ejemplo_cabecera_fijada()
    puntos = resolver_puntos_cabecera(z, c, m, catalogo)
    p = puntos.to_crs(4326).geometry.iloc[0]
    assert p.x == pytest.approx(1.0) and p.y == pytest.approx(3.0)
    assert puntos.crs == z.crs
    assert puntos.tipo_ubicacion.iloc[0] == 'fijada_por_coordenadas'
    assert puntos.anchor_id.iloc[0] == 'punto'


def test_cabecera_fijada_rechaza_otro_punto_editable_en_pixeles():
    z, c, m, catalogo = ejemplo_cabecera_fijada()
    c[0]['pixel_referencia'] = [0, 0]
    with pytest.raises(ErrorAsignacion, match='duplicadas'):
        resolver_puntos_cabecera(z, c, m, catalogo)


def test_cabecera_con_anclaje_inexistente_no_inventa_ubicacion():
    z, c, m, catalogo = ejemplo_cabecera_fijada()
    catalogo['anchors'] = {}
    with pytest.raises(ErrorAsignacion, match='No existe'):
        resolver_puntos_cabecera(z, c, m, catalogo)


def test_cabeceras_sin_coordenadas_mantienen_su_estado_aproximado():
    _, z, m = ejemplo_mapa()
    c = [{'corredor': 'norte', 'cabecera': 'Referencia del mapa', 'pixel_referencia': [0, 0]}]
    puntos = resolver_puntos_cabecera(z, c, m, {'anchors': {}})
    assert puntos.tipo_ubicacion.iloc[0] == 'aproximada_desde_mapa'
    assert puntos.anchor_id.isna().all()
    assert puntos.geometry.iloc[0].equals(Point(0, 4))


def test_referencia_provisional_no_se_presenta_como_cabecera_fijada():
    z, c, m, catalogo = ejemplo_cabecera_fijada()
    ficha = catalogo['anchors']['punto']
    ficha.update({'location_status': 'provisional', 'selection_status': 'Referencia provisional junto a fuente existente'})
    puntos = resolver_puntos_cabecera(z, c, m, catalogo)
    assert puntos.tipo_ubicacion.iloc[0] == 'provisional_desde_fuente'
    assert puntos.estado.iloc[0] == ficha['selection_status']
    p = puntos.to_crs(4326).geometry.iloc[0]
    assert p.x == pytest.approx(1.0) and p.y == pytest.approx(3.0)

def tabla_para_agrupar():
    # Cobertura completa de prueba: incluye una zona sin corredor.
    filas = []
    for zona, corredor in [(10, 'norte'), (11, 'norte'), (12, PENDIENTE)]:
        for colectivo in SEGMENTOS:
            for sentido in ['hacia_teide', 'desde_teide']:
                filas.append({'zona_id': zona, 'colectivo': colectivo, 'sentido': sentido,
                    'viajes_persona_media_57_matrices': float(zona - 9),
                    'macrozona_id_principal': 1, 'macrozona_principal': 'Territorio de prueba',
                    'corredor_candidato': corredor, 'etiqueta_referencia': f'Zona de prueba {zona}'})
    return pd.DataFrame(filas)


def test_agrupacion_conserva_toda_demanda_y_zonas_sin_asignar():
    t = tabla_para_agrupar()
    detalle, grupos = agrupar_origenes(t)
    claves = ['colectivo', 'sentido']; v = 'viajes_persona_media_57_matrices'
    pd.testing.assert_series_equal(t.groupby(claves)[v].sum(), grupos.groupby(claves)[v].sum())
    assert detalle.zona_id.nunique() == 3
    assert grupos.numero_zonas.sum() == 3 * 8
    assert grupos.loc[grupos.corredor_candidato.eq(PENDIENTE), v].sum() == 24
    assert grupos.groupby('sentido').peso_en_sentido.sum().tolist() == pytest.approx([1, 1])
    assert 'grupo_origen_id' not in t  # No modificar la entrada recibida.


def test_referencia_del_grupo_es_la_misma_para_colectivos_y_sentidos():
    t = tabla_para_agrupar()
    # La zona 10 domina un colectivo, pero la 11 domina el conjunto.
    t.loc[(t.zona_id == 10) & (t.colectivo == 'extranjero'), 'viajes_persona_media_57_matrices'] = 3
    _, g = agrupar_origenes(t)
    norte = g.loc[g.corredor_candidato.eq('norte')]
    assert norte.zona_referencia_id.eq(11).all()
    assert norte.origen_referencia.eq('Zona de prueba 11').all()
    assert norte.zonas_id.eq('10, 11').all()


def test_referencia_territorial_ausente_no_pierde_demanda():
    t = tabla_para_agrupar()
    t.loc[t.zona_id.eq(12), ['macrozona_id_principal', 'macrozona_principal']] = None
    d, g = agrupar_origenes(t)
    assert d.zona_id.nunique() == 3
    assert g.loc[g.macrozona.eq('Territorio sin referencia'), 'viajes_persona_media_57_matrices'].sum() == 24


@pytest.mark.parametrize('fallo', ['duplicada', 'incompleta', 'negativa', 'territorio_cambia', 'corredor_cambia'])
def test_agrupacion_rechaza_perdidas_o_cambios_de_ambito(fallo):
    t = tabla_para_agrupar()
    if fallo == 'duplicada': t = pd.concat([t, t.iloc[[0]]], ignore_index=True)
    elif fallo == 'incompleta': t = t.iloc[1:]
    elif fallo == 'negativa': t.loc[0, 'viajes_persona_media_57_matrices'] = -1
    elif fallo == 'territorio_cambia': t.loc[0, 'macrozona_principal'] = 'Otra referencia'
    else: t.loc[0, 'corredor_candidato'] = 'otro'
    with pytest.raises(ErrorAsignacion): agrupar_origenes(t)


def repartos_de_prueba():
    a = tabla_para_agrupar()
    b = a.groupby(['sentido', 'colectivo', 'corredor_candidato'], as_index=False).viajes_persona_media_57_matrices.sum()
    # La mitad de la propuesta no tiene corredor; el perfil reparte todo al norte.
    b = b.groupby(['sentido', 'colectivo'], as_index=False).viajes_persona_media_57_matrices.sum()
    b['corredor'] = 'norte'
    return a, b


def test_discrepancia_cuantifica_diferencia_sin_modificar_repartos():
    a, b = repartos_de_prueba()
    copia = a.copy(deep=True)
    r = resumir_discrepancia_repartos(a, b)
    assert r.minima_fraccion_a_reasignar.tolist() == pytest.approx([.5, .5])
    assert r.fraccion_sin_asignar.tolist() == pytest.approx([.5, .5])
    pd.testing.assert_frame_equal(a, copia)


def test_repartos_iguales_tienen_discrepancia_nula():
    a, b = repartos_de_prueba()
    a.loc[:, 'corredor_candidato'] = 'norte'
    assert resumir_discrepancia_repartos(a, b).minima_fraccion_a_reasignar.eq(0).all()


def test_discrepancia_no_oculta_totales_incompatibles():
    a, b = repartos_de_prueba()
    b.loc[0, 'viajes_persona_media_57_matrices'] += 1
    with pytest.raises(ErrorAsignacion): resumir_discrepancia_repartos(a, b)

def datos_titsa_prueba():
    # Registros sintéticos exclusivos de pruebas: una misma persona podría transbordar.
    filas = [dict(anio=2025, mes=3, linea_id=348, viaje_hora=9,
        parada_entrada_id=1, parada_salida_id=2, pasajeros_cantidad=10,
        fechas_calculadas=21, linea_siguiente_id=341, linea_anterior_id=0,
        tipo_matriz='laborables', tipo_dia='Laborable', registro_fuente_id='a', archivo_fuente='prueba.json'),
        dict(anio=2025, mes=3, linea_id=341, viaje_hora=12,
        parada_entrada_id=2, parada_salida_id=3, pasajeros_cantidad=4,
        fechas_calculadas=21, linea_siguiente_id=0, linea_anterior_id=348,
        tipo_matriz='laborables', tipo_dia='Laborable', registro_fuente_id='b', archivo_fuente='prueba.json')]
    p = pd.DataFrame({'parada_id': [1,2,3,4], 'zona_OD_id': [5,187,187,np.nan]})
    return pd.DataFrame(filas), p


def test_pasajeros_titsa_se_suman_sin_multiplicar_por_dias_ni_deduplicar_personas():
    t, p = datos_titsa_prueba()
    c = clasificar_pasajeros_titsa(t, p, [2,3])
    r = resumir_pasajeros_titsa(c)
    assert r.pasajeros_publicados.sum() == 14
    assert r.loc[r.linea_id.eq(348), 'pasajeros_publicados'].sum() == 10
    assert c.tiene_transbordo.all()
    assert c.relacion_paradas_341.tolist() == ['hacia_ambito', 'interno_ambito']


def test_ambito_telefonico_no_se_equipara_a_paradas_del_servicio_interior():
    t, p = datos_titsa_prueba()
    p.loc[p.parada_id.eq(1), 'zona_OD_id'] = 187  # Referencia como Aguamansa en el ámbito OD.
    c = clasificar_pasajeros_titsa(t, p, [2,3])
    assert c.relacion_ambito_OD.iloc[0] == 'interno_ambito'
    assert c.relacion_paradas_341.iloc[0] == 'hacia_ambito'


def test_parada_o_zona_ausente_se_conserva_sin_inventar_un_exterior():
    t, p = datos_titsa_prueba()
    t.loc[0, 'parada_entrada_id'] = 999
    t.loc[1, 'parada_salida_id'] = 4
    c = clasificar_pasajeros_titsa(t, p, [2,3])
    assert c.relacion_ambito_OD.eq('sin_identificar').all()
    assert c.relacion_paradas_341.iloc[0] == 'sin_identificar'
    assert c.relacion_paradas_341.iloc[1] == 'desde_ambito'
    assert resumir_pasajeros_titsa(c).pasajeros_publicados.sum() == 14


@pytest.mark.parametrize('fallo', ['duplicado','negativo','fraccionario','dia_ausente','dias_excesivos','linea','hora','parada_duplicada'])
def test_demanda_titsa_rechaza_doble_conteo_y_entradas_invalidas(fallo):
    t, p = datos_titsa_prueba()
    if fallo == 'duplicado': t = pd.concat([t, t.iloc[[0]]], ignore_index=True)
    elif fallo == 'negativo': t.loc[0, 'pasajeros_cantidad'] = -1
    elif fallo == 'fraccionario': t['pasajeros_cantidad'] = t.pasajeros_cantidad.astype(float); t.loc[0,'pasajeros_cantidad'] = 1.5
    elif fallo == 'dia_ausente': t.loc[0, 'tipo_dia'] = None
    elif fallo == 'dias_excesivos': t.loc[0, 'fechas_calculadas'] = 32
    elif fallo == 'linea': t.loc[0, 'linea_id'] = 999
    elif fallo == 'hora': t.loc[0, 'viaje_hora'] = 24
    else: p = pd.concat([p, p.iloc[[0]]], ignore_index=True)
    with pytest.raises(ErrorAsignacion): clasificar_pasajeros_titsa(t, p, [2,3])

def test_parada_se_ubica_por_coordenadas_y_no_por_codigo_publicado():
    p = pd.DataFrame({'parada_id':[1,2], 'parada_longitud':[1.,3.], 'parada_latitud':[1.,1.], 'zona_telefonia_id':[187,187]})
    z = gpd.GeoDataFrame({'zona_id':[5,222], 'geometry':[box(0,0,2,2),box(2,0,4,2)]},crs=4326)
    r = ubicar_paradas_titsa(p,z)
    assert r.zona_OD_id.tolist() == [5,222]
    assert r.codigo_zona_publicado_difiere.all()
    assert r.zona_telefonia_id.tolist() == [187,187]
    assert 'zona_OD_id' not in p


def test_parada_sin_coordenadas_o_en_limite_ambiguo_no_se_fuerza():
    p = pd.DataFrame({'parada_id':[1,2], 'parada_longitud':[2.,np.nan], 'parada_latitud':[1.,np.nan], 'zona_telefonia_id':[187,187]})
    z = gpd.GeoDataFrame({'zona_id':[5,222], 'geometry':[box(0,0,2,2),box(2,0,4,2)]},crs=4326)
    assert ubicar_paradas_titsa(p,z).zona_OD_id.isna().all()


def aforos_para_conciliar():
    # Series sintéticas para comprobar conservación, nunca entradas del estudio.
    from calendar import monthrange
    filas = []
    for mes in range(1, 13):
        for punto in ['norte', 'sur']:
            for sentido, valor in [('entrada', 10.5), ('salida', 9.25)]:
                for tipo in ['coche', 'guagua']:
                    filas.append({'anio': 2025, 'mes': mes, 'punto': punto, 'sentido': sentido,
                        'tipo_vehiculo': tipo, 'total_valores_fuente': valor,
                        'horas_esperadas': monthrange(2025, mes)[1] * 24,
                        'horas_ausentes': 0, 'valores_ausentes': 0, 'valores_negativos': 0,
                        'marcas_fuera_calendario': 0, 'valores_decimales': 1})
    mensual = pd.DataFrame(filas)
    claves = ['anio', 'punto', 'sentido', 'tipo_vehiculo']
    anual = mensual.drop(columns='mes').groupby(claves, as_index=False).sum()
    return anual, mensual


def test_conciliacion_anual_conserva_fracciones_y_no_iguala_sentidos():
    a, m = aforos_para_conciliar()
    r = conciliar_aforos_anuales(a, m, 2025, ['norte', 'sur'])
    assert len(r) == 4
    assert r.entradas.eq(126).all() and r.salidas.eq(111).all()
    assert r.saldo_entrada_menos_salida.eq(15).all()
    assert r.valores_decimales_entrada.eq(12).all()
    assert r.peso_entradas_en_categoria.eq(.5).all()
    assert r.loc[r.tipo_vehiculo.eq('guagua'), 'desglose'].str.contains('sin desagregar').all()
    assert not any('personas' in c for c in r)


@pytest.mark.parametrize('incidencia', ['mes_ausente', 'mes_repetido', 'anual_repetido', 'total_distinto', 'hueco', 'calendario', 'negativo'])
def test_conciliacion_rechaza_cobertura_o_sumas_incompatibles(incidencia):
    a, m = aforos_para_conciliar()
    if incidencia == 'mes_ausente': m = m.iloc[1:]
    elif incidencia == 'mes_repetido': m = pd.concat([m, m.iloc[:1]])
    elif incidencia == 'anual_repetido': a = pd.concat([a, a.iloc[:1]])
    elif incidencia == 'total_distinto': a.loc[0, 'total_valores_fuente'] += 1
    elif incidencia == 'hueco': m.loc[0, 'horas_ausentes'] = 1
    elif incidencia == 'calendario': m.loc[0, 'horas_esperadas'] -= 1
    elif incidencia == 'negativo': m.loc[0, 'total_valores_fuente'] = -1
    with pytest.raises(ErrorAsignacion): conciliar_aforos_anuales(a, m, 2025, ['norte', 'sur'])

# Datos sintéticos exclusivos para verificar conservación y límites del nuevo flujo.
def ejemplo_representantes():
    t = tabla_para_agrupar()
    t['municipio_id_principal'] = t.zona_id.map({10:38001,11:38002,12:38003})
    t['municipio_principal'] = t.zona_id.map({10:'Municipio A',11:'Municipio B',12:'Municipio C'})
    centros = [(10,-16.02,28.0),(11,-16.0,28.0),(12,-15.98,28.0)]
    c = pd.DataFrame([{'zone_id':z,'centroid_id':z,'lon':x,'lat':y,
        **{f'{p}_{s}':float(z-9) for p in ['gen','attr'] for s in SEGMENTOS}} for z,x,y in centros])
    zonas = gpd.GeoDataFrame({'zona_id':[10,11,12], 'geometry':[box(x-.005,y-.005,x+.005,y+.005) for z,x,y in centros]},crs=4326).to_crs(32628)
    stops = gpd.GeoDataFrame({'stop_id':['s1','s2'],'stop_name':['Punto A','Punto B'],
        'geometry':[Point(-16.02,28),Point(-16,28)]},crs=4326)
    return t,c,zonas,stops


def test_representantes_separan_municipios_y_conservan_ambos_sentidos_y_colectivos():
    a,c,z,p = ejemplo_representantes()
    m,d,pts = seleccionar_origenes_representativos(a,c,z,p)
    assert len(m)==3 and m.zona_id.is_unique and len(d)==24
    pd.testing.assert_series_equal(a.groupby(['colectivo','sentido']).viajes_persona_media_57_matrices.sum(),
                                  d.groupby(['colectivo','sentido']).viajes_persona_media_57_matrices.sum())
    assert len(pts)==3 and pts.geometry.notna().sum()==2
    assert not pts.punto_adoptado_para_calculo.any()
    assert pts.distancia_coche_ida_km.isna().all()
    assert m.loc[m.zona_id.eq(12),'corredor_candidato'].iloc[0]==PENDIENTE


def test_representantes_sin_parada_no_inventan_punto_o_distancia():
    a,c,z,p = ejemplo_representantes();_,_,pts = seleccionar_origenes_representativos(a,c,z,p)
    sin=pts.loc[pts.zona_referencia_id.eq(12)].iloc[0]
    assert sin.geometry is None and pd.isna(sin.stop_id_referencia)
    assert pd.isna(sin.radio_90_demanda_cartografico_m) and pd.isna(sin.longitud)


def test_representantes_demanda_cero_no_elige_parada_por_existir():
    a,c,z,p=ejemplo_representantes();a.loc[a.zona_id.eq(10),'viajes_persona_media_57_matrices']=0
    for campo in c.filter(regex='gen_|attr_'):c.loc[c.zone_id.eq(10),campo]=0
    _,_,pts=seleccionar_origenes_representativos(a,c,z,p)
    cero=pts.loc[pts.zona_referencia_id.eq(10)].iloc[0]
    assert cero.geometry is None and pd.isna(cero.peso_zona_principal_ambos_sentidos)


@pytest.mark.parametrize('problema',['demanda','duplicado','crs','geometria'])
def test_representantes_rechazan_fuentes_incoherentes(problema):
    a,c,z,p=ejemplo_representantes()
    if problema=='demanda':c.loc[0,'gen_extranjero']+=1
    elif problema=='duplicado':c=pd.concat([c,c.iloc[[0]]],ignore_index=True)
    elif problema=='crs':z=z.to_crs(4326)
    elif problema=='geometria':z=z.iloc[:-1]
    with pytest.raises(ErrorAsignacion):seleccionar_origenes_representativos(a,c,z,p)


def test_contexto_od_no_usa_ratio_con_distintas_zonas_o_ausencia():
    m=pd.DataFrame({'zona_id':[10,11,12],'origen_id':['a','a','a']})
    od=pd.DataFrame([{'zona_id':10,'id_matriz':1,'sentido':'hacia_teide','modo':'privado','viajes':5.,'mes':3,'tipo_dia':'domingo'},
                     {'zona_id':11,'id_matriz':1,'sentido':'hacia_teide','modo':'todos_modos','viajes':7.,'mes':3,'tipo_dia':'domingo'}])
    r=contexto_od_por_origen(od,m).iloc[0]
    assert not r.mismas_zonas_en_ambos_modos and pd.isna(r.fraccion_privado_solo_si_mismas_zonas)
    assert r.numero_zonas_origen==3 and not r.cobertura_zonas_completa
    solo=contexto_od_por_origen(od.iloc[[0]],m).iloc[0]
    assert pd.isna(solo.viajes_todos_modos_publicados)


def test_contexto_od_identifica_cobertura_parcial_aunque_ratio_sea_compatible():
    m=pd.DataFrame({'zona_id':[10,11],'origen_id':['a','a']})
    od=pd.DataFrame([{'zona_id':10,'id_matriz':1,'sentido':'hacia_teide','modo':modo,'viajes':v,'mes':3,'tipo_dia':'domingo'}
                     for modo,v in [('privado',5.),('todos_modos',10.)]])
    r=contexto_od_por_origen(od,m).iloc[0]
    assert r.fraccion_privado_solo_si_mismas_zonas==.5 and not r.cobertura_zonas_completa
    od.loc[0,'viajes']=11
    with pytest.raises(ErrorAsignacion):contexto_od_por_origen(od,m)


def ejemplo_cribado():
    p=gpd.GeoDataFrame({'stop_id':['o1','o2','h1','h2'],'stop_name':['Origen ida','Origen regreso','Cabecera ida','Cabecera regreso'],
        'geometry':[Point(0,0),Point(0,1),Point(100,0),Point(100,1)]},crs=32628)
    o=gpd.GeoDataFrame({'origen_id':['a'],'corredor_candidato':['norte'],'stop_id_referencia':['o1'],'geometry':[Point(0,0)]},crs=32628)
    h=gpd.GeoDataFrame({'corredor':['norte'],'cabecera':['Cabecera de prueba'],'geometry':[Point(100,0)]},crs=32628)
    t=pd.DataFrame({'trip_id':['ida','regreso'],'service_id':['s1','s2'],'route_id':['r','r']})
    r=pd.DataFrame({'route_id':['r'],'route_short_name':['100']})
    cal=pd.DataFrame({'service_id':['s1','s2'],'date':['20261024','20261024'],'exception_type':['1','1']})
    st=pd.DataFrame([{'trip_id':trip,'stop_id':stop,'stop_sequence':seq,'arrival_time':hora,'departure_time':hora}
        for trip,stop,seq,hora in [('ida','o1',1,'09:00:00'),('ida','h1',2,'10:00:00'),
                                  ('regreso','h2',1,'16:00:00'),('regreso','o2',2,'17:00:00')]])
    return o,h,p,st,t,r,cal


def test_directos_conservan_paradas_distintas_de_regreso_y_no_validan_horario_util():
    refs,refs_o,s,d=cribar_conexiones_titsa(*ejemplo_cribado())
    assert len(refs)==2 and len(refs_o)==2 and len(d)==2 and len(s)==2
    assert s.lineas_directas.eq('100').all() and s.dias_con_directos_ambos_sentidos.eq(1).all()
    assert not s.regreso_util_validado.any()
    assert set(d.stop_id_uso_gtfs_origen)=={'o1','o2'}


def test_directos_exigen_mismo_trip_y_orden_no_solo_misma_linea():
    o,h,p,st,t,r,cal=ejemplo_cribado();st=st.loc[st.stop_id.isin(['o1','h2'])]
    _,_,s,d=cribar_conexiones_titsa(o,h,p,st,t,r,cal)
    assert d.empty and s.variantes_trip_directas.eq(0).all()
    o,h,p,st,t,r,cal=ejemplo_cribado();st['stop_sequence']=3-st.stop_sequence
    _,_,s,d=cribar_conexiones_titsa(o,h,p,st,t,r,cal)
    assert d.empty


def test_directos_calendarios_separados_no_prueban_regreso_mismo_dia():
    o,h,p,st,t,r,cal=ejemplo_cribado();cal.loc[1,'date']='20261025'
    _,_,s,d=cribar_conexiones_titsa(o,h,p,st,t,r,cal)
    assert len(d)==2 and s.dias_con_directos_ambos_sentidos.eq(0).all()


def test_directos_respetan_restricciones_y_horas_mayores_que_24():
    o,h,p,st,t,r,cal=ejemplo_cribado()
    st.loc[st.trip_id.eq('ida'),'arrival_time']=['25:00:00','26:00:00']
    st.loc[st.trip_id.eq('ida'),'departure_time']=['25:00:00','26:00:00']
    _,_,s,d=cribar_conexiones_titsa(o,h,p,st,t,r,cal);assert len(d)==2
    st['pickup_type']=0;st.loc[st.stop_id.eq('o1'),'pickup_type']=1
    _,_,s,d=cribar_conexiones_titsa(o,h,p,st,t,r,cal)
    assert d.sentido.eq('desde_cabecera').all() and len(d)==1


@pytest.mark.parametrize('problema',['calendario','secuencia','hora','restriccion'])
def test_cribado_exige_revisar_cambios_de_formato_o_datos_invalidos(problema):
    o,h,p,st,t,r,cal=ejemplo_cribado()
    if problema=='calendario':cal.loc[0,'exception_type']='2'
    elif problema=='secuencia':st['stop_sequence']=st.stop_sequence.astype(float);st.loc[0,'stop_sequence']=1.5
    elif problema=='hora':st.loc[0,'arrival_time']='09:99:00'
    else:st['pickup_type']=-1
    with pytest.raises(ErrorAsignacion):cribar_conexiones_titsa(o,h,p,st,t,r,cal)


def ejemplo_reduccion():
    from movilidad_teide.asignacion import agrupar_origenes_para_recorridos
    a,c,z,p=ejemplo_representantes()
    m,d,o=seleccionar_origenes_representativos(a,c,z,p)
    o['cabecera_candidata']=o.corredor_candidato.map({'norte':'Cabecera de prueba',PENDIENTE:'Sin asignar'})
    campos={'nombre':'Grupo de prueba','fundamento':'Familia territorial sintética','familia_vial_a_contrastar':'Por contrastar','prioridad_revision':'Revisión pendiente'}
    norte=o.loc[o.corredor_candidato.eq('norte'),'origen_id'].tolist()
    resto=o.loc[o.corredor_candidato.eq(PENDIENTE),'origen_id'].tolist()
    spec={'grupos':[{'grupo_reducido_id':'juntos','corredor_candidato':'norte','origenes_id':norte,**campos},
                    {'grupo_reducido_id':'resto','corredor_candidato':PENDIENTE,'origenes_id':resto,**campos}]}
    cotas=pd.DataFrame({'origen_id':o.origen_id,'cota_terreno_m':[10.,20.,np.nan]})
    return m,d,o,c,cotas,spec


def test_reduccion_conserva_zonas_colectivos_sentidos_y_resto():
    from movilidad_teide.asignacion import agrupar_origenes_para_recorridos
    m,d,o,c,h,s=ejemplo_reduccion()
    z,pesos,a,pts,diag,alt=agrupar_origenes_para_recorridos(m,d,o,c,h,s)
    assert len(z)==3 and z.zona_id.is_unique and len(pts)==2 and len(a)==16 and len(pesos)==24
    pd.testing.assert_series_equal(d.groupby(['colectivo','sentido']).viajes_persona_media_57_matrices.sum(),
                                  a.groupby(['colectivo','sentido']).viajes_persona_media_57_matrices.sum())
    assert a.loc[a.grupo_reducido_id.eq('resto'),'viajes_persona_media_57_matrices'].sum()==24
    assert np.allclose(pesos.groupby(['grupo_reducido_id','colectivo','sentido']).peso_origen_en_grupo_colectivo_sentido.sum(),1)
    assert np.allclose(a.groupby(['colectivo','sentido']).peso_en_colectivo_sentido.sum(),1)
    assert pts.loc[pts.grupo_reducido_id.eq('resto')].geometry.item() is None
    assert not pts.adoptado_para_balance.any() and pts.distancia_coche_ida_km.isna().all()
    assert a.modo_futuro.isna().all() and a.viajes_persona_anuales.isna().all()


def test_representante_reducido_es_punto_real_ponderado_y_estable():
    from movilidad_teide.asignacion import agrupar_origenes_para_recorridos
    m,d,o,c,h,s=ejemplo_reduccion();out=agrupar_origenes_para_recorridos(m,d,o,c,h,s)
    pts=out[3];elegida=pts.loc[pts.grupo_reducido_id.eq('juntos')].iloc[0]
    # El origen de mayor peso en este caso es una referencia existente, nunca un punto medio creado.
    assert elegida.punto_referencia=='Punto B'
    assert o.loc[o.origen_id.eq(elegida.origen_referencia_id)].geometry.item().equals(elegida.geometry)
    shuffled=agrupar_origenes_para_recorridos(m.sample(frac=1,random_state=1),d.sample(frac=1,random_state=2),o.iloc[::-1],c.iloc[::-1],h.iloc[::-1],s)
    assert pts.origen_referencia_id.tolist()==shuffled[3].origen_referencia_id.tolist()
    assert out[5].seleccionado.sum()==1 and out[4].shape[0]==3
    assert 'grupo_reducido_id' not in d and 'peso_seleccion' not in o


@pytest.mark.parametrize('fallo',['sin_miembro','repetido','desconocido','dos_cabeceras','colectivo_ausente','demanda_incoherente','centroides_incoherentes','zona_repetida','origen_repetido','cota_repetida','infinito','crs','fundamento'])
def test_reduccion_rechaza_perdidas_o_incoherencias(fallo):
    from movilidad_teide.asignacion import agrupar_origenes_para_recorridos
    m,d,o,c,h,s=ejemplo_reduccion()
    if fallo=='sin_miembro':s['grupos'][0]['origenes_id'].pop()
    elif fallo=='repetido':s['grupos'][0]['origenes_id']*=2
    elif fallo=='desconocido':s['grupos'][0]['origenes_id'][0]='inexistente'
    elif fallo=='dos_cabeceras':s['grupos'][0]['origenes_id']+=s['grupos'][1]['origenes_id'];s['grupos'].pop()
    elif fallo=='colectivo_ausente':d=d.iloc[1:]
    elif fallo=='demanda_incoherente':o.loc[0,'viajes_hacia_teide_media57']+=1
    elif fallo=='centroides_incoherentes':c.loc[0,'gen_extranjero']+=1
    elif fallo=='zona_repetida':m=pd.concat([m,m.iloc[[0]]])
    elif fallo=='origen_repetido':o=pd.concat([o,o.iloc[[0]]])
    elif fallo=='cota_repetida':h=pd.concat([h,h.iloc[[0]]])
    elif fallo=='infinito':h.loc[0,'cota_terreno_m']=np.inf
    elif fallo=='crs':o=o.to_crs(4326)
    elif fallo=='fundamento':s['grupos'][0]['fundamento']=''
    with pytest.raises(ErrorAsignacion):agrupar_origenes_para_recorridos(m,d,o,c,h,s)


def test_reduccion_conserva_peso_sin_localizacion_y_cota_ausente():
    from movilidad_teide.asignacion import agrupar_origenes_para_recorridos
    m,d,o,c,h,s=ejemplo_reduccion()
    # La pertenencia sigue definida aunque una referencia no tenga coordenada o cota.
    o.loc[0,'geometry']=None;h.loc[0,'cota_terreno_m']=np.nan
    pts=agrupar_origenes_para_recorridos(m,d,o,c,h,s)[3]
    grupo=pts.loc[pts.grupo_reducido_id.eq('juntos')].iloc[0]
    assert grupo.cobertura_demanda_con_punto == pytest.approx(2/3)
    assert grupo.cobertura_demanda_con_cota == pytest.approx(2/3)
    assert grupo.numero_subgrupos==2 and grupo.punto_referencia=='Punto B'


def test_reduccion_demanda_cero_no_crea_punto_ni_peso():
    from movilidad_teide.asignacion import agrupar_origenes_para_recorridos
    m,d,o,c,h,s=ejemplo_reduccion();oid=s['grupos'][0]['origenes_id']
    d.loc[d.origen_id.isin(oid),'viajes_persona_media_57_matrices']=0
    for col in ['viajes_hacia_teide_media57','viajes_desde_teide_media57']:o.loc[o.origen_id.isin(oid),col]=0
    for col in c.filter(regex='^(gen|attr)_'):c.loc[c.zone_id.isin([10,11]),col]=0
    z,pesos,a,pts,diag,alt=agrupar_origenes_para_recorridos(m,d,o,c,h,s)
    grupo=pts.loc[pts.grupo_reducido_id.eq('juntos')].iloc[0]
    assert grupo.geometry is None and pd.isna(grupo.cobertura_demanda_con_punto)
    assert pesos.loc[pesos.grupo_reducido_id.eq('juntos')].peso_origen_en_grupo_colectivo_sentido.isna().all()


def ejemplo_revision_trazados():
    """Geometrías sintéticas: un cruce cercano no demuestra una conexión viaria."""
    from shapely.geometry import LineString
    origenes=gpd.GeoDataFrame({'origen_id':['a','b','c','d'],
        'corredor_candidato':['norte','norte','norte',PENDIENTE]},
        geometry=[Point(0,0),Point(0,5),Point(10,0),None],crs=4083)
    miembros=pd.DataFrame({'origen_id':['a','b','c','d'],'grupo_reducido_id':['g1','g1','g2','g3']})
    filas=[]
    for caso,oid,x in [('r1','a',0),('r2','c',10)]:
        for s in ['hacia_teide','desde_teide']:
            coords=[(x,0),(x,10)]
            filas.append({'comparacion_id':caso,'itinerary_id':caso+'_'+s,'origen_referencia_id':oid,
                'corredor_candidato':'norte','sentido':s,'geometry':LineString(coords if s=='hacia_teide' else coords[::-1])})
    rutas=gpd.GeoDataFrame(filas,crs=4083)
    grupos=pd.DataFrame({'grupo_reducido_id':['g1','g2','g3'],'origen_referencia_id':['a','c',None],
        'numero_subgrupos':[2,1,1],'viajes_hacia_teide_media57':[160.,80.,160.]})
    demanda=pd.DataFrame([{'origen_id':oid,'colectivo':c,'sentido':s,
        'viajes_persona_media_57_matrices':v} for oid,v in zip('abcd',[10.,30.,20.,40.])
        for c in SEGMENTOS for s in ['hacia_teide','desde_teide']])
    return origenes,miembros,rutas,grupos,demanda


def test_proyeccion_sobre_cruce_no_asigna_conexion_o_recorrido():
    from movilidad_teide.asignacion import diagnosticar_reutilizacion_trazados
    o,m,r,_,_=ejemplo_revision_trazados();antes=o.copy(deep=True)
    d=diagnosticar_reutilizacion_trazados(o,m,r)
    b=d.loc[d.origen_id.eq('b')&d.comparacion_id.eq('r1')]
    assert len(b)==2 and b.separacion_cartografica_m.eq(0).all()
    assert b.longitud_trazado_desde_proyeccion_hasta_cabecera_m.eq(5).all()
    assert not b.es_subgrupo_referencia_trazada.any()
    assert not d.conexion_circulable_confirmada.any() and not d.recorrido_asignado_para_balance.any()
    pd.testing.assert_frame_equal(o,antes)


def test_punto_ausente_y_cabecera_sin_trazado_conservan_ausencias():
    from movilidad_teide.asignacion import diagnosticar_reutilizacion_trazados
    o,m,r,_,_=ejemplo_revision_trazados();o.loc[o.origen_id.eq('b'),'geometry']=None
    d=diagnosticar_reutilizacion_trazados(o,m,r)
    sin_punto=d.loc[d.origen_id.isin(['b','d'])]
    assert set(d.origen_id)==set(o.origen_id) and sin_punto.separacion_cartografica_m.isna().all()
    assert sin_punto.longitud_trazado_desde_proyeccion_hasta_cabecera_m.isna().all()
    assert d.loc[d.origen_id.eq('d'),'comparacion_id'].isna().all()
    assert set(d.loc[d.origen_id.eq('d'),'sentido'])=={'hacia_teide','desde_teide'}


def test_extremo_proyectado_no_se_convierte_en_acceso_cero():
    from movilidad_teide.asignacion import diagnosticar_reutilizacion_trazados
    o,m,r,_,_=ejemplo_revision_trazados();o.loc[o.origen_id.eq('b'),'geometry']=Point(0,20)
    d=diagnosticar_reutilizacion_trazados(o,m,r)
    b=d.loc[d.origen_id.eq('b')&d.comparacion_id.eq('r1')]
    assert b.longitud_trazado_desde_proyeccion_hasta_cabecera_m.eq(0).all()
    assert b.separacion_cartografica_m.eq(10).all() and not b.recorrido_asignado_para_balance.any()


@pytest.mark.parametrize('defecto',['sentido','referencia','cabecera','duplicado','pertenencia','crs','crs_distinto','geometria'])
def test_diagnostico_rechaza_comparaciones_incompletas_o_incoherentes(defecto):
    from movilidad_teide.asignacion import diagnosticar_reutilizacion_trazados
    o,m,r,_,_=ejemplo_revision_trazados()
    if defecto=='sentido':r=r.iloc[1:].copy()
    elif defecto=='referencia':r.loc[r.comparacion_id.eq('r1'),'origen_referencia_id']='inexistente'
    elif defecto=='cabecera':r.loc[r.comparacion_id.eq('r1'),'corredor_candidato']='otro'
    elif defecto=='duplicado':r=pd.concat([r,r.iloc[[0]]],ignore_index=True)
    elif defecto=='pertenencia':m=pd.concat([m,m.iloc[[0]]],ignore_index=True)
    elif defecto=='crs':o=o.to_crs(4326)
    elif defecto=='crs_distinto':r=r.to_crs(3857)
    elif defecto=='geometria':o.loc[o.origen_id.eq('b'),'geometry']=Point()
    with pytest.raises(ErrorAsignacion):diagnosticar_reutilizacion_trazados(o,m,r)


def test_cobertura_distingue_puntos_y_familias_sin_duplicar_candidatos():
    from movilidad_teide.asignacion import diagnosticar_reutilizacion_trazados,resumir_revision_trazados
    o,m,r,g,d=ejemplo_revision_trazados();antes=d.copy(deep=True)
    proy=diagnosticar_reutilizacion_trazados(o,m,r)
    revision,detalle,cobertura=resumir_revision_trazados(o,g,d,m,proy,{})
    assert len(detalle)==4 and len(revision)==3 and len(cobertura)==8
    assert cobertura.demanda_total_media57.eq(100).all()
    assert np.allclose(cobertura.fraccion_subgrupos_referencia_trazada,.3)
    assert np.allclose(cobertura.fraccion_familias_con_referencia_trazada,.6)
    assert cobertura.demanda_sin_punto_media57.eq(40).all()
    assert cobertura.demanda_sin_cabecera_media57.eq(40).all()
    assert not revision.familia_completamente_contrastada.any()
    assert detalle.subgrupo_referencia_con_trazado.sum()==2 and detalle.familia_con_referencia_trazada.sum()==3
    assert detalle.loc[detalle.origen_id.eq('b'),'comparacion_cercana_cartograficamente'].item()=='r1'
    pd.testing.assert_frame_equal(d,antes)


def test_revision_con_demanda_nula_no_inventa_porcentajes():
    from movilidad_teide.asignacion import diagnosticar_reutilizacion_trazados,resumir_revision_trazados
    o,m,r,g,d=ejemplo_revision_trazados();d['viajes_persona_media_57_matrices']=0.
    _,_,c=resumir_revision_trazados(o,g,d,m,diagnosticar_reutilizacion_trazados(o,m,r),{})
    assert c.fraccion_subgrupos_referencia_trazada.isna().all()
    assert c.fraccion_familias_con_referencia_trazada.isna().all()


@pytest.mark.parametrize('defecto',['colectivo','negativo','excepcion'])
def test_revision_rechaza_perdidas_de_demanda_y_excepciones_sin_grupo(defecto):
    from movilidad_teide.asignacion import diagnosticar_reutilizacion_trazados,resumir_revision_trazados
    o,m,r,g,d=ejemplo_revision_trazados();ex={}
    if defecto=='colectivo':d=d.iloc[1:].copy()
    elif defecto=='negativo':d.loc[0,'viajes_persona_media_57_matrices']=-1.
    else:ex={'inexistente':{'accion':'algo','motivo':'sin grupo'}}
    with pytest.raises(ErrorAsignacion):resumir_revision_trazados(o,g,d,m,diagnosticar_reutilizacion_trazados(o,m,r),ex)


def test_dos_referencias_en_la_misma_familia_no_pierden_trazados_ni_duplican_demanda():
    from shapely.geometry import LineString
    from movilidad_teide.asignacion import diagnosticar_reutilizacion_trazados,resumir_revision_trazados
    o,m,r,g,d=ejemplo_revision_trazados();antes=d.copy(deep=True)
    # El segundo punto de g1 tiene su conexión propia, pero pertenece a la misma familia.
    nuevas=[]
    for sentido in ['hacia_teide','desde_teide']:
        coordenadas=[(0,5),(0,10)]
        nuevas.append({'comparacion_id':'r3','itinerary_id':'r3_'+sentido,'origen_referencia_id':'b',
            'corredor_candidato':'norte','sentido':sentido,
            'geometry':LineString(coordenadas if sentido=='hacia_teide' else coordenadas[::-1])})
    r=gpd.GeoDataFrame(pd.concat([r,gpd.GeoDataFrame(nuevas,crs=r.crs)],ignore_index=True),crs=r.crs)
    proy=diagnosticar_reutilizacion_trazados(o,m,r)
    revision,detalle,cobertura=resumir_revision_trazados(o,g,d,m,proy,{})
    assert set(proy.comparacion_id.dropna())=={'r1','r2','r3'}
    assert revision.loc[revision.grupo_reducido_id.eq('g1'),'numero_subgrupos_referencia_trazada'].item()==2
    assert detalle.subgrupo_referencia_con_trazado.sum()==3
    assert np.allclose(cobertura.fraccion_subgrupos_referencia_trazada,.6)
    assert np.allclose(cobertura.fraccion_familias_con_referencia_trazada,.6)
    assert cobertura.demanda_total_media57.eq(100).all()
    assert not revision.familia_completamente_contrastada.any()
    pd.testing.assert_frame_equal(d,antes)


def ejemplo_representatividad_geografica():
    """Datos sintéticos: puntos trazados, miembro pendiente y resto sin cabecera."""
    from movilidad_teide.asignacion import diagnosticar_reutilizacion_trazados,resumir_revision_trazados
    o,m,r,g,demanda=ejemplo_revision_trazados()
    o.loc[o.origen_id.eq('b'),'geometry']=Point(5,5)
    proy=diagnosticar_reutilizacion_trazados(o,m,r)
    familias,detalle,_=resumir_revision_trazados(o,g,demanda,m,proy,{})
    detalle['punto_referencia']=['Referencia A','Referencia B','Referencia C',None]
    familias['corredor_candidato']=['norte','norte',PENDIENTE]
    catalogo={cid:{'origin_id':oid,'reduced_group_id':grupo,'label':nombre}
        for cid,oid,grupo,nombre in [('r1','a','g1','Referencia A'),('r2','c','g2','Referencia C')]}
    longitudes=pd.DataFrame([{'comparacion_id':cid,'sentido':s,'longitud_alimentador_km':l}
        for cid,l in [('r1',1.),('r2',2.)] for s in ['hacia_teide','desde_teide']])
    return detalle,familias,demanda,proy,catalogo,longitudes,{}


def test_representatividad_conserva_demanda_sin_copiar_distancias_a_miembros():
    from movilidad_teide.asignacion import revisar_representatividad_geografica
    args=ejemplo_representatividad_geografica();copias=[t.copy(deep=True) for t in args[:4]]
    d,f,c=revisar_representatividad_geografica(*args)
    assert d.tratamiento_geografico.tolist()==['referencia_trazada','conexion_pendiente','referencia_trazada','sin_cabecera']
    assert c.demanda_total_media57.eq(100).all()
    assert c.demanda_tratamiento_referencia_trazada_media57.eq(30).all()
    assert c.demanda_tratamiento_conexion_pendiente_media57.eq(30).all() and c.demanda_tratamiento_sin_cabecera_media57.eq(40).all()
    assert d.loc[d.origen_id.eq('b'),'longitud_perfil_propio_hacia_teide_km'].isna().all()
    assert d.loc[d.origen_id.eq('a'),'longitud_perfil_propio_hacia_teide_km'].item()==1
    assert f.referencias_de_todos_los_miembros_trazadas.tolist()==[False,True,False]
    assert not d.representatividad_adoptada_para_balance.any() and not f.representatividad_adoptada_para_balance.any()
    for a,b in zip(args[:4],copias):pd.testing.assert_frame_equal(a,b)


def test_candidato_de_familia_se_separa_del_mas_proximo_de_otra_familia():
    from movilidad_teide.asignacion import revisar_representatividad_geografica
    args=list(ejemplo_representatividad_geografica())
    # Otra familia queda más cerca; eso no justifica cambiar la pertenencia.
    args[3].loc[args[3].origen_id.eq('b')&args[3].comparacion_id.eq('r2'),'separacion_cartografica_m']=0
    d,_,_=revisar_representatividad_geografica(*args)
    b=d.loc[d.origen_id.eq('b')].iloc[0]
    assert b.candidato_revision_misma_familia=='r1' and b.separacion_candidato_familia_m==5
    assert b.candidato_familia_nombre=='Referencia A' and pd.isna(b.longitud_perfil_propio_desde_teide_km)


def test_representatividad_distingue_punto_ausente_de_sin_cabecera():
    from movilidad_teide.asignacion import revisar_representatividad_geografica
    args=list(ejemplo_representatividad_geografica());args[0].loc[args[0].origen_id.eq('b'),'punto_referencia']=None
    d,_,c=revisar_representatividad_geografica(*args)
    assert c.demanda_tratamiento_sin_punto_media57.eq(30).all() and c.demanda_tratamiento_sin_cabecera_media57.eq(40).all()
    assert c.demanda_tratamiento_conexion_pendiente_media57.eq(0).all()
    assert d.loc[d.origen_id.eq('b'),'candidato_revision_misma_familia'].isna().all()


def test_excepcion_de_cabecera_prevalece_sobre_disponibilidad_de_referencia():
    from movilidad_teide.asignacion import revisar_representatividad_geografica
    args=list(ejemplo_representatividad_geografica());args[-1]={'g1':{'accion':'Revisar cabecera','motivo':'Inferencia pendiente'}}
    d,_,c=revisar_representatividad_geografica(*args)
    assert c.demanda_tratamiento_cabecera_en_revision_media57.eq(40).all() and c.demanda_tratamiento_referencia_trazada_media57.eq(20).all()
    assert d.loc[d.grupo_reducido_id.eq('g1'),'longitud_perfil_propio_hacia_teide_km'].isna().all()


def test_representatividad_demanda_nula_no_inventa_porcentajes():
    from movilidad_teide.asignacion import revisar_representatividad_geografica
    args=list(ejemplo_representatividad_geografica());args[2]['viajes_persona_media_57_matrices']=0.
    _,_,c=revisar_representatividad_geografica(*args)
    assert c.filter(like='fraccion_').isna().all().all()


def test_representatividad_conserva_dos_referencias_y_sus_longitudes():
    from movilidad_teide.asignacion import revisar_representatividad_geografica
    args=list(ejemplo_representatividad_geografica());args[0].loc[args[0].origen_id.eq('b'),'subgrupo_referencia_con_trazado']=True
    args[4]['r3']={'origin_id':'b','reduced_group_id':'g1','label':'Referencia B'}
    nuevas=args[3].loc[args[3].comparacion_id.eq('r1')].copy();nuevas['comparacion_id']='r3'
    nuevas['origen_referencia_id']='b';nuevas.loc[nuevas.origen_id.eq('b'),'separacion_cartografica_m']=0
    args[3]=pd.concat([args[3],nuevas],ignore_index=True)
    args[5]=pd.concat([args[5],pd.DataFrame([{'comparacion_id':'r3','sentido':s,'longitud_alimentador_km':3.}
        for s in ['hacia_teide','desde_teide']])],ignore_index=True)
    d,f,c=revisar_representatividad_geografica(*args)
    assert f.loc[f.grupo_reducido_id.eq('g1'),'referencias_de_todos_los_miembros_trazadas'].item()
    assert set(d.loc[d.grupo_reducido_id.eq('g1'),'comparacion_propia_id'])=={'r1','r3'}
    assert d.loc[d.origen_id.eq('b'),'longitud_perfil_propio_hacia_teide_km'].item()==3
    assert c.demanda_tratamiento_referencia_trazada_media57.eq(60).all()


@pytest.mark.parametrize('defecto',['colectivo','negativo','no_finito','longitud_sentido','longitud_cero',
    'familia','origen_duplicado','catalogo_duplicado','cobertura','proyeccion_sentido','proyeccion_negativa','excepcion'])
def test_representatividad_rechaza_incoherencias_o_perdida_de_demanda(defecto):
    from movilidad_teide.asignacion import revisar_representatividad_geografica
    args=list(ejemplo_representatividad_geografica())
    if defecto=='colectivo':args[2]=args[2].iloc[1:]
    elif defecto=='negativo':args[2].loc[0,'viajes_persona_media_57_matrices']=-1
    elif defecto=='no_finito':args[2].loc[0,'viajes_persona_media_57_matrices']=np.nan
    elif defecto=='longitud_sentido':args[5]=args[5].iloc[1:]
    elif defecto=='longitud_cero':args[5].loc[0,'longitud_alimentador_km']=0
    elif defecto=='familia':args[4]['r1']['reduced_group_id']='g2'
    elif defecto=='origen_duplicado':args[0]=pd.concat([args[0],args[0].iloc[[0]]],ignore_index=True)
    elif defecto=='catalogo_duplicado':args[4]['r3']=args[4]['r1'].copy()
    elif defecto=='cobertura':args[0].loc[0,'subgrupo_referencia_con_trazado']=False
    elif defecto=='proyeccion_sentido':args[3]=args[3].iloc[1:]
    elif defecto=='proyeccion_negativa':args[3].loc[0,'separacion_cartografica_m']=-1
    elif defecto=='excepcion':args[-1]={'inexistente':{'accion':'Revisar','motivo':'Sin grupo'}}
    with pytest.raises(ErrorAsignacion):revisar_representatividad_geografica(*args)


def ejemplo_cierre_por_componentes(excepciones=None, sin_punto=False):
    from copy import deepcopy
    from movilidad_teide.asignacion import revisar_representatividad_geografica
    args=list(ejemplo_representatividad_geografica())
    if sin_punto:args[0].loc[args[0].origen_id.eq('b'),'punto_referencia']=None
    args[-1]=excepciones or {}
    detalle,familias,_=revisar_representatividad_geografica(*args)
    catalogo=deepcopy(args[4])
    for cid,ref in catalogo.items():
        ref.update(head_reference_anchor_id='head_'+cid,terminal_reference_anchor_id='terminal_'+cid,head_label='Cabecera '+cid,terminal_label='Terminal')
    proy=args[3].copy();proy['diferencia_cota_origen_proyeccion_m']=12.
    montanas=pd.DataFrame([{'comparacion_id':cid,'sentido':s,'tramo_cabecera_terminal_km':l+i}
        for cid,l in [('r1',7.),('r2',9.)] for i,s in enumerate(['hacia_teide','desde_teide'])])
    return detalle,familias,args[2],proy,catalogo,montanas


def test_cierre_separa_montana_y_perfil_completo_con_demanda_conservada():
    from movilidad_teide.asignacion import cerrar_revision_geografica
    args=ejemplo_cierre_por_componentes();antes=[x.copy(deep=True) for x in args[:4]]
    d,f,c,m=cerrar_revision_geografica(*args)
    assert d.perfil_completo_del_punto_disponible.tolist()==[True,False,True,False]
    assert d.montana_cabecera_candidata_disponible.tolist()==[True,True,True,False]
    b=d.loc[d.origen_id.eq('b')].iloc[0]
    assert b.comparacion_montana_candidata_id=='r1' and b.longitud_montana_candidata_hacia_teide_km==7
    assert b.longitud_montana_candidata_desde_teide_km==8 and pd.isna(b.longitud_perfil_propio_hacia_teide_km)
    assert c.demanda_total_media57.eq(100).all()
    assert c.demanda_pieza_perfil_del_punto_media57.eq(30).all()
    assert c.demanda_pieza_solo_montana_candidata_media57.eq(30).all()
    assert c.demanda_pieza_sin_montana_utilizable_media57.eq(40).all()
    assert m['revision_de_cierre_realizada'] and not m['cobertura_geografica_completa']
    assert m['demanda_positiva_sin_perfil_completo'] and not m['energia_calculada']
    assert not m['perfil_asignado_por_proximidad'] and not d.error_alimentador_acotado.any()
    for a,b in zip(args[:4],antes):pd.testing.assert_frame_equal(a,b)


def test_cierre_usa_cota_del_candidato_de_familia_y_no_del_mas_proximo_global():
    from movilidad_teide.asignacion import cerrar_revision_geografica
    args=list(ejemplo_cierre_por_componentes());p=args[3]
    p.loc[p.origen_id.eq('b')&p.comparacion_id.eq('r2'),['separacion_cartografica_m','diferencia_cota_origen_proyeccion_m']]=[0.,-500.]
    d,_,_,_=cerrar_revision_geografica(*args);b=d.loc[d.origen_id.eq('b')].iloc[0]
    assert b.separacion_candidato_familia_hacia_teide_m==5
    assert b.diferencia_cota_candidato_familia_hacia_teide_m==12
    assert b.comparacion_montana_candidata_id=='r1'


def test_cierre_punto_ausente_conserva_solo_montana_sin_inventar_alimentador():
    from movilidad_teide.asignacion import cerrar_revision_geografica
    d,_,_,m=cerrar_revision_geografica(*ejemplo_cierre_por_componentes(sin_punto=True))
    b=d.loc[d.origen_id.eq('b')].iloc[0]
    assert b.montana_cabecera_candidata_disponible and not b.perfil_completo_del_punto_disponible
    assert pd.isna(b.separacion_candidato_familia_hacia_teide_m) and pd.isna(b.longitud_perfil_propio_hacia_teide_km)
    assert m['montanas_de_cabecera_candidata']==3


def test_cierre_excepcion_de_cabecera_no_hereda_montana_por_tener_familia_trazada():
    from movilidad_teide.asignacion import cerrar_revision_geografica
    args=ejemplo_cierre_por_componentes({'g1':{'accion':'Revisar','motivo':'Cabecera inferida'}})
    d,_,c,_=cerrar_revision_geografica(*args)
    assert not d.loc[d.grupo_reducido_id.eq('g1'),'montana_cabecera_candidata_disponible'].any()
    assert d.loc[d.grupo_reducido_id.eq('g1'),'longitud_montana_candidata_hacia_teide_km'].isna().all()
    assert c.demanda_pieza_sin_montana_utilizable_media57.eq(80).all()


def test_cierre_con_demanda_cero_no_inventa_cobertura_ni_energia():
    from movilidad_teide.asignacion import cerrar_revision_geografica
    args=list(ejemplo_cierre_por_componentes());args[2]['viajes_persona_media_57_matrices']=0.
    _,_,c,m=cerrar_revision_geografica(*args)
    assert c.filter(like='fraccion_pieza_').isna().all().all()
    assert not m['demanda_positiva_sin_perfil_completo'] and not m['cobertura_geografica_completa']


@pytest.mark.parametrize('defecto',['negativo','colectivo','origen','montana_sentido','montana_cero',
    'montana_duplicada','perfil_ajeno','candidato_ajeno','proyeccion_sentido','separacion_negativa',
    'cota_infinita','cabecera_ambigua','terminal_ambiguo'])
def test_cierre_rechaza_perdidas_y_reutilizacion_incompatible(defecto):
    from copy import deepcopy
    from movilidad_teide.asignacion import cerrar_revision_geografica
    args=list(ejemplo_cierre_por_componentes())
    if defecto=='negativo':args[2].loc[0,'viajes_persona_media_57_matrices']=-1
    elif defecto=='colectivo':args[2]=args[2].iloc[1:]
    elif defecto=='origen':args[0]=pd.concat([args[0],args[0].iloc[[0]]],ignore_index=True)
    elif defecto=='montana_sentido':args[5]=args[5].iloc[1:]
    elif defecto=='montana_cero':args[5].loc[0,'tramo_cabecera_terminal_km']=0
    elif defecto=='montana_duplicada':args[5]=pd.concat([args[5],args[5].iloc[[0]]],ignore_index=True)
    elif defecto=='perfil_ajeno':args[0].loc[args[0].origen_id.eq('a'),'comparacion_propia_id']='r2'
    elif defecto=='candidato_ajeno':args[0].loc[args[0].origen_id.eq('b'),'candidato_revision_misma_familia']='r2'
    elif defecto=='proyeccion_sentido':args[3]=args[3].iloc[1:]
    elif defecto=='separacion_negativa':args[3].loc[0,'separacion_cartografica_m']=-1
    elif defecto=='cota_infinita':args[3].loc[0,'diferencia_cota_origen_proyeccion_m']=np.inf
    elif defecto=='cabecera_ambigua':
        args[4]['r3']=deepcopy(args[4]['r1']);args[4]['r3'].update(origin_id='b',head_reference_anchor_id='otra_cabecera')
    elif defecto=='terminal_ambiguo':
        args[4]['r3']=deepcopy(args[4]['r1']);args[4]['r3'].update(origin_id='b',terminal_reference_anchor_id='otro_terminal')
    if defecto in ['cabecera_ambigua','terminal_ambiguo']:
        # Completar sus longitudes: la prueba debe fallar por el extremo incompatible.
        nuevas=args[5].loc[args[5].comparacion_id.eq('r1')].copy()
        nuevas['comparacion_id']='r3'
        args[5]=pd.concat([args[5],nuevas],ignore_index=True)
    with pytest.raises(ErrorAsignacion):cerrar_revision_geografica(*args)


# D121: las propuestas son configurables y no alteran la demanda ni los puntos fuente.
from copy import deepcopy
from movilidad_teide.asignacion import revisar_cabeceras_de_estudio


def _casos_cabecera_estudio():
    ids=['alto','nulo','resto','referencia'];coords=[Point(-16.43,28.23),None,None,Point(-16.72,28.06)]
    origins=gpd.GeoDataFrame({'origen_id':ids,'corredor_candidato':['norte','sin_asignar','sin_asignar','sur'],
        'stop_id_referencia':['1',None,None,'2'],'municipio_referencia':['Sur','Urbano','Costa','Costa']},geometry=coords,crs=4326)
    relation=pd.DataFrame({'origen_id':ids,'zona_id':[1,2,3,4]})
    demand=[];cent=[]
    for i,oid in enumerate(ids,1):
        amount=0.0 if oid=='nulo' else float(i)
        row={'zone_id':i,'centroid_id':i,'lon':-16.721-i*.0001,'lat':28.06}
        for prefix,sense in [('gen','hacia_teide'),('attr','desde_teide')]:
            for collective in SEGMENTOS:
                demand.append({'origen_id':oid,'colectivo':collective,'sentido':sense,'viajes_persona_media_57_matrices':amount})
                row[f'{prefix}_{collective}']=amount
        cent.append(row)
    zones=gpd.GeoDataFrame({'zona_id':[1,2,3,4]},geometry=[box(-16.74,28.05,-16.70,28.07)]*4,crs=4326)
    roads=gpd.GeoDataFrame({'via_nombre':['TF-28'],'tramo_inicio':['A'],'tramo_final':['B']},geometry=[Point(-16.7,28.05).buffer(.01).boundary],crs=4326)
    catalog={'metric_crs':'EPSG:4083','anchors':{'o':{},'h':{},'t':{}},'origin_access_comparisons':{'ref':{
        'origin_id':'referencia','origin_label':'Referencia costera','head_label':'Cabecera sur','terminal_label':'Terminal',
        'origin_reference_anchor_id':'o','head_reference_anchor_id':'h','terminal_reference_anchor_id':'t'}}}
    specs=[]
    for oid,kind in [('alto','cabecera_propuesta'),('nulo','sin_demanda_positiva_media57'),('resto','aproximacion_territorial')]:
        specs.append({'origen_id':oid,'corredor_fuente_esperado':'norte' if oid=='alto' else 'sin_asignar',
            'tipo':kind,'comparacion_referencia_id':'ref','vias_a_contrastar':['TF-28'],
            'fundamento':'Referencia territorial explícita','limitaciones':'Acceso y error energético pendientes',
            'alternativas_comparacion_ids':[]})
    spec={'decision':'D121','hipotesis':'H074','casos':specs}
    mountain=pd.DataFrame({'comparacion_id':['ref','ref'],'sentido':['hacia_teide','desde_teide'],
        'tramo_cabecera_terminal_km':[15.,15.1],'referencia_coche_hasta_terminal_km':[40.,41.]})
    return [origins,pd.DataFrame(demand),relation,pd.DataFrame(cent),zones,roads,catalog,spec,mountain]


def test_revision_cabeceras_conserva_fuente_y_distingue_propio_aproximado_y_nulo():
    args=_casos_cabecera_estudio();before=[a.copy(deep=True) if isinstance(a,pd.DataFrame) else deepcopy(a) for a in args]
    t,m=revisar_cabeceras_de_estudio(*args);t=t.set_index('origen_id')
    assert m['casos_revisados']==3 and m['cabeceras_propuestas']==m['aproximaciones_territoriales']==m['casos_sin_demanda_positiva_media57']==1
    assert not m['fuente_y_pertenencias_modificadas'] and not m['reparto_operativo_reasignado'] and not m['balance_anual_habilitado']
    assert t.loc['alto','punto_propio_conservado'] and t.loc['alto','corredor_fuente_conservado']=='norte'
    assert t.loc['alto','cabecera_estudio_propuesta']=='Cabecera sur' and t.loc['alto','propuesta_difiere_de_fuente']
    assert pd.isna(t.loc['alto','longitud_referencia_aproximada_hacia_teide_km'])
    assert t.loc['resto','referencia_territorial_aproximada_id']=='ref' and not t.loc['resto','punto_propio_conservado']
    assert t.loc['resto','longitud_referencia_aproximada_hacia_teide_km']==40 and t.loc['resto','longitud_referencia_aproximada_desde_teide_km']==41
    assert t.loc['resto','separacion_media_centroides_referencia_aproximada_m']>0
    assert not t.loc['resto','error_energetico_aproximacion_acotado']
    assert pd.isna(t.loc['nulo','longitud_montana_propuesta_hacia_teide_km']) and not t.loc['nulo','actividad_anual_nula_demostrada']
    assert not t.perfil_propio_nuevo_calculado.any()
    for a,b in zip(args,before):
        if isinstance(a,gpd.GeoDataFrame):
            from geopandas.testing import assert_geodataframe_equal
            assert_geodataframe_equal(a,b)
        elif isinstance(a,pd.DataFrame):pd.testing.assert_frame_equal(a,b,check_exact=True)
        else:assert a==b


@pytest.mark.parametrize('defecto',['caso_duplicado','origen_ajeno','fuente_alterada','via_ausente','vias_vacias',
    'referencia_ausente','anclaje_ausente','alternativa_ausente','punto_ausente_en_propuesta',
    'punto_propio_en_aproximacion','municipio_distinto','cero_con_demanda','positivo_sin_demanda',
    'demanda_negativa','colectivo_ausente','demanda_repetida','centroide_ausente','centroide_repetido',
    'centroide_demanda_distinta','longitud_regreso_ausente','longitudes_repetidas'])
def test_revision_cabeceras_rechaza_perdidas_y_aproximaciones_incompatibles(defecto):
    a=_casos_cabecera_estudio();cases=a[7]['casos']
    if defecto=='caso_duplicado':cases.append(deepcopy(cases[0]))
    elif defecto=='origen_ajeno':cases[0]['origen_id']='ajeno'
    elif defecto=='fuente_alterada':cases[0]['corredor_fuente_esperado']='sur'
    elif defecto=='via_ausente':cases[0]['vias_a_contrastar']=['TF-999']
    elif defecto=='vias_vacias':cases[0]['vias_a_contrastar']=[]
    elif defecto=='referencia_ausente':cases[0]['comparacion_referencia_id']='ajena'
    elif defecto=='anclaje_ausente':a[6]['anchors'].pop('h')
    elif defecto=='alternativa_ausente':cases[0]['alternativas_comparacion_ids']=['ajena']
    elif defecto=='punto_ausente_en_propuesta':a[0].loc[0,'geometry']=None
    elif defecto=='punto_propio_en_aproximacion':a[0].loc[2,'geometry']=Point(-16.72,28.06)
    elif defecto=='municipio_distinto':a[0].loc[2,'municipio_referencia']='Otro'
    elif defecto=='cero_con_demanda':cases[0]['tipo']='sin_demanda_positiva_media57'
    elif defecto=='positivo_sin_demanda':cases[1]['tipo']='aproximacion_territorial'
    elif defecto=='demanda_negativa':a[1].loc[0,'viajes_persona_media_57_matrices']=-1
    elif defecto=='colectivo_ausente':a[1]=a[1].iloc[1:]
    elif defecto=='demanda_repetida':a[1]=pd.concat([a[1],a[1].iloc[:1]],ignore_index=True)
    elif defecto=='centroide_ausente':a[3]=a[3].iloc[1:]
    elif defecto=='centroide_repetido':a[3]=pd.concat([a[3],a[3].iloc[:1]],ignore_index=True)
    elif defecto=='centroide_demanda_distinta':a[3].loc[0,'gen_extranjero']+=1
    elif defecto=='longitud_regreso_ausente':a[8]=a[8].iloc[:1]
    elif defecto=='longitudes_repetidas':a[8]=pd.concat([a[8],a[8].iloc[:1]],ignore_index=True)
    with pytest.raises(ErrorAsignacion):revisar_cabeceras_de_estudio(*a)


def ejemplo_representacion_estudio():
    # Ejemplo sintético exclusivo de pruebas: no son datos o hipótesis del Teide.
    ids=list('abcd');valor='viajes_persona_media_57_matrices'
    origenes=pd.DataFrame({'origen_id':ids,'corredor_candidato':['norte']*4,'cabecera_candidata':['Aguamansa']*4})
    detalle=pd.DataFrame({'origen_id':ids,'grupo_reducido_id':['fuente']*4,
        'tratamiento_geografico':['referencia_trazada','conexion_pendiente','cabecera_en_revision','cabecera_en_revision'],
        'comparacion_propia_id':['ra',None,None,None],
        'candidato_revision_misma_familia':[None,'ra',None,None]})
    familias=pd.DataFrame({'grupo_reducido_id':['fuente'],'nombre':['Fuente original'],'numero_subgrupos':[4]})
    demanda=pd.DataFrame([{'origen_id':oid,'colectivo':c,'sentido':s,valor:float((i+1)*(j+1)+k),
        'grupo_reducido_id':'fuente'} for i,oid in enumerate(ids) for j,c in enumerate(SEGMENTOS)
        for k,s in enumerate(['hacia_teide','desde_teide'])])
    demanda['demanda_grupo_misma_unidad']=demanda.groupby(['grupo_reducido_id','colectivo','sentido'])[valor].transform('sum')
    demanda['peso_origen_en_grupo_colectivo_sentido']=demanda[valor]/demanda.demanda_grupo_misma_unidad
    zonas=pd.DataFrame({'zona_id':range(1,7),'origen_id':list('aabccd'),'grupo_reducido_id':['fuente']*6})
    proy=pd.DataFrame([{'origen_id':'b','comparacion_id':'ra','sentido':s,
        'separacion_cartografica_m':30.,'diferencia_cota_origen_proyeccion_m':2.} for s in ['hacia_teide','desde_teide']])
    refs={}
    for cid,oid,coll,cor in [('ra','a','origin_access_comparisons','norte'),
          ('rc','c','study_origin_access_comparisons','sur'),('rd','d','coastal_valley_comparisons','este')]:
        refs[cid]={'origin_id':oid,'collection':coll,'corredor':cor,'head_reference_anchor_id':'h_'+cor,
            'terminal_reference_anchor_id':'t_'+cor,'head_label':cor,'terminal_label':'Terminal '+cor}
    longs=pd.DataFrame([{'comparacion_id':cid,'origen_id':r['origin_id'],'sentido':s,
        'directa_km':5.,'alimentador_km':3.,'montana_km':2.,'cadena_km':5.,
        'desvio_cadena_menos_directa_km':0.} for cid,r in refs.items() for s in ['hacia_teide','desde_teide']])
    spec={'decision':'Prueba','hipotesis':'Prueba','familias':[
        {'grupo_estudio_id':'estudio_sur','nombre':'Estudio sur','fundamento':'Prueba de integración',
         'corredor_fuente_esperado':'norte','corredor_estudio':'sur',
         'referencias':[{'coleccion':'study_origin_access_comparisons','comparacion_id':'rc'}]},
        {'grupo_estudio_id':'estudio_este','nombre':'Estudio este','fundamento':'Prueba de integración',
         'corredor_fuente_esperado':'norte','corredor_estudio':'este',
         'referencias':[{'coleccion':'coastal_valley_comparisons','comparacion_id':'rd'}]}]}
    return [detalle,origenes,familias,demanda,zonas,proy,refs,longs,spec]


def test_integracion_estudio_conserva_fuente_y_distingue_denominadores():
    from copy import deepcopy
    from movilidad_teide.asignacion import integrar_representacion_estudio
    args=ejemplo_representacion_estudio();antes=deepcopy(args);tab,m=integrar_representacion_estudio(*args)
    p=tab['demanda_representacion_estudio'];corr=tab['correspondencia_cabeceras_estudio']
    pd.testing.assert_frame_equal(p[args[3].columns],args[3])
    for a,b in zip(args[:6],antes[:6]):pd.testing.assert_frame_equal(a,b)
    assert args[6]==antes[6] and args[8]==antes[8]
    assert m['grupos_fuente']==1 and m['grupos_estudio']==3 and m['perfiles_propios_integrados']==3
    assert len(p)==32 and len(tab['zonas_representacion_estudio'])==6 and len(tab['recorridos_representacion_estudio'])==8
    c=p.loc[p.origen_id.eq('c')]
    assert c.peso_origen_grupo_estudio_colectivo_sentido.eq(1).all()
    assert c.peso_origen_en_grupo_colectivo_sentido.lt(1).all()
    assert corr.loc[corr.origen_id.eq('c'),'corredor_fuente'].item()=='norte'
    assert corr.loc[corr.origen_id.eq('c'),'corredor_estudio'].item()=='sur'
    r=tab['reparto_corredores_estudio']
    assert r.groupby(['colectivo','sentido']).diferencia_media57.sum().abs().max()<1e-10
    assert not m['energia_calculada'] and not m['visita_equivalente_validada']


def test_integracion_no_copia_alimentador_a_miembro_sin_perfil():
    from movilidad_teide.asignacion import integrar_representacion_estudio
    t,m=integrar_representacion_estudio(*ejemplo_representacion_estudio());b=t['recorridos_representacion_estudio'].loc[lambda f:f.origen_id.eq('b')]
    assert b[['directa_km','alimentador_km','cadena_km']].isna().all().all()
    assert b.montana_km.eq(2).all() and not b.perfil_propio_estudio_disponible.any()
    assert m['solo_montana_candidata']==1 and not m['cobertura_geografica_completa']


@pytest.mark.parametrize('defecto',['origen_duplicado','zona_duplicada','origen_ajeno','peso_fuente',
    'denominador_fuente','grupo_fuente','referencia_ausente','coleccion','propuesta_duplicada',
    'corredor_fuente','corredor_estudio','sentido_ausente','longitud_negativa','perfil_ajeno'])
def test_integracion_rechaza_perdidas_y_correspondencias_incorrectas(defecto):
    from movilidad_teide.asignacion import integrar_representacion_estudio
    a=ejemplo_representacion_estudio()
    if defecto=='origen_duplicado':a[0]=pd.concat([a[0],a[0].iloc[[0]]],ignore_index=True)
    elif defecto=='zona_duplicada':a[4].loc[1,'zona_id']=1
    elif defecto=='origen_ajeno':a[6]['rc']['origin_id']='ajeno'
    elif defecto=='peso_fuente':a[3].loc[0,'peso_origen_en_grupo_colectivo_sentido']+=.1
    elif defecto=='denominador_fuente':a[3].loc[0,'demanda_grupo_misma_unidad']+=1
    elif defecto=='grupo_fuente':a[3].loc[0,'grupo_reducido_id']='otro'
    elif defecto=='referencia_ausente':a[8]['familias'][0]['referencias'][0]['comparacion_id']='ausente'
    elif defecto=='coleccion':a[8]['familias'][0]['referencias'][0]['coleccion']='otra'
    elif defecto=='propuesta_duplicada':a[8]['familias'][0]['referencias']*=2
    elif defecto=='corredor_fuente':a[8]['familias'][0]['corredor_fuente_esperado']='otro'
    elif defecto=='corredor_estudio':a[8]['familias'][0]['corredor_estudio']='otro'
    elif defecto=='sentido_ausente':a[7]=a[7].iloc[1:].copy()
    elif defecto=='longitud_negativa':a[7].loc[0,'montana_km']=-1
    else:a[6]['rc']['origin_id']='a'
    with pytest.raises(ErrorAsignacion):integrar_representacion_estudio(*a)


@pytest.mark.parametrize('defecto',['cabecera','terminal'])
def test_integracion_mantiene_control_de_extremos_dentro_de_familia(defecto):
    from movilidad_teide.asignacion import integrar_representacion_estudio
    a=ejemplo_representacion_estudio();a[6]['rd']['corredor']='sur'
    a[8]['familias'][0]['referencias'].append({'coleccion':'coastal_valley_comparisons','comparacion_id':'rd'})
    a[8]['familias']=a[8]['familias'][:1]
    if defecto=='terminal':a[6]['rd']['head_reference_anchor_id']='h_sur'
    with pytest.raises(ErrorAsignacion,match='cabeceras o terminales distintos'):
        integrar_representacion_estudio(*a)


def test_integracion_grupo_de_demanda_cero_no_inventa_peso():
    from movilidad_teide.asignacion import integrar_representacion_estudio
    a=ejemplo_representacion_estudio();d=a[3];v='viajes_persona_media_57_matrices';d.loc[d.origen_id.eq('c'),v]=0.
    d['demanda_grupo_misma_unidad']=d.groupby(['grupo_reducido_id','colectivo','sentido'])[v].transform('sum')
    d['peso_origen_en_grupo_colectivo_sentido']=d[v]/d.demanda_grupo_misma_unidad
    t,_=integrar_representacion_estudio(*a);p=t['demanda_representacion_estudio'];assert p.loc[p.origen_id.eq('c'),'peso_origen_grupo_estudio_colectivo_sentido'].isna().all()


def ejemplo_normalizacion_estudio():
    f={'origin_id':'a','head_reference_anchor_id':'h','terminal_reference_anchor_id':'t',
       'head_label':'Cabecera','terminal_label':'Terminal','head_axis_anchor_id':'he',
       'itinerary_ids':['i','r']}
    cat={'origin_access_comparisons':{'a':f},'itineraries':{
        'i':{'origin_anchor_id':'o','destination_anchor_id':'te'},
        'r':{'origin_anchor_id':'te','destination_anchor_id':'o'}}}
    t=pd.DataFrame({'origen_id':['a','a'],'itinerary_id':['i','r'],'sentido':['Hacia el Teide','Regreso'],
        'referencia_coche_hasta_terminal_km':[5.,5.],
        'acceso_cabecera_en_coche_si_se_elige_km':[2.,2.],'tramo_cabecera_terminal_km':[3.,3.]})
    return cat,{('origin_access_comparisons','a'):t},[{'origin_anchor_id':'h','corredor':'norte'}]


def test_normalizacion_conserva_longitudes_y_ejes_por_sentido():
    from movilidad_teide.asignacion import normalizar_recorridos_estudio
    refs,t=normalizar_recorridos_estudio(*ejemplo_normalizacion_estudio())
    assert refs['a']['corredor']=='norte' and len(t)==2
    assert t.directa_km.eq(5).all() and t.cadena_km.eq(5).all()
    assert t.origen_eje_anchor_id.eq('o').all() and t.terminal_eje_anchor_id.eq('te').all()


@pytest.mark.parametrize('defecto',['duplicado','nan','negativo','cero','cadena','origen','itinerario','cabecera','tabla_ausente'])
def test_normalizacion_rechaza_longitudes_o_identidades_incoherentes(defecto):
    from movilidad_teide.asignacion import normalizar_recorridos_estudio
    a=ejemplo_normalizacion_estudio();t=a[1]['origin_access_comparisons','a']
    if defecto=='duplicado':t.loc[1,'sentido']='Hacia el Teide'
    elif defecto=='nan':t.loc[0,'tramo_cabecera_terminal_km']=np.nan
    elif defecto=='negativo':t.loc[0,'tramo_cabecera_terminal_km']=-3
    elif defecto=='cero':t.loc[0,'tramo_cabecera_terminal_km']=0
    elif defecto=='cadena':t.loc[0,'referencia_coche_hasta_terminal_km']=6
    elif defecto=='origen':t.loc[0,'origen_id']='otro'
    elif defecto=='itinerario':t.loc[0,'itinerary_id']='otro'
    elif defecto=='cabecera':a[2][0]['origin_anchor_id']='otro'
    else:a[1].clear()
    with pytest.raises(ErrorAsignacion):normalizar_recorridos_estudio(*a)


def test_normalizacion_cadena_independiente_no_inventa_itinerario_completo():
    from copy import deepcopy
    from movilidad_teide.asignacion import normalizar_recorridos_estudio
    cat,tablas,corredores=ejemplo_normalizacion_estudio();f=deepcopy(cat['origin_access_comparisons']['a'])
    f.update(origin_id='b',itinerary_ids=['ib','rb'],feeder_itinerary_ids=['fb','fbr'],
             geometry_mode='independent_reference_and_feeders',reused_mountain_comparison_id='a')
    cat['study_origin_access_comparisons']={'b':f}
    cat['itineraries'].update({'ib':{'origin_anchor_id':'ob','destination_anchor_id':'te'},
                             'rb':{'origin_anchor_id':'te','destination_anchor_id':'ob'}})
    t=tablas['origin_access_comparisons','a'].copy();t['origen_id']='b';t['itinerary_id']=['ib','rb']
    t['referencia_coche_hasta_terminal_km']=4.;t['recorrido_encadenado_hasta_terminal_km']=5.
    tablas['study_origin_access_comparisons','b']=t
    _,r=normalizar_recorridos_estudio(cat,tablas,corredores);r=r.loc[r.origen_id.eq('b')]
    assert r.itinerario_cadena_id.isna().all() and r.itinerario_alimentador_id.tolist()==['fb','fbr']
    assert r.itinerario_montana_referencia_id.tolist()==['i','r']
    assert r.desvio_cadena_menos_directa_km.eq(1).all()


def test_normalizacion_costera_conserva_calzadas_y_diferencia_negativa():
    from movilidad_teide.asignacion import normalizar_recorridos_estudio
    cat,tablas,corredores=ejemplo_normalizacion_estudio()
    cat['coastal_valley_comparisons']={'b':{'origin_id':'b','head_reference_anchor_id':'h',
        'terminal_axis_anchor_id':'te','reused_comparison_id':'a',
        'directa_itinerary_ids':['di','dr'],'costera_itinerary_ids':['ci','cr'],
        'head_axis_anchor_ids':['h_ida','h_regreso']}}
    for ident in ['di','ci']:cat['itineraries'][ident]={'origin_anchor_id':'ob','destination_anchor_id':'te'}
    for ident in ['dr','cr']:cat['itineraries'][ident]={'origin_anchor_id':'te','destination_anchor_id':'ob'}
    tablas['coastal_valley_comparisons','b']=pd.DataFrame({'sentido':['Hacia el Teide','Regreso'],
        'directa_tf523_km':[7.,7.],'alimentador_costero_km':[3.,3.],'montana_km':[3.,3.],
        'cadena_costera_km':[6.,6.]})
    _,r=normalizar_recorridos_estudio(cat,tablas,corredores);r=r.loc[r.origen_id.eq('b')]
    assert r.cabecera_eje_anchor_id.tolist()==['h_ida','h_regreso']
    assert r.itinerario_cadena_id.tolist()==['ci','cr'] and r.desvio_cadena_menos_directa_km.eq(-1).all()


def ejemplo_aproximaciones():
    from movilidad_teide.asignacion import integrar_representacion_estudio
    a=ejemplo_representacion_estudio();t,_=integrar_representacion_estudio(*a)
    spec={'casos':[{'origen_id':'b','tipo':'representante_familia',
        'comparacion_referencia_id':'ra','fundamento':'Familia territorial de prueba, no dato del Teide.'}]}
    return [t['correspondencia_cabeceras_estudio'],t['recorridos_representacion_estudio'],
            t['demanda_representacion_estudio'],a[6],a[7],spec]


def test_aproximacion_conserva_demanda_y_distingue_origen_de_referencia():
    from movilidad_teide.asignacion import preparar_aproximaciones_geograficas
    a=ejemplo_aproximaciones();t=preparar_aproximaciones_geograficas(*a)
    pd.testing.assert_frame_equal(t['demanda_referencia_calculo'][a[2].columns],a[2])
    r=t['recorridos_referencia_calculo'].loc[lambda f:f.origen_id.eq('b')]
    assert r.origen_referencia_calculo_id.eq('a').all() and not r.perfil_propio.any()
    assert r.aproximacion_territorial.all() and r.cadena_km.eq(5).all()
    assert a[1].loc[a[1].origen_id.eq('b'),'cadena_km'].isna().all()


@pytest.mark.parametrize('defecto',['duplicado','falta_caso','referencia_ajena','otra_familia',
    'sin_fundamento','demanda_positiva_condicional','longitud_ausente','longitud_negativa','demanda_duplicada','colectivo_ausente'])
def test_aproximacion_rechaza_perdidas_y_asignaciones_infundadas(defecto):
    from movilidad_teide.asignacion import preparar_aproximaciones_geograficas
    a=ejemplo_aproximaciones();s=a[5]['casos'][0]
    if defecto=='duplicado':a[5]['casos']*=2
    elif defecto=='falta_caso':a[5]['casos']=[]
    elif defecto=='referencia_ajena':s['comparacion_referencia_id']='ausente'
    elif defecto=='otra_familia':s['comparacion_referencia_id']='rc'
    elif defecto=='sin_fundamento':s['fundamento']=''
    elif defecto=='demanda_positiva_condicional':s['tipo']='condicional_media_nula'
    elif defecto=='longitud_ausente':a[4]=a[4].iloc[1:].copy()
    elif defecto=='longitud_negativa':a[4].loc[0,'cadena_km']=-1
    elif defecto=='demanda_duplicada':a[2]=pd.concat([a[2],a[2].iloc[[0]]],ignore_index=True)
    else:a[2]=a[2].iloc[1:].copy()
    with pytest.raises(ErrorAsignacion):preparar_aproximaciones_geograficas(*a)


def test_aproximacion_condicional_conserva_ausencias_y_cero_publicado():
    from movilidad_teide.asignacion import preparar_aproximaciones_geograficas
    a=ejemplo_aproximaciones();a[5]['casos'][0]['tipo']='condicional_media_nula'
    a[2].loc[a[2].origen_id.eq('b'),'viajes_persona_media_57_matrices']=0
    t=preparar_aproximaciones_geograficas(*a);r=t['recorridos_referencia_calculo'].loc[lambda x:x.origen_id.eq('b')]
    assert r[['directa_km','alimentador_km','montana_km','cadena_km']].isna().all().all()
    assert r.requiere_revision_si_demanda_positiva.all()
    assert r.comparacion_condicional_id.eq('ra').all()


from movilidad_teide.asignacion import referencias_velocidad_gtfs


def speed_gtfs_archive(tmp_path, transform=None):
    from zipfile import ZipFile
    import pandas as pd
    tables={
      'routes':pd.DataFrame([dict(route_id='r',route_short_name='341')]),
      'trips':pd.DataFrame([dict(trip_id='t',route_id='r',service_id='serv',shape_id='s',trip_headsign='B')]),
      'stop_times':pd.DataFrame([dict(trip_id='t',stop_sequence='1',stop_id='A',arrival_time='23:55:00',departure_time='23:55:00'),dict(trip_id='t',stop_sequence='2',stop_id='B',arrival_time='24:05:00',departure_time='24:05:00')]),
      'stops':pd.DataFrame([dict(stop_id='A',stop_name='Origen',stop_lon='0',stop_lat='0'),dict(stop_id='B',stop_name='Destino',stop_lon='.01',stop_lat='0')]),
      'shapes':pd.DataFrame([dict(shape_id='s',shape_pt_sequence='1',shape_pt_lon='0',shape_pt_lat='0',shape_dist_traveled='0'),dict(shape_id='s',shape_pt_sequence='2',shape_pt_lon='.01',shape_pt_lat='0',shape_dist_traveled='1')])}
    if transform:transform(tables)
    path=tmp_path/'gtfs.zip'
    with ZipFile(path,'w') as z:
      for name,table in tables.items():z.writestr(name+'.txt',table.to_csv(index=False))
    return path


def test_gtfs_speed_uses_geometry_not_undocumented_distance_units(tmp_path):
    p=speed_gtfs_archive(tmp_path);detail,summary=referencias_velocidad_gtfs(p,lineas=('341',))
    assert len(detail)==1 and detail.duracion_programada_min.item()==10
    assert detail.longitud_shape_completo_km.item()==pytest.approx(1.1131949,abs=1e-7)
    assert detail.velocidad_referencia_kmh.item()==pytest.approx(6.6791694,abs=1e-6)
    assert summary.registros_trip.item()==1
    assert 'no son expediciones al día' in summary.alcance.item()
    assert detail.separacion_inicio_shape_parada_m.item()==0


@pytest.mark.parametrize('bad_time',['','23:50:00'])
def test_missing_or_incoherent_gtfs_time_keeps_trip_without_speed(tmp_path,bad_time):
    def change(t):t['stop_times'].loc[1,'arrival_time']=bad_time;t['stop_times'].loc[1,'departure_time']=bad_time
    p=speed_gtfs_archive(tmp_path,change);detail,summary=referencias_velocidad_gtfs(p,lineas=('341',))
    assert len(detail)==1 and detail.velocidad_referencia_kmh.isna().all()
    assert summary.tiempos_validos.item()==0 and summary.velocidad_min_kmh.isna().all()


@pytest.mark.parametrize('problem',['duplicate_trip','missing_shape','duplicate_sequence','invalid_time','missing_stop','bad_coordinate','missing_route'])
def test_gtfs_speed_rejects_ambiguous_sources(tmp_path,problem):
    def change(t):
      if problem=='duplicate_trip':t['trips']=pd.concat([t['trips'],t['trips']])
      if problem=='missing_shape':t['shapes']['shape_id']='otra'
      if problem=='duplicate_sequence':t['stop_times'].loc[1,'stop_sequence']='1'
      if problem=='invalid_time':t['stop_times'].loc[1,'arrival_time']='25:99:00'
      if problem=='missing_stop':t['stop_times'].loc[1,'stop_id']='ausente'
      if problem=='bad_coordinate':t['shapes'].loc[1,'shape_pt_lat']='100'
      if problem=='missing_route':t['routes']['route_short_name']='999'
    p=speed_gtfs_archive(tmp_path,change)
    with pytest.raises(ValueError):referencias_velocidad_gtfs(p,lineas=('341',))
