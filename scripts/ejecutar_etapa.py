"""Ejecutar una etapa y registrar sus productos con las dependencias verificadas."""
from pathlib import Path
import argparse,json,sys

RAIZ=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RAIZ/'src'))
from movilidad_teide.flujos.etapas_registradas import ejecutar_etapa
from movilidad_teide.configuracion.registro import abrir_ejecucion,resumen_ejecucion
from movilidad_teide.configuracion.contratos_etapas import ETAPAS


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='comando',required=True)
    a=sub.add_parser('ejecutar');a.add_argument('--root',type=Path,default=RAIZ);a.add_argument('--registro',type=Path,required=True)
    a.add_argument('--etapa',choices=list(ETAPAS),required=True);a.add_argument('--accion',choices=['calcular','registrar_datos_fijados','comprobar','consultar','ejecutar_motor','comparar'])
    a.add_argument('--copert',type=Path);a.add_argument('--intercambio',type=Path)
    a=sub.add_parser('estado');a.add_argument('--root',type=Path,default=RAIZ);a.add_argument('--registro',type=Path,required=True)
    args=p.parse_args()
    try:
        if args.comando=='ejecutar':
            result=ejecutar_etapa(args.root,args.registro,args.etapa,accion=args.accion,copert=args.copert,intercambio=args.intercambio)
        else:result=resumen_ejecucion(abrir_ejecucion(args.root,args.registro))
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,AssertionError) as exc:p.exit(2,'La etapa no se ha completado: '+str(exc)+'\n')


if __name__=='__main__':main()
