"""Interfaz compatible; implementación organizada por responsabilidad."""
from movilidad_teide.energia.visita_privada import NUEVOS, ampliar_patron_proximo, coeficientes_interior_mezcla, evaluar_interior, verificar_entradas_interior
from movilidad_teide.opciones import PATRONES_INTERIORES as PATRONES

__all__ = ['NUEVOS', 'PATRONES', 'ampliar_patron_proximo', 'coeficientes_interior_mezcla', 'evaluar_interior', 'verificar_entradas_interior']
