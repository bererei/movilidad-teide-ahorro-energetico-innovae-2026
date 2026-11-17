"""Comprobar procedencia y capa Medallion del terreno sin modificar originales."""
from pathlib import Path
import argparse,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from movilidad_teide.cartografia.verificacion_terreno import verificar_terreno

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--destino',type=Path,required=True)
    args=p.parse_args();verificar_terreno(args.root,args.destino)
