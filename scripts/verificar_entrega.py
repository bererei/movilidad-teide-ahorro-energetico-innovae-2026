"""Verificar que código y paquetes extraídos corresponden a la misma referencia."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from movilidad_teide.publicacion.nucleo import verificar
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);a=p.parse_args();print(json.dumps(verificar(a.root),ensure_ascii=False,indent=2))
