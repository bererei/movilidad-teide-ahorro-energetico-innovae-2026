"""Verificar todas las copias de una referencia congelada, sin modificarla."""
from pathlib import Path
from collections import Counter
import argparse,hashlib,json


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def verificar(captura):
    captura=Path(captura).resolve()
    manifest=captura/'MANIFIESTO_CONGELACION.json';info=json.loads(manifest.read_text());counts=Counter();total=0
    expected=set()
    for row in info['archivos']:
        name=Path(row['raiz'])/row['ruta'];path=captura/name
        if name.is_absolute() or '..' in name.parts or not path.resolve().is_relative_to(captura) or path.is_symlink():
            raise ValueError('La captura contiene una ruta no independiente: '+str(name))
        if not path.is_file() or path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:
            raise ValueError('Archivo congelado ausente o alterado: '+str(name))
        expected.add(str(name));counts[row['raiz']]+=1;total+=row['bytes']
    actual={str(p.relative_to(captura)) for area in counts for p in (captura/area).rglob('*') if p.is_file()}
    if actual!=expected:raise ValueError('El inventario y los archivos congelados difieren.')
    return {'correcto':True,'commit_de_origen':info['commit_de_origen'],'archivos_verificados':len(expected),'bytes':total,'por_raiz':dict(counts),'manifiesto_sha256':sha(manifest),'copias_fisicas_sin_enlaces':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--captura',type=Path,required=True);p.add_argument('--destino',type=Path,required=True)
    args=p.parse_args()
    if args.destino.resolve().is_relative_to(args.captura.resolve()):raise ValueError('La evidencia debe quedar fuera de la captura.')
    if args.destino.exists():raise FileExistsError('No sobrescribo una comprobación anterior.')
    result=verificar(args.captura);args.destino.parent.mkdir(parents=True,exist_ok=True);args.destino.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
