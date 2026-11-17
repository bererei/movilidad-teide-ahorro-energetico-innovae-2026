"""Explico escenarios y balance desde sus resultados conservados, sin cambiar hipótesis."""
from movilidad_teide.informe.formato import formatear_ejes
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, FancyBboxPatch
from pyproj import Geod
from movilidad_teide.informe.formato import numero, tex
from movilidad_teide.energia.valoracion_operacion import valorar_movimientos
(AZUL, JADE, NARANJA, TEXTO) = ('#0C4767', '#397568', '#FA7921', '#24343D')
POLITICA = 'Accesos e interior según reservas'

def ampliar_escenarios(root, destino, resumen):
    (root, destino) = (Path(root), Path(destino))
    usadas = set()

    def leer(rel):
        p = root / rel
        usadas.add(p)
        if p.suffix == '.parquet':
            return pd.read_parquet(p)
        return pd.read_csv(p, sep=';', float_precision='round_trip')

    def exportar(name, frame):
        frame.to_csv(destino / 'anexos' / f'{name}.csv', sep=';', index=False, encoding='utf-8-sig', float_format='%.17g')

    def guardar(fig, name):
        for ext in ['pdf', 'png']:
            formatear_ejes(fig)
            fig.savefig(destino / 'figuras' / f'{name}.{ext}', dpi=220, bbox_inches='tight')
        plt.close(fig)

    def tabla(name, title, heads, rows, note, cols):
        lines = ['\\begin{table}[!htbp]', '\\caption{' + title + '}', '\\centering{\\fontsize{10}{13}\\selectfont', '\\begin{tabularx}{\\linewidth}{@{}' + cols + '@{}}', '\\rowcolor{azul} ' + ' & '.join(('\\Blanco{' + tex(x) + '}' for x in heads)) + '\\\\']
        for (i, row) in enumerate(rows):
            lines.append(('\\rowcolor{fondo_azul} ' if i % 2 else '') + ' & '.join((tex(x) for x in row)) + '\\\\')
        lines += ['\\bottomrule\\end{tabularx}}', '\\Fuente{Fuente: ' + tex(note) + '}', '\\end{table}']
        (destino / 'tablas' / f'{name}.tex').write_text('\n'.join(lines) + '\n')
    plt.rcParams.update({'font.family': 'Liberation Sans', 'font.size': 10})
    base = 'data/silver/energia_turismos/'
    central = leer(base + '20261101_hot_central_fta_sensibilidad/resultado_central.csv')
    fta = leer(base + '20261101_hot_central_fta_sensibilidad/sensibilidad_fta.csv')
    detalle = leer(base + '20261101_pendiente_anual_pareada/correccion_por_origen_y_rama.csv')
    detalle = detalle[detalle.caso_pendiente.eq('Referencia del Excel')].copy()
    detalle['energia_mwh_anio'] = detalle.energia_base_mwh_anio + detalle.correccion_convencional_mwh_anio
    meta = json.loads((destino / 'metadatos.json').read_text())
    valores = {p['id']: p['valor_utilizado'] for p in meta['parametros']['parametros']}
    mov = leer(base + '20261101_flota_30_tres_sustitutas/movimientos_con_identidad_fisica.parquet')
    mov = mov[mov.politica.eq(POLITICA) & ~mov.es_diseno_p85]
    factores = leer('data/silver/copert/20261029_energia_anual_lanzaderas/consumo_por_recorrido_y_referencia.csv')
    energias = []
    for (obs, moves) in mov.groupby('observacion'):
        weights = moves.dias_equivalentes.unique()
        assert len(weights) == 1
        e = valorar_movimientos(moves, factores, carga_comercial=valores['carga_copert'], perdida_rendimiento=valores['perdida_rendimiento_guaguas_contraste'])
        e = e[e.referencia_id.eq('referencia_guagua_2')].copy()
        e['servicio'] = np.where(e.punto.eq('INTERIOR'), 'Interior', 'Acceso')
        e['tipo_viaje'] = np.where(e.componente.str.startswith('comercial'), 'Comercial', 'Vacío')
        e['hot_mwh_anio'] = e.hot_mwh * weights[0]
        e['vehiculos_km_anio'] = e.km_recorrido * weights[0]
        energias.append(e)
    buses = pd.concat(energias).groupby(['servicio', 'tipo_viaje'], as_index=False)[['hot_mwh_anio', 'vehiculos_km_anio']].sum()
    assert abs(buses.hot_mwh_anio.sum() - central.guaguas_mwh_anio.iloc[0]) < 1e-09
    assert abs(buses.vehiculos_km_anio.sum() - 1372353.9529079741) < 1e-07
    exportar('energia_lanzaderas_servicio', buses)
    tabla('energia_servicios', 'Actividad y consumo de las nuevas lanzaderas en 2028', ['Servicio', 'Tipo', 'Vehículos-km/año', 'Hot (MWh/año)'], [[x.servicio, x.tipo_viaje, numero(x.vehiculos_km_anio, 0), numero(x.hot_mwh_anio)] for x in buses.itertuples()], 'mismos movimientos, pesos anuales y factores del balance central; se incluyen comerciales y vacíos. Son cantidades de toda la flota, no de cada unidad.', 'XXrr')
    servicios = {'Particular sin especificar (B00)': 'Turismos de uso particular', 'Alquiler sin conductor (A01)': 'Turismos de alquiler'}
    componentes = []
    puentes = []
    comunes = leer(base + '20261030_balance_con_comunes/guaguas_comunes_detalle.csv')
    energia_comun = float(comunes.energia_comun_mwh_anio.sum())
    for alt in central.alternativa_procedencia:
        t = detalle[detalle.alternativa_procedencia.eq(alt)]
        for (escenario, mask) in [('Sin intervención', t.rama.eq('antes')), ('Con intervención', ~t.rama.eq('antes'))]:
            for (group, label) in servicios.items():
                value = float(t.loc[mask & t.grupo_servicio.eq(group), 'energia_mwh_anio'].sum())
                componentes.append([alt, escenario, label, value, 'Turismos: energía base más corrección de pendiente convencional, por rama y grupo de servicio.'])
            for service in ['Acceso', 'Interior']:
                value = 0.0 if escenario == 'Sin intervención' else float(buses.loc[buses.servicio.eq(service), 'hot_mwh_anio'].sum())
                componentes.append([alt, escenario, 'Lanzaderas de ' + service.lower(), value, 'Nuevas lanzaderas del proyecto: comerciales y vacíos; ausentes sin intervención.'])
            componentes.append([alt, escenario, 'TITSA y excursiones: bloque común', energia_comun, 'Estimación agregada de vehículos equivalentes; no reparto medido por empresa o línea. El consumo sin/con es el mismo por hipótesis.'])
        before = float(t.loc[t.rama.eq('antes'), 'energia_mwh_anio'].sum())
        after = float(t.loc[~t.rama.eq('antes'), 'energia_mwh_anio'].sum())
        row = central[central.alternativa_procedencia.eq(alt)].iloc[0]
        ahorro = before - after - row.guaguas_mwh_anio
        assert abs(before + energia_comun - row.sin_componentes_mwh_anio) < 1e-08
        assert abs(after + energia_comun + row.guaguas_mwh_anio - row.con_construccion_condicionada_mwh_anio) < 1e-08
        assert abs(ahorro - row.saldo_construccion_condicionada_mwh_anio) < 1e-08
        er = fta[fta.alternativa_procedencia.eq(alt)].iloc[0]
        puentes.append([alt, before, after, before - after, energia_comun, row.guaguas_mwh_anio, ahorro, ahorro / 11.63, 100 * (row.saldo_construccion_condicionada_mwh_anio - er.saldo_construccion_condicionada_mwh_anio) / ahorro])
    comp = pd.DataFrame(componentes, columns=['alternativa_procedencia', 'escenario_balance', 'componente_balance', 'energia_mwh_anio', 'criterio_componente'])
    puente = pd.DataFrame(puentes, columns=['alternativa_procedencia', 'turismos_sin_mwh_anio', 'turismos_con_mwh_anio', 'reduccion_turismos_mwh_anio', 'comun_por_escenario_mwh_anio', 'nuevas_lanzaderas_mwh_anio', 'ahorro_mwh_anio', 'ahorro_tep_anio', 'reduccion_relativa_ahorro_fta_pct'])
    exportar('energia_por_componente', comp)
    exportar('puente_ahorro', puente)
    rows = []
    for label in comp.componente_balance.unique():
        vals = [numero(comp.loc[comp.alternativa_procedencia.eq(alt) & comp.escenario_balance.eq(s) & comp.componente_balance.eq(label), 'energia_mwh_anio'].item()) for alt in central.alternativa_procedencia for s in ['Sin intervención', 'Con intervención']]
        rows.append([label, *vals])
    rows.append(['Total representado', *[numero(v) for x in central.itertuples() for v in [x.sin_componentes_mwh_anio, x.con_construccion_condicionada_mwh_anio]]])
    tabla('componentes_detalle', 'Consumo anual de los dos escenarios por componente (MWh/año)', ['Componente', 'Sin · alquiler', 'Con · alquiler', 'Sin · particular', 'Con · particular'], rows, 'sumas del balance conservado. Las cabeceras alquiler/particular identifican la asignación del grupo de visitantes del resto de España; las filas distinguen tipos de vehículos. TITSA y excursiones se estiman conjuntamente, sin imputar un reparto entre ellas.', 'Xrrrr')
    p = destino / 'tablas/componentes_detalle.tex'
    s = p.read_text()
    s = s.replace(tex('Total representado') + ' &', '\\midrule\\textbf{Total representado} &')
    s = s.replace('\\rowcolor{fondo_azul} \\midrule', '\\midrule\\rowcolor{fondo_azul} ')
    p.write_text(s)
    tabla('puente_ahorro', 'Cómo se forma el ahorro central (MWh/año, salvo última fila)', ['Operación', 'Grupo en alquiler', 'Grupo en particular'], [[label, *[numero(v) for v in puente[col]]] for (label, col) in [('Menor consumo conjunto de turismos', 'reduccion_turismos_mwh_anio'), ('Consumo de nuevas lanzaderas que resto', 'nuevas_lanzaderas_mwh_anio'), ('Ahorro de energía final', 'ahorro_mwh_anio'), ('Ahorro convertido a tep/año', 'ahorro_tep_anio')]], 'resto los consumos de las cadenas completas. La contribución neta de TITSA/excursiones es cero por continuidad asumida, aunque su consumo es 3.026,89 MWh/año en cada escenario.', 'Xrr')
    tabla('totales_fta', 'Consumo total y ahorro con y sin el contraste FTA', ['Asignación y tratamiento', 'Sin (MWh/año)', 'Con (MWh/año)', 'Ahorro (tep/año)'], [[alt.split(': ')[1].capitalize() + ' · ' + label, numero(x.sin_componentes_mwh_anio), numero(x.con_construccion_condicionada_mwh_anio), numero(x.saldo_construccion_condicionada_tep_anio)] for alt in central.alternativa_procedencia for (label, frame) in [('Hot', central), ('Hot + FTA', fta)] for x in frame[frame.alternativa_procedencia.eq(alt)].itertuples()], 'balance de todo el ámbito representado, incluidos turismos, nuevas lanzaderas y servicios comunes; solo modifico el consumo de las nuevas lanzaderas en la sensibilidad.', 'Xrrr')
    labels = list(comp.componente_balance.unique())
    colors = [AZUL, '#A4C5D9', NARANJA, JADE, '#AAB2B6']
    hatches = ['', '///', '', '', '...']
    (ax, col, fig, j, v, vals) = _figura_escenarios_1(central, colors, guardar, hatches, labels, comp)
    x = puente.iloc[0]
    vals = [x.reduccion_turismos_mwh_anio, 0.0, -x.nuevas_lanzaderas_mwh_anio, x.ahorro_mwh_anio]
    starts = [0, x.reduccion_turismos_mwh_anio, x.ahorro_mwh_anio, 0]
    (ax, col, fig, v, y) = _figura_escenarios_2(guardar, starts, vals)
    (ax, fig, x) = _figura_escenarios_3(guardar)
    rr = leer('data/silver/demanda/asignacion/recorridos_referencia_calculo.csv')
    oris = leer('data/silver/demanda/asignacion/origenes_representativos.csv').set_index('origen_id')
    capturas = root / 'data/bronze/documentacion/contexto_informe'
    islas = gpd.read_file(capturas / 'islas.geojson').to_crs(4326)
    isla = islas[islas.etiqueta.eq('Tenerife')]
    parque = gpd.read_file(capturas / 'cartografia_parque/PN_Teide/Limites/Limite_Teide.shp').to_crs(4326)
    cfg = json.loads((root / 'config/asignacion_demanda.json').read_text())
    icfg = json.loads((root / 'config/itinerarios.json').read_text())
    usadas.update([root / 'config/asignacion_demanda.json', root / 'config/itinerarios.json'])
    colorscorr = {c['corredor']: '#' + ''.join((f'{v:02x}' for v in c['rgb'])) for c in cfg['mapa']['colores']}
    cor = {c['aforo']: c['corredor'] for c in cfg['corredores']}
    ejes = {}
    heads = {}
    ends = {}
    grupos = [('chio_boca_tauce', 'CHIO', 'Chío'), ('aguamansa_el_portillo', 'OROTAVA', 'Aguamansa'), ('la_esperanza_el_portillo', 'LAGUNA', 'La Esperanza'), ('vilaflor_boca_tauce', 'VILAFLOR', 'Vilaflor'), ('interior_boca_tauce_el_portillo', None, 'Interior')]
    for (group, key, label) in grupos:
        p = next((root / 'data/silver/geografia/perfiles_altimetricos' / group).glob('perfil*ida*.parquet'))
        usadas.add(p)
        g = gpd.read_parquet(p).to_crs(4326)
        ejes[group] = g
        if key:
            j = int(np.argmax(g.distance_from_reference_m))
            heads[key] = (g.geometry.x.iloc[j], g.geometry.y.iloc[j], label)
        else:
            for (j, name) in [(0, 'Boca Tauce'), (-1, 'El Portillo')]:
                ends[name] = (g.geometry.x.iloc[j], g.geometry.y.iloc[j])

    def base(ax, local=False):
        if not local:
            isla.plot(ax=ax, color='#F3F3EF', edgecolor='#859194', linewidth=0.6)
        parque.plot(ax=ax, color='#E5EFE5', edgecolor=JADE, linewidth=0.7)
        ax.set_aspect(1 / np.cos(np.deg2rad(28.3)))
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(alpha=0.12)
        ax.set(xlabel='Longitud (grados)', ylabel='Latitud (grados)')

    def escala(ax, lon, lat, metros):
        (lon1, _, _) = Geod(ellps='WGS84').fwd(lon, lat, 90, metros)
        ax.plot([lon, lon1], [lat, lat], color=TEXTO, lw=2)
        ax.text((lon + lon1) / 2, lat + 0.004 if metros < 5000 else lat + 0.012, str(metros // 1000) + ' kilómetros', ha='center', fontsize=9)
    geometries = {}
    red = []
    for x in rr.itertuples():
        paths = []
        if pd.notna(x.comparacion_calculo_id):
            key = (x.comparacion_calculo_id, x.itinerario_referencia_id)
            if key not in geometries:
                if x.coleccion_catalogo == 'coastal_valley_comparisons':
                    p = root / 'data/silver/geografia/accesos_origenes/contraste_costero_valle/contraste_costero_valle.gpkg'
                    usadas.add(p)
                    g = gpd.read_file(p, layer='componentes')
                    g = g[g.caso.eq(x.comparacion_calculo_id)]
                    direct = g[g.alternativa.eq('directa_tf523') & g.itinerary_id.eq(x.itinerario_referencia_id)]
                    feed = g[g.alternativa.eq('alimentador_costero') & g.itinerary_id.eq(x.itinerario_alimentador_id)]
                    assert len(direct) == len(feed) == 1
                    assert abs(direct.longitud_km.iloc[0] - x.directa_km) < 1e-08 and abs(feed.longitud_km.iloc[0] - x.alimentador_km) < 1e-08
                    pair = {'directos': direct.to_crs(4326), 'alimentadores': feed.to_crs(4326)}
                else:
                    p = root / 'data/silver/geografia/accesos_origenes' / x.comparacion_calculo_id / 'accesos_origenes.gpkg'
                    usadas.add(p)
                    direct = gpd.read_file(p, layer='recorridos_directos')
                    direct = direct[direct.itinerary_id.eq(x.itinerario_referencia_id)]
                    feed = gpd.read_file(p, layer='componentes')
                    feed = feed[feed.itinerary_id.eq(x.itinerario_referencia_id) & feed.componente.eq('origen_cabecera')]
                    assert len(direct) == len(feed) == 1, (x.comparacion_calculo_id, x.itinerario_referencia_id)
                    assert abs(direct.length_m.iloc[0] / 1000 - x.directa_km) < 1e-08 and abs(feed.longitud_km.iloc[0] - x.alimentador_km) < 1e-08
                    pair = {'directos': direct.to_crs(4326), 'alimentadores': feed.to_crs(4326)}
                geometries[key] = pair
            paths = [str(Path('data/silver/geografia/accesos_origenes/contraste_costero_valle/contraste_costero_valle.gpkg'))] if x.coleccion_catalogo == 'coastal_valley_comparisons' else [str(Path('data/silver/geografia/accesos_origenes') / x.comparacion_calculo_id / 'accesos_origenes.gpkg')]
        red.append({'origen_id': x.origen_id, 'sentido': x.sentido, 'comparacion_calculo_id': x.comparacion_calculo_id, 'tipo_representacion_calculo': x.tipo_representacion_calculo, 'perfil_propio': x.perfil_propio, 'aproximacion_territorial': x.aproximacion_territorial, 'itinerario_referencia_id': x.itinerario_referencia_id, 'directa_km': x.directa_km, 'alimentador_km': x.alimentador_km, 'archivo_geometria': '; '.join(paths), 'capas_geometria': 'Recorrido directo y componente origen-cabecera del catálogo, o componentes directa_tf523/alimentador_costero del contraste del valle' if paths else 'Sin recorrido aplicado por media nula; revisar si aparece demanda positiva'})
    exportar('red_recorridos', pd.DataFrame(red))
    for mode in ['directos', 'alimentadores']:
        (fig, ax) = plt.subplots(figsize=(6.3, 5.15))
        base(ax)
        for (key, pair) in geometries.items():
            pair[mode].plot(ax=ax, color=AZUL if mode == 'directos' else NARANJA, linewidth=0.9, alpha=0.65, zorder=2)
        for (group, key, label) in grupos:
            g = ejes[group]
            col = colorscorr[cor[key]] if key else JADE
            ax.plot(g.geometry.x, g.geometry.y, color=col, lw=1.4, zorder=3)
        seen = rr[rr.sentido.eq('hacia_teide')]
        for x in seen.itertuples():
            o = oris.loc[x.origen_id]
            col = colorscorr.get(x.corredor_calculo, TEXTO)
            ax.scatter(o.longitud, o.latitud, s=24, marker='o', facecolor=col if x.perfil_propio else 'white', edgecolor=col, linewidth=0.8, zorder=4)
        for (key, (x, y, label)) in heads.items():
            ax.scatter(x, y, marker='*', s=90, color=colorscorr[cor[key]], edgecolor='white', linewidth=0.5, zorder=5)
        for (label, (x, y)) in ends.items():
            ax.scatter(x, y, marker='s', s=32, color=AZUL, zorder=5)
        ax.set(xlim=(-16.96, -16.08), ylim=(27.98, 28.62))
        ax.annotate('Norte', xy=(-16.91, 28.57), xytext=(-16.91, 28.49), ha='center', fontsize=9, arrowprops={'arrowstyle': '->', 'color': TEXTO})
        escala(ax, -16.91, 28.035, 10000)
        handles = [Line2D([0], [0], color=AZUL if mode == 'directos' else NARANJA, label='Recorridos directos a terminal' if mode == 'directos' else 'Alimentación hasta cabecera'), Line2D([0], [0], marker='o', color='none', markerfacecolor=TEXTO, markeredgecolor=TEXTO, label='Origen con perfil propio'), Line2D([0], [0], marker='o', color='none', markerfacecolor='white', markeredgecolor=TEXTO, label='Origen sin perfil propio'), Line2D([0], [0], marker='*', color='none', markerfacecolor=TEXTO, markersize=9, label='Cabecera propuesta'), Line2D([0], [0], marker='s', color='none', markerfacecolor=AZUL, label='Terminal interior')]
        fig.legend(handles=handles, loc='lower center', ncol=2, fontsize=9, frameon=False)
        fig.tight_layout(rect=[0, 0.18, 1, 1])
        guardar(fig, 'red_' + mode)
    folder = Path('data/silver/geografia/perfiles_altimetricos/interior_boca_tauce_el_portillo')
    pois = leer(folder / 'cobertura_puntos_interes.csv')
    atencion = leer(folder / 'propuesta_atencion_turistica.csv').set_index('target_id')
    points = pois[['target_id', 'lugar', 'longitud', 'latitud']].copy()
    points['atencion_en_estudio'] = points.target_id.map(atencion.atencion_propuesta)
    points['limite_interpretacion'] = points.target_id.map(atencion.comprobacion_pendiente)
    parador = icfg['anchors']['parador_edificio_referencia']['coordinates']
    points.loc[len(points)] = ['parador_edificio', 'Parador de Las Cañadas del Teide', *parador, 'Localización del edificio; no parada interior', 'La lanzadera permanece en la carretera principal; el acceso a pie debe definirse.']
    exportar('puntos_servicio_interior', points)
    fig = plt.figure(figsize=(6.3, 5.8))
    ax = fig.add_axes([0.09, 0.23, 0.53, 0.72])
    lista = fig.add_axes([0.66, 0.15, 0.34, 0.8])
    lista.axis('off')
    base(ax, local=True)
    g = ejes['interior_boca_tauce_el_portillo']
    ax.plot(g.geometry.x, g.geometry.y, color=JADE, lw=2.1, zorder=3)
    for (name, (xx, yy)) in ends.items():
        ax.scatter(xx, yy, marker='s', s=65, color=AZUL, edgecolor='white', linewidth=0.5, zorder=5)
    order = [('centro_portillo', 'Centro de Visitantes\nEl Portillo / referencia\nde acceso a Arenas Negras', (-18, 10)), ('minas_san_jose', 'Minas de San José', (7, 4)), ('tabonal_negro', 'Tabonal Negro', (9, 2)), ('teleferico', 'Estación base del\nTeleférico', (-16, -7)), ('pico_viejo', 'Mirador de Pico Viejo\nAlta montaña: acceso aparte', (-16, 5)), ('parador_edificio', 'Parador', (8, 0)), ('roques_garcia', 'Roques de García /\nLa Ruleta', (-15, -11)), ('llano_ucanca', 'Llano de Ucanca', (3, -17)), ('zapatilla_reina', 'Zapatilla de la Reina', (-15, -8)), ('boca_tauce', 'Boca Tauce: terminal\ny mirador', (-12, 10))]
    cursor = 1.0
    for (j, (key, label, offset)) in enumerate(order, 1):
        z = points[points.target_id.eq(key)].iloc[0]
        ax.scatter(z.longitud, z.latitud, s=20, c=TEXTO, zorder=6)
        ax.annotate(str(j), (z.longitud, z.latitud), xytext=offset, textcoords='offset points', fontsize=10, fontweight='bold', bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': 0.95, 'pad': 0.6}, arrowprops={'arrowstyle': '-', 'color': '#6D7B7E', 'lw': 0.5})
        lista.text(0, cursor, str(j) + '  ' + label, fontsize=9.5, va='top', linespacing=1.12)
        cursor -= 0.031 * (label.count('\n') + 1) + 0.027
    for (letter, anchor, offset) in [('A', 'entrada_parador_tf21', (8, 14)), ('B', 'entrada_teleferico_tf21', (10, -14))]:
        (xx, yy) = icfg['anchors'][anchor]['coordinates']
        ax.scatter(xx, yy, s=35, facecolors='white', edgecolors=NARANJA, linewidth=1.4, zorder=7)
        ax.annotate(letter, (xx, yy), xytext=offset, textcoords='offset points', fontsize=10, fontweight='bold', color=AZUL, bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': 0.9, 'pad': 0.5}, arrowprops={'arrowstyle': '-', 'color': NARANJA, 'lw': 0.6})
    lista.text(0, 0.105, 'A  Entrada Parador /\n    Cañada Blanca\nB  Entrada del Teleférico', fontsize=9.2, va='top', color=AZUL, linespacing=1.2)
    ax.set(xlim=(-16.715, -16.535), ylim=(28.185, 28.332))
    ax.tick_params(labelsize=8)
    ax.annotate('Norte', xy=(-16.705, 28.32), xytext=(-16.705, 28.3), ha='center', fontsize=9, arrowprops={'arrowstyle': '->', 'color': TEXTO})
    escala(ax, -16.705, 28.194, 3000)
    fig.legend(handles=[Line2D([0], [0], color=JADE, lw=2, label='Carretera principal: eje interior'), Line2D([0], [0], marker='s', color='none', markerfacecolor=AZUL, label='Terminales de estudio'), Line2D([0], [0], marker='o', color='none', markerfacecolor=TEXTO, label='Lugares de referencia'), Line2D([0], [0], marker='o', color='none', markerfacecolor='white', markeredgecolor=NARANJA, label='Entradas de acceso de estudio')], loc='lower center', ncol=2, fontsize=9, frameon=False)
    guardar(fig, 'servicio_interior_turistico')
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
    meta.update(decision='D225', version_informe='0.6', estado='Borrador revisado: índice detallado, maquetación y unidades explicadas')
    usadas.update((root / rel for rel in ['data/bronze/transporte_publico/pasajeros_titsa/2025/20261022T171917Z_f6db4cae/metadatos.json', 'data/bronze/documentacion/diseno_interior/20261024/metadata.json', 'data/bronze/documentacion/diseno_interior/20261024_confirmacion_luis/aportacion.json', 'data/bronze/documentacion/diseno_interior/20261025_carretera_principal/aportacion.json']))
    meta['inputs_sha256'].update({str(p.resolve()): sha(p) for p in usadas | {Path(__file__), root / 'docs/informe_energetico/INFORME_ENERGETICO_v0.4_2026-11-01 - BGD.pdf'}})
    fuente_unidades = root / 'data/bronze/documentacion/conversion_unidades/20261101'
    meta['inputs_sha256'].update({str(p.resolve()): sha(p) for p in fuente_unidades.iterdir() if p.is_file()})
    meta['revision_maquetacion'] = {'indice': 'Capítulos y subsecciones en dos páginas; segunda parte desde resultados, con anexos incluidos.', 'horizonte': '2028 es el año previsto de puesta en funcionamiento del sistema; comparo ambos escenarios para ese año.', 'unidades': 'Referencia principal IDAE, guía 13/06/2023, apéndice 2, página 42; y MITECO, Resolución 23/12/2024, cuarto a-c. 1 MWh ≈ 0,086 tep; conservo 1 tep = 11,63 MWh en cálculo, sin redondeo intermedio. Eurostat queda como contraste documental consultado, sin cita principal en el informe.', 'maestro': 'Conservo main.tex como único editable; la maquetación no altera las entradas del modelo.'}
    for nombre in ['origenes', 'vias_origenes', 'pendientes']:
        tabla = destino / 'tablas' / f'{nombre}.tex'
        tabla.write_text(tabla.read_text().replace('\\begin{table}[!htbp]', '\\begin{table}[H]', 1))
    meta['derivados_sha256'] = {str(p.relative_to(destino)): sha(p) for folder in ['anexos', 'tablas', 'figuras'] for p in (destino / folder).iterdir() if p.is_file()}
    meta['revision_escenarios'] = {'modelo_modificado': False, 'comentarios_nuevos': 12, 'TITSA': 'Matrices publicadas incorporadas como evidencia de pasajeros; el balance conserva una estimación conjunta TITSA/excursiones, sin separación inventada.', 'desglose': 'Turismos particulares y alquiler; lanzaderas de acceso e interiores; colectivo existente agregado.', 'rutas': '82 asignaciones de sentido: 80 enlazadas a 31 referencias geométricas, dos filas de un caso de media nula sin recorrido aplicado; no añado conectores para territorios aproximados.', 'puntos_interior': 'Diez objetivos y el edificio del Parador; la lanzadera permanece en carretera principal.', 'guia': 'Ocho fichas enlazan el relato con cuadernos, código y datos.'}
    (destino / 'metadatos.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    return {**resumen, 'version': '0.6', 'anexos_csv': len(list((destino / 'anexos').glob('*.csv'))), 'comentarios_pdf': 12, 'consumo_acceso_mwh_anio': float(buses.loc[buses.servicio.eq('Acceso'), 'hot_mwh_anio'].sum()), 'consumo_interior_mwh_anio': float(buses.loc[buses.servicio.eq('Interior'), 'hot_mwh_anio'].sum())}

def _figura_escenarios_1(central, colors, guardar, hatches, labels, comp):
    (fig, axes) = plt.subplots(1, 2, figsize=(6.3, 4.5), sharey=True)
    for (ax, alt) in zip(axes, central.alternativa_procedencia):
        bottom = np.zeros(2)
        for (lab, col, hatch) in zip(labels, colors, hatches):
            vals = np.array([comp.loc[comp.alternativa_procedencia.eq(alt) & comp.escenario_balance.eq(s) & comp.componente_balance.eq(lab), 'energia_mwh_anio'].item() for s in ['Sin intervención', 'Con intervención']])
            ax.bar([0, 1], vals / 11.63, bottom=bottom / 11.63, color=col, hatch=hatch, width=0.58, edgecolor='white', linewidth=0.4)
            bottom += vals
        for (j, v) in enumerate(bottom):
            ax.text(j, (v + 350) / 11.63, numero(v / 11.63), ha='center', fontsize=10)
        ax.set(xticks=[0, 1], xticklabels=['Sin', 'Con'], ylim=(0, 28500 / 11.63), title=('Asignación A' if alt.endswith('alquiler') else 'Asignación B') + '\nEspaña no Tenerife: ' + alt.split(': ')[1])
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(axis='y', alpha=0.13)
    axes[0].set_ylabel('Consumo del sistema representado (tep/año)')
    legendnames = ['Turismos particulares', 'Turismos de alquiler', 'Lanzaderas de acceso', 'Lanzaderas interiores', 'TITSA y excursiones, conjunto']
    fig.legend(handles=[Patch(facecolor=c, hatch=h, edgecolor='white', label=l) for (c, h, l) in zip(colors, hatches, legendnames)], loc='lower center', ncol=2, fontsize=9.5, frameon=False)
    sec = axes[-1].secondary_yaxis('right', functions=(lambda tep: tep * 11.63, lambda mwh: mwh / 11.63))
    sec.set_ylabel('Equivalencia (MWh/año)')
    from matplotlib.ticker import FuncFormatter
    sec.yaxis.set_major_formatter(FuncFormatter(lambda v, pos: numero(v, 0)))
    fig.subplots_adjust(bottom=0.27, wspace=0.15, top=0.83, right=0.86)
    guardar(fig, 'balance_sistema_completo')
    return (ax, col, fig, j, v, vals)

def _figura_escenarios_2(guardar, starts, vals):
    (fig, ax) = plt.subplots(figsize=(6.3, 3.6))
    for (i, (v, start, col)) in enumerate(zip(vals, starts, [AZUL, '#AAB2B6', NARANJA, JADE])):
        if v == 0:
            ax.plot([i - 0.3, i + 0.3], [start / 11.63, start / 11.63], color=col, lw=3)
        else:
            ax.bar(i, abs(v) / 11.63, bottom=start / 11.63, color=col, width=0.6)
        y = (start + abs(v) if v >= 0 else start + abs(v)) + 120
        ax.text(i, y / 11.63, ('+' if i == 0 else '−' if i == 2 else '') + numero(abs(v) / 11.63), ha='center', fontsize=10, fontweight='bold')
    ax.set(xticks=range(4), xticklabels=['Menor consumo\nde turismos', 'Variación de TITSA\ny excursiones', 'Consumo de las\nnuevas lanzaderas', 'Ahorro neto\ndel sistema'], ylim=(0, 6500 / 11.63), ylabel='Variación de energía (tep/año)')
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='y', alpha=0.13)
    sec = ax.secondary_yaxis('right', functions=(lambda tep: tep * 11.63, lambda mwh: mwh / 11.63))
    sec.set_ylabel('Equivalencia (MWh/año)')
    from matplotlib.ticker import FuncFormatter
    sec.yaxis.set_major_formatter(FuncFormatter(lambda v, pos: numero(v, 0)))
    fig.tight_layout()
    guardar(fig, 'formacion_ahorro')
    return (ax, col, fig, v, y)

def _figura_escenarios_3(guardar):
    (fig, ax) = plt.subplots(figsize=(6.3, 4.5))
    ax.axis('off')
    ax.set(xlim=(0, 1), ylim=(0, 1))

    def caja(x, y, w, h, texto, col):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=.012', facecolor='#EFF5F8' if col == AZUL else '#EEF5F2', edgecolor=col, lw=1))
        ax.text(x + w / 2, y + h / 2, texto, ha='center', va='center', fontsize=10, linespacing=1.4)
    caja(0.1, 0.82, 0.8, 0.13, '2028 · Misma demanda y territorio de partida\nCambio la organización de los desplazamientos', AZUL)
    caja(0.015, 0.23, 0.45, 0.46, 'SIN INTERVENCIÓN\n\nTurismos particulares y de alquiler\nAcceso directo, visita y regreso\nSin nuevas lanzaderas\nTITSA y excursiones existentes', AZUL)
    caja(0.535, 0.23, 0.45, 0.46, 'CON INTERVENCIÓN\n\nCupo de 500 coches diarios\nAlimentación + lanzaderas de acceso\nVisita interior + regreso + vacíos\nTITSA y excursiones mantenidos', JADE)
    for x in [0.24, 0.76]:
        ax.annotate('', xy=(x, 0.71), xytext=(x, 0.81), arrowprops={'arrowstyle': '->', 'color': TEXTO, 'lw': 1.2})
    ax.text(0.5, 0.105, 'Servicios existentes: consumo conjunto igual por hipótesis\nLa demanda inducida se fija en cero en el caso central', ha='center', fontsize=10)
    guardar(fig, 'escenarios_pareados')
    return (ax, fig, x)
