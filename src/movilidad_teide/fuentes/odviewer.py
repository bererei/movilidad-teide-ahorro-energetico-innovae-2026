"""Lectores de odviewer; conservo formatos, ausencias y procedencia."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import pandas as pd
import requests
API_BASE = 'https://od.mp3net.es/ODviewer/gateway'
ZONAS_TEIDE = [187, 222]
MODOS = {1: 'no_mecanizado', 2: 'privado', 3: 'publico'}

def consultar_api(endpoint, parametros=None):
    respuesta = requests.get(API_BASE + '/' + endpoint.lstrip('/'), params=parametros, headers={'Accept': 'application/json'}, timeout=(10, 60))
    respuesta.raise_for_status()
    return (respuesta, respuesta.json())

def descargar_consulta(id_matriz, sentido='hacia_teide', modo=None, filtros=None, reutilizar=True, *, catalogo, respuesta_catalogo, carpeta_odviewer):
    CARPETA_ODVIEWER = Path(carpeta_odviewer)
    coincidencias = [m for m in catalogo if m['idMatriz'] == id_matriz]
    if len(coincidencias) != 1 or coincidencias[0]['version'] != 2025:
        raise ValueError('Selecciono un identificador único con zonificación 2025.')
    matriz = coincidencias[0]
    if sentido not in {'hacia_teide', 'desde_teide'}:
        raise ValueError('El sentido debe ser hacia_teide o desde_teide.')
    if modo is not None and modo not in MODOS:
        raise ValueError('El modo debe ser None, 1, 2 o 3.')
    parametros = {'id_matriz2025': id_matriz}
    campo_zona = 'destino2025' if sentido == 'hacia_teide' else 'origen2025'
    parametros[campo_zona] = json.dumps(ZONAS_TEIDE, separators=(',', ':'))
    if modo is not None:
        parametros['modo2025'] = modo
    reservados = {'id_matriz2025', 'origen2025', 'destino2025', 'modo2025'}
    for (campo, valor) in (filtros or {}).items():
        if campo in reservados:
            raise ValueError(f'Configuro {campo} mediante los argumentos de la función.')
        parametros[campo] = json.dumps(valor, separators=(',', ':')) if isinstance(valor, list) else valor
    etiqueta_modo = 'todos_modos' if modo is None else MODOS[modo]
    destino_consulta = CARPETA_ODVIEWER / 'api' / f'matriz_{id_matriz}' / f'{sentido}_{etiqueta_modo}'
    if reutilizar:
        for ficha in sorted(destino_consulta.glob('*/metadata.json'), reverse=True):
            metadata = json.loads(ficha.read_text(encoding='utf-8'))
            if metadata.get('parametros') == parametros and metadata.get('matriz') == matriz and (metadata.get('comprobacion', {}).get('sumas_coincidentes') is True) and all(((ficha.parent / f).is_file() for f in ('viajes_od.json', 'viajes_horarios.json'))):
                print(f"Reutilizo {matriz['nombreDia']} / {sentido} / {etiqueta_modo}")
                return {'carpeta': ficha.parent, 'od': pd.DataFrame(json.loads((ficha.parent / 'viajes_od.json').read_bytes()), columns=['origen', 'destino', 'viajes']), 'horario': pd.DataFrame(json.loads((ficha.parent / 'viajes_horarios.json').read_bytes()), columns=['origen', 'destino', 'id_periodo', 'viajes']), 'metadata': metadata}
    (respuesta_od, registros_od) = consultar_api('viajes2025/', parametros)
    (respuesta_horaria, registros_horarios) = consultar_api('horario2025/', parametros)
    for registros in (registros_od, registros_horarios):
        if not isinstance(registros, list):
            raise ValueError('La API no ha devuelto una lista de viajes.')
        if any((not {'origen', 'destino', 'viajes'}.issubset(fila) for fila in registros)):
            raise ValueError('La respuesta no contiene las columnas esperadas.')
        if any((not math.isfinite(fila['viajes']) or fila['viajes'] < 0 for fila in registros)):
            raise ValueError('Hay valores de viajes no válidos.')
    clave_zona = 'destino' if sentido == 'hacia_teide' else 'origen'
    if any((f[clave_zona] not in ZONAS_TEIDE for f in registros_od + registros_horarios)):
        raise ValueError('La respuesta no respeta las zonas seleccionadas.')
    total_od = math.fsum((f['viajes'] for f in registros_od))
    total_horario = math.fsum((f['viajes'] for f in registros_horarios))
    coinciden = math.isclose(total_od, total_horario, rel_tol=1e-09, abs_tol=1e-08)
    etiqueta_modo = 'todos_modos' if modo is None else MODOS[modo]
    sello = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    carpeta = CARPETA_ODVIEWER / 'api' / f'matriz_{id_matriz}' / f'{sentido}_{etiqueta_modo}' / f'{sello}_{uuid4().hex[:8]}'
    carpeta.mkdir(parents=True, exist_ok=False)
    (carpeta / 'viajes_od.json').write_bytes(respuesta_od.content)
    (carpeta / 'viajes_horarios.json').write_bytes(respuesta_horaria.content)
    metadata = {'url_origen': 'https://od.mp3net.es/ODviewer/', 'fecha_descarga_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'matriz': matriz, 'sentido': sentido, 'modo': etiqueta_modo, 'parametros': parametros, 'consultas': {'od': respuesta_od.url, 'horario': respuesta_horaria.url, 'catalogo': respuesta_catalogo.url}, 'archivos': ['viajes_od.json', 'viajes_horarios.json'], 'licencia': None, 'ponderacion_temporal': None, 'comprobacion': {'relaciones_od': len(registros_od), 'registros_horarios': len(registros_horarios), 'suma_viajes_od': total_od, 'suma_viajes_horarios': total_horario, 'sumas_coincidentes': coinciden}}
    (carpeta / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Matriz:', matriz['nombreDia'])
    print('Suma de viajes:', total_od)
    print('Coincidencia OD-horario:', coinciden)
    print('Guardado en:', carpeta)
    if not coinciden:
        print('Reviso la diferencia OD-horario antes de utilizar los resultados.')
    return {'carpeta': carpeta, 'od': pd.DataFrame(registros_od, columns=['origen', 'destino', 'viajes']), 'horario': pd.DataFrame(registros_horarios), 'metadata': metadata}
