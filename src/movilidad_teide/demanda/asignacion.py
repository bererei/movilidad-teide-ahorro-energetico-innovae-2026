"""demanda: asignacion. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from rasterio.transform import Affine
from shapely.geometry import Point
from movilidad_teide.cartografia.extraccion import resolve_anchor
from movilidad_teide.demanda.asignacion_tipos import ErrorAsignacion
from movilidad_teide.demanda.asignacion_tipos import SEGMENTOS
from movilidad_teide.demanda.asignacion_tipos import SENTIDOS
from movilidad_teide.demanda.asignacion_tipos import PENDIENTE


def _valores(tabla, columnas):
    # Un dato ausente no se convierte en demanda cero.
    if not set(columnas).issubset(tabla.columns):
        raise ErrorAsignacion('Faltan columnas de demanda.')
    try:
        a = tabla[columnas].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ErrorAsignacion('La demanda debe ser numérica.') from exc
    if not np.isfinite(a).all() or (a < 0).any():
        raise ErrorAsignacion('La demanda contiene ausencias, infinitos o negativos.')



def demanda_por_origen(centroides, referencias):
    """Agregar el reparto modelizado del visor por zona, colectivo y sentido."""
    cols = [f'{p}_{s}' for p in SENTIDOS for s in SEGMENTOS]
    _valores(centroides, cols)
    if centroides[['zone_id', 'centroid_id']].isna().any().any() or centroides.duplicated(['zone_id', 'centroid_id']).any():
        raise ErrorAsignacion('Centroides sin clave o repetidos.')
    if referencias.zona_id.duplicated().any() or referencias.zona_id.isna().any():
        raise ErrorAsignacion('Las referencias de zona no son únicas.')
    if set(centroides.zone_id) & {187, 222}:
        raise ErrorAsignacion('La demanda externa incluye las zonas del Teide.')
    if not set(centroides.zone_id) <= set(referencias.zona_id):
        raise ErrorAsignacion('Hay orígenes sin identificar en la zonificación.')
    por_zona = centroides.groupby('zone_id')[cols].sum().reset_index().rename(columns={'zone_id': 'zona_id'})
    filas = []
    for prefijo, sentido in SENTIDOS.items():
        parte = por_zona.melt(id_vars='zona_id', value_vars=[f'{prefijo}_{s}' for s in SEGMENTOS],
                             var_name='colectivo', value_name='viajes_persona_media_57_matrices')
        parte['colectivo'] = parte.colectivo.str.removeprefix(prefijo + '_')
        parte['sentido'] = sentido
        filas.append(parte)
    salida = pd.concat(filas, ignore_index=True).merge(referencias, on='zona_id', validate='many_to_one')
    salida['colectivo_nombre'] = salida.colectivo.map(SEGMENTOS)
    v = 'viajes_persona_media_57_matrices'
    total = salida.groupby('sentido')[v].transform('sum')
    grupo = salida.groupby(['sentido', 'colectivo'])[v].transform('sum')
    salida['peso_en_sentido'] = salida[v].div(total.where(total.ne(0)))
    salida['peso_en_colectivo_sentido'] = salida[v].div(grupo.where(grupo.ne(0)))
    return salida

def demanda_por_corredor(perfiles, corredores):
    """Media aritmética de 57 matrices, conservando separados los sentidos."""
    _valores(perfiles, list(SEGMENTOS))
    claves = ['direccion', 'access_corridor', 'hora_servicio', 'matrix_index']
    if perfiles[claves].isna().any().any() or perfiles.duplicated(claves).any():
        raise ErrorAsignacion('Claves horarias ausentes o duplicadas.')
    if set(perfiles.direccion) != {'subida', 'bajada'} or set(perfiles.access_corridor) != set(corredores):
        raise ErrorAsignacion('Los cuatro corredores o los dos sentidos no coinciden.')
    if not perfiles.hora_servicio.isin(range(24)).all() or not perfiles.matrix_index.isin(range(57)).all():
        raise ErrorAsignacion('Hora o índice de matriz fuera de rango.')
    # Exigir los 57 índices en cada corredor/sentido evita tratar matrices ausentes como ceros.
    for _, bloque in perfiles.groupby(['access_corridor', 'direccion']):
        if set(bloque.matrix_index) != set(range(57)):
            raise ErrorAsignacion('Faltan matrices en un corredor o sentido.')
    diaria = perfiles.groupby(['access_corridor', 'direccion', 'matrix_index'])[list(SEGMENTOS)].sum()
    media = diaria.groupby(['access_corridor', 'direccion']).mean().reset_index()
    salida = media.melt(id_vars=['access_corridor', 'direccion'], value_vars=list(SEGMENTOS),
                        var_name='colectivo', value_name='viajes_persona_media_57_matrices')
    salida = salida.rename(columns={'access_corridor': 'corredor'})
    salida['sentido'] = salida.direccion.map({'subida': 'hacia_teide', 'bajada': 'desde_teide'})
    salida['colectivo_nombre'] = salida.colectivo.map(SEGMENTOS)
    salida['matrices'] = 57
    return salida.drop(columns='direccion')

def contrastar_totales(origenes, corredores):
    """Comprobar el total de cada colectivo sin forzar igualdad por corredor."""
    claves = ['sentido', 'colectivo']
    v = 'viajes_persona_media_57_matrices'
    a = origenes.groupby(claves)[v].sum().rename('origenes')
    b = corredores.groupby(claves)[v].sum().rename('perfiles')
    tabla = pd.concat([a, b], axis=1)
    if tabla.isna().any().any() or not np.allclose(tabla.origenes, tabla.perfiles, rtol=1e-5, atol=1e-3):
        raise ErrorAsignacion('Los totales por colectivo de las dos fuentes no son compatibles.')
    tabla['diferencia_redondeo'] = tabla.origenes - tabla.perfiles
    return tabla.reset_index()


def reconstruir_cabeceras(imagen, zonas, especificacion, desplazamiento=(0, 0)):
    """Leer el color dominante de cada polígono en una imagen georreferenciada.

    Es una reconstrucción del mapa de cabecera dominante, no una medición de
    recorridos ni recuperación de la asignación fraccionaria original.
    """
    a = np.asarray(imagen)
    if a.ndim != 3 or a.shape[2] < 3 or list(a.shape[:2]) != especificacion['forma_imagen']:
        raise ErrorAsignacion('La imagen no tiene el tamaño documentado.')
    rgb = np.round(a[:, :, :3] * 255).astype(np.uint8) if np.issubdtype(a.dtype, np.floating) else a[:, :, :3]
    etiquetas = np.zeros(rgb.shape[:2], dtype=np.uint8)
    catalogo = especificacion['colores']
    for i, color in enumerate(catalogo, 1):
        etiquetas[np.all(rgb == color['rgb'], axis=2)] = i
    # Excluir la leyenda evita confundir sus muestras de color con territorio.
    x0, y0, x1, y1 = especificacion['leyenda_pixeles']
    etiquetas[y0:y1, x0:x1] = 0
    yy, xx = np.where(etiquetas > 0)
    if not len(xx):
        raise ErrorAsignacion('No se reconocen los colores publicados.')
    caja = [int(xx.min()), int(yy.min()), int(xx.max()), int(yy.max())]
    if caja != especificacion['envolvente_pixeles']:
        raise ErrorAsignacion('La envolvente de la imagen ha cambiado; revisar la georreferencia.')
    if zonas.zona_id.duplicated().any() or zonas.zona_id.isna().any() or zonas.geometry.is_empty.any() or not zonas.is_valid.all():
        raise ErrorAsignacion('Revisar claves o geometrías de las zonas.')
    geo = zonas.to_crs(especificacion['crs_georreferencia'])
    xmin, ymin, xmax, ymax = geo.total_bounds
    izq, arriba, der, abajo = caja
    ax, ey = (xmax - xmin) / (der - izq), -(ymax - ymin) / (abajo - arriba)
    dx, dy = desplazamiento
    tr = Affine(ax, 0, xmin - (izq + .5 + dx) * ax,
                0, ey, ymax - (arriba + .5 + dy) * ey)
    # Los identificadores temporales consecutivos evitan depender del código numérico de zona.
    raster = rasterize(((g, i) for i, g in enumerate(geo.geometry, 1)),
                       out_shape=etiquetas.shape, transform=tr, fill=0, dtype='int32')
    n = len(catalogo) + 1
    cuentas = np.bincount((raster * n + etiquetas).ravel(), minlength=(len(geo) + 1) * n).reshape(-1, n)
    filas = []
    for i, zona in enumerate(geo.zona_id, 1):
        c = cuentas[i, 1:]
        pixeles = int(c.sum())
        dominante = int(c.argmax())
        pureza = float(c.max() / pixeles) if pixeles else 0.0
        color = catalogo[dominante]
        corredor = color.get('corredor')
        asignable = pixeles > 0 and pureza >= especificacion['pureza_minima'] and corredor is not None
        filas.append({'zona_id': zona, 'corredor_candidato': corredor if asignable else PENDIENTE,
                      'pixeles_color': pixeles, 'fraccion_color_dominante': pureza,
                      'muestra_pequena': pixeles < 20,
                      'estado_lectura': 'reconstruccion_cartografica_provisional' if asignable else 'sin_lectura_suficiente'})
    return pd.DataFrame(filas)

def construir_asignacion(origenes, lectura, catalogo):
    """Unir demanda y propuesta sin rellenar modos o demanda anual desconocidos."""
    if lectura.zona_id.duplicated().any() or not set(origenes.zona_id) <= set(lectura.zona_id):
        raise ErrorAsignacion('Lectura de cabeceras incompleta o duplicada.')
    salida = origenes.merge(lectura, on='zona_id', validate='many_to_one')
    conocidos = {c['corredor']: c for c in catalogo}
    if not set(salida.corredor_candidato) <= set(conocidos) | {PENDIENTE}:
        raise ErrorAsignacion('Cabecera candidata sin identificar.')
    for campo in ['cabecera', 'terminal']:
        salida[campo] = salida.corredor_candidato.map({k: v[campo] for k, v in conocidos.items()})
    # Mantener las ausencias: esta fuente no desagrega modo ni acredita transferencias.
    salida['modo_sin_actuacion'] = pd.NA
    salida['modo_hasta_cabecera_con_actuacion'] = pd.NA
    salida['fraccion_transferida'] = np.nan
    salida['viajes_persona_anuales'] = np.nan
    salida['opciones_con_actuacion'] = ('Coche con reserva; coche o transporte público hasta cabecera y lanzadera; '
                                       'servicios existentes; cambio de fecha o desistimiento por justificar')
    salida['alcance'] = 'Propuesta de cabecera dominante; no todos los viajes de la zona usan ese corredor'
    salida['fuente'] = 'Visor Teide: reparto espacial medio de 57 matrices y mapa publicado de Medianías'
    return salida

def contrastar_corredores(asignacion, publicado):
    """Mostrar diferencias, sin ajustar el mapa para hacerlo coincidir con las tablas."""
    k = ['sentido', 'colectivo', 'corredor']
    v = 'viajes_persona_media_57_matrices'
    a = asignacion.rename(columns={'corredor_candidato': 'corredor'}).groupby(k)[v].sum().rename('reconstruccion_dominante')
    b = publicado.groupby(k)[v].sum().rename('perfil_publicado')
    tabla = pd.concat([a, b], axis=1).reset_index()
    # Una cabecera sin lectura conserva su demanda; no equivale a cero en la fuente publicada.
    tabla.loc[tabla.corredor.eq(PENDIENTE), 'perfil_publicado'] = np.nan
    tabla['diferencia'] = tabla.reconstruccion_dominante - tabla.perfil_publicado
    return tabla

def resolver_puntos_cabecera(zonas, corredores, especificacion, catalogo):
    """Usar anclajes fijados o referencias del mapa, conservando su distinto estado."""
    geo = zonas.to_crs(especificacion['crs_georreferencia'])
    xmin, ymin, xmax, ymax = geo.total_bounds
    izq, arriba, der, abajo = especificacion['envolvente_pixeles']
    filas = []
    for corredor in corredores:
        if 'origin_anchor_id' in corredor:
            # Una cabecera fijada tiene un único origen: nunca se sustituye por un píxel.
            if 'pixel_referencia' in corredor:
                raise ErrorAsignacion('La cabecera tiene definiciones duplicadas: anclaje y píxel.')
            identificador = corredor['origin_anchor_id']
            if identificador not in catalogo.get('anchors', {}):
                raise ErrorAsignacion('No existe el anclaje de la cabecera fijada.')
            ficha = catalogo['anchors'][identificador]
            if ficha['type'] != 'coordinate':
                raise ErrorAsignacion('La cabecera fijada requiere un anclaje de coordenadas.')
            punto = resolve_anchor(identificador, ficha, {}, zonas.crs).geometry.iloc[0]
            # Tener coordenadas no convierte una referencia junto a TITSA en cabecera definitiva.
            if ficha.get('location_status') == 'provisional':
                tipo = 'provisional_desde_fuente'
                estado = ficha['selection_status']
            else:
                tipo = 'fijada_por_coordenadas'
                estado = 'Cabecera fijada por mi indicación; conexión viaria y perfil pendientes'
        else:
            px, py = corredor['pixel_referencia']
            punto = Point(xmin + (px - izq) * (xmax - xmin) / (der - izq),
                          ymax - (py - arriba) * (ymax - ymin) / (abajo - arriba))
            punto = gpd.GeoSeries([punto], crs=geo.crs).to_crs(zonas.crs).iloc[0]
            identificador = None
            tipo = 'aproximada_desde_mapa'
            estado = 'Referencia aproximada leída del mapa; no anclaje operativo'
        filas.append({'cabecera': corredor['cabecera'], 'corredor': corredor['corredor'],
                      'tipo_ubicacion': tipo, 'anchor_id': identificador,
                      'estado': estado, 'geometry': punto})
    return gpd.GeoDataFrame(filas, crs=zonas.crs)

def agrupar_origenes(asignacion):
    """Reducir la tabla a macrozona/corredor sin perder zonas, colectivos ni sentidos.

    La macrozona identifica territorio, no reparte personas por superficie.
    La zona de referencia es la de mayor demanda del grupo en ambos sentidos;
    solo ayuda a revisar futuros recorridos, no sustituye los demás orígenes.
    """
    v = 'viajes_persona_media_57_matrices'
    claves = ['zona_id', 'colectivo', 'sentido']
    campos = claves + [v, 'macrozona_id_principal', 'macrozona_principal',
                       'corredor_candidato', 'etiqueta_referencia']
    if not set(campos) <= set(asignacion.columns) or asignacion.empty:
        raise ErrorAsignacion('Faltan demanda o referencias para agrupar orígenes.')
    _valores(asignacion, [v])
    if asignacion[claves].isna().any().any() or asignacion.duplicated(claves).any():
        raise ErrorAsignacion('Las claves zona/colectivo/sentido deben ser únicas.')
    if set(asignacion.colectivo) != set(SEGMENTOS) or set(asignacion.sentido) != set(SENTIDOS.values()):
        raise ErrorAsignacion('Deben conservarse los cuatro colectivos y ambos sentidos.')
    if not asignacion.groupby('zona_id').size().eq(8).all():
        raise ErrorAsignacion('Una zona no contiene todas las combinaciones; no se rellenan ceros.')
    a = asignacion.copy()
    # Una referencia territorial ausente permanece como grupo explícito.
    a['macrozona_id_principal'] = a.macrozona_id_principal.astype('string').fillna('sin_referencia')
    a['macrozona_principal'] = a.macrozona_principal.fillna('Territorio sin referencia')
    a['corredor_candidato'] = a.corredor_candidato.fillna(PENDIENTE)
    a['etiqueta_referencia'] = a.etiqueta_referencia.fillna(a.zona_id.map(lambda z: f'Zona {z}'))
    atributos = ['macrozona_id_principal', 'macrozona_principal', 'corredor_candidato', 'etiqueta_referencia']
    if a.groupby('zona_id')[atributos].nunique(dropna=False).gt(1).any().any():
        raise ErrorAsignacion('Una zona cambia de referencia territorial o corredor entre colectivos/sentidos.')
    if a.groupby('macrozona_id_principal').macrozona_principal.nunique().gt(1).any():
        raise ErrorAsignacion('Una macrozona tiene nombres contradictorios.')
    a['grupo_origen_id'] = 'M' + a.macrozona_id_principal + '__' + a.corredor_candidato
    llaves = ['grupo_origen_id', 'colectivo', 'sentido']
    grupos = a.groupby(llaves, as_index=False).agg(
        macrozona=('macrozona_principal', 'first'),
        corredor_candidato=('corredor_candidato', 'first'),
        zonas_id=('zona_id', lambda s: ', '.join(map(str, sorted(s.unique())))),
        numero_zonas=('zona_id', 'nunique'),
        viajes_persona_media_57_matrices=(v, 'sum'),
    )
    # Elegir una única referencia del grupo para los dos sentidos y escenarios.
    pesos = a.groupby(['grupo_origen_id', 'zona_id'], as_index=False)[v].sum()
    referencias = pesos.sort_values([v, 'zona_id'], ascending=[False, True]).drop_duplicates('grupo_origen_id')
    nombres = a[['zona_id', 'etiqueta_referencia']].drop_duplicates().set_index('zona_id').etiqueta_referencia
    referencias['origen_referencia'] = referencias.zona_id.map(nombres)
    referencias = referencias.rename(columns={'zona_id': 'zona_referencia_id'})
    grupos = grupos.merge(referencias[['grupo_origen_id', 'zona_referencia_id', 'origen_referencia']],
                          on='grupo_origen_id', validate='many_to_one')
    grupos['colectivo_nombre'] = grupos.colectivo.map(SEGMENTOS)
    for keys, campo in [(['sentido'], 'peso_en_sentido'),
                        (['sentido', 'colectivo'], 'peso_en_colectivo_sentido')]:
        total = grupos.groupby(keys)[v].transform('sum')
        grupos[campo] = grupos[v].div(total.where(total.gt(0)))
    grupos['unidad'] = 'viajes-persona estimados: media de 57 matrices, sin anualizar'
    grupos['ambito'] = 'Demanda externa del Teide; origen territorial y corredor candidato'
    grupos['fuente'] = 'F035 — Visor Teide; F041 — zonificación OD; F051 — mapa de Medianías'
    grupos['estado'] = 'Agrupación de una propuesta cartográfica; asignación operativa pendiente'
    grupos['tratamiento_incertidumbre'] = (
        'Conservo todas las zonas y la demanda sin asignar. La cabecera dominante no acredita '
        'todos los recorridos de la zona; contrasto con perfiles numéricos. La zona de referencia '
        'no representa por sí sola todos los kilómetros del grupo. Modos y anualización pendientes.'
    )
    original = a.groupby(['colectivo', 'sentido'])[v].sum().sort_index()
    agrupado = grupos.groupby(['colectivo', 'sentido'])[v].sum().sort_index()
    if not np.allclose(original, agrupado, rtol=0, atol=1e-8):
        raise ErrorAsignacion('La agrupación pierde demanda de algún colectivo o sentido.')
    return a, grupos

def resumir_discrepancia_repartos(asignacion, publicado):
    """Comparar participaciones sin calibrar ni inferir una asignación origen-corredor.

    La mitad de la suma de diferencias absolutas es la mínima fracción que
    habría que reasignar para igualar repartos. No mide error real ni identifica
    qué zonas usan varios accesos. Cada fuente conserva su denominador.
    """
    contrastar_totales(asignacion, publicado)
    v = 'viajes_persona_media_57_matrices'
    _valores(asignacion, [v])
    _valores(publicado, [v])
    if publicado.corredor.isna().any() or publicado.corredor.eq(PENDIENTE).any():
        raise ErrorAsignacion('El perfil publicado debe identificar sus corredores.')
    conocidos = set(publicado.corredor)
    if not set(asignacion.corredor_candidato) <= conocidos | {PENDIENTE}:
        raise ErrorAsignacion('La propuesta contiene un corredor desconocido.')
    filas = []
    for sentido, a in asignacion.groupby('sentido'):
        b = publicado.loc[publicado.sentido.eq(sentido)]
        if a[v].sum() <= 0 or b[v].sum() <= 0:
            raise ErrorAsignacion('Comparar repartos exige totales positivos.')
        indice = sorted(conocidos | {PENDIENTE})
        ma = a.groupby('corredor_candidato')[v].sum().reindex(indice, fill_value=0)
        mb = b.groupby('corredor')[v].sum().reindex(indice, fill_value=0)
        diferencia = ma / ma.sum() - mb / mb.sum()
        filas.append({'sentido': sentido, 'total_propuesta': float(ma.sum()),
                      'total_perfil_publicado': float(mb.sum()),
                      'minima_fraccion_a_reasignar': float(diferencia.abs().sum() / 2),
                      'fraccion_sin_asignar': float(ma.loc[PENDIENTE] / ma.sum()),
                      'mayor_exceso_propuesta': diferencia.idxmax(),
                      'mayor_defecto_propuesta': diferencia.idxmin(),
                      'unidad': 'fracción de viajes-persona de cada reparto; no error ni intervalo',
                      'fuente': 'F035 — perfiles numéricos; F051 — mapa dominante reconstruido',
                      'estado': 'Diferencia cuantificada; asignación fraccionaria no identificada',
                      'tratamiento_incertidumbre': 'Conservo ambos repartos. No corrijo originales ni deduzco un cruce único a partir de sus marginales.'})
    return pd.DataFrame(filas)

def catalogo_cadenas_movilidad():
    """Cadenas alternativas antes/después, sin adjudicarles cantidades de demanda.

    Una fila describe qué cambia; no es otra copia de los viajes-persona.
    El catálogo se vincula a los grupos al justificar su reparto modal.
    """
    filas = [
        ('coche_reserva', 'Coche que continúa con reserva', 'Acceso directo',
         'Coche: origen → Teide', 'Coche con reserva: mismo origen → Teide',
         'Coches autorizados y ocupación por grupo', 'cupo_global; reparto_cupo; ocupacion_coche',
         'H034 — máximo global de 500 coches/día; H036 — reparto provisional del cupo',
         'El cupo no se aplica por acceso. Mantengo viajes de personas y coches por separado.'),
        ('coche_cabecera', 'Del coche directo a coche más lanzadera', 'Cuatro cabeceras candidatas',
         'Coche: origen → Teide', 'Coche: mismo origen → cabecera; lanzadera: cabecera → Teide',
         'Grupos completos transferidos, ocupación y modo hasta cabecera',
         'ocupacion_coche; transferencia_lanzadera; alimentacion_coche',
         'H022/H023 — accesos a cabeceras; F035 — Visor Teide; F040 — contexto OD',
         'Retirar el tramo de montaña no elimina los kilómetros en coche hasta cabecera. No transformo todo privado OD en coche.'),
        ('publico_cabecera', 'Del coche directo a transporte público más lanzadera', 'Cabeceras con alimentación por justificar',
         'Coche: origen → Teide', 'Transporte público: mismo origen → cabecera; lanzadera: cabecera → Teide',
         'Servicio utilizable, demanda, capacidad y refuerzos alimentadores',
         'transferencia_lanzadera; alimentacion_coche; ocupacion_coche',
         'H022/H023 — acceso a cabeceras; F045/F052 — GTFS y rutas TITSA',
         'Compruebo conexión y horario por origen; la existencia de TITSA en la isla no demuestra alimentación de todas las cabeceras.'),
        ('coche_titsa', 'Del coche a TITSA existente', 'Servicios 342 y 348; accesibilidad por origen pendiente',
         'Coche: origen → Teide', 'TITSA de acceso: mismo origen → Teide',
         'Transferencia efectiva de grupos, pasajeros y capacidad disponible',
         'ocupacion_coche; reparto específico a TITSA pendiente',
         'H032 — oferta TITSA constante; F045/F052 — horarios, rutas y paradas',
         'No confundo esta transferencia con transferencia_lanzadera. Más pasajeros pueden cambiar carga o exigir refuerzos.'),
        ('titsa_acceso', 'Viajes que ya utilizan TITSA de acceso', 'Líneas 342 y 348',
         'TITSA: origen → Teide', 'TITSA: mismo origen → Teide',
         'Pasajeros, carga y kilómetros existentes', 'H032; pasajeros y cargas pendientes',
         'H032 — oferta constante; F045/F052 — GTFS y trazados',
         'La constancia de horarios no demuestra energía constante ni permite contar estos pasajeros como coches retirados.'),
        ('excursiones', 'Excursiones privadas en guagua', 'Orígenes, accesos y destinos por justificar',
         'Guagua discrecional: origen → Teide', 'Guagua discrecional: mismo origen → Teide, salvo cambio justificado',
         'Guaguas, recorridos, ocupación y eventuales cambios', 'Actividad discrecional pendiente',
         'F035/F040 — modo privado agregado; metodología §4 — servicios existentes',
         'Separo las excursiones del coche antes de convertir personas en vehículos. No las cancelo por falta de datos.'),
        ('otros_servicios', 'Reparto, servicios y tránsito', 'Vehículos fuera de los grupos de visitantes por identificar',
         'Vehículo de servicio o tránsito: recorrido actual', 'Vehículo de servicio o tránsito: recorrido con actuación',
         'Actividad afectada, excepciones y recorridos', 'Actividad y condiciones de acceso pendientes',
         'F038 — categorías de aforo; metodología §§3–4 — actividad y excepciones',
         'No añado estos vehículos a los viajes-persona del visor ni identifico todos los pesados como guaguas.'),
        ('cambio_horario', 'Visita desplazada dentro del mismo año', 'Coches sujetos a reserva',
         'Coche: origen → Teide en la fecha inicial', 'Visita desde el mismo origen en otra hora o fecha del mismo año',
         'Reprogramación y modo finalmente utilizado', 'permanencia_min; franja_reserva_min; respuesta pendiente',
         'H034 — reserva y permanencia; metodología §4 — respuesta al acceso',
         'Conservo la visita anual una sola vez. Cambiar de fecha no equivale a eliminar su energía.'),
        ('visita_no_realizada', 'Visita desistida o desplazada fuera del año', 'Demanda inicial que no se realiza en el año evaluado',
         'Viaje que se realizaría sin actuación', 'No realiza esa visita en el año evaluado',
         'Personas y grupos que no viajan; efectos diferenciales pertinentes', 'Respuesta a restricciones pendiente',
         'H031/H034 — acceso condicionado; metodología §4 — viajes evitados',
         'Conservo esta demanda como no realizada; no la presento como pasajero de lanzadera ni la elimino de la conciliación.'),
        ('induccion', 'Visitas adicionales causadas por el sistema', 'Demanda adicional separada de la inicial',
         'La visita no se realizaría sin actuación', 'Viaje adicional: origen → cabecera/Teide según modo justificado',
         'Personas adicionales, modos, accesos y servicio necesario', 'induccion; modos de acceso pendientes',
         'Metodología §2.2 y §4 — inducción y accesos diferenciales',
         'No supongo inducción cero ni la resto de otras filas para mantener artificialmente igual demanda.'),
        ('titsa_interior', 'TITSA interior existente', 'Línea 341; enlaces con accesos por justificar',
         'TITSA 341: desplazamiento dentro del Parque', 'TITSA 341: desplazamiento dentro del Parque',
         'Expediciones, pasajeros, carga y enlaces', 'H032; pasajeros y cargas pendientes',
         'H032 — oferta constante; F045/F052 — GTFS y trazado 341',
         'Un embarque interior no es una visita nueva. No sumo 341 como otra línea de acceso.'),
        ('lanzadera_interior', 'Nueva lanzadera interior', 'Conexiones dentro del Parque pendientes de cerrar',
         'Desplazamiento interior según el modo de la visita sin actuación', 'Nueva lanzadera interior enlazada con la visita',
         'Transbordos, recorridos, oferta, carga y compatibilidad con 341', 'Oferta interior; demanda y tecnología pendientes',
         'F035 — diseño interior del visor; H035 — servicio nuevo anual constante',
         'Vinculo los embarques a la misma visita; no añado visitantes ni supongo que todos utilicen el interior.'),
    ]
    columnas = ['cadena_id', 'cadena', 'ambito', 'sin_actuacion', 'con_actuacion',
                'dato_necesario', 'parametros_o_decisiones', 'fuente', 'tratamiento_incertidumbre']
    t = pd.DataFrame(filas, columns=columnas)
    t['unidad'] = 'Cadena de viaje; sin cantidad de personas ni vehículos asignada'
    t['estado'] = 'Estructura para asignar; fracciones, actividad y recorridos pendientes'
    return t

def conciliar_aforos_anuales(anuales, mensuales, anio, puntos):
    """Conciliar categorías recibidas y sentidos sin convertir pasos en visitas.

    Verifico los doce meses contra cada total anual. Los decimales y el saldo
    entre sentidos se conservan: la aritmética no valida la clasificación física.
    """
    from calendar import isleap, monthrange

    claves = ['punto', 'sentido', 'tipo_vehiculo']
    calidad = ['horas_esperadas', 'horas_ausentes', 'valores_ausentes',
               'valores_negativos', 'marcas_fuera_calendario', 'valores_decimales']
    requeridas = ['anio', *claves, 'total_valores_fuente', *calidad]
    if not set(requeridas) <= set(anuales) or not set(requeridas + ['mes']) <= set(mensuales):
        raise ErrorAsignacion('Faltan totales o controles de calidad de aforos.')
    if isinstance(anio, bool) or not isinstance(anio, (int, np.integer)) or not 1 <= anio <= 9999:
        raise ErrorAsignacion('El año de conciliación debe ser un entero válido.')
    puntos = list(puntos)
    if not puntos or len(set(puntos)) != len(puntos):
        raise ErrorAsignacion('Los puntos de aforo deben ser explícitos y únicos.')
    a = anuales.loc[anuales.anio.eq(anio)].copy()
    m = mensuales.loc[mensuales.anio.eq(anio)].copy()
    esperado = {(p, s, t) for p in puntos for s in ['entrada', 'salida'] for t in ['coche', 'guagua']}
    if a[claves].isna().any().any() or a.duplicated(claves).any() or set(a[claves].itertuples(index=False, name=None)) != esperado:
        raise ErrorAsignacion('La base anual debe cubrir puntos, categorías y ambos sentidos una sola vez.')
    if m[claves + ['mes']].isna().any().any() or m.duplicated(claves + ['mes']).any():
        raise ErrorAsignacion('Claves mensuales ausentes o repetidas.')
    if set(m[claves + ['mes']].itertuples(index=False, name=None)) != {(*k, mes) for k in esperado for mes in range(1, 13)}:
        raise ErrorAsignacion('Deben estar presentes los doce meses de cada serie.')
    for tabla in [a, m]:
        _valores(tabla, ['total_valores_fuente', *calidad])
        if tabla[['horas_ausentes', 'valores_ausentes', 'valores_negativos', 'marcas_fuera_calendario']].ne(0).any().any():
            raise ErrorAsignacion('Hay incidencias de cobertura; no se completa una base anual silenciosamente.')
    horas = 24 * (366 if isleap(anio) else 365)
    if not a.horas_esperadas.eq(horas).all() or not m.horas_esperadas.eq(m.mes.map(lambda v: 24 * monthrange(anio, v)[1])).all():
        raise ErrorAsignacion('La cobertura declarada no corresponde al calendario del año.')
    suma = m.groupby(claves)[['total_valores_fuente', 'horas_esperadas', 'valores_decimales']].sum()
    a = a.set_index(claves).sort_index()
    if not np.allclose(a[suma.columns], suma.reindex(a.index), rtol=1e-12, atol=1e-7):
        raise ErrorAsignacion('Los meses no concilian con el resumen anual.')
    salida = a.total_valores_fuente.unstack('sentido').rename(columns={'entrada': 'entradas', 'salida': 'salidas'})
    decimales = a.valores_decimales.unstack('sentido')
    salida['valores_decimales_entrada'] = decimales.entrada
    salida['valores_decimales_salida'] = decimales.salida
    salida['saldo_entrada_menos_salida'] = salida.entradas - salida.salidas
    salida['saldo_relativo_a_entradas'] = salida.saldo_entrada_menos_salida.div(salida.entradas.where(salida.entradas.gt(0)))
    salida['peso_entradas_en_categoria'] = salida.entradas.div(salida.groupby('tipo_vehiculo').entradas.transform('sum').where(lambda v: v.gt(0)))
    salida['anio'] = anio
    salida['unidad'] = 'pasos de vehículos por el aforo en el año; no vehículos únicos ni visitas'
    salida['fuente'] = 'F038 — aforos corregidos recibidos; integración única en integracion_aforos_teide.ipynb'
    salida['estado'] = 'Suma anual conciliada; interpretación física y correcciones pendientes'
    salida = salida.reset_index()
    salida['desglose'] = np.where(salida.tipo_vehiculo.eq('guagua'),
        'TITSA, excursiones y posibles otros vehículos largos sin desagregar',
        'Categoría coche del productor; tránsito, reentradas y ocupantes sin identificar')
    return salida

def contexto_od_por_origen(od, correspondencia):
    """Mantener las nueve consultas separadas, sin sumar OD a la demanda del Visor."""
    claves = ['zona_id', 'id_matriz', 'sentido', 'modo']
    if od.duplicated(claves).any() or correspondencia.zona_id.duplicated().any():
        raise ErrorAsignacion('Las claves OD o de correspondencia no son únicas.')
    _valores(od, ['viajes'])
    if not set(od.modo) <= {'privado', 'todos_modos'} or not set(od.zona_id) <= set(correspondencia.zona_id):
        raise ErrorAsignacion('El contexto OD tiene modos o zonas fuera del ámbito.')
    a = od.merge(correspondencia[['zona_id', 'origen_id']], on='zona_id', validate='many_to_one')
    filas = []
    for (ident, matriz, sentido), b in a.groupby(['origen_id', 'id_matriz', 'sentido']):
        privado = b.loc[b.modo.eq('privado')]; todos = b.loc[b.modo.eq('todos_modos')]
        mismas = set(privado.zona_id) == set(todos.zona_id) and not todos.empty
        pv = privado.viajes.sum(min_count=1); tv = todos.viajes.sum(min_count=1)
        if mismas and pv > tv + 1e-6:
            raise ErrorAsignacion('Privado OD supera todos los modos para las mismas zonas.')
        filas.append({'origen_id':ident, 'id_matriz':matriz, 'sentido':sentido,
            'mes':b.mes.iloc[0], 'tipo_dia':b.tipo_dia.iloc[0],
            'viajes_privados_publicados':pv, 'viajes_todos_modos_publicados':tv,
            'zonas_con_privado':privado.zona_id.nunique(), 'zonas_con_todos_modos':todos.zona_id.nunique(),
            'mismas_zonas_en_ambos_modos':mismas,
            'fraccion_privado_solo_si_mismas_zonas':pv/tv if mismas and tv > 0 else np.nan,
            'numero_zonas_origen':int(correspondencia.origen_id.eq(ident).sum()),
            'cobertura_zonas_completa':mismas and len(todos)==int(correspondencia.origen_id.eq(ident).sum()),
            'alcance':'Contexto OD por consulta; privado incluye coche y bus discrecional; no reparto futuro a cabecera'})
    return pd.DataFrame(filas)
