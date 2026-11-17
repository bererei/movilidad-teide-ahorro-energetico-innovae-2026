"""Interfaz compatible; implementación organizada por responsabilidad."""
from movilidad_teide.operacion.interior import _numero, cargas_por_tramos, coordinar_destino_por_tramos, coordinar_visitas_completas, cotas_capacidad_interior, horario_en_paradas, referenciar_paradas_del_eje

__all__ = ['cargas_por_tramos', 'coordinar_destino_por_tramos', 'coordinar_visitas_completas', 'cotas_capacidad_interior', 'horario_en_paradas', 'referenciar_paradas_del_eje']
