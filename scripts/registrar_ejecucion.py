"""Preparar o reabrir un registro de configuración, sin ejecutar el cálculo del estudio."""
from pathlib import Path
import argparse
import json
import sys

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / 'src'))

from movilidad_teide.configuracion.registro import iniciar_ejecucion, abrir_ejecucion, resumen_ejecucion
from movilidad_teide.configuracion.parametros_tipos import ErrorParametros


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='accion', required=True)
    crear = sub.add_parser('iniciar', help='Guardar configuración y comprobar entradas en una carpeta nueva.')
    crear.add_argument('--root', type=Path, default=RAIZ)
    crear.add_argument('--destino', type=Path, required=True, help='Ruta relativa a la raíz o ruta externa absoluta.')
    crear.add_argument('--modo', choices=['consulta', 'reproduccion'], default='consulta')
    crear.add_argument('--id', dest='identificador')
    abrir = sub.add_parser('abrir', help='Leer un registro ya creado con un proceso de Python nuevo.')
    abrir.add_argument('--root', type=Path, default=RAIZ)
    abrir.add_argument('--registro', type=Path, required=True)
    abrir.add_argument('--comprobar-referencias', action='store_true', help='Contrastar también las referencias Gold, como comprobación separada.')
    args = parser.parse_args()
    try:
        if args.accion == 'iniciar':
            destino = iniciar_ejecucion(args.root, args.destino, modo=args.modo, identificador=args.identificador)
            # La reapertura se ofrece como acción separada; no ocultar una segunda lectura de todos los datos.
            print(json.dumps(dict(registro=str(destino / 'registro_ejecucion.json'),
                                  estado='preparada_sin_calculo', modo_solicitado=args.modo), ensure_ascii=False, indent=2))
        else:
            datos = abrir_ejecucion(args.root, args.registro, comprobar_referencias=args.comprobar_referencias)
            print(json.dumps(resumen_ejecucion(datos), ensure_ascii=False, indent=2))
    except (ErrorParametros, OSError, ValueError, KeyError) as exc:
        parser.exit(2, 'No se puede completar el registro: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
