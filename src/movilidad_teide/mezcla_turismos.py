"""Interfaz compatible; implementación organizada por responsabilidad."""
from movilidad_teide.opciones import ALQUILER, COLECTIVOS, CRITERIOS_MEZCLA as CRITERIOS, PARTICULAR
from movilidad_teide.energia.mezcla import asignar_servicio_colectivos, comparar_mezcla_anual, estimar_resto_turismos, verificar_entradas_mezcla

__all__ = ['ALQUILER', 'COLECTIVOS', 'CRITERIOS', 'PARTICULAR', 'asignar_servicio_colectivos', 'comparar_mezcla_anual', 'estimar_resto_turismos', 'verificar_entradas_mezcla']
