"""Localizar una fuente citada con su nombre de adquisición, sin copiarla a rutas antiguas."""
from pathlib import Path
import json

def resolver_procedencia(root, nombre):
    root=Path(root).resolve();name=str(nombre)
    mapping=json.loads((root/'config/rutas_datos.json').read_text())['resolucion_de_procedencia_original']
    for old,new in sorted(mapping.items(),key=lambda p:-len(p[0])):
        if name==old or name.startswith(old+'/'):
            name=new+name[len(old):];break
    p=Path(name)
    if p.is_absolute() or '..' in p.parts:raise ValueError('Referencia de procedencia no portable.')
    return root/p
