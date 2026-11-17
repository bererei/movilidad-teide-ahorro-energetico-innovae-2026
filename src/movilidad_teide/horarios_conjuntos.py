"""Interfaz compatible; implementación organizada por responsabilidad."""
from movilidad_teide.opciones import DESTINOS, METODO_HORARIOS as METODO, PUNTOS
from movilidad_teide.operacion.horarios import NUEVOS, _contexto, _interior, _lado, _programar, _proponer, contrastar_circulacion_con_flota, energia_movimientos, optimizar_horarios_conjuntos, verificar_entradas_conjuntas

__all__ = ['DESTINOS', 'METODO', 'NUEVOS', 'PUNTOS', 'contrastar_circulacion_con_flota', 'energia_movimientos', 'optimizar_horarios_conjuntos', 'verificar_entradas_conjuntas']
