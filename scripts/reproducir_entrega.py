"""Interfaz compatible; las acciones ejecutan directamente el árbol Medallion común."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('accion',choices=['verificar','balance','recursos','factores','balance-copert']);p.add_argument('--destino',type=Path);p.add_argument('--resultados-copert',type=Path);a=p.parse_args()
    if a.accion=='verificar':
        from movilidad_teide.publicacion.nucleo import verificar
        print(json.dumps(verificar(ROOT),ensure_ascii=False));return
    if a.destino is None:p.error('Indicar un destino nuevo.')
    if a.accion=='balance':
        from movilidad_teide.flujos.ordenacion_vigente import reproducir_ordenacion
        _,result=reproducir_ordenacion(ROOT,a.destino);print(result.to_string(index=False))
    elif a.accion=='recursos':
        from movilidad_teide.informe.vigente import generar_informe_vigente
        print(generar_informe_vigente(ROOT,a.destino))
    elif a.accion=='balance-copert':
        from movilidad_teide.flujos.copert_publico import verify_study
        print(verify_study(ROOT,a.resultados_copert or ROOT/'data/silver/copert/ejecuciones',a.destino))
    else:
        from movilidad_teide.vehiculos.copert_publico import compare_package
        print(compare_package(ROOT/'data/bronze/copert/entradas_publicas',ROOT/'data/silver/copert/ejecuciones',reference=ROOT/'data/silver/copert/referencia_comparacion',destination=a.destino))
if __name__=='__main__':main()
