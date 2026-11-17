"""configuracion: parametros tipos. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from dataclasses import dataclass


class ErrorParametros(ValueError):
    """Entrada incompleta, ambigua o incompatible con el cálculo disponible."""

@dataclass(frozen=True)
class Campo:
    clave: str
    grupo: str
    nombre: str
    unidad: str
    tipo: str = "numero"
    minimo: float | None = None
    maximo: float | None = None
    opciones: tuple = ()
    aplicacion: str = "Referencia / fase pendiente de conectar"

LIBRO = "config/parametros_modelo.xlsx"

CASOS = ("Central", "Variante A", "Variante B")

MODOS = ("Propuesta", "Manual", "Pendiente", "Heredar central")

METODOS = {
    "Ajuste histórico con exclusión temporal": "ajuste_log_lineal_con_exclusiones",
    "Tasa compuesta 2019–2025": "cagr_2019_2025",
    "Tasa compuesta 2023–2025": "cagr_2023_2025",
    "Tasas manuales por acceso": "tasas_manuales",
}

ACCESOS = {"OROTAVA": "Norte — Aguamansa", "VILAFLOR": "Sur — Vilaflor", "LAGUNA": "Este — La Esperanza", "CHIO": "Oeste — Chío"}

AZUL, JADE, NARANJA = "0C4767", "397568", "FA7921"

FONDO, TEXTO = "EFF5F8", "24343D"
