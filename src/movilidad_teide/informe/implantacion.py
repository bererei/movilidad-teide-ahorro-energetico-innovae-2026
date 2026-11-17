"""Condiciones de implantación: propuesta documental, sin nuevos datos o hipótesis."""
from .integracion import _longtable
def preparar_implantacion(destino):
    rows=[
    ['Reservas y atención','Definir cadena completa y capacidad por tramo; probar confirmación, cancelación, reasignación y contingencia; disponer de atención digital y alternativa.','Cabildo y operador: responsable designado y prueba del proceso completo antes de abrir reservas.'],
    ['Cupo y control de acceso','Definir autorización, excepciones y recuento para el máximo global de 650 y puntuales de 700/750; comprobar su aplicación.','Cabildo y gestor de acceso: regla y procedimiento antes de confirmar reservas.'],
    ['Cabeceras y recorridos','Confirmar emplazamientos, capacidad de aparcamiento, trazados, paradas y enlaces; contrastar con distancias del cálculo.','Cabildo y responsables de emplazamientos: planos y autorizaciones antes de cerrar el servicio.'],
    ['Flota y sustitución','Asegurar treinta propias, bases y programa variable; dos sustitutas externas disponibles al programar treinta, con conductor y respuesta.','Cabildo y operador: disponibilidad, localización y procedimiento de sustitución antes de programar.'],
    ['Viajeros y operación','Comprobar plazas por tramo, ida/regreso, estancia, horarios, regulación y continuidad; dimensionar personal.','Operador con supervisión del Cabildo: programa completo y comprobaciones antes de confirmar reservas.'],
    ['TITSA y excursiones','Acordar retirada o mantenimiento real de servicios, transferencia de viajeros y alimentación; evitar contar dos veces actividad o ahorro.','Cabildo y operadores: acuerdo y oferta detallada antes de aplicar el cambio modal.'],
    ['Vehículo y consumo','Confirmar prestaciones finales y contrastar tiempos, combustible, auxiliares, vacíos y posicionamiento; recalcular si cambia la operación.','Operador y equipo técnico: ficha de vehículo, prueba de servicio y balance revisado antes del cierre operativo.'],
    ['Puntas e incidencias','Preparar respuestas completas de refuerzo, reasignación y cupo; registrar déficit y energía adicional.','Cabildo y operador: protocolo, recursos y validación de cada cambio antes de confirmar transporte.'],
    ['Coordinación y continuidad','Relacionar actuaciones tecnológicas, medios de transporte, financiación y programación; designar responsables y cerrar las evidencias pendientes.','Cabildo y operador: decisiones documentadas y actualización antes del servicio.']]
    _longtable(destino/'tablas/vigente/implantacion_condiciones.tex','Decisiones y evidencias propuestas para implantar el sistema',['Condición','Acción y evidencia de cierre','Responsable y momento propuestos'],rows,widths=[29,68,51])
    return {'condiciones_documentadas':len(rows),'compromisos_confirmados_por_esta_tabla':False}
