"""Comprobar conservación, calendario, límites de cupo y ausencias de actividad."""
import numpy as np
import pandas as pd
import pytest

from movilidad_teide.actividad import (
    comparar_tendencias_aforos,
    repartir_cupo_global,
    calcular_oferta_acceso,
    evaluar_cupos_diarios,
    proyectar_trafico_diario,
)


@pytest.fixture
def diarios():
    # Una base artificial de prueba permite comprobar el bisiesto sin fuentes externas.
    fechas = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    return pd.concat([
        pd.DataFrame({"fecha": fechas, "sentido": sentido, "pasos_vehiculo": valor})
        for sentido, valor in [("entrada", 1.0), ("salida", 2.0)]
    ], ignore_index=True)


def test_bisiesto_sin_crecimiento_y_sin_igualar_direcciones(diarios):
    fijas = proyectar_trafico_diario(diarios, 2028, "total_anual_objetivo")
    medias = proyectar_trafico_diario(diarios, 2028, "perfil_medio_por_mes_y_dia_semana")
    assert len(fijas) == len(medias) == 366 * 2
    assert fijas["fecha"].eq(pd.Timestamp("2028-02-29")).sum() == 2
    assert fijas.groupby("sentido")["pasos_vehiculo"].sum().to_dict() == pytest.approx({"entrada": 365, "salida": 730})
    assert medias.groupby("sentido")["pasos_vehiculo"].sum().to_dict() == {"entrada": 366, "salida": 732}


def test_reproduce_el_anio_base_con_perfiles_estacionales(diarios):
    # Medias mensuales y semanales conocidas deben reproducirse sin desplazar semanas.
    diarios["pasos_vehiculo"] *= diarios["fecha"].dt.month * 10 + diarios["fecha"].dt.dayofweek
    salida = proyectar_trafico_diario(diarios, 2025, "perfil_medio_por_mes_y_dia_semana")
    esperado = diarios.sort_values(["fecha", "sentido"])
    np.testing.assert_allclose(salida["pasos_vehiculo"], esperado["pasos_vehiculo"])


def test_cero_observado_no_produce_nan(diarios):
    diarios["pasos_vehiculo"] = 0.0
    salida = proyectar_trafico_diario(diarios, 2028, "total_anual_objetivo")
    assert salida["pasos_vehiculo"].eq(0).all()
    assert salida["factor_normalizacion"].eq(1).all()


@pytest.mark.parametrize("incidencia", ["falta_dia", "duplicado", "negativo", "ausente", "otro_anio"])
def test_rechaza_incidencias_sin_imputarlas(diarios, incidencia):
    if incidencia == "falta_dia": diarios = diarios.iloc[1:].copy()
    elif incidencia == "duplicado": diarios = pd.concat([diarios, diarios.iloc[[0]]])
    elif incidencia == "negativo": diarios.loc[0, "pasos_vehiculo"] = -1
    elif incidencia == "ausente": diarios.loc[0, "pasos_vehiculo"] = np.nan
    else: diarios.loc[0, "fecha"] = pd.Timestamp("2024-01-01")
    with pytest.raises(ValueError):
        proyectar_trafico_diario(diarios, 2028, "total_anual_objetivo")


def test_cupos_conservan_demanda_y_son_monotonos():
    salida = evaluar_cupos_diarios([0, 2, 5], [5, 0, 3])
    assert salida["cupo_coches_dia"].tolist() == [0, 3, 5]
    assert salida["pasos_que_caben_mismo_dia"].tolist() == [0, 5, 7]
    assert salida["pasos_que_exceden_cupo_mismo_dia"].tolist() == [7, 2, 0]
    assert salida["dias_con_exceso"].tolist() == [2, 1, 0]
    assert np.allclose(salida["pasos_que_caben_mismo_dia"] + salida["pasos_que_exceden_cupo_mismo_dia"], 7)


@pytest.mark.parametrize("valores,cupos", [([], [1]), ([np.nan], [1]), ([-1], [1]), ([1], []), ([1], [2, 2]), ([1], [1.5])])
def test_rechaza_cupos_o_demanda_invalidos(valores, cupos):
    with pytest.raises(ValueError): evaluar_cupos_diarios(valores, cupos)


def test_kilometros_comerciales_y_reposicion_con_calendario():
    salida = calcular_oferta_acceso(25, 10, 9, 1, 366)
    assert salida["vehiculo_km_dia"].tolist() == [250, 225, 25]
    assert salida["vehiculo_km_anio"].sum() == 500 * 366
    assert salida["recorridos_anio"].tolist() == [3660, 3294, 366]
    assert salida.iloc[-1]["sentido"] == "sin_desglose"


def test_calendario_ausente_no_es_calendario_cero():
    ausente = calcular_oferta_acceso(25, 10, 9, 1)
    cerrado = calcular_oferta_acceso(25, 10, 9, 1, 0)
    assert ausente[["dias_operacion", "recorridos_anio", "vehiculo_km_anio"]].isna().all().all()
    assert cerrado[["dias_operacion", "recorridos_anio", "vehiculo_km_anio"]].eq(0).all().all()


@pytest.mark.parametrize("dias", [True, -1, 1.5, 367, float("nan")])
def test_rechaza_calendario_no_fisico(dias):
    with pytest.raises(ValueError): calcular_oferta_acceso(25, 10, 9, 1, dias)


def test_crecimiento_compuesto_sin_doble_efecto_bisiesto(diarios):
    salida = proyectar_trafico_diario(diarios, 2028, "perfil_medio_por_mes_y_dia_semana", tasa_anual=.1)
    assert salida.groupby("sentido")["pasos_vehiculo"].sum().to_dict() == pytest.approx({"entrada": 366 * 1.1**3, "salida": 732 * 1.1**3})


def test_tendencia_no_confunde_hueco_2024_con_un_anio():
    filas = []
    for anio, factor in [(2019, 1 / 1.1**6), (2020, .1), (2021, .2), (2022, 1 / 1.1**3), (2023, 1 / 1.1**2), (2025, 1)]:
        for sentido in ["entrada", "salida"]:
            filas.append(dict(anio=anio, punto="prueba", sentido=sentido, tipo_vehiculo="coche", total_valores_fuente=365 * factor, horas_esperadas=8760, horas_ausentes=0, valores_negativos=0, valores_ausentes=0))
    comparacion = comparar_tendencias_aforos(pd.DataFrame(filas))
    assert np.allclose(comparacion["tasa_anual"], .1)
    central = comparacion.loc[comparacion["metodo"].eq("ajuste_log_lineal_con_exclusiones")]
    assert central["anios_utilizados"].eq("2019,2022,2023,2025").all()
    assert central["anios_excluidos_periodo"].eq("2020,2021").all()
    # Un negativo en un sentido invalida el acceso/año conjunto, sin borrar datos.
    datos = pd.DataFrame(filas)
    datos.loc[datos.anio.eq(2022) & datos.sentido.eq("entrada"), "valores_negativos"] = 1
    salida = comparar_tendencias_aforos(datos)
    ambos = salida.loc[salida.sentido.eq("ambos_sentidos") & salida.metodo.eq("ajuste_log_lineal_con_exclusiones")].iloc[0]
    assert ambos.anios_utilizados == "2019,2023,2025"
    assert ambos.anios_excluidos_calidad == "2022"


def test_cupo_global_no_se_aplica_500_a_cada_acceso():
    demanda = pd.DataFrame({"fecha": ["2028-01-01"] * 4, "punto": ["a", "b", "c", "d"], "pasos_vehiculo": [100, 200, 300, 400], "sentido": ["entrada"] * 4})
    salida = repartir_cupo_global(demanda, 500)
    assert salida["cuota_teorica_coches_dia"].tolist() == [50, 100, 150, 200]
    assert salida["cuota_teorica_coches_dia"].sum() == 500
    np.testing.assert_allclose(salida["cuota_teorica_coches_dia"] + salida["exceso_sobre_cuota_teorica"], salida["pasos_vehiculo"])


def test_cupo_sin_demanda_no_inventa_reservas():
    demanda = pd.DataFrame({"fecha": ["2028-01-01"] * 2, "punto": ["a", "b"], "pasos_vehiculo": [0., 0.]})
    salida = repartir_cupo_global(demanda, 500)
    assert salida["cuota_teorica_coches_dia"].eq(0).all()
    demanda.loc[0, "pasos_vehiculo"] = 100
    salida = repartir_cupo_global(demanda, 500)
    assert salida["cuota_teorica_coches_dia"].sum() == 100


def test_cupo_rechaza_sumar_salidas_y_ocultar_accesos_ausentes():
    d = pd.DataFrame({"fecha": ["2028-01-01", "2028-01-01", "2028-01-02"], "punto": ["a", "b", "a"], "pasos_vehiculo": [100] * 3})
    with pytest.raises(ValueError): repartir_cupo_global(d, 500)
    d = d.iloc[:2].assign(sentido="salida")
    with pytest.raises(ValueError): repartir_cupo_global(d, 500)


def test_reparto_manual_no_reasigna_cupo_no_utilizado():
    d = pd.DataFrame({"fecha": ["2028-01-01"] * 4, "punto": ["a", "b", "c", "d"], "pasos_vehiculo": [100, 200, 300, 400]})
    salida = repartir_cupo_global(d, 500, pesos={p: .25 for p in ["a", "b", "c", "d"]})
    assert salida["cuota_teorica_coches_dia"].tolist() == [100, 125, 125, 125]
    assert salida["cuota_teorica_coches_dia"].sum() == 475
    with pytest.raises(ValueError): repartir_cupo_global(d, 500, pesos={"a": 1})
    with pytest.raises(ValueError): repartir_cupo_global(d, 500, pesos={p: .3 for p in ["a", "b", "c", "d"]})


def ejemplo_anualizacion_visor():
    # Datos sintéticos solo para verificar el cálculo, no representan el Teide.
    tipos=['Laborable','Sábado','Domingo'];meses=['Marzo','Julio','Octubre']
    indices=pd.DataFrame([{'matrix_index':3*m+t,'anio':2025,'mes_publicado':mes,'tipo_dia_publicado':tipo}
        for m,mes in enumerate(meses) for t,tipo in enumerate(tipos)])
    colectivos=['extranjero','espana_no_tenerife','tenerife_no_frecuente','tenerife_resto']
    perfiles=pd.DataFrame([dict(matrix_index=i,access_corridor='prueba',direccion=s,hora_servicio=9,
        **{c:float(1+2*(i//3)) for c in colectivos}) for i in range(9) for s in ['subida','bajada']])
    return perfiles,indices,{c:.25 for c in colectivos}


def test_anualizacion_media_meses_y_calendario_real_antes_del_percentil():
    from movilidad_teide.actividad import anualizar_referencias_visor
    a=ejemplo_anualizacion_visor()
    for year,days in [(2025,365),(2028,366)]:
        r=anualizar_referencias_visor(*a,anio_base=2025,anio_calendario=year,criterio='Media de meses 2025 por tipo de día')
        t=r['demanda_anual_referencia_visor'];assert t.viajes_persona_anuales_referencia.eq(3*days).all()
        assert t.viajes_persona_captables_anuales_referencia.eq(.75*days).all()
        assert t.coches_sustituidos_anuales.isna().all()
        assert r['calendario_anualizacion'].dias_calendario.sum()==days
        assert r['calendario_anualizacion'].mes_con_referencia_2025.sum()==9


@pytest.mark.parametrize('criterio',[None,'Sin anualizar'])
def test_anualizacion_pendiente_no_produce_cero(criterio):
    from movilidad_teide.actividad import anualizar_referencias_visor
    r=anualizar_referencias_visor(*ejemplo_anualizacion_visor(),anio_base=2025,anio_calendario=2028,criterio=criterio)
    assert r['demanda_anual_referencia_visor'].viajes_persona_anuales_referencia.isna().all()


@pytest.mark.parametrize('defecto',['indice_repetido','mes_ausente','perfil_repetido','sentido_ausente',
    'demanda_negativa','demanda_ausente','captacion_excesiva','colectivo_ausente','criterio_desconocido'])
def test_anualizacion_rechaza_perdidas_y_valores_no_fisicos(defecto):
    from movilidad_teide.actividad import anualizar_referencias_visor
    p,i,c=ejemplo_anualizacion_visor();criterio='Media de meses 2025 por tipo de día'
    if defecto=='indice_repetido':i.loc[1,'matrix_index']=0
    elif defecto=='mes_ausente':i=i.iloc[:-1].copy()
    elif defecto=='perfil_repetido':p=pd.concat([p,p.iloc[[0]]],ignore_index=True)
    elif defecto=='sentido_ausente':p=p.iloc[1:].copy()
    elif defecto=='demanda_negativa':p.loc[0,'extranjero']=-1
    elif defecto=='demanda_ausente':p.loc[0,'extranjero']=np.nan
    elif defecto=='captacion_excesiva':c['extranjero']=1.1
    elif defecto=='colectivo_ausente':c.pop('extranjero')
    else:criterio='Desconocido'
    with pytest.raises(ValueError):anualizar_referencias_visor(p,i,c,anio_base=2025,anio_calendario=2028,criterio=criterio)


def test_anualizacion_separa_captacion_fuera_de_ventana_sin_borrar_demanda():
    from movilidad_teide.actividad import anualizar_referencias_visor
    r=anualizar_referencias_visor(*ejemplo_anualizacion_visor(),anio_base=2025,anio_calendario=2025,
        criterio='Media de meses 2025 por tipo de día',hora_inicio=10,hora_fin=19)
    t=r['demanda_anual_referencia_visor']
    assert t.viajes_persona_anuales_referencia.eq(1095).all()
    assert t.viajes_persona_captables_anuales_referencia.eq(0).all()
    assert t.viajes_persona_captables_anuales_fuera_ventana.eq(273.75).all()


def ejemplo_historico_personas():
    # Serie sintética de prueba, con crecimiento conocido y sin datos del Teide.
    perfiles,indices,captacion=ejemplo_anualizacion_visor();ps=[];ii=[]
    for y in range(2022,2026):
        p=perfiles.copy();i=indices.copy();i['formato_publicado']='Formato 2025';p['matrix_index']+=9*(y-2022);i['matrix_index']+=9*(y-2022);i['anio']=y
        for c in captacion:p[c]*=1.02**(y-2022)
        ps.append(p);ii.append(i)
    return pd.concat(ps,ignore_index=True),pd.concat(ii,ignore_index=True),captacion


def test_tendencia_personas_compara_mismos_periodos_y_calendario():
    from movilidad_teide.actividad import comparar_tendencias_personas_visor
    p,i,c=ejemplo_historico_personas();r=comparar_tendencias_personas_visor(p,i,c)
    t=r['tendencias_personas_visor'];assert len(t)==20
    assert np.allclose(t.tasa_anual,.02,rtol=0,atol=1e-12)
    assert t.loc[t.metodo.eq('cagr_2022_2025'),'anios_utilizados'].eq('2022,2025').all()
    assert t.loc[t.metodo.eq('cagr_2023_2025'),'anios_utilizados'].eq('2023,2025').all()
    assert r['cobertura_matrices_tendencia_personas'].utilizado_en_ajuste.all()


@pytest.mark.parametrize('defecto',['anio_ausente','mes_duplicado','indice_repetido','demanda_negativa'])
def test_tendencia_rechaza_comparabilidad_incompleta(defecto):
    from movilidad_teide.actividad import comparar_tendencias_personas_visor
    p,i,c=ejemplo_historico_personas()
    if defecto=='anio_ausente':i=i.loc[i.anio.ne(2024)]
    elif defecto=='mes_duplicado':i.loc[1,['mes_publicado','tipo_dia_publicado']]=i.loc[0,['mes_publicado','tipo_dia_publicado']]
    elif defecto=='indice_repetido':i.loc[1,'matrix_index']=0
    else:p.loc[0,'extranjero']=-1
    with pytest.raises(ValueError):comparar_tendencias_personas_visor(p,i,c)


def test_tendencia_no_anualiza_2026_parcial_y_conserva_colectivo_nulo():
    from movilidad_teide.actividad import comparar_tendencias_personas_visor
    p,i,c=ejemplo_historico_personas();extra=i.iloc[[0]].assign(anio=2026,matrix_index=99)
    i=pd.concat([i,extra],ignore_index=True);p['tenerife_resto']=0
    r=comparar_tendencias_personas_visor(p,i,c)
    assert not r['cobertura_matrices_tendencia_personas'].loc[lambda x:x.anio.eq(2026),'utilizado_en_ajuste'].item()
    assert r['tendencias_personas_visor'].loc[lambda x:x.colectivo.eq('tenerife_resto'),'tasa_anual'].isna().all()


def ejemplo_proyeccion_personas():
    from movilidad_teide.actividad import anualizar_referencias_visor,comparar_tendencias_personas_visor
    p,i,c=ejemplo_historico_personas();r=anualizar_referencias_visor(p,i,c,anio_base=2025,anio_calendario=2028,criterio='Media de meses 2025 por tipo de día')
    return r['demanda_anual_referencia_visor'],comparar_tendencias_personas_visor(p,i,c)['tendencias_personas_visor']


def test_proyeccion_tasa_comun_anclada_2025_sin_repetir_calendario():
    from movilidad_teide.actividad import proyectar_personas_desde_referencia
    r,t=ejemplo_proyeccion_personas();out=proyectar_personas_desde_referencia(r,t,'Ajuste comparable del Visor 2022–2025',2028)
    pd.testing.assert_frame_equal(out[r.columns],r)
    assert np.allclose(out.factor_crecimiento_personas,1.02**3)
    assert np.allclose(out.viajes_persona_proyectados,r.viajes_persona_anuales_referencia*1.02**3)
    assert out.coches_sustituidos_anuales.isna().all()
    t.loc[t.colectivo.eq('total_sistema')&t.metodo.eq('ajuste_2022_2025'),'tasa_anual']=-.1
    out=proyectar_personas_desde_referencia(r,t,'Ajuste comparable del Visor 2022–2025',2028)
    assert np.allclose(out.factor_crecimiento_personas,.9**3)


@pytest.mark.parametrize('metodo',[None,'Sin crecimiento'])
def test_proyeccion_distingue_pendiente_y_constancia(metodo):
    from movilidad_teide.actividad import proyectar_personas_desde_referencia
    r,t=ejemplo_proyeccion_personas();out=proyectar_personas_desde_referencia(r,t,metodo,2028)
    if metodo is None:assert out.viajes_persona_proyectados.isna().all()
    else:assert np.allclose(out.viajes_persona_proyectados,r.viajes_persona_anuales_referencia)


@pytest.mark.parametrize('defecto',['tasa_ausente','tasa_repetida','tasa_menor_menos_uno','referencia_duplicada','criterio_inventado'])
def test_proyeccion_rechaza_tasas_y_referencias_invalidas(defecto):
    from movilidad_teide.actividad import proyectar_personas_desde_referencia
    r,t=ejemplo_proyeccion_personas();metodo='Ajuste comparable del Visor 2022–2025';mask=t.colectivo.eq('total_sistema')&t.metodo.eq('ajuste_2022_2025')
    if defecto=='tasa_ausente':t.loc[mask,'tasa_anual']=np.nan
    elif defecto=='tasa_repetida':t=pd.concat([t,t.loc[mask]],ignore_index=True)
    elif defecto=='tasa_menor_menos_uno':t.loc[mask,'tasa_anual']=-1
    elif defecto=='referencia_duplicada':r=pd.concat([r,r.iloc[[0]]],ignore_index=True)
    else:metodo='Inventado'
    with pytest.raises(ValueError):proyectar_personas_desde_referencia(r,t,metodo,2028)


def ejemplo_horario_personas():
    p,i,c=ejemplo_anualizacion_visor();p=p.drop(columns='hora_servicio').merge(pd.DataFrame({'hora_servicio':range(24)}),how='cross')
    for col in c:p[col]/=24
    return p,i,c


def test_desglose_horario_conserva_exterior_y_no_afirma_llegadas():
    from movilidad_teide.actividad import desglosar_captacion_horaria_visor
    r=desglosar_captacion_horaria_visor(*ejemplo_horario_personas(),anio_base=2025,hora_inicio=7,hora_fin=19)
    assert len(r)==192 and r.en_ventana_diseno.sum()==13*8
    assert r.limite_temporal.str.contains('P029',regex=False).all()
    # 11 de los 24 bloques quedan fuera de la ventana inclusiva de 7 a 19.
    assert np.isclose(r.loc[~r.en_ventana_diseno].captables_anuales.sum(),3*365*.25*8*11/24)


def test_desglose_horario_rechaza_horas_ausentes():
    from movilidad_teide.actividad import desglosar_captacion_horaria_visor
    p,i,c=ejemplo_horario_personas();p=p.loc[~(p.matrix_index.eq(0)&p.direccion.eq('subida')&p.hora_servicio.eq(0))]
    with pytest.raises(ValueError):desglosar_captacion_horaria_visor(p,i,c,anio_base=2025,hora_inicio=7,hora_fin=19)


def test_desglose_conserva_hora_siempre_sin_registros_como_ausencia():
    from movilidad_teide.actividad import desglosar_captacion_horaria_visor
    p,i,c=ejemplo_horario_personas();p=p.loc[~(p.direccion.eq('subida')&p.hora_servicio.eq(23))]
    r=desglosar_captacion_horaria_visor(p,i,c,anio_base=2025,hora_inicio=7,hora_fin=19)
    missing=r.loc[r.direccion.eq('subida')&r.hora_servicio.eq(23)]
    assert len(missing)==4 and not missing.valor_publicado_disponible.any()
    assert missing[['viajes_persona_anuales','captables_anuales']].isna().all().all()


def test_proyeccion_exportable_con_indice_original_desplazado():
    from movilidad_teide.actividad import proyectar_personas_desde_referencia
    r,t=ejemplo_proyeccion_personas();r.index=pd.RangeIndex(32,32+len(r))
    out=proyectar_personas_desde_referencia(r,t,'Ajuste comparable del Visor 2022–2025',2028)
    assert out.index.equals(pd.RangeIndex(len(out)))
    pd.testing.assert_frame_equal(out[r.columns],r.reset_index(drop=True))


def ejemplo_contraste_escalas():
    # Cantidades sintéticas de prueba, sin usar datos del proyecto.
    personas=pd.DataFrame([{'anio':y,'access_corridor':p,'direccion':d,'viajes_persona_anuales':100.}
        for y in [2025,2028] for p in ['norte','sur'] for d in ['subida','bajada']])
    coches=personas.rename(columns={'access_corridor':'punto'}).drop(columns='viajes_persona_anuales')
    coches['punto']=coches.punto.map({'norte':'N','sur':'S'});coches['pasos_coche']=80.
    corredores=[{'corredor':'norte','aforo':'N','nombre':'Norte'},{'corredor':'sur','aforo':'S','nombre':'Sur'}]
    return personas,coches,corredores


def test_contraste_escala_conserva_saldos_negativos_sin_calibrar():
    from movilidad_teide.actividad import contrastar_escala_personas_aforos
    p,c,g=ejemplo_contraste_escalas();r=contrastar_escala_personas_aforos(p,c,g,ocupacion_referencia=3.2)
    assert len(r)==12 and not r.comparabilidad_validada.any()
    assert r.coches_sustituidos_anuales.isna().all()
    assert np.allclose(r.cociente_personas_por_paso_no_ocupacion,1.25)
    assert np.allclose(r.relacion_entre_escalas_no_factor_de_calibracion,100/256)
    assert not r.prueba_mismo_ambito_no_descartada.any()
    own=r.loc[r.access_corridor.ne('total_parque')];assert own.saldo_personas_menos_prueba_coches.eq(-156).all()
    globales=r.loc[r.access_corridor.eq('total_parque')];assert globales.viajes_persona_anuales.eq(200).all()
    assert globales.pasos_coche.eq(160).all() and globales.saldo_personas_menos_prueba_coches.eq(-312).all()
    pd.testing.assert_frame_equal(p,ejemplo_contraste_escalas()[0])


def test_contraste_no_confunde_saldo_positivo_con_ambito_validado():
    from movilidad_teide.actividad import contrastar_escala_personas_aforos
    r=contrastar_escala_personas_aforos(*ejemplo_contraste_escalas(),ocupacion_referencia=1)
    assert r.prueba_mismo_ambito_no_descartada.all() and not r.comparabilidad_validada.any()


def test_contraste_preserva_ausencias_y_ceros_sin_dividir_por_cero():
    from movilidad_teide.actividad import contrastar_escala_personas_aforos
    p,c,g=ejemplo_contraste_escalas();p.loc[0,'viajes_persona_anuales']=np.nan;c.loc[1,'pasos_coche']=0
    r=contrastar_escala_personas_aforos(p,c,g)
    assert r.personas_en_coches_si_coincidieran_ambitos.isna().all()
    assert r.loc[r.anio.eq(2025)&r.direccion.eq('subida')&r.access_corridor.eq('total_parque'),'viajes_persona_anuales'].isna().all()
    assert r.loc[r.anio.eq(2025)&r.direccion.eq('bajada')&r.access_corridor.eq('norte'),'cociente_personas_por_paso_no_ocupacion'].isna().all()


@pytest.mark.parametrize('defecto',['persona_duplicada','coche_duplicado','acceso_ausente','sentido_ausente',
    'aforo_repetido','personas_negativas','coches_infinitos','ocupacion_menor_uno'])
def test_contraste_rechaza_claves_incompletas_y_valores_no_fisicos(defecto):
    from movilidad_teide.actividad import contrastar_escala_personas_aforos
    p,c,g=ejemplo_contraste_escalas();occ=3.2
    if defecto=='persona_duplicada':p=pd.concat([p,p.iloc[[0]]],ignore_index=True)
    elif defecto=='coche_duplicado':c=pd.concat([c,c.iloc[[0]]],ignore_index=True)
    elif defecto=='acceso_ausente':p=p.iloc[1:].copy()
    elif defecto=='sentido_ausente':c=c.loc[c.direccion.ne('bajada')]
    elif defecto=='aforo_repetido':g[1]['aforo']='N'
    elif defecto=='personas_negativas':p.loc[0,'viajes_persona_anuales']=-1
    elif defecto=='coches_infinitos':c.loc[0,'pasos_coche']=np.inf
    else:occ=.9
    with pytest.raises(ValueError):contrastar_escala_personas_aforos(p,c,g,ocupacion_referencia=occ)


def test_formato_publicado_se_enlaza_por_nombre_no_por_posicion():
    from movilidad_teide.actividad import adjuntar_formato_publicado
    i=pd.DataFrame({'matrix_index':[8,3],'matriz_publicada':['A','B'],'anio':[2022,2025]})
    c=pd.DataFrame({'Matriz':['B','A'],'Año':[2025,2022],'Versión':['Formato 2025','Formato 2021']})
    out=adjuntar_formato_publicado(i,c)
    pd.testing.assert_frame_equal(out[i.columns],i)
    assert out.formato_publicado.tolist()==['Formato 2021','Formato 2025']


@pytest.mark.parametrize('defecto',['nombre_repetido','anio_distinto','formato_desconocido','nombre_ausente'])
def test_formato_no_se_infiere_sin_catalogo_inequivoco(defecto):
    from movilidad_teide.actividad import adjuntar_formato_publicado
    i=pd.DataFrame({'matrix_index':[8,3],'matriz_publicada':['A','B'],'anio':[2022,2025]})
    c=pd.DataFrame({'Matriz':['A','B'],'Año':[2022,2025],'Versión':['Formato 2021','Formato 2025']})
    if defecto=='nombre_repetido':c.loc[1,'Matriz']='A'
    elif defecto=='anio_distinto':c.loc[0,'Año']=2025
    elif defecto=='formato_desconocido':c.loc[0,'Versión']='Desconocido'
    else:i.loc[0,'matriz_publicada']='C'
    with pytest.raises(ValueError):adjuntar_formato_publicado(i,c)


def ejemplo_formatos_mixtos():
    p,i,c=ejemplo_historico_personas()
    i.loc[i.anio.eq(2022)|(i.anio.eq(2023)&i.mes_publicado.eq('Marzo')),'formato_publicado']='Formato 2021'
    return p,i,c


def test_tendencias_mixtas_quedan_diagnosticadas_sin_aplicacion():
    from movilidad_teide.actividad import comparar_tendencias_personas_visor
    t=comparar_tendencias_personas_visor(*ejemplo_formatos_mixtos())['tendencias_personas_visor']
    assert not t.loc[t.metodo.ne('cagr_2024_2025_mismo_formato'),'aplicable_mismo_formato'].any()
    assert t.loc[t.metodo.eq('cagr_2024_2025_mismo_formato'),'aplicable_mismo_formato'].all()


@pytest.mark.parametrize('metodo',['Ajuste comparable del Visor 2022–2025','Tasa compuesta del Visor 2022–2025','Tasa compuesta del Visor 2023–2025'])
def test_proyeccion_rechaza_una_tasa_entre_formatos(metodo):
    from movilidad_teide.actividad import comparar_tendencias_personas_visor,proyectar_personas_desde_referencia
    reference,_=ejemplo_proyeccion_personas();t=comparar_tendencias_personas_visor(*ejemplo_formatos_mixtos())['tendencias_personas_visor']
    with pytest.raises(ValueError,match='mezcla formatos'):proyectar_personas_desde_referencia(reference,t,metodo,2028)


def test_proyeccion_comparable_usa_solo_intervalo_homogeneo():
    from movilidad_teide.actividad import comparar_tendencias_personas_visor,proyectar_personas_desde_referencia
    ref,_=ejemplo_proyeccion_personas();t=comparar_tendencias_personas_visor(*ejemplo_formatos_mixtos())['tendencias_personas_visor']
    out=proyectar_personas_desde_referencia(ref,t,'Tasa comparable del Visor 2024–2025',2028)
    assert np.allclose(out.tasa_anual_personas,.02,atol=1e-12,rtol=0)
    assert np.allclose(out.factor_crecimiento_personas,1.02**3,atol=1e-12,rtol=0)


def ejemplo_ambito_od_visor():
    # Datos sintéticos: IDs API arbitrarios y distintos de los índices del simulador.
    p,i,c=ejemplo_anualizacion_visor();i['formato_publicado']='Formato 2025';queries=[];rows=[]
    ids=[753,6,301,88,1002,59,42,703,915]
    for r in i.itertuples():
        for sense,direction in [('hacia_teide','subida'),('desde_teide','bajada')]:
            value=p.loc[p.matrix_index.eq(r.matrix_index)&p.direccion.eq(direction),list(c)].sum().sum()
            origin,dest=(1,187) if sense=='hacia_teide' else (187,1)
            common={'id_matriz':ids[r.matrix_index],'anio':2025,'sentido':sense,'modo':'todos_modos'}
            rows.extend([dict(common,origen=origin,destino=dest,viajes=value),dict(common,origen=187,destino=222,viajes=2.)])
            queries.append(dict(common,mes={'Marzo':3,'Julio':7,'Octubre':10}[r.mes_publicado],tipo_dia={'Laborable':'laborable','Sábado':'sabado','Domingo':'domingo'}[r.tipo_dia_publicado],viajes_total=value+2,viajes_internos=2.,viajes_externos=value,fuente='prueba_sintetica'))
    return pd.DataFrame(queries),pd.DataFrame(rows),p,i


def test_ambito_separa_internos_y_no_suma_fuentes():
    from movilidad_teide.actividad import contrastar_ambito_od_visor
    r=contrastar_ambito_od_visor(*ejemplo_ambito_od_visor())
    assert len(r)==18 and r.coincidencia_numerica.all()
    assert r.internos_verificados.eq(2).all() and np.allclose(r.viajes_visor,r.externos_verificados)
    assert r.id_matriz.ne(r.matrix_index).all()
    assert not r.expansion_y_equivalencia_con_aforos_validadas.any()


@pytest.mark.parametrize('defecto',['consulta_ausente','consulta_repetida','relacion_repetida','internos_alterados','extremo_fuera','periodo_distinto'])
def test_ambito_rechaza_perdidas_y_filtros_incompatibles(defecto):
    from movilidad_teide.actividad import contrastar_ambito_od_visor
    q,r,p,i=ejemplo_ambito_od_visor()
    if defecto=='consulta_ausente':q=q.iloc[1:].copy()
    elif defecto=='consulta_repetida':q=pd.concat([q,q.iloc[[0]]],ignore_index=True)
    elif defecto=='relacion_repetida':r=pd.concat([r,r.iloc[[0]]],ignore_index=True)
    elif defecto=='internos_alterados':q.loc[0,'viajes_internos']=3
    elif defecto=='extremo_fuera':r.loc[0,'destino']=99
    else:q.loc[0,'mes']=4
    with pytest.raises(ValueError):contrastar_ambito_od_visor(q,r,p,i)


def test_ambito_conserva_diferencia_y_no_agrega_privado_como_demanda_extra():
    from movilidad_teide.actividad import contrastar_ambito_od_visor
    q,r,p,i=ejemplo_ambito_od_visor();p.loc[0,'extranjero']+=1
    privado=r.copy();privado['modo']='privado';privado['viajes']*=.5
    out=contrastar_ambito_od_visor(q,pd.concat([r,privado],ignore_index=True),p,i)
    assert np.isclose(out.diferencia_visor_menos_od_externo.sum(),1)
    assert out.coincidencia_numerica.sum()==17
    assert not out.expansion_y_equivalencia_con_aforos_validadas.any()


@pytest.fixture
def captacion_para_conversion():
    # Magnitudes analíticas para probar unidades; nunca se exportan como datos del estudio.
    return pd.DataFrame([
        dict(access_corridor='A',direccion='subida',colectivo='uno',anio_calendario=2028,
             viajes_persona_proyectados=2000.,viajes_persona_captables_proyectados=1000.),
        dict(access_corridor='A',direccion='subida',colectivo='dos',anio_calendario=2028,
             viajes_persona_proyectados=1000.,viajes_persona_captables_proyectados=500.),
        dict(access_corridor='A',direccion='bajada',colectivo='uno',anio_calendario=2028,
             viajes_persona_proyectados=1600.,viajes_persona_captables_proyectados=800.)])


def test_conversion_anual_unidades_y_sentidos(captacion_para_conversion):
    from movilidad_teide.actividad import convertir_captacion_anual_a_coches
    a=captacion_para_conversion;prev=a.copy(deep=True)
    c=convertir_captacion_anual_a_coches(a,ocupacion=3.2,fraccion_desde_coche=.7387)
    detalle=c['detalle'];s=c['por_corredor_sentido'].set_index('direccion')
    assert detalle.iloc[0].recorridos_coche_equivalentes_condicionados==pytest.approx(230.84375)
    assert s.loc['subida','recorridos_coche_equivalentes_condicionados']==pytest.approx(346.265625)
    assert s.loc['bajada','recorridos_coche_equivalentes_condicionados']==pytest.approx(184.675)
    assert c['coherencia_sentidos'].iloc[0].diferencia_subida_menos_bajada==pytest.approx(161.590625)
    assert c['coherencia_sentidos'].visitas_ida_vuelta_identificadas.isna().all()
    assert detalle[['coches_efectivamente_sustituidos','coches_alimentacion_cabecera']].isna().all().all()
    assert np.allclose(detalle.viajes_persona_captables_origen_coche+detalle.viajes_persona_captables_otro_origen_modal,
                       a.viajes_persona_captables_proyectados)
    pd.testing.assert_frame_equal(a,prev)


@pytest.mark.parametrize('ocupacion,fraccion',[(None,None),(3.2,None),(None,.7387)])
def test_conversion_pendiente_no_imputa_ceros(captacion_para_conversion,ocupacion,fraccion):
    from movilidad_teide.actividad import convertir_captacion_anual_a_coches
    c=convertir_captacion_anual_a_coches(captacion_para_conversion,ocupacion=ocupacion,fraccion_desde_coche=fraccion)
    assert c['detalle'].recorridos_coche_equivalentes_condicionados.isna().all()
    assert c['por_corredor_sentido'].recorridos_coche_equivalentes_condicionados.isna().all()


def test_conversion_faltante_no_se_oculta_en_subtotal(captacion_para_conversion):
    from movilidad_teide.actividad import convertir_captacion_anual_a_coches
    a=captacion_para_conversion;a.loc[0,'viajes_persona_captables_proyectados']=np.nan
    c=convertir_captacion_anual_a_coches(a,ocupacion=3.2,fraccion_desde_coche=.7387)
    s=c['por_corredor_sentido'].set_index('direccion')
    assert pd.isna(s.loc['subida','recorridos_coche_equivalentes_condicionados'])
    assert s.loc['bajada','recorridos_coche_equivalentes_condicionados']==pytest.approx(184.675)


@pytest.mark.parametrize('ocupacion,fraccion',[(0,.7),(.8,.7),(True,.7),(3.2,-.1),(3.2,1.1),(3.2,True),(3.2,float('inf'))])
def test_conversion_rechaza_parametros_no_fisicos(captacion_para_conversion,ocupacion,fraccion):
    from movilidad_teide.actividad import convertir_captacion_anual_a_coches
    with pytest.raises(ValueError):
        convertir_captacion_anual_a_coches(captacion_para_conversion,ocupacion=ocupacion,fraccion_desde_coche=fraccion)


@pytest.mark.parametrize('cambio',['duplicado','negativo','captacion_excesiva','sin_demanda','dos_anios','sentido_invalido'])
def test_conversion_rechaza_demanda_incoherente(captacion_para_conversion,cambio):
    from movilidad_teide.actividad import convertir_captacion_anual_a_coches
    a=captacion_para_conversion
    if cambio=='duplicado':a=pd.concat([a,a.iloc[[0]]])
    elif cambio=='negativo':a.loc[0,'viajes_persona_captables_proyectados']=-1
    elif cambio=='captacion_excesiva':a.loc[0,'viajes_persona_captables_proyectados']=2100
    elif cambio=='sin_demanda':a.loc[0,'viajes_persona_proyectados']=np.nan
    elif cambio=='dos_anios':a.loc[0,'anio_calendario']=2027
    elif cambio=='sentido_invalido':a.loc[0,'direccion']='ida_vuelta'
    with pytest.raises(ValueError):convertir_captacion_anual_a_coches(a,ocupacion=3.2,fraccion_desde_coche=.7387)


def test_conversion_fraccion_cero_no_identifica_visitas(captacion_para_conversion):
    from movilidad_teide.actividad import convertir_captacion_anual_a_coches
    c=convertir_captacion_anual_a_coches(captacion_para_conversion.iloc[:1],ocupacion=3.2,fraccion_desde_coche=0)
    assert c['detalle'].recorridos_coche_equivalentes_condicionados.iloc[0]==0
    assert c['coherencia_sentidos'].recorridos_equivalentes_bajada.isna().all()
    assert c['coherencia_sentidos'].visitas_ida_vuelta_identificadas.isna().all()


@pytest.fixture
def aforos_para_reparto():
    # Caso de prueba analítico; sus valores no se usan en las salidas del estudio.
    filas=[]
    for punto,coches,guaguas in [('A',100.,5.),('B',10.,1.)]:
        for sentido in ['entrada','salida']:
            for tipo,total in [('coche',coches),('guagua',guaguas)]:
                filas.append(dict(anio=2024,punto=punto,sentido=sentido,tipo_vehiculo=tipo,
                    total_valores_fuente=total,medidas=8784,valores_presentes=8784,
                    horas_esperadas=8784,horas_ausentes=0,marcas_fuera_calendario=0,
                    valores_negativos=0,valores_ausentes=0,valores_decimales=0))
    return pd.DataFrame(filas)


def test_reparto_aforos_pondera_personas_y_separa_sentidos(aforos_para_reparto):
    from movilidad_teide.actividad import estimar_reparto_personas_aforos
    a=aforos_para_reparto;antes=a.copy(deep=True)
    c=estimar_reparto_personas_aforos(a,ocupacion_coche=3,ocupacion_guagua=30,anios=[2024],puntos=['A','B'])
    t=c['conjunto_por_sentido'];e=t.loc[t.sentido.eq('entrada')].iloc[0]
    assert e.pasos_coche==110 and e.pasos_guagua==6
    assert e.personas_paso_en_coche==330 and e.personas_paso_en_guagua==180
    assert e.fraccion_personas_paso_en_coche==pytest.approx(330/510)
    assert e.fraccion_pasos_vehiculo_coche==pytest.approx(110/116)
    assert e.fraccion_personas_paso_en_coche!=pytest.approx((300/450+30/60)/2)
    assert len(t)==2 and set(t.sentido)=={'entrada','salida'}
    assert t.procedencia_coche_de_captados.isna().all()
    assert not t.visitas_unicas_identificadas.any() and not t.clasificacion_modal_confirmada.any()
    pd.testing.assert_frame_equal(a,antes)


@pytest.mark.parametrize('coche,guagua',[(None,None),(3,None),(None,30)])
def test_reparto_ocupaciones_pendientes_sin_porcentaje(aforos_para_reparto,coche,guagua):
    from movilidad_teide.actividad import estimar_reparto_personas_aforos
    c=estimar_reparto_personas_aforos(aforos_para_reparto,ocupacion_coche=coche,ocupacion_guagua=guagua,anios=[2024],puntos=['A','B'])
    assert c['conjunto_por_sentido'].fraccion_personas_paso_en_coche.isna().all()
    assert c['por_acceso'].fraccion_personas_paso_en_guagua.isna().all()


@pytest.mark.parametrize('bandera',['horas_ausentes','valores_ausentes','valores_negativos','marcas_fuera_calendario'])
def test_reparto_incidencia_no_se_oculta_en_conjunto(aforos_para_reparto,bandera):
    from movilidad_teide.actividad import estimar_reparto_personas_aforos
    a=aforos_para_reparto;a.loc[0,bandera]=1
    c=estimar_reparto_personas_aforos(a,ocupacion_coche=3,ocupacion_guagua=30,anios=[2024],puntos=['A','B'])
    e=c['conjunto_por_sentido'].loc[lambda t:t.sentido.eq('entrada')].iloc[0]
    assert not e.conteos_aptos_para_contraste and pd.isna(e.personas_paso_estimadas)
    assert e.pasos_coche==110
    assert c['conjunto_por_sentido'].loc[lambda t:t.sentido.eq('salida'),'personas_paso_estimadas'].item()==510


def test_reparto_cero_y_decimales_no_inventa_ocupantes(aforos_para_reparto):
    from movilidad_teide.actividad import estimar_reparto_personas_aforos
    a=aforos_para_reparto;a.loc[a.sentido.eq('entrada'),'total_valores_fuente']=0.
    a.loc[(a.punto.eq('A')&a.sentido.eq('salida')&a.tipo_vehiculo.eq('coche')),'total_valores_fuente']=100.25
    c=estimar_reparto_personas_aforos(a,ocupacion_coche=3,ocupacion_guagua=30,anios=[2024],puntos=['A','B'])
    t=c['conjunto_por_sentido'].set_index('sentido')
    assert t.loc['entrada','personas_paso_estimadas']==0
    assert pd.isna(t.loc['entrada','fraccion_personas_paso_en_coche'])
    assert t.loc['salida','pasos_coche']==110.25
    assert t.loc['salida','personas_paso_en_coche']==330.75


@pytest.mark.parametrize('cambio',['categoria_ausente','duplicado','punto_ausente','categoria_extra','calidad_ausente'])
def test_reparto_rechaza_ambito_incompleto_o_ambiguo(aforos_para_reparto,cambio):
    from movilidad_teide.actividad import estimar_reparto_personas_aforos
    a=aforos_para_reparto
    if cambio=='categoria_ausente':a=a.iloc[1:]
    elif cambio=='duplicado':a=pd.concat([a,a.iloc[[0]]])
    elif cambio=='punto_ausente':a=a.loc[a.punto.eq('A')]
    elif cambio=='categoria_extra':a.loc[0,'tipo_vehiculo']='camion'
    elif cambio=='calidad_ausente':a=a.drop(columns='horas_ausentes')
    with pytest.raises(ValueError):estimar_reparto_personas_aforos(a,ocupacion_coche=3,ocupacion_guagua=30,anios=[2024],puntos=['A','B'])


@pytest.mark.parametrize('coche,guagua',[(0,30),(3,.5),(True,30),(3,float('inf'))])
def test_reparto_rechaza_ocupaciones_invalidas(aforos_para_reparto,coche,guagua):
    from movilidad_teide.actividad import estimar_reparto_personas_aforos
    with pytest.raises(ValueError):
        estimar_reparto_personas_aforos(aforos_para_reparto,ocupacion_coche=coche,ocupacion_guagua=guagua,anios=[2024],puntos=['A','B'])
