"""Interfaz compatible; implementación organizada por responsabilidad."""
from movilidad_teide.opciones import METODO_CONSUMO as METODO
from movilidad_teide.energia.referencia import NUEVOS, referencia_ponderada, verificar_referencia

__all__ = ['METODO', 'NUEVOS', 'referencia_ponderada', 'verificar_referencia']
