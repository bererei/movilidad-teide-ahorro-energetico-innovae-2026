"""Interfaz compatible; implementación organizada por responsabilidad."""
from movilidad_teide.opciones import HYBRID, HYBRID_ID, OFFICIALS, PARK_ENTRADA, PARK_INTERIOR, REFUERZOS
from movilidad_teide.operacion.criterios_estudio import NUEVOS, balance_con_aparcamiento, cota_refuerzos_interior, recalcular_oferta_hibrida, reforzar_reservas_interior, verificar_revision_luis

__all__ = ['HYBRID', 'HYBRID_ID', 'NUEVOS', 'OFFICIALS', 'PARK_ENTRADA', 'PARK_INTERIOR', 'REFUERZOS', 'balance_con_aparcamiento', 'cota_refuerzos_interior', 'recalcular_oferta_hibrida', 'reforzar_reservas_interior', 'verificar_revision_luis']
