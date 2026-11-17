"""demanda: representacion. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import numpy as np
import pandas as pd
from movilidad_teide.demanda.asignacion_tipos import ErrorAsignacion
from movilidad_teide.demanda.asignacion_tipos import SENTIDOS


def normalizar_recorridos_estudio(catalogo, tablas, corredores):
    """Unificar longitudes ya verificadas, conservando la procedencia y los ejes.

    No lee ni edita geometrías. El llamador verifica las huellas de los productos.
    Los contrastes nominales D122 se mantienen fuera de esta selección.
    """
    grupos = ['origin_access_comparisons', 'study_origin_access_comparisons',
              'coastal_valley_comparisons']
    por_cabecera = {c['origin_anchor_id']: c for c in corredores}
    referencias, filas = {}, []
    for coleccion in grupos:
        for cid, ficha in catalogo.get(coleccion, {}).items():
            if cid in referencias or (coleccion, cid) not in tablas:
                raise ErrorAsignacion('Comparación repetida o sin tabla física verificada.')
            t = tablas[coleccion, cid].copy()
            if len(t) != 2 or set(t.sentido) != {'Hacia el Teide', 'Regreso'} or t.sentido.duplicated().any():
                raise ErrorAsignacion('Cada comparación necesita los dos sentidos, sin duplicados.')
            coastal = coleccion == 'coastal_valley_comparisons'
            parent = catalogo['origin_access_comparisons'][ficha['reused_comparison_id']] if coastal else ficha
            head = ficha['head_reference_anchor_id']
            if head not in por_cabecera or parent['head_reference_anchor_id'] != head:
                raise ErrorAsignacion('La comparación no identifica una cabecera compatible.')
            ref = dict(ficha, collection=coleccion, head_label=parent['head_label'],
                       terminal_label=parent['terminal_label'],
                       terminal_reference_anchor_id=(ficha.get('terminal_reference_anchor_id')
                                                     or ficha['terminal_axis_anchor_id']),
                       corredor=por_cabecera[head]['corredor'])
            referencias[cid] = ref
            direct_ids = ficha['directa_itinerary_ids'] if coastal else ficha['itinerary_ids']
            chain_ids = ficha['costera_itinerary_ids'] if coastal else ficha['itinerary_ids']
            for i, sentido in enumerate(['Hacia el Teide', 'Regreso']):
                r = t.loc[t.sentido.eq(sentido)].iloc[0]
                cols = (['directa_tf523_km','alimentador_costero_km','montana_km'] if coastal else
                        ['referencia_coche_hasta_terminal_km','acceso_cabecera_en_coche_si_se_elige_km',
                         'tramo_cabecera_terminal_km'])
                if not set(cols) <= set(t):
                    raise ErrorAsignacion('Faltan longitudes del recorrido.')
                values = r[cols].to_numpy(dtype=float)
                if not np.isfinite(values).all() or (values <= 0).any():
                    raise ErrorAsignacion('Las longitudes propias deben ser finitas y positivas.')
                direct, feeder, mountain = values
                chain = feeder + mountain
                if coastal:
                    published = r.cadena_costera_km
                elif ficha.get('geometry_mode') == 'independent_reference_and_feeders':
                    published = r.recorrido_encadenado_hasta_terminal_km
                else:
                    published = direct
                if not np.isfinite(published) or not np.isclose(chain,published,atol=1e-6,rtol=0):
                    raise ErrorAsignacion('La cadena no conserva sus dos componentes.')
                if not coastal and ('origen_id' not in t or r.origen_id != ficha['origin_id']
                                    or r.itinerary_id != direct_ids[i]):
                    raise ErrorAsignacion('La tabla física pertenece a otro origen o itinerario.')
                dspec = catalogo['itineraries'][direct_ids[i]]
                independent = ficha.get('geometry_mode') == 'independent_reference_and_feeders'
                cspec = catalogo['itineraries'][chain_ids[i]]
                mountain_ids = (catalogo['origin_access_comparisons'][ficha['reused_mountain_comparison_id']]['itinerary_ids']
                                if independent else chain_ids)
                if coastal:
                    hid = ficha['head_axis_anchor_ids'][i]
                else:
                    hid = ficha.get('head_axis_anchor_ids', {}).get(chain_ids[i],ficha['head_axis_anchor_id'])
                filas.append({'comparacion_id':cid,'origen_id':ficha['origin_id'],
                    'sentido':list(SENTIDOS.values())[i], 'coleccion_catalogo':coleccion,
                    'itinerario_referencia_id':direct_ids[i],
                    'itinerario_cadena_id':None if independent else chain_ids[i],
                    'itinerario_montana_referencia_id':mountain_ids[i],
                    'itinerario_alimentador_id':ficha.get('feeder_itinerary_ids',chain_ids)[i],
                    'origen_eje_anchor_id':dspec['destination_anchor_id' if i else 'origin_anchor_id'],
                    'cabecera_eje_anchor_id':hid,
                    'terminal_eje_anchor_id':cspec['origin_anchor_id' if i else 'destination_anchor_id'],
                    'directa_km':direct,'alimentador_km':feeder,'montana_km':mountain,
                    'cadena_km':chain,'desvio_cadena_menos_directa_km':chain-direct})
    return referencias, pd.DataFrame(filas)

def integrar_representacion_estudio(detalle, origenes, familias, demanda, zonas,
                                    proyecciones, referencias, longitudes, especificacion):
    """Relacionar fuente y estudio sin cambiar personas, zonas o pesos fuente.

    Las familias de estudio se separan cuando cambian cabecera o terminal. Reutilizo
    íntegro el control de extremos de cerrar_revision_geografica sobre una copia.
    Tener perfil propio no adopta modos, actividad anual, visitas o ahorro.
    """
    from movilidad_teide.demanda.asignacion import _valores
    from movilidad_teide.demanda.origenes import cerrar_revision_geografica
    valor = 'viajes_persona_media_57_matrices'
    ids = set(detalle.origen_id)
    if (detalle.origen_id.duplicated().any() or set(origenes.origen_id)!=ids
            or origenes.origen_id.duplicated().any() or familias.grupo_reducido_id.duplicated().any()
            or set(demanda.origen_id)!=ids
            or zonas.zona_id.duplicated().any() or set(zonas.origen_id)!=ids
            or not set(detalle.grupo_reducido_id)==set(familias.grupo_reducido_id)):
        raise ErrorAsignacion('La representación necesita orígenes, familias y zonas completos y únicos.')
    # Los pesos originales se verifican y conservan; los nuevos usan otro denominador explícito.
    _valores(demanda,[valor])
    esperado = demanda.groupby(['grupo_reducido_id','colectivo','sentido'])[valor].transform('sum')
    peso = demanda[valor]/esperado.where(esperado.ne(0))
    if (not np.allclose(demanda.demanda_grupo_misma_unidad,esperado,atol=1e-8,rtol=0)
            or not np.allclose(demanda.peso_origen_en_grupo_colectivo_sentido,peso,
                               atol=1e-10,rtol=0,equal_nan=True)):
        raise ErrorAsignacion('Los pesos o denominadores de la fuente no se conservan.')
    columns = ['origen_id','grupo_reducido_id','tratamiento_geografico',
               'comparacion_propia_id','candidato_revision_misma_familia']
    d = detalle[columns].copy()
    fuente = d[['origen_id','grupo_reducido_id']].rename(columns={'grupo_reducido_id':'grupo_fuente_id'})
    fuente = fuente.merge(origenes[['origen_id','corredor_candidato','cabecera_candidata']],
                          on='origen_id',validate='one_to_one').rename(columns={
                              'corredor_candidato':'corredor_fuente','cabecera_candidata':'cabecera_fuente'})
    if not demanda.grupo_reducido_id.eq(demanda.origen_id.map(fuente.set_index('origen_id').grupo_fuente_id)).all():
        raise ErrorAsignacion('La demanda no conserva la familia fuente de cada origen.')
    d['grupo_reducido_id'] = 'estudio__'+d.grupo_reducido_id
    nombres = {'estudio__'+r.grupo_reducido_id:r.nombre for r in familias.itertuples()}
    elegidas, cambiados = {}, set()
    grupos_nuevos = set()
    for group in especificacion.get('familias', []):
        gid = group['grupo_estudio_id']
        if (not gid or gid in nombres or gid in grupos_nuevos or not group.get('nombre')
                or not group.get('fundamento') or not group.get('referencias')):
            raise ErrorAsignacion('La familia propuesta requiere identificador, nombre y fundamento únicos.')
        grupos_nuevos.add(gid);nombres[gid]=group['nombre']
        for spec in group['referencias']:
            cid = spec['comparacion_id']
            if cid not in referencias or referencias[cid]['collection']!=spec['coleccion']:
                raise ErrorAsignacion('La propuesta necesita una referencia del catálogo disponible.')
            ref = referencias[cid];oid = ref['origin_id']
            if oid not in ids or oid in cambiados:
                raise ErrorAsignacion('Propuesta duplicada o con un origen ajeno a la fuente.')
            original = fuente.set_index('origen_id').loc[oid]
            if (original.corredor_fuente!=group['corredor_fuente_esperado']
                    or ref['corredor']!=group['corredor_estudio']):
                raise ErrorAsignacion('El corredor fuente o de estudio no coincide con la propuesta.')
            cambiados.add(oid);elegidas[oid]=(cid,group['fundamento'])
            mask = d.origen_id.eq(oid)
            d.loc[mask,'grupo_reducido_id']=gid
            d.loc[mask,'tratamiento_geografico']='referencia_trazada'
            d.loc[mask,'comparacion_propia_id']=cid
            d.loc[mask,'candidato_revision_misma_familia']=None
    refs = {}
    pertenencia = d.set_index('origen_id').grupo_reducido_id
    for r in d.loc[d.comparacion_propia_id.notna()].itertuples():
        cid = r.comparacion_propia_id
        if cid not in referencias or referencias[cid]['origin_id']!=r.origen_id:
            raise ErrorAsignacion('El perfil propio no corresponde al origen.')
        ref = dict(referencias[cid],reduced_group_id=pertenencia.loc[r.origen_id])
        if r.origen_id not in cambiados:
            original = fuente.set_index('origen_id').loc[r.origen_id]
            if ref['collection']!='origin_access_comparisons' or ref['corredor']!=original.corredor_fuente:
                raise ErrorAsignacion('Cambiar el corredor o usar un perfil propuesto requiere elección explícita.')
        refs[cid]=ref
    f = d.groupby('grupo_reducido_id',sort=True).size().rename('numero_subgrupos').reset_index()
    f['nombre']=f.grupo_reducido_id.map(nombres)
    for cid,ref in refs.items():
        parte=longitudes.loc[longitudes.comparacion_id.eq(cid)]
        if set(parte.origen_id)!={ref['origin_id']}:
            raise ErrorAsignacion('Las longitudes no corresponden al origen de su perfil.')
    montanas = longitudes.loc[longitudes.comparacion_id.isin(refs),
        ['comparacion_id','sentido','montana_km']].rename(columns={'montana_km':'tramo_cabecera_terminal_km'})
    # Este control sigue rechazando cabeceras/terminales incompatibles en una familia.
    cierre, ff, cobertura, estado = cerrar_revision_geografica(
        d,f,demanda[['origen_id','colectivo','sentido',valor]],proyecciones,refs,montanas)
    corr = fuente.merge(cierre,on='origen_id',validate='one_to_one').rename(columns={
        'grupo_reducido_id':'grupo_estudio_id','comparacion_propia_id':'comparacion_estudio_id',
        'perfil_completo_del_punto_disponible':'perfil_propio_estudio_disponible'})
    corr['corredor_estudio']=corr.corredor_fuente
    corr['cabecera_estudio']=corr.cabecera_montana_candidata.combine_first(corr.cabecera_fuente)
    corr['terminal_estudio']=corr.terminal_montana_candidata
    corr['cambio_geografico_para_estudio']=corr.origen_id.isin(cambiados)
    corr['fundamento_estudio']=corr.origen_id.map({k:v[1] for k,v in elegidas.items()}).fillna(
        'Conservar representación y piezas disponibles de la fuente; acceso propio y representatividad según diagnóstico.')
    for oid,(cid,_) in elegidas.items():corr.loc[corr.origen_id.eq(oid),'corredor_estudio']=refs[cid]['corredor']
    mapa = corr[['origen_id','grupo_fuente_id','grupo_estudio_id','corredor_fuente','cabecera_fuente',
                 'corredor_estudio','cabecera_estudio','terminal_estudio','comparacion_estudio_id',
                 'perfil_propio_estudio_disponible','cambio_geografico_para_estudio','fundamento_estudio']]
    z = zonas.merge(mapa.drop(columns='grupo_fuente_id'),on='origen_id',validate='many_to_one')
    if not z.grupo_reducido_id.eq(z.origen_id.map(fuente.set_index('origen_id').grupo_fuente_id)).all():
        raise ErrorAsignacion('La correspondencia de zonas no conserva sus familias fuente.')
    # Cada origen conserva dos filas de carretera; los accesos desconocidos siguen ausentes.
    carreteras = corr.merge(pd.DataFrame({'sentido':list(SENTIDOS.values())}),how='cross')
    carreteras = carreteras.merge(
            longitudes.rename(columns={'comparacion_id':'comparacion_estudio_id'}),
            on=['origen_id','comparacion_estudio_id','sentido'],how='left',validate='one_to_one')
    for sense in SENTIDOS.values():
        mask=carreteras.sentido.eq(sense)&~carreteras.perfil_propio_estudio_disponible
        carreteras.loc[mask,'montana_km']=carreteras.loc[mask,'longitud_montana_candidata_'+sense+'_km']
    propias=carreteras.loc[carreteras.perfil_propio_estudio_disponible]
    _valores(propias,['directa_km','alimentador_km','montana_km','cadena_km'])
    if propias[['directa_km','alimentador_km','montana_km','cadena_km']].le(0).any().any():
        raise ErrorAsignacion('Cada perfil propio necesita longitudes positivas en ambos sentidos.')
    desconocidos=~carreteras.perfil_propio_estudio_disponible
    if not carreteras.loc[desconocidos,['directa_km','alimentador_km','cadena_km']].isna().all().all():
        raise ErrorAsignacion('No copiar un perfil o rellenar accesos desconocidos.')
    pesos = demanda.merge(mapa,on='origen_id',validate='many_to_one')
    keys=['grupo_estudio_id','colectivo','sentido']
    pesos['demanda_grupo_estudio_media57']=pesos.groupby(keys)[valor].transform('sum')
    den=pesos.demanda_grupo_estudio_media57
    pesos['peso_origen_grupo_estudio_colectivo_sentido']=pesos[valor]/den.where(den.ne(0))
    # Comprobar conservación fila a fila y por colectivo/sentido, incluidos ceros y resto.
    pd.testing.assert_frame_equal(demanda.reset_index(drop=True),pesos[demanda.columns].reset_index(drop=True))
    for _,b in pesos.loc[den.gt(0)].groupby(keys):
        if not np.isclose(b.peso_origen_grupo_estudio_colectivo_sentido.sum(),1,atol=1e-10,rtol=0):
            raise ErrorAsignacion('Los pesos de estudio no suman uno en su propio denominador.')
    repartos=[]
    for (c,s),b in pesos.groupby(['colectivo','sentido']):
        a=b.groupby('corredor_fuente')[valor].sum();e=b.groupby('corredor_estudio')[valor].sum()
        for corredor in sorted(set(a.index)|set(e.index)):
            fa=float(a.get(corredor,0));es=float(e.get(corredor,0))
            repartos.append({'colectivo':c,'sentido':s,'corredor':corredor,
                'demanda_fuente_media57':fa,'demanda_estudio_media57':es,'diferencia_media57':es-fa})
    ff=ff.rename(columns={'grupo_reducido_id':'grupo_estudio_id'})
    ff['numero_zonas']=ff.grupo_estudio_id.map(z.groupby('grupo_estudio_id').size())
    ff['familias_fuente']=ff.grupo_estudio_id.map(corr.groupby('grupo_estudio_id').grupo_fuente_id.agg(lambda a:'; '.join(sorted(set(a)))))
    tablas={'correspondencia_cabeceras_estudio':corr,'recorridos_representacion_estudio':carreteras,
            'demanda_representacion_estudio':pesos,'zonas_representacion_estudio':z,
            'grupos_representacion_estudio':ff,'cobertura_representacion_estudio':cobertura,
            'reparto_corredores_estudio':pd.DataFrame(repartos)}
    metadata={'decision':especificacion['decision'],'hipotesis':especificacion['hipotesis'],
        'grupos_fuente':len(familias),'grupos_estudio':len(ff),'origenes':len(corr),'zonas':len(z),
        'origenes_con_cambio_geografico':len(cambiados),'perfiles_propios_integrados':len(refs),
        'solo_montana_candidata':int((~corr.perfil_propio_estudio_disponible&corr.montana_cabecera_candidata_disponible).sum()),
        'sin_montana_atribuible':int((~corr.montana_cabecera_candidata_disponible).sum()),
        'demanda_y_pesos_fuente_conservados':True,'cobertura_geografica_completa':estado['cobertura_geografica_completa'],
        'unidad':'Viajes-persona medios de 57 matrices; no demanda anual o vehículos.',
        'modo_o_captacion_adoptados':False,'energia_calculada':False,'visita_equivalente_validada':False,
        'limites':'Integración geográfica para estudio, no reparto observado. Conciliar visita e interior entre terminales distintos; modos, actividad anual y factores pendientes.'}
    return tablas,metadata

def preparar_aproximaciones_geograficas(correspondencia, recorridos, demanda, referencias,
                                       longitudes, especificacion):
    """Preparar referencias de cálculo explícitas sin atribuir perfiles propios.

    Una agrupación territorial permite un primer cálculo aproximado. No mide el
    acceso de sus miembros ni acota su error. La demanda publicada nula exige
    revisión si cambia: no se interpreta como año o energía cero.
    """
    from movilidad_teide.demanda.asignacion import _valores
    c = correspondencia.copy(); v = 'viajes_persona_media_57_matrices'
    if c.origen_id.duplicated().any() or set(c.origen_id)!=set(demanda.origen_id):
        raise ErrorAsignacion('Correspondencia y demanda deben conservar los mismos orígenes.')
    _valores(demanda,[v])
    if demanda.duplicated(['origen_id','colectivo','sentido']).any():
        raise ErrorAsignacion('Demanda duplicada por origen, colectivo y sentido.')
    if not demanda.groupby('origen_id').size().eq(8).all():
        raise ErrorAsignacion('Conservar los cuatro colectivos y ambos sentidos.')
    if (len(recorridos)!=2*len(c) or recorridos.duplicated(['origen_id','sentido']).any()
            or set(recorridos.origen_id)!=set(c.origen_id)):
        raise ErrorAsignacion('Conservar los recorridos originales por origen y sentido.')
    pendientes=set(c.loc[~c.perfil_propio_estudio_disponible,'origen_id'])
    specs=especificacion['casos'];seleccion={}
    for s in specs:
        oid=s['origen_id'];cid=s['comparacion_referencia_id']
        if oid in seleccion or oid not in pendientes or cid not in referencias or not s.get('fundamento'):
            raise ErrorAsignacion('Cada aproximación necesita un origen pendiente único y referencia fundada.')
        row=c.set_index('origen_id').loc[oid];ref=referencias[cid]
        if s['tipo']=='representante_familia':
            if cid!=row.comparacion_montana_candidata_id:
                raise ErrorAsignacion('La aproximación debe conservar la referencia de su propia familia.')
        elif s['tipo'] not in ['territorial_explicita','condicional_media_nula']:
            raise ErrorAsignacion('Tipo de aproximación desconocido.')
        if row.corredor_estudio!='sin_asignar' and row.corredor_estudio!=ref['corredor']:
            raise ErrorAsignacion('No cambiar una cabecera atribuida mediante una aproximación.')
        if s['tipo']=='condicional_media_nula' and demanda.loc[demanda.origen_id.eq(oid),v].ne(0).any():
            raise ErrorAsignacion('Nueva demanda positiva: fundamentar origen y recorrido antes de calcular.')
        seleccion[oid]=s
    if set(seleccion)!=pendientes:
        raise ErrorAsignacion('Todos los casos pendientes necesitan tratamiento explícito.')
    filas=[]
    for row in c.itertuples():
        own=row.perfil_propio_estudio_disponible
        s=seleccion.get(row.origen_id,{})
        cid=row.comparacion_estudio_id if own else s['comparacion_referencia_id']
        ref=referencias[cid];conditional=s.get('tipo')=='condicional_media_nula'
        if own and ref['origin_id']!=row.origen_id:
            raise ErrorAsignacion('Un perfil propio debe pertenecer a su origen.')
        filas.append({'origen_id':row.origen_id,'grupo_estudio_id':row.grupo_estudio_id,
            'tipo_representacion_calculo':'perfil_propio' if own else s['tipo'],
            'comparacion_calculo_id':None if conditional else cid,
            'comparacion_condicional_id':cid if conditional else None,
            'origen_referencia_calculo_id':None if conditional else ref['origin_id'],
            'corredor_calculo':ref['corredor'],'cabecera_calculo':ref['head_label'],
            'terminal_calculo':ref['terminal_label'],'perfil_propio':bool(own),
            'aproximacion_territorial':not own and not conditional,
            'requiere_revision_si_demanda_positiva':conditional,
            'error_geografico_energetico_acotado':False,
            'fundamento':row.fundamento_estudio if own else s['fundamento'],
            'limite':('Representatividad de sus zonas por contrastar.' if own else
                'Referencia de cálculo de otra ubicación; no acceso propio, elección observada o error acotado. Revisar sensibilidad y equivalencia de visita.' if not conditional else
                'Media publicada nula; conservar zona y revisar si aparece demanda positiva. No acredita actividad anual o energía cero.')})
    plan=pd.DataFrame(filas)
    # Las longitudes pertenecen a la referencia, nunca al punto sin perfil propio.
    r=plan.merge(pd.DataFrame({'sentido':list(SENTIDOS.values())}),how='cross')
    dims=longitudes.drop(columns='origen_id').rename(columns={'comparacion_id':'comparacion_calculo_id'})
    if dims.duplicated(['comparacion_calculo_id','sentido']).any():
        raise ErrorAsignacion('Longitudes repetidas por referencia y sentido.')
    r=r.merge(dims,on=['comparacion_calculo_id','sentido'],how='left',validate='many_to_one')
    cols=['directa_km','alimentador_km','montana_km','cadena_km']
    active=~r.requiere_revision_si_demanda_positiva
    _valores(r.loc[active],cols)
    if r.loc[active,cols].le(0).any().any() or not r.loc[~active,cols].isna().all().all():
        raise ErrorAsignacion('Referencias activas completas; casos condicionales sin kilómetros atribuidos.')
    p=demanda.merge(plan.drop(columns='grupo_estudio_id'),on='origen_id',validate='many_to_one')
    pd.testing.assert_frame_equal(p[demanda.columns],demanda)
    cov=p.groupby(['colectivo','sentido','tipo_representacion_calculo'])[v].sum().unstack(fill_value=0).reset_index()
    return {'representaciones_calculo_geografico':plan,'recorridos_referencia_calculo':r,
            'demanda_referencia_calculo':p,'cobertura_referencias_calculo':cov}
