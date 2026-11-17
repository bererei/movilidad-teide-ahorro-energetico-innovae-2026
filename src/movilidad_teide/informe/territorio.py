"""Revisión narrativa y territorial del informe; conservo el modelo y sus resultados."""
from movilidad_teide.informe.formato import formatear_ejes
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch
from pyproj import Geod
from movilidad_teide.informe.formato import numero, tex
(AZUL, JADE, NARANJA, TEXTO) = ('#0C4767', '#397568', '#FA7921', '#24343D')
RUTAS = [('chio_boca_tauce', 'CHIO', 'Chío → Boca Tauce'), ('aguamansa_el_portillo', 'OROTAVA', 'Aguamansa → El Portillo'), ('la_esperanza_el_portillo', 'LAGUNA', 'La Esperanza → El Portillo'), ('vilaflor_boca_tauce', 'VILAFLOR', 'Vilaflor → Boca Tauce'), ('interior_boca_tauce_el_portillo', None, 'Boca Tauce → El Portillo')]

def actualizar_narrativa(root, destino, resumen):
    (root, destino) = (Path(root), Path(destino))
    usadas = set()

    def leer(p):
        p = root / p
        usadas.add(p)
        if p.suffix == '.parquet':
            return gpd.read_parquet(p)
        if p.suffix in {'.gpkg', '.shp', '.geojson'}:
            return gpd.read_file(p)
        return pd.read_csv(p, sep=';', float_precision='round_trip')

    def exportar(nombre, frame):
        frame.to_csv(destino / 'anexos' / f'{nombre}.csv', sep=';', index=False, encoding='utf-8-sig', float_format='%.17g')

    def figura(fig, nombre):
        for ext in ['pdf', 'png']:
            formatear_ejes(fig)
            fig.savefig(destino / 'figuras' / f'{nombre}.{ext}', dpi=220, bbox_inches='tight')
        plt.close(fig)

    def tabla(nombre, titulo, encabezados, filas, fuente, columnas):
        lines = ['\\begin{table}[!htbp]', '\\caption{' + titulo + '}', '\\centering{\\fontsize{10}{13}\\selectfont', '\\begin{tabularx}{\\linewidth}{@{}' + columnas + '@{}}', '\\rowcolor{azul} ' + ' & '.join(('\\Blanco{' + tex(x) + '}' for x in encabezados)) + '\\\\']
        for (i, row) in enumerate(filas):
            lines.append(('\\rowcolor{fondo_azul} ' if i % 2 else '') + ' & '.join((tex(x) for x in row)) + '\\\\')
        lines += ['\\bottomrule\\end{tabularx}}', '\\Fuente{Fuente: ' + tex(fuente) + '}', '\\end{table}']
        (destino / 'tablas' / f'{nombre}.tex').write_text('\n'.join(lines) + '\n')
    plt.rcParams.update({'font.family': 'Liberation Sans', 'font.size': 10, 'axes.labelcolor': TEXTO, 'text.color': TEXTO})
    cfg = json.loads((root / 'config/asignacion_demanda.json').read_text())
    usadas.add(root / 'config/asignacion_demanda.json')
    corredores = {c['aforo']: c for c in cfg['corredores']}
    colores = {c['corredor']: '#' + ''.join((f'{v:02x}' for v in c['rgb'])) for c in cfg['mapa']['colores']}

    def color(key):
        return colores[corredores[key]['corredor']] if key else JADE
    capturas = 'data/bronze/documentacion/contexto_informe/'
    islas = leer(capturas + 'islas.geojson').to_crs(4326)
    tenerife = islas[islas.etiqueta.eq('Tenerife')]
    assert len(tenerife) == 1
    parque = leer(capturas + 'cartografia_parque/PN_Teide/Limites/Limite_Teide.shp').to_crs(4326)
    lineas = {}
    cabeceras = {}
    terminales = {}
    for (grupo, key, label) in RUTAS:
        p = next((root / 'data/silver/geografia/perfiles_altimetricos' / grupo).glob('perfil*ida*.parquet'))
        g = leer(p.relative_to(root)).to_crs(4326)
        lineas[grupo] = g
        if key:
            pos = int(np.argmax(g.distance_from_reference_m.to_numpy()))
            cabeceras[key] = (float(g.geometry.x.iloc[pos]), float(g.geometry.y.iloc[pos]))
        else:
            for (pos, lab) in [(0, 'Boca Tauce'), (-1, 'El Portillo')]:
                terminales[lab] = (float(g.geometry.x.iloc[pos]), float(g.geometry.y.iloc[pos]))

    def base(ax):
        tenerife.plot(ax=ax, color='#F1F2EC', edgecolor='#859194', linewidth=0.7)
        parque.plot(ax=ax, color='#D8E9DC', edgecolor=JADE, linewidth=0.7)
        ax.set(xlim=(-16.96, -16.08), ylim=(27.98, 28.62), xlabel='Longitud (grados)', ylabel='Latitud (grados)')
        ax.set_aspect(1 / np.cos(np.deg2rad(28.3)))
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(alpha=0.12)

    def ejes(ax, etiquetas=True):
        for (grupo, key, label) in RUTAS:
            g = lineas[grupo]
            ax.plot(g.geometry.x, g.geometry.y, color=color(key), lw=1.6, zorder=3)
        for (key, (x, y)) in cabeceras.items():
            ax.scatter(x, y, marker='*', s=125, c=color(key), edgecolor='white', linewidth=0.55, zorder=5)
            if etiquetas:
                lab = {'CHIO': 'Chío', 'OROTAVA': 'Aguamansa', 'LAGUNA': 'La Esperanza', 'VILAFLOR': 'Vilaflor'}[key]
                off = {'CHIO': (-30, -15), 'OROTAVA': (-50, 10), 'LAGUNA': (7, 7), 'VILAFLOR': (7, -12)}[key]
                ax.annotate(lab, (x, y), xytext=off, textcoords='offset points', fontsize=10, fontweight='bold', bbox={'facecolor': 'white', 'alpha': 0.85, 'edgecolor': 'none', 'pad': 1})
        for (label, (x, y)) in terminales.items():
            ax.scatter(x, y, marker='s', s=38, c=AZUL, edgecolor='white', linewidth=0.5, zorder=6)
            if etiquetas:
                ax.annotate(label, (x, y), xytext=(7, 8) if label == 'El Portillo' else (-25, -18), textcoords='offset points', fontsize=9, bbox={'facecolor': 'white', 'alpha': 0.85, 'edgecolor': 'none', 'pad': 1})

    def norte_escala(ax):
        ax.annotate('Norte', xy=(-16.91, 28.57), xytext=(-16.91, 28.49), ha='center', fontsize=9, arrowprops={'arrowstyle': '->', 'color': TEXTO, 'lw': 1.1})
        (lon0, lat) = (-16.91, 28.035)
        (lon1, lat1, _) = Geod(ellps='WGS84').fwd(lon0, lat, 90, 10000)
        ax.plot([lon0, lon1], [lat, lat], color=TEXTO, lw=2)
        ax.text((lon0 + lon1) / 2, lat + 0.012, '10 kilómetros', ha='center', fontsize=9)
    (ax,) = _figura_territorio_1(base, ejes, figura, islas, norte_escala, tenerife)
    rutas = leer('data/silver/demanda/asignacion/recorridos_referencia_calculo.csv')
    detalle = leer('data/silver/energia/referencias_unitarias/pendiente_turismos/correccion_por_origen_y_rama.csv')
    d = detalle[detalle.caso_pendiente.eq('Referencia del Excel') & detalle.alternativa_procedencia.eq('España no Tenerife: alquiler') & detalle.rama.eq('antes') & detalle.sentido.eq('hacia_teide')]
    rank = d.groupby('origen_id').recorridos_coche_anio.sum().sort_values(ascending=False)
    r = rutas[rutas.sentido.eq('hacia_teide')].set_index('origen_id').join(rank.rename('entradas_modelizadas_anio')).sort_values('entradas_modelizadas_anio', ascending=False)
    assert len(r) == 41 and abs(r.entradas_modelizadas_anio.sum() - 377697.412861) < 1e-05
    sel = list(r.head(6).index)
    for hub in ['Vilaflor', 'La Esperanza']:
        k = r[r.cabecera_calculo.eq(hub)].index[0]
        if k not in sel:
            sel.append(k)
    icfg = json.loads((root / 'config/itinerarios.json').read_text())
    usadas.add(root / 'config/itinerarios.json')
    comparaciones = {}
    for collection in ['origin_access_comparisons', 'coastal_valley_comparisons', 'study_origin_access_comparisons']:
        for (k, v) in icfg.get(collection, {}).items():
            comparaciones.setdefault(k, v)
    tabla_origenes = leer('data/silver/demanda/asignacion/origenes_representativos.csv').set_index('origen_id')
    filas = []
    dibujo = []
    for (n, (oid, rr)) in enumerate(r.iterrows(), 1):
        cc = comparaciones.get(rr.comparacion_calculo_id, {})
        label = cc.get('origin_label', tabla_origenes.loc[oid, 'municipio_referencia'])
        if rr.comparacion_calculo_id == 'columbus_vilaflor':
            label = 'Referencia costera de Arona'
        if rr.comparacion_calculo_id == 'duque_chio':
            label = 'Referencia costera de Adeje'
        selected = oid in sel
        codigo = sel.index(oid) + 1 if selected else 0
        filas.append({'origen_id': oid, 'comparacion_calculo_id': rr.comparacion_calculo_id, 'nombre_origen_informe': label, 'cabecera_calculo': rr.cabecera_calculo, 'entradas_modelizadas_anio': rr.entradas_modelizadas_anio, 'cuota_entradas_modelizadas_pct': 100 * rr.entradas_modelizadas_anio / rank.sum(), 'alimentador_ida_km': rr.alimentador_km, 'itinerario_referencia_id': rr.itinerario_referencia_id, 'vias_itinerario': cc.get('road_chain', 'Aproximación territorial; véase catálogo de recorridos'), 'ejemplo_cartografico': selected, 'numero_en_mapa': codigo})
        if selected:
            p = root / 'data/silver/geografia/accesos_origenes' / rr.comparacion_calculo_id / 'accesos_origenes.gpkg'
            usadas.add(p)
            g = gpd.read_file(p, layer='componentes').to_crs(4326)
            g = g[g.componente.eq('origen_cabecera') & g.itinerary_id.eq(rr.itinerario_referencia_id)]
            assert len(g) == 1, (rr.comparacion_calculo_id, rr.itinerario_referencia_id)
            dibujo.append((codigo, label, rr, g))
    origenes = pd.DataFrame(filas)
    exportar('origenes_itinerarios', origenes)
    present = origenes[origenes.ejemplo_cartografico].sort_values('numero_en_mapa')
    tabla('origenes', 'Ejemplos de alimentación desde los orígenes hasta las cabeceras', ['N.º y referencia geográfica', 'Cabecera', 'Ida (km)', 'Entradas (%)'], [[f'{x.numero_en_mapa}. {x.nombre_origen_informe}', x.cabecera_calculo, numero(x.alimentador_ida_km, 1), numero(x.cuota_entradas_modelizadas_pct, 1)] for x in present.itertuples()], 'asignación anual y recorridos conservados. Porcentajes sobre las entradas modelizadas de coches sin intervención; no son aforos de esos lugares. Distancias de ida por carretera. La selección reúne los seis primeros y el principal de cada corredor todavía no incluido.', 'XXrr')
    tabla('vias_origenes', 'Referencias viarias de los accesos completos de los ejemplos', ['N.º', 'Origen representativo', 'Cadena viaria de referencia'], [[str(x.numero_en_mapa), x.nombre_origen_informe, x.vias_itinerario] for x in present.itertuples()], 'catálogo de itinerarios y trazados de carretera conservados. La cadena puede incluir la continuación desde la cabecera al Parque y las aproximaciones conservadas; no identifica la ruta elegida por cada visitante.', 'L{8mm}L{62mm}X')
    (ax, g, label, xy) = _figura_territorio_2(base, cabeceras, color, dibujo, ejes, figura, norte_escala)
    intervalos = [(-np.inf, -6, '< −6 %'), (-6, -3, '−6 a < −3 %'), (-3, 0, '−3 a < 0 %'), (0, 3, '0 a < 3 %'), (3, 6, '3 a 6 %'), (6, np.inf, '> 6 %')]
    pendientes = []
    perfiles = []
    for (grupo, key, label) in RUTAS:
        parts = []
        for p in sorted((root / 'data/silver/geografia/perfiles_altimetricos' / grupo).glob('tramos_*.parquet')):
            g = leer(p.relative_to(root))
            assert np.isfinite(g[['length_m', 'slope_pct']]).all().all()
            sentido = 'ida' if '_ida_' in p.name else 'regreso'
            parts.append(g)
            for z in g.itertuples():
                perfiles.append({'recorrido_informe': label, 'sentido_perfil': sentido, 'distancia_inicio_km': z.distance_start_m / 1000, 'longitud_tramo_km': z.length_m / 1000, 'cota_inicio_m': z.elevation_start_m, 'cota_fin_m': z.elevation_end_m, 'pendiente_tramo_pct': z.slope_pct, 'fuera_rango_factor': abs(z.slope_pct) > 6})
        g = pd.concat(parts, ignore_index=True)
        assert len(parts) == 2, (grupo, len(parts))
        total = g.length_m.sum()
        checks = []
        for (j, (lo, hi, lab)) in enumerate(intervalos):
            mask = (g.slope_pct >= lo) & (g.slope_pct < hi)
            if j == 4:
                mask = (g.slope_pct >= lo) & (g.slope_pct <= hi)
            if j == 5:
                mask = g.slope_pct > lo
            km = float(g.loc[mask, 'length_m'].sum() / 1000)
            checks.append(km)
            pendientes.append({'recorrido_informe': label, 'intervalo_pendiente': lab, 'longitud_intervalo_km': km, 'porcentaje_longitud': 100 * km / (total / 1000), 'longitud_ida_regreso_km': total / 1000, 'longitud_fuera_rango_km': float(g.loc[g.slope_pct.abs() > 6, 'length_m'].sum() / 1000)})
        assert abs(sum(checks) - total / 1000) < 1e-10
    slopes = pd.DataFrame(pendientes)
    exportar('pendientes_recorridos', slopes)
    exportar('perfiles_recorridos', pd.DataFrame(perfiles))
    (ax,) = _figura_territorio_3(figura, intervalos, slopes)
    filas = []
    for (_, _, label) in RUTAS:
        t = slopes[slopes.recorrido_informe.eq(label)].iloc[0]
        filas.append([label, numero(t.longitud_ida_regreso_km, 1), numero(100 * t.longitud_fuera_rango_km / t.longitud_ida_regreso_km, 1)])
    tabla('pendientes', 'Alcance geométrico de la pendiente en los cinco ejes', ['Recorrido: ida y regreso', 'Longitud (km)', 'Fuera de ±6 % (% de longitud)'], filas, 'segmentos altimétricos ya utilizados. Las fracciones describen distancia física, no consumo anual ni error del factor. La rasante estimada conserva sus limitaciones.', 'XL{25mm}L{44mm}')
    cen = pd.read_csv(destino / 'anexos/resultado_central.csv', sep=';')
    fta = pd.read_csv(destino / 'anexos/sensibilidad_fta.csv', sep=';')
    hot = float(cen.guaguas_mwh_anio.iloc[0])
    extra = float(fta.guaguas_mwh_anio.iloc[0])
    delta = extra - hot
    assert abs(delta / 11.63 - (cen.saldo_construccion_condicionada_tep_anio - fta.saldo_construccion_condicionada_tep_anio).iloc[0]) < 1e-09
    (a, ax) = _figura_territorio_4(cen, extra, figura, fta, hot)

    def caja(ax, xy, w, h, t, color=AZUL, fs=10):
        ax.add_patch(FancyBboxPatch(xy, w, h, boxstyle='round,pad=0.012,rounding_size=.018', facecolor='#EFF5F8' if color == AZUL else '#EEF5F2', edgecolor=color, lw=1))
        ax.text(xy[0] + w / 2, xy[1] + h / 2, t, ha='center', va='center', fontsize=fs, linespacing=1.3)

    def flecha(ax, a, b):
        ax.annotate('', xy=b, xytext=a, arrowprops={'arrowstyle': '->', 'color': TEXTO, 'lw': 1.15, 'shrinkA': 2, 'shrinkB': 2})
    _figura_territorio_5(caja, figura, flecha)
    _figura_territorio_6(caja, figura, flecha)
    for p in (destino / 'tablas').glob('*.tex'):
        if p.name == 'cifras.tex':
            continue
        s = p.read_text().replace('guaguas', 'lanzaderas').replace('guagua', 'lanzadera').replace('Guaguas', 'Lanzaderas')
        if p.name == 'inventario.tex':
            s = s.replace('Total físico & 30', '\\midrule\\textbf{Total físico} & \\textbf{30}')
        if p.name == 'parametros.tex':
            s = s.replace('Excel del modelo, caso Central', 'libro de escenarios, caso Central')
        p.write_text(s)
    p = destino / 'figuras/sensibilidad_pendiente.pdf'
    cases = pd.read_csv(destino / 'anexos/balance_vigente.csv', sep=';')
    selected = cases[cases.politica.eq('Accesos e interior según reservas') & cases.referencia_id.eq('referencia_guagua_2')]
    (col,) = _figura_territorio_7(figura, selected)
    from movilidad_teide.informe.diccionario import _definiciones
    definitions = _definiciones()
    rows = []
    for p in sorted((destino / 'anexos').glob('*.csv')):
        if p.stem == 'diccionario_anexos':
            continue
        for col in pd.read_csv(p, sep=';', nrows=0).columns:
            assert col in definitions, (p.name, col)
            (unit, meaning) = definitions[col]
            rows.append({'archivo': p.name, 'campo': col, 'unidad_o_lectura': unit, 'aclaracion': meaning})
    exportar('diccionario_anexos', pd.DataFrame(rows))
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    meta = json.loads((destino / 'metadatos.json').read_text())
    meta.update(decision='D223', version_informe='0.4', estado='Borrador revisado con comentarios de lectura')
    usadas.update((p for p in (root / capturas).rglob('*') if p.is_file()))
    meta['inputs_sha256'].update({str(p.resolve()): sha(p) for p in usadas | {Path(__file__), root / 'docs/informe_energetico/INFORME_ENERGETICO_v0.3_2026-11-01 - BGD.pdf'}})
    meta['derivados_sha256'] = {str(p.relative_to(destino)): sha(p) for folder in ['anexos', 'tablas', 'figuras'] for p in (destino / folder).iterdir() if p.is_file()}
    meta['revision_narrativa'] = {'modelo_modificado': False, 'voz': 'primera persona singular', 'termino_publico': 'lanzadera (autobús)', 'comentarios_pdf': 38, 'cartografia_contextual': 'ISTAC y MITECO; no cambia recorridos de energía', 'origenes_mostrados': len(present), 'criterio_origenes': 'Seis primeras entradas de coche modelizadas y principal de los dos corredores restantes', 'pendientes': 'Longitud de perfiles conservados, ambos sentidos; no ponderación anual', 'release': 'Estructura de entrega prevista, sin publicación ni resultados provisionales en Gold'}
    (destino / 'metadatos.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    return {**resumen, 'version': '0.4', 'anexos_csv': len(list((destino / 'anexos').glob('*.csv'))), 'comentarios_pdf': 38}

def _figura_territorio_1(base, ejes, figura, islas, norte_escala, tenerife):
    (fig, ax) = plt.subplots(figsize=(6.3, 4.85))
    base(ax)
    ejes(ax)
    norte_escala(ax)
    ax.text(-16.61, 28.275, 'Parque Nacional\ndel Teide', ha='center', fontsize=10, color=JADE, fontweight='bold')
    ax.text(-16.39, 28.13, 'TENERIFE', fontsize=12, color='#65757B', rotation=25)
    ax.legend(handles=[Patch(facecolor='#D8E9DC', edgecolor=JADE, label='Límite cartográfico del Parque'), Line2D([0], [0], marker='*', color='none', markerfacecolor=TEXTO, markersize=10, label='Cabecera propuesta: acceso exterior'), Line2D([0], [0], marker='s', color='none', markerfacecolor=AZUL, markersize=6, label='Terminal del servicio interior')], loc='upper right', fontsize=8.3, framealpha=0.94)
    iax = ax.inset_axes([0.53, 0.02, 0.45, 0.2])
    islas.plot(ax=iax, color='#E0E4E3', edgecolor='#8C9696', linewidth=0.4)
    tenerife.plot(ax=iax, color=AZUL, edgecolor=AZUL, linewidth=0.4)
    iax.set(xlim=(-18.25, -13.35), ylim=(27.5, 29.5))
    iax.set_aspect(1 / np.cos(np.deg2rad(28.5)))
    iax.axis('off')
    iax.text(-15.7, 27.62, 'Islas Canarias', ha='center', fontsize=8)
    fig.tight_layout()
    figura(fig, 'localizacion_servicios')
    return (ax,)

def _figura_territorio_2(base, cabeceras, color, dibujo, ejes, figura, norte_escala):
    (fig, ax) = plt.subplots(figsize=(6.3, 5.25))
    base(ax)
    ejes(ax, etiquetas=False)
    norte_escala(ax)
    for (n, label, rr, g) in dibujo:
        key = next((k for (k, v) in {'CHIO': 'Chío', 'OROTAVA': 'Aguamansa', 'LAGUNA': 'La Esperanza', 'VILAFLOR': 'Vilaflor'}.items() if v == rr.cabecera_calculo))
        g.plot(ax=ax, color=color(key), linewidth=1.1, alpha=0.9, zorder=2)
        coords = list(g.geometry.iloc[0].coords)
        hub = np.array(cabeceras[key])
        ends = [np.array(coords[0]), np.array(coords[-1])]
        xy = max(ends, key=lambda x: np.linalg.norm(x - hub))
        ax.scatter(xy[0], xy[1], s=48, marker='o', c='white', edgecolor=color(key), linewidth=1.3, zorder=6)
        offset = {1: (-10, 9), 2: (-18, 2), 3: (5, 8), 4: (-12, -15), 5: (-18, 5), 6: (-22, -10), 7: (-4, -18), 8: (6, 4)}[n]
        ax.annotate(str(n), xy, xytext=offset, textcoords='offset points', fontsize=10, fontweight='bold', color=color(key), bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': 0.85, 'pad': 0.6})
    ax.legend(handles=[Line2D([0], [0], marker='o', color='none', markerfacecolor='white', markeredgecolor=TEXTO, label='Origen representativo numerado'), Line2D([0], [0], marker='*', color='none', markerfacecolor=TEXTO, markersize=9, label='Cabecera propuesta'), Line2D([0], [0], marker='s', color='none', markerfacecolor=AZUL, markersize=5, label='Terminal interior'), Patch(facecolor='#D8E9DC', edgecolor=JADE, label='Parque Nacional del Teide')], loc='upper right', fontsize=8.3, framealpha=0.94)
    ax.text(-16.34, 28.09, 'Líneas: recorridos de cálculo\nNúmeros: tabla de orígenes', fontsize=9, ha='center')
    fig.tight_layout()
    figura(fig, 'origenes_cabeceras')
    return (ax, g, label, xy)

def _figura_territorio_3(figura, intervalos, slopes):
    (fig, ax) = plt.subplots(figsize=(6.3, 3.9))
    palette = ['#346B96', '#6E9FC0', '#B6CFDE', '#D3E4BF', '#9DBE6B', '#5A883A']
    ys = np.arange(5)
    left = np.zeros(5)
    labels = [label.replace(' → ', '\n→ ') for (_, _, label) in RUTAS]
    for (j, (_, _, lab)) in enumerate(intervalos):
        v = np.array([slopes[(slopes.recorrido_informe == label) & (slopes.intervalo_pendiente == lab)].porcentaje_longitud.iloc[0] for (_, _, label) in RUTAS])
        ax.barh(ys, v, left=left, color=palette[j], height=0.58, label=lab, edgecolor='white', linewidth=0.35)
        left += v
    ax.set(yticks=ys, yticklabels=labels, xlim=(0, 100), ylim=(4.65, -0.65), xlabel='Porcentaje de la longitud del recorrido, ida y regreso')
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(loc='upper center', bbox_to_anchor=(0.38, 1.23), ncol=3, fontsize=8, frameon=False)
    ax.grid(axis='x', alpha=0.12)
    fig.tight_layout()
    figura(fig, 'distribucion_pendientes')
    return (ax,)

def _figura_territorio_4(cen, extra, figura, fta, hot):
    (fig, (ax, bx)) = plt.subplots(1, 2, figsize=(6.3, 3.8), gridspec_kw={'width_ratios': [0.88, 1.12]})
    ax.bar([0, 1], [hot, extra], color=[JADE, NARANJA], width=0.6)
    ax.set(xticks=[0, 1], xticklabels=['Hot', 'Hot + FTA'], ylim=(0, 6300), ylabel='Consumo de nuevas lanzaderas (MWh/año)')
    ax.set_title('Más consumo', fontsize=11, fontweight='bold')
    for (j, v) in enumerate([hot, extra]):
        ax.text(j, v + 100, numero(v, 0), ha='center', fontsize=9)
    ax.text(0.5, 6000, '+11,11 %', ha='center', fontsize=10, color=NARANJA, fontweight='bold')
    for (i, (tratamiento, frame)) in enumerate([('Hot', cen), ('Hot + FTA', fta)]):
        vals = frame.saldo_construccion_condicionada_tep_anio.to_numpy()
        ys = np.arange(2) + (-0.18 if i == 0 else 0.18)
        bx.barh(ys, vals, height=0.32, color=[JADE, NARANJA][i], label=tratamiento)
        for (y, v) in zip(ys, vals):
            bx.text(v + 1, y, numero(v), va='center', fontsize=9)
    bx.set(yticks=[0, 1], yticklabels=['Asignación A', 'Asignación B'], xlim=(0, 90), ylim=(1.65, -0.65), xlabel='Ahorro del proyecto (tep/año)')
    bx.axvline(60, color=TEXTO, ls='--', lw=1)
    bx.set_title('Menos ahorro', fontsize=11, fontweight='bold')
    bx.legend(loc='lower right', fontsize=8, frameon=False)
    for a in [ax, bx]:
        a.spines[['top', 'right']].set_visible(False)
        a.grid(axis='y' if a is ax else 'x', alpha=0.12)
    fig.subplots_adjust(wspace=0.6, bottom=0.24, top=0.84)
    fig.text(0.02, 0.02, 'Hot: motor caliente de COPERT. FTA: sensibilidad externa de consumo adicional.\nA y B: dos asignaciones de coches de España no Tenerife; todos los colectivos están incluidos.', fontsize=9)
    figura(fig, 'hot_y_fta')
    return (a, ax)

def _figura_territorio_5(caja, figura, flecha):
    (fig, ax) = plt.subplots(figsize=(6.3, 3.7))
    ax.axis('off')
    ax.set(xlim=(0, 1), ylim=(0, 1))
    caja(ax, (0.12, 0.79), 0.76, 0.17, 'Año 2028 · Misma demanda de partida\nIncluyo también las observaciones de mayor afluencia')
    caja(ax, (0.02, 0.22), 0.44, 0.44, 'SIN INTERVENCIÓN\n\nCoches hasta el Parque\nVisita interior y regreso\nServicios colectivos existentes', AZUL)
    caja(ax, (0.54, 0.22), 0.44, 0.44, 'CON INTERVENCIÓN\n\nHasta 500 coches diarios\nCoche hasta cabecera + lanzadera\nInterior, regreso y vacíos\nServicios existentes conservados', JADE)
    flecha(ax, (0.32, 0.78), (0.24, 0.67))
    flecha(ax, (0.68, 0.78), (0.76, 0.67))
    ax.text(0.5, 0.08, 'Comparación de energía final de las cadenas completas de ambos escenarios', ha='center', fontsize=10, fontweight='bold')
    figura(fig, 'escenarios_pareados')
    return ()

def _figura_territorio_6(caja, figura, flecha):
    (fig, ax) = plt.subplots(figsize=(6.3, 6.45))
    ax.axis('off')
    ax.set(xlim=(0, 1), ylim=(0, 1))
    caja(ax, (0.08, 0.875), 0.84, 0.1, '1  FUENTES Y DEMANDA\nVisor Teide · matrices origen–destino · aforos · parque de vehículos', fs=9)
    caja(ax, (0.08, 0.735), 0.84, 0.09, '2  DEMANDA COMÚN PROYECTADA A 2028\nPesos anuales · ocupación · orígenes y cabeceras')
    flecha(ax, (0.5, 0.87), (0.5, 0.83))
    flecha(ax, (0.29, 0.73), (0.24, 0.69))
    flecha(ax, (0.71, 0.73), (0.76, 0.69))
    caja(ax, (0.015, 0.515), 0.45, 0.17, '3a  SIN INTERVENCIÓN\nCoches: acceso + interior + regreso\nServicios colectivos existentes\nRecorridos × distancias')
    caja(ax, (0.535, 0.515), 0.45, 0.17, '3b  CON INTERVENCIÓN\nCupo + alimentación + lanzaderas\nReserva completa y capacidad\nExpediciones comerciales y vacías', JADE)
    flecha(ax, (0.24, 0.51), (0.3, 0.46))
    flecha(ax, (0.76, 0.51), (0.7, 0.46))
    caja(ax, (0.08, 0.345), 0.84, 0.11, '4  CONSUMO POR RECORRIDO Y VEHÍCULO\nFactores COPERT Hot · pendiente de pesados en la biblioteca\nAjuste físico propio de pendiente de turismos convencionales')
    flecha(ax, (0.3, 0.34), (0.24, 0.29))
    flecha(ax, (0.7, 0.34), (0.76, 0.29))
    caja(ax, (0.06, 0.205), 0.39, 0.08, 'Energía anual SIN\nSuma de los componentes', AZUL)
    caja(ax, (0.55, 0.205), 0.39, 0.08, 'Energía anual CON\nSuma de los componentes', JADE)
    flecha(ax, (0.25, 0.2), (0.38, 0.16))
    flecha(ax, (0.75, 0.2), (0.62, 0.16))
    caja(ax, (0.12, 0.08), 0.76, 0.075, '5  AHORRO = ENERGÍA SIN − ENERGÍA CON\nConversión de unidades y comprobación del balance', JADE)
    ax.text(0.5, 0.015, '6  Sensibilidad → condiciones de operación → recomendaciones y seguimiento', ha='center', fontsize=9, fontweight='bold')
    flecha(ax, (0.5, 0.077), (0.5, 0.035))
    figura(fig, 'proceso_calculo')
    return ()

def _figura_territorio_7(figura, selected):
    (fig, ax) = plt.subplots(figsize=(6.3, 3.8))
    for (j, (case, lab)) in enumerate(zip(['Referencia del Excel', 'Tara P25', 'Tara P75', 'Transmisión 0,95'], ['Referencia central', 'Menor masa: cuartil inferior', 'Mayor masa: cuartil superior', 'Transmisión del 95 %'])):
        for (tratamiento, col, shift, marker, label) in [('Hot COPERT', JADE, -0.13, 'o', 'Hot: motor caliente'), ('Hot con contraste operativo externo', NARANJA, 0.13, 's', 'Hot + FTA: consumo adicional')]:
            v = selected.loc[selected.caso_pendiente.eq(case) & selected.tratamiento_operativo.eq(tratamiento), 'saldo_construccion_condicionada_tep_anio'].sort_values()
            assert len(v) == 2
            ax.plot(v, [j + shift] * 2, color=col, lw=2)
            ax.scatter(v, [j + shift] * 2, c=col, s=30, marker=marker, label=label if j == 0 else None)
    ax.axvline(60, color=TEXTO, ls='--')
    ax.set(xlim=(0, 100), ylim=(3.65, -0.65), yticks=range(4), yticklabels=['Referencia central', 'Menor masa: cuartil inferior', 'Mayor masa: cuartil superior', 'Transmisión del 95 %'], xlabel='Ahorro anual (tep/año)')
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='x', alpha=0.15)
    ax.legend(frameon=False, loc='upper center', bbox_to_anchor=(0.36, 1.2), ncol=1, fontsize=9)
    fig.tight_layout()
    figura(fig, 'sensibilidad_pendiente')
    return (col,)
