"""Definiciones y unidades de los anexos del informe."""
from pathlib import Path

def _definiciones():
    """Diccionario exhaustivo: ninguna columna se deja al significado inferido del nombre."""
    text = (Path(__file__).parents[1] / 'informe_campos.txt').read_text()
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        (key, unit, meaning) = line.split('|', 2)
        assert key not in out, key
        out[key] = (unit, meaning)
    return out
