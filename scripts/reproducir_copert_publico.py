"""Ejecutar CSV nativos, verificar factores y reproducir el balance del estudio."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from movilidad_teide.vehiculos.copert_publico import execute_package,compare_package,import_workbook
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='accion',required=True)
    a=s.add_parser('crear-entrada');a.add_argument('--csv',type=Path,required=True);a.add_argument('--xlsx',type=Path,required=True)
    a=s.add_parser('ejecutar');a.add_argument('--entradas',type=Path,required=True);a.add_argument('--destino',type=Path,required=True);a.add_argument('--copert',type=Path,required=True);a.add_argument('--timeout',type=int,default=180);a.add_argument('--reanudar',action='store_true');a.add_argument('--referencia',type=Path,required=True)
    a=s.add_parser('verificar');a.add_argument('--entradas',type=Path,required=True);a.add_argument('--resultados',type=Path,required=True);a.add_argument('--referencia',type=Path,required=True);a.add_argument('--destino',type=Path,required=True)
    a=s.add_parser('verificar-estudio');a.add_argument('--root',type=Path,default=ROOT);a.add_argument('--resultados-copert',type=Path,required=True);a.add_argument('--destino',type=Path,required=True)
    x=p.parse_args()
    if x.accion=='crear-entrada':
        if x.xlsx.exists():raise FileExistsError('No sobrescribo una entrada existente.')
        import_workbook(x.csv,x.xlsx);print('Entrada XLSX creada desde sus CSV:',x.xlsx)
    elif x.accion=='ejecutar':print(json.dumps(execute_package(x.entradas,x.destino,x.copert,x.timeout,x.reanudar,reference=x.referencia),ensure_ascii=False,indent=2))
    elif x.accion=='verificar':print(json.dumps(compare_package(x.entradas,x.resultados,reference=x.referencia,destination=x.destino),ensure_ascii=False,indent=2))
    else:
        from movilidad_teide.flujos.copert_publico import verify_study
        print(json.dumps(verify_study(x.root,x.resultados_copert,x.destino),ensure_ascii=False,indent=2))
