"""demanda: titsa. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import geopandas as gpd
import numpy as np
import pandas as pd
from movilidad_teide.demanda.asignacion_tipos import ErrorAsignacion


def clasificar_pasajeros_titsa(viajes, paradas, paradas_341):
    """Clasificar tramos publicados sin confundir embarques y personas únicas.

    Las zonas 187/222 son el ámbito de telefonía, no el límite físico del Parque.
    La relación con las paradas de 341 es otra clasificación y se conserva aparte.
    Una parada o zona desconocida queda pendiente; no se convierte en exterior.
    """
    from movilidad_teide.demanda.asignacion import _valores
    campos = ['anio', 'mes', 'linea_id', 'viaje_hora', 'parada_entrada_id',
              'parada_salida_id', 'pasajeros_cantidad', 'fechas_calculadas',
              'linea_siguiente_id', 'linea_anterior_id']
    extras = ['tipo_matriz', 'tipo_dia', 'registro_fuente_id', 'archivo_fuente']
    if not set(campos + extras) <= set(viajes.columns) or viajes.empty:
        raise ErrorAsignacion('Faltan cantidades, periodo o procedencia de los pasajeros TITSA.')
    t = viajes.copy()
    for c in campos:
        t[c] = pd.to_numeric(t[c], errors='raise')
    _valores(t, campos)
    if (t[campos].to_numpy() % 1 != 0).any():
        raise ErrorAsignacion('Los identificadores, días y cantidades de esta fuente deben ser enteros.')
    if not t.linea_id.isin([341, 342, 348]).all() or not t.mes.between(1, 12).all() or not t.viaje_hora.between(0, 23).all():
        raise ErrorAsignacion('Línea, mes u hora fuera del ámbito publicado seleccionado.')
    if t[extras].isna().any().any() or t.registro_fuente_id.duplicated().any():
        raise ErrorAsignacion('Hay registros de fuente repetidos o sin procedencia.')
    if not t.tipo_matriz.isin(['laborables', 'no_laborables']).all():
        raise ErrorAsignacion('Tipo de matriz sin identificar; no se deduce del día de semana.')
    for c in campos:
        t[c] = t[c].astype('int64')
    dias_mes = pd.to_datetime(dict(year=t.anio, month=t.mes, day=1)).dt.days_in_month
    if not (t.fechas_calculadas.gt(0) & t.fechas_calculadas.le(dias_mes)).all():
        raise ErrorAsignacion('Días calculados no compatibles con el mes; no se anualizan cantidades.')
    if not {'parada_id', 'zona_OD_id'} <= set(paradas) or paradas.parada_id.isna().any() or paradas.parada_id.duplicated().any():
        raise ErrorAsignacion('El catálogo mensual de paradas no tiene identificadores únicos.')
    zonas = paradas.set_index('parada_id').zona_OD_id
    paradas_conocidas = set(paradas.parada_id)
    interiores = set(paradas_341)
    if not interiores:
        raise ErrorAsignacion('Falta el conjunto de referencia de paradas de la 341.')
    for lado, columna in [('origen', 'parada_entrada_id'), ('destino', 'parada_salida_id')]:
        t['zona_OD_' + lado] = t[columna].map(zonas)
        if 'zona_telefonia_id' in paradas:
            t['zona_catalogo_' + lado] = t[columna].map(paradas.set_index('parada_id').zona_telefonia_id)
    def relacion(a, b, conocidos_a, conocidos_b):
        resultado = np.select([~a & b, a & ~b, a & b],
                              ['hacia_ambito', 'desde_ambito', 'interno_ambito'], default='externo_ambito')
        return np.where(conocidos_a & conocidos_b, resultado, 'sin_identificar')
    t['relacion_ambito_OD'] = relacion(t.zona_OD_origen.isin([187, 222]), t.zona_OD_destino.isin([187, 222]),
                                        t.zona_OD_origen.notna(), t.zona_OD_destino.notna())
    t['relacion_paradas_341'] = relacion(t.parada_entrada_id.isin(interiores), t.parada_salida_id.isin(interiores),
                                        t.parada_entrada_id.isin(paradas_conocidas), t.parada_salida_id.isin(paradas_conocidas))
    t['tiene_transbordo'] = t.linea_anterior_id.ne(0) | t.linea_siguiente_id.ne(0)
    # Cantidad total mensual publicada: no multiplicar por fechas_calculadas.
    t['unidad'] = 'pasajeros/tramos publicados; no personas ni visitantes únicos'
    return t

def resumir_pasajeros_titsa(viajes):
    """Sumar cantidades publicadas preservando periodo, tipo de día y ámbitos."""
    from movilidad_teide.demanda.asignacion import _valores
    claves = ['anio', 'mes', 'linea_id', 'tipo_matriz', 'tipo_dia',
              'relacion_ambito_OD', 'relacion_paradas_341']
    if viajes[claves].isna().any().any() or viajes.registro_fuente_id.duplicated().any():
        raise ErrorAsignacion('Los pasajeros no conservan ámbito o identidad de fuente.')
    _valores(viajes, ['pasajeros_cantidad'])
    t = viajes.groupby(claves, as_index=False).agg(
        pasajeros_publicados=('pasajeros_cantidad', 'sum'),
        registros_fuente=('registro_fuente_id', 'size'),
        dias_calculados_min=('fechas_calculadas', 'min'),
        dias_calculados_max=('fechas_calculadas', 'max'),
    )
    if not np.isclose(t.pasajeros_publicados.sum(), viajes.pasajeros_cantidad.sum(), rtol=0, atol=1e-8):
        raise ErrorAsignacion('La agregación pierde o duplica pasajeros publicados.')
    t['unidad'] = 'pasajeros/tramos publicados en el mes; no visitas únicas'
    t['fuente'] = 'F057 — matrices mensuales de transporte público del Cabildo/TITSA, 2025'
    t['estado'] = 'Cantidad publicada; cobertura y paradas sin identificar se conservan por separado'
    t['tratamiento_incertidumbre'] = ('No multiplico por días ni sumo embarques como visitantes; '
        'conservo transbordos, tipos de día originales y zonas OD separadas de paradas 341. '
        'La falta de una matriz mensual no significa cero. No extrapolo automáticamente a 2028.')
    return t

def leer_demanda_publica_titsa(manifiesto, paradas_341, zonas_od):
    """Leer la captura mensual conservada y verificar fuentes antes de agregar.

    Los ZIP conservan la matriz insular; los JSON son respuestas originales
    filtradas de CKAN. Se guardan ambos formatos sin alterar sus cantidades.
    """
    from pathlib import Path
    import hashlib
    import json
    import zipfile

    manifiesto = Path(manifiesto)
    ficha = json.loads(manifiesto.read_text())
    raiz = manifiesto.parent
    if {m['mes'] for m in ficha['meses']} != set(range(1, 13)) or len(ficha['meses']) != 12:
        raise ErrorAsignacion('El inventario debe describir los doce meses, también las ausencias.')
    with (raiz / 'catalogo.json').open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != ficha['sha256_catalogo']:
            raise ErrorAsignacion('El catálogo de descarga ha cambiado.')
    todos, cobertura, inventario = [], [], []
    for mes in ficha['meses']:
        for f in mes['archivos']:
            with (raiz / f['archivo']).open('rb') as h:
                if hashlib.file_digest(h, 'sha256').hexdigest() != f['sha256']:
                    raise ErrorAsignacion('Una fuente mensual de TITSA ha cambiado.')
        cat = [f for f in mes['archivos'] if f['tipo'] == 'paradas_csv']
        lineas = [f for f in mes['archivos'] if f['tipo'] == 'lineas_json']
        if len(cat) != 1 or len(lineas) != 1:
            raise ErrorAsignacion('Falta el catálogo único mensual de paradas o líneas.')
        paradas = ubicar_paradas_titsa(pd.read_csv(raiz / cat[0]['archivo']), zonas_od)
        lineas = pd.DataFrame(json.loads((raiz / lineas[0]['archivo']).read_text())['lineas'])
        selec = lineas.loc[lineas.linea_id.isin([341,342,348])]
        if len(selec) != 3 or set(selec.linea_id) != {341,342,348} or not selec.linea_empresa.eq('TITSA').all():
            raise ErrorAsignacion('Los códigos de línea del catálogo no identifican TITSA 341/342/348.')
        for tipo in ['laborables', 'no_laborables']:
            archivos = [f for f in mes['archivos'] if f['tipo'].startswith('demanda_') and f['tipo_dia'] == tipo]
            # Exigir la cobertura completa de páginas conservadas de cada recurso API.
            for recurso in {f['recurso_id'] for f in archivos if f['tipo'] == 'demanda_api'}:
                paginas = [f for f in archivos if f['recurso_id'] == recurso]
                totales = {f['total_filtrado'] for f in paginas}
                if len(totales) != 1 or sum(f['registros'] for f in paginas) != next(iter(totales)):
                    raise ErrorAsignacion('Las páginas no conservan todo el resultado filtrado.')
            partes = []
            for f in archivos:
                leidos = 0
                if f['tipo'] == 'demanda_api':
                    datos = json.loads((raiz / f['archivo']).read_text())
                    if datos.get('success') is not True:
                        raise ErrorAsignacion('Respuesta de demanda CKAN inválida.')
                    bloque = pd.DataFrame(datos['result']['records'])
                    leidos = len(bloque)
                    if leidos != f['registros']:
                        raise ErrorAsignacion('La página no conserva su número de registros.')
                    if not bloque.empty:
                        if not bloque.linea_id.isin([341,342,348]).all():
                            raise ErrorAsignacion('La API no conservó el filtro de líneas.')
                        bloque['registro_fuente_id'] = f['recurso_id'] + ':' + bloque['_id'].astype(str)
                        partes.append(bloque)
                else:
                    with zipfile.ZipFile(raiz / f['archivo']) as z:
                        csvs = [v for v in z.namelist() if v.lower().endswith('.csv')]
                        if len(csvs) != 1:
                            raise ErrorAsignacion('El ZIP no contiene una única matriz CSV.')
                        with z.open(csvs[0]) as h:
                            for bloque in pd.read_csv(h, chunksize=200000):
                                leidos += len(bloque)
                                elegido = bloque.loc[bloque.linea_id.isin([341,342,348])].copy()
                                if not elegido.empty:
                                    elegido['registro_fuente_id'] = f['recurso_id'] + ':' + elegido.index.astype(str)
                                    partes.append(elegido)
                # Las páginas API comparten recurso; la clave original evita doble conteo.
                seleccionados = []
                for bloque in partes:
                    if 'archivo_fuente' not in bloque:
                        bloque['archivo_fuente'] = f['archivo']
                        seleccionados.append(bloque)
                inventario.append({'mes': mes['mes'], 'tipo_matriz': tipo, 'archivo': f['archivo'],
                                   'registros_leidos': leidos,
                                   'registros_seleccionados': sum(len(b) for b in seleccionados),
                                   'sha256': f['sha256']})
            if partes:
                t = pd.concat(partes, ignore_index=True)
                t['anio'], t['mes'], t['tipo_matriz'] = ficha['anio'], mes['mes'], tipo
                if 'tipo_dia' not in t:
                    if tipo != 'laborables':
                        raise ErrorAsignacion('No se deduce el tipo de día de una matriz no laboral.')
                    t['tipo_dia'] = 'Laborable (matriz)'
                t = clasificar_pasajeros_titsa(t, paradas, paradas_341)
                todos.append(t)
                dias = sorted(t.fechas_calculadas.unique().tolist())
                cantidad = int(t.pasajeros_cantidad.sum())
                identificadas = sorted(t.linea_id.unique().tolist())
            else:
                dias, cantidad, identificadas = [], None, []
            cobertura.append({'anio': ficha['anio'], 'mes': mes['mes'], 'tipo_matriz': tipo,
                'fuente_presente': bool(archivos), 'archivos': len(archivos),
                'paradas_con_zona_revisada': int(paradas.zona_OD_id.notna().sum()),
                'codigos_zona_diferentes': int(paradas.codigo_zona_publicado_difiere.sum()),
                'dias_calculados_declarados': ', '.join(map(str, dias)) if dias else None,
                'pasajeros_publicados': cantidad, 'lineas_con_registros': ', '.join(map(str, identificadas)),
                'estado': 'Fuente publicada; días no multiplicados' if archivos else 'Fuente ausente; no equivale a cero'})
    if not todos:
        raise ErrorAsignacion('No hay registros publicados de las líneas seleccionadas.')
    viajes = pd.concat(todos, ignore_index=True)
    if viajes.registro_fuente_id.duplicated().any():
        raise ErrorAsignacion('Se han repetido registros originales al unir meses o páginas.')
    return viajes, pd.DataFrame(cobertura), pd.DataFrame(inventario)

def ubicar_paradas_titsa(paradas, zonas_od):
    """Derivar la zona OD por coordenadas sin sustituir el código publicado.

    Los catálogos pueden usar otra versión de zonificación. Una coincidencia
    ambigua o coordenadas ausentes mantienen la zona derivada desconocida.
    """
    campos = ['parada_id', 'parada_longitud', 'parada_latitud', 'zona_telefonia_id']
    if not set(campos) <= set(paradas) or paradas.parada_id.duplicated().any() or paradas.parada_id.isna().any():
        raise ErrorAsignacion('Faltan coordenadas o claves únicas en el catálogo de paradas.')
    if 'zona_id' not in zonas_od or zonas_od.crs is None or zonas_od.zona_id.duplicated().any() or not zonas_od.is_valid.all():
        raise ErrorAsignacion('La zonificación OD no permite una correspondencia única y válida.')
    p = paradas.copy()
    lon = pd.to_numeric(p.parada_longitud, errors='coerce')
    lat = pd.to_numeric(p.parada_latitud, errors='coerce')
    validas = lon.between(-180, 180) & lat.between(-90, 90)
    puntos = gpd.GeoDataFrame(p.loc[validas, ['parada_id']].copy(),
        geometry=gpd.points_from_xy(lon[validas], lat[validas]), crs=4326).to_crs(zonas_od.crs)
    cruce = gpd.sjoin(puntos, zonas_od[['zona_id', 'geometry']], how='left', predicate='intersects')
    unicos = cruce.loc[cruce.zona_id.notna()].groupby('parada_id').filter(lambda t: len(t) == 1)
    p['zona_OD_id'] = p.parada_id.map(unicos.set_index('parada_id').zona_id)
    p['zona_OD_estado'] = np.where(p.zona_OD_id.notna(), 'Identificada por coordenadas', 'Sin correspondencia espacial única')
    p['codigo_zona_publicado_difiere'] = (p.zona_telefonia_id.notna() & p.zona_OD_id.notna()
                                         & p.zona_telefonia_id.ne(p.zona_OD_id))
    return p

def cribar_conexiones_titsa(origenes, cabeceras, paradas, horarios, trips, rutas, calendario, numero_paradas=2):
    """Buscar directos con orden y calendario; no validar transbordos o regreso útil.

    Las paradas próximas a cabecera son referencias cartográficas. Un directo
    hasta ellas no demuestra acceso al recinto ni compatibilidad con lanzaderas.
    Solo se admite el calendario explícito de adiciones del fichero conservado.
    """
    if not isinstance(numero_paradas, int) or isinstance(numero_paradas, bool) or numero_paradas < 1:
        raise ErrorAsignacion('El número de referencias próximas debe ser entero positivo.')
    if calendario.duplicated(['service_id', 'date']).any() or not calendario.exception_type.astype(str).eq('1').all():
        raise ErrorAsignacion('Revisar calendario GTFS: se requieren adiciones explícitas únicas.')
    if trips.trip_id.duplicated().any() or rutas.route_id.duplicated().any():
        raise ErrorAsignacion('Claves GTFS duplicadas.')
    t = trips.copy(); t[['trip_id','service_id','route_id']] = t[['trip_id','service_id','route_id']].astype(str)
    cal = calendario.copy(); cal['service_id'] = cal.service_id.astype(str)
    fechas = pd.to_datetime(cal.date.astype(str), format='%Y%m%d', errors='raise')
    cal['fecha'] = fechas.dt.strftime('%Y-%m-%d')
    if not set(t.route_id) <= set(rutas.route_id.astype(str)):
        raise ErrorAsignacion('Un trip GTFS no tiene línea identificada.')
    activos = t.loc[t.service_id.isin(cal.service_id)]
    p = paradas.to_crs(cabeceras.crs).copy(); p['stop_id'] = p.stop_id.astype(str)
    if p.stop_id.duplicated().any() or cabeceras.corredor.duplicated().any():
        raise ErrorAsignacion('Paradas o cabeceras duplicadas.')
    referencias = []
    for h in cabeceras.itertuples():
        cercanas = p.assign(distancia=p.geometry.distance(h.geometry)).sort_values(['distancia','stop_id']).head(numero_paradas)
        for i, q in enumerate(cercanas.itertuples(), 1):
            referencias.append({'corredor':h.corredor, 'cabecera':h.cabecera, 'orden_cercania':i,
                'stop_id':q.stop_id,'stop_name':q.stop_name,'separacion_cabecera_m':q.distancia,
                'acceso_cabecera_validado':False,'geometry':q.geometry})
    ref = gpd.GeoDataFrame(referencias, crs=cabeceras.crs)
    filas_origen = []
    for o in origenes.loc[origenes.geometry.notna()].to_crs(cabeceras.crs).itertuples():
        cercanas = p.assign(distancia=p.geometry.distance(o.geometry)).sort_values(['distancia','stop_id']).head(numero_paradas)
        for i,q in enumerate(cercanas.itertuples(),1):
            filas_origen.append({'origen_id':o.origen_id,'orden_cercania':i,'stop_id':q.stop_id,
                'stop_name':q.stop_name,'separacion_origen_m':q.distancia,'enlace_peatonal_validado':False,'geometry':q.geometry})
    ref_origen = gpd.GeoDataFrame(filas_origen,columns=['origen_id','orden_cercania','stop_id','stop_name','separacion_origen_m','enlace_peatonal_validado','geometry'],crs=cabeceras.crs)
    st = horarios.copy(); st[['trip_id','stop_id']] = st[['trip_id','stop_id']].astype(str)
    st = st.loc[st.trip_id.isin(activos.trip_id)]
    relevantes = set(ref.stop_id) | set(ref_origen.stop_id)
    st = st.loc[st.stop_id.isin(relevantes)].copy()
    if st.duplicated(['trip_id','stop_sequence']).any():
        raise ErrorAsignacion('El orden de paradas GTFS contiene claves repetidas.')
    st['stop_sequence'] = pd.to_numeric(st.stop_sequence, errors='raise')
    if not np.isfinite(st.stop_sequence).all() or st.stop_sequence.lt(0).any() or st.stop_sequence.mod(1).ne(0).any():
        raise ErrorAsignacion('El orden de paradas GTFS debe ser entero no negativo.')
    for campo in ['arrival_time', 'departure_time']:
        partes = st[campo].astype(str).str.extract(r'^(\d+):([0-5]\d):([0-5]\d)$')
        if partes.isna().any().any():
            raise ErrorAsignacion('Faltan horas GTFS válidas para las conexiones.')
        st[campo+'_s'] = partes.astype(int).to_numpy() @ np.array([3600,60,1])
    # Ausente significa servicio regular en esta exportación; las restricciones explícitas se respetan.
    for campo in ['pickup_type','drop_off_type']:
        st[campo] = pd.to_numeric(st[campo] if campo in st else pd.Series(0,index=st.index),errors='raise').fillna(0)
        if not st[campo].isin([0,1,2,3]).all():
            raise ErrorAsignacion('Restricción GTFS de embarque/desembarque desconocida.')
    por_parada = {k:b for k,b in st.groupby('stop_id')}
    nombres = rutas.set_index(rutas.route_id.astype(str)).route_short_name.astype(str).to_dict()
    dias_servicio = cal.groupby('service_id').fecha.agg(set).to_dict()
    resumen = []; soluciones = []
    for o in origenes.itertuples():
        refs = ref.loc[ref.corredor.eq(o.corredor_candidato)]
        refs_origen = ref_origen.loc[ref_origen.origen_id.eq(o.origen_id)]
        dias = {}; temporal = []
        for sentido in ['hacia_cabecera','desde_cabecera']:
            encontrados = []
            for q in refs.itertuples():
                for qo in refs_origen.itertuples():
                    ori, des = (qo.stop_id,q.stop_id) if sentido=='hacia_cabecera' else (q.stop_id,qo.stop_id)
                    if ori==des or ori not in por_parada or des not in por_parada:
                        continue
                    pares = por_parada[ori].merge(por_parada[des],on='trip_id',suffixes=('_origen','_destino'))
                    pares = pares.loc[(pares.stop_sequence_origen < pares.stop_sequence_destino) &
                        (pares.arrival_time_s_destino >= pares.departure_time_s_origen) &
                        pares.pickup_type_origen.eq(0) & pares.drop_off_type_destino.eq(0)]
                    if pares.empty:continue
                    pares = pares.merge(activos[['trip_id','route_id','service_id']],on='trip_id',validate='many_to_one')
                    pares['stop_id_cabecera'] = q.stop_id
                    pares['stop_id_referencia_origen'] = qo.stop_id
                    encontrados.append(pares)
            b = pd.concat(encontrados,ignore_index=True) if encontrados else pd.DataFrame()
            dias[ sentido ] = set().union(*(dias_servicio[x] for x in b.service_id.unique())) if not b.empty else set()
            lineas = sorted({nombres[x] for x in b.route_id.unique()}) if not b.empty else []
            temporal.append({'origen_id':o.origen_id,'sentido':sentido,'corredor_candidato':o.corredor_candidato,
                'lineas_directas':', '.join(lineas) if lineas else None,
                'variantes_trip_directas':b.trip_id.nunique() if not b.empty else 0,
                'dias_con_directo_en_calendario':len(dias[sentido]),
                'origen_coincide_referencia_cabecera':str(o.stop_id_referencia) in set(refs.stop_id),
                'estado':('Directo regular candidato hasta referencia próxima; horario y enlace por revisar' if not b.empty else
                          'Sin directo regular en estas referencias; revisar otras paradas y transbordos') if not refs.empty and pd.notna(o.stop_id_referencia) else 'Punto o cabecera sin referencia; conexión pendiente',
                'regreso_util_validado':False,'fuente':'F045 — GTFS conservado; oferta programada 2026–2027, no frecuencia anual ni demanda observada'})
            if b.empty:continue
            for (ruta, parada, parada_origen), grupo in b.groupby(['route_id','stop_id_cabecera','stop_id_referencia_origen']):
                fechas_ruta = set().union(*(dias_servicio[x] for x in grupo.service_id.unique()))
                salida = grupo.sort_values('departure_time_s_origen')
                soluciones.append({'origen_id':o.origen_id,'sentido':sentido,'linea':nombres[ruta],
                    'route_id':ruta,'stop_id_origen_representativo':o.stop_id_referencia,'stop_id_uso_gtfs_origen':parada_origen,'stop_id_cabecera':parada,
                    'variantes_trip':grupo.trip_id.nunique(),'service_ids':', '.join(sorted(grupo.service_id.unique())),
                    'dias_en_calendario':len(fechas_ruta),'fecha_primera':min(fechas_ruta),'fecha_ultima':max(fechas_ruta),
                    'primera_salida_catalogada':salida.departure_time_origen.iloc[0],
                    'ultima_salida_catalogada':salida.departure_time_origen.iloc[-1],
                    'alcance':'Extremos de catálogo entre variantes; no frecuencia diaria ni horario de una fecha elegida'})
        comunes = len(dias['hacia_cabecera'] & dias['desde_cabecera'])
        for fila in temporal:fila['dias_con_directos_ambos_sentidos']=comunes
        resumen.extend(temporal)
    columnas = ['origen_id','sentido','linea','route_id','stop_id_origen_representativo','stop_id_uso_gtfs_origen','stop_id_cabecera',
                'variantes_trip','service_ids','dias_en_calendario','fecha_primera','fecha_ultima',
                'primera_salida_catalogada','ultima_salida_catalogada','alcance']
    return ref, ref_origen, pd.DataFrame(resumen), pd.DataFrame(soluciones,columns=columnas)

def referencias_velocidad_gtfs(archivo, lineas=('341','342','348')):
    """Contrastar distancias de shapes completos con tiempos programados del GTFS.

    Son referencias del servicio existente, no velocidades observadas, medias
    por tramo o tiempos de futuras lanzaderas. No convertir trips a oferta diaria.
    """
    from zipfile import ZipFile
    from pyproj import Geod
    import re
    tables = {}
    with ZipFile(archivo) as z:
        for name in ['routes','trips','stop_times','shapes','stops']:
            if z.namelist().count(name+'.txt') != 1:
                raise ErrorAsignacion('El GTFS debe contener una tabla única de '+name)
            with z.open(name+'.txt') as stream:
                tables[name] = pd.read_csv(stream,dtype=str,keep_default_na=False)
    required = {'routes':['route_id','route_short_name'],
        'trips':['trip_id','route_id','service_id','shape_id','trip_headsign'],
        'stop_times':['trip_id','stop_sequence','stop_id','arrival_time','departure_time'],
        'shapes':['shape_id','shape_pt_sequence','shape_pt_lon','shape_pt_lat'],
        'stops':['stop_id','stop_name','stop_lon','stop_lat']}
    for name,columns in required.items():
        if not set(columns) <= set(tables[name]):
            raise ErrorAsignacion('Faltan campos GTFS en '+name)
    routes = tables['routes'].loc[tables['routes'].route_short_name.isin(lineas)].copy()
    if set(routes.route_short_name) != set(lineas) or routes.route_id.duplicated().any():
        raise ErrorAsignacion('Falta una línea seleccionada o sus route_id no son únicos.')
    trips = tables['trips'].loc[tables['trips'].route_id.isin(routes.route_id)].copy()
    if trips.empty or trips.trip_id.duplicated().any() or trips.trip_id.eq('').any():
        raise ErrorAsignacion('Los trips seleccionados deben estar presentes y ser únicos.')
    times = tables['stop_times'].loc[tables['stop_times'].trip_id.isin(trips.trip_id)].copy()
    times['secuencia'] = pd.to_numeric(times.stop_sequence,errors='raise')
    if (times.duplicated(['trip_id','secuencia']).any() or (times.secuencia % 1 != 0).any()
            or (times.secuencia < 0).any()):
        raise ErrorAsignacion('Secuencias de parada no válidas o duplicadas.')
    stops = tables['stops']
    if stops.stop_id.duplicated().any() or not set(times.stop_id) <= set(stops.stop_id):
        raise ErrorAsignacion('Paradas ausentes o no únicas.')
    stops = stops.set_index('stop_id')
    geod = Geod(ellps='WGS84'); shapes = {}
    for ident in trips.shape_id.unique():
        shape = tables['shapes'].loc[tables['shapes'].shape_id.eq(ident)].copy()
        if len(shape)<2:
            raise ErrorAsignacion('Falta un shape completo del servicio seleccionado.')
        shape['secuencia'] = pd.to_numeric(shape.shape_pt_sequence,errors='raise')
        if shape.secuencia.duplicated().any() or (shape.secuencia % 1 != 0).any():
            raise ErrorAsignacion('Secuencia de puntos de shape no válida.')
        shape = shape.sort_values('secuencia')
        xy = shape[['shape_pt_lon','shape_pt_lat']].to_numpy(dtype=float)
        if not np.isfinite(xy).all() or (np.abs(xy[:,0])>180).any() or (np.abs(xy[:,1])>90).any():
            raise ErrorAsignacion('Coordenadas del shape no válidas.')
        length = geod.line_length(xy[:,0],xy[:,1])
        if length<=0:
            raise ErrorAsignacion('Shape de longitud nula.')
        shapes[ident] = (xy,length)
    def seconds(value):
        if value=='':return np.nan
        if not re.fullmatch(r'\d{2,}:[0-5]\d:[0-5]\d',value):
            raise ErrorAsignacion('Hora GTFS no válida; no se interpreta como cero.')
        h,m,s = map(int,value.split(':'));return h*3600+m*60+s
    rows=[]
    for trip in trips.itertuples(index=False):
        tt = times.loc[times.trip_id.eq(trip.trip_id)].sort_values('secuencia')
        if len(tt)<2:
            raise ErrorAsignacion('Un trip tiene menos de dos paradas.')
        a,b=tt.iloc[0],tt.iloc[-1];aa,bb=stops.loc[a.stop_id],stops.loc[b.stop_id]
        coords=np.array([aa.stop_lon,aa.stop_lat,bb.stop_lon,bb.stop_lat],dtype=float)
        if not np.isfinite(coords).all() or abs(coords[0])>180 or abs(coords[2])>180 or abs(coords[1])>90 or abs(coords[3])>90:
            raise ErrorAsignacion('Coordenadas de paradas no válidas.')
        arrivals=tt.arrival_time.map(seconds).to_numpy();departures=tt.departure_time.map(seconds).to_numpy()
        complete=np.isfinite(arrivals).all() and np.isfinite(departures).all()
        chronological=complete and (departures>=arrivals).all() and (arrivals[1:]>=departures[:-1]).all()
        duration=arrivals[-1]-departures[0] if chronological else np.nan
        valid=chronological and duration>0
        xy,length=shapes[trip.shape_id]
        rows.append({'trip_id':trip.trip_id,'service_id':trip.service_id,'route_id':trip.route_id,
            'linea':routes.set_index('route_id').loc[trip.route_id,'route_short_name'],
            'shape_id':trip.shape_id,'destino_publicado':trip.trip_headsign,
            'stop_id_origen':a.stop_id,'origen':aa.stop_name,'stop_id_destino':b.stop_id,'destino':bb.stop_name,
            'salida_programada':a.departure_time,'llegada_programada':b.arrival_time,
            'longitud_shape_completo_km':length/1000,'duracion_programada_min':duration/60 if valid else np.nan,
            'velocidad_referencia_kmh':length/duration*3.6 if valid else np.nan,
            'separacion_inicio_shape_parada_m':geod.inv(xy[0,0],xy[0,1],coords[0],coords[1])[2],
            'separacion_fin_shape_parada_m':geod.inv(xy[-1,0],xy[-1,1],coords[2],coords[3])[2],
            'estado_tiempo':'programado_completo' if valid else 'pendiente_o_incoherente; sin velocidad calculada',
            'alcance':'Shape completo y horario existente; no media observada o asignada a nuevos recorridos'})
    detail=pd.DataFrame(rows)
    summary=detail.groupby(['linea','shape_id','origen','destino'],as_index=False).agg(
        registros_trip=('trip_id','size'),tiempos_validos=('velocidad_referencia_kmh','count'),
        longitud_shape_completo_km=('longitud_shape_completo_km','first'),
        minutos_min=('duracion_programada_min','min'),minutos_max=('duracion_programada_min','max'),
        velocidad_min_kmh=('velocidad_referencia_kmh','min'),velocidad_max_kmh=('velocidad_referencia_kmh','max'),
        separacion_inicio_shape_parada_m=('separacion_inicio_shape_parada_m','max'),
        separacion_fin_shape_parada_m=('separacion_fin_shape_parada_m','max'))
    summary['alcance']='Referencias programadas por shape; registros_trip no son expediciones al día'
    return detail,summary
