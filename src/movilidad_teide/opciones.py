"""Opciones del contrato de cálculo; sus elecciones permanecen en el Excel."""

CRITERIOS_MEZCLA = {
    'criterio_alquiler_procedencia': 'Fuera de Canarias en coche: alquiler',
    'criterio_residentes_coche': 'Tenerife: particular; España no Tenerife: dos alternativas',
    'criterio_sustitucion_turismos': 'Media comparable por servicio y combustible; resto media del servicio',
}

PARTICULAR = 'Particular sin especificar (B00)'

ALQUILER = 'Alquiler sin conductor (A01)'

COLECTIVOS = {'extranjero', 'espana_no_tenerife', 'tenerife_no_frecuente', 'tenerife_resto'}

METODO_CONSUMO = 'Distribución de tamaños y normas identificados entre comparables'

PATRONES_INTERIORES = {
    'Una zona próxima por entrada':'zona_proxima',
    'Zona Parador / Roques':'zona_parador',
    'Zona Teleférico':'zona_teleferico',
    'Ambas zonas':'ambas_zonas',
    'Eje completo (solo contraste)':'eje_completo',
}

HYBRID = 'Guagua urbana diésel híbrida'

HYBRID_ID = 'referencia_guagua_3'

PARK_INTERIOR = 'Zona próxima interior; acceso y salida en coche conservados'

PARK_ENTRADA = 'Entrada del eje; solo contraste de aparcamiento'

OFFICIALS = 'Misma actividad oficial en ambos escenarios'

REFUERZOS = 'Refuerzos interiores vinculados a reservas, conservando oferta base'

METODO_HORARIOS='Horarios conjuntos con reservas y oferta de acceso conservada'

PUNTOS={'TF21_BocaTauce_Granadilla':'VILAFLOR','TF21_Orotava_Portillo':'OROTAVA',
        'TF24_LaLaguna_Portillo':'LAGUNA','TF38_Chio_BocaTauce':'CHIO'}

DESTINOS={'VILAFLOR':'entrada_parador_tf21','CHIO':'entrada_parador_tf21',
          'OROTAVA':'entrada_teleferico_tf21','LAGUNA':'entrada_teleferico_tf21'}
