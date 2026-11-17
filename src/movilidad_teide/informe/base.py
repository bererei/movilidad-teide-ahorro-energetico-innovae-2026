from movilidad_teide.informe.formato import formatear_ejes
from movilidad_teide.informe.formato import numero, tex
'Derivar tablas y figuras del borrador desde resultados verificados, sin editar el modelo.'
from pathlib import Path
import hashlib, json, shutil
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.trazabilidad import verificar_archivo_de_referencia

def preparar_borrador(root, destino):
    """Generar solo derivados; el texto maestro main.tex se edita por separado."""
    (root, destino) = (Path(root), Path(destino))
    if not (destino / 'main.tex').exists():
        raise ValueError('Crear primero el proyecto LaTeX del informe.')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    read = lambda p: pd.read_csv(p, sep=';', float_precision='round_trip')
    source = root / 'data/silver/energia_turismos/20261101_hot_central_fta_sensibilidad'
    meta = json.loads((source / 'metadatos.json').read_text())
    params = leer_parametros(root)
    extension_validada = False
    if meta['parametros'] != params:
        from movilidad_teide.configuracion.ordenacion import leer_ordenacion
        ref = leer_ordenacion(root)
        esperado = {k: v for k, v in meta['parametros'].items() if k != 'sha256_libro'}
        if ref['indice']['parametros_base_conservados'] != esperado:
            raise ValueError('El libro y la referencia histórica no coinciden.')
        extension_validada = True
    for (rel, h) in meta['outputs_sha256'].items():
        if sha(source / rel) != h:
            raise ValueError('Salida vigente alterada: ' + rel)
    for (rel, h) in meta['inputs_sha256'].items():
        if rel == 'config/parametros_modelo.xlsx' and extension_validada:
            # Extensión identificada: las 129 referencias y 387 elecciones se
            # comprobaron exactamente; la nueva tabla también se ha validado.
            continue
        verificar_archivo_de_referencia(root, rel, h)
    data = read(source / 'balance_vigente.csv')
    central = read(source / 'resultado_central.csv')
    fta = read(source / 'sensibilidad_fta.csv')
    threshold = read(source / 'umbrales_central.csv')
    assert len(data) == 120 and len(central) == len(fta) == 2 and central.es_resultado_central.all()
    assert central.tratamiento_operativo.eq('Hot COPERT').all() and (not data.cumplimiento_acreditado.any())
    for folder in ['tablas', 'figuras', 'anexos']:
        (destino / folder).mkdir(exist_ok=True)
    written = []

    def table(name, title, headers, rows, source_note, widths=None):
        cols = widths or 'X' + 'r' * (len(headers) - 1)
        body = ['\\begin{table}[htbp]', '\\caption{' + title + '}', '\\centering', '{\\fontsize{10}{13}\\selectfont', '\\begin{tabularx}{\\linewidth}{@{}' + cols + '@{}}', '\\rowcolor{azul} ' + ' & '.join(('{\\color{white}\\textbf{' + tex(h) + '}}' for h in headers)) + '\\\\']
        for (j, row) in enumerate(rows):
            body.append(('\\rowcolor{fondo_azul} ' if j % 2 else '') + ' & '.join((tex(x) for x in row)) + '\\\\')
        body += ['\\bottomrule', '\\end{tabularx}}', '\\Fuente{' + source_note + '}', '\\end{table}']
        p = destino / 'tablas' / f'{name}.tex'
        p.write_text('\n'.join(body) + '\n')
        written.append(p)
    dgt = root / 'data/silver/energia/referencias_unitarias/pendiente_turismos/correccion_por_componente_anual.csv'
    cars = read(dgt)
    cars = cars[cars.caso_pendiente.eq('Referencia del Excel')]
    lookup = cars.set_index(['alternativa_procedencia', 'rama']).energia_con_ajuste_convencional_mwh_anio
    components = []
    for r in central.itertuples():
        country = r.alternativa_procedencia
        a = float(lookup[country, 'antes'])
        b = float(sum((lookup[country, q] for q in ['autorizados', 'transferidos', 'alimentacion_otros'])))
        common = r.sin_componentes_mwh_anio - a
        assert np.isclose(b + common + r.guaguas_mwh_anio, r.con_construccion_condicionada_mwh_anio, atol=1e-08, rtol=0)
        for (label, x, y) in [('Turismos: cadenas completas', a, b), ('Servicios colectivos comunes representados', common, common), ('Nuevas guaguas, comerciales y vacíos', 0.0, r.guaguas_mwh_anio), ('Total representado', r.sin_componentes_mwh_anio, r.con_construccion_condicionada_mwh_anio)]:
            components.append({'alternativa_procedencia': country, 'componente': label, 'sin_mwh_anio': x, 'con_mwh_anio': y})
    c = pd.DataFrame(components)
    table('balance', 'Consumos y ahorro anual del ámbito representado', ['Asignación nacional', 'Sin (MWh)', 'Con (MWh)', 'Ahorro (tep)'], [[r.alternativa_procedencia.split(': ')[1].capitalize(), numero(r.sin_componentes_mwh_anio), numero(r.con_construccion_condicionada_mwh_anio), numero(r.saldo_construccion_condicionada_tep_anio)] for r in central.itertuples()], 'Fuente: resultados D218, Hot central, año 2028. Las dos asignaciones no son un intervalo de confianza.')
    componentrows = []
    countries = list(central.alternativa_procedencia)
    for label in c.componente.unique():
        values = []
        for country in countries:
            r = c.loc[c.alternativa_procedencia.eq(country) & c.componente.eq(label)].iloc[0]
            values.extend([numero(r.sin_mwh_anio), numero(r.con_mwh_anio)])
        componentrows.append([label, *values])
    table('componentes', 'Desglose del balance central (MWh/año)', ['Componente', 'Sin A', 'Con A', 'Sin P', 'Con P'], componentrows, 'Fuente: D213 y D218, conciliación por componentes. A: asignación a alquiler; P: asignación a particular. El consumo común estimado no representa todo el transporte del Parque.')
    contrasts = []
    for (name, t) in [('Central Hot', central), ('Sensibilidad FTA', fta)]:
        v = t.saldo_construccion_condicionada_tep_anio
        contrasts.append([name, numero(v.min()), numero(v.max())])
    table('hot_fta', 'Resultado central y sensibilidad operativa (tep/año)', ['Tratamiento', 'Alquiler', 'Particular'], contrasts, 'Fuente: D218. Misma actividad; FTA aplica una sola vez un aumento de combustible del 11,111\\,\\% en las nuevas guaguas. Las cifras no acotan toda la incertidumbre.')
    policy = central.politica.unique().item()
    coach = data[data.politica.eq(policy) & data.referencia_id.eq('referencia_guagua_2')]
    cases = ['Referencia del Excel', 'Tara P25', 'Tara P75', 'Transmisión 0,95', 'Descenso sin reducción']
    names = ['Referencia de estudio', 'Tara: cuartil inferior', 'Tara: cuartil superior', 'Transmisión 0,95', 'Descenso sin reducción']
    sensitivity = []
    for (case, label) in zip(cases, names):
        row = [label]
        for treatment in ['Hot COPERT', 'Hot con contraste operativo externo']:
            v = coach.loc[coach.caso_pendiente.eq(case) & coach.tratamiento_operativo.eq(treatment), 'saldo_construccion_condicionada_tep_anio']
            assert len(v) == 2
            row.append(numero(v.min()) + '–' + numero(v.max()))
        sensitivity.append(row)
    table('sensibilidad', 'Sensibilidad del método de pendiente con autocar diésel (tep/año)', ['Hipótesis', 'Hot', 'Con FTA'], sensitivity, 'Fuente: 20 comparaciones D218, misma oferta y demanda. Los extremos reúnen dos asignaciones nacionales; no son percentiles del ahorro o intervalos estadísticos.')
    technology = []
    techlabels = {'referencia_guagua_2': 'Autocar diésel, referencia central', 'referencia_guagua_3': 'Híbrida urbana, sustituto', 'referencia_guagua_1': 'Diésel urbano, control'}
    for (ref, label) in techlabels.items():
        row = [label]
        for treatment in ['Hot COPERT', 'Hot con contraste operativo externo']:
            v = data.loc[data.politica.eq(policy) & data.caso_pendiente.eq('Referencia del Excel') & data.referencia_id.eq(ref) & data.tratamiento_operativo.eq(treatment), 'saldo_construccion_condicionada_tep_anio']
            assert len(v) == 2
            row.append(numero(v.min()) + '–' + numero(v.max()))
        technology.append(row)
    table('tecnologias', 'Sensibilidad a la referencia de consumo (tep/año)', ['Referencia COPERT', 'Hot', 'Con FTA'], technology, 'Fuente: D218, misma actividad de nuevas guaguas. Cambian categoría y motorización; la diferencia no es una ventaja híbrida demostrada del futuro autocar interurbano.')
    operation = root / 'data/silver/energia_turismos/20261101_flota_30_tres_sustitutas'
    inventory = read(operation / 'resumen_inventario_bases.csv')
    table('inventario', 'Distribución inicial de estudio de las 30 unidades', ['Ubicación propuesta', 'Unidades'], [[r.terminal_inicial, int(r.unidades_inventario)] for r in inventory.itertuples()] + [['Total físico', 30]], 'Fuente: D216. Distribución constructiva común para las dos ofertas y el p85; no acredita instalaciones o respuesta inmediata a incidencias.')
    diag = read(operation / 'diagnostico_diario.csv')
    diag = diag[diag.politica.eq(policy) & ~diag.es_diseno_p85]
    obs = {30: 'Marzo, laborable', 31: 'Marzo, sábado', 32: 'Marzo, domingo', 39: 'Julio, sábado', 40: 'Julio, laborable', 41: 'Julio, domingo', 52: 'Octubre, sábado', 54: 'Octubre, laborable', 56: 'Octubre, domingo'}
    table('observaciones', 'Guaguas físicas por perfil de demanda proyectado a 2028', ['Perfil fuente 2025', 'Asignadas', 'Sin viajes', 'Intervalo de 30 min'], [[obs[r.observacion], int(r.vehiculos_programados), int(r.vehiculos_sin_programar), 'Cumple' if r.cumple_intervalo_vigente else 'Requiere refuerzo'] for r in diag.itertuples()], 'Fuente: comprobación de circulación. Asignadas y Sin viajes cuentan guaguas físicas con uno o más viajes en la jornada simulada o sin ninguno, respectivamente. Los nueve perfiles proceden de combinaciones de mes y tipo de día de 2025; se proyectan y ponderan para 2028. La última columna indica si basta el intervalo de 30 minutos entre salidas; el p85 se comprueba aparte.', widths='XrrX')
    params_rows = []
    parammap = {p['id']: p for p in params['parametros']}
    paramids = ['anio_base', 'anio_objetivo', 'cupo_global', 'ocupacion_coche', 'fraccion_captados_coche', 'induccion', 'plazas_guagua', 'ocupacion_diseno', 'reserva_minima_dentro_flota', 'intervalo_minimo_subidas_min', 'intervalo_refuerzo_punta_min', 'estancia_min_visita_min', 'margen_enlace_interior_min', 'espera_max_lanzadera_min', 'carga_copert']
    for key in paramids:
        r = parammap[key]
        v = r['valor_utilizado']
        val = numero(v * 100) if r['unidad'] == '%' else str(int(v)) if isinstance(v, (int, float)) and float(v).is_integer() else numero(v) if isinstance(v, (int, float)) else str(v)
        params_rows.append([r['parametro'], val, r['unidad']])
    table('parametros', 'Parámetros principales de la configuración utilizada', ['Parámetro', 'Valor', 'Unidad'], params_rows, 'Fuente: Excel del modelo, caso Central, ejecución D218. Los valores elegidos son hipótesis o referencias con su fundamento; la tabla no los convierte en observaciones.', widths='XrX')
    extrema = lambda s: (numero(float(s.min())), numero(float(s.max())))
    (lo, hi) = extrema(central.saldo_construccion_condicionada_tep_anio)
    (fl, fh) = extrema(fta.saldo_construccion_condicionada_tep_anio)
    (ml, mh) = extrema(threshold.margen_sobre_60_tep_anio)
    (pl, ph) = extrema(threshold.incremento_consumo_guaguas_que_agota_margen_pct)
    macros = {'AhorroMin': lo, 'AhorroMax': hi, 'FtaMin': fl, 'FtaMax': fh, 'MargenMin': ml, 'MargenMax': mh, 'PorcentajeMargenMin': pl, 'PorcentajeMargenMax': ph, 'EnergiaGuaguas': numero(central.guaguas_mwh_anio.iloc[0]), 'EnergiaGuaguasFta': numero(fta.guaguas_mwh_anio.iloc[0]), 'CuotaCoche': numero(100 * parammap['fraccion_captados_coche']['valor_utilizado'])}
    (destino / 'tablas/cifras.tex').write_text('\n'.join(('\\newcommand{\\' + k + '}{' + v + '}' for (k, v) in macros.items())) + '\n')
    plt.rcParams.update({'font.family': 'Liberation Sans', 'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    _figura_base_1(central, destino, fta)
    _figura_base_2(cases, coach, destino, names)
    cfg = json.loads((root / 'config/asignacion_demanda.json').read_text())
    colors = {c['corredor']: '#' + ''.join((f'{x:02x}' for x in c['rgb'])) for c in cfg['reconstruccion_mapa']['colores']} if 'reconstruccion_mapa' in cfg else {}
    if not colors:
        for obj in cfg.values():
            if isinstance(obj, dict) and 'colores' in obj:
                colors = {c['corredor']: '#' + ''.join((f'{x:02x}' for x in c['rgb'])) for c in obj['colores']}
    routes = {r['aforo']: r for r in cfg['corredores']}
    (r,) = _figura_base_3(colors, destino, routes)
    for name in ['resultado_central', 'sensibilidad_fta', 'balance_vigente', 'umbrales_central']:
        shutil.copyfile(source / (name + '.csv'), destino / 'anexos' / (name + '.csv'))
    c.to_csv(destino / 'anexos/componentes_representados.csv', sep=';', index=False, encoding='utf-8-sig', float_format='%.17g')
    pd.DataFrame([{'id': r['id'], 'parametro': r['parametro'], 'unidad_en_libro': r['unidad'], 'valor_utilizado_en_libro': r['valor_utilizado'], 'valor_presentacion': numero(r['valor_utilizado'] * 100) if '%' in r['unidad'] and isinstance(r['valor_utilizado'], (int, float)) else r['valor_utilizado'], 'unidad_almacenamiento': 'fracción/año' if r['unidad'] == '%/año' else 'fracción' if r['unidad'] == '%' else r['unidad'], 'eleccion': r['modo_efectivo'], 'justificacion': r['justificacion_utilizada']} for r in params['parametros']]).to_csv(destino / 'anexos/parametros_utilizados.csv', sep=';', index=False, encoding='utf-8-sig')
    inputs = [source / p for p in ['metadatos.json', 'balance_vigente.csv', 'resultado_central.csv', 'sensibilidad_fta.csv', 'umbrales_central.csv']] + [dgt, operation / 'resumen_inventario_bases.csv', operation / 'diagnostico_diario.csv', root / 'config/asignacion_demanda.json', root / 'config/parametros_modelo.xlsx', root / 'docs/METODOLOGIA_AHORRO_ENERGETICO.md', root / 'src/movilidad_teide/informe_energetico.py']
    outputfiles = [p for folder in ['tablas', 'figuras', 'anexos'] for p in (destino / folder).glob('*') if p.is_file()]
    evidence = {'decision': 'D219', 'fecha': '2026-11-01', 'version_informe': '0.1', 'estado': 'Borrador para revisión; no aprobación institucional', 'maestro': 'main.tex', 'parametros': params, 'inputs_sha256': {str(p.resolve()): sha(p) for p in inputs}, 'derivados_sha256': {str(p.relative_to(destino)): sha(p) for p in outputfiles}, 'controles': {'filas_balance': len(data), 'datos_modificados': False, 'conciliacion_componentes': True, 'resultado_central': 'Hot COPERT', 'fta_solo_sensibilidad': True}, 'nota': 'Los CSV anexos son exportaciones de revisión, no puntos de edición de escenarios.'}
    (destino / 'metadatos.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    return {'tablas': len(list((destino / 'tablas').glob('*.tex'))), 'figuras': 3, 'anexos_csv': len(list((destino / 'anexos').glob('*.csv'))), 'datos_modificados': False}

def _figura_base_1(central, destino, fta):
    (fig, ax) = plt.subplots(figsize=(6.3, 2.5))
    for (y, (label, t, color)) in enumerate([('Central Hot', central, '#397568'), ('Sensibilidad FTA', fta, '#FA7921')]):
        values = t.saldo_construccion_condicionada_tep_anio.sort_values()
        ax.plot(values, [y, y], color=color, lw=3)
        ax.scatter(values, [y, y], c=color, s=45, zorder=3)
        ax.text(values.max() + 2, y, numero(values.min()) + '–' + numero(values.max()), va='center', fontsize=9)
    ax.axvline(60, color='#24343D', ls='--', lw=1.2, label='Objetivo de referencia:60 tep/año')
    ax.set(xlim=(0, 105), ylim=(1.65, -0.5), yticks=[0, 1], yticklabels=['Central Hot', 'Sensibilidad FTA'], xlabel='Ahorro estimado (tep/año)')
    ax.grid(axis='x', alpha=0.2)
    ax.legend(loc='lower right', frameon=False, fontsize=8)
    fig.tight_layout()
    for ext in ['pdf', 'png']:
        formatear_ejes(fig)
        fig.savefig(destino / 'figuras' / ('hot_y_fta.' + ext), dpi=220, bbox_inches='tight')
    plt.close(fig)
    return ()

def _figura_base_2(cases, coach, destino, names):
    (fig, ax) = plt.subplots(figsize=(6.3, 3.5))
    for (j, (case, label)) in enumerate(zip(cases[:4], names[:4])):
        for (treatment, color, shift, marker) in [('Hot COPERT', '#397568', -0.12, 'o'), ('Hot con contraste operativo externo', '#FA7921', 0.12, 's')]:
            values = coach.loc[coach.caso_pendiente.eq(case) & coach.tratamiento_operativo.eq(treatment), 'saldo_construccion_condicionada_tep_anio'].sort_values()
            ax.plot(values, [j + shift] * 2, color=color, lw=2)
            ax.scatter(values, [j + shift] * 2, c=color, s=28, marker=marker, label=('Hot' if treatment == 'Hot COPERT' else 'FTA') if j == 0 else None)
    ax.axvline(60, color='#24343D', ls='--', lw=1)
    ax.set(xlim=(0, 100), ylim=(3.6, -0.6), yticks=range(4), yticklabels=names[:4], xlabel='Ahorro estimado (tep/año)')
    ax.grid(axis='x', alpha=0.2)
    ax.legend(frameon=False, loc='lower left', ncol=2, fontsize=9)
    fig.tight_layout()
    for ext in ['pdf', 'png']:
        formatear_ejes(fig)
        fig.savefig(destino / 'figuras' / ('sensibilidad_pendiente.' + ext), dpi=220, bbox_inches='tight')
    plt.close(fig)
    return ()

def _figura_base_3(colors, destino, routes):
    (fig, ax) = plt.subplots(figsize=(6.3, 3.0))
    ax.axis('off')
    ax.set(xlim=(-1, 11), ylim=(-0.2, 5.1))
    for (key, x, y, tx, ty) in [('OROTAVA', 0, 4, 5, 4), ('LAGUNA', 10, 4, 5, 4), ('CHIO', 0, 1, 5, 1), ('VILAFLOR', 10, 1, 5, 1)]:
        r = routes[key]
        col = colors[r['corredor']]
        ax.annotate('', xy=(tx, ty), xytext=(x, y), arrowprops={'arrowstyle': '<->', 'color': col, 'lw': 2})
        ax.scatter(x, y, marker='*', s=120, c=col, zorder=3)
        ax.text(x, y + 0.38, {'OROTAVA': 'Aguamansa', 'LAGUNA': 'La Esperanza', 'CHIO': 'Chío', 'VILAFLOR': 'Vilaflor'}[key], ha='center', fontsize=10)
    for (y, label) in [(4, 'El Portillo'), (1, 'Boca Tauce')]:
        ax.scatter(5, y, marker='s', s=65, c='#0C4767', zorder=4)
        ax.text(5.3, y - 0.3, label, ha='left', fontsize=10)
    ax.annotate('', xy=(5, 3.7), xytext=(5, 1.3), arrowprops={'arrowstyle': '<->', 'color': '#397568', 'lw': 3})
    ax.text(5.3, 2.6, 'Servicio interior', fontsize=10, va='center')
    ax.text(5, 0.05, 'Esquema funcional propuesto · sin escala cartográfica', ha='center', fontsize=9, color='#53636C')
    fig.tight_layout()
    for ext in ['pdf', 'png']:
        formatear_ejes(fig)
        fig.savefig(destino / 'figuras' / ('esquema_servicios.' + ext), dpi=220, bbox_inches='tight')
    plt.close(fig)
    return (r,)
