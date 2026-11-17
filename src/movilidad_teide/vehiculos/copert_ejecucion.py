"""vehiculos: copert ejecucion. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def windows_path(path: str | Path) -> str:
    """Convertir una ruta WSL a Windows y exigir almacenamiento local para COPERT."""
    result = subprocess.check_output(['wslpath', '-w', str(Path(path).resolve())], text=True).strip()
    if result.startswith('\\\\'):
        raise ValueError('Utilizar una carpeta de intercambio local de Windows para esta prueba.')
    return result

def run_case(case_dir: str | Path, executable: str | Path, timeout_s: int = 120) -> dict:
    """Lanzar COPERT solo tras validar entradas; conservar logs y exigir salida legible."""
    from movilidad_teide.trazabilidad import file_hash
    from movilidad_teide.vehiculos.copert_resultados import read_hot_ec
    from movilidad_teide.vehiculos.copert_entrada import validate_pilot_input
    case_dir, executable = Path(case_dir).resolve(), Path(executable)
    preparation = json.loads((case_dir / 'preparacion.json').read_text())
    configuration = validate_pilot_input(case_dir / 'entrada.xlsx', preparation['configuration']['slope_pct'],
                                         preparation['configuration']['year'], preparation.get('base_reference'))
    for name in ('resultado.xlsx', 'ejecucion.json'):
        if (case_dir / name).exists():
            raise FileExistsError(f'La salida {name} ya existe; usar otra ejecución.')
    if file_hash(case_dir / 'entrada.xlsx') != preparation['input_sha256']:
        raise ValueError('La entrada cambió tras su validación.')
    if file_hash(case_dir / 'proyecto.cop') != preparation['project_sha256_before']:
        raise ValueError('El proyecto de trabajo cambió tras su preparación.')
    args = [str(executable), '-c', windows_path(case_dir / 'proyecto.cop'),
            '-i', windows_path(case_dir / 'entrada.xlsx'),
            '-oEF', windows_path(case_dir / 'resultado.xlsx'), '-keep', 'ES']
    record = {'started_utc': datetime.now(timezone.utc).isoformat(), 'args': args,
              'configuration': configuration, 'input_sha256': preparation['input_sha256']}
    with (case_dir / 'stdout.txt').open('w') as out, (case_dir / 'stderr.txt').open('w') as err:
        process = subprocess.Popen(args, cwd=case_dir, stdout=out, stderr=err)
        record['launcher_pid'] = process.pid
        try:
            record['returncode'] = process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            record['status'] = 'timeout_process_not_terminated'
            (case_dir / 'ejecucion.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
            raise TimeoutError('La ejecución sigue activa; se conserva su PID y no se presupone éxito.')
    record['finished_utc'] = datetime.now(timezone.utc).isoformat()
    record['status'] = 'exported' if record['returncode'] == 0 and (case_dir / 'resultado.xlsx').is_file() else 'failed'
    (case_dir / 'ejecucion.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    if record['status'] != 'exported':
        raise RuntimeError('COPERT no produjo una exportación; revisar logs.')
    result = read_hot_ec(case_dir / 'resultado.xlsx', configuration)
    record['result'] = result
    record['output_sha256'] = file_hash(case_dir / 'resultado.xlsx')
    (case_dir / 'ejecucion.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    return record

def run_reference_case(case_dir, executable, timeout_s=120):
    """Ejecutar sin proyecto heredado y exigir resultados de todas las categorías."""
    from movilidad_teide.trazabilidad import file_hash
    from movilidad_teide.vehiculos.copert_resultados import read_car_energy_breakdown
    from movilidad_teide.vehiculos.copert_resultados import read_car_hot_ec
    from movilidad_teide.vehiculos.copert_resultados import read_hot_ec
    from movilidad_teide.vehiculos.copert_entrada import validate_car_reference_input
    from movilidad_teide.vehiculos.copert_entrada import validate_reference_input
    case_dir, executable = Path(case_dir).resolve(), Path(executable)
    preparation = json.loads((case_dir/'preparacion.json').read_text())
    kind=preparation.get('case_kind')
    c=preparation['configuration']
    if kind=='explicit_bus_reference':
        checked=validate_reference_input(case_dir/'entrada.xlsx',c['vehicles'],
            slope_pct=c['slope_pct'],speed_kmh=c['rural_speed_kmh'],load_fraction=c['load_fraction'],
            year=c['year'],mean_activity_km=c['mean_activity_km'])
    elif kind=='explicit_car_reference':
        checked=validate_car_reference_input(case_dir/'entrada.xlsx',c['vehicles'],
            speed_kmh=c['speed_kmh'],mode_shares=c['mode_shares'],
            year=c['year'],mean_activity_km=c['mean_activity_km'],
            primary_fuel_share=c.get('energy_condition',{}).get('primary_fuel_share'))
    else:raise ValueError('La preparación no es una referencia explícita reconocida.')
    if checked != c or file_hash(case_dir/'entrada.xlsx') != preparation['input_sha256']:
        raise ValueError('La entrada o su configuración cambió después de validarla.')
    if any((case_dir/name).exists() for name in ['resultado.xlsx','resultado.cop','ejecucion.json','desglose.xlsx']):
        raise FileExistsError('La salida ya existe; usar otra ejecución.')
    args = [str(executable), '-i', windows_path(case_dir/'entrada.xlsx'),
            '-oEF', windows_path(case_dir/'resultado.xlsx')]
    if c.get('export_energy_breakdown'):
        args += ['-oEB',windows_path(case_dir/'desglose.xlsx')]
    args += ['-keep','ES']
    record = {'started_utc': datetime.now(timezone.utc).isoformat(), 'args': args,
              'configuration': c, 'input_sha256': preparation['input_sha256'],
              'executable_sha256': file_hash(executable)}
    with (case_dir/'stdout.txt').open('w') as out, (case_dir/'stderr.txt').open('w') as err:
        process = subprocess.Popen(args, cwd=case_dir, stdout=out, stderr=err)
        record['launcher_pid'] = process.pid
        try:
            record['returncode'] = process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            record['status'] = 'timeout_process_not_terminated'
            (case_dir/'ejecucion.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
            raise TimeoutError('COPERT sigue activo; conservar PID y revisar antes de relanzar.')
    record['finished_utc'] = datetime.now(timezone.utc).isoformat()
    record['status'] = 'exported' if record['returncode'] == 0 and (case_dir/'resultado.xlsx').is_file() else 'failed'
    (case_dir/'ejecucion.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    if record['status'] != 'exported':
        raise RuntimeError('COPERT no produjo la exportación; revisar los logs.')
    # Cada fila se normaliza con la actividad de su categoría, sin sumar vehículos.
    if kind=='explicit_car_reference':
        record['results']=read_car_hot_ec(case_dir/'resultado.xlsx',c)
        if c.get('export_energy_breakdown'):
            record['energy_breakdown']=read_car_energy_breakdown(case_dir/'resultado.xlsx',case_dir/'desglose.xlsx',c)
    else:
        record['results'] = []
        for vehicle in c['vehicles']:
            config = {'vehicle': vehicle, 'year': c['year'], 'slope_pct': c['slope_pct'],
                      'vehicle_km': c['vehicle_km_per_category']}
            result = read_hot_ec(case_dir/'resultado.xlsx', config)
            if result['hot_ec_mj_per_km'] <= 0:
                raise ValueError('Factor ausente o cero: no se publica como consumo válido.')
            record['results'].append({**result, 'vehicle': vehicle,
                 'rural_speed_kmh': c['rural_speed_kmh'], 'load_fraction': c['load_fraction']})
    record['output_sha256'] = file_hash(case_dir/'resultado.xlsx')
    (case_dir/'ejecucion.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    return record
