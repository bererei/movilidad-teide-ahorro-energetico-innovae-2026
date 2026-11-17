"""Aclaración de escenarios y cobertura desde las salidas conservadas del modelo."""
from movilidad_teide.informe.formato import formatear_ejes
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from movilidad_teide.informe.formato import numero, tex
COLECTIVOS = {'tenerife_no_frecuente': 'Tenerife: no frecuentes', 'tenerife_resto': 'Tenerife: resto del colectivo', 'espana_no_tenerife': 'España no Tenerife', 'extranjero': 'Extranjeros'}

def aclarar_cobertura(root, destino, resumen):
    """Conciliar las visitas de cada colectivo y explicar el alcance energético.

    Las asignaciones de alquiler/particular no cambian la demanda. Exporto
    cantidades ya calculadas; no reconstruyo escenarios ni imputo consumos.
    """
    (root, destino) = (Path(root), Path(destino))
    usadas = []

    def leer(rel):
        p = root / rel
        usadas.append(p)
        return pd.read_csv(p, sep=';', float_precision='round_trip')

    def exportar(nombre, tabla):
        tabla.to_csv(destino / 'anexos' / f'{nombre}.csv', sep=';', index=False, encoding='utf-8-sig', float_format='%.17g')

    def tabla(nombre, titulo, cabeceras, filas, nota, columnas):
        lines = ['\\begin{table}[H]', '\\caption{' + titulo + '}', '\\centering{\\fontsize{10}{13}\\selectfont', '\\begin{tabularx}{\\linewidth}{@{}' + columnas + '@{}}', '\\rowcolor{azul} ' + ' & '.join(('\\Blanco{' + tex(c) + '}' for c in cabeceras)) + '\\\\']
        for (i, fila) in enumerate(filas):
            lines.append(('\\rowcolor{fondo_azul} ' if i % 2 else '') + ' & '.join((tex(v) for v in fila)) + '\\\\')
        lines += ['\\bottomrule\\end{tabularx}}', '\\Fuente{Fuente: ' + tex(nota) + '}', '\\end{table}']
        (destino / 'tablas' / f'{nombre}.tex').write_text('\n'.join(lines) + '\n')
    meta = json.loads((destino / 'metadatos.json').read_text())
    valores = {p['id']: p['valor_utilizado'] for p in meta['parametros']['parametros']}
    base = 'data/silver/energia_turismos/'
    fuente = leer('data/silver/actividad/corredor_norte/proyeccion_personas_2028.csv')
    detalle = leer(base + '20261101_pendiente_anual_pareada/correccion_por_origen_y_rama.csv')
    detalle = detalle[detalle.caso_pendiente.eq('Referencia del Excel')]
    comunes = leer(base + '20261030_balance_con_comunes/guaguas_comunes_detalle.csv')
    visitas = fuente[fuente.direccion.eq('subida')].groupby('colectivo').viajes_persona_proyectados.sum()
    comunes = comunes[comunes.sentido.eq('hacia_teide')].groupby('colectivo').personas_no_coche_sentido_anio.sum()
    if set(visitas.index) != set(COLECTIVOS) or set(comunes.index) != set(COLECTIVOS):
        raise ValueError('La cobertura debe conservar los cuatro colectivos de la fuente.')
    ocupacion = float(valores['ocupacion_coche'])
    coberturas = []
    for (alternativa, g) in detalle[detalle.sentido.eq('hacia_teide')].groupby('alternativa_procedencia'):
        ramas = g.groupby(['colectivo', 'rama']).recorridos_coche_anio.sum().unstack('rama')
        if set(ramas.index) != set(COLECTIVOS) or ramas.isna().any().any():
            raise ValueError('Falta una rama o colectivo en la actividad privada.')
        z = pd.DataFrame(index=list(COLECTIVOS))
        z['visitas_fuente_anio'] = visitas
        z['personas_coche_sin_anio'] = ramas.antes * ocupacion
        z['personas_colectivo_sin_anio'] = comunes
        z['personas_coche_autorizado_anio'] = ramas.autorizados * ocupacion
        z['personas_transferidas_coche_anio'] = ramas.transferidos * ocupacion
        z['personas_lanzadera_desde_otros_anio'] = ramas.alimentacion_otros
        z['personas_lanzadera_anio'] = z.personas_transferidas_coche_anio + z.personas_lanzadera_desde_otros_anio
        z['personas_colectivo_permanecen_anio'] = comunes - z.personas_lanzadera_desde_otros_anio
        z['personas_con_anio'] = z.personas_coche_autorizado_anio + z.personas_lanzadera_anio + z.personas_colectivo_permanecen_anio
        if z.lt(-1e-08).any().any() or not np.allclose(z.visitas_fuente_anio, z.personas_coche_sin_anio + z.personas_colectivo_sin_anio, rtol=0, atol=1e-07) or (not np.allclose(z.visitas_fuente_anio, z.personas_con_anio, rtol=0, atol=1e-07)):
            raise ValueError('No se conservan las visitas por colectivo entre fuente, sin y con intervención.')
        coberturas.append(z)
    if len(coberturas) != 2:
        raise ValueError('Conservar las dos asignaciones del grupo España no Tenerife.')
    pd.testing.assert_frame_equal(coberturas[0], coberturas[1], check_exact=True)
    z = coberturas[0].rename_axis('colectivo').reset_index()
    z.insert(1, 'colectivo_lectura', z.colectivo.map(COLECTIVOS))
    z['conservacion_visitas_comprobada'] = True
    exportar('cobertura_colectivos', z)
    filas = [[r.colectivo_lectura, numero(r.visitas_fuente_anio, 0), numero(r.personas_coche_sin_anio, 0), numero(r.personas_colectivo_sin_anio, 0)] for r in z.itertuples()]
    filas.append(['Total representado', *[numero(z[c].sum(), 0) for c in ['visitas_fuente_anio', 'personas_coche_sin_anio', 'personas_colectivo_sin_anio']]])
    tabla('cobertura_colectivos', 'Todos los colectivos de la demanda anual representada en 2028', ['Colectivo de la fuente', 'Visitas', 'Sin: coche', 'Sin: colectivo'], filas, 'proyección y asignación anual conservadas, conciliadas por colectivo. Visitas-persona equivalentes, con regreso emparejado; cada cantidad se redondea por separado, por lo que puede diferir en una unidad de la suma mostrada. La cobertura y las cantidades son idénticas en las dos asignaciones de alquiler/particular. No son personas únicas ni un nuevo censo del Parque.', 'Xrrr')
    filas = [['Turismos', 'Directo al Parque, visita interior y regreso', 'Autorizados al Parque y alimentación a cabeceras', 'Estimado; todos los colectivos'], ['TITSA y excursiones existentes', 'Consumo conjunto estimado', 'Mismo consumo que sin intervención, por hipótesis', 'Agregado; sin reparto por línea o empresa'], ['Nuevas lanzaderas de acceso', 'Ausentes', 'Viajes comerciales y vacíos', 'Calculado para la oferta de estudio'], ['Nuevo servicio interior', 'Ausente; permanece la movilidad interior existente', 'Viajes comerciales y vacíos', 'Calculado para las visitas asignadas'], ['Arranque en frío e instalaciones fijas', 'Excluidos del alcance elegido', 'Excluidos del alcance elegido', 'Exclusión; no consumo físico nulo'], ['Pendiente de otros turismos y operación no identificada', 'Efecto adicional sin estimar', 'Efecto adicional sin estimar', 'Límite material; no cero imputado']]
    cobertura = pd.DataFrame(filas, columns=['componente_cobertura', 'sin_intervencion', 'con_intervencion', 'estado_cobertura'])
    exportar('cobertura_componentes', cobertura)
    tabla('matriz_escenarios', 'Qué incluye cada escenario y cómo se representa', ['Componente', 'Sin intervención', 'Con intervención'], [r[:3] for r in filas[:4]], 'reglas y componentes del balance conservado. La ausencia sin intervención afecta a las nuevas lanzaderas; se conservan los desplazamientos interiores de coches y servicios existentes. TITSA y excursiones se estiman conjuntamente, sin combustible medido por línea.', 'L{34mm}XX')
    _figura_cobertura_1(destino)
    for p in (destino / 'tablas').glob('*.tex'):
        if p.stem in {'cobertura_colectivos', 'matriz_escenarios'}:
            continue
        s = p.read_text()
        for (old, new) in [('Sin · alquiler', 'Sin · A'), ('Con · alquiler', 'Con · A'), ('Sin · particular', 'Sin · B'), ('Con · particular', 'Con · B'), ('Grupo en alquiler', 'Asignación A'), ('Grupo en particular', 'Asignación B'), ('Alquiler · Hot', 'A · Hot'), ('Particular · Hot', 'B · Hot'), ('Blanco{Alquiler}', 'Blanco{A}'), ('Blanco{Particular}', 'Blanco{B}'), ('textbf{Alquiler}', 'textbf{A}'), ('textbf{Particular}', 'textbf{B}'), ('Alquiler &', 'A &'), ('Particular &', 'B &')]:
            s = s.replace(old, new)
        p.write_text(s)
    trace = pd.read_csv(destino / 'anexos/trazabilidad_metodo.csv', sep=';')
    trace.loc[trace.etapa.eq('Preparación del informe'), 'entrada_en_repositorio'] += '; src/movilidad_teide/informe_operacion.py; src/movilidad_teide/informe_alineacion.py'
    exportar('trazabilidad_metodo', trace)
    from movilidad_teide.informe.diccionario import _definiciones
    definiciones = _definiciones()
    rows = []
    for p in sorted((destino / 'anexos').glob('*.csv')):
        if p.stem == 'diccionario_anexos':
            continue
        for col in pd.read_csv(p, sep=';', nrows=0).columns:
            (unidad, descripcion) = definiciones[col]
            rows.append({'archivo': p.name, 'campo': col, 'unidad_o_lectura': unidad, 'aclaracion': descripcion})
    exportar('diccionario_anexos', pd.DataFrame(rows))
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    meta.pop('revision_documento', None)
    meta.update(decision='D227', fecha='2026-11-02', version_informe='0.8', estado='Borrador revisado: alineación, colectivos completos y dos escenarios de 2028')
    meta['inputs_sha256'].update({str(p.resolve()): sha(p) for p in usadas + [Path(__file__)]})
    meta['revision_alineacion'] = {'modelo_modificado': False, 'colectivos': 4, 'visitas_persona_anio': float(z.visitas_fuente_anio.sum()), 'cobertura_fuente_sin_con_conciliada': True, 'asignaciones_coches_no_son_escenarios': True, 'titsa_excursiones': 'Estimación conjunta igual por hipótesis; no desglose medido', 'anexos_nuevos': ['cobertura_colectivos.csv', 'cobertura_componentes.csv'], 'alcance': 'Hot de componentes representados, con exclusiones y efectos sin estimar explícitos'}
    meta['revision_prioritaria']['anexos_csv'] = len(list((destino / 'anexos').glob('*.csv')))
    meta['derivados_sha256'] = {str(p.relative_to(destino)): sha(p) for folder in ['anexos', 'tablas', 'figuras'] for p in (destino / folder).iterdir() if p.is_file()}
    (destino / 'metadatos.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    return {**resumen, 'version': '0.8', 'anexos_csv': len(list((destino / 'anexos').glob('*.csv'))), 'comentarios_chat': 3, 'colectivos_conciliados': 4, 'visitas_persona_anio': float(z.visitas_fuente_anio.sum()), 'modelo_modificado': False}

def _figura_cobertura_1(destino):
    (fig, ax) = plt.subplots(figsize=(6.3, 3.65))
    ax.axis('off')
    ax.set(xlim=(0, 1), ylim=(0, 1))
    (azul, jade, tinta) = ('#0C4767', '#397568', '#24343D')

    def caja(x, y, w, h, texto, color, fondo):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=.008', facecolor=fondo, edgecolor=color, lw=1.0))
        ax.text(x + w / 2, y + h / 2, texto, ha='center', va='center', fontsize=10, color=tinta, linespacing=1.35)
    ax.text(0.18, 0.94, 'Personas que viajan en coche', ha='center', fontsize=10, fontweight='bold', color=azul)
    ax.text(0.52, 0.94, 'Asignación A', ha='center', fontsize=11, fontweight='bold', color=azul)
    ax.text(0.85, 0.94, 'Asignación B', ha='center', fontsize=11, fontweight='bold', color=jade)
    for (y, label, a, b) in [(0.65, 'Tenerife\n(no frecuentes y resto)', 'Particular', 'Particular'), (0.4, 'España no Tenerife', 'Alquiler', 'Particular'), (0.15, 'Extranjeros', 'Alquiler', 'Alquiler')]:
        ax.text(0.18, y + 0.08, label, ha='center', va='center', fontsize=10, color=tinta)
        caja(0.39, y, 0.26, 0.16, a, azul, '#EFF5F8')
        caja(0.72, y, 0.26, 0.16, b, jade, '#EEF5F2')
        if label == 'España no Tenerife':
            ax.annotate('', xy=(0.705, y + 0.08), xytext=(0.665, y + 0.08), arrowprops={'arrowstyle': '<->', 'color': '#FA7921', 'lw': 1.5})
    ax.text(0.5, 0.025, 'Cada columna contiene todos los colectivos y se aplica sin y con intervención.', ha='center', fontsize=9.8, color=tinta)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    for ext in ['pdf', 'png']:
        formatear_ejes(fig)
        fig.savefig(destino / 'figuras' / f'asignacion_colectivos.{ext}', dpi=220, bbox_inches='tight')
    plt.close(fig)
    return ()
