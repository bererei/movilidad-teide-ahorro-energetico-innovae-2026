"""Exporto recursos vigentes; la edición histórica se selecciona explícitamente."""
from pathlib import Path
import argparse
import json
import sys

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=RAIZ)
    parser.add_argument('--destino', type=Path, required=True)
    parser.add_argument('--compilar', action='store_true')
    parser.add_argument('--referencia', choices=['vigente','historica'], default='vigente')
    args = parser.parse_args()
    if args.referencia=='vigente':
        from movilidad_teide.informe.vigente import generar_informe_vigente
        from movilidad_teide.informe.compilacion import compilar_pdf
        resultado=generar_informe_vigente(args.root,args.destino)
        if args.compilar:resultado['pdf']=str(compilar_pdf(args.destino))
    else:
        parser.error('Las ediciones anteriores requieren su código y raíz archivados en desarrollo. La entrega actual utiliza --referencia vigente y los cuadernos 00–07.')
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
