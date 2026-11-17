"""vehiculos: flota tipos. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations


class ErrorFlota(ValueError):
    """Fuente incompleta, composición duplicada o propuesta fuera de límites."""
