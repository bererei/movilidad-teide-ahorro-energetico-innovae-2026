"""Interfaz compatible; implementación organizada por responsabilidad."""
from movilidad_teide.operacion.circulacion import COLUMNAS_REGRESO, ErrorOperacion, _cadenas_vehiculos, _clock, _criterios_regreso, coordinar_horarios, incorporar_circulacion, programar_circulacion, proponer_refuerzos, proponer_tiempos, referencias_tiempo_gtfs, revisar_cadenas_interiores, revisar_regresos

__all__ = ['COLUMNAS_REGRESO', 'ErrorOperacion', 'coordinar_horarios', 'incorporar_circulacion', 'programar_circulacion', 'proponer_refuerzos', 'proponer_tiempos', 'referencias_tiempo_gtfs', 'revisar_cadenas_interiores', 'revisar_regresos']
