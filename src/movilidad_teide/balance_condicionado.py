"""Interfaz compatible; las responsabilidades se organizan en energia."""

from movilidad_teide.energia.actividad_pareada import actividad_comparacion_hot, emparejar_retornos_condicionados, repartir_actividad_condicionada, revisar_cupo_y_oferta

from movilidad_teide.energia.balance import calcular_aportes_anuales, comparar_anualmente_hot, comparar_con_lanzaderas, impacto_separacion_turismos

from movilidad_teide.energia.balance_condicionado_tipos import CRITERIO_TERRITORIAL, MAGNITUD_ANUAL, SENTIDOS

from movilidad_teide.energia.compatibilidad import verificar_representacion_tecnica, verificar_reutilizacion_hot, verificar_reutilizacion_sensibilidad, verificar_reutilizacion_sin_cocheras

from movilidad_teide.energia.interior import coeficientes_hot_interior_coche, contraste_umbral_interior_hot, recorridos_interiores_coche

from movilidad_teide.energia.materialidad import coeficientes_cocheras_auxiliares, coeficientes_energia_resto, componentes_pendientes, comprobar_cocheras_en_extremos, desglosar_resto_sin_referencia, exposicion_lanzaderas_materialidad, incremento_por_perdida_rendimiento, integrar_coeficientes_materialidad, margen_para_componentes_pendientes, revisar_elecciones_para_cierre, sensibilidad_interior_y_operacion, umbral_aporte_para_equilibrio

from movilidad_teide.validacion import _claves

__all__ = ['CRITERIO_TERRITORIAL', 'MAGNITUD_ANUAL', 'SENTIDOS', 'actividad_comparacion_hot', 'calcular_aportes_anuales', 'coeficientes_cocheras_auxiliares', 'coeficientes_energia_resto', 'coeficientes_hot_interior_coche', 'comparar_anualmente_hot', 'comparar_con_lanzaderas', 'componentes_pendientes', 'comprobar_cocheras_en_extremos', 'contraste_umbral_interior_hot', 'desglosar_resto_sin_referencia', 'emparejar_retornos_condicionados', 'exposicion_lanzaderas_materialidad', 'impacto_separacion_turismos', 'incremento_por_perdida_rendimiento', 'integrar_coeficientes_materialidad', 'margen_para_componentes_pendientes', 'recorridos_interiores_coche', 'repartir_actividad_condicionada', 'revisar_cupo_y_oferta', 'revisar_elecciones_para_cierre', 'sensibilidad_interior_y_operacion', 'umbral_aporte_para_equilibrio', 'verificar_representacion_tecnica', 'verificar_reutilizacion_hot', 'verificar_reutilizacion_sensibilidad', 'verificar_reutilizacion_sin_cocheras']
