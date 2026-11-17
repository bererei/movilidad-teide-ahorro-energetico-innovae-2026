"""configuracion: catalogo. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import hashlib
import json
import math
from movilidad_teide.configuracion.parametros_tipos import ACCESOS
from movilidad_teide.configuracion.parametros_tipos import Campo
from movilidad_teide.configuracion.parametros_tipos import METODOS
from movilidad_teide.configuracion.parametros_tipos import ErrorParametros


def catalogo():
    """Definir significado y validación; los valores editables residen en Excel."""
    actividad = "Aplicado: actividad norte"
    campos = [
        Campo("anio_base", "General", "Año de aforos de partida", "año", "entero", 2025, 2025, aplicacion=actividad),
        Campo("anio_objetivo", "General", "Año del cálculo", "año", "entero", 2028, 2028, aplicacion=actividad),
        Campo("metodo_crecimiento", "Demanda", "Método de crecimiento", "método", "opcion", opciones=tuple(METODOS), aplicacion=actividad),
        Campo("anios_excluidos", "Demanda", "Años excluidos del ajuste histórico", "años separados por coma", "anios", aplicacion=actividad),
        Campo("cupo_global", "Reservas", "Máximo de coches privados para TODO el Parque", "coches/día", "entero", 0, aplicacion=actividad),
        Campo("reparto_cupo", "Reservas", "Cómo distribuir el cupo entre accesos", "método", "opcion", opciones=("Proporcional a entradas diarias", "Porcentajes manuales"), aplicacion=actividad),
        Campo("regimen_reserva_lanzaderas", "Reservas de lanzaderas", "Compra anticipada y asignación de horarios", "criterio", "opcion",
              opciones=("Compra anticipada con subida y regreso vinculados", "Sin cambio de franja de referencia"),
              aplicacion="Aplicado: propuesta de plazas vinculadas y refuerzos; no respuesta real observada"),
        Campo("referencia_guagua_acceso", "Vehículos de acceso", "Categoría COPERT provisional para las lanzaderas de acceso", "categoría", "opcion",
              opciones=("Autocar diésel de hasta 18 t", "Guagua urbana diésel de 15–18 t", "Guagua urbana diésel híbrida"),
              aplicacion="Aplicado: Hot de la propuesta de acceso; no selecciona el vehículo interior"),
        Campo("permanencia_min", "Reservas", "Duración máxima de permanencia", "minutos", "entero", 1),
        Campo("franja_reserva_min", "Reservas", "Duración de cada franja de reservas", "minutos", "entero", 1),
        Campo("calendario", "Servicio", "Calendario de las nuevas lanzaderas", "regla", "opcion", opciones=("Todo el año", "Número de días manual"), aplicacion=actividad),
        Campo("dias_servicio", "Servicio", "Días de servicio si se elige calendario manual", "días/año", "entero", 0, 366, aplicacion="Aplicado solo con calendario manual"),
        Campo("ocupacion_coche", "Personas y modos", "Ocupación de turismos: referencia agregada", "personas/coche", "numero", 1, aplicacion="Aplicado: conversión anual condicionada; Pendiente no activa la propuesta"),
        Campo("ocupacion_guagua_aforo", "Personas y modos", "Guaguas aforadas: ocupación de referencia", "personas/guagua", "numero", 1,
              aplicacion="Aplicado: contraste condicionado de aforos; no carga o plazas de nuevas lanzaderas"),
        Campo("criterio_pesos_turismos", "Flota de turismos", "Pesos dentro de cada servicio registrado", "criterio", "opcion",
              opciones=("Igual kilometraje medio dentro de cada servicio",),
              aplicacion="Aplicado: referencia condicionada de flota; no reparto particular/alquiler del Teide"),
        Campo("criterio_tamanos_turismos", "Flota de turismos", "Tratamiento de tamaños de turismos", "criterio", "opcion",
              opciones=("Todas las alternativas de tamaño", "Tamaño propuesto; resto alternativas"),
              aplicacion="Aplicado: contraste de tamaños y uso COPERT; Pendiente no activa aportes"),
        Campo("criterio_categoria_incompleta_turismos", "Flota de turismos", "Categoría europea vacía: tratamiento", "criterio", "opcion",
              opciones=("Conservar pendientes", "Contrastar tipo DGT si categoría vacía"),
              aplicacion="Aplicado: contraste condicionado; no imputa categoría M1 o reasigna N1"),
        Campo("criterio_norma_incompleta_turismos", "Flota de turismos", "Norma Euro vacía: tratamiento", "criterio", "opcion",
              opciones=("Conservar pendientes", "Contrastar normas consultadas si norma vacía"),
              aplicacion="Aplicado: referencias del combustible documentado; no imputa Euro o completa el dominio"),
        Campo("velocidad_turismo_local", "Turismos: circulación", "Velocidad media propuesta: calles locales", "km/h", "numero", 20, 100,
              aplicacion="Aplicado: referencia Hot EC por recorrido; solo nodos consultados, no velocidad medida"),
        Campo("velocidad_turismo_convencional", "Turismos: circulación", "Velocidad media propuesta: convencional y enlaces", "km/h", "numero", 20, 100,
              aplicacion="Aplicado: referencia Hot EC por recorrido; travesías no identificadas aparte"),
        Campo("velocidad_turismo_rapida", "Turismos: circulación", "Velocidad media propuesta: vías rápidas", "km/h", "numero", 20, 100,
              aplicacion="Aplicado: referencia Hot EC por recorrido; no límite legal o velocidad observada"),
        Campo("criterio_reparto_territorial_anual", "Demanda: distribución territorial", "Distribución anual condicionada entre orígenes", "criterio", "opcion",
              opciones=("Cuotas de personas de las 57 matrices por corredor fuente",),
              aplicacion="Aplicado: reparto condicionado para comparación anual parcial; no anualiza las 57 matrices"),
        Campo("alimentacion_coche", "Personas y modos", "Usuarios que llegan a cabecera en coche", "%", "porcentaje", 0, 1),
        Campo("transferencia_lanzadera", "Personas y modos", "Demanda no autorizada que pasa a lanzadera", "%", "porcentaje", 0, 1),
        Campo("induccion", "Personas y modos", "Demanda adicional causada por el sistema", "%", "porcentaje", 0, 1),
        Campo("plazas_guagua", "Capacidad", "Plazas nominales de la guagua publicada", "plazas/vehículo", "entero", 1),
        Campo("ocupacion_diseno", "Capacidad", "Proporción de plazas de diseño", "%", "porcentaje", 0, 1),
        Campo("flota_interior", "Interior", "Guaguas interiores del escenario publicado", "vehículos", "entero", 0),
        Campo("km_interior", "Interior", "Distancia interior de un sentido publicada", "km", "numero", 0),
        Campo("velocidad_copert", "Condiciones COPERT", "Velocidad de la prueba COPERT", "km/h", "numero", 1),
        Campo("carga_copert", "Condiciones COPERT", "Carga física de la prueba COPERT", "%", "porcentaje", 0, 1),
    ]
    for punto, nombre in ACCESOS.items():
        campos += [
            Campo(f"tasa_{punto}", "Demanda", f"Tasa anual manual: {nombre}", "%/año", "porcentaje", -.999999, aplicacion="Aplicado solo si se eligen tasas manuales"),
            Campo(f"cuota_{punto}", "Reservas", f"Porcentaje del CUPO DE COCHES: {nombre}", "%", "porcentaje", 0, 1, aplicacion="Aplicado solo con reparto manual del cupo"),
            Campo(f"personas_{punto}", "Personas y modos", f"Porcentaje de PERSONAS por acceso: {nombre}", "%", "porcentaje", 0, 1),
        ]
        for sufijo, etiqueta, unidad, tipo in [
            ("subidas", "Expediciones de subida al día", "expediciones/día", "entero"),
            ("bajadas", "Expediciones de bajada al día", "expediciones/día", "entero"),
            ("reposiciones", "Reposiciones equivalentes al día", "recorridos equivalentes/día", "numero"),
            ("km", "Distancia de un sentido", "km", "numero"),
            ("flota", "Guaguas de acceso disponibles", "vehículos", "entero"),
        ]:
            aplica = actividad if punto == "OROTAVA" and sufijo != "flota" else "Referencia: oferta de otros corredores o capacidad pendiente"
            campos.append(Campo(f"{sufijo}_{punto}", "Oferta por corredor", f"{etiqueta}: {nombre}", unidad, tipo, 0, aplicacion=aplica))
    dimensionamiento = "Aplicado: dimensionamiento de Medianías"
    campos += [
        Campo('captacion_extranjero', 'Captación del Visor', 'Turistas extranjeros que usarían el sistema', '%', 'porcentaje', 0, 1, aplicacion=dimensionamiento),
        Campo('captacion_nacional', 'Captación del Visor', 'Turistas nacionales no Tenerife que usarían el sistema', '%', 'porcentaje', 0, 1, aplicacion=dimensionamiento),
        Campo('captacion_local', 'Captación del Visor', 'Residentes no frecuentes que usarían el sistema', '%', 'porcentaje', 0, 1, aplicacion=dimensionamiento),
        Campo('captacion_frecuente', 'Captación del Visor', 'Residentes frecuentes y resto que usarían el sistema', '%', 'porcentaje', 0, 1, aplicacion=dimensionamiento),
        Campo('percentil_diseno', 'Método de diseño', 'Percentil de demanda para dimensionar', '%', 'porcentaje', 0.01, 1, aplicacion=dimensionamiento),
        Campo('umbral_demanda', 'Método de diseño', 'Demanda mínima para añadir oferta por demanda', 'personas/hora', 'numero', 0, None, aplicacion=dimensionamiento),
        Campo('hora_inicio_acceso', 'Horario de acceso', 'Primera hora incluida en los accesos', 'hora local del perfil', 'entero', 0, 23, aplicacion=dimensionamiento),
        Campo('hora_fin_acceso', 'Horario de acceso', 'Última hora incluida en los accesos', 'hora local del perfil', 'entero', 0, 23, aplicacion=dimensionamiento),
        Campo('regulacion_min', 'Operación', 'Tiempo de regulación por terminal', 'minutos', 'numero', 0, None, aplicacion=dimensionamiento),
        Campo('reserva_flota', 'Operación', 'Flota adicional de reserva', '%', 'porcentaje', 0, 1, aplicacion=dimensionamiento),
        Campo('hora_inicio_interior', 'Interior', 'Inicio del servicio interior', 'hora local del perfil', 'entero', 0, 23, aplicacion=dimensionamiento),
        Campo('hora_fin_interior', 'Interior', 'Fin del servicio interior, excluido', 'hora local del perfil', 'entero', 0, 24, aplicacion=dimensionamiento),
        Campo('min_buses_hora_interior', 'Interior', 'Frecuencia mínima por sentido del interior', 'expediciones/hora', 'entero', 0, None, aplicacion=dimensionamiento),
        Campo('min_ida_interior', 'Interior', 'Tiempo interior Portillo hacia Boca Tauce', 'minutos', 'numero', 1e-06, None, aplicacion=dimensionamiento),
        Campo('min_vuelta_interior', 'Interior', 'Tiempo interior Boca Tauce hacia Portillo', 'minutos', 'numero', 1e-06, None, aplicacion=dimensionamiento),
        Campo('fraccion_captados_coche', 'Personas y modos', 'Captados que habrían viajado en coche', '%', 'porcentaje', 0, 1, aplicacion='Aplicado: conversión condicionada; propuesta histórica distinta de la elección activa'),
        Campo("origen_oferta", "Servicio", "Cómo determinar expediciones de acceso", "método", "opcion",
              opciones=("Simulador de captación", "Expediciones manuales"), aplicacion=dimensionamiento),
    ]
    revision = "Aplicado: revisión operativa de Medianías; criterio pendiente"
    campos += [
        Campo("espera_max_lanzadera_min", "Revisión operativa", "Espera máxima admisible de la lanzadera", "minutos", "numero", 1, 1440, aplicacion=revision),
        Campo("estancia_min_visita_min", "Revisión operativa", "Estancia mínima para comprobar el regreso", "minutos", "numero", 1, 1440, aplicacion=revision),
    ]
    campos.append(Campo('anualizacion_personas', 'Personas y modos',
        'Anualización provisional de personas del Visor', 'método', 'opcion',
        opciones=('Media de meses 2025 por tipo de día','Sin anualizar'),
        aplicacion='Aplicado: referencia anual de personas/captación, sin crecimiento o conversión a coches'))
    campos.append(Campo('crecimiento_personas', 'Personas y modos',
        'Crecimiento común de viajes-persona del Visor', 'método', 'opcion',
        opciones=('Ajuste comparable del Visor 2022–2025','Tasa compuesta del Visor 2022–2025',
                  'Tasa compuesta del Visor 2023–2025','Sin crecimiento','Tasa comparable del Visor 2024–2025'),
        aplicacion='Aplicado: proyección de personas con tasa común; sin conversión a coches'))
    campos += [
        Campo('criterio_tara_turismos','Turismos: masa','Estadístico de tara por perfil DGT','criterio','opcion',
            opciones=('Mediana (P50)','Cuartil inferior (P25)','Cuartil superior (P75)'),
            aplicacion='Aplicado: ajuste anual condicionado de pendiente convencional; tara por grupo DGT, no peso por actividad'),
        Campo('masa_persona_turismo_kg','Turismos: masa','Masa de cálculo por ocupante, incluido conductor','kg/persona','numero',1,
            aplicacion='Aplicado: ajuste anual condicionado de pendiente convencional; hipótesis por ocupante, no medición visitante'),
        Campo('equipaje_turismo_kg_coche','Turismos: masa','Equipaje y carga adicional por turismo','kg/coche','numero',0,
            aplicacion='Aplicado: ajuste anual condicionado de pendiente convencional; carga adicional una sola vez por coche'),
    ]
    campos.append(Campo('distancias_actividad_lanzaderas','Actividad de lanzaderas',
        'Base de distancias para kilómetros de lanzaderas','criterio','opcion',
        opciones=('Recorridos del estudio','Referencias de distancia del Excel'),
        aplicacion='Aplicado: actividad por servicio/sentido; distancias publicadas conservadas para contraste'))
    for punto,nombre in ACCESOS.items():
        for sentido,etiqueta in [('ida','cabecera → Parque'),('vuelta','Parque → cabecera')]:
            campos.append(Campo(f'tiempo_{sentido}_{punto}_min','Tiempos de lanzaderas',
                f'Tiempo propuesto {nombre}: {etiqueta}','minutos','numero',.000001,
                aplicacion='Aplicado: propuesta de circulación; tiempo provisional, no observado ni velocidad COPERT'))
    campos += [
        Campo('tratamiento_regresos','Regresos propuestos','Tratamiento del regreso y cierre de servicio','criterio','opcion',
            opciones=('Horario inicial','Refuerzos de regreso','Horario coordinado'),
            aplicacion='Aplicado: circulación y actividad; refuerzos de cierre, no nueva demanda'),
        Campo('margen_enlace_interior_min','Regresos propuestos','Margen de planificación para enlaces interiores','minutos','numero',0,1440,
            aplicacion='Aplicado: prueba de enlace y refuerzos; distinto de regulación del vehículo'),
    ]
    campos.append(Campo('hora_limite_bajada_parque','Regresos propuestos',
        'Hora máxima de salida de bajada desde el Parque','hora local','numero',.000001,24,
        aplicacion='Aplicado: límite superior, no salida obligatoria igual; llegadas a cabeceras posteriores'))
    campos.append(Campo('intervalo_minimo_subidas_min','Regresos propuestos',
        'Separación mínima de planificación entre subidas','minutos','numero',1,1440,
        aplicacion='Aplicado: distribuir oferta de subida antes de reservas; no espera observada'))
    campos.append(Campo('alcance_consumo_anual','Alcance energético','Componentes de consumo de la primera comparación anual','criterio','opcion',
        opciones=('Solo consumo en caliente (Hot EC)',),
        aplicacion='Aplicado: comparación anual Hot en ambos escenarios; frío excluido, sin presumirlo nulo o cancelado'))
    campos.append(Campo('ubicacion_cocheras_lanzaderas','Cocheras de lanzaderas',
        'Estacionamiento al inicio y final del servicio','criterio','opcion',
        opciones=('Cabeceras de acceso y extremos del interior',),
        aplicacion='Aplicado: recorrido adicional base-extremo cero solo tras verificar horarios y equilibrio por terminal; maniobras/parado pendientes'))
    campos.append(Campo('perdida_rendimiento_guaguas_contraste','Sensibilidad de guaguas',
        'Reducción de km por unidad de combustible: solo contraste externo','%','porcentaje',0,1,
        aplicacion='Aplicado: sensibilidad externa; incremento de combustible=1/(1-p)-1, no corrección COPERT o estimación central de auxiliares'))
    from dataclasses import replace
    actualizados = []
    for c in campos:
        aplica = c.aplicacion
        if c.clave in {'hora_inicio_interior','hora_fin_interior'}:
            aplica='Referencia de dimensionamiento del Visor; con horario coordinado la apertura/cierre se derivan de accesos y última bajada'
        if c.clave=='tratamiento_regresos':
            aplica='Aplicado: horario inicial, refuerzos de referencia o coordinación previa a reservas; no demanda observada'
        if c.clave in {"plazas_guagua", "ocupacion_diseno", "km_interior"}:
            aplica = dimensionamiento
        elif c.clave == "flota_interior" or c.clave.startswith("flota_"):
            aplica = "Referencia publicada: comparar con flota calculada; disponibilidad pendiente"
        elif c.clave.startswith(("subidas_", "bajadas_", "reposiciones_")):
            aplica = "Aplicado solo con expediciones manuales; el simulador recalcula la oferta"
        elif c.clave.startswith("km_") and c.clave != "km_interior":
            aplica = "Aplicado: distancia de referencia; correspondencia geográfica pendiente"
        actualizados.append(replace(c, aplicacion=aplica))
    campos = actualizados
    from movilidad_teide.opciones import CRITERIOS_MEZCLA as CRITERIOS
    nombres = {
        'criterio_alquiler_procedencia': 'Fuera de Canarias: tipo de coche supuesto',
        'criterio_residentes_coche': 'Tenerife y grupo nacional mixto: tipo de coche',
        'criterio_sustitucion_turismos': 'Consumo estimado de turismos sin factor',
    }
    campos.extend(Campo(k, 'Turismos: hipótesis de cierre', nombres[k], 'criterio', 'opcion',
        opciones=(v,), aplicacion='Aplicado: mezcla por procedencia y sustitución explícita; no dato observado')
        for k, v in CRITERIOS.items())
    from movilidad_teide.opciones import METODO_CONSUMO as METODO
    campos.extend([
        Campo('criterio_consumo_representativo', 'Turismos: referencia principal', 'Consumo de referencia: ponderación de curvas', 'criterio', 'opcion', opciones=(METODO,),
              aplicacion='Aplicado: referencia técnica principal con tamaños/normas ponderados; no flota visitante medida'),
        Campo('control_primario_referencia', 'Turismos: referencia principal', 'Control nativo de gas y enchufables: referencia técnica', '%', 'porcentaje', 0, 1,
              aplicacion='Aplicado: mezcla lineal nativa verificada; no porcentaje de viajeros o energía eléctrica observado'),
    ])
    from movilidad_teide.opciones import PATRONES_INTERIORES as PATRONES
    campos.extend([
        Campo('patron_visita_coche_interior', 'Coches: circulación interior', 'Recorrido interior de referencia por visita', 'patrón', 'opcion', opciones=tuple(PATRONES),
              aplicacion='Aplicado: recorridos interiores de contraste; no frecuencia o destino observado'),
        Campo('fraccion_interior_sin', 'Coches: circulación interior', 'Sin actuación: visitas en coche que hacen el recorrido interior', '%', 'porcentaje', 0, 1,
              aplicacion='Aplicado: comparación interior si se elige; Pendiente conserva contraste, no cero'),
        Campo('fraccion_interior_autorizados', 'Coches: circulación interior', 'Con actuación: visitas autorizadas que hacen el recorrido en coche', '%', 'porcentaje', 0, 1,
              aplicacion='Aplicado: comparación interior si se elige; no confirma reglas futuras de circulación'),
    ])
    from movilidad_teide.opciones import HYBRID, PARK_INTERIOR, PARK_ENTRADA, OFFICIALS, REFUERZOS
    campos.extend([
        Campo('estrategia_refuerzo_interior','Interior: coordinación con reservas','Estrategia de salidas interiores adicionales','criterio','opcion',opciones=(REFUERZOS,),
              aplicacion='Aplicado: conserva salidas base, comparte plazas por tramo, añade enlaces necesarios y recalcula flota/vacíos/energía'),
        Campo('referencia_guagua_interior','Guaguas: respuesta de Luis','Categoría COPERT provisional para las nuevas guaguas interiores','categoría','opcion',opciones=(HYBRID,'Autocar diésel de hasta 18 t','Guagua urbana diésel de 15–18 t'),
              aplicacion='Aplicado: referencia energética de estudio; no cambia la previsión híbrida del suministro'),
        Campo('aparcamiento_reservado_referencia','Coches: aparcamiento y visita','Ubicación de referencia del aparcamiento reservado','criterio','opcion',opciones=(PARK_INTERIOR,PARK_ENTRADA),
              aplicacion='Aplicado: conservar acceso y salida en coche; referencia geométrica, no ubicación aprobada'),
        Campo('tratamiento_vehiculos_oficiales','Coches: excepciones','Tratamiento de la actividad oficial no cuantificada','criterio','opcion',opciones=(OFFICIALS,),
              aplicacion='Aplicado: hipótesis de cambio neto cero por actividad común; consumo total desconocido, no cero'),
        Campo('fraccion_visita_primera_zona','Coches: aparcamiento y visita','Visitas representadas por llegada a la zona interior próxima','%','porcentaje',0,1,
              aplicacion='Aplicado: referencia de visita tipo y sensibilidad; no porcentaje observado de destinos'),
        Campo('fraccion_visita_segunda_zona','Coches: aparcamiento y visita','Dentro de esas visitas, fracción que añade la otra zona','%','porcentaje',0,1,
              aplicacion='Aplicado: movilidad entre zonas antes y demanda colectiva después; no circulación privada autorizada'),
    ])
    from movilidad_teide.opciones import METODO_HORARIOS as METODO
    campos.extend([
        Campo('estrategia_horarios_conjuntos','Lanzaderas: horarios conjuntos','Estrategia de coordinación de accesos e interior','criterio','opcion',opciones=(METODO,),
              aplicacion='Aplicado: misma demanda y viajes de acceso; fases comunes del interior, flota por base, reserva y energía recalculadas'),
        Campo('banda_ultimas_bajadas_min','Lanzaderas: horarios conjuntos','Amplitud de la banda para las últimas bajadas por corredor','minutos','numero',0,120,
              aplicacion='Aplicado: última bajada de cada acceso entre cierre menos esta banda y cierre; propuesta operativa, no dato publicado'),
        Campo('vehiculos_contrato_contraste','Lanzaderas: flota y pliego','Vehículos del contrato para contrastar el dimensionamiento','vehículos físicos','entero',1,1000,
              aplicacion='Aplicado: techo numérico incluyendo reserva; no acredita asignación o disponibilidad para el Teide'),
    ])
    campos.append(Campo('cambio_neto_servicios_existentes_mwh_anio','Servicios existentes',
        'Cambio neto de consumo de servicios existentes: con menos sin','MWh/año','numero',
        aplicacion='Aplicado: diferencia anual de transporte; positivo aumenta consumo y reduce saldo, negativo exige reducción justificada; no incluye coches o nuevas lanzaderas ya calculados'))
    campos.append(Campo('criterio_guaguas_comunes','Consumos comunes','Referencia de consumo para guaguas existentes agrupadas','criterio','opcion',None,opciones=('Autocar diésel <=18 t Euro VI D/E; rural, 34 km/h, carga50%, pendiente0%',),aplicacion='Aplicado: totales y porcentaje del ámbito representado; complemento desconocido conserva ausencia'))
    campos.append(Campo('consumo_comun_complementario_mwh_anio','Consumos comunes','Consumo común adicional no representado, si se justifica','MWh/año','numero',0,opciones=(),aplicacion='Aplicado: totales y porcentaje del ámbito representado; complemento desconocido conserva ausencia'))
    campos.extend([
        Campo('eficiencia_incremental_gasolina_pendiente','Turismos: pendiente',
              'Conversión incremental de gasolina para sensibilidad de pendiente','fracción','numero',.000001,1,
              aplicacion='Aplicado: ajuste anual condicionado de gasolina convencional; régimen/fricción constantes, no calibración Teide'),
        Campo('eficiencia_incremental_diesel_pendiente','Turismos: pendiente',
              'Conversión incremental de diésel para sensibilidad de pendiente','fracción','numero',.000001,1,
              aplicacion='Aplicado: ajuste anual condicionado de diésel convencional; régimen/fricción constantes, no calibración Teide'),
        Campo('tratamiento_descenso_turismos','Turismos: pendiente',
              'Tratamiento del descenso en la sensibilidad de combustión convencional','criterio','opcion',
              opciones=('Corte ideal de inyección','Sin reducción de consumo en descenso'),
              aplicacion='Aplicado: ajuste anual condicionado H083 por tramo; corte de referencia y contraste sin reducción, no intervalo real'),
    ])
    campos.extend([
        Campo('reserva_minima_dentro_flota','Flota total y sustitución',
              'Mínimo de guaguas sin programar dentro de la flota total','vehículos','entero',0,
              aplicacion='Aplicado: propuesta D216 de inventario cerrado; no suma vehículos al techo ni sustituye la referencia porcentual histórica'),
        Campo('intervalo_refuerzo_punta_min','Flota total y sustitución',
              'Separación mínima propuesta en corredores que no cubren la punta con30min','minutos','numero',1,1440,
              aplicacion='Aplicado: propuesta excepcional D216 en corredores insuficientes; conserva30min ordinarios y los horarios construidos'),
    ])
    campos.append(Campo('tratamiento_central_guaguas','Presentación del balance',
        'Tratamiento de consumo de nuevas guaguas en el resultado central','criterio','opcion',
        opciones=('Hot COPERT','Hot con contraste operativo externo'),
        aplicacion='Aplicado: selección del resultado central vigente; FTA se conserva como sensibilidad separada, sin cambiar actividad'))
    return {c.clave: c for c in campos}


def _valor(valor, campo):
    """Interpretación estricta: vacío permanece ausente y nunca se usa eval."""
    if valor is None or valor == "": return None
    if isinstance(valor, str) and valor.startswith("="):
        raise ErrorParametros(f"{campo.nombre}: escribe un valor, no una fórmula.")
    if campo.tipo == "opcion":
        if valor not in campo.opciones: raise ErrorParametros(f"{campo.nombre}: opción no reconocida.")
        return valor
    if campo.tipo == "anios":
        if str(valor).strip().casefold() == "ninguno": return []
        try: valores = [int(v.strip()) for v in str(valor).split(",") if v.strip()]
        except ValueError as exc: raise ErrorParametros(f"{campo.nombre}: usa años separados por coma.") from exc
        if not valores or len(set(valores)) != len(valores) or any(not 1900 <= v <= 2100 for v in valores):
            raise ErrorParametros(f"{campo.nombre}: años repetidos o fuera del ámbito.")
        return valores
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ErrorParametros(f"{campo.nombre}: valor numérico no válido.")
    if campo.tipo == "entero" and valor != int(valor): raise ErrorParametros(f"{campo.nombre}: debe ser entero.")
    if campo.minimo is not None and valor < campo.minimo or campo.maximo is not None and valor > campo.maximo:
        raise ErrorParametros(f"{campo.nombre}: valor fuera de límites ({campo.unidad}).")
    return int(valor) if campo.tipo == "entero" else float(valor)

def _firma_referencias(propuestas):
    """Sellar el punto de partida tolerando solo el redondeo de almacenamiento Excel."""
    def normalizar(v):
        if isinstance(v, float): return format(v, ".14g")
        if isinstance(v, dict): return {k: normalizar(x) for k, x in v.items()}
        if isinstance(v, list): return [normalizar(x) for x in v]
        return v
    return hashlib.sha256(json.dumps(normalizar(propuestas), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
