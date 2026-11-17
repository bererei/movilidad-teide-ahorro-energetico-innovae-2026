"""Contrato explícito de entradas complementarias y trazabilidad de la entrega."""
from pathlib import Path
import json
from movilidad_teide.trazabilidad import sha256_archivo


def cargar_especificacion(root, *, verificar=True):
    root=Path(root).resolve()
    spec=json.loads((root/'config/dependencias_publicacion.json').read_text())
    if spec.get('version')!='1.0' or spec['referencia']['visitas_sin_y_con']!=2500000:
        raise ValueError('Especificación de publicación incompatible con la referencia.')
    paths=[x['ruta'] for x in spec['entradas']]
    if len(paths)!=len(set(paths)):raise ValueError('Dependencia de publicación repetida.')
    for row in spec['entradas']:
        name=Path(row['ruta']);p=root/name
        if name.is_absolute() or '..' in name.parts or not p.resolve().is_relative_to(root):
            raise ValueError('Dependencia de publicación no portable: '+str(name))
        if verificar:
            if not p.is_file():raise FileNotFoundError('Falta la entrada pública: '+str(name))
            if p.stat().st_size!=row['bytes'] or sha256_archivo(p)!=row['sha256']:
                raise ValueError('Entrada de publicación modificada: '+str(name))
    if verificar:
        for name,key in [('docs/informe_energetico/main.tex','maestro_sha256'),('docs/informe_energetico/INFORME_ENERGETICO_v0.25_2026-11-11 - Entregado.pdf','pdf_sha256')]:
            if sha256_archivo(root/name)!=spec['referencia'][key]:
                raise ValueError('La especificación no corresponde al informe: '+name)
    return spec
