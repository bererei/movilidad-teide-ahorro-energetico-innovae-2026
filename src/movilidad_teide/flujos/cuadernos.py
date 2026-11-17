"""Lectura verificada de las tablas que explico en los cuadernos."""
from dataclasses import dataclass
from pathlib import Path
import json
import pandas as pd

from movilidad_teide.trazabilidad import sha256_archivo


@dataclass
class Cuaderno:
    fuentes: pd.DataFrame
    tablas: dict[str, pd.DataFrame]

    def tabla(self, nombre):
        return self.tablas[nombre].copy(deep=True)


def abrir_cuaderno(root, nombre):
    """Leo las capturas identificadas y rechazo cambios antes de presentar resultados."""
    root = Path(root).resolve()
    manifest = json.loads(Path(__file__).with_name('insumos_cuadernos.json').read_text())
    tablas = {}
    fuentes = []
    for ficha in manifest[nombre]:
        p = root / ficha['ruta']
        if not p.is_file() or sha256_archivo(p) != ficha['sha256']:
            raise ValueError(f'La fuente del cuaderno ha cambiado: {ficha["ruta"]}')
        if p.suffix == '.csv':
            tabla = pd.read_csv(p, sep=ficha['separador'], float_precision='round_trip')
        elif p.suffix == '.parquet':
            tabla = pd.read_parquet(p)
        else:
            datos = json.loads(p.read_text(encoding='utf-8-sig'))
            tabla = pd.DataFrame([
                {'campo': k, 'contenido': v if isinstance(v, (str, int, float, bool)) or v is None else f'{len(v)} elementos conservados'}
                for k, v in datos.items()
            ])
        tablas[ficha['nombre']] = tabla
        fuentes.append({**ficha, 'filas': len(tabla), 'huella_comprobada': True})
    return Cuaderno(pd.DataFrame(fuentes), tablas)
