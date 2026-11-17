"""Reconstrucción histórica del balance previo a la ordenación vigente."""
from pathlib import Path
import json
import platform
from io import StringIO

import numpy as np
import pandas as pd

from movilidad_teide.trazabilidad import sha256_archivo
from .fuentes import carpeta_etapa, verificar_entradas
from .pendiente import calcular_pendiente
from .modulacion import calcular_modulacion
from .inventario import calcular_inventario
from .seleccion import calcular_seleccion


def comparar_etapa(root, nombre, resultado):
    """Interfaz histórica: conservo las mismas referencias y tolerancias."""
    from .comprobaciones import comparar_tablas
    return comparar_tablas(carpeta_etapa(root,nombre),resultado,nombre=nombre)


def reproducir_estudio(root, destino=None):
    """Calculo pendiente → oferta → inventario → balance, desde las fuentes fijadas."""
    root = Path(root).resolve()
    if destino is not None:
        destino = Path(destino).resolve()
        if destino == root or any(destino.is_relative_to((root / p).resolve()) for p in ('data', 'config', 'docs', 'src', 'tests', 'notebooks')):
            raise ValueError('La reproducción necesita un destino independiente de originales, referencias y código.')
        if destino.exists() and any(destino.iterdir()):
            raise FileExistsError('Conservo las ejecuciones anteriores: elijo un destino vacío.')
    parametros, fuentes, productores = verificar_entradas(root)
    resultados = {}
    controles = []
    for nombre, productor, anterior in (
        ('pendiente', calcular_pendiente, None),
        ('modulacion', calcular_modulacion, 'pendiente'),
        ('inventario', calcular_inventario, 'modulacion'),
        ('seleccion', calcular_seleccion, 'inventario'),
    ):
        print(f'Reconstruyo {nombre}...', flush=True)
        args = (parametros, resultados[anterior]) if nombre == 'seleccion' else (root, parametros, resultados[anterior]) if anterior else (root, parametros)
        resultado = productor(*args)
        controles.extend(comparar_etapa(root, nombre, resultado))
        resultados[nombre] = resultado
    # Compruebo de nuevo las entradas tras el cálculo para detectar cambios durante la ejecución.
    for p, huella in fuentes.items():
        if sha256_archivo(p) != huella:
            raise ValueError(f'Una entrada ha cambiado durante la reproducción: {p}')
    if destino is not None:
        destino.mkdir(parents=True, exist_ok=True)
        for nombre, etapa in resultados.items():
            carpeta = destino / nombre
            carpeta.mkdir()
            for clave, tabla in etapa.tablas.items():
                tabla.to_csv(carpeta / f'{clave}.csv', sep=';', index=False, encoding='utf-8-sig', float_format='%.17g')
            for clave, tabla in etapa.auxiliares.items():
                tabla.to_parquet(carpeta / f'{clave}.parquet', index=False)
        pd.DataFrame(controles).to_csv(destino / 'comparacion_referencia.csv', sep=';', index=False)
        paquete = Path(__file__).parents[1]
        meta = {
            'parametros': parametros, 'fuentes_sha256': fuentes,
            'codigo_actual_sha256': {str(p.relative_to(paquete)): sha256_archivo(p) for p in paquete.rglob('*.py')},
            'productores_historicos_conservados': productores,
            'productores_historicos_igualados_al_codigo_actual': False,
            'referencia': 'Entradas y ejecuciones anteriores conservadas; reconstrucción numérica sin cambios de hipótesis.',
            'entorno': {'python': platform.python_version(), 'pandas': pd.__version__, 'numpy': np.__version__},
            'tablas_comparadas': len(controles),
            'maxima_diferencia_absoluta': max(c['maxima_diferencia_absoluta'] for c in controles),
            'cumplimiento_metodologico_o_institucional_acreditado': False,
        }
        (destino / 'metadatos.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    return resultados, pd.DataFrame(controles)
