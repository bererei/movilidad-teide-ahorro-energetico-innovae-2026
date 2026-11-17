"""Resultados explícitos de cada etapa, separados de su exportación."""
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class Etapa:
    tablas: dict[str, pd.DataFrame]
    auxiliares: dict[str, pd.DataFrame] = field(default_factory=dict)
