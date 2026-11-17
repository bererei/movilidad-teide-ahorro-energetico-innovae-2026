"""vehiculos: copert entrada. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import json
import math
from pathlib import Path
import shutil
from openpyxl import load_workbook
from movilidad_teide.vehiculos.copert_cli_tipos import INHERITABLE_SHEETS
from movilidad_teide.vehiculos.copert_cli_tipos import REQUIRED_SHEETS
from movilidad_teide.vehiculos.copert_cli_tipos import VEHICLE
from movilidad_teide.vehiculos.copert_cli_tipos import REFERENCE_UNITS
from movilidad_teide.vehiculos.copert_cli_tipos import CAR_BIFUEL_PAIRS
from movilidad_teide.vehiculos.copert_cli_tipos import CAR_INPUT_PREFIX
from movilidad_teide.vehiculos.copert_cli_tipos import CAR_MODES


def inspect_input(path: str | Path) -> dict:
    """Inventariar la plantilla sin rellenar campos ausentes ni ejecutar COPERT."""
    from movilidad_teide.trazabilidad import file_hash
    with Path(path).open('rb') as stream:
        book = load_workbook(stream, read_only=True, data_only=True)
        try:
            sheets = {sheet.title: {
                'rows': sheet.max_row, 'columns': sheet.max_column,
                'header': list(next(sheet.iter_rows(values_only=True), ())),
            } for sheet in book}
            return {'sheets': sheets,
                    'missing_required_sheets': [s for s in REQUIRED_SHEETS if s not in sheets],
                    'fields_inherited_from_base': [s for s in INHERITABLE_SHEETS if s not in sheets],
                    'sha256': file_hash(path)}
        finally:
            book.close()


def vehicle_value(book, sheet: str, year: int = 2028, vehicle=VEHICLE) -> float:
    """Leer un valor inequívoco para vehículo/año; no agregar otras categorías."""
    if sheet not in book.sheetnames:
        raise ValueError(f'Falta la hoja {sheet}; no se infiere su valor.')
    rows = list(book[sheet].values)
    headers = [str(v) for v in rows[0]]
    if str(year) not in headers:
        raise ValueError(f'Falta el año {year} en {sheet}.')
    matches = [r for r in rows[1:] if tuple(r[:4]) == tuple(vehicle)]
    if len(matches) != 1:
        raise ValueError(f'{sheet}: se exige exactamente una fila del vehículo.')
    value = matches[0][headers.index(str(year))]
    if value is None or isinstance(value, bool):
        raise ValueError(f'{sheet}: valor ausente o no numérico.')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'{sheet}: valor no finito.')
    return result

def validate_pilot_input(path: str | Path, slope_pct: float, year: int = 2028,
                         base_reference: dict | None = None) -> dict:
    """Validar campos explícitos y documentar los heredados del proyecto base."""
    if inspect_input(path)['missing_required_sheets']:
        raise ValueError('Plantilla incompleta: faltan hojas necesarias para acreditar configuración y actividad.')
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        values = {sheet: vehicle_value(book, sheet, year) for sheet in REQUIRED_SHEETS if sheet != 'FB~FUEL_BALANCE'}
        if values['STOCK'] <= 0:
            raise ValueError('Stock debe ser positivo para obtener MJ/km.')
        inherited = {}
        for sheet in INHERITABLE_SHEETS:
            if sheet in book.sheetnames:
                values[sheet] = vehicle_value(book, sheet, year)
            else:
                if not base_reference or not base_reference.get('baseline_cli_matches_gui'):
                    raise ValueError(f'{sheet} no está exportada: acreditar el proyecto base antes de heredarla.')
                if sheet == 'MEAN_ACTIVITY':
                    values[sheet] = base_reference['vehicle_km'] / values['STOCK']
                    inherited[sheet] = 'Actividad deducida de exportaciones GUI de energía/factor y conservada en .cop'
                else:
                    # Reproducir la energía GUI no acredita la velocidad heredada.
                    if (base_reference.get('rural_speed_verified_kmh') != 34.0
                            or not base_reference.get('speed_verification')):
                        raise ValueError('Velocidad heredada sin verificación independiente; usar referencias explícitas.')
                    values[sheet] = base_reference['rural_speed_verified_kmh']
                    inherited[sheet] = 'Velocidad acreditada por contraste independiente del estado base'
        balance_rows = list(book['FB~FUEL_BALANCE'].values)
        year_column = [str(v) for v in balance_rows[0]].index(str(year))
        balance = balance_rows[1][year_column]
        if balance not in (0, False):
            raise ValueError('El balance de combustible debe estar desactivado para conservar la actividad.')
        if values['STOCK'] <= 0 or values['MEAN_ACTIVITY'] <= 0:
            raise ValueError('Stock y actividad deben ser positivos para obtener MJ/km.')
        for name, expected in [('RURAL_SPEED', 34.0), ('RURAL_SHARE', 1.0),
                               ('RURAL_LOAD', 0.5), ('RURAL_ROAD_SLOPE', slope_pct / 100.0)]:
            if abs(values[name] - expected) > 1e-12:
                raise ValueError(f'{name} no coincide con el piloto: {values[name]} frente a {expected}.')
        for sheet in ('URBAN_PEAK_SHARE', 'URBAN_OFF_PEAK_SHARE', 'HIGHWAY_SHARE'):
            if vehicle_value(book, sheet, year) != 0:
                raise ValueError('La actividad del piloto debe ser exclusivamente rural.')
        return {'year': year, 'vehicle': list(VEHICLE), 'slope_pct': slope_pct,
                'vehicle_km': values['STOCK'] * values['MEAN_ACTIVITY'],
                'values': values, 'fuel_balance': 0,
                'inherited_fields': inherited,
                'speed_read_directly_from_export': 'RURAL_SPEED' not in inherited}
    finally:
        book.close()

def prepare_case(project: str | Path, template: str | Path, case_dir: str | Path,
                 slope_pct: float, year: int = 2028, base_reference: dict | None = None) -> dict:
    """Copiar el estado base y modificar únicamente su pendiente rural."""
    from movilidad_teide.trazabilidad import file_hash
    if not math.isfinite(slope_pct) or slope_pct not in (-6, -4, -2, 0, 2, 4, 6):
        raise ValueError('Esta reproducción utiliza únicamente los siete nodos de COPERT.')
    project, template, case_dir = Path(project).resolve(), Path(template).resolve(), Path(case_dir).resolve()
    if case_dir.exists():
        raise FileExistsError('El directorio de ejecución ya existe; no se sobrescribe.')
    for source in (project, template):
        if source.parent == case_dir or source.parent in case_dir.parents:
            raise ValueError('La ejecución debe quedar separada de los originales.')
    info = inspect_input(template)
    if info['missing_required_sheets']:
        raise ValueError(f'Completar la exportación antes de ejecutar: {info["missing_required_sheets"]}')
    before = {str(p): file_hash(p) for p in (project, template)}
    if info['fields_inherited_from_base']:
        if not base_reference or not base_reference.get('baseline_cli_matches_gui'):
            raise ValueError('Acreditar el proyecto base antes de heredar campos no exportados.')
        if (before[str(project)] != base_reference['project_sha256']
                or before[str(template)] != base_reference['template_sha256']):
            raise ValueError('El proyecto o la plantilla no coinciden con la referencia contrastada.')
    case_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(project, case_dir / 'proyecto.cop')
    book = load_workbook(template)
    changes = []
    for name, requested in [('RURAL_ROAD_SLOPE', slope_pct / 100.0)]:
        sheet = book[name]
        column = [str(c.value) for c in sheet[1]].index(str(year)) + 1
        matches = [i for i, row in enumerate(sheet.iter_rows(values_only=True), start=1) if tuple(row[:4]) == VEHICLE]
        if len(matches) != 1:
            raise ValueError(f'Fila ambigua del vehículo en {name}.')
        cell = sheet.cell(matches[0], column)
        changes.append({'sheet': name, 'cell': cell.coordinate, 'before': cell.value, 'after': requested})
        cell.value = requested
    book.save(case_dir / 'entrada.xlsx')
    book.close()
    configuration = validate_pilot_input(case_dir / 'entrada.xlsx', slope_pct, year, base_reference)
    for source in (project, template):
        if file_hash(source) != before[str(source)]:
            raise RuntimeError('La fuente cambió durante la preparación.')
    manifest = {'sources': before, 'configuration': configuration, 'changes': changes,
                'input_sha256': file_hash(case_dir / 'entrada.xlsx'),
                'project_sha256_before': file_hash(case_dir / 'proyecto.cop'),
                'base_reference': base_reference}
    (case_dir / 'preparacion.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def validate_reference_input(path, vehicles, *, slope_pct, speed_kmh, load_fraction,
                             year=2028, mean_activity_km=17.0) -> dict:
    """Acreditar las entradas explícitas del ensayo rural, nunca una flota real."""
    vehicles = [tuple(v) for v in vehicles]
    if not vehicles or len(set(vehicles)) != len(vehicles) or any(len(v) != 4 for v in vehicles):
        raise ValueError('Se requieren claves de vehículo completas, únicas y no vacías.')
    if slope_pct not in (-6, -4, -2, 0, 2, 4, 6):
        raise ValueError('Pendiente de referencia fuera de los siete nodos.')
    if (not math.isfinite(speed_kmh) or not 0 < speed_kmh <= 100
            or not math.isfinite(load_fraction) or not 0 <= load_fraction <= 1
            or not math.isfinite(mean_activity_km) or mean_activity_km <= 0):
        raise ValueError('Velocidad, carga o actividad de normalización no válidas.')
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        units_rows = list(book['SHEETS'].values)[1:]
        names = [r[0] for r in units_rows]
        if len(names) != len(set(names)):
            raise ValueError('SHEETS contiene nombres duplicados.')
        units = {r[0]: r[1] for r in units_rows}
        for name, unit in REFERENCE_UNITS.items():
            if name not in book.sheetnames or units.get(name) != unit:
                raise ValueError(f'{name}: hoja o unidad explícita ausente/incompatible.')
        expected = {
            'STOCK': 1, 'MEAN_ACTIVITY': mean_activity_km, 'RURAL_SPEED': speed_kmh,
            'RURAL_LOAD': load_fraction, 'RURAL_ROAD_SLOPE': slope_pct / 100,
            'RURAL_SHARE': 1, 'URBAN_PEAK_SHARE': 0, 'URBAN_OFF_PEAK_SHARE': 0,
            'HIGHWAY_SHARE': 0, 'URBAN_PEAK_SPEED': 0,
            'URBAN_OFF_PEAK_SPEED': 0, 'HIGHWAY_SPEED': 0,
        }
        for name, requested in expected.items():
            rows = list(book[name].values)
            if {tuple(r[:4]) for r in rows[1:]} != set(vehicles) or len(rows)-1 != len(vehicles):
                raise ValueError(f'{name}: categorías adicionales, ausentes o duplicadas.')
            for vehicle in vehicles:
                if not math.isclose(vehicle_value(book, name, year, vehicle), requested, rel_tol=0, abs_tol=1e-12):
                    raise ValueError(f'{name} no coincide con la configuración explícita.')
        if list(book['FB~FUEL_BALANCE'].values) != [(str(year),), (0,)]:
            raise ValueError('El balance de combustible debe estar desactivado.')
        return {'year': year, 'vehicles': [list(v) for v in vehicles], 'slope_pct': slope_pct,
                'rural_speed_kmh': speed_kmh, 'load_fraction': load_fraction,
                'stock_per_category': 1, 'mean_activity_km': mean_activity_km,
                'vehicle_km_per_category': mean_activity_km,
                'speed_explicit_in_input': True, 'inherited_fields': [],
                'scope': 'Ensayo Hot EC rural; no actividad anual ni elección de flota'}
    finally:
        book.close()

def prepare_reference_case(template, catalog, case_dir, vehicles, *, slope_pct,
                           speed_kmh, load_fraction, year=2028, mean_activity_km=17.0):
    """Crear una entrada independiente con claves del catálogo y condiciones visibles.

    La plantilla aporta ambiente/combustible y las condiciones auxiliares del
    piloto. Solo se admiten aquí referencias diésel de guagua Euro VI D/E.
    Stock=1 y actividad=17 normalizan el factor: no representan la operación.
    """
    from movilidad_teide.trazabilidad import file_hash
    import csv
    template, catalog, case_dir = map(lambda p: Path(p).resolve(), (template, catalog, case_dir))
    if case_dir.exists():
        raise FileExistsError('La ejecución ya existe; no se sobrescribe.')
    vehicles = [tuple(v) for v in vehicles]
    allowed = {
        VEHICLE,
        ('Buses', 'Diesel', 'Coaches Standard <=18 t', 'Euro VI D/E'),
        ('Buses', 'Diesel Hybrid', 'Urban Buses Diesel Hybrid', 'Euro VI D/E'),
    }
    with catalog.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    available = {tuple(r[k] for k in ('Category','Fuel','Segment','Euro Standard')) for r in rows}
    if (not vehicles or len(set(vehicles)) != len(vehicles)
            or any(v not in allowed or v not in available for v in vehicles)):
        raise ValueError('Referencia no acreditada en el catálogo o fuera del alcance diésel de guaguas.')
    hashes = {str(p): file_hash(p) for p in (template, catalog)}
    book = load_workbook(template)
    changes = []
    try:
        # Conservar ambiente y combustible; sustituir solo las filas de las referencias.
        for sheet in book:
            source_rows = list(sheet.values)
            if source_rows and tuple(source_rows[0][:4]) == ('Category','Fuel','Segment','Euro Standard'):
                body = source_rows[1:]
                if any(tuple(r[:4]) != VEHICLE for r in body):
                    raise ValueError('La plantilla contiene otra categoría: revisar antes de replicarla.')
                sheet.delete_rows(2, max(sheet.max_row-1, 0))
                for vehicle in vehicles:
                    for row in body:
                        sheet.append([*vehicle, *row[4:]])
        values = {'STOCK': 1, 'MEAN_ACTIVITY': mean_activity_km,
                  'RURAL_SPEED': speed_kmh, 'RURAL_LOAD': load_fraction,
                  'RURAL_ROAD_SLOPE': slope_pct/100, 'RURAL_SHARE': 1,
                  'URBAN_PEAK_SPEED': 0, 'URBAN_OFF_PEAK_SPEED': 0,
                  'HIGHWAY_SPEED': 0, 'URBAN_PEAK_SHARE': 0,
                  'URBAN_OFF_PEAK_SHARE': 0, 'HIGHWAY_SHARE': 0,
                  'LIFETIME_CUMUL_ACTIVITY': 80000}
        # Las hojas nuevas se registran también en SHEETS para que la CLI las importe.
        for name, value in values.items():
            if name in book.sheetnames:
                sheet = book[name]
                old = list(sheet.values)[1:]
                sheet.delete_rows(2, max(sheet.max_row-1, 0))
            else:
                sheet = book.create_sheet(name)
                sheet.append(['Category','Fuel','Segment','Euro Standard',str(year)])
                book['SHEETS'].append([name, REFERENCE_UNITS[name]])
                old = []
            if list(sheet.values)[0] != ('Category','Fuel','Segment','Euro Standard',str(year)):
                raise ValueError('La plantilla no es de un solo año compatible.')
            for vehicle in vehicles:
                sheet.append([*vehicle, value])
            changes.append({'sheet': name, 'before_rows': old, 'requested': value})
        # Validar en un temporal antes de crear un directorio persistente de ejecución.
        import tempfile
        with tempfile.TemporaryDirectory(prefix='teide_copert_') as temp:
            trial = Path(temp)/'entrada.xlsx';book.save(trial)
            config = validate_reference_input(trial, vehicles, slope_pct=slope_pct,
                         speed_kmh=speed_kmh, load_fraction=load_fraction,
                         year=year, mean_activity_km=mean_activity_km)
            case_dir.mkdir(parents=True, exist_ok=False)
            shutil.copy2(trial, case_dir/'entrada.xlsx')
    finally:
        book.close()
    if any(file_hash(p) != digest for p, digest in hashes.items()):
        raise RuntimeError('Una fuente cambió durante la preparación.')
    manifest = {'case_kind': 'explicit_bus_reference', 'sources': hashes,
                'configuration': config, 'changes': changes,
                'input_sha256': file_hash(case_dir/'entrada.xlsx'),
                'auxiliary_conditions': 'Ambiente, combustible y tecnología de la plantilla piloto; no flota futura',
                'lifetime_cumulative_activity_km': 80000,
                'lifetime_source': 'Stock_&_Activity_Data_Spain.csv del piloto; control técnico, no edad ni desgaste real inferido'}
    (case_dir/'preparacion.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    return manifest




def validate_car_reference_input(path, vehicles, *, speed_kmh, mode_shares,
                                 mean_activity_km=17.0, year=2028, primary_fuel_share=None):
    """Validar la consulta Hot EC de turismos sin condiciones de la guagua piloto."""
    vehicles=[tuple(v) for v in vehicles]
    if (not vehicles or len(set(vehicles))!=len(vehicles)
            or any(len(v)!=4 or v[0]!='Passenger Cars' or v[1] not in ({'Petrol','Diesel','Petrol Hybrid','Battery electric'} | set(CAR_BIFUEL_PAIRS)) for v in vehicles)):
        raise ValueError('Claves de turismo ausentes, repetidas o fuera del alcance documentado.')
    bifuel=_car_energy_condition(vehicles,primary_fuel_share)
    if (not math.isfinite(speed_kmh) or not 0<speed_kmh<=130
            or not math.isfinite(mean_activity_km) or mean_activity_km<=0):
        raise ValueError('Velocidad o actividad de normalización no válida.')
    if (set(mode_shares)!=set(CAR_MODES)
            or any(not math.isfinite(v) or not 0<=v<=1 for v in mode_shares.values())
            or not math.isclose(sum(mode_shares.values()),1,rel_tol=0,abs_tol=1e-12)):
        raise ValueError('El reparto técnico entre modos debe sumar uno, sin ausencias.')
    book=load_workbook(path,read_only=True,data_only=True)
    try:
        units_rows=list(book['SHEETS'].values)[1:]
        if len({r[0] for r in units_rows})!=len(units_rows):
            raise ValueError('SHEETS contiene nombres duplicados.')
        units={r[0]:r[1] for r in units_rows}
        required={'STOCK':(1,'[n]'),'MEAN_ACTIVITY':(mean_activity_km,'[km]')}
        for mode,prefix in CAR_INPUT_PREFIX.items():
            required[prefix+'_SPEED']=(speed_kmh,'[km/h]')
            required[prefix+'_SHARE']=(mode_shares[mode],'[%]')
        for name,(requested,unit) in required.items():
            if name not in book.sheetnames or units.get(name)!=unit:
                raise ValueError('Hoja o unidad explícita ausente: '+name)
            rows=list(book[name].values)[1:]
            if len(rows)!=len(vehicles) or {tuple(r[:4]) for r in rows}!=set(vehicles):
                raise ValueError('Categorías adicionales, ausentes o repetidas en '+name)
            for vehicle in vehicles:
                if not math.isclose(vehicle_value(book,name,year,vehicle),requested,rel_tol=0,abs_tol=1e-12):
                    raise ValueError('Valor incompatible con la consulta en '+name)
        for name,value in [('FB~FUEL_BALANCE',0),('EXCLUDE_EVAPORATIVE',1),('AC_EFFECT',0),('CO2_REDUCTION',0)]:
            if name not in book.sheetnames or list(book[name].values)!=[(str(year),),(value,)]:
                raise ValueError('Revisar control técnico '+name)
        # Los nombres de combustible de este formulario son Petrol/LPG, sin Grade 1.
        # Etiquetas de especificación como Petrol Grade 1 se ignoran en la importación.
        energy_sheets={'PRIMARY_FUEL_BIFUEL_SHARE':primary_fuel_share,
                       'SECONDARY_FUEL_BIFUEL_SHARE':None if primary_fuel_share is None else 1-primary_fuel_share}
        for name,requested in energy_sheets.items():
            if not bifuel:
                if name in book and len(list(book[name].values))>1:
                    raise ValueError('Reparto bifuel presente en una consulta sin esas tecnologías.')
                continue
            if name not in book or units.get(name)!='[%]':raise ValueError('Falta el reparto energético explícito: '+name)
            rows=list(book[name].values)
            if rows[0]!=('Category','Fuel','Segment','Euro Standard','Primary Fuel','Secondary Fuel',str(year)):
                raise ValueError('Cabecera de reparto bifuel no reconocida.')
            if len(rows)-1!=len(bifuel) or {tuple(row[:4]) for row in rows[1:]}!=set(bifuel):
                raise ValueError('Faltan o se repiten vehículos en el reparto bifuel.')
            for row in rows[1:]:
                if (tuple(row[4:6])!=CAR_BIFUEL_PAIRS[row[1]] or isinstance(row[6],bool)
                        or not isinstance(row[6],(int,float)) or not math.isfinite(row[6])
                        or not math.isclose(row[6],requested,rel_tol=0,abs_tol=1e-12)):
                    raise ValueError('Combustibles o proporción bifuel incompatibles con la consulta.')
        # No copiar carga, pendiente, DPF+SCR o ajustes específicos de la guagua.
        for sheet in book:
            rows=list(sheet.values)
            if rows and tuple(rows[0][:4])==('Category','Fuel','Segment','Euro Standard'):
                if sheet.title not in required and sheet.title not in energy_sheets and len(rows)>1:
                    raise ValueError('Condición de vehículo no acreditada para turismos: '+sheet.title)
        fuel_rows=list(book['FUEL_YEAR'].values)
        if (len(fuel_rows)!=2 or fuel_rows[0]!=(str(year),)
                or fuel_rows[1][0] not in (1996,2000,2005,2009)):
            raise ValueError('Especificación FUEL_YEAR no reconocida.')
        config={'year':year,'vehicles':[list(v) for v in vehicles],
            'fuel_year_specification':fuel_rows[1][0], 'speed_kmh':speed_kmh,'mode_shares':dict(mode_shares),'mean_activity_km':mean_activity_km,
            'stock_per_category':1,'scope':'Referencia Hot EC sin corrección de pendiente; no mezcla o actividad operativa',
            'slope_correction':'No aplicada a turismos; aplicación a montaña pendiente de justificar',
            'auxiliary_conditions':'Ambiente y combustible de la plantilla; sin evaporación, efecto A/C o balance; sin extrapolación de mejora CO2'}
        if bifuel or any(v[1]=='Battery electric' for v in vehicles):
            config['energy_condition']={'primary_fuel_share':primary_fuel_share,
                'fuel_pairs':{fuel:list(CAR_BIFUEL_PAIRS[fuel]) for fuel in sorted({v[1] for v in bifuel})},
                'scope':'Control nativo explícito; no cuota energética o UF observado. PHEV puede conservar combustible en el extremo secundario.'}
            config['export_energy_breakdown']=True
        return config
    finally:book.close()

def prepare_car_reference_case(template, catalog, candidates, case_dir, *, speed_kmh,
                               mean_activity_km=17.0, mode_shares=None, year=2028, fuel_year=None, primary_fuel_share=None):
    """Consultar todas las claves candidatas, sin elegir tamaños o pesos de flota."""
    from movilidad_teide.trazabilidad import file_hash
    import csv,tempfile
    template,catalog,candidates,case_dir=[Path(p).resolve() for p in (template,catalog,candidates,case_dir)]
    if case_dir.exists():raise FileExistsError('La consulta ya existe; no se sobrescribe.')
    mode_shares=dict(mode_shares) if mode_shares is not None else {k:.25 for k in CAR_MODES}
    fields=['Category','Fuel','Segment','Euro Standard']
    with candidates.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f,delimiter=';'))
    vehicles=[tuple(r[k] for k in fields) for r in rows]
    bifuel=_car_energy_condition(vehicles,primary_fuel_share)
    with catalog.open(encoding='utf-8-sig',newline='') as f:available={tuple(r[k] for k in fields) for r in csv.DictReader(f)}
    if not vehicles or any(v not in available for v in vehicles):
        raise ValueError('Una clave candidata no existe en el catálogo original.')
    hashes={str(p):file_hash(p) for p in (template,catalog,candidates)}
    book=load_workbook(template)
    try:
        # Conservar tablas comunes de ambiente/combustible y vaciar datos de la guagua.
        removed=[]
        for sheet in book:
            old=list(sheet.values)
            if old and tuple(old[0][:4])==tuple(fields):
                if len(old)>1:removed.append({'sheet':sheet.title,'rows':len(old)-1})
                sheet.delete_rows(2,max(sheet.max_row-1,0))
        values={'STOCK':(1,'[n]'),'MEAN_ACTIVITY':(mean_activity_km,'[km]')}
        for mode,prefix in CAR_INPUT_PREFIX.items():
            values[prefix+'_SPEED']=(speed_kmh,'[km/h]')
            values[prefix+'_SHARE']=(mode_shares.get(mode),'[%]')
        for name,(value,unit) in values.items():
            if name not in book.sheetnames:
                sheet=book.create_sheet(name);sheet.append([*fields,str(year)])
                book['SHEETS'].append([name,unit])
            else:sheet=book[name]
            if list(sheet.values)[0]!=tuple([*fields,str(year)]):
                raise ValueError('La plantilla no es de un solo año compatible.')
            for vehicle in vehicles:sheet.append([*vehicle,value])
        for name,value in [('PRIMARY_FUEL_BIFUEL_SHARE',primary_fuel_share),
                           ('SECONDARY_FUEL_BIFUEL_SHARE',None if primary_fuel_share is None else 1-primary_fuel_share)]:
            if not bifuel:continue
            if name not in book:
                sheet=book.create_sheet(name)
                sheet.append([*fields,'Primary Fuel','Secondary Fuel',str(year)])
                book['SHEETS'].append([name,'[%]'])
            if list(book[name].values)[0]!=tuple([*fields,'Primary Fuel','Secondary Fuel',str(year)]):
                raise ValueError('La plantilla bifuel no es del año o formato esperado.')
            for vehicle in bifuel:book[name].append([*vehicle,*CAR_BIFUEL_PAIRS[vehicle[1]],value])
        book['EXCLUDE_EVAPORATIVE'].cell(2,1).value=1
        if fuel_year is not None:book['FUEL_YEAR'].cell(2,1).value=fuel_year
        with tempfile.TemporaryDirectory(prefix='teide_car_') as temp:
            trial=Path(temp)/'entrada.xlsx';book.save(trial)
            config=validate_car_reference_input(trial,vehicles,speed_kmh=speed_kmh,
                mode_shares=mode_shares,mean_activity_km=mean_activity_km,year=year,
                primary_fuel_share=primary_fuel_share)
            case_dir.mkdir(parents=True,exist_ok=False);shutil.copy2(trial,case_dir/'entrada.xlsx')
    finally:book.close()
    if any(file_hash(p)!=h for p,h in hashes.items()):raise RuntimeError('Una fuente cambió durante la preparación.')
    manifest={'case_kind':'explicit_car_reference','configuration':config,'sources':hashes,
        'input_sha256':file_hash(case_dir/'entrada.xlsx'),'removed_bus_rows':removed,
        'normalization_note':'Stock=1 y actividad por categoría; reparto técnico de extracción, no reparto modal real'}
    (case_dir/'preparacion.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest

def _car_energy_condition(vehicles, primary_fuel_share):
    """Exigir un control explícito, sin interpretarlo como cuota de energía/UF."""
    bifuel = [v for v in vehicles if v[1] in CAR_BIFUEL_PAIRS]
    if bifuel:
        if (isinstance(primary_fuel_share,bool) or not isinstance(primary_fuel_share,(int,float))
                or not math.isfinite(primary_fuel_share) or not 0 <= primary_fuel_share <= 1):
            raise ValueError('La consulta bifuel/PHEV necesita un reparto primario explícito entre 0 y 1.')
    elif primary_fuel_share is not None:
        raise ValueError('No asignar reparto bifuel a una consulta sin vehículos de dos fuentes.')
    return bifuel
