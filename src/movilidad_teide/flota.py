"""Interfaz compatible; las responsabilidades se organizan en vehiculos."""

from movilidad_teide.vehiculos.catalogo_copert import contrastar_familias_catalogo, leer_claves_copert, proponer_claves_desde_microdatos, resumir_segmentos_catalogo, revisar_claves_copert

from movilidad_teide.vehiculos.composicion import construir_referencias_turismos, contrastar_registros_incompletos_turismos, desglosar_referencias_tecnicas_turismos, preparar_aportes_tamanos_turismos, preparar_mezcla_stock_turismos, revisar_cobertura_turismos

from movilidad_teide.vehiculos.dgt import agregar_microdatos_parque, clasificar_microdatos_parque, clasificar_tamanos_turismos, leer_microdatos_parque, leer_modelos_turismos_dgt, leer_taras_turismos_dgt, resumir_tamanos_turismos, vincular_taras_a_perfiles

from movilidad_teide.vehiculos.flota_tipos import ErrorFlota

from movilidad_teide.vehiculos.parque import _nombre_es, acotar_cruce_marginal, composicion_validada, proponer_cuotas_energia, proponer_familias_turismos, proponer_guaguas, seleccionar_istac

__all__ = ['ErrorFlota', 'acotar_cruce_marginal', 'agregar_microdatos_parque', 'clasificar_microdatos_parque', 'clasificar_tamanos_turismos', 'composicion_validada', 'construir_referencias_turismos', 'contrastar_familias_catalogo', 'contrastar_registros_incompletos_turismos', 'desglosar_referencias_tecnicas_turismos', 'leer_claves_copert', 'leer_microdatos_parque', 'leer_modelos_turismos_dgt', 'leer_taras_turismos_dgt', 'preparar_aportes_tamanos_turismos', 'preparar_mezcla_stock_turismos', 'proponer_claves_desde_microdatos', 'proponer_cuotas_energia', 'proponer_familias_turismos', 'proponer_guaguas', 'resumir_segmentos_catalogo', 'resumir_tamanos_turismos', 'revisar_claves_copert', 'revisar_cobertura_turismos', 'seleccionar_istac', 'vincular_taras_a_perfiles']
