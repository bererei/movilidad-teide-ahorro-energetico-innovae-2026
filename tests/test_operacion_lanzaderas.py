"""Ejemplos sintéticos de circulación; no observaciones o validación del Teide."""
import numpy as np
import pandas as pd
import pytest
from movilidad_teide.operacion_lanzaderas import ErrorOperacion,programar_circulacion,incorporar_circulacion,proponer_tiempos,proponer_refuerzos,revisar_regresos,revisar_cadenas_interiores,coordinar_horarios,_cadenas_vehiculos


def fixture():
    summary=pd.DataFrame([{'punto':'INTERIOR','salidas_ida_dia':3,'salidas_vuelta_dia':3,
        'longitud_ida_km':10.,'longitud_vuelta_km':12.,'dias_operacion':366,
        'vehiculo_km_identificados_dia':66.,'vehiculo_km_identificados_anio':66*366,
        'base_distancias':'Recorridos del estudio'}])
    geo=pd.DataFrame([{'punto':'INTERIOR','sentido':s,'origen':a,'destino':b,'itinerary_id':'ruta_'+s}
        for s,a,b in [('ida','Boca Tauce','El Portillo'),('vuelta','El Portillo','Boca Tauce')]])
    deps=pd.DataFrame([{'sentido':s,'minuto_salida_local':m} for s in ['ida','vuelta'] for m in [600.,620.,640.]])
    v={'regulacion_min':10.,'min_vuelta_interior':45.,'min_ida_interior':45.,
       'estancia_min_visita_min':120.,'distancias_actividad_lanzaderas':'Recorridos del estudio'}
    return summary,pd.DataFrame(),deps,geo,v


def test_circulacion_respetar_tiempos_regulacion_y_terminales():
    out=programar_circulacion(*fixture());m=out['movimientos']
    assert len(out['vehiculos'])==6
    assert len(m.loc[m.componente.eq('comercial')])==6
    assert set(out['vehiculos'].terminal_inicial)=={'Boca Tauce','El Portillo'}
    for _,b in m.groupby('vehiculo_id'):
        b=b.sort_values('salida_min')
        for i in range(1,len(b)):
            assert b.iloc[i].salida_min>=b.iloc[i-1].llegada_min+10-1e-9
            assert b.iloc[i].origen==b.iloc[i-1].destino
    assert out['regresos'].salida_regreso_compatible_local.isna().all()


def test_regresos_no_reutiliza_una_salida_y_no_asume_personas():
    args=list(fixture());args[2].loc[args[2].sentido.eq('vuelta'),'minuto_salida_local']=[780.,800.,820.]
    out=programar_circulacion(*args);back=out['regresos'].loc[lambda t:t.sentido_revisado.eq('ida')].salida_regreso_compatible_local
    assert back.notna().all() and not back.duplicated().any()
    assert all('Prueba de oferta' in x for x in out['regresos'].alcance)


def test_sin_estancia_no_inventa_una_visita_de_cero():
    args=list(fixture());args[4].update(estancia_min_visita_min=None,origen_oferta='Expediciones manuales',hora_inicio_acceso=10,hora_fin_acceso=10,tiempo_ida_OROTAVA_min=45.,tiempo_vuelta_OROTAVA_min=45.)
    args[0]['punto']='OROTAVA';args[3]['punto']='OROTAVA'
    out=programar_circulacion(*args)
    assert out['regresos'].estancia_revision_min.isna().all()
    assert out['regresos'].estado.str.contains('Sin criterio').all()


def test_mapear_sentidos_interiores_sin_intercambiar_duracion():
    args=list(fixture());args[4].update(min_ida_interior=20.,min_vuelta_interior=30.)
    m=programar_circulacion(*args)['movimientos']
    assert m.loc[m.sentido.eq('ida')].tiempo_recorrido_min.eq(30).all()
    assert m.loc[m.sentido.eq('vuelta')].tiempo_recorrido_min.eq(20).all()


def test_incorporar_vacios_por_horario_y_preservar_desconocidos():
    args=list(fixture());args[0].loc[0,['salidas_ida_dia','salidas_vuelta_dia']]=[3,1]
    args[2]=args[2].drop(index=[4,5])
    out=programar_circulacion(*args)
    unknown=pd.DataFrame([{'punto':'INTERIOR','sentido':'pendiente','componente':c,
        'recorridos_dia':np.nan,'vehiculo_km_anio':np.nan} for c in ['cocheras','vacios_adicionales_por_horario']])
    new=incorporar_circulacion({'resumen':args[0],'movimientos':unknown},out)
    s=new['resumen'].iloc[0]
    assert s.salidas_ida_dia+s.reposicion_modelada_ida_dia==s.salidas_vuelta_dia+s.reposicion_modelada_vuelta_dia
    assert new['movimientos'].loc[lambda t:t.sentido.eq('pendiente')].vehiculo_km_anio.isna().all()
    assert 'otros_vacios_no_modelizados' in set(new['movimientos'].componente)


@pytest.mark.parametrize('problem',['tiempo','regulacion','masa_salida','negativa','estancia','sentido'])
def test_rechazar_entradas_que_no_permiten_circulacion(problem):
    args=list(fixture())
    if problem=='tiempo':args[4]['min_vuelta_interior']=None
    elif problem=='regulacion':args[4]['regulacion_min']=-1
    elif problem=='masa_salida':args[0]['salidas_ida_dia']=args[0].salidas_ida_dia.astype(float);args[0].loc[0,'salidas_ida_dia']=2.5
    elif problem=='negativa':args[2].loc[0,'minuto_salida_local']=-1
    elif problem=='estancia':args[4]['estancia_min_visita_min']=-1
    elif problem=='sentido':args[3]=args[3].iloc[:1]
    with pytest.raises(ErrorOperacion):programar_circulacion(*args)


def test_cero_servicios_conserva_estructuras_vacias():
    args=list(fixture());args[0][['salidas_ida_dia','salidas_vuelta_dia']]=0
    args[2]=args[2].iloc[0:0]
    out=programar_circulacion(*args)
    assert out['movimientos'].empty and 'vehiculo_id' in out['vehiculos']


def test_proxies_se_distinguen_de_tiempos_programados_y_no_se_llaman_observados():
    geo=pd.DataFrame([{'punto':p,'sentido':s,'longitud_geografica_km':d}
        for p,d in [('OROTAVA',16.5),('VILAFLOR',15.),('INTERIOR',22.),('CHIO',29.),('LAGUNA',35.)] for s in ['ida','vuelta']])
    refs=pd.DataFrame([{'punto':p,'sentido':s,'duracion_programada_min':t}
        for p,t in [('OROTAVA',31.),('VILAFLOR',30.),('INTERIOR',44.)] for s in ['ida','vuelta']])
    out=proponer_tiempos(geo,refs)
    assert out.loc[out.punto.eq('OROTAVA')].tiempo_propuesto_min.eq(35).all()
    assert out.loc[out.punto.eq('CHIO')].metodo.str.contains('Proxy').all()
    assert out.loc[out.punto.eq('LAGUNA')].tiempo_propuesto_min.eq(70).all()


def test_interior_no_suma_otra_estancia_de_visita():
    args=list(fixture());args[2].loc[args[2].sentido.eq('vuelta'),'minuto_salida_local']=[660.,680.,700.]
    out=programar_circulacion(*args)['regresos'].loc[lambda t:t.sentido_revisado.eq('ida')]
    assert out.estancia_revision_min.isna().all()
    assert out.salida_regreso_compatible_local.notna().all()
    assert out.estado.str.contains('cota favorable').all()


def test_refuerzos_cierran_ambos_sentidos_sin_crear_nuevas_cohortes():
    args=list(fixture());args[4]['margen_enlace_interior_min']=10
    base=programar_circulacion(*args);extra=proponer_refuerzos(base['movimientos'],args[4])
    assert len(extra)==6 and set(extra.sentido)=={'ida','vuelta'}
    new=programar_circulacion(*args,refuerzos=extra)
    assert new['regresos'].id_salida_regreso.notna().all()
    assert len(new['regresos'])==6  # Solo las seis salidas iniciales, sin vuelta recursiva.
    pd.testing.assert_frame_equal(base['movimientos'].loc[lambda t:t.componente.eq('comercial'),['id_salida','salida_min']].sort_values('id_salida').reset_index(drop=True),
        new['movimientos'].loc[lambda t:t.componente.eq('comercial'),['id_salida','salida_min']].sort_values('id_salida').reset_index(drop=True))
    for _,b in new['regresos'].groupby(['punto','sentido_revisado']):assert not b.id_salida_regreso.duplicated().any()
    for _,b in new['movimientos'].groupby('vehiculo_id'):
        b=b.sort_values('salida_min');assert np.all(b.salida_min.to_numpy()[1:]>=b.llegada_min.to_numpy()[:-1]+10-1e-9)


def test_dos_guaguas_a_misma_hora_tienen_capacidad_distinta():
    args=list(fixture());base=programar_circulacion(*args)
    extra=pd.DataFrame([{'punto':'INTERIOR','sentido':'vuelta','salida_min':700.,'id_salida':'extra_1'},
                        {'punto':'INTERIOR','sentido':'vuelta','salida_min':700.,'id_salida':'extra_2'},
                        {'punto':'INTERIOR','sentido':'vuelta','salida_min':720.,'id_salida':'extra_3'}])
    out=programar_circulacion(*args,refuerzos=extra);rev=out['regresos'].loc[lambda t:t.sentido_revisado.eq('ida')]
    assert rev.id_salida_regreso.notna().all() and rev.id_salida_regreso.nunique()==3
    assert rev.salida_regreso_compatible_local.eq('11:40:00').sum()==2


def test_margen_interior_desplaza_refuerzo_sin_otra_estancia():
    args=list(fixture());m=programar_circulacion(*args)['movimientos']
    zero=proponer_refuerzos(m,args[4]);args[4]['margen_enlace_interior_min']=10
    ten=proponer_refuerzos(m,args[4])
    assert np.allclose(ten.salida_min-zero.salida_min,10)
    args[4]['estancia_min_visita_min']=240
    pd.testing.assert_frame_equal(ten,proponer_refuerzos(m,args[4]))


@pytest.mark.parametrize('fallo',['negativo','pendiente','duplicado','ajeno','sentido'])
def test_refuerzos_y_margen_incompatibles_se_rechazan(fallo):
    args=list(fixture());extra=proponer_refuerzos(programar_circulacion(*args)['movimientos'],args[4])
    if fallo=='negativo':args[4]['margen_enlace_interior_min']=-1
    elif fallo=='pendiente':args[4]['margen_enlace_interior_min']=None
    elif fallo=='duplicado':extra=pd.concat([extra,extra.iloc[:1]],ignore_index=True)
    elif fallo=='ajeno':extra.loc[0,'punto']='OTRO'
    else:extra.loc[0,'sentido']='otro'
    with pytest.raises(ErrorOperacion):programar_circulacion(*args,refuerzos=extra)


def test_refuerzos_se_suman_como_comerciales_y_no_vacios():
    args=list(fixture());base=programar_circulacion(*args);extra=proponer_refuerzos(base['movimientos'],args[4]);new=programar_circulacion(*args,refuerzos=extra)
    unknown=pd.DataFrame([{'punto':'INTERIOR','sentido':'pendiente','componente':'cocheras','vehiculo_km_dia':np.nan}])
    activity=incorporar_circulacion({'resumen':args[0],'movimientos':unknown},new);row=activity['resumen'].iloc[0]
    assert row.salidas_base_ida_dia==3 and row.salidas_base_vuelta_dia==3
    assert row.salidas_ida_dia==6 and row.salidas_vuelta_dia==6
    assert row.km_comerciales_dia==132 and row.km_comerciales_base_dia==66
    assert activity['movimientos'].loc[lambda t:t.componente.eq('cocheras')].vehiculo_km_dia.isna().all()
    assert np.isclose(activity['movimientos'].vehiculo_km_anio.sum(),row.vehiculo_km_identificados_anio)


def test_cadena_temporal_no_confunde_llegada_con_salida_ni_reserva_plazas():
    # Un acceso sintético llega al terminal A a10:00; el interior10:00 no sirve con10 min de enlace.
    args=list(fixture());base=programar_circulacion(*args)['movimientos'];v=dict(args[4],margen_enlace_interior_min=10)
    access=pd.DataFrame([dict(base.iloc[0],punto='OROTAVA',id_salida='acceso',componente='comercial',sentido='ida',origen='Cabecera',destino='Boca Tauce',salida_min=550.,llegada_min=600.,salida_local='09:10:00',llegada_local='10:00:00'),
        dict(base.iloc[0],punto='OROTAVA',id_salida='vuelta',componente='comercial',sentido='vuelta',origen='Boca Tauce',destino='Cabecera',salida_min=900.,llegada_min=950.,salida_local='15:00:00',llegada_local='15:50:00')])
    extra=proponer_refuerzos(base,v);all_moves=pd.concat([programar_circulacion(*args,refuerzos=extra)['movimientos'],access],ignore_index=True)
    chain=revisar_cadenas_interiores(all_moves,v).iloc[0]
    assert chain.primera_salida_interior_posible=='10:20:00'
    assert chain.espera_enlace_inmediato_min==20
    assert chain.estado=='Cadena temporal disponible; plazas no reservadas'
    assert 'no obligación' in chain.alcance


def referencia_coordinacion():
    # Oferta sintética con acceso a ambos terminales; no datos observados del Teide.
    args=list(fixture());inner=programar_circulacion(*args)['movimientos'];template=inner.iloc[0].to_dict();rows=[]
    for point,terminal,up,down,prefix in [('OROTAVA','El Portillo',35,25,'acceso'),('VILAFLOR','Boca Tauce',30,30,'sur')]:
        for sense,deps in [('ida',[420.,960.]),('vuelta',[660.,1140.])]:
            for i,dep in enumerate(deps):
                duration=up if sense=='ida' else down
                rows.append({**template,'punto':point,'sentido':sense,'id_salida':f'{prefix}_{sense}_{i}',
                    'salida_min':dep,'llegada_min':dep+duration,'tiempo_recorrido_min':duration,
                    'salida_local':f'{int(dep)//60:02d}:{int(dep)%60:02d}:00',
                    'origen':'Cabecera' if sense=='ida' else terminal,'destino':terminal if sense=='ida' else 'Cabecera'})
    return pd.concat([inner,pd.DataFrame(rows)],ignore_index=True),dict(args[4],hora_limite_bajada_parque=18.,espera_max_lanzadera_min=20.,margen_enlace_interior_min=10.,intervalo_minimo_subidas_min=30.)


def test_coordinacion_conserva_accesos_y_su_referencia_sin_inventar_demanda():
    m,v=referencia_coordinacion();c=coordinar_horarios(m,v,3)
    old=m.loc[m.punto.ne('INTERIOR')&m.componente.eq('comercial')]
    assert set(c['salidas'].loc[c['salidas'].punto.ne('INTERIOR')].id_salida)==set(old.id_salida)
    assert c['ajustes_acceso'].salida_referencia_min.tolist()==old.salida_min.tolist()
    assert c['ajustes_acceso'].adelanto_min.ge(0).all()
    late=c['ajustes_acceso'].loc[lambda t:t.id_salida.eq('acceso_ida_1')].iloc[0]
    assert late.salida_referencia_min==960 and late.salida_propuesta_min==925
    windows=pd.DataFrame(c['interior']).set_index('sentido')
    assert windows.primera_salida_visita_min.eq(470).all()
    assert windows.loc['ida','ultima_salida_visita_min']==950
    assert windows.loc['vuelta','ultima_salida_visita_min']==970
    assert windows.loc['ida','salidas_visita_por_sentido']==25 and windows.loc['vuelta','salidas_visita_por_sentido']==26


@pytest.mark.parametrize('problem',['limite','frecuencia','visita','espera'])
def test_coordinacion_inviable_no_elimina_oferta_ni_rellena_criterios(problem):
    m,v=referencia_coordinacion();freq=3
    if problem=='limite':v['hora_limite_bajada_parque']=7
    elif problem=='frecuencia':freq=0
    elif problem=='visita':v['estancia_min_visita_min']=None
    else:v['espera_max_lanzadera_min']=5
    with pytest.raises(ErrorOperacion):coordinar_horarios(m,v,freq)


def test_horario_explicito_no_puede_superar_cierre_ni_perder_capacidades():
    args=list(fixture());args[4].update(tratamiento_regresos='Horario coordinado',hora_limite_bajada_parque=18)
    proposed=pd.DataFrame([{'punto':'INTERIOR','sentido':'ida','salida_min':1140.,'id_salida':'tardia'}])
    with pytest.raises(ErrorOperacion,match='cierre'):programar_circulacion(*args,salidas_propuestas=proposed)
    args[0]['punto']='OROTAVA';args[3]['punto']='OROTAVA';args[4].update(tiempo_ida_OROTAVA_min=35.,tiempo_vuelta_OROTAVA_min=25.,origen_oferta='Expediciones manuales',hora_inicio_acceso=7,hora_fin_acceso=18)
    proposed['punto']='OROTAVA';proposed['salida_min']=900.
    with pytest.raises(ErrorOperacion,match='capacidades'):programar_circulacion(*args,salidas_propuestas=proposed)


def test_maximo_comun_no_fuerza_mismo_cierre_y_espacia_las_subidas():
    m,v=referencia_coordinacion();c=coordinar_horarios(m,v,3);limits=c['limites_acceso'].set_index('punto')
    assert limits.loc['OROTAVA','ultima_bajada_parque_min']==1080
    assert limits.loc['VILAFLOR','ultima_bajada_parque_min']==1065
    for _,b in c['salidas'].loc[lambda t:t.punto.ne('INTERIOR')&t.sentido.eq('ida')].groupby('punto'):
        assert np.diff(sorted(b.salida_min)).min()>=30-1e-9
    assert c['refuerzos'].salida_min.le(1080).all()


def test_cada_ultimo_interior_tiene_enlace_de_acceso_en_destino():
    m,v=referencia_coordinacion();c=coordinar_horarios(m,v,3);limits=c['limites_acceso'].set_index('punto')
    for sense,point in [('ida','OROTAVA'),('vuelta','VILAFLOR')]:
        extra=c['refuerzos'].loc[lambda t:t.punto.eq('INTERIOR')&t.sentido.eq(sense)]
        assert extra.salida_min.max()+45+10<=limits.loc[point,'ultima_bajada_parque_min']


@pytest.mark.parametrize('gap',[None,0,-1,2000])
def test_intervalo_inviable_no_comprime_silenciosamente_la_oferta(gap):
    m,v=referencia_coordinacion();v['intervalo_minimo_subidas_min']=gap
    with pytest.raises(ErrorOperacion):coordinar_horarios(m,v,3)


def test_cadenas_minimas_contraste_con_busqueda_exhaustiva_independiente():
    # Enumerar emparejamientos pequeños contrasta el algoritmo de flujo sin replicarlo.
    jobs=[{'sentido':sense,'salida_min':dep} for sense,dep in [('ida',0),('ida',12),('vuelta',17),('ida',35),('vuelta',50),('vuelta',68)]]
    duration={'ida':10.,'vuelta':12.};distance={'ida':4.,'vuelta':5.};reg=3.
    allowed={}
    for i,a in enumerate(jobs):
        end='B' if a['sentido']=='ida' else 'A'
        for j,b in enumerate(jobs):
            origin='A' if b['sentido']=='ida' else 'B';empty=end!=origin
            reverse='vuelta' if end=='B' else 'ida'
            ready=a['salida_min']+duration[a['sentido']]+reg+(duration[reverse]+reg if empty else 0)
            if i!=j and ready<=b['salida_min']:allowed[i,j]=distance[reverse] if empty else 0.
    best=[-1,float('inf')]
    def search(i,used,count,cost):
        if i==len(jobs):
            if count>best[0] or (count==best[0] and cost<best[1]):best[:]=[count,cost]
            return
        search(i+1,used,count,cost)
        for j in range(len(jobs)):
            if j not in used and (i,j) in allowed:search(i+1,used|{j},count+1,cost+allowed[i,j])
    search(0,set(),0,0.)
    chains=_cadenas_vehiculos(jobs,duration,distance,reg);links=[(a,b) for chain in chains for a,b in zip(chain,chain[1:])]
    assert len(chains)==len(jobs)-best[0]
    assert np.isclose(sum(allowed[x] for x in links),best[1])
    assert sorted(x for chain in chains for x in chain)==list(range(len(jobs)))


def test_plan_completo_reservas_recalcula_cadenas_y_rechaza_doble_refuerzo():
    args=list(fixture());base=programar_circulacion(*args)
    plan=base['movimientos'].loc[base['movimientos'].componente.eq('comercial')].copy()
    extra=plan.iloc[[0]].copy();extra['id_salida']='reserva_extra'
    plan=pd.concat([plan,extra],ignore_index=True)
    new=programar_circulacion(*args,salidas_propuestas=plan,plan_completo_reservas=True)
    assert set(new['movimientos'].loc[lambda t:t.componente.eq('comercial'),'id_salida'])==set(plan.id_salida)
    assert new['movimientos'].vehiculo_id.notna().all()
    with pytest.raises(ErrorOperacion):programar_circulacion(*args,plan_completo_reservas=True)
    with pytest.raises(ErrorOperacion):programar_circulacion(*args,salidas_propuestas=plan,
        refuerzos=plan.iloc[:0],plan_completo_reservas=True)
    with pytest.raises(ErrorOperacion):programar_circulacion(*args,salidas_propuestas=plan.loc[plan.sentido.eq('ida')],plan_completo_reservas=True)
