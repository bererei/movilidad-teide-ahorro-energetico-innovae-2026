"""Entradas CSV completas de COPERT y comprobación de ejecuciones nuevas.

El paquete contiene las tablas nativas y sus tipos. Ejecutarlo no requiere la
plantilla ni las consultas de desarrollo; esas fuentes solo intervienen al
crear el paquete y su referencia de comparación.
"""
from pathlib import Path
from collections import Counter
import csv,datetime,hashlib,json,math,shutil,tempfile
import numpy as np
import pandas as pd
from openpyxl import Workbook,load_workbook
from .copert_entrada import prepare_reference_case,prepare_car_reference_case
from .copert_ejecucion import run_reference_case
from .copert_resultados import read_car_hot_ec,read_hot_ec

FIELDS=['Category','Fuel','Segment','Euro Standard']
COACH=('Buses','Diesel','Coaches Standard <=18 t','Euro VI D/E')
KEYS=FIELDS+['year','driving_mode','speed_kmh','slope_class_pct','load_fraction','primary_control_fraction','consulta']
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,value):Path(p).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def new_directory(p):
    p=Path(p).resolve()
    if p.exists() and any(p.iterdir()):raise FileExistsError('La carpeta de salida debe estar vacía.')
    p.mkdir(parents=True,exist_ok=True);return p
def relative_file(root,name):
    p=Path(name)
    if p.is_absolute() or '..' in p.parts:raise ValueError('El paquete debe utilizar rutas relativas sin ascensos.')
    return Path(root)/p
def typed(value):
    if value is None:return 'vacio',''
    if isinstance(value,bool):return 'booleano','true' if value else 'false'
    if isinstance(value,int):return 'entero',str(value)
    if isinstance(value,float):
        if not math.isfinite(value):raise ValueError('Valor no finito en entrada nativa.')
        return 'decimal',repr(value)
    if isinstance(value,str):
        if value.startswith('='):raise ValueError('Las entradas públicas no admiten fórmulas.')
        return 'texto',value
    raise ValueError('Tipo de celda no admitido: '+str(type(value)))
def restore(kind,value):
    if kind=='vacio':
        if value!='':raise ValueError('Celda vacía con contenido.')
        return None
    if kind=='texto':return value
    if kind=='booleano':
        if value not in ['true','false']:raise ValueError('Booleano inválido.')
        return value=='true'
    if kind=='entero':return int(value)
    if kind=='decimal':
        n=float(value)
        if not math.isfinite(n):raise ValueError('Número no finito.')
        return n
    raise ValueError('Tipo de celda desconocido.')

def export_workbook(path,folder):
    """Cada hoja se conserva como una matriz CSV legible; los tipos son explícitos."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    book=load_workbook(path,read_only=True,data_only=False);spec=[]
    try:
        for i,sheet in enumerate(book):
            name=f'{i+1:02d}_{sheet.title}.csv';types=[]
            with (folder/name).open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.writer(f,delimiter=';')
                for row in sheet.values:
                    cells=[typed(x) for x in row]
                    writer.writerow([v for k,v in cells]);types.append([k for k,v in cells])
            spec.append({'hoja':sheet.title,'archivo':name,'tipos':types})
    finally:book.close()
    dump(folder/'estructura.json',spec)
    return spec

def import_workbook(folder,path):
    folder=Path(folder);spec=json.loads((folder/'estructura.json').read_text())
    if not spec or len({x['hoja'] for x in spec})!=len(spec):raise ValueError('Hojas ausentes o duplicadas.')
    book=Workbook();book.remove(book.active)
    for s in spec:
        with relative_file(folder,s['archivo']).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f,delimiter=';'))
        if len(rows)!=len(s['tipos']):raise ValueError('Cambió el número de filas de '+s['hoja'])
        sheet=book.create_sheet(s['hoja'])
        for row,kinds in zip(rows,s['tipos']):
            if len(row)!=len(kinds):raise ValueError('Cambió el número de columnas de '+s['hoja'])
            sheet.append([restore(k,v) for k,v in zip(kinds,row)])
    book.save(path);book.close()

def normalize(path,config,ident,kind):
    if kind=='explicit_bus_reference':
        rows=[]
        for vehicle in config['vehicles']:
            z=read_hot_ec(path,{'vehicle':vehicle,'year':config['year'],'slope_pct':config['slope_pct'],'vehicle_km':config['vehicle_km_per_category']})
            rows.append({**dict(zip(FIELDS,vehicle)),**z,'year':config['year'],'driving_mode':'rural','speed_kmh':config['rural_speed_kmh'],
                'slope_class_pct':config['slope_pct'],'load_fraction':config['load_fraction'],'primary_control_fraction':np.nan,'consulta':ident})
    else:
        rows=[]
        for z in read_car_hot_ec(path,config):
            rows.append({**dict(zip(FIELDS,z['vehicle'])),**{k:v for k,v in z.items() if k!='vehicle'},'slope_class_pct':np.nan,'load_fraction':np.nan,
                'primary_control_fraction':np.nan if config.get('energy_condition',{}).get('primary_fuel_share') is None else float(config['energy_condition']['primary_fuel_share']),'consulta':ident})
    return pd.DataFrame(rows)

def create_package(root,destination,reference_destination):
    root=Path(root).resolve()
    inputs=Path(destination).resolve();reference=Path(reference_destination).resolve()
    if inputs==reference or inputs.is_relative_to(reference) or reference.is_relative_to(inputs):
        raise ValueError('Las entradas Bronze y las referencias Silver deben estar separadas.')
    out=new_directory(inputs);refout=new_directory(reference)
    selected=pd.read_csv(root/'docs/auditoria_reproducibilidad/seleccion_consultas_copert.csv',sep=';')
    selected=selected[selected['Incluir con preparador actual']].copy()
    template=root/'data/bronze/copert/2026-10-19/Export_Input_Structure_to_EXCEL_Spain.xlsx'
    catalog=root/'data/bronze/copert/2026-10-19/Stock_Configuration_Spain.csv'
    cases=[];expected=[];origins=[];vehicles=[];summary=[]
    with tempfile.TemporaryDirectory(prefix='teide_public_inputs_') as tmp:
        tmp=Path(tmp)
        for raw in selected['Ejecución original']:
            previous=root/raw;prep=json.loads((previous/'preparacion.json').read_text());c=prep['configuration'];kind=prep['case_kind']
            bus=kind=='explicit_bus_reference';control=c.get('energy_condition',{}).get('primary_fuel_share');speed=c.get('speed_kmh',c.get('rural_speed_kmh'))
            if bus:
                ident=f'autocar_carga{round(c["load_fraction"]*100):03d}_pendiente'+('m' if c['slope_pct']<0 else 'p')+f'{abs(c["slope_pct"]):02d}'
                chosen=[COACH]
            else:
                ident=('turismos' if control is None else 'multienergia')+f'_velocidad{speed:03d}'+('' if control is None else f'_control{round(control*100):03d}')
                chosen=[tuple(x) for x in c['vehicles']]
            working=tmp/ident
            if bus:
                new=prepare_reference_case(template,catalog,working,chosen,slope_pct=c['slope_pct'],speed_kmh=speed,load_fraction=c['load_fraction'],year=c['year'],mean_activity_km=c['mean_activity_km'])
            else:
                candidates=tmp/(ident+'_vehiculos.csv')
                with candidates.open('w',encoding='utf-8-sig',newline='') as f:
                    w=csv.writer(f,delimiter=';');w.writerow(FIELDS);w.writerows(chosen)
                new=prepare_car_reference_case(template,catalog,candidates,working,speed_kmh=speed,mean_activity_km=c['mean_activity_km'],mode_shares=c['mode_shares'],year=c['year'],fuel_year=c['fuel_year_specification'],primary_fuel_share=control)
            csv_folder=out/'tablas'/ident;export_workbook(working/'entrada.xlsx',csv_folder)
            roundtrip=tmp/(ident+'_desde_csv.xlsx');import_workbook(csv_folder,roundtrip)
            a=load_workbook(working/'entrada.xlsx',read_only=True,data_only=False);b=load_workbook(roundtrip,read_only=True,data_only=False)
            try:
                assert a.sheetnames==b.sheetnames
                for name in a.sheetnames:assert list(a[name].values)==list(b[name].values),(ident,name)
            finally:a.close();b.close()
            cfg=new['configuration']
            for k,value in c.items():
                if k=='vehicles':continue
                assert cfg[k]==value,(ident,k,cfg[k],value)
            if not bus:assert cfg['vehicles']==c['vehicles']
            old=normalize(previous/'resultado.xlsx',c,ident,kind)
            if bus:
                mask=np.ones(len(old),bool)
                for key,value in zip(FIELDS,COACH):mask &= old[key].eq(value)
                old=old[mask].copy();assert len(old)==1
            expected.append(old)
            cases.append({'nombre':ident,'tipo':kind,'carpeta_csv':'tablas/'+ident,'configuracion':cfg})
            summary.append({'Consulta':ident,'Tipo':'Autocar' if bus else 'Turismos','Año':c['year'],'Velocidad técnica (km/h)':speed,
                'Pendiente (%)':c.get('slope_pct',np.nan),'Carga técnica (fracción)':c.get('load_fraction',np.nan),'Control primario técnico':control,
                'Actividad técnica (km)':c['mean_activity_km'],'Categorías consultadas':len(chosen),
                'Uso':'Preparación de malla; no velocidad de operación' if not bus and speed in [60,100] else ('Comprobación de linealidad' if control==.37 else 'Factor utilizado en el consumo')})
            vehicles.extend({'Consulta':ident,**dict(zip(FIELDS,v))} for v in chosen)
            origins.append({'consulta_publica':ident,'origen_desarrollo':raw,'entrada_origen_sha256':digest(previous/'entrada.xlsx'),
                'salida_origen_sha256':digest(previous/'resultado.xlsx'),'entrada_nueva_sin_estilos_sha256':digest(roundtrip)})
            print('Entrada CSV preparada:',ident,flush=True)
    pd.DataFrame(summary).to_csv(out/'consultas.csv',sep=';',index=False,encoding='utf-8-sig')
    pd.DataFrame(vehicles).to_csv(out/'vehiculos.csv',sep=';',index=False,encoding='utf-8-sig')
    pd.concat(expected,ignore_index=True).to_csv(refout/'factores_esperados.csv',sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
    reference_hash=digest(refout/'factores_esperados.csv')
    dump(refout/'manifiesto.json',{'version':'1.1','capa':'Silver','archivos_sha256':{'factores_esperados.csv':reference_hash}})
    manifest={'version':'1.1','capa':'Bronze','referencia_comparacion_sha256':reference_hash,'copert_version':'5.10.1','consultas':cases,'alcance':'Factores técnicos Hot; no actividad anual ni visitas adicionales',
        'distribucion':'Todos los datos en release; código y documentación en repositorio','csv':'UTF-8 con BOM, punto y coma, punto decimal; tipos explícitos en estructura.json',
        'archivos_sha256':{str(p.relative_to(out)):digest(p) for p in sorted(out.rglob('*')) if p.is_file()}}
    dump(out/'manifiesto.json',manifest)
    return manifest,origins

def verify_package(folder):
    root=Path(folder);m=json.loads((root/'manifiesto.json').read_text())
    if len(m['consultas'])!=34 or len({c['nombre'] for c in m['consultas']})!=34:raise ValueError('Se requieren las34consultas de referencia únicas.')
    for name,h in m['archivos_sha256'].items():
        p=relative_file(root,name)
        if not p.is_file() or digest(p)!=h:raise ValueError('Entrada pública ausente o modificada: '+name)
    return m

def load_reference(package,reference):
    """Las salidas esperadas se leen desde Silver; no son entradas de COPERT."""
    inputs=Path(package).resolve();m=verify_package(inputs)
    if reference is None:raise ValueError('Indique --referencia con la carpeta Silver de comparación.')
    ref=Path(reference).resolve()
    if ref==inputs or ref.is_relative_to(inputs) or inputs.is_relative_to(ref):
        raise ValueError('La referencia Silver debe estar separada de las entradas Bronze.')
    manifest=json.loads((ref/'manifiesto.json').read_text())
    if manifest.get('capa')!='Silver':raise ValueError('La referencia debe identificarse como Silver.')
    for name,h in manifest['archivos_sha256'].items():
        p=relative_file(ref,name)
        if not p.is_file() or digest(p)!=h:raise ValueError('Referencia ausente o modificada: '+name)
    p=ref/'factores_esperados.csv'
    if digest(p)!=m.get('referencia_comparacion_sha256'):raise ValueError('La referencia Silver no corresponde al paquete Bronze.')
    return pd.read_csv(p,sep=';',float_precision='round_trip')

def execute_package(package,destination,executable,timeout_s=180,resume=False,reference=None):
    package=Path(package).resolve();m=verify_package(package)
    expected=load_reference(package,reference)
    source_info={'manifiesto_sha256':digest(package/'manifiesto.json'),'referencia_sha256':m['referencia_comparacion_sha256'],'copert_sha256':digest(executable),'version_requerida':m['copert_version']}
    if resume:
        out=Path(destination).resolve()
        if json.loads((out/'fuente_paquete.json').read_text())!=source_info:raise ValueError('No coincide el paquete o el ejecutable de la ejecución que se quiere retomar.')
    else:
        out=new_directory(destination);dump(out/'fuente_paquete.json',source_info)
    records=[];frames=[]
    for i,case in enumerate(m['consultas'],1):
        p=out/'consultas'/case['nombre']
        if p.exists():
            if not resume:raise FileExistsError('La consulta ya existe.')
            prep=json.loads((p/'preparacion.json').read_text());run=json.loads((p/'ejecucion.json').read_text())
            if (prep['configuration']!=case['configuracion'] or run.get('status')!='exported' or run.get('returncode')!=0
                or digest(p/'entrada.xlsx')!=run['input_sha256'] or digest(p/'resultado.xlsx')!=run['output_sha256']):
                raise ValueError('No se reutiliza una consulta incompleta, fallida o modificada: '+case['nombre'])
            print(f'Consulta {i}/{len(m["consultas"])} ya ejecutada: {case["nombre"]}',flush=True)
        else:
            p.mkdir(parents=True,exist_ok=False)
            import_workbook(package/case['carpeta_csv'],p/'entrada.xlsx')
            dump(p/'preparacion.json',{'case_kind':case['tipo'],'configuration':case['configuracion'],'input_sha256':digest(p/'entrada.xlsx'),
                'fuente':'Entradas públicas CSV completas; no requiere proyectoCOPERT heredado'})
            print(f'COPERT {i}/{len(m["consultas"])}: {case["nombre"]}',flush=True)
            run=run_reference_case(p,Path(executable),timeout_s=timeout_s)
        actual=normalize(p/'resultado.xlsx',case['configuracion'],case['nombre'],case['tipo'])
        wanted=expected[expected.consulta.eq(case['nombre'])]
        compared=wanted.merge(actual,on=KEYS,how='outer',suffixes=('_esperado','_nuevo'),indicator=True,validate='one_to_one')
        if compared._merge.ne('both').any():raise ValueError('La consulta nueva tiene factores ausentes o adicionales: '+case['nombre'])
        np.testing.assert_allclose(compared.hot_ec_mj_per_km_nuevo,compared.hot_ec_mj_per_km_esperado,rtol=0,atol=1e-12)
        frames.append(actual)
        records.append({'consulta':case['nombre'],'estado':run['status'],'entrada_sha256':run['input_sha256'],'salida_sha256':run['output_sha256'],
            'inicio_utc':run['started_utc'],'fin_utc':run['finished_utc'],'ejecutable_sha256':run['executable_sha256']})
        dump(out/'ejecuciones.json',records)
    result=pd.concat(frames,ignore_index=True)
    result.to_csv(out/'factores_nuevos.csv',sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
    return compare_package(package,out,result,reference=reference)

def compare_package(package,output,result=None,reference=None,destination=None):
    package=Path(package);source=Path(output);m=verify_package(package)
    expected=load_reference(package,reference)
    out=new_directory(destination) if destination is not None else source
    executed_here=result is not None
    if result is None:
        normalized=source/'factores_nuevos.csv'
        if not normalized.exists() and source.name=='ejecuciones':normalized=source.parent/'factores/factores_nuevos.csv'
        result=pd.read_csv(normalized,sep=';',float_precision='round_trip')
    if result.duplicated(KEYS).any() or expected.duplicated(KEYS).any():raise ValueError('Factor repetido; no se admite una comparación ambigua.')
    z=expected.merge(result,on=KEYS,how='outer',suffixes=('_esperado','_nuevo'),indicator=True,validate='one_to_one')
    if z._merge.ne('both').any():raise ValueError('Faltan o sobran factores en la ejecución nueva.')
    assert z.unit_esperado.eq('MJ/km').all() and z.unit_nuevo.eq('MJ/km').all()
    delta=np.abs(z.hot_ec_mj_per_km_nuevo-z.hot_ec_mj_per_km_esperado)
    np.testing.assert_allclose(z.hot_ec_mj_per_km_nuevo,z.hot_ec_mj_per_km_esperado,rtol=0,atol=1e-12)
    checks=z[KEYS].copy();checks['factor_esperado_mj_km']=z.hot_ec_mj_per_km_esperado;checks['factor_nuevo_mj_km']=z.hot_ec_mj_per_km_nuevo;checks['diferencia_absoluta_mj_km']=delta
    checks.to_csv(out/'comparacion_factores.csv',sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
    main=result[result.consulta.str.startswith('turismos_')].copy()
    main['slope_correction']='Factor nativo de turismos sin corrección propia de pendiente'
    main['raw_case']=main.consulta.map(lambda x:'consultas/'+x);main.to_parquet(out/'factores_turismos.parquet',index=False)
    multi=result[result.consulta.str.startswith('multienergia_')].copy()
    # Comprobar primero el control intermedio; conservar BEV una sola vez.
    mk=FIELDS+['year','driving_mode','speed_kmh']
    full=multi.pivot(index=mk,columns='primary_control_fraction',values='hot_ec_mj_per_km')
    np.testing.assert_allclose(full[.37],.63*full[0.]+.37*full[1.],rtol=0,atol=1e-12)
    ends=multi[multi.primary_control_fraction.isin([0.,1.])].copy()
    ends=ends[ends.Fuel.ne('Battery electric')|ends.primary_control_fraction.eq(1.)].copy()
    ev=ends.Fuel.eq('Battery electric');ends.loc[ev,'primary_control_fraction']=np.nan
    ends['linearity_verified']=True;ends['reference_kind']=np.where(ev,'BEV nativo','Extremos de control nativo')
    ends['raw_case']=ends.consulta.map(lambda x:'consultas/'+x);ends.to_parquet(out/'factores_multienergia.parquet',index=False)
    bus=result[result.consulta.str.startswith('autocar_')].copy();bus['rural_speed_kmh']=bus.speed_kmh
    bus['raw_case']=bus.consulta.map(lambda x:'consultas/'+x);bus.to_parquet(out/'factores_autocar.parquet',index=False)
    summary={'consultas':len(m['consultas']),'factores_comparados':len(z),'maxima_diferencia_mj_km':float(delta.max()),'tolerancia_absoluta_mj_km':1e-12,
        'motor_copert_ejecutado':True,'motor_copert_ejecutado_en_esta_llamada':executed_here,'entradas_desde_csv':True,'consultas_de_una_sola_categoria_autocar':14,
        'filas_biblioteca_turismos':len(main),'filas_biblioteca_multienergia':len(ends),'filas_biblioteca_autocar':len(bus),
        'control_linealidad_verificado':True,'parametros_actividad_anual_modificados':False}
    dump(out/'verificacion_copert.json',summary);return summary
