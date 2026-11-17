"""Copiar el núcleo común y preparar sus ZIP sin publicar ni hacer commits."""
from pathlib import Path
import argparse,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from movilidad_teide.publicacion.seleccion import preparar
from movilidad_teide.publicacion.empaquetado import empaquetar
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--destino',type=Path,required=True);p.add_argument('--sin-paquetes',action='store_true');p.add_argument('--ensayo-local',action='store_true',help='Permite probar localmente la selección completa con condiciones pendientes; no habilita su difusión.');p.add_argument('--gitignore-publico',type=Path,help='Política .gitignore de la carpeta pública; por defecto, la de --root.');a=p.parse_args()
    tree=preparar(a.root,a.destino,gitignore_publico=a.gitignore_publico,ensayo_local=a.ensayo_local)
    if not a.sin_paquetes:empaquetar(tree,a.destino/'paquetes',ensayo_local=a.ensayo_local)
    print('Copia preparada y verificada:',tree)
