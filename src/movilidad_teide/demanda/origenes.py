"""demanda: origenes. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from movilidad_teide.demanda.asignacion_tipos import ErrorAsignacion
from movilidad_teide.demanda.asignacion_tipos import SEGMENTOS
from movilidad_teide.demanda.asignacion_tipos import SENTIDOS
from movilidad_teide.demanda.asignacion_tipos import PENDIENTE


def seleccionar_origenes_representativos(asignacion, centroides, zonas, paradas):
    """Proponer puntos reales por municipio/grupo sin modificar demanda o corredores.

    El municipio es una etiqueta territorial del visor, no una distribución de
    personas por superficie. La parada elegida aproxima un origen para revisar
    recorridos; no acredita aparcamiento, modo, accesibilidad o salida observada.
    """
    from movilidad_teide.demanda.asignacion import _valores
    from movilidad_teide.demanda.asignacion import agrupar_origenes
    v = 'viajes_persona_media_57_matrices'
    a, _ = agrupar_origenes(asignacion)
    necesarios = {'municipio_id_principal', 'municipio_principal'}
    if not necesarios <= set(a) or zonas.zona_id.duplicated().any():
        raise ErrorAsignacion('Faltan referencias municipales o las zonas están repetidas.')
    if zonas.crs is None or not zonas.crs.is_projected or zonas.crs.axis_info[0].unit_name != 'metre':
        raise ErrorAsignacion('La selección de puntos requiere un CRS proyectado en metros.')
    if a.groupby('zona_id')[list(necesarios)].nunique(dropna=False).gt(1).any().any():
        raise ErrorAsignacion('Una zona cambia de referencia municipal.')
    if not set(a.zona_id) <= set(zonas.zona_id):
        raise ErrorAsignacion('Faltan geometrías de zonas de origen.')
    c = centroides.copy()
    cols = [f'{p}_{s}' for p in SENTIDOS for s in SEGMENTOS]
    _valores(c, cols)
    if not np.isfinite(c[['lon','lat']].to_numpy(dtype=float)).all() or not c.lon.between(-180,180).all() or not c.lat.between(-90,90).all():
        raise ErrorAsignacion('Coordenadas de centroides no válidas.')
    if c.duplicated(['zone_id', 'centroid_id']).any() or set(c.zone_id) != set(a.zona_id):
        raise ErrorAsignacion('Los centroides y las zonas no tienen las mismas claves.')
    # Contrastar pesos antes de usar sus localizaciones para proponer una referencia.
    pesos_zona = a.groupby('zona_id')[v].sum().sort_index()
    c['peso'] = c[cols].sum(axis=1)
    if not np.allclose(c.groupby('zone_id').peso.sum().reindex(pesos_zona.index), pesos_zona, atol=1e-7, rtol=0):
        raise ErrorAsignacion('La demanda de los centroides no coincide con la asignación.')
    cg = gpd.GeoDataFrame(c, geometry=gpd.points_from_xy(c.lon, c.lat), crs=4326).to_crs(zonas.crs)
    p = paradas.copy().to_crs(zonas.crs)
    if p.stop_id.isna().any() or p.stop_id.duplicated().any() or not p.geometry.is_valid.all() or not p.geom_type.eq('Point').all():
        raise ErrorAsignacion('Las paradas de referencia tienen claves o geometrías no válidas.')
    p['stop_id'] = p.stop_id.astype(str)
    # Excluir correspondencias espaciales ambiguas; nunca elegir por una unión repetida.
    pertenencia = gpd.sjoin(p, zonas[['zona_id', 'geometry']], how='inner', predicate='within')
    pertenencia = pertenencia.loc[~pertenencia.stop_id.duplicated(keep=False)].copy()
    a['municipio_clave'] = a.municipio_id_principal.map(lambda x: 'sin_referencia' if pd.isna(x) else str(int(x)))
    a['origen_id'] = a.grupo_origen_id + '__MUN' + a.municipio_clave
    m = a[['zona_id', 'origen_id', 'grupo_origen_id', 'municipio_principal', 'corredor_candidato']].drop_duplicates()
    assert m.zona_id.is_unique
    demanda = a.groupby(['origen_id', 'colectivo', 'sentido'], as_index=False)[v].sum()
    demanda['colectivo_nombre'] = demanda.colectivo.map(SEGMENTOS)
    demanda['unidad'] = 'viajes-persona estimados: media de 57 matrices, sin anualizar'
    filas = []
    for ident, bloque in a.groupby('origen_id', sort=True):
        z = bloque.groupby('zona_id', as_index=False)[v].sum().sort_values([v, 'zona_id'], ascending=[False, True])
        total = z[v].sum(); zona = int(z.iloc[0].zona_id)
        principal = cg.loc[cg.zone_id.eq(zona) & cg.peso.gt(0)]
        punto = None; stop_id = stop_name = None; desplazamiento = np.nan
        estado = 'Sin demanda positiva; no se inventa un punto de origen'
        if total > 0:
            centro = Point(np.average(principal.geometry.x, weights=principal.peso),
                           np.average(principal.geometry.y, weights=principal.peso))
            candidatas = pertenencia.loc[pertenencia.zona_id.eq(zona)].copy()
            estado = 'Sin parada activa GTFS dentro de la zona principal; punto pendiente'
            if not candidatas.empty:
                candidatas['distancia'] = candidatas.geometry.distance(centro)
                elegida = candidatas.sort_values(['distancia', 'stop_id']).iloc[0]
                punto, stop_id, stop_name = elegida.geometry, elegida.stop_id, elegida.stop_name
                desplazamiento = float(elegida.distancia)
                estado = 'Propuesta de origen representativo; no recorrido ni modo adoptados'
        dispersion = media = np.nan
        if punto is not None:
            muestra = cg.loc[cg.zone_id.isin(z.zona_id) & cg.peso.gt(0)]
            radios = muestra.geometry.distance(punto).to_numpy(); pesos = muestra.peso.to_numpy()
            orden = np.argsort(radios, kind='stable')
            dispersion = float(radios[orden][np.searchsorted(np.cumsum(pesos[orden]), .9 * pesos.sum())])
            media = float(np.average(radios, weights=pesos))
        sentido = bloque.groupby('sentido')[v].sum()
        turistas = bloque.loc[bloque.colectivo.isin(['extranjero', 'espana_no_tenerife'])].groupby('sentido')[v].sum()
        fila = {'origen_id':ident, 'grupo_origen_id':bloque.grupo_origen_id.iloc[0],
            'macrozona':bloque.macrozona_principal.iloc[0], 'municipio_referencia':bloque.municipio_principal.iloc[0],
            'corredor_candidato':bloque.corredor_candidato.iloc[0], 'numero_zonas':len(z),
            'zonas_id':', '.join(map(str, sorted(z.zona_id))), 'zona_referencia_id':zona,
            'peso_zona_principal_ambos_sentidos':np.nan if total == 0 else z.iloc[0][v]/total,
            'stop_id_referencia':stop_id, 'punto_referencia':stop_name,
            'separacion_centro_ponderado_parada_m':desplazamiento,
            'radio_90_demanda_cartografico_m':dispersion, 'distancia_media_cartografica_m':media,
            'viajes_hacia_teide_media57':sentido['hacia_teide'], 'viajes_desde_teide_media57':sentido['desde_teide'],
            'turistas_hacia_media57':turistas['hacia_teide'], 'turistas_desde_media57':turistas['desde_teide'],
            'estado':estado, 'punto_adoptado_para_calculo':False,
            'distancia_coche_ida_km':np.nan, 'distancia_coche_regreso_km':np.nan,
            'unidad_demanda':'viajes-persona medios de 57 matrices; no día anual representativo',
            'unidad_dispersion':'m en línea recta, ponderados por demanda modelizada; no distancias de circulación ni error',
            'fuente':'F035 — Visor Teide; F041 — zonificación; F051 — cabecera candidata; F045 — parada real GTFS',
            'geometry':punto}
        fila['residentes_hacia_media57'] = fila['viajes_hacia_teide_media57'] - fila['turistas_hacia_media57']
        fila['residentes_desde_media57'] = fila['viajes_desde_teide_media57'] - fila['turistas_desde_media57']
        filas.append(fila)
    puntos = gpd.GeoDataFrame(filas, crs=zonas.crs)
    ll = puntos.to_crs(4326)
    puntos['longitud'] = ll.geometry.x; puntos['latitud'] = ll.geometry.y
    for nombre, sentido in [('hacia', 'hacia_teide'), ('desde', 'desde_teide')]:
        total = a.loc[a.sentido.eq(sentido), v].sum()
        puntos[f'peso_en_sentido_{nombre}'] = puntos[f'viajes_{sentido}_media57'] / total if total > 0 else np.nan
    original = a.groupby(['colectivo', 'sentido'])[v].sum().sort_index()
    if not np.allclose(original, demanda.groupby(['colectivo', 'sentido'])[v].sum().sort_index(), rtol=0, atol=1e-8):
        raise ErrorAsignacion('La selección de orígenes pierde demanda.')
    return m, demanda, puntos

def agrupar_origenes_para_recorridos(correspondencia, demanda, origenes, centroides, cotas, especificacion):
    """Proponer menos referencias sin perder zonas, colectivos o sentidos.

    Las familias son decisiones territoriales explícitas en configuración, no
    rutas calculadas. El representante es un punto real que minimiza separación
    cartográfica ponderada entre referencias conocidas. No optimiza consumo ni
    prueba similitud de kilómetros/pendientes; las cotas y dispersión la revisan.
    """
    from movilidad_teide.demanda.asignacion import _valores
    v = 'viajes_persona_media_57_matrices'
    claves = ['origen_id', 'colectivo', 'sentido']
    requeridas = [(correspondencia,{'zona_id','origen_id'}),(demanda,set(claves)|{v}),
        (origenes,{'origen_id','corredor_candidato','cabecera_candidata','geometry','municipio_referencia','stop_id_referencia','punto_referencia','viajes_hacia_teide_media57','viajes_desde_teide_media57'}),
        (cotas,{'origen_id','cota_terreno_m'})]
    if any(not campos <= set(tabla) for tabla,campos in requeridas):
        raise ErrorAsignacion('Faltan campos de correspondencia, demanda, puntos o cotas.')
    if not origenes.geometry.dropna().geom_type.eq('Point').all() or not origenes.geometry.dropna().is_valid.all():
        raise ErrorAsignacion('Las referencias deben ser puntos originales válidos o ausencias explícitas.')
    if (correspondencia.zona_id.isna().any() or correspondencia.zona_id.duplicated().any()
            or origenes.origen_id.isna().any() or origenes.origen_id.duplicated().any()
            or demanda[claves].isna().any().any() or demanda.duplicated(claves).any()):
        raise ErrorAsignacion('Claves de origen, zona o demanda ausentes/repetidas.')
    _valores(demanda, [v])
    ids = set(origenes.origen_id)
    if set(correspondencia.origen_id) != ids or set(demanda.origen_id) != ids:
        raise ErrorAsignacion('La correspondencia, los puntos y la demanda deben cubrir los mismos orígenes.')
    combinaciones = {(c,s) for c in SEGMENTOS for s in SENTIDOS.values()}
    for _, bloque in demanda.groupby('origen_id'):
        if set(zip(bloque.colectivo,bloque.sentido)) != combinaciones:
            raise ErrorAsignacion('Cada origen debe conservar cuatro colectivos y ambos sentidos, sin rellenar ceros.')
    if origenes.crs is None or not origenes.crs.is_projected or origenes.crs.axis_info[0].unit_name != 'metre':
        raise ErrorAsignacion('La agrupación necesita geometrías en metros.')
    if cotas.origen_id.duplicated().any() or set(cotas.origen_id) != ids:
        raise ErrorAsignacion('Las cotas deben cubrir los orígenes una sola vez, incluidas sus ausencias.')
    if cotas.cota_terreno_m.dropna().map(np.isfinite).eq(False).any():
        raise ErrorAsignacion('Una cota no es finita; no se interpreta como dato válido.')

    familias = especificacion['grupos']
    if not familias or len({g['grupo_reducido_id'] for g in familias}) != len(familias):
        raise ErrorAsignacion('Grupos reducidos ausentes o repetidos.')
    miembros = []
    for grupo in familias:
        for campo in ['nombre','corredor_candidato','fundamento','familia_vial_a_contrastar','prioridad_revision']:
            if not grupo.get(campo):
                raise ErrorAsignacion('Cada grupo requiere nombre, cabecera, fundamento y revisión vial explícitos.')
        if not grupo['origenes_id']:
            raise ErrorAsignacion('Un grupo reducido no puede quedar vacío.')
        for oid in grupo['origenes_id']:
            miembros.append({'origen_id':oid, 'grupo_reducido_id':grupo['grupo_reducido_id'],
                             'grupo_nombre':grupo['nombre']})
    miembros = pd.DataFrame(miembros)
    if miembros.origen_id.duplicated().any() or set(miembros.origen_id) != ids:
        raise ErrorAsignacion('Cada origen debe pertenecer exactamente a un grupo, sin perder el resto.')
    o = origenes.merge(miembros,on='origen_id',validate='one_to_one').merge(
        cotas[['origen_id','cota_terreno_m']],on='origen_id',validate='one_to_one')
    # Una agrupación mantiene la cabecera candidata; no corrige el mapa por conveniencia.
    for grupo in familias:
        b = o.loc[o.grupo_reducido_id.eq(grupo['grupo_reducido_id'])]
        if not b.corredor_candidato.eq(grupo['corredor_candidato']).all():
            raise ErrorAsignacion('Un grupo mezcla o cambia cabeceras candidatas.')
    z = correspondencia.merge(miembros,on='origen_id',validate='many_to_one')
    pesos = demanda.merge(miembros,on='origen_id',validate='many_to_one')
    llaves = ['grupo_reducido_id','colectivo','sentido']
    agregada = pesos.groupby(llaves,as_index=False)[v].sum()
    pesos = pesos.merge(agregada.rename(columns={v:'demanda_grupo_misma_unidad'}),on=llaves,validate='many_to_one')
    pesos['peso_origen_en_grupo_colectivo_sentido'] = pesos[v].div(pesos.demanda_grupo_misma_unidad.where(pesos.demanda_grupo_misma_unidad.gt(0)))
    for keys, col in [(['sentido'],'peso_en_sentido'),(['colectivo','sentido'],'peso_en_colectivo_sentido')]:
        total = agregada.groupby(keys)[v].transform('sum')
        agregada[col] = agregada[v].div(total.where(total.gt(0)))
    for tabla in [pesos,agregada]:
        tabla['unidad'] = 'viajes-persona medios de 57 matrices; no demanda anual o vehículos'
        tabla['colectivo_nombre'] = tabla.colectivo.map(SEGMENTOS)
        tabla['modo_futuro'] = None
        tabla['viajes_persona_anuales'] = np.nan
    # Cada origen conserva su total, incluso si no tiene punto, cota o cabecera.
    por_origen = demanda.groupby('origen_id')[v].sum()
    o['peso_seleccion'] = o.origen_id.map(por_origen)
    for sentido, col in [('hacia_teide','viajes_hacia_teide_media57'),('desde_teide','viajes_desde_teide_media57')]:
        esperado = demanda.loc[demanda.sentido.eq(sentido)].groupby('origen_id')[v].sum().reindex(o.origen_id)
        if not np.allclose(o[col],esperado,rtol=0,atol=1e-7):
            raise ErrorAsignacion('Los totales por origen no coinciden con la demanda por colectivo/sentido.')

    cols = [f'{p}_{s}' for p in SENTIDOS for s in SEGMENTOS]
    _valores(centroides,cols)
    if (centroides.duplicated(['zone_id','centroid_id']).any() or set(centroides.zone_id) != set(z.zona_id)
            or not np.isfinite(centroides[['lon','lat']].to_numpy(dtype=float)).all()
            or not centroides.lon.between(-180,180).all() or not centroides.lat.between(-90,90).all()):
        raise ErrorAsignacion('Centroides inválidos o zonas sin correspondencia.')
    c = centroides.copy();c['peso'] = c[cols].sum(axis=1)
    cg = gpd.GeoDataFrame(c,geometry=gpd.points_from_xy(c.lon,c.lat),crs=4326).to_crs(origenes.crs)
    cg = cg.merge(z[['zona_id','origen_id','grupo_reducido_id']],left_on='zone_id',right_on='zona_id',validate='many_to_one')
    contraste = cg.groupby('origen_id').peso.sum().reindex(por_origen.index)
    if not np.allclose(contraste,por_origen,rtol=0,atol=1e-7):
        raise ErrorAsignacion('La demanda espacial no coincide con la agregada; no cambiar pesos.')

    filas, diagnosticos, alternativas = [], [], []
    for grupo in familias:
        gid = grupo['grupo_reducido_id'];b = o.loc[o.grupo_reducido_id.eq(gid)].copy()
        conocidas = b.loc[b.geometry.notna() & b.peso_seleccion.gt(0)].sort_values('origen_id')
        total = float(b.peso_seleccion.sum());elegida = None;distancias = None
        if not conocidas.empty:
            xy = np.column_stack([conocidas.geometry.x,conocidas.geometry.y])
            distancias = np.sqrt(((xy[:,None,:]-xy[None,:,:])**2).sum(axis=2))
            objetivo = distancias @ conocidas.peso_seleccion.to_numpy() / conocidas.peso_seleccion.sum()
            # Desempate estable por identificador; no crear un punto en el centro del mapa.
            posicion = int(np.argmin(objetivo));elegida = conocidas.iloc[posicion]
            for j,(_,r) in enumerate(conocidas.iterrows()):
                alternativas.append({'grupo_reducido_id':gid,'grupo_nombre':grupo['nombre'],'origen_id':r.origen_id,
                    'punto_referencia':r.punto_referencia,'separacion_media_ponderada_m':float(objetivo[j]),
                    'cota_terreno_m':r.cota_terreno_m,'seleccionado':r.origen_id==elegida.origen_id,
                    'alcance':'Distancias en línea recta entre referencias; no km circulables ni energía'})
        punto = None if elegida is None else elegida.geometry
        nulas = b.loc[b.geometry.isna(),'peso_seleccion'].sum()
        cotas_conocidas = b.loc[b.geometry.notna() & b.cota_terreno_m.notna()]
        masa_cota = float(cotas_conocidas.peso_seleccion.sum())
        radio90 = media_radio = np.nan
        if punto is not None:
            muestra = cg.loc[cg.grupo_reducido_id.eq(gid) & cg.peso.gt(0)]
            radios = muestra.geometry.distance(punto).to_numpy();w = muestra.peso.to_numpy();orden = np.argsort(radios,kind='stable')
            radio90 = float(radios[orden][np.searchsorted(np.cumsum(w[orden]),.9*w.sum())])
            media_radio = float(np.average(radios,weights=w))
        for _,r in b.iterrows():
            diagnosticos.append({'grupo_reducido_id':gid,'grupo_nombre':grupo['nombre'],'origen_id':r.origen_id,
                'municipio_referencia':r.municipio_referencia,'punto_referencia':r.punto_referencia,
                'stop_id_referencia':r.stop_id_referencia,'referencia_seleccionada':False if elegida is None else r.origen_id==elegida.origen_id,
                'cota_terreno_m':r.cota_terreno_m,
                'separacion_cartografica_al_representante_m':np.nan if punto is None or r.geometry is None else float(r.geometry.distance(punto)),
                'diferencia_cota_con_representante_m':np.nan if elegida is None else r.cota_terreno_m-elegida.cota_terreno_m,
                'peso_ambos_sentidos_en_grupo':r.peso_seleccion/total if total>0 else np.nan,
                'alcance':'Diagnóstico de puntos, no distancias por carretera ni perfil o error energético'})
        fila = {'grupo_reducido_id':gid,'nombre':grupo['nombre'],'corredor_candidato':grupo['corredor_candidato'],
            'cabecera_candidata':b.cabecera_candidata.iloc[0], 'numero_subgrupos':len(b),
            'numero_zonas':z.loc[z.grupo_reducido_id.eq(gid),'zona_id'].nunique(),
            'origenes_id':'; '.join(sorted(b.origen_id)),
            'municipios_referencia':'; '.join(sorted(b.municipio_referencia.unique())),
            'origen_referencia_id':None if elegida is None else elegida.origen_id,
            'stop_id_referencia':None if elegida is None else elegida.stop_id_referencia,
            'punto_referencia':None if elegida is None else elegida.punto_referencia,
            'cota_referencia_m':np.nan if elegida is None else elegida.cota_terreno_m,
            'cota_min_referencias_m':b.cota_terreno_m.min(),'cota_max_referencias_m':b.cota_terreno_m.max(),
            'cobertura_demanda_con_punto':1-nulas/total if total>0 else np.nan,
            'cobertura_demanda_con_cota':masa_cota/total if total>0 else np.nan,
            'max_separacion_entre_referencias_m':np.nan if distancias is None else float(distancias.max()),
            'radio_90_demanda_cartografico_m':radio90,'distancia_media_cartografica_m':media_radio,
            'fundamento':grupo['fundamento'],'familia_vial_a_contrastar':grupo['familia_vial_a_contrastar'],
            'prioridad_revision':grupo['prioridad_revision'],'estado':'Propuesta de agrupación; similitud vial/energética y representatividad pendientes',
            'criterio_punto':'Parada existente con menor separación cartográfica media ponderada a las referencias conocidas; cuatro colectivos y ambos sentidos, sin pesos anuales',
            'adoptado_para_balance':False,'distancia_coche_ida_km':np.nan,'distancia_coche_regreso_km':np.nan,
            'unidad_demanda':'viajes-persona medios de 57 matrices; no anualizados',
            'limite_diagnostico':'Cotas solo de puntos de referencia, no extremos del territorio o rasante. Dispersión cartográfica no es km circulables, error o aceptación del grupo.',
            'fuente':'F035 — Visor Teide; F041 — zonificación OD; F045 — GTFS; F051 — cabecera candidata; F078 — cotas MDT05; D094-D095/H052',
            'geometry':punto}
        for s,col in [('hacia_teide','viajes_hacia_teide_media57'),('desde_teide','viajes_desde_teide_media57')]:
            fila[col] = float(b[col].sum())
            denominador = float(origenes[col].sum());fila['peso_en_'+s] = fila[col]/denominador if denominador>0 else np.nan
        filas.append(fila)
    puntos = gpd.GeoDataFrame(filas,crs=origenes.crs)
    ll = puntos.to_crs(4326);puntos['longitud']=ll.geometry.x;puntos['latitud']=ll.geometry.y
    original = demanda.groupby(['colectivo','sentido'])[v].sum().sort_index()
    if not np.allclose(original,agregada.groupby(['colectivo','sentido'])[v].sum().sort_index(),atol=1e-8,rtol=0):
        raise ErrorAsignacion('La agrupación no conserva todos los colectivos y sentidos.')
    return z,pesos,agregada,puntos,pd.DataFrame(diagnosticos),pd.DataFrame(alternativas)

def diagnosticar_reutilizacion_trazados(origenes, pertenencias, trazados):
    """Proyectar puntos sobre alimentadores conservados, sin asignar recorridos.

    La proyección puede caer en un cruce a distinto nivel o al final de una vía.
    Ni separación cero ni una cota parecida acreditan una conexión circulable.
    Cada cabecera conserva todos sus candidatos y ambos sentidos; no se elige
    una ruta óptima y las ausencias no se transforman en distancias cero.
    """
    requeridas = [(origenes, {'origen_id','corredor_candidato','geometry'}),
        (pertenencias, {'origen_id','grupo_reducido_id'}),
        (trazados, {'comparacion_id','itinerary_id','origen_referencia_id','corredor_candidato','sentido','geometry'})]
    if any(not campos <= set(t) for t,campos in requeridas):
        raise ErrorAsignacion('Faltan campos para revisar puntos y trazados.')
    if (origenes.origen_id.isna().any() or origenes.origen_id.duplicated().any()
            or pertenencias.origen_id.isna().any() or pertenencias.origen_id.duplicated().any()
            or set(origenes.origen_id)!=set(pertenencias.origen_id)
            or pertenencias.grupo_reducido_id.isna().any() or origenes.corredor_candidato.isna().any()):
        raise ErrorAsignacion('Cada origen necesita una única pertenencia y una cabecera explícita, incluida sin asignar.')
    for t in [origenes,trazados]:
        if t.crs is None or not t.crs.is_projected or t.crs.axis_info[0].unit_name!='metre':
            raise ErrorAsignacion('La revisión requiere un CRS métrico explícito.')
    if origenes.crs!=trazados.crs:
        raise ErrorAsignacion('Puntos y trazados deben usar el mismo CRS; no se reinterpretan coordenadas.')
    if origenes.is_empty.any():
        raise ErrorAsignacion('Una referencia vacía no sustituye a un punto ausente.')
    conocidos = origenes.loc[origenes.geometry.notna()]
    if (not conocidos.geom_type.eq('Point').all() or not conocidos.is_valid.all()
            or conocidos.is_empty.any()):
        raise ErrorAsignacion('Una referencia debe ser un punto válido o una ausencia explícita.')
    campos = ['comparacion_id','itinerary_id','origen_referencia_id','corredor_candidato','sentido']
    if (trazados.empty or trazados[campos].isna().any().any() or trazados.itinerary_id.duplicated().any()
            or trazados.duplicated(['comparacion_id','sentido']).any()
            or trazados.geometry.isna().any() or not trazados.geom_type.eq('LineString').all()
            or not trazados.is_valid.all() or trazados.is_empty.any()
            or not np.isfinite(trazados.length).all() or trazados.length.le(0).any()):
        raise ErrorAsignacion('Los alimentadores necesitan líneas válidas y claves únicas por comparación/sentido.')
    por_origen = origenes.set_index('origen_id')
    for _,b in trazados.groupby('comparacion_id'):
        if (set(b.sentido)!=set(SENTIDOS.values()) or len(b)!=2
                or b.corredor_candidato.nunique()!=1 or b.origen_referencia_id.nunique()!=1):
            raise ErrorAsignacion('Cada comparación debe conservar una cabecera, un origen y sus dos sentidos.')
        ref = b.origen_referencia_id.iloc[0]
        if (ref not in por_origen.index or por_origen.loc[ref,'corredor_candidato']!=b.corredor_candidato.iloc[0]
                or pd.isna(por_origen.loc[ref,'geometry'])):
            raise ErrorAsignacion('La referencia del trazado no coincide con los orígenes y su cabecera.')
    filas = []
    o = origenes.merge(pertenencias[['origen_id','grupo_reducido_id']],on='origen_id',validate='one_to_one')
    for _,r in o.iterrows():
        candidatos = trazados.loc[trazados.corredor_candidato.eq(r.corredor_candidato)]
        casos = list(candidatos.iterrows()) or [(None,None),(None,None)]
        for indice,(_,t) in enumerate(casos):
            sentido = list(SENTIDOS.values())[indice] if t is None else t.sentido
            fila = {'origen_id':r.origen_id,'grupo_reducido_id':r.grupo_reducido_id,
                'comparacion_id':None if t is None else t.comparacion_id,
                'itinerary_id':None if t is None else t.itinerary_id,'sentido':sentido,
                'origen_referencia_id':None if t is None else t.origen_referencia_id,
                'es_subgrupo_referencia_trazada':False if t is None else r.origen_id==t.origen_referencia_id,
                'separacion_cartografica_m':np.nan,'longitud_alimentador_conservado_m':np.nan,
                'longitud_trazado_desde_proyeccion_hasta_cabecera_m':np.nan,
                'conexion_circulable_confirmada':False,'recorrido_asignado_para_balance':False,'geometry':None}
            if t is None:
                fila['estado'] = 'Sin trazado para la cabecera candidata; demanda conservada'
            elif pd.isna(r.geometry):
                fila['estado'] = 'Sin punto de origen; separación y conexión ausentes, no cero'
            else:
                posicion = t.geometry.project(r.geometry)
                proyeccion = t.geometry.interpolate(posicion)
                fila.update({'geometry':proyeccion,'separacion_cartografica_m':r.geometry.distance(proyeccion),
                    'longitud_alimentador_conservado_m':t.geometry.length,
                    'longitud_trazado_desde_proyeccion_hasta_cabecera_m':(
                        t.geometry.length-posicion if sentido=='hacia_teide' else posicion),
                    'estado':'Proyección cartográfica; no nuevo recorrido o conexión circulable'})
            filas.append(fila)
    return gpd.GeoDataFrame(filas,crs=origenes.crs).sort_values(
        ['origen_id','comparacion_id','sentido'],na_position='last').reset_index(drop=True)


def resumir_revision_trazados(origenes, grupos, demanda, diagnostico, proyecciones, excepciones):
    """Distinguir cobertura de puntos y familias, conservando sus denominadores.

    El candidato más próximo solo ordena la revisión cartográfica. No se copian
    distancias a nuevos orígenes ni se adopta equivalencia vial o energética.
    """
    from movilidad_teide.demanda.asignacion import _valores
    v = 'viajes_persona_media_57_matrices'
    ids = set(origenes.origen_id)
    if (diagnostico.origen_id.duplicated().any() or set(diagnostico.origen_id)!=ids
            or grupos.grupo_reducido_id.duplicated().any()
            or set(diagnostico.grupo_reducido_id)!=set(grupos.grupo_reducido_id)
            or demanda.duplicated(['origen_id','colectivo','sentido']).any() or set(demanda.origen_id)!=ids
            or set(proyecciones.origen_id)!=ids):
        raise ErrorAsignacion('La revisión debe conservar exactamente todos los grupos, orígenes y colectivos.')
    _valores(demanda,[v])
    combinaciones = {(c,s) for c in SEGMENTOS for s in SENTIDOS.values()}
    for _,b in demanda.groupby('origen_id'):
        if set(zip(b.colectivo,b.sentido))!=combinaciones:
            raise ErrorAsignacion('Cada origen debe conservar cuatro colectivos y ambos sentidos.')
    if set(excepciones)-set(grupos.grupo_reducido_id):
        raise ErrorAsignacion('Hay excepciones para familias inexistentes.')
    referencias = set(proyecciones.loc[proyecciones.es_subgrupo_referencia_trazada,'origen_id'])
    familias_trazadas = set(diagnostico.loc[diagnostico.origen_id.isin(referencias),'grupo_reducido_id'])
    detalle = diagnostico.copy()
    detalle['subgrupo_referencia_con_trazado'] = detalle.origen_id.isin(referencias)
    detalle['familia_con_referencia_trazada'] = detalle.grupo_reducido_id.isin(familias_trazadas)
    candidatos = []
    for (oid,cid),b in proyecciones.dropna(subset=['comparacion_id']).groupby(['origen_id','comparacion_id']):
        if set(b.sentido)!=set(SENTIDOS.values()) or len(b)!=2:
            raise ErrorAsignacion('Falta un sentido en el diagnóstico de una comparación.')
        if b.separacion_cartografica_m.isna().any():
            continue
        fila = {'origen_id':oid,'comparacion_cercana_cartograficamente':cid,
            'separacion_max_ambos_sentidos_m':b.separacion_cartografica_m.max()}
        for sentido in SENTIDOS.values():
            r=b.loc[b.sentido.eq(sentido)].iloc[0]
            fila['separacion_trazado_'+sentido+'_m']=r.separacion_cartografica_m
            fila['diferencia_cota_proyeccion_'+sentido+'_m']=r.get('diferencia_cota_origen_proyeccion_m',np.nan)
        candidatos.append(fila)
    candidatos = pd.DataFrame(candidatos)
    if not candidatos.empty:
        cercanos = candidatos.sort_values(['origen_id','separacion_max_ambos_sentidos_m',
            'comparacion_cercana_cartograficamente']).drop_duplicates('origen_id')
        detalle = detalle.merge(cercanos,on='origen_id',how='left',validate='one_to_one')
    detalle['recorrido_asignado_para_balance'] = False
    revision = grupos.drop(columns='geometry',errors='ignore').copy()
    revision['referencia_principal_con_trazado'] = revision.origen_referencia_id.isin(referencias)
    revision['numero_subgrupos_referencia_trazada'] = revision.grupo_reducido_id.map(
        detalle.groupby('grupo_reducido_id').subgrupo_referencia_con_trazado.sum()).astype(int)
    revision['familia_completamente_contrastada'] = False
    revision['recorrido_asignado_para_balance'] = False
    acciones, motivos, compatibles = [], [], []
    for _,r in revision.iterrows():
        b = proyecciones.loc[proyecciones.grupo_reducido_id.eq(r.grupo_reducido_id)]
        compatibles.append('; '.join(sorted(b.comparacion_id.dropna().unique())))
        if r.grupo_reducido_id in excepciones:
            ficha = excepciones[r.grupo_reducido_id]
            accion,motivo = ficha['accion'],ficha['motivo']
        elif r.referencia_principal_con_trazado:
            accion = 'Conservar referencia y revisar miembros' if r.numero_subgrupos>1 else 'Conservar referencia trazada'
            motivo = 'El punto principal tiene trazado. Revisar conexiones y los demás miembros antes de extenderle su perfil.'
        else:
            accion = 'Preparar alimentador propio'
            motivo = 'No hay trazado desde el punto principal de esta familia; compartir cabecera no elimina su acceso.'
        acciones.append(accion);motivos.append(motivo)
    revision['accion_propuesta'] = acciones
    revision['motivo_revision'] = motivos
    revision['comparaciones_disponibles_misma_cabecera'] = compatibles
    revision['orden_demanda_media_referencias_pendientes'] = pd.Series(pd.NA,index=revision.index,dtype='Int64')
    pendientes = revision.loc[~revision.referencia_principal_con_trazado & revision.accion_propuesta.isin(
        ['Preparar alimentador propio','Revisar conexión local'])].sort_values(
            ['viajes_hacia_teide_media57','grupo_reducido_id'],ascending=[False,True])
    revision.loc[pendientes.index,'orden_demanda_media_referencias_pendientes'] = range(1,len(pendientes)+1)
    # Cada colectivo/sentido tiene su propio denominador; nunca sumar las proyecciones como demanda.
    cobertura=[]
    pertenencias = diagnostico[['origen_id','grupo_reducido_id']]
    d=demanda.merge(pertenencias,on='origen_id',validate='many_to_one')
    puntos = set(origenes.loc[origenes.geometry.notna(),'origen_id'])
    sin_cabecera = set(origenes.loc[origenes.corredor_candidato.eq(PENDIENTE),'origen_id'])
    for (colectivo,sentido),b in d.groupby(['colectivo','sentido'],sort=True):
        total=b[v].sum();ref=b.loc[b.origen_id.isin(referencias),v].sum()
        familia=b.loc[b.grupo_reducido_id.isin(familias_trazadas),v].sum()
        cobertura.append({'colectivo':colectivo,'colectivo_nombre':SEGMENTOS[colectivo],'sentido':sentido,
            'demanda_total_media57':total,'demanda_subgrupos_referencia_trazada_media57':ref,
            'demanda_familias_con_referencia_trazada_media57':familia,
            'fraccion_subgrupos_referencia_trazada':ref/total if total>0 else np.nan,
            'fraccion_familias_con_referencia_trazada':familia/total if total>0 else np.nan,
            'demanda_sin_punto_media57':b.loc[~b.origen_id.isin(puntos),v].sum(),
            'demanda_sin_cabecera_media57':b.loc[b.origen_id.isin(sin_cabecera),v].sum(),
            'unidad':'viajes-persona medios de 57 matrices; no demanda anual, coches o cobertura validada',
            'familias_completamente_contrastadas':0,'recorridos_asignados_para_balance':0})
    return revision,detalle,pd.DataFrame(cobertura)

def revisar_representatividad_geografica(detalle, familias, demanda, proyecciones,
                                       comparaciones, longitudes, excepciones):
    """Revisar referencias y conexiones sin copiar perfiles a otros orígenes.

    Conservo los candidatos de la propia familia, separados del más cercano de
    toda la cabecera. Las longitudes solo describen referencias ya trazadas.
    Los cinco tratamientos son excluyentes y conservan cuatro colectivos y
    ambos sentidos; no representan vehículos, demanda anual o energía.
    """
    from movilidad_teide.demanda.asignacion import _valores
    v = 'viajes_persona_media_57_matrices'
    tratamientos = ['referencia_trazada','conexion_pendiente','cabecera_en_revision',
                    'sin_punto','sin_cabecera']
    campos = [({'origen_id','grupo_reducido_id','punto_referencia',
                'subgrupo_referencia_con_trazado'},detalle),
              ({'grupo_reducido_id','numero_subgrupos','corredor_candidato'},familias),
              ({'origen_id','colectivo','sentido',v},demanda),
              ({'origen_id','comparacion_id','sentido','separacion_cartografica_m'},proyecciones),
              ({'comparacion_id','sentido','longitud_alimentador_km'},longitudes)]
    if any(not c <= set(t) for c,t in campos):
        raise ErrorAsignacion('Faltan campos para revisar la representatividad geográfica.')
    ids=set(detalle.origen_id);gids=set(familias.grupo_reducido_id)
    if (detalle.origen_id.isna().any() or detalle.origen_id.duplicated().any()
            or familias.grupo_reducido_id.isna().any() or familias.grupo_reducido_id.duplicated().any()
            or detalle.grupo_reducido_id.isna().any() or set(detalle.grupo_reducido_id)!=gids
            or set(demanda.origen_id)!=ids or demanda.duplicated(['origen_id','colectivo','sentido']).any()
            or set(proyecciones.origen_id)!=ids or set(excepciones)-gids):
        raise ErrorAsignacion('La revisión debe conservar pertenencias, demanda y excepciones únicas.')
    _valores(demanda,[v])
    combinaciones={(c,s) for c in SEGMENTOS for s in SENTIDOS.values()}
    if any(set(zip(b.colectivo,b.sentido))!=combinaciones for _,b in demanda.groupby('origen_id')):
        raise ErrorAsignacion('Cada origen necesita cuatro colectivos y ambos sentidos.')
    conteo=detalle.groupby('grupo_reducido_id').size().sort_index()
    if not conteo.eq(familias.set_index('grupo_reducido_id').numero_subgrupos.reindex(conteo.index)).all():
        raise ErrorAsignacion('El número de miembros no coincide con las familias.')
    if not comparaciones:
        raise ErrorAsignacion('La revisión necesita referencias trazadas identificadas.')
    refs=[]
    for cid,ficha in comparaciones.items():
        if (not {'origin_id','reduced_group_id','label'}<=set(ficha)
                or ficha['origin_id'] not in ids or ficha['reduced_group_id'] not in gids):
            raise ErrorAsignacion('Hay una referencia del catálogo sin origen o familia válidos.')
        if detalle.set_index('origen_id').loc[ficha['origin_id'],'grupo_reducido_id']!=ficha['reduced_group_id']:
            raise ErrorAsignacion('Una referencia trazada pertenece a otra familia.')
        refs.append({'comparacion_id':cid,'origen_id':ficha['origin_id'],
                     'grupo_reducido_id':ficha['reduced_group_id'],'nombre':ficha['label']})
    refs=pd.DataFrame(refs)
    if refs.origen_id.duplicated().any():
        raise ErrorAsignacion('Un origen tiene más de una referencia; resolver esa ambigüedad explícitamente.')
    if (not detalle.subgrupo_referencia_con_trazado.isin([True,False]).all()
            or not detalle.subgrupo_referencia_con_trazado.eq(detalle.origen_id.isin(refs.origen_id)).all()):
        raise ErrorAsignacion('La cobertura previa y las referencias del catálogo no coinciden.')
    _valores(longitudes,['longitud_alimentador_km'])
    claves={(c,s) for c in refs.comparacion_id for s in SENTIDOS.values()}
    if (longitudes.duplicated(['comparacion_id','sentido']).any()
            or set(zip(longitudes.comparacion_id,longitudes.sentido))!=claves
            or longitudes.longitud_alimentador_km.le(0).any()):
        raise ErrorAsignacion('Cada referencia necesita longitudes positivas y sus dos sentidos.')
    p=proyecciones.dropna(subset=['comparacion_id'])
    if (p.duplicated(['origen_id','comparacion_id','sentido']).any()
            or set(p.comparacion_id)-set(refs.comparacion_id)):
        raise ErrorAsignacion('Hay proyecciones repetidas o candidatos inexistentes.')
    for _,b in p.groupby(['origen_id','comparacion_id']):
        if len(b)!=2 or set(b.sentido)!=set(SENTIDOS.values()):
            raise ErrorAsignacion('El candidato debe conservar ambos sentidos.')
        a=b.separacion_cartografica_m
        if a.notna().any() and (not a.notna().all() or not np.isfinite(a).all() or a.lt(0).any()):
            raise ErrorAsignacion('Las separaciones necesitan ambos sentidos finitos y no negativos.')
    # Los nombres y estados son diagnósticos; no introducen umbrales de aceptación.
    nombres={'referencia_trazada':'Referencia con perfil',
             'conexion_pendiente':'Conexión de miembro pendiente',
             'cabecera_en_revision':'Cabecera en revisión',
             'sin_punto':'Referencia territorial ausente',
             'sin_cabecera':'Sin cabecera candidata'}
    reglas={'referencia_trazada':'Conservar el perfil desde esta referencia; revisar la dispersión de sus zonas.',
            'conexion_pendiente':'Revisar la conexión propia hasta un tramo común documentado; conservar la montaña disponible.',
            'cabecera_en_revision':'Revisar la cabecera inferida antes de definir el acceso transversal.',
            'sin_punto':'Conservar la demanda y definir una referencia territorial con fundamento antes de atribuir distancias.',
            'sin_cabecera':'Conservar la demanda sin recorrido; ausencia de datos no equivale a energía cero.'}
    own=refs.set_index('origen_id').comparacion_id;longs=longitudes.set_index(['comparacion_id','sentido']).longitud_alimentador_km
    fg=familias.set_index('grupo_reducido_id');filas=[]
    for _,r in detalle.iterrows():
        grupo=r.grupo_reducido_id;ficha=excepciones.get(grupo);fref=refs.loc[refs.grupo_reducido_id.eq(grupo)]
        if fg.loc[grupo,'corredor_candidato']==PENDIENTE:
            estado='sin_cabecera'
        elif ficha:
            estado='cabecera_en_revision'
        elif pd.isna(r.punto_referencia):
            estado='sin_punto'
        elif r.origen_id in own.index:
            estado='referencia_trazada'
        else:
            estado='conexion_pendiente'
        ident=own.get(r.origen_id) if estado=='referencia_trazada' else None
        fila={'origen_id':r.origen_id,'tratamiento_geografico':estado,'tratamiento_geografico_nombre':nombres[estado],
              'perfil_desde_referencia_disponible':estado=='referencia_trazada',
              'comparacion_propia_id':ident,'referencias_disponibles_familia':'; '.join(fref.comparacion_id),
              'referencias_familia_nombres':'; '.join(fref.nombre),
              'candidato_revision_misma_familia':None,'candidato_familia_nombre':None,
              'separacion_candidato_familia_m':np.nan,'representatividad_adoptada_para_balance':False,
              'accion_representatividad':reglas[estado],
              'fundamento_representatividad':(ficha['motivo'] if ficha else
                  'Referencias territoriales y trazados conservados; separación cartográfica no es conexión o error energético.')}
        for sentido in SENTIDOS.values():
            fila['longitud_perfil_propio_'+sentido+'_km']=longs.loc[(ident,sentido)] if ident is not None else np.nan
        # Conservar candidatos de la familia, incluso si otra familia pasa más cerca.
        # La elección ordena una revisión; no asigna recorrido, longitud o perfil.
        if estado in ['referencia_trazada','conexion_pendiente']:
            candidatos=[]
            for cid in fref.comparacion_id:
                b=p.loc[p.origen_id.eq(r.origen_id)&p.comparacion_id.eq(cid)]
                if len(b)!=2:
                    raise ErrorAsignacion('Falta el contraste de ambos sentidos para un candidato de la propia familia.')
                if b.separacion_cartografica_m.notna().all():
                    candidatos.append((b.separacion_cartografica_m.max(),cid))
            if candidatos:
                distancia,cid=(next(x for x in candidatos if x[1]==ident) if ident is not None else min(candidatos))
                fila.update(candidato_revision_misma_familia=cid,
                    candidato_familia_nombre=refs.set_index('comparacion_id').loc[cid,'nombre'],
                    separacion_candidato_familia_m=distancia)
        filas.append(fila)
    d=detalle.merge(pd.DataFrame(filas),on='origen_id',validate='one_to_one')
    f=familias.copy()
    for estado in tratamientos:
        f['numero_subgrupos_tratamiento_'+estado]=f.grupo_reducido_id.map(
            d.loc[d.tratamiento_geografico.eq(estado)].groupby('grupo_reducido_id').size()).fillna(0).astype(int)
    f['referencias_de_todos_los_miembros_trazadas']=f.grupo_reducido_id.map(
        detalle.groupby('grupo_reducido_id').subgrupo_referencia_con_trazado.sum()).eq(f.numero_subgrupos)
    # Cubrir todos los puntos de referencia no valida todos los viajes de sus zonas.
    f['representatividad_adoptada_para_balance']=False
    f['decision_simplificacion']=np.where(f.referencias_de_todos_los_miembros_trazadas,
        'Conservar las referencias trazadas y los pesos de sus subgrupos; no sustituir varias por una.',
        'Conservar las referencias disponibles; resolver miembros o excepciones antes de extender perfiles.')
    for sentido in SENTIDOS.values():
        for estado in tratamientos:
            b=demanda.loc[demanda.sentido.eq(sentido)].merge(d[['origen_id','grupo_reducido_id','tratamiento_geografico']],on='origen_id',validate='many_to_one')
            suma=b.loc[b.tratamiento_geografico.eq(estado)].groupby('grupo_reducido_id')[v].sum()
            f['demanda_tratamiento_'+estado+'_'+sentido+'_media57']=f.grupo_reducido_id.map(suma).fillna(0.)
    f['orden_revision_conexiones_por_demanda_media']=pd.Series(pd.NA,index=f.index,dtype='Int64')
    pendiente=f.loc[f.numero_subgrupos_tratamiento_conexion_pendiente.gt(0)].sort_values(
        ['demanda_tratamiento_conexion_pendiente_hacia_teide_media57','grupo_reducido_id'],ascending=[False,True])
    f.loc[pendiente.index,'orden_revision_conexiones_por_demanda_media']=range(1,len(pendiente)+1)
    cobertura=[]
    original=demanda.merge(d[['origen_id','tratamiento_geografico']],on='origen_id',validate='many_to_one')
    for (colectivo,sentido),b in original.groupby(['colectivo','sentido'],sort=True):
        total=b[v].sum();fila={'colectivo':colectivo,'sentido':sentido,'demanda_total_media57':total}
        for estado in tratamientos:
            valor=b.loc[b.tratamiento_geografico.eq(estado),v].sum()
            fila['demanda_tratamiento_'+estado+'_media57']=valor
            fila['fraccion_tratamiento_'+estado]=valor/total if total>0 else np.nan
        if not np.isclose(sum(fila['demanda_tratamiento_'+e+'_media57'] for e in tratamientos),total,atol=1e-8,rtol=0):
            raise ErrorAsignacion('Los tratamientos no conservan la demanda por colectivo y sentido.')
        cobertura.append(fila)
    return d,f,pd.DataFrame(cobertura)

def cerrar_revision_geografica(detalle, familias, demanda, proyecciones, comparaciones, montanas):
    """Cerrar la revisión por piezas, sin extender un perfil a otro origen.

    La montaña solo se referencia dentro de la misma familia/cabecera candidata.
    Conservo alimentadores desconocidos, demanda y excepciones. Las separaciones
    y diferencias de cota describen candidatos; no son accesos ni errores acotados.
    El cierre de esta revisión no habilita un balance energético completo.
    """
    from movilidad_teide.demanda.asignacion import _valores
    valor = 'viajes_persona_media_57_matrices'
    estados = {'referencia_trazada', 'conexion_pendiente', 'cabecera_en_revision',
               'sin_punto', 'sin_cabecera'}
    campos = [({'origen_id','grupo_reducido_id','tratamiento_geografico',
                'comparacion_propia_id','candidato_revision_misma_familia'}, detalle),
              ({'grupo_reducido_id','numero_subgrupos'}, familias),
              ({'origen_id','colectivo','sentido',valor}, demanda),
              ({'origen_id','comparacion_id','sentido','separacion_cartografica_m',
                'diferencia_cota_origen_proyeccion_m'}, proyecciones),
              ({'comparacion_id','sentido','tramo_cabecera_terminal_km'}, montanas)]
    if any(not campos <= set(tabla) for campos,tabla in campos):
        raise ErrorAsignacion('Faltan campos para el cierre geográfico por componentes.')
    ids=set(detalle.origen_id); grupos=set(familias.grupo_reducido_id)
    if (detalle.origen_id.isna().any() or detalle.origen_id.duplicated().any()
            or familias.grupo_reducido_id.isna().any() or familias.grupo_reducido_id.duplicated().any()
            or set(detalle.grupo_reducido_id)!=grupos or set(demanda.origen_id)!=ids
            or not detalle.tratamiento_geografico.isin(estados).all()
            or demanda.duplicated(['origen_id','colectivo','sentido']).any()):
        raise ErrorAsignacion('El cierre necesita orígenes, familias y demanda únicos y completos.')
    _valores(demanda,[valor])
    esperadas={(c,s) for c in SEGMENTOS for s in SENTIDOS.values()}
    if any(set(zip(b.colectivo,b.sentido))!=esperadas for _,b in demanda.groupby('origen_id')):
        raise ErrorAsignacion('Conservar cuatro colectivos y ambos sentidos en cada origen.')
    conteos=detalle.groupby('grupo_reducido_id').size()
    if not conteos.eq(familias.set_index('grupo_reducido_id').numero_subgrupos.reindex(conteos.index)).all():
        raise ErrorAsignacion('Las familias no conservan sus miembros.')
    pertenencias=detalle.set_index('origen_id').grupo_reducido_id
    por_familia={g:[] for g in grupos}; vistos=set()
    for cid,ref in comparaciones.items():
        if (not {'origin_id','reduced_group_id','head_reference_anchor_id','terminal_reference_anchor_id','head_label','terminal_label'}<=set(ref)
                or ref['origin_id'] not in ids or ref['origin_id'] in vistos
                or ref['reduced_group_id']!=pertenencias.loc[ref['origin_id']]
                or not ref['head_reference_anchor_id'] or not ref['terminal_reference_anchor_id']):
            raise ErrorAsignacion('Referencia trazada sin origen, familia o cabecera inequívocos.')
        vistos.add(ref['origin_id']);por_familia[ref['reduced_group_id']].append(cid)
    # Compartir familia requiere la misma cabecera y terminal, no solo cercanía.
    for referencias in por_familia.values():
        if len({(comparaciones[c]['head_reference_anchor_id'],comparaciones[c]['terminal_reference_anchor_id'])
                for c in referencias})>1:
            raise ErrorAsignacion('Una familia contiene cabeceras o terminales distintos.')
    claves={(cid,s) for cid in comparaciones for s in SENTIDOS.values()}
    if (not comparaciones or montanas.duplicated(['comparacion_id','sentido']).any()
            or set(zip(montanas.comparacion_id,montanas.sentido))!=claves):
        raise ErrorAsignacion('Cada montaña necesita una longitud por referencia y sentido.')
    _valores(montanas,['tramo_cabecera_terminal_km'])
    if montanas.tramo_cabecera_terminal_km.le(0).any():
        raise ErrorAsignacion('Las montañas documentadas necesitan longitudes positivas.')
    if (proyecciones.duplicated(['origen_id','comparacion_id','sentido']).any()
            or set(proyecciones.origen_id)-ids
            or set(proyecciones.comparacion_id.dropna())-set(comparaciones)):
        raise ErrorAsignacion('Proyecciones repetidas o sin origen/referencia conocidos.')
    largos=montanas.set_index(['comparacion_id','sentido']).tramo_cabecera_terminal_km
    acciones={
        'referencia_trazada':'Conservar el perfil de este punto y sus pesos; contrastar representatividad de sus zonas.',
        'conexion_pendiente':'Reutilizar solo la montaña candidata; cuantificar el alimentador antes del balance. Trazado adicional según materialidad, sin copiar un perfil por cercanía.',
        'cabecera_en_revision':'Conservar la demanda y contrastar cabecera/corredor antes de asignar montaña o acceso transversal.',
        'sin_punto':'Conservar la demanda y la montaña candidata; falta fundamentar el origen y su alimentador.',
        'sin_cabecera':'Conservar la demanda sin distancias; faltan cabecera, origen y recorrido. Ausencia no equivale a energía cero.'}
    pendientes={
        'referencia_trazada':'Representatividad territorial; modos, actividad y factores.',
        'conexion_pendiente':'Alimentador propio; representatividad, modos, actividad y factores.',
        'cabecera_en_revision':'Cabecera/corredor y cadena completa; modos, actividad y factores.',
        'sin_punto':'Origen y alimentador; modos, actividad y factores.',
        'sin_cabecera':'Cabecera, origen y cadena completa; modos, actividad y factores.'}
    filas=[]
    for _,r in detalle.iterrows():
        estado=r.tratamiento_geografico;referencias=por_familia[r.grupo_reducido_id]
        propia=r.comparacion_propia_id if pd.notna(r.comparacion_propia_id) else None
        candidato=r.candidato_revision_misma_familia if pd.notna(r.candidato_revision_misma_familia) else None
        if ((estado=='referencia_trazada')!=(propia is not None)
                or (propia is not None and (propia not in referencias or comparaciones[propia]['origin_id']!=r.origen_id))
                or (candidato is not None and candidato not in referencias)):
            raise ErrorAsignacion('Perfil propio o candidato incompatibles con su origen/familia.')
        # Una excepción de cabecera prevalece aunque haya perfiles en esa familia.
        referencia=None
        if estado not in {'cabecera_en_revision','sin_cabecera'}:
            referencia=propia or candidato or (sorted(referencias)[0] if referencias else None)
            if referencia is None:
                raise ErrorAsignacion('Falta la montaña de la cabecera candidata que se pretende reutilizar.')
        fila={'origen_id':r.origen_id,'perfil_completo_del_punto_disponible':propia is not None,
              'montana_cabecera_candidata_disponible':referencia is not None,
              'comparacion_montana_candidata_id':referencia,
              'cabecera_montana_candidata':comparaciones[referencia]['head_label'] if referencia else None,
              'terminal_montana_candidata':comparaciones[referencia]['terminal_label'] if referencia else None,
              'tratamiento_cierre_geografico':acciones[estado],
              'piezas_pendientes_para_balance':pendientes[estado],
              'error_alimentador_acotado':False}
        for sentido in SENTIDOS.values():
            fila['longitud_montana_candidata_'+sentido+'_km']=largos.loc[(referencia,sentido)] if referencia else np.nan
            fila['separacion_candidato_familia_'+sentido+'_m']=np.nan
            fila['diferencia_cota_candidato_familia_'+sentido+'_m']=np.nan
        if candidato is not None:
            p=proyecciones.loc[proyecciones.origen_id.eq(r.origen_id)&proyecciones.comparacion_id.eq(candidato)]
            if len(p)!=2 or set(p.sentido)!=set(SENTIDOS.values()):
                raise ErrorAsignacion('El candidato de familia necesita sus dos proyecciones.')
            for _,s in p.iterrows():
                distancia=s.separacion_cartografica_m;delta=s.diferencia_cota_origen_proyeccion_m
                if pd.isna(distancia) or not np.isfinite(distancia) or distancia<0:
                    raise ErrorAsignacion('La separación cartográfica del candidato no es válida.')
                if pd.notna(delta) and not np.isfinite(delta):
                    raise ErrorAsignacion('La diferencia de cota del candidato no es finita.')
                fila['separacion_candidato_familia_'+s.sentido+'_m']=distancia
                fila['diferencia_cota_candidato_familia_'+s.sentido+'_m']=delta
        filas.append(fila)
    d=detalle.merge(pd.DataFrame(filas),on='origen_id',validate='one_to_one')
    f=familias.copy()
    for campo in ['perfil_completo_del_punto_disponible','montana_cabecera_candidata_disponible']:
        f['numero_subgrupos_'+campo]=f.grupo_reducido_id.map(d.groupby('grupo_reducido_id')[campo].sum()).astype(int)
    # Tres piezas de cobertura excluyentes: no mezclar montaña con viaje completo.
    base=demanda.merge(d[['origen_id','perfil_completo_del_punto_disponible','montana_cabecera_candidata_disponible']],on='origen_id',validate='many_to_one')
    base['pieza_geografica']=np.select([base.perfil_completo_del_punto_disponible,
        base.montana_cabecera_candidata_disponible],['perfil_del_punto','solo_montana_candidata'],default='sin_montana_utilizable')
    cobertura=[]
    for (colectivo,sentido),b in base.groupby(['colectivo','sentido'],sort=True):
        total=b[valor].sum();fila={'colectivo':colectivo,'sentido':sentido,'demanda_total_media57':total}
        for pieza in ['perfil_del_punto','solo_montana_candidata','sin_montana_utilizable']:
            cantidad=b.loc[b.pieza_geografica.eq(pieza),valor].sum()
            fila['demanda_pieza_'+pieza+'_media57']=cantidad
            fila['fraccion_pieza_'+pieza]=cantidad/total if total>0 else np.nan
        if not np.isclose(sum(v for k,v in fila.items() if k.startswith('demanda_pieza_')),total,atol=1e-8,rtol=0):
            raise ErrorAsignacion('La cobertura por piezas no conserva la demanda.')
        cobertura.append(fila)
    metadata={'decision':'D118','revision_de_cierre_realizada':True,'subgrupos':len(d),
        'perfiles_completos_del_punto':int(d.perfil_completo_del_punto_disponible.sum()),
        'montanas_de_cabecera_candidata':int(d.montana_cabecera_candidata_disponible.sum()),
        'cobertura_geografica_completa':bool(d.perfil_completo_del_punto_disponible.all()),
        'demanda_positiva_sin_perfil_completo':bool((base[valor].gt(0)&~base.perfil_completo_del_punto_disponible).any()),
        'perfil_asignado_por_proximidad':False,'error_alimentador_acotado':False,
        'energia_calculada':False,'representatividad_adoptada_para_balance':False,
        'unidad':'Viajes-persona medios de 57 matrices, no año, vehículos o ahorro.',
        'continuacion':'Resolver las representaciones geográficas pendientes con recorridos/perfiles o aproximaciones fundadas antes de continuar con actividad anual, conforme a D119. No habilita un balance completo ni atribuye energía cero a ausencias.'}
    return d,f,pd.DataFrame(cobertura),metadata

def revisar_cabeceras_de_estudio(origenes, demanda, correspondencia, centroides, zonas,
                                carreteras, catalogo, especificacion, montanas):
    """Proponer cabeceras de trabajo sin corregir la lectura fuente ni copiar accesos.

    La referencia territorial aproximada permanece distinta del punto propio.
    Demanda nula en la media publicada no prueba actividad o energía anual nulas.
    """
    from movilidad_teide.demanda.asignacion import _valores
    v='viajes_persona_media_57_matrices'
    required=[({'origen_id','corredor_candidato','stop_id_referencia','municipio_referencia','geometry'},origenes),
              ({'origen_id','colectivo','sentido',v},demanda),
              ({'origen_id','zona_id'},correspondencia),
              ({'zone_id','centroid_id','lon','lat'},centroides),
              ({'zona_id','geometry'},zonas),
              ({'via_nombre','tramo_inicio','tramo_final','geometry'},carreteras),
              ({'comparacion_id','sentido','tramo_cabecera_terminal_km',
                'referencia_coche_hasta_terminal_km'},montanas)]
    if any(not fields<=set(frame) for fields,frame in required):
        raise ErrorAsignacion('Faltan campos para revisar cabeceras de estudio.')
    if (origenes.origen_id.isna().any() or origenes.origen_id.duplicated().any()
            or zonas.zona_id.isna().any() or zonas.zona_id.duplicated().any()
            or correspondencia.zona_id.isna().any() or correspondencia.zona_id.duplicated().any()
            or set(correspondencia.origen_id)!=set(origenes.origen_id)
            or set(demanda.origen_id)!=set(origenes.origen_id)
            or demanda.duplicated(['origen_id','colectivo','sentido']).any()):
        raise ErrorAsignacion('La revisión necesita orígenes, zonas y demanda completos y únicos.')
    _valores(demanda,[v]);expected={(c,s) for c in SEGMENTOS for s in SENTIDOS.values()}
    if any(set(zip(b.colectivo,b.sentido))!=expected for _,b in demanda.groupby('origen_id')):
        raise ErrorAsignacion('Conservar cuatro colectivos y ambos sentidos en la revisión.')
    cols=[f'{p}_{s}' for p in SENTIDOS for s in SEGMENTOS];_valores(centroides,cols)
    if (centroides.duplicated(['zone_id','centroid_id']).any()
            or not np.isfinite(centroides[['lon','lat']].to_numpy(dtype=float)).all()
            or not centroides.lon.between(-180,180).all() or not centroides.lat.between(-90,90).all()):
        raise ErrorAsignacion('Los centroides necesitan claves y coordenadas válidas.')
    if (not isinstance(especificacion,dict) or not especificacion.get('decision')
            or not especificacion.get('hipotesis') or not isinstance(especificacion.get('casos'),list)
            or not especificacion['casos']):
        raise ErrorAsignacion('Falta la propuesta explícita de cabeceras de estudio.')
    metric=catalogo['metric_crs'];o=origenes.to_crs(metric);z=zonas.to_crs(metric);roads=carreteras.to_crs(metric)
    if (z.geometry.isna().any() or z.geometry.is_empty.any() or not z.geometry.is_valid.all()
            or roads.geometry.isna().any() or roads.geometry.is_empty.any()):
        raise ErrorAsignacion('Las geometrías fuente deben ser válidas y estar presentes.')
    refs=catalogo['origin_access_comparisons'];by_origin=o.set_index('origen_id');seen=set();rows=[]
    if montanas.duplicated(['comparacion_id','sentido']).any():
        raise ErrorAsignacion('Longitudes de referencia repetidas en la revisión.')
    _valores(montanas,['tramo_cabecera_terminal_km','referencia_coche_hasta_terminal_km'])
    for spec in especificacion['casos']:
        fields={'origen_id','corredor_fuente_esperado','tipo','comparacion_referencia_id',
                'vias_a_contrastar','fundamento','limitaciones','alternativas_comparacion_ids'}
        if not fields<=set(spec) or spec['origen_id'] not in by_origin.index or spec['origen_id'] in seen:
            raise ErrorAsignacion('Cada caso debe ser explícito, único y pertenecer a la demanda.')
        oid=spec['origen_id'];seen.add(oid);r=by_origin.loc[oid];kind=spec['tipo'];cid=spec['comparacion_referencia_id']
        if (r.corredor_candidato!=spec['corredor_fuente_esperado']
                or kind not in {'cabecera_propuesta','aproximacion_territorial','sin_demanda_positiva_media57'}
                or not isinstance(spec['vias_a_contrastar'],list) or not spec['vias_a_contrastar']
                or not set(spec['vias_a_contrastar'])<=set(roads.via_nombre)
                or not spec['fundamento'] or not spec['limitaciones']):
            raise ErrorAsignacion('La propuesta debe conservar la fuente y acreditar sus vías y límites.')
        if cid not in refs or not isinstance(spec['alternativas_comparacion_ids'],list) or not set(spec['alternativas_comparacion_ids'])<=set(refs):
            raise ErrorAsignacion('La cabecera y las alternativas necesitan referencias existentes.')
        ref=refs[cid];ref_origin=ref['origin_id']
        if ref_origin not in by_origin.index or ref_origin==oid:
            raise ErrorAsignacion('La referencia de contraste debe identificarse por separado del caso.')
        if not {'head_reference_anchor_id','terminal_reference_anchor_id','origin_reference_anchor_id'}<=set(ref):
            raise ErrorAsignacion('La referencia no identifica sus anclajes.')
        if any(ref[k] not in catalogo['anchors'] for k in ['head_reference_anchor_id','terminal_reference_anchor_id','origin_reference_anchor_id']):
            raise ErrorAsignacion('Los anclajes de la referencia deben existir en el maestro.')
        if kind=='aproximacion_territorial' and by_origin.loc[ref_origin].municipio_referencia!=r.municipio_referencia:
            raise ErrorAsignacion('La aproximación territorial debe conservar el municipio de referencia.')
        reference_point=by_origin.loc[ref_origin].geometry
        if reference_point is None or reference_point.is_empty:
            raise ErrorAsignacion('Falta el punto real de la referencia de contraste.')
        zones=correspondencia.loc[correspondencia.origen_id.eq(oid),'zona_id'];cg=centroides.loc[centroides.zone_id.isin(zones)].copy()
        if set(cg.zone_id)!=set(zones) or not set(zones)<=set(z.zona_id):
            raise ErrorAsignacion('Faltan centroides o polígonos de las zonas del caso.')
        dd=demanda.loc[demanda.origen_id.eq(oid)];sums=dd.groupby('sentido')[v].sum();weight=cg[cols].sum(axis=1)
        if not np.isclose(weight.sum(),dd[v].sum(),atol=1e-7,rtol=0):
            raise ErrorAsignacion('La demanda de centroides y subgrupo debe coincidir.')
        positive=bool(dd[v].gt(0).any());has_point=r.geometry is not None and not r.geometry.is_empty
        if ((kind=='sin_demanda_positiva_media57')!=(not positive)
                or (kind=='cabecera_propuesta' and not has_point)
                or (kind=='aproximacion_territorial' and (has_point or not positive))):
            raise ErrorAsignacion('El tratamiento no coincide con los datos de origen y demanda.')
        subset=montanas.loc[montanas.comparacion_id.eq(cid)]
        if len(subset)!=2 or set(subset.sentido)!=set(SENTIDOS.values()) or subset.tramo_cabecera_terminal_km.le(0).any():
            raise ErrorAsignacion('La referencia necesita sus dos longitudes de montaña positivas.')
        evidence=roads.loc[roads.via_nombre.isin(spec['vias_a_contrastar'])]
        row={'origen_id':oid,'revision_cabecera_realizada':True,'revision_cabecera_tipo':kind,
             'corredor_fuente_conservado':r.corredor_candidato,'cabecera_estudio_propuesta':ref['head_label'],
             'terminal_estudio_propuesto':ref['terminal_label'],'comparacion_cabecera_estudio_id':cid,
             'cabecera_estudio_anchor_id':ref['head_reference_anchor_id'],
             'punto_propio_conservado':has_point,'demanda_positiva_media57':positive,
             'propuesta_difiere_de_fuente':spec['corredor_fuente_esperado']!=by_origin.loc[ref_origin].corredor_candidato,
             'vias_a_contrastar':'; '.join(spec['vias_a_contrastar']),
             'registros_viales_disponibles':len(evidence),'cabecera_estudio_fundamento':spec['fundamento'],
             'cabecera_estudio_limitaciones':spec['limitaciones'],
             'alternativas_cabecera_estudio':'; '.join(refs[k]['head_label'] for k in spec['alternativas_comparacion_ids']),
             'referencia_territorial_aproximada_id':cid if kind=='aproximacion_territorial' else None,
             'referencia_territorial_aproximada_nombre':ref['origin_label'] if kind=='aproximacion_territorial' else None,
             'separacion_media_centroides_referencia_aproximada_m':np.nan,
             'separacion_max_centroides_referencia_aproximada_m':np.nan,
             'modelo_reparto_operativo_modificado':False,'perfil_propio_nuevo_calculado':False,
             'error_energetico_aproximacion_acotado':False,'actividad_anual_nula_demostrada':False,
             'balance_anual_habilitado':False}
        if kind=='aproximacion_territorial':
            # El área es contigua a la referencia costera; cuantificar separación sin inventar circulación.
            cp=gpd.GeoSeries(gpd.points_from_xy(cg.lon,cg.lat),crs=4326).to_crs(metric)
            dist=cp.distance(reference_point).to_numpy();positive_weights=weight.to_numpy()>0
            row['separacion_media_centroides_referencia_aproximada_m']=float(np.average(dist[positive_weights],weights=weight.to_numpy()[positive_weights]))
            row['separacion_max_centroides_referencia_aproximada_m']=float(dist[positive_weights].max())
        for sense in SENTIDOS.values():
            row['demanda_revisada_'+sense+'_media57']=float(sums.loc[sense])
            mountain=float(subset.loc[subset.sentido.eq(sense),'tramo_cabecera_terminal_km'].item())
            row['longitud_montana_propuesta_'+sense+'_km']=mountain if positive else np.nan
            row['longitud_referencia_aproximada_'+sense+'_km']=(float(subset.loc[subset.sentido.eq(sense),'referencia_coche_hasta_terminal_km'].item()) if kind=='aproximacion_territorial' else np.nan)
        rows.append(row)
    table=pd.DataFrame(rows)
    # El resultado amplía el diagnóstico: no sustituye las pertenencias o la demanda original.
    return table,{'decision':especificacion['decision'],'hipotesis':especificacion['hipotesis'],
        'casos_revisados':len(table),'cabeceras_propuestas':int(table.revision_cabecera_tipo.eq('cabecera_propuesta').sum()),
        'aproximaciones_territoriales':int(table.revision_cabecera_tipo.eq('aproximacion_territorial').sum()),
        'casos_sin_demanda_positiva_media57':int(table.revision_cabecera_tipo.eq('sin_demanda_positiva_media57').sum()),
        'fuente_y_pertenencias_modificadas':False,'nuevos_perfiles_calculados':False,
        'reparto_operativo_reasignado':False,'balance_anual_habilitado':False,
        'limite':'Elecciones geográficas propuestas y referencia aproximada explícita; no observación, asignación operativa ni distancias circulables derivadas de proximidad. Demanda media nula no acredita actividad anual nula.'}
