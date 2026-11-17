"""Comparación de tablas sin dependencia de ninguna programación de transporte."""
from pathlib import Path
from io import StringIO
import numpy as np
import pandas as pd

def comparar_tablas(origen, resultado, *, nombre, columnas_por_tabla=None, claves_por_tabla=None):
    """Exijo igualdad de estructura y ausencias; aplico el umbral numérico existente.

    1e-8 es el control absoluto ya utilizado en estas etapas para conciliaciones
    de CSV. No es una precisión física ni un margen para variar hipótesis. Las
    comprobaciones internas más estrictas se conservan dentro de cada cálculo.
    """
    origen = Path(origen)
    controles = []
    for extension, tablas in (('csv', resultado.tablas), ('parquet', resultado.auxiliares)):
        for clave, actual in tablas.items():
            path = origen / f'{clave}.{extension}'
            esperado = pd.read_csv(path, sep=';', float_precision='round_trip') if extension == 'csv' else pd.read_parquet(path)
            actual = actual.reset_index(drop=True)
            if extension == 'csv':
                # Comparo la misma representación persistida. Un texto vacío
                # se exporta vacío y read_csv lo interpreta como ausencia;
                # no cambio ese valor dentro del cálculo ni lo sustituyo por cero.
                actual = pd.read_csv(StringIO(actual.to_csv(sep=';', index=False, float_format='%.17g')),
                                     sep=';', float_precision='round_trip')
            if columnas_por_tabla and clave in columnas_por_tabla:
                esperado = esperado[columnas_por_tabla[clave]]
            if claves_por_tabla and clave in claves_por_tabla:
                ids = claves_por_tabla[clave]
                actual = actual.sort_values(ids).reset_index(drop=True)
                esperado = esperado.sort_values(ids).reset_index(drop=True)
            esperado = esperado.reset_index(drop=True)
            pd.testing.assert_frame_equal(actual, esperado, check_dtype=False, check_exact=False, rtol=0, atol=1e-8)
            maxima = 0.
            for col in esperado:
                if pd.api.types.is_numeric_dtype(esperado[col]) and not pd.api.types.is_bool_dtype(esperado[col]):
                    a = pd.to_numeric(actual[col]).to_numpy(dtype=float)
                    b = esperado[col].to_numpy(dtype=float)
                    diferencias = np.abs(a - b)
                    if np.isfinite(diferencias).any():
                        maxima = max(maxima, float(np.nanmax(diferencias)))
            controles.append({'etapa': nombre, 'tabla': clave, 'filas': len(actual),
                              'columnas': len(actual.columns), 'maxima_diferencia_absoluta': maxima,
                              'tolerancia_absoluta': 1e-8, 'equivalente': True})
    return controles

