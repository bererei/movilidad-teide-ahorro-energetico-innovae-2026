"""Demanda captable y oferta de Medianías, reproducidas del Visor Teide.

El p85 dimensiona un servicio; no es una demanda anual ni acredita cambio modal.
La lanzadera interior sirve a las mismas visitas, sin añadir entradas al Parque.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from movilidad_teide.demanda.asignacion_tipos import SEGMENTOS


CAPTACION = dict(zip(SEGMENTOS, ['captacion_extranjero', 'captacion_nacional',
    'captacion_local', 'captacion_frecuente']))


def referencias_dimensionamiento(root):
    """Leer referencias publicadas inalteradas, solo al ampliar/crear el libro."""
    from pathlib import Path
    import json
    import re
    root = Path(root)
    base = root / 'data/bronze/documentacion/visor_teide/20261016T154507Z_a35edd7a'
    s = (base / 'coeficientes_servicio_teide.js').read_text()
    marca = 'window.TEIDE_COEF_APP_DATA_BY_ARCH = '
    datos, _ = json.JSONDecoder().raw_decode(s[s.index(marca) + len(marca):])
    meta = datos['medianias']['meta']
    publicado = json.loads((root / 'data/silver/movilidad/visor_teide/20261016T154509Z_f7cda5fc/parametros_publicados.json').read_text())
    operacion = publicado['operacion_costes_publicados']
    horas = re.search(r'const sharedService = \{start: (\d+), end: (\d+)\}', s)
    p = re.search(r'return percentile\(matrixTotals, ([\d.]+)\)', s)
    if horas is None or p is None or set(meta['defaults']) != set(CAPTACION):
        raise ErrorDimensionamiento('La estructura del simulador requiere revisión.')
    v = {CAPTACION[g]: meta['defaults'][g] / 100 for g in CAPTACION}
    v.update(percentil_diseno=float(p[1]), umbral_demanda=meta['min_demand'],
        hora_inicio_acceso=int(horas[1]), hora_fin_acceso=int(horas[2]),
        regulacion_min=operacion['layoverMin'], reserva_flota=operacion['vehicleReserveFactor'],
        hora_inicio_interior=operacion['shuttle']['start'], hora_fin_interior=operacion['shuttle']['end'],
        min_buses_hora_interior=operacion['shuttle']['minBusesHour'],
        min_ida_interior=operacion['shuttle']['eastWestMin'], min_vuelta_interior=operacion['shuttle']['westEastMin'],
        origen_oferta='Simulador de captación', fraccion_captados_coche=None)
    return v


class ErrorDimensionamiento(ValueError):
    """Entradas incompletas o incompatibles con el servicio a dimensionar."""


def _numero(datos, clave, minimo=0, maximo=None, entero=False):
    valor = datos.get(clave)
    if isinstance(valor, (bool, np.bool_)) or not isinstance(valor, (int, float, np.integer, np.floating)):
        raise ErrorDimensionamiento(f'Falta un valor numérico elegido para {clave}.')
    if not np.isfinite(valor) or valor < minimo or (maximo is not None and valor > maximo) or (entero and valor != int(valor)):
        raise ErrorDimensionamiento(f'Valor fuera del dominio para {clave}.')
    return float(valor)


def dimensionar_medianias(perfiles, rutas, valores):
    """Aplicar captación antes del percentil y recalcular expediciones y flota.

    Las observaciones ausentes de una celda horaria no se rellenan: se conserva
    exactamente el tratamiento del JavaScript publicado y se muestra su número.
    Los tiempos/distancias siguen siendo los del diseño, no trazados validados.
    """
    columnas = ['direccion', 'access_corridor', 'hora_servicio', 'matrix_index', *SEGMENTOS]
    necesarias = ['corredor', 'punto', 'min_subida_modelo', 'min_bajada_modelo', 'km_elegidos']
    if not set(columnas) <= set(perfiles) or not set(necesarias) <= set(rutas) or perfiles.empty or rutas.empty:
        raise ErrorDimensionamiento('Faltan perfiles o parámetros de los recorridos.')
    a = perfiles[columnas].copy()
    claves = columnas[:4]
    if a[claves].isna().any().any() or a.duplicated(claves).any() or rutas.corredor.duplicated().any() or rutas.punto.duplicated().any():
        raise ErrorDimensionamiento('Claves de perfiles o recorridos ausentes/repetidas.')
    if set(a.direccion) != {'subida', 'bajada'} or set(a.access_corridor) != set(rutas.corredor):
        raise ErrorDimensionamiento('Corredores o sentidos incompletos.')
    if not a.hora_servicio.isin(range(24)).all() or not a.matrix_index.isin(range(57)).all():
        raise ErrorDimensionamiento('Hora o índice de matriz fuera del catálogo publicado.')
    for _, bloque in a.groupby(['access_corridor', 'direccion']):
        if set(bloque.matrix_index) != set(range(57)):
            raise ErrorDimensionamiento('Faltan matrices en un corredor/sentido.')
    for tabla, campos in [(a, list(SEGMENTOS)), (rutas, necesarias[2:])]:
        try:
            numeros = tabla[campos].to_numpy(dtype=float)
        except (ValueError, TypeError) as exc:
            raise ErrorDimensionamiento('Demanda, tiempos y distancias deben ser numéricos.') from exc
        if not np.isfinite(numeros).all() or (numeros < 0).any():
            raise ErrorDimensionamiento('Demanda o recorridos con ausencias/negativos.')
    if rutas[necesarias[2:]].le(0).any().any():
        raise ErrorDimensionamiento('Tiempos y distancias deben ser positivos.')
    coef = {g: _numero(valores, k, 0, 1) for g, k in CAPTACION.items()}
    percentil = _numero(valores, 'percentil_diseno', .01, 1)
    plazas = _numero(valores, 'plazas_guagua', 1, entero=True)
    ocupacion = _numero(valores, 'ocupacion_diseno', .000001, 1)
    capacidad = plazas * ocupacion
    umbral = _numero(valores, 'umbral_demanda')
    inicio = int(_numero(valores, 'hora_inicio_acceso', 0, 23, True))
    fin = int(_numero(valores, 'hora_fin_acceso', 0, 23, True))
    regulacion = _numero(valores, 'regulacion_min')
    reserva = _numero(valores, 'reserva_flota', 0, 1)
    if inicio >= fin:
        raise ErrorDimensionamiento('La hora de inicio debe preceder al final del servicio.')
    a['personas_captables'] = sum(a[g] * c for g, c in coef.items())
    dentro = a.loc[a.hora_servicio.between(inicio, fin)].copy()
    if dentro.empty:
        raise ErrorDimensionamiento('No hay observaciones en la ventana elegida.')
    # Percentiles horarios para capacidad; el p85 del total diario se calcula aparte.
    k = ['access_corridor', 'direccion', 'hora_servicio']
    horario = dentro.groupby(k).personas_captables.agg(
        personas_percentil=lambda x: x.quantile(percentil), observaciones='size').reset_index()
    horario = horario.rename(columns={'access_corridor': 'corredor'})
    completo = pd.MultiIndex.from_product([rutas.corredor, ['subida', 'bajada'], range(inicio, fin + 1)],
        names=['corredor', 'direccion', 'hora_servicio']).to_frame(index=False)
    horario = completo.merge(horario, how='left', validate='one_to_one')
    # Solo para oferta mínima: el simulador da cero a una celda sin registros.
    horario[['personas_percentil', 'observaciones']] = horario[['personas_percentil', 'observaciones']].fillna(0)
    horario['expediciones_por_demanda'] = np.where(horario.personas_percentil.ge(umbral),
        np.ceil(horario.personas_percentil / capacidad), 0).astype(int)
    horario['oferta_minima'] = ((horario.direccion.eq('subida') & horario.hora_servicio.le(inicio + 2)) |
        (horario.direccion.eq('bajada') & horario.hora_servicio.ge(fin - 2))).astype(int)
    horario['expediciones'] = horario[['expediciones_por_demanda', 'oferta_minima']].max(axis=1)
    horario['plazas_diseno'] = horario.expediciones * capacidad
    horario['demanda_bajo_umbral'] = horario.personas_percentil.gt(0) & horario.personas_percentil.lt(umbral)
    por_matriz = dentro.groupby(['matrix_index', 'access_corridor', 'direccion']).personas_captables.sum().reset_index()
    por_matriz = por_matriz.rename(columns={'access_corridor': 'corredor'})
    diarios = por_matriz.groupby('matrix_index').personas_captables.sum().reindex(range(57), fill_value=0)
    filas = []
    for ruta in rutas.itertuples():
        h = horario.loc[horario.corredor.eq(ruta.corredor)]
        n = h.groupby('direccion').expediciones.sum()
        ciclo = ruta.min_subida_modelo + ruta.min_bajada_modelo + 2 * regulacion
        # Misma aproximación de flota del Visor; no es un cuadro de turnos validado.
        pico = h.expediciones.max()
        filas.append({'corredor': ruta.corredor, 'punto': ruta.punto,
            'subidas_dia': int(n['subida']), 'bajadas_dia': int(n['bajada']),
            'reposiciones_equivalentes_dia': abs(int(n['subida']) - int(n['bajada'])),
            'flota_acceso': math.ceil(pico * ciclo / 60), 'ciclo_min': ciclo,
            'km_elegidos': ruta.km_elegidos,
            'km_comerciales_dia': (n['subida'] + n['bajada']) * ruta.km_elegidos,
            'km_reposicion_dia': abs(n['subida'] - n['bajada']) * ruta.km_elegidos})
    corredores = pd.DataFrame(filas)
    # La demanda interior es el proxy publicado sobre las mismas visitas.
    ini_int = max(inicio, int(_numero(valores, 'hora_inicio_interior', 0, 23, True)))
    fin_int = min(fin, int(_numero(valores, 'hora_fin_interior', 0, 24, True)))
    if valores['hora_inicio_interior'] >= valores['hora_fin_interior']:
        raise ErrorDimensionamiento('Ventana interior invertida o vacía.')
    ciclo_int = _numero(valores, 'min_ida_interior', .000001) + _numero(valores, 'min_vuelta_interior', .000001) + 2 * regulacion
    km_int = _numero(valores, 'km_interior', .000001)
    minimo_int = int(_numero(valores, 'min_buses_hora_interior', 0, entero=True))
    interior = a.loc[a.hora_servicio.ge(ini_int) & a.hora_servicio.lt(fin_int)]
    picos = interior.groupby(['matrix_index', 'direccion', 'hora_servicio']).personas_captables.sum().groupby('matrix_index').max().reindex(range(57), fill_value=0)
    pico_int = float(picos.quantile(percentil))
    frecuencia = max(math.ceil(pico_int / capacidad) if pico_int >= umbral else 0, minimo_int) if fin_int > ini_int else 0
    flota_int = math.ceil(ciclo_int * frecuencia / 60)
    horas_int = max(0, fin_int - ini_int)
    ciclos_dia = flota_int * horas_int * 60 / ciclo_int
    interior = pd.DataFrame([{'personas_percentil_pico_proxy': pico_int,
        'expediciones_hora_modelo': frecuencia, 'flota_interior': flota_int,
        'inicio': ini_int, 'fin': fin_int, 'ciclo_min': ciclo_int,
        'recorridos_equivalentes_por_sentido_dia': ciclos_dia,
        'km_por_sentido': km_int, 'km_dia': ciclos_dia * km_int * 2,
        'alcance': 'Servicio para las mismas visitas; proxy del Visor, no nuevas entradas; regreso por la cabecera de llegada pendiente de horarios'}])
    flota = int(corredores.flota_acceso.sum()) + flota_int
    resumen = {'personas_percentil_total_diario': float(diarios.quantile(percentil)),
        'suma_percentiles_horarios_capacidad': float(horario.personas_percentil.sum()),
        'subidas_dia': int(corredores.subidas_dia.sum()), 'bajadas_dia': int(corredores.bajadas_dia.sum()),
        'flota_acceso': int(corredores.flota_acceso.sum()), 'flota_interior': flota_int,
        'flota_operativa': flota, 'flota_con_reserva': math.ceil(flota * (1 + reserva)),
        'capacidad_diseno_por_guagua': capacidad,
        'demanda_anual': None, 'regreso_misma_cabecera': True,
        'saldo_sentidos': 'Conservo observaciones distintas; no identifico parejas de personas ni fuerzo igualdad',
        'alcance': 'Diseño sobre las 57 matrices; no previsión anual 2028 ni ahorro'}
    return {'horaria': horario, 'por_matriz': por_matriz, 'corredores': corredores,
        'interior': interior, 'resumen': resumen}


def estimar_coches_sustituidos(personas_captadas, ocupacion, fraccion_desde_coche):
    """Convertir viajes-persona de un sentido; los grupos deben retirar el coche.

    Una elección pendiente conserva la ausencia. El resultado no elimina el
    acceso en coche a la cabecera y no identifica vehículos únicos.
    """
    personas = np.asarray(personas_captadas, dtype=float)
    if not np.isfinite(personas).all() or (personas < 0).any():
        raise ErrorDimensionamiento('Las personas deben ser finitas y no negativas.')
    if ocupacion is None or fraccion_desde_coche is None:
        return np.full(personas.shape, np.nan)
    o = _numero({'o': ocupacion}, 'o', 1)
    f = _numero({'f': fraccion_desde_coche}, 'f', 0, 1)
    return personas * f / o


def identificar_matrices_visor(perfiles, catalogo):
    """Inferir índice/periodo solo si los 57 totales publicados dan cruce único."""
    campos = ['Matriz', 'Año', 'Mes', 'Tipo de día', 'Viajes subida']
    if not set(campos) <= set(catalogo) or len(catalogo) != 57:
        raise ErrorDimensionamiento('El catálogo debe contener las 57 matrices publicadas.')
    c = catalogo.reset_index(drop=True).copy()
    totales = pd.to_numeric(c['Viajes subida'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), errors='raise')
    a = perfiles.loc[perfiles.direccion.eq('subida')].copy()
    a['total'] = a[list(SEGMENTOS)].sum(axis=1)
    sumas = a.groupby('matrix_index').total.sum()
    if set(sumas.index) != set(range(57)) or not np.isfinite(sumas).all():
        raise ErrorDimensionamiento('Faltan índices o totales para identificar matrices.')
    filas = []
    usados = set()
    for idx, suma in sumas.items():
        candidatos = c.loc[(totales - suma).abs().le(.500001)]
        if len(candidatos) != 1 or candidatos.index[0] in usados:
            raise ErrorDimensionamiento('El total redondeado no da una correspondencia uno a uno.')
        f = candidatos.iloc[0];n = candidatos.index[0];usados.add(n)
        filas.append({'matrix_index': idx, 'matriz_publicada': f['Matriz'], 'anio': int(f['Año']),
            'mes_publicado': f['Mes'], 'tipo_dia_publicado': f['Tipo de día'],
            'total_subida_reconstruido': suma, 'total_subida_publicado': totales[n],
            'diferencia_redondeo': suma - totales[n],
            'estado': 'Correspondencia inferida por total único compatible con redondeo; no confirmación recibida'})
    return pd.DataFrame(filas)


def conectar_oferta_norte(root, parametros, config):
    """Usar oferta calculada del mismo caso/libro, o la elección manual explícita."""
    from pathlib import Path
    import json
    from movilidad_teide.trazabilidad import sha256_archivo
    valores = {r['id']: r['valor_utilizado'] for r in parametros['parametros']}
    fila_regla=next((r for r in parametros.get('parametros',[]) if r['id']=='distancias_actividad_lanzaderas'),None)
    if fila_regla is not None:
        if fila_regla['valor_utilizado'] is None:raise ErrorDimensionamiento('Falta elegir las distancias de actividad de lanzaderas.')
        folder=Path(root)/'data/silver/demanda/asignacion'
        meta=json.loads((folder/'metadatos.json').read_text())
        source=meta.get('parametros_dimensionamiento',{})
        if source.get('sha256_libro')!=parametros['sha256_libro'] or source.get('caso')!=parametros['caso']:
            raise ErrorDimensionamiento('Completo los cuadernos 01 de demanda y 04 de servicio con el libro y registro actuales antes de consultar la actividad.')
        for name in ['actividad_lanzaderas_resumen.csv','actividad_lanzaderas_por_sentido.csv']:
            if sha256_archivo(folder/name)!=meta['archivos'].get(name):
                raise ErrorDimensionamiento('La nueva actividad de lanzaderas no conserva su integridad.')
        summary=pd.read_csv(folder/'actividad_lanzaderas_resumen.csv',sep=';')
        rows=summary.loc[summary.punto.eq(config['punto_norte'])]
        if len(rows)!=1 or not rows.base_distancias.eq(fila_regla['valor_utilizado']).all():
            raise ErrorDimensionamiento('No hay actividad única del norte con la base de distancias elegida.')
        row=rows.iloc[0]
        details=pd.read_csv(folder/'actividad_lanzaderas_por_sentido.csv',sep=';')
        details=details.loc[details.punto.eq(config['punto_norte']) & (details.componente.str.startswith('comercial')|details.componente.str.startswith('reposicion_'))].copy()
        config['oferta_norte_elegida']={'subidas':int(row.salidas_ida_dia),'bajadas':int(row.salidas_vuelta_dia),
            'reposiciones':int(row.get('reposicion_modelada_ida_dia',row.reposicion_minima_ida_dia)+row.get('reposicion_modelada_vuelta_dia',row.reposicion_minima_vuelta_dia)),
            'km':float(row.longitud_ida_km),'km_vuelta':float(row.longitud_vuelta_km),
            'reposicion_ida':int(row.get('reposicion_modelada_ida_dia',row.reposicion_minima_ida_dia)),
            'reposicion_vuelta':int(row.get('reposicion_modelada_vuelta_dia',row.reposicion_minima_vuelta_dia))}
        config['oferta_norte_detallada']=details.astype(object).where(details.notna(),None).to_dict('records')
        config['origen_oferta']='Actividad por sentido del mismo libro/caso; circulación propuesta y cocheras/otros vacíos pendientes'
        return config
    if valores['origen_oferta'] == 'Expediciones manuales':
        return config
    if valores['origen_oferta'] != 'Simulador de captación':
        raise ErrorDimensionamiento('Falta elegir el origen de la oferta en el Excel.')
    root = Path(root)
    carpeta = root / 'data/silver/demanda/asignacion'
    meta = json.loads((carpeta / 'metadatos.json').read_text())
    fuente = meta.get('parametros_dimensionamiento', {})
    if fuente.get('sha256_libro') != parametros['sha256_libro'] or fuente.get('caso') != parametros['caso']:
        raise ErrorDimensionamiento('Completo los cuadernos 01 de demanda y 04 de servicio con el libro y registro actuales antes de consultar la actividad.')
    nombre = 'dimensionamiento_medianias_corredores.csv'
    if sha256_archivo(carpeta / nombre) != meta['archivos'][nombre]:
        raise ErrorDimensionamiento('La oferta calculada no conserva su integridad.')
    tabla = pd.read_csv(carpeta / nombre, sep=';')
    norte = tabla.loc[tabla.punto.eq(config['punto_norte'])]
    if len(norte) != 1:
        raise ErrorDimensionamiento('No hay una oferta única del norte.')
    r = norte.iloc[0]
    config['oferta_norte_elegida'] = {'subidas': int(r.subidas_dia), 'bajadas': int(r.bajadas_dia),
        'reposiciones': float(r.reposiciones_equivalentes_dia), 'km': float(r.km_elegidos)}
    config['origen_oferta'] = 'Simulador de captación; misma huella y caso del libro'
    return config


def anualizar_oferta_dimensionada(dimensionamiento, dias):
    """Anualizar vehículos del servicio constante; nunca los pasajeros p85."""
    from movilidad_teide.demanda.oferta import calcular_oferta_acceso
    n = _numero({'dias': dias}, 'dias', 0, 366, True)
    filas = []
    for r in dimensionamiento['corredores'].itertuples():
        t = calcular_oferta_acceso(r.km_elegidos, r.subidas_dia, r.bajadas_dia,
            r.reposiciones_equivalentes_dia, n)
        t['corredor'] = r.corredor
        t['servicio'] = 'acceso'
        filas.append(t)
    i = dimensionamiento['interior'].iloc[0]
    for sentido in ['Portillo_Boca_Tauce', 'Boca_Tauce_Portillo']:
        ciclos = i.recorridos_equivalentes_por_sentido_dia
        filas.append(pd.DataFrame([{'componente': 'interior_equivalente_modelo',
            'sentido': sentido, 'recorridos_dia': ciclos, 'km_por_recorrido': i.km_por_sentido,
            'vehiculo_km_dia': ciclos * i.km_por_sentido, 'dias_operacion': n,
            'recorridos_anio': ciclos * n, 'vehiculo_km_anio': ciclos * i.km_por_sentido * n,
            'corredor': 'interior_Portillo_Boca_Tauce', 'servicio': 'interior'}]))
    resultado = pd.concat(filas, ignore_index=True)
    resultado['alcance'] = ('Oferta constante del modelo; distancias/tiempos provisionales. '
        'Interior por flota-horas/ciclo, no expediciones validadas. Cocheras y otros vacíos pendientes.')
    return resultado


def revisar_operacion_medianias(dimensionamiento, rutas, valores):
    """Revisar cobertura y cotas de retorno; no generar un horario observado.

    Acumulo el perfil horario de diseño y aplico FIFO con capacidad compartida.
    Servir toda una franja con sus plazas es una cota favorable: faltan minutos
    de llegada/salida, turnos, regulación efectiva y parejas de visitas.
    Para retornos uso la envolvente temporal de cada bloque como salida. Esta
    interpretación de hora_servicio es condicional y requiere confirmación.
    """
    from collections import deque

    h = dimensionamiento['horaria'].copy()
    claves = ['corredor', 'direccion', 'hora_servicio']
    necesarios = claves + ['personas_percentil', 'expediciones', 'plazas_diseno']
    if not set(necesarios) <= set(h) or h.empty or h[necesarios].isna().any().any():
        raise ErrorDimensionamiento('Faltan datos horarios para revisar la operación.')
    if h.duplicated(claves).any() or set(h.direccion) != {'subida', 'bajada'}:
        raise ErrorDimensionamiento('Claves horarias repetidas o sentidos incompletos.')
    if not h.hora_servicio.isin(range(24)).all():
        raise ErrorDimensionamiento('Las franjas de revisión deben ser horas enteras.')
    numeros = h[['personas_percentil', 'expediciones', 'plazas_diseno']].to_numpy(dtype=float)
    if not np.isfinite(numeros).all() or (numeros < 0).any() or not h.expediciones.eq(h.expediciones.round()).all():
        raise ErrorDimensionamiento('Demanda y oferta deben ser finitas, no negativas y expediciones enteras.')
    capacidad = _numero(valores, 'plazas_guagua', 1, entero=True) * _numero(valores, 'ocupacion_diseno', .000001, 1)
    if not np.allclose(h.plazas_diseno, h.expediciones * capacidad, rtol=0, atol=1e-9):
        raise ErrorDimensionamiento('Las plazas no corresponden a las expediciones y capacidad elegidas.')
    inicio = int(_numero(valores, 'hora_inicio_acceso', 0, 23, True))
    fin = int(_numero(valores, 'hora_fin_acceso', 0, 23, True))
    rutas_campos = ['corredor', 'min_subida_modelo', 'min_bajada_modelo']
    if not set(rutas_campos) <= set(rutas) or rutas.corredor.duplicated().any() or set(h.corredor) != set(rutas.corredor):
        raise ErrorDimensionamiento('Faltan tiempos únicos de los mismos corredores.')
    tiempos = rutas[rutas_campos[1:]].to_numpy(dtype=float)
    if not np.isfinite(tiempos).all() or (tiempos <= 0).any():
        raise ErrorDimensionamiento('Los tiempos publicados deben ser positivos y finitos.')
    for _, bloque in h.groupby(['corredor', 'direccion']):
        if set(bloque.hora_servicio) != set(range(inicio, fin + 1)):
            raise ErrorDimensionamiento('La revisión exige todas las franjas de la ventana elegida.')
    if len(h) != len(rutas) * 2 * (fin - inicio + 1):
        raise ErrorDimensionamiento('Falta un sentido en algún corredor.')
    espera = valores.get('espera_max_lanzadera_min')
    estancia = valores.get('estancia_min_visita_min')
    for clave, valor in [('espera_max_lanzadera_min', espera), ('estancia_min_visita_min', estancia)]:
        if valor is not None:
            _numero(valores, clave, 1, 1440)
    # Cero aquí es solo una cota física sin estancia; nunca una elección de visita.
    estancia_cota = 0. if estancia is None else float(estancia)
    fin_interior = _numero(valores, 'hora_fin_interior', 0, 24)
    filas, desplazamientos, retornos, resumen = [], [], [], []
    for corredor, bloque in h.groupby('corredor', sort=False):
        resumen_corredor = {'corredor': corredor}
        atendidas_subida = {}
        for sentido in ['subida', 'bajada']:
            b = bloque.loc[bloque.direccion.eq(sentido)].sort_values('hora_servicio')
            cola = deque()
            pendientes = 0.
            flujos_sentido = []
            for row in b.itertuples():
                hora, demanda = int(row.hora_servicio), float(row.personas_percentil)
                saldo_inicial = pendientes
                if demanda > 0:
                    cola.append([hora, demanda])
                pendientes += demanda
                plazas = float(row.plazas_diseno)
                atendidas = min(pendientes, plazas)
                restantes = atendidas
                # FIFO conserva cada cohorte y evita reutilizar una plaza en dos horas.
                while restantes > 1e-10 and cola:
                    origen, cantidad = cola[0]
                    usadas = min(cantidad, restantes)
                    separacion_min = max(0, (hora - origen - 1) * 60)
                    separacion_max = (hora - origen + 1) * 60
                    if espera is None:
                        estado_espera = 'Espera máxima pendiente; no acredita atención efectiva'
                    elif separacion_min > espera:
                        estado_espera = 'Supera la espera elegida incluso con la cota favorable'
                    elif separacion_max <= espera:
                        estado_espera = 'No supera la espera elegida dentro de la envolvente horaria'
                    else:
                        estado_espera = 'Indeterminado a resolución horaria; faltan minutos'
                    flujo = {'corredor': corredor, 'direccion': sentido, 'hora_demanda': origen,
                        'hora_atencion_cota': hora, 'cantidad_diseno': usadas,
                        'demora_cota_min_min': separacion_min, 'demora_cota_max_min': separacion_max,
                        'espera_max_elegida_min': espera, 'estado': estado_espera}
                    desplazamientos.append(flujo); flujos_sentido.append(flujo)
                    cola[0][1] -= usadas
                    restantes -= usadas
                    if cola[0][1] < 1e-10:
                        cola.popleft()
                pendientes = max(0., pendientes - atendidas)
                futuras = b.loc[b.hora_servicio.gt(hora) & b.expediciones.gt(0), 'hora_servicio']
                filas.append({'corredor': corredor, 'direccion': sentido, 'hora_servicio': hora,
                    'demanda_diseno_horaria': demanda, 'expediciones': int(row.expediciones),
                    'plazas_diseno': plazas, 'saldo_inicial_diseno': saldo_inicial,
                    'atencion_cota_favorable': atendidas, 'saldo_final_diseno': pendientes,
                    'demanda_sin_expedicion_en_franja': demanda > 0 and row.expediciones == 0,
                    'siguiente_hora_con_oferta': None if futuras.empty else int(futuras.min())})
                if sentido == 'subida':
                    atendidas_subida[hora] = atendidas
            for origen, cantidad in cola:
                desplazamientos.append({'corredor': corredor, 'direccion': sentido,
                    'hora_demanda': origen, 'hora_atencion_cota': None, 'cantidad_diseno': cantidad,
                    'demora_cota_min_min': None, 'demora_cota_max_min': None,
                    'espera_max_elegida_min': espera, 'estado': 'Sin capacidad posterior dentro de la ventana'})
            resumen_corredor.update({f'expediciones_{sentido}': int(b.expediciones.sum()),
                f'suma_perfil_diseno_{sentido}': float(b.personas_percentil.sum()),
                f'sin_atencion_cota_{sentido}': pendientes,
                f'franjas_sin_salida_{sentido}': int((b.personas_percentil.gt(0) & b.expediciones.eq(0)).sum()),
                f'diseno_desplazado_a_otra_franja_{sentido}': sum(f['cantidad_diseno'] for f in flujos_sentido if f['hora_atencion_cota'] != f['hora_demanda'])})
        tiempo = float(rutas.loc[rutas.corredor.eq(corredor), 'min_subida_modelo'].iloc[0])
        bajadas = bloque.loc[bloque.direccion.eq('bajada') & bloque.expediciones.gt(0)].sort_values('hora_servicio')
        ultima = None if bajadas.empty else int(bajadas.hora_servicio.max())
        retornables = dict.fromkeys(atendidas_subida, 0.)
        por_devolver = dict(atendidas_subida)
        # Cota favorable compartida: subida al principio y bajada al final del bloque.
        # No uso las bajadas observadas como parejas ni añado demanda por transbordos.
        for bajada in bajadas.itertuples():
            disponibles = float(bajada.plazas_diseno)
            for hora in sorted(por_devolver):
                if hora * 60 + tiempo + estancia_cota > (bajada.hora_servicio + 1) * 60:
                    continue
                cantidad = min(disponibles, por_devolver[hora])
                retornables[hora] += cantidad
                por_devolver[hora] -= cantidad
                disponibles -= cantidad
                if disponibles < 1e-10:
                    break
        for hora, cantidad in atendidas_subida.items():
            maximo = None if ultima is None else (ultima + 1 - hora) * 60 - tiempo
            minimo = None if ultima is None else (ultima - hora - 1) * 60 - tiempo
            deficit = max(0., cantidad - retornables[hora])
            estado = ('Sin subida atendible en esa franja' if cantidad < 1e-10 else
                'No supera la cota favorable de retorno en el día' if deficit > 1e-8 else
                'No descartado por la cota; horario y estancia por validar')
            retornos.append({'corredor': corredor, 'hora_subida_cota': hora,
                'subidas_atendibles_cota': cantidad, 'ultima_hora_bajada_con_oferta': ultima,
                'min_subida_publicados': tiempo,
                'estancia_min_elegida_min': estancia, 'estancia_usada_solo_en_cota_min': estancia_cota,
                'estancia_max_hasta_ultima_bajada_cota_favorable_min': maximo,
                'estancia_max_hasta_ultima_bajada_cota_desfavorable_min': minimo,
                'retornables_cota_favorable': retornables[hora],
                'sin_retorno_cota_favorable': deficit,
                'margen_llegada_temprana_hasta_fin_interior_min': fin_interior * 60 - (hora * 60 + tiempo),
                'estado': estado})
        resumen_corredor['sin_retorno_cota_favorable'] = sum(por_devolver.values())
        resumen_corredor['estancia_min_elegida_min'] = estancia
        resumen_corredor['espera_max_elegida_min'] = espera
        resumen.append(resumen_corredor)
    franjas = pd.DataFrame(filas)
    flujos = pd.DataFrame(desplazamientos, columns=['corredor', 'direccion', 'hora_demanda',
        'hora_atencion_cota', 'cantidad_diseno', 'demora_cota_min_min',
        'demora_cota_max_min', 'espera_max_elegida_min', 'estado'])
    if not np.allclose(franjas.saldo_inicial_diseno + franjas.demanda_diseno_horaria,
            franjas.atencion_cota_favorable + franjas.saldo_final_diseno, atol=1e-8):
        raise ErrorDimensionamiento('No se conserva el perfil de diseño en la revisión horaria.')
    for (corredor, sentido), bloque in franjas.groupby(['corredor', 'direccion']):
        f = flujos.loc[flujos.corredor.eq(corredor) & flujos.direccion.eq(sentido)]
        if not math.isclose(f.cantidad_diseno.sum(), bloque.demanda_diseno_horaria.sum(), abs_tol=1e-8):
            raise ErrorDimensionamiento('No se conservan las cohortes del perfil de diseño.')
    criterios = {'espera_max_elegida_min': espera, 'estancia_min_elegida_min': estancia,
        'criterios_operativos_completos': espera is not None and estancia is not None,
        'horario_validado': False, 'pasajeros_transportados_acreditados': False,
        'supuesto_temporal': 'hora_servicio tratada condicionalmente como franja de salida [h,h+1]; extremos cerrados solo para cotas favorables, no salidas reales',
        'alcance': 'Perfil formado por percentiles horarios, no personas de un día observado ni demanda anual. FIFO y retorno son cotas; no acreditan minutos, turnos, estancia, flota ni transbordos interiores.'}
    return {'franjas': franjas, 'desplazamientos': flujos, 'retornos': pd.DataFrame(retornos),
        'resumen': pd.DataFrame(resumen), 'criterios': criterios}


def leer_longitudes_servicios(root):
    """Leer los diez perfiles operativos existentes, sin regenerar la geografía."""
    from pathlib import Path
    import json
    from movilidad_teide.trazabilidad import sha256_archivo
    root=Path(root)
    cfg=json.loads((root/'config/perfil_altimetrico.json').read_text())['operational_profiles']
    groups={'CHIO':'chio_boca_tauce','OROTAVA':'aguamansa_el_portillo',
            'LAGUNA':'la_esperanza_el_portillo','VILAFLOR':'vilaflor_boca_tauce',
            'INTERIOR':'interior_boca_tauce_el_portillo'}
    rows=[]
    for point,group in groups.items():
        ficha=cfg[group];folder=root/'data/silver/geografia/perfiles_altimetricos'/group
        meta_path=folder/'metadatos.json';meta=json.loads(meta_path.read_text())
        if len(ficha['itinerary_ids'])!=2:raise ErrorDimensionamiento('Cada servicio necesita dos perfiles.')
        for sentido,ident in zip(['ida','vuelta'],ficha['itinerary_ids'],strict=True):
            path=folder/f'tramos_{ident}.parquet';digest=sha256_archivo(path)
            if digest!=meta['output_sha256'][path.name]:raise ErrorDimensionamiento('Perfil distinto de su manifiesto: '+ident)
            tabla=pd.read_parquet(path,columns=['segment_id','itinerary_id','length_m'])
            lengths=pd.to_numeric(tabla.length_m,errors='coerce')
            if (tabla.empty or tabla.segment_id.duplicated().any() or tabla.segment_id.isna().any()
                    or not tabla.itinerary_id.eq(ident).all() or not np.isfinite(lengths).all() or lengths.le(0).any()):
                raise ErrorDimensionamiento('Perfil incompleto, incompatible o con longitudes no válidas.')
            origen=ficha['cabecera_name'] if sentido=='ida' else ficha['terminal_name']
            destino=ficha['terminal_name'] if sentido=='ida' else ficha['cabecera_name']
            rows.append({'punto':point,'sentido':sentido,'origen':origen,'destino':destino,
                'itinerary_id':ident,'longitud_geografica_km':float(lengths.sum()/1000),
                'ruta_perfil':path.relative_to(root).as_posix(),'sha256_perfil':digest,
                'ruta_manifiesto':meta_path.relative_to(root).as_posix(),
                'sha256_manifiesto':sha256_archivo(meta_path)})
    return pd.DataFrame(rows)


def actividad_lanzaderas_por_servicio(dimensionamiento, longitudes, valores, dias):
    """Cuantificar salidas y cierre diario mínimo; no declarar operación completa.

    La frecuencia interior fija salidas enteras en una ventana [inicio,fin).
    Cada servicio cierra su distribución diaria sin intercambio entre servicios.
    Cocheras y movimientos adicionales por horario permanecen desconocidos.
    """
    n=_numero({'dias':dias},'dias',0,366,True)
    rule=valores.get('distancias_actividad_lanzaderas')
    if rule not in {'Recorridos del estudio','Referencias de distancia del Excel'}:
        raise ErrorDimensionamiento('Falta elegir la base de distancias de actividad en el Excel.')
    required={'punto','sentido','origen','destino','itinerary_id','longitud_geografica_km'}
    if not required<=set(longitudes) or longitudes.duplicated(['punto','sentido']).any():
        raise ErrorDimensionamiento('Longitudes sin identificación única por servicio y sentido.')
    points=list(dimensionamiento['corredores'].punto)
    if (len(points)!=len(set(points)) or 'INTERIOR' in points
            or set(map(tuple,longitudes[['punto','sentido']].to_numpy()))!={(p,s) for p in points+['INTERIOR'] for s in ['ida','vuelta']}):
        raise ErrorDimensionamiento('Servicios/sentidos de geografía y oferta no coinciden.')
    lengths=pd.to_numeric(longitudes.longitud_geografica_km,errors='coerce')
    if not np.isfinite(lengths).all() or lengths.le(0).any():raise ErrorDimensionamiento('Longitudes geográficas no válidas.')
    mode=valores.get('origen_oferta')
    if mode not in {'Simulador de captación','Expediciones manuales'}:raise ErrorDimensionamiento('Origen de oferta sin elegir.')
    counts={};reference_fleet={}
    for row in dimensionamiento['corredores'].itertuples():
        if mode=='Simulador de captación':
            up=_numero({'v':row.subidas_dia},'v',entero=True);down=_numero({'v':row.bajadas_dia},'v',entero=True)
        else:
            up=_numero(valores,f'subidas_{row.punto}',entero=True);down=_numero(valores,f'bajadas_{row.punto}',entero=True)
            repos=_numero(valores,f'reposiciones_{row.punto}')
            if repos<abs(up-down):raise ErrorDimensionamiento('Reposición manual inferior al desequilibrio diario; revisar '+row.punto)
        counts[row.punto]={'ida':int(up),'vuelta':int(down)}
        reference_fleet[row.punto]=row.flota_acceso
    interior=dimensionamiento['interior'].iloc[0]
    frequency=int(_numero({'f':interior.expediciones_hora_modelo},'f',entero=True))
    start=int(_numero({'h':interior.inicio},'h',0,23,True));end=int(_numero({'h':interior.fin},'h',0,24,True))
    if start>end:raise ErrorDimensionamiento('Ventana interior invertida.')
    counts['INTERIOR']={s:frequency*(end-start) for s in ['ida','vuelta']}
    reference_fleet['INTERIOR']=interior.flota_interior
    movements=[];summary=[];comparison=[];departures=[]
    for point in points+['INTERIOR']:
        table=longitudes.loc[longitudes.punto.eq(point)].set_index('sentido')
        chosen={s:(float(table.loc[s,'longitud_geografica_km']) if rule=='Recorridos del estudio'
                   else _numero(valores,'km_interior' if point=='INTERIOR' else f'km_{point}',.000001))
                for s in ['ida','vuelta']}
        commercial=counts[point];empty={s:max(commercial['vuelta' if s=='ida' else 'ida']-commercial[s],0) for s in ['ida','vuelta']}
        assert commercial['ida']+empty['ida']==commercial['vuelta']+empty['vuelta']
        known_km=0.;commercial_km=0.;empty_km=0.
        for sense in ['ida','vuelta']:
            for component,count in [('comercial',commercial[sense]),('reposicion_minima_cierre',empty[sense])]:
                km=count*chosen[sense];known_km+=km
                if component=='comercial':commercial_km+=km
                else:empty_km+=km
                movements.append({'punto':point,'componente':component,'sentido':sense,
                    'origen':table.loc[sense,'origen'],'destino':table.loc[sense,'destino'],
                    'itinerary_id':table.loc[sense,'itinerary_id'] if rule=='Recorridos del estudio' else None,
                    'recorridos_dia':count,'km_por_recorrido':chosen[sense],
                    'vehiculo_km_dia':km,'dias_operacion':int(n),'recorridos_anio':count*n,'vehiculo_km_anio':km*n,
                    'base_distancias':rule,'estado':'Actividad identificada provisional; horario/flota pendientes'})
            if point=='INTERIOR':
                for hour in range(start,end):
                    for k in range(frequency):
                        minute=60*hour+60*k/frequency
                        departures.append({'punto':point,'sentido':sense,'origen':table.loc[sense,'origen'],
                            'destino':table.loc[sense,'destino'],'minuto_salida_local':minute,
                            'hora_salida_local':f'{int(round(minute*60))//3600:02d}:{int(round(minute*60))%3600//60:02d}:{int(round(minute*60))%60:02d}',
                            'hora_llegada_local':None,'estado':'Propuesta regular de salidas; tiempos/llegadas y flota sin validar'})
        for component in ['cocheras','vacios_adicionales_por_horario']:
            movements.append({'punto':point,'componente':component,'sentido':'pendiente',
                'origen':None,'destino':None,'itinerary_id':None,'recorridos_dia':np.nan,'km_por_recorrido':np.nan,
                'vehiculo_km_dia':np.nan,'dias_operacion':int(n),'recorridos_anio':np.nan,'vehiculo_km_anio':np.nan,
                'base_distancias':rule,'estado':'Pendiente; no cero ni incluido en subtotal identificado'})
        summary.append({'punto':point,'longitud_ida_km':chosen['ida'],'longitud_vuelta_km':chosen['vuelta'],
            'salidas_ida_dia':commercial['ida'],'salidas_vuelta_dia':commercial['vuelta'],
            'reposicion_minima_ida_dia':empty['ida'],'reposicion_minima_vuelta_dia':empty['vuelta'],
            'km_comerciales_dia':commercial_km,'km_cierre_minimo_dia':empty_km,
            'vehiculo_km_identificados_dia':known_km,'dias_operacion':int(n),
            'vehiculo_km_identificados_anio':known_km*n,
            'flota_referencia_visor_no_validada':reference_fleet[point],
            'reposicion_referencia_manual_dia':valores.get(f'reposiciones_{point}') if mode=='Expediciones manuales' and point!='INTERIOR' else np.nan,
            'componentes_km_pendientes':2,'operacion_completa_validada':False,'base_distancias':rule})
        published=_numero(valores,'km_interior' if point=='INTERIOR' else f'km_{point}',.000001)
        reference_count=(interior.recorridos_equivalentes_por_sentido_dia if point=='INTERIOR' else None)
        comparison.append({'punto':point,'km_referencia_excel_por_sentido':published,
            'longitud_geografica_ida_km':float(table.loc['ida','longitud_geografica_km']),
            'longitud_geografica_vuelta_km':float(table.loc['vuelta','longitud_geografica_km']),
            'salidas_propuesta_por_sentido_interior':counts[point]['ida'] if point=='INTERIOR' else np.nan,
            'recorridos_equivalentes_continuos_interior':reference_count,
            'alcance':'Referencias distintas y propuesta de actividad; diferencia no es ahorro ni demanda transportada'})
    return {'movimientos':pd.DataFrame(movements),'resumen':pd.DataFrame(summary),
            'contraste':pd.DataFrame(comparison),'salidas_interior':pd.DataFrame(departures,columns=['punto','sentido','origen','destino','minuto_salida_local','hora_salida_local','hora_llegada_local','estado'])}
