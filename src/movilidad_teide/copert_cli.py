"""Interfaz compatible; las responsabilidades se organizan en vehiculos."""

from movilidad_teide.trazabilidad import file_hash

from movilidad_teide.vehiculos.copert_cli_tipos import CAR_BIFUEL_PAIRS, CAR_INPUT_PREFIX, CAR_MODES, INHERITABLE_SHEETS, REFERENCE_UNITS, REQUIRED_SHEETS, VEHICLE

from movilidad_teide.vehiculos.copert_ejecucion import run_case, run_reference_case, windows_path

from movilidad_teide.vehiculos.copert_entrada import _car_energy_condition, inspect_input, prepare_car_reference_case, prepare_case, prepare_reference_case, validate_car_reference_input, validate_pilot_input, validate_reference_input, vehicle_value

from movilidad_teide.vehiculos.copert_factores import apply_reference_factors_by_segment, read_car_reference_library, read_reference_library, seleccionar_referencia_multienergia

from movilidad_teide.vehiculos.copert_resultados import auditar_alcance_energia, make_base_reference, read_car_energy_breakdown, read_car_hot_ec, read_hot_ec, read_hot_factor

from movilidad_teide.vehiculos.lanzaderas import anualizar_consumos_lanzaderas

__all__ = ['CAR_BIFUEL_PAIRS', 'CAR_INPUT_PREFIX', 'CAR_MODES', 'INHERITABLE_SHEETS', 'REFERENCE_UNITS', 'REQUIRED_SHEETS', 'VEHICLE', 'anualizar_consumos_lanzaderas', 'apply_reference_factors_by_segment', 'auditar_alcance_energia', 'file_hash', 'inspect_input', 'make_base_reference', 'prepare_car_reference_case', 'prepare_case', 'prepare_reference_case', 'read_car_energy_breakdown', 'read_car_hot_ec', 'read_car_reference_library', 'read_hot_ec', 'read_hot_factor', 'read_reference_library', 'run_case', 'run_reference_case', 'seleccionar_referencia_multienergia', 'validate_car_reference_input', 'validate_pilot_input', 'validate_reference_input', 'vehicle_value', 'windows_path']
