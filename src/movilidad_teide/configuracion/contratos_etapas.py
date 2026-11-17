"""Contrato único de etapas del recorrido registrado; no contiene hipótesis numéricas."""
ETAPAS = {
    '01': dict(nombre='Fuentes y demanda', dependencias=[], acciones=['calcular'], unidades='Visitas-persona, personas/día tipo, fracciones y fechas'),
    '02': dict(nombre='Recorridos, pendientes y clasificación vial', dependencias=['01'], acciones=['calcular'], unidades='Metros, kilómetros, cotas en metros, pendientes en porcentaje y coordenadas con CRS'),
    '03': dict(nombre='Representación técnica del parque', dependencias=[], acciones=['registrar_datos_fijados'], unidades='Categorías y proporciones técnicas; selección fijada identificada'),
    '04': dict(nombre='Servicio de transporte y actividad', dependencias=['01','02'], acciones=['comprobar'], unidades='Personas, vehículos físicos, expediciones, minutos y vehículos-kilómetro'),
    '05': dict(nombre='Factores COPERT', dependencias=[], acciones=['consultar','ejecutar_motor'], unidades='MJ/km; categorías, velocidades en km/h, pendientes en porcentaje y fracción de carga'),
    '06': dict(nombre='Coeficientes, balance y sensibilidades', dependencias=['01','02','03','04','05'], acciones=['calcular'], unidades='MWh, tep, visitas-persona y valores por visita según columna'),
    '07': dict(nombre='Comprobación de equivalencia', dependencias=['01','02','03','04','05','06'], acciones=['comparar'], unidades='Diferencias en las unidades originales; tolerancias de los contratos existentes'),
}
