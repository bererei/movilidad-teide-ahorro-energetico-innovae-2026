"""Contratos comunes de tablas, independientes del cálculo energético."""
from numbers import Real
import numpy as np


def comprobar_claves(tabla, claves, nombre):
    if not set(claves) <= set(tabla) or tabla[claves].isna().any().any() or tabla.duplicated(claves).any():
        raise ValueError(f'{nombre}: claves ausentes, nulas o duplicadas.')


_claves = comprobar_claves


def numero_actividad(valor, nombre, *, positivo=False):
    """Rechazar ausencias y valores no físicos antes de multiplicar actividad."""
    if isinstance(valor, (bool, np.bool_)) or not isinstance(valor, Real):
        raise ValueError(f'{nombre} debe ser un número finito.')
    valor = float(valor)
    if not np.isfinite(valor) or valor < 0 or (positivo and valor == 0):
        raise ValueError(f"{nombre} debe ser finito y {('positivo' if positivo else 'no negativo')}.")
    return valor
