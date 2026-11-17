"""Reconstruir demanda desde Bronze y comprobar su equivalencia con Silver."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from movilidad_teide.flujos.preparacion_demanda import preparar,comparar

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='accion',required=True)
    for action in ['preparar','comparar','reproducir']:
        a=s.add_parser(action);a.add_argument('--root',type=Path,default=ROOT);a.add_argument('--destino',type=Path,required=True)
        if action=='comparar':a.add_argument('--resultados',type=Path,required=True)
    x=p.parse_args()
    if x.accion=='preparar':result=preparar(x.root,x.destino)
    elif x.accion=='comparar':result=comparar(x.root,x.resultados,x.destino)
    else:
        preparar(x.root,x.destino);result=comparar(x.root,x.destino,x.destino/'comprobacion')
    if x.accion=='preparar':
        result={k:result[k] for k in ['visitas_sin_y_con','tablas_producidas','origenes','fraccion_coche','energia_recalculada']}
        result['metadatos']=str(x.destino/'metadatos.json')
    print(json.dumps(result,ensure_ascii=False,indent=2))
