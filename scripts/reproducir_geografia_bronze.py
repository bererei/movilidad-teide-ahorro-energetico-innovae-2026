"""Reconstruir recorridos y perfiles desde Bronze; contrastar después con Silver."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from movilidad_teide.flujos.preparacion_geografia import preparar,comparar

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);actions=parser.add_subparsers(dest='accion',required=True)
    for name in ['preparar','comparar','reproducir']:
        action=actions.add_parser(name);action.add_argument('--root',type=Path,default=ROOT);action.add_argument('--destino',type=Path,required=True)
        if name=='comparar':action.add_argument('--resultados',type=Path,required=True)
    args=parser.parse_args()
    if args.accion=='preparar':
        metadata=preparar(args.root,args.destino)
        result={k:metadata[k] for k in ['visitas_sin_y_con','tablas_producidas','itinerarios_extraidos','energia_recalculada']}
        result['metadatos']=str(args.destino/'metadatos.json')
    elif args.accion=='comparar':result=comparar(args.root,args.resultados,args.destino)
    else:
        preparar(args.root,args.destino);result=comparar(args.root,args.destino,args.destino/'comprobacion')
    print(json.dumps(result,ensure_ascii=False,indent=2))
