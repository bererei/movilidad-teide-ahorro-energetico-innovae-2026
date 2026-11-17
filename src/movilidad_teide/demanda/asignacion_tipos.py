"""demanda: asignacion tipos. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations


class ErrorAsignacion(ValueError):
    """Una fuente o propuesta no permite conservar sus unidades o totales."""

SEGMENTOS = {
    'extranjero': 'Turistas extranjeros',
    'espana_no_tenerife': 'Turistas nacionales no Tenerife',
    'tenerife_no_frecuente': 'Residentes de Tenerife no frecuentes',
    'tenerife_resto': 'Resto de residentes de Tenerife',
}

SENTIDOS = {'gen': 'hacia_teide', 'attr': 'desde_teide'}

PENDIENTE = 'sin_asignar'
