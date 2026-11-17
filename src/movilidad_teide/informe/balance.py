"""Ampliación editorial del informe: derivados auditables, sin cambiar el modelo."""
from movilidad_teide.informe.formato import formatear_ejes
from pathlib import Path
import hashlib, json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from movilidad_teide.informe.formato import numero, tex
POLITICA = 'Accesos e interior según reservas'
NOMBRES = {'CHIO': 'Chío', 'OROTAVA': 'Aguamansa', 'LAGUNA': 'La Esperanza', 'VILAFLOR': 'Vilaflor', 'INTERIOR': 'Interior'}

def preparar_revision(root, destino):
    (root, destino) = (Path(root).resolve(), Path(destino).resolve())
    display = destino / 'tablas/parametros.tex'
    display.write_text(display.read_text().replace('con30min', 'con 30 min'))
    used = []

    def read(rel):
        p = root / rel
        used.append(p)
        return pd.read_parquet(p) if p.suffix == '.parquet' else pd.read_csv(p, sep=';', float_precision='round_trip')

    def export(name, frame):
        frame.to_csv(destino / 'anexos' / f'{name}.csv', sep=';', index=False, encoding='utf-8-sig', float_format='%.17g')

    def tabla(name, title, heads, rows, note, cols=None):
        lines = ['\\begin{table}[!htbp]', '\\caption{' + title + '}', '\\centering{\\fontsize{10}{13}\\selectfont', '\\begin{tabularx}{\\linewidth}{@{}' + (cols or 'X' + 'r' * (len(heads) - 1)) + '@{}}', '\\rowcolor{azul} ' + ' & '.join(('{\\color{white}\\textbf{' + tex(h) + '}}' for h in heads)) + '\\\\']
        for (i, row) in enumerate(rows):
            lines.append(('\\rowcolor{fondo_azul} ' if i % 2 else '') + ' & '.join((tex(x) for x in row)) + '\\\\')
        lines += ['\\bottomrule\\end{tabularx}}', '\\Fuente{' + tex(note) + '}', '\\end{table}']
        (destino / 'tablas' / f'{name}.tex').write_text('\n'.join(lines) + '\n')
    base = 'data/silver/energia_turismos/'
    central = read(base + '20261101_hot_central_fta_sensibilidad/resultado_central.csv')
    allcases = read(base + '20261101_hot_central_fta_sensibilidad/balance_vigente.csv')
    corr = read(base + '20261101_pendiente_anual_pareada/correccion_por_componente_anual.csv')
    corr = corr[corr.caso_pendiente.eq('Referencia del Excel')]
    initial_meta = json.loads((destino / 'metadatos.json').read_text())
    parammap = {r['id']: r for r in initial_meta['parametros']['parametros']}
    occ = float(parammap['ocupacion_coche']['valor_utilizado'])
    rows = []
    for r in central.itertuples():
        x = corr[corr.alternativa_procedencia.eq(r.alternativa_procedencia)]
        net = float(x.loc[x.rama.eq('antes'), 'correccion_convencional_mwh_anio'].sum() - x.loc[~x.rama.eq('antes'), 'correccion_convencional_mwh_anio'].sum())
        rows.append({'alternativa_procedencia': r.alternativa_procedencia, 'hot_sin_ajuste_turismos_tep_anio': r.saldo_construccion_condicionada_tep_anio - net / 11.63, 'aporte_neto_pendiente_tep_anio': net / 11.63, 'hot_central_tep_anio': r.saldo_construccion_condicionada_tep_anio, 'ahorro_pct_ambito_representado': 100 * r.saldo_construccion_condicionada_mwh_anio / r.sin_componentes_mwh_anio})
    contribution = pd.DataFrame(rows)
    export('contribucion_pendiente', contribution)
    tabla('contribucion', 'Suma del saldo previo y el aporte de pendiente (tep/año)', ['Comprobación, misma oferta', 'Alquiler', 'Particular'], [[lab, *[numero(x) for x in contribution[key]]] for (lab, key) in [('Hot sin ajuste propio de pendiente de turismos', 'hot_sin_ajuste_turismos_tep_anio'), ('+ Aporte neto del ajuste de pendiente', 'aporte_neto_pendiente_tep_anio'), ('= Resultado central Hot', 'hot_central_tep_anio')]], 'Fuente: corrección anual de turismos y balance central. Cada columna suma las dos primeras filas con precisión completa; las cifras se redondean después. La diferencia visible de 0,01 tep en A se explica bajo la figura y en contribucion_pendiente.csv. No se suman columnas A/B ni extremos de sus rangos.')
    tabla('balance', 'Balance anual de energía final representada', ['Asignación', 'Sin (MWh)', 'Con (MWh)', 'Ahorro (tep)', 'Ahorro (%)'], [[r.alternativa_procedencia.split(': ')[1].capitalize(), numero(r.sin_componentes_mwh_anio), numero(r.con_construccion_condicionada_mwh_anio), numero(r.saldo_construccion_condicionada_tep_anio), numero(100 * r.saldo_construccion_condicionada_mwh_anio / r.sin_componentes_mwh_anio)] for r in central.itertuples()], 'Fuente: balance central, 2028. El porcentaje utiliza el consumo sin actuación del ámbito representado; no es un porcentaje de todo el Parque.', cols='Xrrrr')
    stress = []
    for (case, extra, label) in [('Referencia del Excel', 0, 'Central Hot'), ('Referencia del Excel', 0.01, 'Central + 1 % de consumo de nuevas guaguas'), ('Transmisión 0,95', 0, 'Transmisión 0,95'), ('Transmisión 0,95', 0.01, 'Transmisión 0,95 + 1 % de consumo de nuevas guaguas')]:
        t = allcases[allcases.politica.eq(POLITICA) & allcases.referencia_id.eq('referencia_guagua_2') & allcases.caso_pendiente.eq(case) & allcases.tratamiento_operativo.eq('Hot COPERT')]
        assert len(t) == 2
        for r in t.itertuples():
            stress.append({'comprobacion': label, 'alternativa_procedencia': r.alternativa_procedencia, 'incremento_consumo_guaguas_fraccion': extra, 'saldo_tep_anio': r.saldo_construccion_condicionada_tep_anio - extra * r.guaguas_mwh_anio / 11.63, 'actividad_fija': True, 'probabilidad_asignada': False})
    stress = pd.DataFrame(stress)
    export('sensibilidad_combinada', stress)
    tabla('combinada', 'Comprobación combinada con actividad fija (tep/año)', ['Comprobación', 'Alquiler', 'Particular'], [[lab, *[numero(x) for x in g.saldo_tep_anio]] for (lab, g) in stress.groupby('comprobacion', sort=False)], 'Fuente: aritmética sobre resultados existentes. El 1 % es una perturbación ilustrativa; no es un sobreconsumo medido o una distribución de probabilidad.')
    detail = read(base + '20261101_pendiente_anual_pareada/correccion_por_origen_y_rama.csv')
    detail = detail[detail.caso_pendiente.eq('Referencia del Excel')].copy()
    routes = read('data/silver/demanda/asignacion/recorridos_referencia_calculo.csv').set_index(['origen_id', 'sentido'])
    energies = read(base + '20261101_pendiente_anual_pareada/energia_por_recorrido.csv')
    energies = energies[energies.caso_pendiente.eq('Referencia del Excel')]
    distances = []
    for r in detail.itertuples():
        rr = routes.loc[r.origen_id, r.sentido]
        feed = r.rama in ['transferidos', 'alimentacion_otros']
        km = rr.alimentador_km if feed else rr.directa_km
        if not feed and r.sentido == 'hacia_teide':
            vals = energies.loc[energies.comparacion_id.eq('visita_proxima_' + rr.terminal_calculo), 'longitud_km'].unique()
            assert len(vals) == 1
            km += float(vals[0])
        distances.append(km * r.recorridos_coche_anio)
    detail['vehiculos_km_anio'] = distances
    activity = detail.groupby(['alternativa_procedencia', 'rama', 'sentido'], as_index=False)[['recorridos_coche_anio', 'vehiculos_km_anio']].sum()
    activity['unidad_recorridos'] = 'Trayectos equivalentes por sentido; interior añadido una vez a la ida'
    export('actividad_turismos', activity)
    mov = read(base + '20261101_flota_30_tres_sustitutas/movimientos_con_identidad_fisica.parquet')
    mov = mov[mov.politica.eq(POLITICA)].copy()
    annual = mov[~mov.es_diseno_p85].copy()
    annual['viajes_anio'] = annual.dias_equivalentes
    annual['vehiculos_km_anio'] = annual.km_por_recorrido * annual.dias_equivalentes
    buses = annual.assign(servicio=np.where(annual.punto.eq('INTERIOR'), 'Interior', 'Acceso'), tipo_viaje=np.where(annual.componente.eq('comercial'), 'Comercial', 'Vacío')).groupby(['servicio', 'tipo_viaje'], as_index=False)[['viajes_anio', 'vehiculos_km_anio']].sum()
    export('actividad_guaguas', buses)
    expected = float(central.guaguas_mwh_anio.iloc[0])
    costs = read(base + '20261101_flota_30_tres_sustitutas/costes_anuales_reproducidos.csv')
    cost = costs[costs.politica.eq(POLITICA) & costs.referencia_id.eq('referencia_guagua_2')].iloc[0]
    assert abs(buses.vehiculos_km_anio.sum() - cost.vehiculos_km_anio) < 1e-07 and abs(cost.hot_mwh_anio - expected) < 1e-08
    pairs = read(base + '20261101_flota_30_tres_sustitutas/pares_revisados.parquet')
    pairs = pairs[pairs.politica.eq(POLITICA)].copy()
    p = pairs[~pairs.es_diseno_p85]
    people = float((p.personas_asignadas_dia_tipo * p.dias_equivalentes).sum())
    a = activity[activity.alternativa_procedencia.eq(central.alternativa_procedencia.iloc[0])]
    toward = a[a.sentido.eq('hacia_teide')].set_index('rama')
    assert abs(toward.loc['antes', 'recorridos_coche_anio'] - toward.loc['autorizados', 'recorridos_coche_anio'] - toward.loc['transferidos', 'recorridos_coche_anio']) < 1e-08
    table_rows = []
    for (branch, label) in [('antes', 'Coches hasta el Parque sin actuación'), ('autorizados', 'Coches autorizados hasta el Parque'), ('transferidos', 'Coches de alimentación de transferidos'), ('alimentacion_otros', 'Coches adicionales desde otros modos')]:
        t = a[a.rama.eq(branch)]
        table_rows.append([label, numero(toward.loc[branch, 'recorridos_coche_anio'], 0), numero(t.vehiculos_km_anio.sum(), 0)])
    tabla('actividad_coches', 'Actividad privada representada en 2028', ['Rama', 'Entradas o alimentaciones/año', 'Vehículos-km/año'], table_rows, 'Fuente: actividad y perfiles del cálculo. La primera fila corresponde a sin actuación; las otras tres, a con actuación. Las cifras son equivalentes modelizados, no vehículos distintos. Kilómetros con ida, regreso e interior aplicable.', cols='Xrr')
    tabla('actividad_guaguas', 'Actividad anual de las nuevas guaguas', ['Servicio', 'Tipo', 'Viajes de un sentido', 'Vehículos-km'], [[r.servicio, r.tipo_viaje, numero(r.viajes_anio, 0), numero(r.vehiculos_km_anio, 0)] for r in buses.itertuples()], 'Fuente: expediciones ponderadas del horario de estudio. Se incluyen vacíos y cierre diario; el p85 se comprueba aparte y no se anualiza.', cols='XXrr')
    proj = read('data/silver/actividad/corredor_norte/proyeccion_personas_2028.csv')
    export('proyeccion_fuente', proj[['access_corridor', 'direccion', 'colectivo', 'viajes_persona_anuales_referencia', 'tasa_anual_personas', 'factor_crecimiento_personas', 'viajes_persona_proyectados']])
    rates = proj.tasa_anual_personas.unique()
    factors = proj.factor_crecimiento_personas.unique()
    assert len(rates) == len(factors) == 1
    macros = {'TasaPersonas': numero(rates[0] * 100, 4), 'FactorPersonas': numero(factors[0], 6), 'PersonasLanzadera': numero(people, 0), 'PersonasCocheSin': numero(toward.loc['antes', 'recorridos_coche_anio'] * occ, 0), 'PersonasCocheAutorizadas': numero(toward.loc['autorizados', 'recorridos_coche_anio'] * occ, 0), 'PersonasTransferidas': numero(toward.loc['transferidos', 'recorridos_coche_anio'] * occ, 0)}
    assert detail.loc[detail.rama.ne('alimentacion_otros'), 'ocupacion_hipotesis'].eq(occ).all()
    assert abs(toward.loc['transferidos', 'recorridos_coche_anio'] * occ + toward.loc['alimentacion_otros', 'recorridos_coche_anio'] - people) < 1e-07
    with (destino / 'tablas/cifras.tex').open('a') as f:
        f.write('\n'.join(('\\newcommand{\\' + k + '}{' + v + '}' for (k, v) in macros.items())) + '\n')
    selected = mov[mov.observacion.isin([30, 41])]
    selected.to_csv(destino / 'anexos/expediciones_casos.csv', sep=';', index=False, encoding='utf-8-sig', float_format='%.17g')
    export('reservas_casos', pairs[pairs.observacion.isin([30, 41])])
    loads = read(base + '20261101_flota_30_tres_sustitutas/cargas_tramos_revisadas.parquet')
    loads = loads[loads.politica.eq(POLITICA) & loads.observacion.isin([30, 41])]
    export('cargas_casos', loads)
    op = []
    for ((obs, point), g) in selected.groupby(['observacion', 'punto'], sort=True):
        pp = pairs[pairs.observacion.eq(obs) & pairs.punto.eq(point)]
        ll = loads[loads.observacion.eq(obs)] if point == 'INTERIOR' else None
        op.append({'observacion': obs, 'caso': 'Ordinario' if obs == 30 else 'Punta', 'servicio': NOMBRES[point], 'comerciales_ida': int((g.componente.eq('comercial') & g.sentido.eq('ida')).sum()), 'comerciales_vuelta': int((g.componente.eq('comercial') & g.sentido.eq('vuelta')).sum()), 'viajes_vacios': int(g.componente.ne('comercial').sum()), 'vehiculos_km_dia': g.km_por_recorrido.sum(), 'unidades_con_movimientos': g.unidad_fisica_id.nunique(), 'personas_acceso_asignadas': pp.personas_asignadas_dia_tipo.sum() if point != 'INTERIOR' else np.nan, 'max_carga_interior_tramo': ll.personas_asignadas_prueba_dia.max() if point == 'INTERIOR' else np.nan})
    op = pd.DataFrame(op)
    export('operacion_casos', op)
    for (obs, name) in [(30, 'ordinario'), (41, 'punta')]:
        t = op[op.observacion.eq(obs)]
        tabla('operacion_' + name, 'Expediciones del caso ' + name + ' de estudio', ['Servicio', 'Ida', 'Regreso', 'Vacíos', 'Vehículos-km'], [[r.servicio, r.comerciales_ida, r.comerciales_vuelta, r.viajes_vacios, numero(r.vehiculos_km_dia, 1)] for r in t.itertuples()], 'Fuente: movimientos con identidad física, observación ' + str(obs) + '. Ida y regreso son viajes distintos. Unidades de distintos servicios no se suman como flotas independientes.', cols='Xrrrr')
    raw = pd.read_csv(destino / 'anexos/parametros_utilizados.csv', sep=';', keep_default_na=False)
    status = []
    for r in raw.itertuples():
        state = 'Referencia técnica o criterio de configuración'
        note = 'Consultar valor, elección y justificación originales; no equivale por sí solo a actividad de la oferta modulada.'
        if r.id in ['plazas_guagua', 'ocupacion_diseno']:
            state = 'Activo en la capacidad'
            note = '55 plazas nominales y 46 de planificación. La nota histórica «todavía no limita» ha quedado superada por la comprobación de capacidad.'
        elif r.id == 'consumo_comun_complementario_mwh_anio':
            state = 'Pendiente material'
            note = 'Consumo común complementario no estimado; no es cero. Su cancelación exige mantener la hipótesis de igualdad.'
        elif r.id in ['permanencia_min', 'franja_reserva_min']:
            state = 'Pendiente operativo'
            note = 'Reglas de estancia/reserva de coches sin concretar. No confundir con la estancia mínima de 120 minutos de lanzaderas.'
        elif r.id in ['fraccion_interior_sin', 'fraccion_interior_autorizados']:
            state = 'Alternativa no activada'
            note = 'El patrón elegido es una zona próxima por visita; estas cuotas pertenecen a otro tratamiento y no se rellenan automáticamente.'
        elif r.valor_utilizado_en_libro == '':
            state = 'Opción manual sin valor'
            note = 'Se conserva ausente; el método seleccionado determina si aplica. No es un cero ni automáticamente un pendiente del saldo actual.'
        elif r.id in ['metodo_crecimiento', 'anios_excluidos'] or r.id.startswith('tasa_'):
            state = 'Proyección de aforos, distinta de la de personas'
            note = 'Referencia del tratamiento de aforos y reparto de cupo; no es la tasa comparable de personas aplicada al Visor.'
        elif r.id.startswith(('subidas_', 'bajadas_', 'reposiciones_', 'km_', 'flota_')) or r.id in ['flota_interior', 'km_interior']:
            state = 'Antecedente o referencia sustituida en la oferta actual'
            note = 'El balance vigente utiliza la proyección de personas, perfiles del estudio y expediciones reconstruidas; no multiplica automáticamente esta cifra por los días del año.'
        elif r.id in ['reserva_minima_dentro_flota', 'intervalo_refuerzo_punta_min', 'tratamiento_central_guaguas', 'fraccion_captados_coche', 'ocupacion_coche', 'crecimiento_personas', 'calendario', 'cupo_global', 'induccion', 'tratamiento_descenso_turismos'] or 'pendiente' in r.id:
            state = 'Activo en la configuración central'
            note = 'Hipótesis o criterio aplicado, con los límites descritos en el informe; no observación futura.'
        status.append({'id': r.id, 'estado_aplicacion': state, 'aclaracion_vigente': note, 'valor_y_motivo_originales': 'parametros_utilizados.csv; fila con el mismo id'})
    export('estado_parametros', pd.DataFrame(status))
    examples = [x for x in status if x['id'] in ['plazas_guagua', 'km_interior', 'metodo_crecimiento', 'fraccion_interior_sin', 'consumo_comun_complementario_mwh_anio']]
    tabla('estado_parametros', 'Lectura de referencias activas, históricas y pendientes', ['Referencia', 'Aplicación vigente'], [[x['id'].replace('_', ' '), x['aclaracion_vigente']] for x in examples], 'Fuente: anotación documental sobre el inventario original. No modifica valores, elecciones o justificaciones del Excel.', cols='p{43mm}X')
    plt.rcParams.update({'font.family': 'Liberation Sans', 'font.size': 10})

    def save(fig, name):
        for ext in ['pdf', 'png']:
            formatear_ejes(fig)
            fig.savefig(destino / 'figuras' / f'{name}.{ext}', dpi=220, bbox_inches='tight')
        plt.close(fig)

    def box(ax, xy, w, h, text, color='#EFF5F8'):
        (x, y) = xy
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.02', facecolor=color, edgecolor='#0C4767', linewidth=0.9))
        ax.text(x + w / 2, y + h / 2, text, ha='center', va='center', fontsize=10, linespacing=1.4)
    (p,) = _figura_balance_1(box, save)
    _figura_balance_2(box, save)
    (r,) = _figura_balance_3(contribution, save)
    import geopandas as gpd
    cfg = json.loads((root / 'config/asignacion_demanda.json').read_text())
    cols = {c['corredor']: '#' + ''.join((f'{v:02x}' for v in c['rgb'])) for obj in cfg.values() if isinstance(obj, dict) for c in obj.get('colores', [])}
    routes_cfg = {r['aforo']: r for r in cfg['corredores']}
    (col, p) = _figura_balance_4(cols, gpd, root, routes_cfg, save, used)
    descriptions = {'oferta_anual_30_reglas_vigentes_demostrada': 'Se refiere a las reglas anteriores, incluido el intervalo ordinario; False no invalida la comprobación separada con reglas propuestas.', 'circulacion_30_reglas_propuestas_comprobada': 'Comprobación constructiva con máximo 30, tres libres y refuerzo propuesto. No es aprobación del operador.', 'propuesta_adoptada': 'Aceptación operativa/institucional; no confundir con elección del tratamiento energético central.', 'cumplimiento_acreditado': 'Validación del cumplimiento; alcanzar numéricamente 60 no activa esta acreditación.', 'intervalo_confianza': 'Indica si existe intervalo estadístico; False significa que los rangos no son intervalos de confianza.', 'demanda_real_otros_usuarios': 'Ausencia de dato de usuarios interiores ajenos a las cadenas; vacío no equivale a cero.', 'referencia_id': 'referencia_guagua_2: autocar diésel central; referencia_guagua_3: sustituto híbrido urbano; referencia_guagua_1: control diésel urbano.', 'observacion': 'Índice de la observación fuente; 30 = marzo laborable; 41 = julio domingo; -85 = contraste p85, no fecha operativa.', 'plazas_vinculadas': 'Capacidad vinculada de planificación, distinta de personas asignadas.', 'personas_asignadas_dia_tipo': 'Visitas-persona equivalentes de la cadena de ida y regreso; no embarques sumables como personas nuevas.', 'max_carga_interior_tramo': 'Máxima carga modelizada de visitas en un tramo interior del caso; no incluye usuarios sin dato.', 'unidad_fisica_id': 'Identidad del mismo vehículo a través de los movimientos; no sumar identificadores locales como flotas distintas.', 'dias_equivalentes': 'Peso de la observación fuente en la anualización; p85 tiene peso cero.', 'recorridos_coche_anio': 'Trayectos equivalentes de coches por sentido, no matrículas distintas.', 'rama': 'antes: sin actuación; autorizados, transferidos y alimentación de otros: con actuación.', 'saldo_tep_anio': 'Saldo de la comprobación algebraica, con actividad fija y sin probabilidad asignada.'}
    dictionary = []
    for p in sorted((destino / 'anexos').glob('*.csv')):
        if p.stem == 'diccionario_anexos':
            continue
        frame = pd.read_csv(p, sep=';', keep_default_na=False)
        for col in frame:
            unit = 'MWh/año' if 'mwh_anio' in col else 'tep/año' if 'tep_anio' in col else 'vehículos-km/año' if 'vehiculos_km_anio' in col else 'minutos desde 00:00' if col.endswith('_min') and col.startswith(('salida', 'llegada', 'interior')) else 'minutos' if col.endswith('_min') else 'Fracción' if 'fraccion' in col else 'Porcentaje' if col.endswith('_pct') else 'Según nombre de campo y fuente'
            meaning = descriptions.get(col, 'Campo conservado de la exportación; su nombre identifica magnitud, clasificación o estado. No interpretar una celda vacía como cero.')
            dictionary.append({'archivo': p.name, 'campo': col, 'unidad_o_lectura': unit, 'aclaracion': meaning})
    export('diccionario_anexos', pd.DataFrame(dictionary))
    meta = json.loads((destino / 'metadatos.json').read_text())
    meta['decision'] = 'D221'
    meta['version_informe'] = '0.2'
    meta['estado'] = 'Borrador revisado para evaluación técnica'
    meta.pop('revision_documento', None)
    meta['inputs_sha256'].update({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in set(used) | {Path(__file__)}})
    meta['derivados_sha256'] = {str(p.relative_to(destino)): hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['anexos', 'tablas', 'figuras'] for p in (destino / folder).iterdir() if p.is_file()}
    meta['revision_prioritaria'] = {'cambio_de_modelo': False, 'balance_central_conservado': True, 'comprobacion_combinada': 'Aritmética de resultados existentes con actividad fija; no caso adoptado', 'parametros_originales_conservados': True, 'anexo_estado_separado_del_excel': True, 'casos_operativos_fuente': [30, 41], 'calendario_mensual_nuevo': False, 'anexos_csv': len(list((destino / 'anexos').glob('*.csv'))), 'referencia_editorial': 'TFM aportado: secuencia contexto–método–resultados y diagramas explicativos; no fuente de datos de movilidad.'}
    (destino / 'metadatos.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    resumen = {'version': '0.2', 'anexos_csv': len(list((destino / 'anexos').glob('*.csv'))), 'personas_lanzadera_anio': people, 'vehiculos_km_guaguas_anio': float(buses.vehiculos_km_anio.sum()), 'modelo_modificado': False}
    return resumen

def _figura_balance_1(box, save):
    (fig, ax) = plt.subplots(figsize=(6.3, 3.4))
    ax.axis('off')
    ax.set(xlim=(0, 10), ylim=(0, 6))
    for (j, (t, sub)) in enumerate([('1. Personas', 'Demanda y proyección'), ('2. Movilidad', 'Coches, guaguas y reservas'), ('3. Recorridos', 'Ida, interior, regreso y vacíos'), ('4. Energía', 'Kilómetros × consumo')]):
        x = 0.1 + [0, 1, 1, 0][j] * 5
        y = 4.1 - j // 2 * 2.7
        box(ax, (x, y), 4.7, 1.5, t + '\n' + sub)
    for (p, q) in [((4.8, 4.85), (5.05, 4.85)), ((7.4, 4), (7.4, 3.2)), ((5.0, 2), (4.8, 2))]:
        ax.annotate('', xy=q, xytext=p, arrowprops={'arrowstyle': '->', 'lw': 1.3, 'color': '#397568'})
    ax.text(5, 0.25, 'Misma demanda de partida → dos escenarios → diferencia anual de energía', ha='center', fontsize=10, color='#0C4767')
    save(fig, 'proceso_calculo')
    return (p,)

def _figura_balance_2(box, save):
    (fig, ax) = plt.subplots(figsize=(6.3, 3.1))
    ax.axis('off')
    ax.set(xlim=(0, 10), ylim=(0, 7))
    box(ax, (0.2, 5.2), 9.6, 1.1, 'Una misma demanda de visitas, también en días de alta demanda')
    box(ax, (0.2, 1.8), 4.5, 2.4, 'SIN INTERVENCIÓN\nMovilidad existente proyectada\nCoche hasta el Parque\nServicios existentes')
    box(ax, (5.3, 1.8), 4.5, 2.4, 'CON INTERVENCIÓN\nCoches autorizados y alimentación\nLanzaderas de acceso e interior\nServicios existentes', color='#EEF5F2')
    for x in [2.45, 7.55]:
        ax.annotate('', xy=(x, 4.25), xytext=(x, 5.15), arrowprops={'arrowstyle': '->', 'color': '#397568'})
    ax.text(5, 0.6, 'Ahorro = energía sin intervención − energía con intervención', ha='center', fontsize=11, color='#0C4767')
    save(fig, 'escenarios_pareados')
    return ()

def _figura_balance_3(contribution, save):
    (fig, ax) = plt.subplots(figsize=(6.3, 2.8))
    for (i, r) in enumerate(contribution.itertuples()):
        ax.barh(i, r.hot_sin_ajuste_turismos_tep_anio, color='#0C4767', label='Hot sin ajuste propio de turismos' if i == 0 else None)
        ax.barh(i, r.aporte_neto_pendiente_tep_anio, left=r.hot_sin_ajuste_turismos_tep_anio, color='#397568', hatch='///', label='Aporte neto de pendiente' if i == 0 else None)
        ax.text(r.hot_central_tep_anio + 1, i, numero(r.hot_central_tep_anio), va='center')
    ax.axvline(60, color='#24343D', ls='--')
    ax.set(yticks=[0, 1], yticklabels=['Asignación A', 'Asignación B'], xlim=(0, 92), xlabel='Ahorro (tep/año)')
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.22), frameon=False, ncol=1, fontsize=9)
    fig.tight_layout()
    save(fig, 'aporte_pendiente')
    return (r,)

def _figura_balance_4(cols, gpd, root, routes_cfg, save, used):
    (fig, ax) = plt.subplots(figsize=(6.3, 4.5))
    for (group, key, label) in [('chio_boca_tauce', 'CHIO', 'Chío'), ('aguamansa_el_portillo', 'OROTAVA', 'Aguamansa'), ('la_esperanza_el_portillo', 'LAGUNA', 'La Esperanza'), ('vilaflor_boca_tauce', 'VILAFLOR', 'Vilaflor'), ('interior_boca_tauce_el_portillo', None, 'Interior')]:
        p = next((root / 'data/silver/geografia/perfiles_altimetricos' / group).glob('perfil*ida*.parquet'))
        used.append(p)
        g = gpd.read_parquet(p).to_crs(4326)
        x = g.geometry.x.to_numpy()
        y = g.geometry.y.to_numpy()
        col = cols[routes_cfg[key]['corredor']] if key else '#397568'
        ax.plot(x, y, color=col, lw=1.8, label=label)
        if key:
            pos = int(np.argmax(g.distance_from_reference_m.to_numpy())) if 'distance_from_reference_m' in g else 0
            ax.scatter(x[pos], y[pos], marker='*', c=col, s=100, zorder=4)
            ax.annotate(label, (x[pos], y[pos]), xytext=(5, 5), textcoords='offset points', fontsize=9)
        else:
            for (pos, lab, off) in [(0, 'Boca Tauce', (-45, -14)), (-1, 'El Portillo', (4, -12))]:
                ax.scatter(x[pos], y[pos], marker='s', c='#0C4767', s=32)
                ax.annotate(lab, (x[pos], y[pos]), xytext=off, textcoords='offset points', fontsize=9)
    ax.set_aspect(1 / np.cos(np.deg2rad(28.3)))
    ax.set(xlabel='Longitud (°)', ylabel='Latitud (°)', title='Accesos y eje interior: trazados de estudio')
    ax.grid(alpha=0.18)
    ax.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    save(fig, 'localizacion_servicios')
    return (col, p)
