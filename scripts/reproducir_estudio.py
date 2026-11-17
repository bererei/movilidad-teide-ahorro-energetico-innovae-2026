"""Reconstruyo la ordenación vigente y compruebo su equivalencia con la referencia."""
from pathlib import Path
import argparse
import sys

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / 'src'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=RAIZ)
    parser.add_argument('--destino', type=Path, required=True)
    parser.add_argument('--referencia', choices=['vigente','historica'], default='vigente',
                        help='Vigente: ordenación recomendada de 2028. Histórica: reconstrucción de la edición de noviembre de 2026 anterior a esta ordenación.')
    args = parser.parse_args()
    if args.referencia=='vigente':
        from movilidad_teide.flujos.ordenacion_vigente import reproducir_ordenacion
        _, controles = reproducir_ordenacion(args.root, args.destino)
    else:
        import subprocess,os
        legacy=args.root/'desarrollo/antecedentes/20261112_pre_implantacion_701de68/repositorio_original'
        if not legacy.is_dir():
            parser.error('Esta entrega contiene la referencia vigente. La reconstrucción anterior requiere su raíz archivada de desarrollo.')
        subprocess.run([sys.executable,'-B',str(legacy/'scripts/reproducir_estudio.py'),'--referencia','historica','--destino',str(args.destino.resolve())],cwd=legacy,env={**os.environ,'PYTHONPATH':str(legacy/'src')},check=True)
        sys.exit(0)
    print(controles.to_string(index=False))
