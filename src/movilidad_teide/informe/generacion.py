"""Coordino los recursos del informe en un destino explícito y reproducible."""
from pathlib import Path
import json
import shutil
import subprocess
import csv

from movilidad_teide.trazabilidad import sha256_archivo
from movilidad_teide.informe.base import preparar_borrador
from movilidad_teide.informe.balance import preparar_revision
from movilidad_teide.informe.lectura import actualizar_lectura
from movilidad_teide.informe.territorio import actualizar_narrativa
from movilidad_teide.informe.escenarios import ampliar_escenarios
from movilidad_teide.informe.operacion import revisar_desarrollos
from movilidad_teide.informe.cobertura import aclarar_cobertura


def _preparar_destino(root, destino):
    """Copio el maestro y los recursos editoriales sin tocar sus originales."""
    for protegido in ('data', 'config', 'src', 'tests', 'notebooks'):
        if destino.is_relative_to((root / protegido).resolve()):
            raise ValueError('El informe requiere un destino separado de las entradas y el código.')
    if destino == root:
        raise ValueError('La raíz del repositorio no es un destino de generación.')
    origen = root / 'docs/informe_energetico'
    maestro_anterior = origen / 'revision/antecedentes/v0.14/main.tex'
    maestro = maestro_anterior if maestro_anterior.exists() else origen / 'main.tex'
    destino.mkdir(parents=True, exist_ok=True)
    if destino != origen:
        for p in [maestro, *origen.glob('*.sty')]:
            shutil.copy2(p, destino / p.name)
        for name in ('cabildo_logo.pdf', 'marcas_programa.png'):
            p = origen / 'figuras' / name
            if p.exists():
                (destino / 'figuras').mkdir(exist_ok=True)
                shutil.copy2(p, destino / 'figuras' / name)


def _trazabilidad_actual(root, destino):
    from movilidad_teide.informe.guia import actualizar_guia
    actualizar_guia(root, destino)


def generar_recursos(root, destino):
    """Genero la revisión vigente desde los productores integrados, sin editar el cálculo o el maestro."""
    root, destino = Path(root).resolve(), Path(destino).resolve()
    _preparar_destino(root, destino)
    resumen = preparar_borrador(root, destino)
    resumen = preparar_revision(root, destino)
    for productor in (actualizar_lectura, actualizar_narrativa, ampliar_escenarios,
                       revisar_desarrollos, aclarar_cobertura):
        resumen = productor(root, destino, resumen)
    from movilidad_teide.informe.cierre import preparar_cierre
    preparar_cierre(root, destino)
    _trazabilidad_actual(root, destino)
    p = destino / 'metadatos.json'
    meta = json.loads(p.read_text())
    meta.update(decision='D232', fecha='2026-11-05', version_informe='0.14', estado='Trazabilidad del parque, factores e hipótesis de circulación aclarada; sin cambios de cálculo')
    meta.pop('decision_externa_propuesta', None)
    meta.pop('revision_documento', None)
    # Registro el código realmente ejecutado; las huellas históricas no se reescriben.
    paquete = Path(__file__).parents[1]
    for fuente in paquete.rglob('*.py'):
        meta['inputs_sha256'][str(fuente)] = sha256_archivo(fuente)
    meta['inputs_sha256'][str(paquete / 'informe_campos.txt')] = sha256_archivo(paquete / 'informe_campos.txt')
    maestro = root / 'docs/informe_energetico/revision/antecedentes/v0.14/main.tex'
    if not maestro.exists():
        maestro = root / 'docs/informe_energetico/main.tex'
    meta['inputs_sha256'][str(maestro)] = sha256_archivo(maestro)
    meta['generacion_integrada'] = {
        'version_editorial': '0.14',
        'entrada': 'scripts/generar_informe.py',
        'parche_temporal_necesario': False,
        'compilacion_pdf_ejecutada': False,
        'datos_y_escenarios_modificados': False,
    }
    meta['revision_prioritaria']['anexos_csv'] = len(list((destino / 'anexos').glob('*.csv')))
    control = root / 'docs/informe_energetico/revision/comentarios_atendidos.csv'
    with control.open(encoding='utf-8-sig', newline='') as f:
        comentarios = list(csv.DictReader(f, delimiter=';'))
    totales = {
        'comentarios_pdf_acumulados': sum(not c['comentario_id'].startswith('CHAT-') for c in comentarios),
        'solicitudes_chat_acumuladas': sum(c['comentario_id'].startswith('CHAT-') for c in comentarios),
    }
    meta['control_editorial'] = {**totales, 'registro': str(control.relative_to(root)), 'sha256': sha256_archivo(control), 'nota': 'El acumulado distingue comentarios de PDF y solicitudes del chat; no son comentarios nuevos de esta versión.'}
    meta['revision_documental_09'] = {'modelo_modificado': False, 'guia_fichas_actuales': 8, 'cuadernos_refactorizados': True, 'reconstruccion_previa': 'docs/VERIFICACION_REFACTORIZACION.json; 1585 pruebas y 48 tablas con diferencia cero en la fase anterior; no implica nueva ejecución en esta revisión.'}
    meta['revision_narrativa']['voz'] = 'Predominio impersonal y sujetos concretos; D228 sustituye para el informe la preferencia anterior de D223.'
    meta['revision_editorial_010'] = {'modelo_modificado': False, 'alcance': 'Voz del informe y de sus textos generados; la documentación y los cuadernos conservan su voz.', 'antecedente': 'Informe v0.9; decisión D227', 'datos_parametros_hipotesis_formulas_resultados_modificados': False}
    meta['revision_cierre_011'] = {'decision':'D229', 'fecha':'2026-11-05', 'comentarios_pdf_v010':63, 'datos_parametros_y_resultados_previos_modificados':False, 'ampliacion':'Sensibilidad algebraica conjunta y umbrales de demanda sobre salidas conservadas; no una nueva simulación de oferta.'}
    meta['revision_claridad_012'] = {'decision':'D230', 'fecha':'2026-11-05', 'alcance':'Precisión editorial del informe y sus productores: flota, perfiles de demanda, expediciones, intervalos, resultados y referencias.', 'calculos_parametros_hipotesis_resultados_modificados':False, 'antecedente':'D229 / informe v0.11; sus sensibilidades permanecen iguales.'}
    pdf_comentado = root / 'docs/informe_energetico/INFORME_ENERGETICO_v0.12_2026-11-05 - BGD.pdf'
    meta['revision_notas_013'] = {'decision':'D231','fecha':'2026-11-05','comentarios_pdf_v012':15,'pdf_comentado':str(pdf_comentado.relative_to(root)),'pdf_comentado_sha256':sha256_archivo(pdf_comentado),'datos_parametros_formulas_y_resultados_modificados':False,'alcance':'Comentarios, atribución de alcance, parámetros COPERT, representación en tep/MWh, redondeo y explicación de sensibilidad.'}
    # Conservo las comprobaciones documentadas de revisiones anteriores como antecedentes.
    publicado = root / 'docs/informe_energetico/revision/antecedentes/v0.14/metadatos.json'
    if not publicado.exists():
        publicado = root / 'docs/informe_energetico/metadatos.json'
    if publicado.exists():
        anteriores = json.loads(publicado.read_text())
        for clave in ('revision_documental_09', 'revision_editorial_010',
                      'revision_cierre_011', 'revision_claridad_012', 'revision_notas_013'):
            if 'comprobaciones' in anteriores.get(clave, {}):
                meta[clave] = anteriores[clave]
    for relativo in ('data/silver/vehiculos/flota_teide/perfil_combustible_euro_por_servicio_2025.csv', 'data/silver/vehiculos/ponderacion/cobertura_identificacion.csv', 'data/silver/vehiculos/ponderacion/factores.csv', 'data/silver/vehiculos/ponderacion/metodos_por_servicio.csv', 'data/silver/geografia/perfiles_altimetricos/aguamansa_el_portillo/metadatos.json'):
        meta['inputs_sha256'][str(root / relativo)] = sha256_archivo(root / relativo)
    meta['revision_trazabilidad_014'] = {'decision':'D232', 'datos_parametros_hipotesis_calculos_modificados':False, 'alcance':'Parque DGT, curvas y sustituciones COPERT, pesos de actividad, velocidades, visita próxima y referencia espacial norte.'}
    meta['derivados_sha256'] = {
        str(f.relative_to(destino)): sha256_archivo(f)
        for carpeta in ('anexos', 'tablas', 'figuras')
        for f in sorted((destino / carpeta).iterdir()) if f.is_file()
    }
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    resumen.pop('comentarios_pdf', None)
    resumen.pop('comentarios_chat', None)
    return {**resumen, **totales, 'version': '0.14', 'anexos_csv': len(list((destino/'anexos').glob('*.csv')))}


def compilar_pdf(destino):
    """Mantengo la entrada citada por las fichas y los cuadernos anteriores."""
    from movilidad_teide.informe.compilacion import compilar_pdf as compilar
    return compilar(destino)
