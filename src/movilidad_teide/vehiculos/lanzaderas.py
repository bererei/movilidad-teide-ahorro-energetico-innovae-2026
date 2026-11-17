"""vehiculos: lanzaderas. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations


def anualizar_consumos_lanzaderas(actividad, referencias, *, caso_excel, sha256_libro,
                                  carga_comercial, anio):
    """Cruzar oferta y energía por recorrido, separando alternativas y ausencias.

    Cada referencia representa por separado el mismo horario completo con una
    categoría técnica. No sumo categorías alternativas ni estimo pasajeros a
    partir de plazas. Cocheras y otros movimientos desconocidos conservan NA.
    La carga comercial es una condición explícita, no ocupación observada.
    """
    import numpy as np
    import pandas as pd
    import calendar

    claves = ['referencia_id', 'punto', 'sentido', 'itinerary_id', 'carga_fisica']
    descripcion = ['referencia', 'Category', 'Fuel', 'Segment', 'Euro Standard']
    columnas_a = {'punto', 'componente', 'sentido', 'itinerary_id', 'recorridos_dia',
        'km_por_recorrido', 'vehiculo_km_dia', 'dias_operacion', 'recorridos_anio',
        'vehiculo_km_anio', 'base_distancias', 'caso_excel', 'sha256_libro'}
    columnas_r = set(claves + descripcion + ['longitud_km', 'velocidad_media_kmh',
        'energia_mj_recorrido', 'energia_exterior_mj_recorrido', 'longitud_exterior_km', 'anio'])
    if actividad.empty or referencias.empty or not columnas_a <= set(actividad) or not columnas_r <= set(referencias):
        raise ValueError('Faltan actividad o referencias completas de las lanzaderas.')
    a, r = actividad.copy(deep=True), referencias.copy(deep=True)
    for campo, esperado in [('caso_excel', caso_excel), ('sha256_libro', sha256_libro)]:
        if campo in r:
            if set(r[campo]) != {esperado}:
                raise ValueError('Referencias de otro libro/caso.')
            r.drop(columns=campo, inplace=True)
    if (set(a.caso_excel) != {caso_excel} or set(a.sha256_libro) != {sha256_libro}
            or set(a.base_distancias) != {'Recorridos del estudio'}):
        raise ValueError('Actividad de otro libro/caso o distancias ajenas al perfil del estudio.')
    carga_comercial = float(carga_comercial)
    if not np.isfinite(carga_comercial) or not 0 <= carga_comercial <= 1:
        raise ValueError('La carga comercial debe estar elegida entre cero y uno.')
    if int(anio) != anio or not 1900 <= anio <= 2200 or set(r.anio) != {anio}:
        raise ValueError('Año de factores incompatible con la anualización.')
    dias_max = 366 if calendar.isleap(int(anio)) else 365
    comerciales = {'comercial', 'comercial_refuerzo_regreso'}
    vacios = {'reposicion_por_horario', 'reposicion_cierre_diario'}
    pendientes = {'cocheras', 'otros_vacios_no_modelizados'}
    if not set(a.componente) <= comerciales | vacios | pendientes:
        raise ValueError('Componente sin tratamiento explícito de actividad/carga.')
    if a[['punto', 'sentido', 'componente']].isna().any().any() or a.duplicated(['punto', 'sentido', 'componente']).any():
        raise ValueError('Actividad repetida o sin identificar por servicio, sentido y componente.')
    conocida = ~a.componente.isin(pendientes)
    numeros_a = ['recorridos_dia', 'km_por_recorrido', 'vehiculo_km_dia',
                 'dias_operacion', 'recorridos_anio', 'vehiculo_km_anio']
    x = a.loc[conocida, numeros_a].to_numpy(dtype=float)
    if (not conocida.any() or not np.isfinite(x).all() or (x < 0).any()
            or (x[:, 1] <= 0).any() or (x[:, 3] > dias_max).any()
            or not np.allclose(x[:, [0, 3, 4]], np.round(x[:, [0, 3, 4]]), rtol=0, atol=1e-9)):
        raise ValueError('Actividad conocida ausente, negativa o con recorridos/días no enteros.')
    if a.loc[conocida, 'itinerary_id'].isna().any() or not set(a.loc[conocida, 'sentido']) <= {'ida', 'vuelta'}:
        raise ValueError('Recorrido conocido sin itinerario o sentido identificado.')
    if a.dias_operacion.nunique(dropna=False) != 1:
        raise ValueError('El horario constante debe conservar el mismo calendario en todos los servicios.')
    for obtenido, esperado in [(x[:, 2], x[:, 0]*x[:, 1]),
                              (x[:, 4], x[:, 0]*x[:, 3]), (x[:, 5], x[:, 2]*x[:, 3])]:
        if not np.allclose(obtenido, esperado, rtol=1e-10, atol=1e-8):
            raise ValueError('No se conserva recorridos × longitud × días en la actividad.')
    # Los días sí pueden conocerse aunque el recorrido de cochera siga ausente.
    sin_actividad = [c for c in numeros_a if c != 'dias_operacion']
    if a.loc[~conocida, sin_actividad].notna().any().any():
        raise ValueError('Cocheras/otros no modelizados no pueden contener actividad supuesta o cero.')
    if r[claves + descripcion].isna().any().any() or r.duplicated(claves).any():
        raise ValueError('Referencias repetidas o sin clave/condiciones completas.')
    if any(r.groupby('referencia_id')[c].nunique().ne(1).any() for c in descripcion):
        raise ValueError('Una referencia mezcla categorías de vehículo distintas.')
    numeros_r = ['longitud_km', 'velocidad_media_kmh', 'carga_fisica',
                 'energia_mj_recorrido', 'energia_exterior_mj_recorrido', 'longitud_exterior_km']
    y = r[numeros_r].to_numpy(dtype=float)
    if (not np.isfinite(y).all() or (y < 0).any() or (y[:, [0, 1, 3]] <= 0).any()
            or (y[:, 2] > 1).any() or (y[:, 4] > y[:, 3]+1e-10).any()
            or (y[:, 5] > y[:, 0]+1e-10).any()):
        raise ValueError('Energía, longitud exterior o condiciones de referencia no válidas.')
    if r.velocidad_media_kmh.nunique() != 1:
        raise ValueError('Este ensayo uniforme no admite mezclar velocidades por recorrido.')

    salidas = []
    for identidad, b in r.groupby('referencia_id', sort=False):
        # Cada categoría es una alternativa completa; nunca una parte sumable de la flota.
        t = a.copy(deep=True)
        t['carga_fisica'] = np.where(t.componente.isin(vacios), 0.0, carga_comercial)
        t.loc[~conocida, 'carga_fisica'] = np.nan
        t = t.merge(b, on=['punto', 'sentido', 'itinerary_id', 'carga_fisica'],
                    how='left', validate='many_to_one', indicator=True)
        conocida_t = ~t.componente.isin(pendientes)
        if not t.loc[conocida_t, '_merge'].eq('both').all():
            raise ValueError('Falta consumo compatible: itinerario/sentido/carga de ' + str(identidad))
        if not np.allclose(t.loc[conocida_t, 'km_por_recorrido'],
                           t.loc[conocida_t, 'longitud_km'], rtol=1e-10, atol=1e-8):
            raise ValueError('La longitud anualizada no coincide con el perfil energético.')
        t.drop(columns='_merge', inplace=True)
        t['referencia_id'] = identidad
        for c in descripcion:
            t[c] = b.iloc[0][c]
        t['tipo_movimiento'] = np.select([t.componente.isin(comerciales), t.componente.isin(vacios)],
                                        ['comercial', 'vacio_modelizado'], default='pendiente')
        t['energia_mj_anio'] = t.energia_mj_recorrido*t.recorridos_anio
        t['energia_kwh_anio'] = t.energia_mj_anio/3.6
        t['energia_exterior_mj_anio'] = t.energia_exterior_mj_recorrido*t.recorridos_anio
        t['vehiculo_km_exterior_anio'] = t.longitud_exterior_km*t.recorridos_anio
        t['estado_energia'] = np.where(conocida_t,
            'Referencia técnica condicionada; no consumo observado', 'Pendiente: ausencia, no cero')
        salidas.append(t)
    detalle = pd.concat(salidas, ignore_index=True)

    def resumir(tabla, por_servicio):
        filas = []
        grupos = ['referencia_id', 'punto'] if por_servicio else ['referencia_id']
        for _, t in tabla.groupby(grupos, sort=False):
            c = t.tipo_movimiento.eq('comercial'); v = t.tipo_movimiento.eq('vacio_modelizado')
            conocida_t = c | v
            # Solo sumo filas comprobadas; el subtotal no imputa los componentes pendientes.
            energia = float(t.loc[conocida_t, 'energia_mj_anio'].sum())
            exterior = float(t.loc[conocida_t, 'energia_exterior_mj_anio'].sum())
            fila = {k: t.iloc[0][k] for k in ['referencia_id', *descripcion, 'caso_excel', 'sha256_libro']}
            if por_servicio:
                fila['punto'] = t.iloc[0].punto
            fila.update(vehiculo_km_anio=float(t.loc[conocida_t, 'vehiculo_km_anio'].sum()),
                energia_comercial_mj_anio=float(t.loc[c, 'energia_mj_anio'].sum()),
                energia_vacios_modelizados_mj_anio=float(t.loc[v, 'energia_mj_anio'].sum()),
                energia_identificada_mj_anio=energia, energia_identificada_kwh_anio=energia/3.6,
                energia_identificada_mwh_anio=energia/3600,
                energia_exterior_mj_anio=exterior, fraccion_energia_exterior=exterior/energia if energia else np.nan,
                vehiculo_km_exterior_anio=float(t.loc[conocida_t, 'vehiculo_km_exterior_anio'].sum()),
                error_tratamiento_exterior_mj_anio=np.nan,
                componentes_pendientes='; '.join(sorted(set(t.loc[~conocida_t, 'componente']))),
                energia_total_sistema_mj_anio=np.nan, ahorro_sistema_mj_anio=np.nan,
                alcance='Subtotal Hot EC de actividad identificada; cocheras/otros y balance completo pendientes')
            filas.append(fila)
        return pd.DataFrame(filas)

    return {'detalle': detalle, 'por_servicio': resumir(detalle, True),
            'por_referencia': resumir(detalle, False)}
