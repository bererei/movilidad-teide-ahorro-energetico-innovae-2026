"""Incorporar o verificar resultados vigentes en Gold, sin recalcular el estudio."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from movilidad_teide.configuracion.ordenacion import leer_ordenacion,verificar_entradas
from movilidad_teide.publicacion.gold import promover_gold

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--candidata',type=Path,help='Raíz arbol_publicacion de una candidata sellada.')
    p.add_argument('--verificar',action='store_true',help='Comprobar sin incorporar archivos.')
    a=p.parse_args()
    reference=leer_ordenacion(a.root);verificar_entradas(a.root,reference)
    checks=promover_gold(a.root,a.candidata,a.verificar)
    print(json.dumps({k:v for k,v in checks.items() if k!='archivos'},ensure_ascii=False,indent=2))
