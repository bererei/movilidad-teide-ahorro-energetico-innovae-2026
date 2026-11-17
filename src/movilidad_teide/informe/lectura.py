"""Presentación y diccionario de lectura del informe, sin alterar datos del modelo."""
from movilidad_teide.informe.formato import formatear_ejes
from pathlib import Path
import json, hashlib, re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from pyproj import Geod
from movilidad_teide.informe.formato import numero, tex
from movilidad_teide.informe.diccionario import _definiciones

def actualizar_lectura(root, destino, resumen):
    (root, destino) = (Path(root), Path(destino))

    def rd(name):
        return pd.read_csv(destino / 'anexos' / name, sep=';', float_precision='round_trip')
    notes = {'D213 y D218, conciliación por componentes. A: asignación a alquiler; P: asignación a particular.': 'corrección anual de pendiente y balance central, conciliados por componentes.', 'D218, misma actividad de nuevas guaguas.': 'comparación de referencias de consumo, con la misma actividad de nuevas guaguas.', 'D218. Misma actividad;': 'balance anual conservado. Misma actividad;', '20 comparaciones D218, misma oferta y demanda.': 'veinte comparaciones del balance conservado, con la misma oferta y demanda.', 'D216. Distribución constructiva común': 'comprobación de circulación de treinta vehículos. Distribución común', 'D216. Son observaciones ponderadas': 'comprobación de circulación. Son observaciones ponderadas', 'ejecución D218.': 'exportación del cálculo central.', 'Sin A': 'Sin · alquiler', 'Con A': 'Con · alquiler', 'Sin P': 'Sin · particular', 'Con P': 'Con · particular', 'Tara: cuartil inferior': 'Menor masa: cuartil inferior', 'Tara: cuartil superior': 'Mayor masa: cuartil superior', 'Transmisión 0,95': 'Transmisión del 95 %', 'Máximo de coches privados para TODO el Parque': 'Cupo global diario de coches privados', 'Captados que habrían viajado en coche': 'Captados que habrían usado coche, antes del cupo', 'Proporción de plazas de diseño': 'Plazas nominales utilizables para planificar', 'Carga física de la prueba COPERT': 'Carga técnica del factor COPERT para viajes con pasajeros', 'vehículos distintos': 'vehículos diferentes', 'observación 30.': 'caso ordinario de marzo laborable.', 'observación 41.': 'caso de punta de julio domingo.'}
    for p in (destino / 'tablas').glob('*.tex'):
        s = p.read_text()
        for (a, b) in notes.items():
            s = s.replace(a, tex(b) if a == 'Transmisión 0,95' else b)
        assert not re.search('\\b[DFHP]\\d{3}\\b', s), (p.name, s)
        s = re.sub('p\\{(\\d+mm)\\}', 'L{\\1}', s)
        p.write_text(s)
    p = destino / 'tablas/componentes.tex'
    s = p.read_text().replace('L{46mm}rrrr', 'Xrrrr')
    for scenario in ['Sin', 'Con']:
        for country in ['alquiler', 'particular']:
            s = s.replace(scenario + ' · ' + country, '\\shortstack{' + scenario + '\\\\' + country + '}')
    p.write_text(s)
    p = destino / 'tablas/tecnologias.tex'
    s = p.read_text()
    s = re.sub('(-\\d+,\\d+)–(-\\d+,\\d+)', '\\1 a \\2', s)
    p.write_text(s)
    names = rd('parametros_utilizados.csv').set_index('id').parametro.to_dict()
    labels = {'plazas_guagua': 'Plazas nominales del vehículo', 'km_interior': 'Distancia interior publicada por el Visor', 'metodo_crecimiento': 'Proyección histórica de aforos', 'fraccion_interior_sin': 'Cuota interior de una alternativa no activada', 'consumo_comun_complementario_mwh_anio': 'Consumo común complementario'}
    p = destino / 'tablas/estado_parametros.tex'
    s = p.read_text()
    for (k, v) in labels.items():
        s = s.replace(k.replace('_', ' '), v)
    p.write_text(s)
    status = rd('estado_parametros.csv')
    status.insert(1, 'nombre_parametro', status.id.map(names))
    status.to_csv(destino / 'anexos/estado_parametros.csv', sep=';', index=False, encoding='utf-8-sig')
    trace = [['Demanda y proyección', 'data/silver/actividad/corredor_norte/proyeccion_personas_2028.csv', 'Ponderar observaciones por tipo de día y aplicar la tasa comparable elegida.', 'proyeccion_fuente.csv', 'Viajes de personas al año, por sentido'], ['Recorridos y composición', 'config/itinerarios.json; config/asignacion_demanda.json; config/parametros_modelo.xlsx', 'Asignar orígenes, cabeceras, recorridos y categorías, conservando las elecciones del libro.', 'actividad_turismos.csv', 'Trayectos y vehículos-kilómetro anuales'], ['Oferta y capacidad', 'data/silver/energia_turismos/20261101_flota_30_tres_sustitutas/', 'Vincular ida, interior y regreso; comprobar plazas, identidad de unidades y cierre de bases.', 'actividad_guaguas.csv; expediciones_casos.csv; reservas_casos.csv; cargas_casos.csv', 'Viajes, vehículos-kilómetro y personas por tramo'], ['Consumo de vehículos', 'src/movilidad_teide/copert_cli.py; data/silver/copert/', 'Seleccionar factores de energía por categoría y condiciones; aplicarlos a recorridos, sin convertir de nuevo una energía ya exportada.', 'componentes_representados.csv', 'Megavatios-hora al año'], ['Pendiente de turismos', 'src/movilidad_teide/pendiente_anual.py; data/silver/energia/referencias_unitarias/pendiente_turismos/', 'Aplicar trabajo gravitatorio por tramo y grupo, sumar cadenas de ambos escenarios y restar sus correcciones.', 'contribucion_pendiente.csv', 'Toneladas equivalentes de petróleo al año'], ['Balance y contraste', 'data/silver/energia_turismos/20261101_hot_central_fta_sensibilidad/', 'Restar consumos anuales comparables, convertir unidades y separar el tratamiento central de la sensibilidad.', 'resultado_central.csv; sensibilidad_fta.csv; umbrales_central.csv', 'Megavatios-hora y toneladas equivalentes de petróleo al año'], ['Preparación del informe', 'src/movilidad_teide/informe_revision.py; src/movilidad_teide/informe_lectura.py; src/movilidad_teide/informe_narrativa.py; src/movilidad_teide/informe_escenarios.py', 'Exportar tablas y figuras, diccionario y correspondencia de etapas; no modifica el modelo energético.', 'docs/informe_energetico/main.tex; docs/informe_energetico/metadatos.json', 'Documento y evidencia de reproducción']]
    pd.DataFrame(trace, columns=['etapa', 'entrada_en_repositorio', 'operacion', 'salida_informe', 'unidad_salida']).to_csv(destino / 'anexos/trazabilidad_metodo.csv', sep=';', index=False, encoding='utf-8-sig')
    lines = ['\\begin{table}[!htbp]', '\\caption{Cómo seguir las etapas del estudio en el repositorio}', '\\centering{\\fontsize{10}{13}\\selectfont', '\\begin{tabularx}{\\linewidth}{@{}L{34mm}X@{}}', '\\rowcolor{azul}\\Blanco{Etapa} & \\Blanco{Dónde comprobarla}\\\\']
    short = [('Demanda y proyección', 'data/silver/actividad/corredor_norte/', 'Las cantidades y tasas se consultan también en el anexo de proyección.'), ('Reglas y recorridos', 'config/parametros_modelo.xlsx', 'Las rutas y la asignación territorial se documentan junto al libro en la configuración.'), ('Operación y balance', 'data/silver/energia_turismos/', 'Las exportaciones conservan escenarios, expediciones y verificaciones; el anexo de trazabilidad identifica las carpetas concretas.'), ('Método y ejecución', 'docs/METODOLOGIA_AHORRO_ENERGETICO.md', 'El cuaderno de cálculo ejecuta el procedimiento y enlaza fuentes, parámetros y salidas.'), ('Documento y anexos', 'docs/informe_energetico/', 'Contiene este informe, sus figuras, tablas y archivos de revisión.')]
    for (i, (label, path, note)) in enumerate(short):
        lines.append(('\\rowcolor{fondo_azul}' if i % 2 else '') + tex(label) + ' & \\Ruta{' + path + '}' + '\\par ' + tex(note) + '\\\\')
    lines.extend(['\\bottomrule\\end{tabularx}}', '\\Fuente{Fuente: estructura del repositorio y correspondencia detallada del anexo de trazabilidad.}', '\\end{table}'])
    (destino / 'tablas/trazabilidad.tex').write_text('\n'.join(lines) + '\n')
    central = rd('resultado_central.csv')
    fta = rd('sensibilidad_fta.csv')
    allcases = rd('balance_vigente.csv')
    plt.rcParams.update({'font.family': 'Liberation Sans', 'font.size': 10})

    def save(fig, name):
        for ext in ['pdf', 'png']:
            formatear_ejes(fig)
            fig.savefig(destino / 'figuras' / f'{name}.{ext}', dpi=220, bbox_inches='tight')
        plt.close(fig)
    (ax, fig, frame, r, treatment, v) = _figura_lectura_1(central, fta, save)
    import geopandas as gpd
    cfg = json.loads((root / 'config/asignacion_demanda.json').read_text())
    colors = {c['corredor']: '#' + ''.join((f'{v:02x}' for v in c['rgb'])) for obj in cfg.values() if isinstance(obj, dict) for c in obj.get('colores', [])}
    routes = {r['aforo']: r for r in cfg['corredores']}
    (ax, col, fig, p) = _figura_lectura_2(colors, gpd, root, routes, save)
    for name in ['sensibilidad_pendiente']:
        (fig, ax) = plt.subplots(figsize=(6.3, 3.8))
        cases = ['Referencia del Excel', 'Tara P25', 'Tara P75', 'Transmisión 0,95']
        labs = ['Referencia central', 'Menor masa (cuartil inferior)', 'Mayor masa (cuartil superior)', 'Transmisión del 95 %']
        selected = allcases[allcases.politica.eq('Accesos e interior según reservas') & allcases.referencia_id.eq('referencia_guagua_2')]
        for (j, (case, label)) in enumerate(zip(cases, labs)):
            for (treatment, color, shift, mark) in [('Hot COPERT', '#397568', -0.13, 'o'), ('Hot con contraste operativo externo', '#FA7921', 0.13, 's')]:
                v = selected.loc[selected.caso_pendiente.eq(case) & selected.tratamiento_operativo.eq(treatment), 'saldo_construccion_condicionada_tep_anio'].sort_values()
                assert len(v) == 2
                ax.plot(v, [j + shift] * 2, color=color, lw=2)
                ax.scatter(v, [j + shift] * 2, c=color, s=30, marker=mark, label=('Hot' if treatment == 'Hot COPERT' else 'FTA') if j == 0 else None)
        ax.axvline(60, color='#24343D', ls='--')
        ax.set(xlim=(0, 100), ylim=(3.6, -0.6), yticks=range(4), yticklabels=labs, xlabel='Ahorro anual (tep/año)')
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(axis='x', alpha=0.15)
        ax.legend(frameon=False, loc='lower left', ncol=2)
        fig.tight_layout()
        save(fig, name)
    (col,) = _figura_lectura_3(colors, routes, save)
    definiciones = _definiciones()
    rows = []
    for p in sorted((destino / 'anexos').glob('*.csv')):
        if p.stem == 'diccionario_anexos':
            continue
        frame = pd.read_csv(p, sep=';', keep_default_na=False)
        for col in frame:
            assert col in definiciones, (p.name, col)
            (unit, meaning) = definiciones[col]
            rows.append({'archivo': p.name, 'campo': col, 'unidad_o_lectura': unit, 'aclaracion': meaning})
    pd.DataFrame(rows).to_csv(destino / 'anexos/diccionario_anexos.csv', sep=';', index=False, encoding='utf-8-sig')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    meta = json.loads((destino / 'metadatos.json').read_text())
    meta.update(decision='D222', version_informe='0.3', estado='Borrador revisado para lectura y evaluación externa')
    meta['inputs_sha256'][str(Path(__file__).resolve())] = sha(Path(__file__))
    meta['inputs_sha256'][str((Path(__file__).parents[1] / 'informe_campos.txt').resolve())] = sha((Path(__file__).parents[1] / 'informe_campos.txt'))
    meta['derivados_sha256'] = {str(p.relative_to(destino)): sha(p) for folder in ['anexos', 'tablas', 'figuras'] for p in (destino / folder).iterdir() if p.is_file()}
    meta['revision_lectura'] = {'modelo_modificado': False, 'siglas_y_unidades_explicadas': True, 'fuentes_en_lenguaje_natural': True, 'conexion_con_repositorio': 'anexo de trazabilidad de método y diccionario completo de campos', 'orientacion_y_escala_mapa': True, 'datos_originales_conservados': True}
    (destino / 'metadatos.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    return resumen

def _figura_lectura_1(central, fta, save):
    (fig, ax) = plt.subplots(figsize=(6.3, 3.4))
    values = []
    labels = []
    for (treatment, frame) in [('Hot', central), ('FTA', fta)]:
        for r in frame.itertuples():
            values.append(r.saldo_construccion_condicionada_tep_anio)
            labels.append(treatment + ' · ' + ('A' if r.alternativa_procedencia.endswith('alquiler') else 'B'))
    bars = ax.barh(range(4), values, color=['#397568'] * 2 + ['#FA7921'] * 2, height=0.58, edgecolor='#24343D', linewidth=0.5)
    for (i, (bar, v)) in enumerate(zip(bars, values)):
        if i % 2:
            bar.set_hatch('///')
        ax.text(v + 1.5, i, numero(v), va='center', fontsize=10)
    ax.axvline(60, color='#24343D', ls='--', lw=1.2)
    ax.text(61, 3.65, 'Objetivo: 60 tep/año', fontsize=9)
    ax.set(xlim=(0, 95), ylim=(3.9, -0.6), yticks=range(4), yticklabels=labels, xlabel='Ahorro anual (tep/año)')
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='x', alpha=0.15)
    fig.tight_layout()
    save(fig, 'hot_y_fta')
    return (ax, fig, frame, r, treatment, v)

def _figura_lectura_2(colors, gpd, root, routes, save):
    (fig, ax) = plt.subplots(figsize=(6.3, 4.8))
    for (group, key, label) in [('chio_boca_tauce', 'CHIO', 'Chío'), ('aguamansa_el_portillo', 'OROTAVA', 'Aguamansa'), ('la_esperanza_el_portillo', 'LAGUNA', 'La Esperanza'), ('vilaflor_boca_tauce', 'VILAFLOR', 'Vilaflor'), ('interior_boca_tauce_el_portillo', None, 'Interior')]:
        p = next((root / 'data/silver/geografia/perfiles_altimetricos' / group).glob('perfil*ida*.parquet'))
        g = gpd.read_parquet(p).to_crs(4326)
        x = g.geometry.x.to_numpy()
        y = g.geometry.y.to_numpy()
        col = colors[routes[key]['corredor']] if key else '#397568'
        ax.plot(x, y, color=col, lw=1.8)
        if key:
            pos = int(np.argmax(g.distance_from_reference_m.to_numpy())) if 'distance_from_reference_m' in g else 0
            ax.scatter(x[pos], y[pos], marker='*', c=col, s=100, zorder=4)
            off = (-76, 7) if key == 'LAGUNA' else (5, 7)
            ax.annotate(label, (x[pos], y[pos]), xytext=off, textcoords='offset points', fontsize=10)
        else:
            for (pos, lab, off) in [(0, 'Boca Tauce', (-59, -15)), (-1, 'El Portillo', (4, -15))]:
                ax.scatter(x[pos], y[pos], marker='s', c='#0C4767', s=32)
                ax.annotate(lab, (x[pos], y[pos]), xytext=off, textcoords='offset points', fontsize=10)
    ax.annotate('Norte', xy=(-16.79, 28.415), xytext=(-16.79, 28.375), ha='center', arrowprops={'arrowstyle': '->', 'color': '#24343D', 'lw': 1.1}, fontsize=9)
    (lon0, lat) = (-16.8, 28.177)
    (lon1, lat1, _) = Geod(ellps='WGS84').fwd(lon0, lat, 90, 5000)
    ax.plot([lon0, lon1], [lat, lat], color='#24343D', lw=2)
    ax.text((lon0 + lon1) / 2, lat + 0.006, '5 kilómetros', ha='center', fontsize=9)
    handles = [Line2D([0], [0], marker='*', color='none', markerfacecolor='#24343D', markersize=10, label='Cabecera de estudio'), Line2D([0], [0], marker='s', color='none', markerfacecolor='#24343D', markersize=6, label='Terminal interior')]
    ax.legend(handles=handles, loc='lower right', frameon=False, fontsize=8.5)
    ax.set_aspect(1 / np.cos(np.deg2rad(28.3)))
    ax.set(xlabel='Longitud (grados)', ylabel='Latitud (grados)', title='Accesos y eje interior en el entorno del Teide')
    ax.grid(alpha=0.15)
    ax.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    save(fig, 'localizacion_servicios')
    return (ax, col, fig, p)

def _figura_lectura_3(colors, routes, save):
    (fig, ax) = plt.subplots(figsize=(6.3, 1.85))
    ax.axis('off')
    ax.set(xlim=(-1, 11), ylim=(-0.15, 3.0))
    for (key, x, y, label) in [('OROTAVA', 0, 2.5, 'Aguamansa'), ('LAGUNA', 10, 2.5, 'La Esperanza'), ('CHIO', 0, 0.45, 'Chío'), ('VILAFLOR', 10, 0.45, 'Vilaflor')]:
        col = colors[routes[key]['corredor']]
        ax.annotate('', xy=(5, y), xytext=(x, y), arrowprops={'arrowstyle': '<->', 'color': col, 'lw': 2})
        ax.scatter(x, y, marker='*', s=100, c=col, zorder=3)
        ax.text(x, y + 0.24, label, ha='center', fontsize=10)
    for (y, label) in [(2.5, 'El Portillo'), (0.45, 'Boca Tauce')]:
        ax.scatter(5, y, marker='s', s=55, c='#0C4767', zorder=4)
        ax.text(5.28, y - 0.2, label, fontsize=10)
    ax.annotate('', xy=(5, 2.25), xytext=(5, 0.7), arrowprops={'arrowstyle': '<->', 'color': '#397568', 'lw': 2.5})
    ax.text(5.28, 1.5, 'Servicio interior', fontsize=10, va='center')
    fig.tight_layout()
    save(fig, 'esquema_servicios')
    return (col,)
