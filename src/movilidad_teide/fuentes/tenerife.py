"""Lectores de tenerife; conservo formatos, ausencias y procedencia."""
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import uuid4
import requests
API_BASE = 'https://datos.tenerife.es/ckan/api/3/action/'
PORTAL_BASE = 'https://datos.tenerife.es/ckan'

def nombre_seguro(texto, limite=36):
    texto = unicodedata.normalize('NFKD', str(texto or 'sin_nombre'))
    texto = texto.encode('ascii', 'ignore').decode().lower()
    texto = re.sub('[^a-z0-9._-]+', '_', texto).strip(' ._')[:limite].rstrip(' ._') or 'sin_nombre'
    reservados = {'con', 'prn', 'aux', 'nul'} | {f'com{i}' for i in range(1, 10)} | {f'lpt{i}' for i in range(1, 10)}
    return '_' + texto if texto.split('.')[0] in reservados else texto

def nombre_archivo(recurso, indice):
    ruta = urlparse(recurso.get('url') or '').path
    extension = Path(ruta).suffix.lower()
    if not re.fullmatch('\\.[a-z0-9]{1,8}', extension or ''):
        formato = str(recurso.get('format') or '').lower()
        extension = '.' + formato if re.fullmatch('[a-z0-9]{1,8}', formato) else '.bin'
    nombre = nombre_seguro(recurso.get('name') or Path(ruta).stem, 24)
    identificador = nombre_seguro(str(recurso.get('id') or '')[:8], 8)
    return f'{indice:03d}_{nombre}_{identificador}{extension}'

def es_pagina_o_servicio(recurso, tipo_contenido=''):
    url = str(recurso.get('url') or '').lower()
    formato = str(recurso.get('format') or '').upper()
    return formato in {'HTML', 'HTM', 'WMS', 'WFS', 'WMTS', 'API', 'SPARQL'} or urlparse(url).path.endswith(('.html', '.htm')) or any((marca in url for marca in ('service=wms', 'service=wfs', 'getcapabilities', '/api/'))) or ('text/html' in tipo_contenido.lower())

def descargar_dataset(nombre_o_uuid, *, carpeta_destino):
    CARPETA_DESTINO = Path(carpeta_destino)
    respuesta = requests.get(API_BASE + 'package_show', params={'id': nombre_o_uuid}, timeout=(10, 30))
    respuesta.raise_for_status()
    datos = respuesta.json()
    if datos.get('success') is not True or not isinstance(datos.get('result'), dict):
        raise ValueError(f"CKAN no devolvió el conjunto: {datos.get('error')}")
    conjunto = datos['result']
    identificador = conjunto['id']
    nombre = conjunto.get('name') or identificador
    carpeta_conjunto = CARPETA_DESTINO / f'{nombre_seguro(nombre)}_{identificador[:8]}'
    carpeta = carpeta_conjunto / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8])
    carpeta.mkdir(parents=True, exist_ok=False)
    organizacion = conjunto.get('organization') or {}
    if not isinstance(organizacion, dict):
        organizacion = {}
    metadatos = {'titulo': conjunto.get('title'), 'identificador': identificador, 'url_ficha': f'{PORTAL_BASE}/dataset/{quote(nombre)}', 'organismo_publicador': organizacion.get('title') or organizacion.get('name'), 'licencia': conjunto.get('license_title') or conjunto.get('license_id'), 'url_licencia': conjunto.get('license_url'), 'fecha_descarga_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'archivos': []}
    ruta_metadatos = carpeta / 'metadata.json'
    ruta_metadatos.write_text(json.dumps(metadatos, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for (indice, recurso) in enumerate(conjunto.get('resources') or [], 1):
        url = recurso.get('url')
        if not isinstance(url, str) or urlparse(url).scheme not in {'http', 'https'}:
            print(f"Error en {recurso.get('name') or indice}: URL HTTP(S) ausente o inválida")
            continue
        destino = carpeta / nombre_archivo(recurso, indice)
        temporal = destino.with_name(destino.name + '.part')
        try:
            with requests.get(url, stream=True, timeout=(10, 60)) as archivo_remoto:
                archivo_remoto.raise_for_status()
                tipo = archivo_remoto.headers.get('Content-Type', '')
                if 'text/html' in tipo.lower():
                    destino = destino.with_suffix('.html')
                    temporal = destino.with_name(destino.name + '.part')
                with temporal.open('xb') as archivo_local:
                    for bloque in archivo_remoto.iter_content(chunk_size=1024 * 1024):
                        if bloque:
                            archivo_local.write(bloque)
            os.replace(temporal, destino)
            metadatos['archivos'].append({'nombre_recurso': recurso.get('name'), 'url_origen': url, 'archivo_local': destino.name, 'fecha_modificacion_declarada': recurso.get('last_modified')})
            ruta_metadatos.write_text(json.dumps(metadatos, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'Descargado: {destino.name}')
            if es_pagina_o_servicio(recurso, tipo):
                print('  Aviso: es una página o servicio; esta copia puede ser solo una respuesta puntual.')
        except (requests.RequestException, OSError) as error:
            print(f"Error en {recurso.get('name') or indice}: {error}")
        finally:
            temporal.unlink(missing_ok=True)
    print(f'Metadatos y archivos: {carpeta}')
    return carpeta

def listar_datasets():
    conjuntos = []
    inicio = 0
    while True:
        respuesta = requests.get(API_BASE + 'package_search', params={'rows': 100, 'start': inicio}, timeout=(10, 30))
        respuesta.raise_for_status()
        datos = respuesta.json()
        if datos.get('success') is not True:
            raise ValueError(f"Error de CKAN: {datos.get('error')}")
        resultado = datos['result']
        pagina = resultado['results']
        conjuntos.extend(({'titulo': conjunto.get('title') or conjunto['name'], 'nombre': conjunto['name']} for conjunto in pagina))
        inicio += len(pagina)
        if inicio >= resultado['count']:
            break
        if not pagina:
            raise RuntimeError('La API interrumpió el listado antes de completarlo.')
    return sorted(conjuntos, key=lambda conjunto: conjunto['titulo'].casefold())

def descargar_demanda_teide(anio=2025, *, carpeta_destino):
    """Conservar solo las matrices y catálogos necesarios para revisar TITSA.

    Cuando CKAN permite filtrar, conservo las respuestas originales de la API
    para las líneas 341/342/348. Si publica solo un ZIP, conservo ese original
    completo y filtro después en Silver. Cada ejecución crea una carpeta nueva.
    """
    CARPETA_DESTINO = Path(carpeta_destino)
    import hashlib
    from concurrent.futures import ThreadPoolExecutor
    meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
    prefijo = 'matriz-origen-destino-de-transporte-publico-de-la-isla-de-tenerife-de-'
    respuesta = requests.get(API_BASE + 'package_search', params={'q': f'name:{prefijo}* AND name:*{anio}', 'rows': 20}, timeout=(10, 60))
    respuesta.raise_for_status()
    catalogo = respuesta.json()
    if catalogo.get('success') is not True:
        raise ValueError('El catálogo no devuelve una consulta válida.')
    paquetes = catalogo['result']['results']
    esperados = {f'{prefijo}{mes}-de-{anio}' for mes in meses}
    if len(paquetes) != 12 or {p['name'] for p in paquetes} != esperados:
        raise ValueError('Reviso los doce paquetes mensuales antes de descargar.')
    sello = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8]
    raiz = CARPETA_DESTINO / f'demanda_titsa_teide_{anio}' / sello
    raiz.mkdir(parents=True, exist_ok=False)
    (raiz / 'catalogo.json').write_bytes(respuesta.content)

    def guardar(carpeta, nombre, url, parametros=None):
        destino = carpeta / nombre
        with requests.get(url, params=parametros, stream=True, timeout=(10, 90)) as remoto:
            remoto.raise_for_status()
            with destino.open('xb') as local:
                for bloque in remoto.iter_content(1024 * 1024):
                    if bloque:
                        local.write(bloque)
            url_consulta = remoto.url
        with destino.open('rb') as local:
            huella = hashlib.file_digest(local, 'sha256').hexdigest()
        return {'archivo': str(destino.relative_to(raiz)), 'sha256': huella, 'url': url_consulta}

    def descargar_mes(mes):
        paquete = next((p for p in paquetes if p['name'] == f'{prefijo}{mes}-de-{anio}'))
        carpeta = raiz / f'{meses.index(mes) + 1:02d}'
        carpeta.mkdir()
        archivos = []
        grupos = set()
        for recurso in paquete['resources']:
            nombre = recurso.get('name', '')
            formato = recurso.get('format', '').upper()
            if nombre.startswith('Matriz O-D de transporte público en días'):
                tipo = 'no_laborables' if 'no laborables' in nombre else 'laborables'
                grupos.add(tipo)
                if recurso.get('datastore_active') is True:
                    (inicio, total) = (0, None)
                    while total is None or inicio < total:
                        parametros = {'resource_id': recurso['id'], 'filters': json.dumps({'linea_id': [341, 342, 348]}), 'limit': 10000, 'offset': inicio, 'sort': '_id asc'}
                        f = guardar(carpeta, f'{tipo}_{inicio:06d}.json', API_BASE + 'datastore_search', parametros)
                        datos = json.loads((raiz / f['archivo']).read_text())
                        if datos.get('success') is not True:
                            raise ValueError('Consulta CKAN de demanda inválida.')
                        pagina = datos['result']
                        if total is not None and pagina['total'] != total:
                            raise ValueError('La demanda cambió durante la paginación.')
                        total = pagina['total']
                        registros = pagina['records']
                        if not registros and inicio < total:
                            raise ValueError('La API ha truncado una página de demanda.')
                        if any((int(v['linea_id']) not in [341, 342, 348] for v in registros)):
                            raise ValueError('La API no respeta el filtro de líneas.')
                        f.update(tipo='demanda_api', tipo_dia=tipo, recurso_id=recurso['id'], registros=len(registros), total_filtrado=total, offset=inicio)
                        archivos.append(f)
                        inicio += len(registros)
                        if total == 0:
                            break
                elif formato == 'ZIP':
                    f = guardar(carpeta, f'{tipo}.zip', recurso['url'])
                    f.update(tipo='demanda_zip', tipo_dia=tipo, recurso_id=recurso['id'])
                    archivos.append(f)
                else:
                    raise ValueError('Formato de matriz sin lectura definida; no se omite.')
            elif nombre == 'Paradas de transporte público en matriz O-D' and formato == 'CSV' or (nombre == 'Líneas de transporte público en matriz O-D' and formato == 'JSON') or nombre.startswith('Diccionario de datos de matriz O-D de transporte público'):
                if nombre.startswith('Diccionario') and formato != 'JSON':
                    continue
                tipo = 'paradas_csv' if formato == 'CSV' else 'lineas_json' if nombre.startswith('Líneas') else 'diccionario_json'
                f = guardar(carpeta, recurso['id'] + ('.csv' if formato == 'CSV' else '.json'), recurso['url'])
                f.update(tipo=tipo, recurso_id=recurso['id'], nombre_recurso=nombre)
                archivos.append(f)
        print(f'{mes}: {len(grupos)} tipos de día descargados', flush=True)
        return {'mes': meses.index(mes) + 1, 'conjunto_id': paquete['id'], 'url_ficha': f"{PORTAL_BASE}/dataset/{paquete['name']}", 'fecha_modificacion_catalogo': paquete['metadata_modified'], 'licencia': paquete.get('license_title'), 'tipos_ausentes': sorted({'laborables', 'no_laborables'} - grupos), 'archivos': archivos}
    with ThreadPoolExecutor(max_workers=3) as ejecutor:
        detalle = list(ejecutor.map(descargar_mes, meses))
    manifest = {'version': '1.0', 'anio': anio, 'lineas_objetivo': [341, 342, 348], 'fecha_descarga_utc': datetime.now(timezone.utc).isoformat(), 'url_catalogo': respuesta.url, 'sha256_catalogo': hashlib.sha256(respuesta.content).hexdigest(), 'alcance': 'Matrices mensuales publicadas: cantidades por línea y relación de paradas, no visitantes únicos; sin imputación.', 'meses': detalle}
    (raiz / 'metadatos.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return raiz
