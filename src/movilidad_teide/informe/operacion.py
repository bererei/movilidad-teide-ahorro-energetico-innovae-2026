"""Derivados de revisión: proceso operativo y contraste con el balance vigente."""
from movilidad_teide.informe.formato import formatear_ejes
from pathlib import Path
import hashlib, json, re
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from movilidad_teide.informe.formato import numero, tex

def revisar_desarrollos(root, destino, resumen):
    (root, destino) = (Path(root), Path(destino))
    usadas = [Path(__file__)]

    def leer(rel):
        p = root / rel
        usadas.append(p)
        return pd.read_csv(p, sep=';', float_precision='round_trip')

    def exportar(nombre, tabla):
        tabla.to_csv(destino / 'anexos' / f'{nombre}.csv', sep=';', index=False, encoding='utf-8-sig', float_format='%.17g')

    def tabla(nombre, titulo, cabeceras, filas, nota, columnas):
        lines = ['\\begin{table}[H]', '\\caption{' + titulo + '}', '\\centering{\\fontsize{10}{13}\\selectfont\\setlength{\\extrarowheight}{3pt}', '\\begin{tabularx}{\\linewidth}{@{}' + columnas + '@{}}', '\\rowcolor{azul} ' + ' & '.join(('\\Blanco{' + ('\\shortstack[r]{' + '\\\\'.join((tex(z) for z in x.split('\n'))) + '}' if '\n' in x else tex(x)) + '}' for x in cabeceras)) + '\\\\']
        for (i, row) in enumerate(filas):
            lines.append(('\\rowcolor{fondo_azul} ' if i % 2 else '') + ' & '.join((tex(x) for x in row)) + '\\\\')
        lines += ['\\bottomrule\\end{tabularx}}', '\\Fuente{Fuente: ' + tex(nota) + '}', '\\end{table}']
        (destino / 'tablas' / f'{nombre}.tex').write_text('\n'.join(lines) + '\n')
    base = 'data/silver/energia_turismos/'
    diag = leer(base + '20261101_flota_30_tres_sustitutas/diagnostico_diario.csv')
    diag = diag[diag.politica.eq('Accesos e interior según reservas')].copy()
    assert len(diag) == 10 and diag.circulacion_30_reglas_propuestas_comprobada.all()
    assert diag.demanda_y_cadenas_completas_comprobadas.all() and diag.cierre_de_bases_comprobado.all()
    assert diag.vehiculos_programados.add(diag.vehiculos_sin_programar).eq(30).all()
    nombres = {30: 'Marzo, laborable', 31: 'Marzo, sábado', 32: 'Marzo, domingo', 39: 'Julio, sábado', 40: 'Julio, laborable', 41: 'Julio, domingo', 52: 'Octubre, sábado', 54: 'Octubre, laborable', 56: 'Octubre, domingo'}
    diag['observacion_descripcion'] = diag.observacion.map(nombres).fillna('Diseño p85, comprobación separada')
    exportar('comprobacion_operacion', diag)
    costes = leer(base + '20261101_flota_30_tres_sustitutas/costes_anuales_reproducidos.csv')
    balance = leer(base + '20261101_hot_central_fta_sensibilidad/balance_vigente.csv')
    contraste = balance[balance.referencia_id.eq('referencia_guagua_2') & balance.caso_pendiente.eq('Referencia del Excel') & balance.tratamiento_operativo.eq('Hot COPERT')].copy()
    assert len(contraste) == 4
    contraste = contraste.merge(costes[costes.referencia_id.eq('referencia_guagua_2')][['politica', 'hot_mwh_anio', 'vehiculos_km_anio']], on='politica', validate='many_to_one')
    assert (contraste.guaguas_mwh_anio - contraste.hot_mwh_anio).abs().max() < 1e-08
    exportar('comparacion_operativa', contraste)
    filas = []
    for politica in sorted(contraste.politica.unique(), key=lambda x: x == 'Accesos e interior según reservas'):
        g = contraste[contraste.politica.eq(politica)]
        filas.append(['Accesos modulados; interior regular' if politica != 'Accesos e interior según reservas' else 'Accesos e interior según reservas', numero(g.vehiculos_km_anio.iloc[0], 0), numero(g.hot_mwh_anio.iloc[0]), numero(g.saldo_construccion_condicionada_tep_anio.min()) + '–' + numero(g.saldo_construccion_condicionada_tep_anio.max())])
    tabla('comparacion_operativa', 'Efecto de modular el servicio interior, con la misma demanda de 2028', ['Oferta con intervención', 'Vehículos-km\npor año', 'Consumo flota\nMWh/año', 'Ahorro\ntep/año'], filas, 'Movimientos, costes reproducidos y balance vigente; referencia de autocar diésel Hot y ajuste de pendiente de turismos. Las cifras de kilómetros y energía son de toda la flota. Las dos asignaciones de procedencia se conservan.', 'Xrrr')
    filas = []
    for obs in [30, 41]:
        q = diag[diag.observacion.eq(obs)].iloc[0]
        m = pd.read_csv(destino / 'anexos/expediciones_casos.csv', sep=';')
        m = m[m.observacion.eq(obs)]
        filas.append([nombres[obs], int(q.vehiculos_programados), int(q.vehiculos_sin_programar), int(m.componente.eq('comercial').sum()), int(m.componente.ne('comercial').sum()), numero(m.km_por_recorrido.sum(), 1)])
    tabla('sintesis_operacion', 'Flota y viajes de dos perfiles de demanda proyectados a 2028', ['Perfil fuente', 'Guaguas\nasignadas', 'Guaguas\nsin viajes', 'Viajes\ncomerciales', 'Viajes\nen vacío', 'Vehículos-km\npor día'], filas, 'Diagnóstico de flota y movimientos con identidad física del mismo cálculo. Cada guagua física asignada puede realizar varios viajes durante la jornada; los viajes se cuentan en un sentido y se separan los vacíos. Sin viajes indica guaguas sin programar para sustitución. Los meses y tipos de día identifican perfiles fuente de 2025, no días concretos de 2028 ni dos categorías para todo el año.', 'Xrrrrr')
    _figura_operacion_1(destino)
    from movilidad_teide.informe.diccionario import _definiciones
    definiciones = _definiciones()
    rows = []
    for p in sorted((destino / 'anexos').glob('*.csv')):
        if p.stem == 'diccionario_anexos':
            continue
        for col in pd.read_csv(p, sep=';', nrows=0).columns:
            assert col in definiciones, (p.name, col)
            (unidad, descripcion) = definiciones[col]
            rows.append({'archivo': p.name, 'campo': col, 'unidad_o_lectura': unidad, 'aclaracion': descripcion})
    exportar('diccionario_anexos', pd.DataFrame(rows))
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    meta = json.loads((destino / 'metadatos.json').read_text())
    meta.update(decision='D226', version_informe='0.7', estado='Borrador revisado: proceso operativo completo, seguimiento y correspondencia con el cálculo')
    usadas.append(root / 'docs/informe_energetico/INFORME_ENERGETICO_v0.6_2026-11-01 - BGD.pdf')
    meta['inputs_sha256'].update({str(p.resolve()): sha(p) for p in usadas})
    meta['derivados_sha256'] = {str(p.relative_to(destino)): sha(p) for carpeta in ['anexos', 'tablas', 'figuras'] for p in (destino / carpeta).iterdir() if p.is_file()}
    meta['revision_desarrollos'] = {'comentarios_nuevos': 4, 'modelo_modificado': False, 'operacion': 'Explico demanda, cadenas, modulación, asignación de vehículos, refuerzos, comprobación física y valoración energética; óptimo solo para los enlaces del horario fijado, no para cualquier horario futuro.', 'seguimiento': 'Distingo datos por medir/estimar e indicadores propuestos; no son observaciones actuales.', 'anexos_nuevos': ['comprobacion_operacion.csv', 'comparacion_operativa.csv']}
    (destino / 'metadatos.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    return {**resumen, 'version': '0.7', 'anexos_csv': len(list((destino / 'anexos').glob('*.csv'))), 'comentarios_pdf': 4}

def _figura_operacion_1(destino):
    (fig, ax) = plt.subplots(figsize=(6.3, 4.7))
    ax.axis('off')
    ax.set(xlim=(0, 10), ylim=(0, 10))
    bloques = [('1  Demanda común de 2028', 'Nueve perfiles de demanda; p85 aparte'), ('2  Visitas completas', 'Subida, destino interior y regreso; 46 plazas'), ('3  Oferta modulada', 'Expediciones necesarias, regresos y vacíos'), ('4  Vehículos y refuerzos', '30 guaguas físicas; al menos 3 sin viajes'), ('5  Comprobaciones y energía', 'Viajeros, plazas, horarios y bases → km → consumo')]
    for (i, (title, body)) in enumerate(bloques):
        y = 9 - i * 1.92
        ax.add_patch(FancyBboxPatch((0.3, y - 0.95), 9.4, 1.5, boxstyle='round,pad=.08', facecolor='#EFF5F8' if i % 2 == 0 else '#EEF5F2', edgecolor='#0C4767', linewidth=1))
        ax.text(5, y + 0.05, title, ha='center', va='center', fontsize=11, fontweight='bold', color='#0C4767')
        ax.text(5, y - 0.5, body, ha='center', va='center', fontsize=10, color='#24343D')
        if i < 4:
            ax.annotate('', xy=(5, y - 1.32), xytext=(5, y - 1.05), arrowprops={'arrowstyle': '->', 'color': '#0C4767'})
    fig.tight_layout()
    for ext in ['pdf', 'png']:
        formatear_ejes(fig)
        fig.savefig(destino / 'figuras' / f'proceso_operativo.{ext}', dpi=220, bbox_inches='tight')
    plt.close(fig)
    return ()
