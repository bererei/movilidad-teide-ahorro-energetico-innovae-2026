"""vehiculos: copert resultados. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import math
from pathlib import Path
from openpyxl import load_workbook
from movilidad_teide.vehiculos.copert_cli_tipos import VEHICLE
from movilidad_teide.vehiculos.copert_cli_tipos import CAR_MODES


def read_hot_ec(output: str | Path, configuration: dict) -> dict:
    """Leer EC_HOT en TJ y dividir por la actividad rural acreditada, una sola vez."""
    activity = float(configuration['vehicle_km'])
    if not math.isfinite(activity) or activity <= 0:
        raise ValueError('Actividad no positiva o desconocida: no se obtiene un factor.')
    book = load_workbook(output, read_only=True, data_only=True)
    try:
        units = dict(book['SHEETS'].iter_rows(min_row=2, max_col=2, values_only=True))
        if units.get('EC_HOT') != '[TJ]':
            raise ValueError('Unidad de EC_HOT inesperada; no se aplica una conversión implícita.')
        rows = list(book['EC_HOT'].values)
        header = list(rows[0])
        matches = [r for r in rows[1:] if tuple(r[:4]) == tuple(configuration['vehicle'])]
        if len(matches) != 1 or matches[0][4:6] != ('Hot', 'EC'):
            raise ValueError('Resultado Hot EC ambiguo o de otro vehículo/indicador.')
        row = matches[0]
        year = configuration['year']
        rural = float(row[header.index(f'{year}_R')])
        total = float(row[header.index(f'{year}_T')])
        others = [float(row[header.index(f'{year}_{mode}')]) for mode in ('PK', 'OP', 'H')]
        if (not math.isfinite(rural) or rural < 0 or not math.isfinite(total)
                or any(not math.isfinite(v) or v != 0 for v in others)
                or not math.isclose(rural, total, rel_tol=0, abs_tol=1e-12)):
            raise ValueError('Revisar energía, componentes y reparto exclusivamente rural.')
        return {'hot_ec_tj': rural, 'hot_ec_mj': rural * 1_000_000,
                'vehicle_km': activity, 'hot_ec_mj_per_km': rural * 1_000_000 / activity,
                'slope_class_pct': configuration['slope_pct'], 'unit': 'MJ/km',
                'conversion': 'EC_HOT[TJ] × 1 000 000 / (STOCK × MEAN_ACTIVITY)',
                'source_sheet': 'EC_HOT', 'copert_version': '5.10.1'}
    finally:
        book.close()


def read_hot_factor(path: str | Path, year: int = 2028, vehicle=VEHICLE) -> float:
    """Leer HOT_EC de la exportación de factores, que ya está en MJ/km."""
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        units = dict(book['SHEETS'].iter_rows(min_row=2, max_col=2, values_only=True))
        if units.get('HOT_EC') != '[MJ/km]':
            raise ValueError('La exportación de factores debe identificar HOT_EC en MJ/km.')
        rows = list(book['HOT_EC'].values)
        header = [str(v).split('\n')[0] for v in rows[0]]
        matches = [r for r in rows[1:] if tuple(r[:4]) == tuple(vehicle)]
        if len(matches) != 1 or matches[0][4] != 'EC':
            raise ValueError('Factor Hot EC ambiguo o de otro vehículo.')
        value = float(matches[0][header.index(f'{year}_R')])
        if not math.isfinite(value) or value <= 0:
            raise ValueError('El factor de referencia debe ser finito y positivo.')
        return value
    finally:
        book.close()

def make_base_reference(project: str | Path, template: str | Path, gui_factors: str | Path,
                         gui_results: str | Path, baseline_cli_results: str | Path,
                         declared_speed_kmh: float = 34.0, year: int = 2028) -> dict:
    """Contrastar el mismo estado GUI/CLI sin inventar las hojas omitidas.

    La velocidad se conserva como declarada; no se afirma haberla leído del
    Excel. La actividad se deduce de dos exportaciones y la CLI reproduce la
    energía del mismo caso base. Las huellas fijan el estado reproducible.
    """
    from movilidad_teide.trazabilidad import file_hash
    from movilidad_teide.vehiculos.copert_entrada import vehicle_value
    factor = read_hot_factor(gui_factors, year)
    book = load_workbook(template, read_only=True, data_only=True)
    try:
        baseline_slope = vehicle_value(book, 'RURAL_ROAD_SLOPE', year) * 100
    finally:
        book.close()
    unit_configuration = {'vehicle_km': 1.0, 'vehicle': list(VEHICLE), 'year': year, 'slope_pct': baseline_slope}
    gui_energy = read_hot_ec(gui_results, unit_configuration)['hot_ec_mj']
    cli_energy = read_hot_ec(baseline_cli_results, unit_configuration)['hot_ec_mj']
    if not math.isclose(gui_energy, cli_energy, rel_tol=0, abs_tol=1e-9):
        raise ValueError('El estado base CLI no reproduce la energía GUI; no heredar parámetros.')
    vehicle_km = gui_energy / factor
    if not math.isfinite(vehicle_km) or vehicle_km <= 0:
        raise ValueError('Actividad de referencia no positiva.')
    return {'year': year, 'vehicle': list(VEHICLE), 'vehicle_km': vehicle_km,
            'baseline_slope_pct': baseline_slope, 'baseline_gui_factor_mj_km': factor,
            'baseline_gui_energy_mj': gui_energy, 'baseline_cli_energy_mj': cli_energy,
            'baseline_cli_matches_gui': True,
            'declared_rural_speed_kmh': declared_speed_kmh,
            'speed_source': 'Configuración manual declarada; heredada del .cop, no leída directamente del Excel',
            'project_sha256': file_hash(project), 'template_sha256': file_hash(template),
            'gui_factors_sha256': file_hash(gui_factors), 'gui_results_sha256': file_hash(gui_results),
            'baseline_cli_output_sha256': file_hash(baseline_cli_results),
            'normalization_source': 'EC_HOT GUI en MJ / HOT_EC GUI en MJ/km',
            'limitations': ['Las condiciones heredadas se fijan por el proyecto y su comparación numérica.',
                            'La velocidad declarada no queda acreditada por una hoja de entrada exportada.']}


def read_car_hot_ec(output, configuration):
    """Obtener MJ/km por modo desde EC_HOT, normalizando solo su actividad."""
    c=configuration;vehicles=[tuple(v) for v in c['vehicles']]
    book=load_workbook(output,read_only=True,data_only=True)
    try:
        units=dict(list(book['SHEETS'].values)[1:])
        if units.get('EC_HOT')!='[TJ]':raise ValueError('Unidad EC_HOT incompatible.')
        rows=list(book['EC_HOT'].values);header=list(rows[0]);body=rows[1:]
        if len(body)!=len(vehicles) or {tuple(r[:4]) for r in body}!=set(vehicles):
            raise ValueError('Resultados adicionales, ausentes o duplicados de vehículos.')
        results=[]
        for row in body:
            if tuple(row[4:6])!=('Hot','EC'):raise ValueError('Indicador distinto de Hot EC.')
            energies={mode:float(row[header.index(f'{c["year"]}_{native}')]) for mode,native in CAR_MODES.items()}
            total=float(row[header.index(f'{c["year"]}_T')])
            if (any(not math.isfinite(v) or v<0 for v in energies.values()) or not math.isfinite(total)
                    or not math.isclose(sum(energies.values()),total,rel_tol=0,abs_tol=1e-12)):
                raise ValueError('Energías o suma de modos incoherentes.')
            for mode,energy in energies.items():
                share=c['mode_shares'][mode]
                if share==0:
                    if energy!=0:raise ValueError('Energía presente en un modo sin actividad.')
                    continue
                km=c['stock_per_category']*c['mean_activity_km']*share
                factor=energy*1e6/km
                if not math.isfinite(factor) or factor<=0:raise ValueError('Factor ausente/no positivo.')
                results.append({'vehicle':list(row[:4]),'year':c['year'],'driving_mode':mode,
                    'speed_kmh':c['speed_kmh'],'fuel_year_specification':c['fuel_year_specification'],'mode_share':share,'normalization_vehicle_km':km,
                    'hot_ec_mj':energy*1e6,'hot_ec_mj_per_km':factor,'unit':'MJ/km',
                    'slope_correction':c['slope_correction']})
        return results
    finally:book.close()

def read_car_energy_breakdown(output, breakdown, configuration):
    """Contrastar el desglose TOTAL con EC_TOTAL, sin sumarlo otra vez a Hot EC.

    La exportación -oEB solo desglosa el total, que puede incluir frío. No
    inventar su reparto por modo ni presentarlo como desglose del componente Hot.
    """
    from movilidad_teide.trazabilidad import file_hash
    c=configuration;vehicles={tuple(v) for v in c['vehicles']}
    distance=c['stock_per_category']*c['mean_activity_km']
    if not math.isfinite(distance) or distance <= 0:raise ValueError('Actividad de normalización no válida.')
    book=load_workbook(output,read_only=True,data_only=True)
    try:
        units=dict(list(book['SHEETS'].values)[1:]);totals={};hot={};cold={}
        for sheet,emission,destination in [('EC_HOT','Hot',hot),('EC_COLD','Cold',cold),('EC_TOTAL','Total',totals)]:
            if units.get(sheet)!='[TJ]':raise ValueError('Unidad energética incompatible en '+sheet)
            rows=list(book[sheet].values);header=list(rows[0]);col=header.index(str(c['year'])+'_T')
            if len(rows)-1!=len(vehicles) or {tuple(v[:4]) for v in rows[1:]}!=vehicles:
                raise ValueError('Categorías ausentes, adicionales o repetidas en '+sheet)
            for row in rows[1:]:
                if row[4:6]!=(emission,'EC'):raise ValueError('Indicador energético no reconocido.')
                value=row[col]
                if sheet=='EC_COLD' and value in (None,''):
                    destination[tuple(row[:4])]=None
                elif (isinstance(value,bool) or not isinstance(value,(int,float))
                        or not math.isfinite(value) or value<0):
                    raise ValueError('Energía ausente, negativa o no finita en '+sheet)
                else:destination[tuple(row[:4])]=float(value)*1e6
    finally:book.close()
    book=load_workbook(breakdown,read_only=True,data_only=True)
    try:
        units=dict(list(book['SHEETS'].values)[1:])
        if units.get('EC_TOTAL')!='[TJ]':raise ValueError('Unidad del desglose incompatible.')
        rows=list(book['EC_TOTAL'].values);header=list(rows[0]);col=header.index(str(c['year'])+'_T')
        if header[:8]!=['Category','Fuel','Segment','Euro Standard','Fuel Category','Primary Fuel','Emission','Pollutant\n[TJ]']:
            raise ValueError('Estructura del desglose energético no reconocida.')
        components=[];seen=set();sums={v:0. for v in vehicles};electric={v:0. for v in vehicles}
        for row in rows[1:]:
            key=tuple(row[:4]);component=tuple(row[:6]);value=row[col]
            if (key not in vehicles or component in seen or row[6:8]!=('Total','EC')
                    or row[4] not in {'Fossil','Bio','Electricity'} or not row[5]):
                raise ValueError('Componente repetido, categoría o indicador no reconocido.')
            if (isinstance(value,bool) or not isinstance(value,(int,float))
                    or not math.isfinite(value) or value<0):
                raise ValueError('Componente energético ausente, negativo o no finito.')
            if (row[4]=='Electricity')!=(row[5]=='Electricity'):
                raise ValueError('Etiqueta de electricidad incoherente.')
            seen.add(component);mj=float(value)*1e6;sums[key]+=mj
            if row[4]=='Electricity':electric[key]+=mj
            components.append({'vehicle':list(key),'fuel_category':row[4],'primary_fuel':row[5],
                'total_energy_mj':mj,'total_energy_mj_per_km':mj/distance,'unit':'MJ/km',
                'scope':'EC_TOTAL: incluye frío cuando lo calcula COPERT; no componente Hot por modo'})
        checks=[]
        for key in vehicles:
            if not any(tuple(v['vehicle'])==key for v in components):raise ValueError('Falta un vehículo en el desglose.')
            if not math.isclose(sums[key],totals[key],rel_tol=1e-10,abs_tol=1e-8):
                raise ValueError('La suma de combustibles y electricidad no reproduce EC_TOTAL.')
            if cold[key] is not None:
                if not math.isclose(hot[key]+cold[key],totals[key],rel_tol=1e-10,abs_tol=1e-8):
                    raise ValueError('Hot y frío no reproducen EC_TOTAL con los auxiliares desactivados.')
            elif not math.isclose(hot[key],totals[key],rel_tol=1e-10,abs_tol=1e-8):
                raise ValueError('No se puede conciliar el total con un frío no informado.')
            checks.append({'vehicle':list(key),'hot_energy_mj':hot[key],'cold_energy_mj':cold[key],
                'total_energy_mj':totals[key],'electricity_total_mj':electric[key],
                'fuel_total_mj':sums[key]-electric[key],
                'cold_status':'Informado por COPERT' if cold[key] is not None else 'No informado; Hot coincide con total, sin imputación'})
        return {'components':components,'checks':checks,
            'output_sha256':file_hash(output),'breakdown_sha256':file_hash(breakdown)}
    finally:book.close()

def auditar_alcance_energia(output,entrada,*,year=2028):
    """Leer Hot/frío/total y controles reales de una ejecución conservada.

    No aplicar el exceso en frío técnico a los recorridos del estudio. Los
    vacíos exportados permanecen ausentes, aunque Hot coincida con el total.
    """
    from movilidad_teide.trazabilidad import file_hash
    from movilidad_teide.vehiculos.copert_entrada import vehicle_value
    import pandas as pd
    inp=load_workbook(entrada,read_only=True,data_only=True)
    try:
        stock_rows=list(inp['STOCK'].values)
        vehicles=[tuple(row[:4]) for row in stock_rows[1:]]
        if not vehicles or len(set(vehicles))!=len(vehicles):
            raise ValueError('Vehículos de entrada ausentes o repetidos.')
        distance={}
        for key in vehicles:
            stock=vehicle_value(inp,'STOCK',year,key)
            mileage=vehicle_value(inp,'MEAN_ACTIVITY',year,key)
            if not math.isfinite(stock*mileage) or stock<=0 or mileage<=0:
                raise ValueError('Actividad técnica no válida.')
            distance[key]=stock*mileage
        controls={}
        for name in ['AC_EFFECT','FB~FUEL_BALANCE']:
            rows=list(inp[name].values) if name in inp else []
            if rows:
                if len(rows)!=2 or rows[0]!=(str(year),) or rows[1][0] not in (0,1):
                    raise ValueError('Control técnico no reconocido: '+name)
                controls[name]=int(rows[1][0])
            else:controls[name]=None
        conditions={}
        for name in ['MIN_TEMPERATURE','MAX_TEMPERATURE','TRIP_LENGTH','TRIP_DURATION']:
            conditions[name]=[list(row) for row in inp[name].values] if name in inp else None
    finally:inp.close()
    book=load_workbook(output,read_only=True,data_only=True)
    try:
        units=dict(list(book['SHEETS'].values)[1:])
        data={}
        for sheet,emission in [('EC_HOT','Hot'),('EC_COLD','Cold'),('EC_TOTAL','Total')]:
            if sheet not in book:
                if sheet=='EC_COLD':
                    data[sheet]={key:None for key in vehicles}
                    continue
                raise ValueError('Falta hoja energética: '+sheet)
            if units.get(sheet)!='[TJ]':raise ValueError('Unidad energética no revisada.')
            rows=list(book[sheet].values);header=list(rows[0]);col=header.index(str(year)+'_T')
            if (len(rows)-1!=len(vehicles) or {tuple(row[:4]) for row in rows[1:]}!=set(vehicles)):
                raise ValueError('Claves energéticas distintas de la entrada.')
            values={}
            for row in rows[1:]:
                if row[4:6]!=(emission,'EC'):raise ValueError('Indicador energético no reconocido.')
                value=row[col]
                if sheet=='EC_COLD' and value in (None,''):
                    values[tuple(row[:4])]=None
                elif (isinstance(value,bool) or not isinstance(value,(int,float))
                        or not math.isfinite(value) or value<0):
                    raise ValueError('Energía ausente, negativa o no finita.')
                else:values[tuple(row[:4])]=float(value)*1e6
            data[sheet]=values
    finally:book.close()
    rows=[]
    for key in vehicles:
        hot=data['EC_HOT'][key];cold=data['EC_COLD'][key];total=data['EC_TOTAL'][key]
        extra=total-hot
        if extra < -max(1e-8,abs(total)*1e-10):
            raise ValueError('EC_TOTAL es menor que EC_HOT.')
        residual=total-hot-cold if cold is not None else None
        # Una discrepancia no se oculta o asigna al aire acondicionado.
        reconciled=math.isclose(residual,0.,rel_tol=0,abs_tol=max(1e-8,abs(total)*1e-10)) if residual is not None else None
        rows.append(dict(zip(['Category','Fuel','Segment','Euro Standard'],key))|{
            'actividad_tecnica_veh_km':distance[key],'hot_mj_consulta':hot,
            'cold_mj_consulta':cold,'total_mj_consulta':total,
            'cold_informado':cold is not None,'total_menos_hot_mj_consulta':extra,
            'residuo_total_hot_cold_mj_consulta':residual,
            'total_conciliado_con_hot_y_cold':reconciled,
            'fraccion_cold_sobre_hot_consulta':cold/hot if cold is not None and hot>0 else None,
            'ac_effect_entrada':controls['AC_EFFECT'],'balance_combustible_entrada':controls['FB~FUEL_BALANCE'],
            'hot_total_ponderado_tecnico_mj_km':hot/distance[key],
            'cold_ponderado_tecnico_mj_km':cold/distance[key] if cold is not None else None,
            'aporte_cold_anual_al_estudio_mj':None,
            'alcance':'Consulta técnica; no arranques, clima, modos o consumo por recorrido del estudio'})
    return {'energia':pd.DataFrame(rows),'condiciones':conditions,'controles':controls,
        'input_sha256':file_hash(entrada),'output_sha256':file_hash(output)}
