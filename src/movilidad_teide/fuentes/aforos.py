"""Lectores de aforos; conservo formatos, ausencias y procedencia."""
from pathlib import Path
import pandas as pd
columnas_medida = ['ecoches', 'eguaguas', 'scoches', 'sguaguas']
columnas_requeridas = {'punto', 'fecha', 'hora', *columnas_medida}

def leer_filas_aforo(path, hoja, filas):
    cabecera = None
    registros = []
    control = {'archivo': path.name, 'hoja': hoja, 'cabeceras': 0, 'filas_vacias': 0, 'celdas_auxiliares_sin_nombre': 0, 'alias_columnas': {}}
    for (numero, fila) in enumerate(filas, start=1):
        if not any((v is not None and str(v).strip() for v in fila)):
            control['filas_vacias'] += 1
            continue
        etiquetas = [str(v).strip().casefold().replace('año', 'anio') if v is not None else '' for v in fila]
        if etiquetas[0] == 'punto':
            if 'year' in etiquetas:
                control['alias_columnas']['year'] = 'anio'
            etiquetas = ['anio' if v == 'year' else v for v in etiquetas]
            nueva = {nombre: i for (i, nombre) in enumerate(etiquetas) if nombre}
            assert len(nueva) == sum((bool(v) for v in etiquetas)), f'Columnas repetidas en {path.name}/{hoja}, fila {numero}'
            assert columnas_requeridas <= nueva.keys(), f'Faltan columnas en {path.name}/{hoja}: {columnas_requeridas - nueva.keys()}'
            assert nueva.keys() <= columnas_requeridas | {'dia', 'mes', 'anio'}, f"Columnas no previstas en {path.name}/{hoja}: {nueva.keys() - columnas_requeridas - {'dia', 'mes', 'anio'}}"
            if cabecera is not None:
                assert nueva == cabecera, f'Cabeceras distintas: {path.name}/{hoja}'
            cabecera = nueva
            control['cabeceras'] += 1
            continue
        assert cabecera is not None, f'Datos sin cabecera reconocida: {path.name}/{hoja}, fila {numero}'
        assert max(cabecera.values()) < len(fila), f'Fila incompleta: {path.name}/{hoja}, fila {numero}'
        registro = {nombre: fila[i] for (nombre, i) in cabecera.items()}
        registro.update(archivo_origen=path.name, hoja_origen=hoja, fila_origen=numero)
        registros.append(registro)
        posiciones = set(cabecera.values())
        control['celdas_auxiliares_sin_nombre'] += sum((i not in posiciones and v is not None and bool(str(v).strip()) for (i, v) in enumerate(fila)))
    control['registros'] = len(registros)
    return (pd.DataFrame(registros), control)

def leer_csv_aforos(path):
    import csv
    with path.open(encoding='utf-8-sig', newline='') as handle:
        dialecto = csv.Sniffer().sniff(handle.readline(), delimiters=',;')
        handle.seek(0)
        (tabla, control) = leer_filas_aforo(path, 'CSV', csv.reader(handle, dialecto))
    control['separador_csv'] = dialecto.delimiter
    control['codificacion_csv'] = 'utf-8-sig'
    return (tabla, control)

def normalizar_horas_aforo(serie):
    texto = serie.astype('string').str.strip()
    texto = texto.str.replace('^(\\d{1,2}:\\d{2})$', '\\1:00', regex=True)
    desfase = pd.to_timedelta(texto, errors='raise')
    assert desfase.notna().all(), 'Hora ausente en la fuente'
    assert desfase.between(pd.Timedelta(0), pd.Timedelta(days=1), inclusive='left').all()
    assert (desfase % pd.Timedelta(hours=1)).eq(pd.Timedelta(0)).all()
    return desfase

def resumir_aforos(datos, claves, mensual=False):
    filas = []
    for (valores, bloque) in datos.groupby(claves, sort=True):
        fila = dict(zip(claves, valores))
        anio = int(fila['anio'])
        inicio = pd.Timestamp(anio, int(fila['mes']) if mensual else 1, 1)
        fin = inicio + (pd.offsets.MonthBegin(1) if mensual else pd.offsets.YearBegin(1))
        calendario = pd.date_range(inicio, fin, inclusive='left', freq='h')
        marcas = pd.DatetimeIndex(bloque['timestamp_local'].unique())
        fila.update(medidas=len(bloque), valores_presentes=int(bloque['n_vehiculos_corregido'].notna().sum()), total_valores_fuente=bloque['n_vehiculos_corregido'].sum(min_count=1), horas_esperadas=len(calendario), horas_ausentes=len(calendario.difference(marcas)), marcas_fuera_calendario=len(marcas.difference(calendario)), cobertura_regular_pct=100.0 * len(marcas.intersection(calendario)) / len(calendario), valores_negativos=int(bloque['valor_negativo'].sum()), valores_decimales=int(bloque['valor_decimal'].sum()), valores_ausentes=int(bloque['valor_ausente'].sum()), marcas_corregidas_2025=int(bloque['correccion_temporal_aplicada'].sum()))
        filas.append(fila)
    return pd.DataFrame(filas)
