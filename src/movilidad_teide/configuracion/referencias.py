"""configuracion: referencias. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import json
from pathlib import Path


def _referencias(root):
    """Importación inicial de fuentes existentes; nunca se ejecuta al leer elecciones."""
    import csv
    root = Path(root)
    cfg = json.loads((root / "config/actividad_corredor_norte.json").read_text())
    visor = root / "data/silver/movilidad/visor_teide/20261016T154509Z_f7cda5fc"
    filas = list(csv.DictReader((visor / "tablas_publicadas/tab-dimensionamiento-medianias_05.csv").open(encoding="utf-8-sig"), delimiter=";"))
    rutas = list(csv.DictReader((visor / "rutas_modelo_publicado.csv").open(encoding="utf-8-sig"), delimiter=";"))
    comparacion = list(csv.DictReader((root / "data/silver/aforos_teide/comparacion_tendencias.csv").open(encoding="utf-8-sig"), delimiter=";"))
    valores = {
        "anio_base": 2025, "anio_objetivo": 2028,
        "metodo_crecimiento": "Ajuste histórico con exclusión temporal", "anios_excluidos": "2020,2021",
        "cupo_global": 500, "reparto_cupo": "Proporcional a entradas diarias",
        "calendario": "Todo el año", "ocupacion_coche": 3.2,
        "plazas_guagua": 55, "ocupacion_diseno": .85, "flota_interior": 5,
        "km_interior": 29, "velocidad_copert": 34, "carga_copert": .5,
    }
    cabeceras = {"OROTAVA": "Aguamansa", "VILAFLOR": "Vilaflor", "LAGUNA": "La Esperanza TF24", "CHIO": "Intercambiador oeste TF38"}
    def numero_es(v): return float(v.replace(".", "").replace(",", "."))
    for punto, cabecera in cabeceras.items():
        f = next(f for f in filas if f["Centro de intercambio"] == cabecera)
        corredor = {"OROTAVA": "TF21_Orotava_Portillo", "VILAFLOR": "TF21_BocaTauce_Granadilla", "LAGUNA": "TF24_LaLaguna_Portillo", "CHIO": "TF38_Chio_BocaTauce"}[punto]
        r = next(f for f in rutas if f["arquitectura"] == "medianias" and f["corredor"] == corredor)
        valores.update({f"subidas_{punto}": int(numero_es(f["Subidas/día"])), f"bajadas_{punto}": int(numero_es(f["Bajadas/día"])), f"reposiciones_{punto}": numero_es(f["Reposiciones equivalentes"]), f"flota_{punto}": int(numero_es(f["Flota acceso"])), f"km_{punto}": float(r["km_un_sentido_modelo"])})
        tasa = next(f for f in comparacion if f["punto"] == punto and f["sentido"] == "ambos_sentidos" and f["metodo"] in {cfg["tendencia"]["metodo_central"], "ajuste_log_lineal_con_exclusiones"})
        valores[f"tasa_{punto}"] = float(tasa["tasa_anual"])
    from movilidad_teide.operacion.dimensionamiento import referencias_dimensionamiento
    valores.update(referencias_dimensionamiento(root))
    # Antecedente histórico para el cálculo condicionado, sin activarlo por defecto.
    valores["fraccion_captados_coche"] = .7387
    valores['alcance_consumo_anual'] = 'Solo consumo en caliente (Hot EC)'
    valores['perdida_rendimiento_guaguas_contraste'] = .10
    valores['ubicacion_cocheras_lanzaderas'] = 'Cabeceras de acceso y extremos del interior'
    valores["regimen_reserva_lanzaderas"] = "Compra anticipada con subida y regreso vinculados"
    valores["referencia_guagua_acceso"] = "Autocar diésel de hasta 18 t"
    valores["criterio_pesos_turismos"] = "Igual kilometraje medio dentro de cada servicio"
    valores["criterio_tamanos_turismos"] = "Tamaño propuesto; resto alternativas"
    valores["criterio_categoria_incompleta_turismos"] = "Contrastar tipo DGT si categoría vacía"
    valores["criterio_norma_incompleta_turismos"] = "Contrastar normas consultadas si norma vacía"
    valores.update({"velocidad_turismo_local":20,"velocidad_turismo_convencional":40,"velocidad_turismo_rapida":80})
    valores["criterio_reparto_territorial_anual"] = "Cuotas de personas de las 57 matrices por corredor fuente"
    # Antecedente de2019 conservado, no ocupación medida en2024/2025.
    ocupaciones = list(csv.DictReader((root / 'data/silver/movilidad/ocupacion_vehiculos/revision_memorias/20261016T135034Z/ocupaciones_referencia.csv').open(encoding='utf-8-sig'), delimiter=';'))
    referencia = next(f for f in ocupaciones if f['anio_memoria']=='2019')
    valores['ocupacion_guagua_aforo'] = float(referencia['personas_por_guagua_o_vehiculo_largo'])
    valores["anualizacion_personas"] = "Media de meses 2025 por tipo de día"
    valores["crecimiento_personas"] = "Tasa comparable del Visor 2024–2025"
    valores.update({'criterio_tara_turismos':'Mediana (P50)', 'masa_persona_turismo_kg':75, 'equipaje_turismo_kg_coche':None})
    valores['distancias_actividad_lanzaderas']='Recorridos del estudio'
    valores.update(tratamiento_regresos='Refuerzos de regreso',margen_enlace_interior_min=10,hora_limite_bajada_parque=18,intervalo_minimo_subidas_min=30)
    from movilidad_teide.opciones import CRITERIOS_MEZCLA as CRITERIOS
    valores.update(CRITERIOS)
    from movilidad_teide.opciones import METODO_CONSUMO as METODO
    valores.update(criterio_consumo_representativo=METODO,control_primario_referencia=.5)
    valores['patron_visita_coche_interior']='Una zona próxima por entrada'
    from movilidad_teide.opciones import HYBRID, PARK_INTERIOR, OFFICIALS, REFUERZOS
    valores.update(estrategia_refuerzo_interior=REFUERZOS,referencia_guagua_interior=HYBRID,aparcamiento_reservado_referencia=PARK_INTERIOR,
        tratamiento_vehiculos_oficiales=OFFICIALS,fraccion_visita_primera_zona=1.,fraccion_visita_segunda_zona=0.)
    from movilidad_teide.opciones import METODO_HORARIOS as CONJUNTO
    valores.update(estrategia_horarios_conjuntos=CONJUNTO,vehiculos_contrato_contraste=30,banda_ultimas_bajadas_min=30)
    valores['cambio_neto_servicios_existentes_mwh_anio'] = 0.
    valores.update({'criterio_guaguas_comunes': 'Autocar diésel <=18 t Euro VI D/E; rural, 34 km/h, carga50%, pendiente0%', 'consumo_comun_complementario_mwh_anio': None})
    valores.update(eficiencia_incremental_gasolina_pendiente=.34, eficiencia_incremental_diesel_pendiente=.408, tratamiento_descenso_turismos='Corte ideal de inyección')
    valores.update(reserva_minima_dentro_flota=3, intervalo_refuerzo_punta_min=15)
    valores['tratamiento_central_guaguas']='Hot COPERT'
    return cfg, valores

def _fundamento(campo):
    if campo.clave == 'tratamiento_central_guaguas':
        return ('D218: Hot de COPERT como estimación central condicionada por indicación expresa. Conservar el incremento FTA como sensibilidad externa, con su amplitud en el control de pérdida de rendimiento; no convertir auxiliares pendientes en cero ni acreditar cumplimiento independiente de las condiciones.',
                'Mi autorización del01/11/2026; D162/D166/D183/D216/D217. F126 FTA/WVU2007, p.9: criterio externo para contraste, sin validación local.',
                'Elección de método/presentación para el estudio; no consumo real calibrado o aprobación operativa')
    if campo.clave == 'reserva_minima_dentro_flota':
        return ('D216: evaluar un mínimo absoluto de tres unidades libres dentro de las30 existentes, con hasta27 programadas en punta. Las no programadas ya cuentan como sustitución; no añadir otro porcentaje por encima de30. En días de menor demanda quedan más libres. Es una propuesta de estudio por indicación expresa; disponibilidad y respuesta por base sin acreditar.',
                'Mi aclaración del01/11: máximo30 guaguas y estudiar dejar tres de reserva. D214/D215 conservados; reserva20% del Visor como contraste histórico.',
                'Propuesta operativa para evaluación; no tasa de averías observada o aprobación institucional')
    if campo.clave == 'intervalo_refuerzo_punta_min':
        return ('D216: contrastar15min solo en corredores/observaciones cuya demanda supera la cota favorable de30min. Reutiliza las construcciones D193/D197/D214 con enlaces y estancia comprobados; no inventa duraciones ni cambia demanda. Mantener30min ordinarios y registrar cada excepción. La regla no queda aprobada por el encaje numérico.',
                'D142/H091: separación30min como propuesta de organización editable. D193/D197/D214: construcciones conservadas de15min en punta.',
                'Propuesta operativa excepcional evaluada; validación del Cabildo/operador pendiente')
    if campo.clave in {'eficiencia_incremental_gasolina_pendiente','eficiencia_incremental_diesel_pendiente'}:
        return ('D211/D212: referencia incremental indicada EPA de 0,40 gasolina o 0,48 diésel, multiplicada por transmisión 0,85. Aproximación a régimen y fricción constantes; no eficiencia media del viaje. Se utiliza en sensibilidad, sin validar la flota de montaña.',
                'F144 EPA420-P-05-001, Draft febrero2005, pp.9–10 y24; F119 transmisión0,85. F146 MOVES5/2024 sigue citando el mismo borrador.',
                'Hipótesis técnica de sensibilidad; no parámetro medido del Teide')
    if campo.clave == 'tratamiento_descenso_turismos':
        return ('D212: adoptar corte ideal E=max(Ebase+m*g*dh/eta,0), con energías en MJ y Wg=m*g*dh/1e6. En retención se permite cortar inyección; con tracción positiva sigue habiendo consumo. Mantener sin reducción de consumo en descenso como sensibilidad. No promediar extremos ni afirmar corte en toda la bajada o conservadurismo del ahorro neto sin comparación sin/con.',
                'F147 IDAE, Estilo de conducción, puntos6–10 y recordatorio sobre marcha engranada y régimen; H083/D211. Deducción de estudio autorizada el01/11/2026.',
                'Referencia simplificada convencional; no perfil de revoluciones observado o calibración Teide')
    if campo.clave in {'criterio_guaguas_comunes','consumo_comun_complementario_mwh_anio'}:
        return ('D184/H122: aproximar personas no-coche del caso principal con la ocupación histórica de guaguas35,99 y recorridos representativos existentes de ida/regreso y visita próxima. Incluye TITSA y excursiones agregadas, sin sumarlas de nuevo ni convertir pasos de aforo en visitas. Uso autocar diésel <=18t Euro VI D/E, factor nativo rural a34km/h, carga50% y pendiente0% como referencia de escala del consumo común; no flota existente medida, pendiente real nula o factor conservador. Afecta a totales y porcentaje, no al ahorro absoluto al mantenerse igual antes/después. Comparar otros nodos como diagnóstico, sin llamarlos intervalo real. El complemento permite incorporar consumo común adicional acreditado fuera de la representación; mientras falte, permanece desconocido y no cero.', 'D183/H121 referencia principal; F042 ocupación, F038 aforos para cuota; F073/COPERT factores nativos conservados y recorridos disponibles; D182/H120 continuidad energética; D184/H122', 'Aproximación técnica de visitas modelizadas; complemento sin estimar. No inventario GTFS, actividad oficial individual o consumo total exhaustivo del Parque.')
    if campo.clave=='cambio_neto_servicios_existentes_mwh_anio':
        return ('D182/H120: referencia simplificada de continuidad de TITSA341/342/348, excursiones, oficiales y otros servicios mantenidos: mismo consumo agregado sin/con. El0 expresa diferencia por hipótesis, no combustible nulo o igualdad medida. H032 solo mantiene oferta TITSA; H120 añade expresamente continuidad energética al ensayo, sin atribuir ahorro por pasajeros que cambian de modo o por guaguas compradas para el nuevo sistema. Sin retirada o refuerzo documentado de esos servicios, no invento expediciones. Si se justifica un cambio, editar Manual y Motivo: positivo=mayor consumo con actuación; negativo=reducción. No repetir coches, alimentadores, nuevas lanzaderas, vacíos o contraste de auxiliares ya sumados. Instalaciones fijas fuera por D181.',
                'H032/D054 — continuidad de oferta TITSA F045/F052; F127 — nuevas híbridas y excepción oficial; H114 — oficiales comunes; D180 — sin ahorro atribuido al modo previo; D182/H120 — aproximación técnica explícita de estudio',
                'Hipótesis de continuidad aplicada al ensayo; no consumo observado, cota conservadora o cancelación probada por horarios. Demanda, visitas, carga y otros efectos conservan sus límites.')
    if campo.clave=='banda_ultimas_bajadas_min':
        return ('D173/H116: propongo que la última bajada de cada corredor se sitúe en la media hora previa al cierre18:00, es decir17:30–18:00. Evita reducir flota adelantando excesivamente el final de algunos accesos y mantiene margen para coordinar el interior. Es una decisión técnica de planificación coherente con la petición de horarios prácticos; no una hora publicada por el Visor ni una regla aprobada. Parámetro independiente del intervalo entre subidas.', 'Indicación de revisar conjuntamente horarios prácticos y coherentes; cierre18:00 provisional acordado y D173/H116', 'Propuesta técnica aplicada y contrastada; aceptación y operación real pendientes')
    if campo.clave in {'estrategia_horarios_conjuntos','vehiculos_contrato_contraste'}:
        return ('D173/H116: coordinar llegadas de cuatro accesos con salidas interiores y regreso reservado. Conservar demanda diaria y viajes comerciales de cada acceso/sentido; mantener oferta interior mínima de D157, espera20/margen10, estancia120 desde llegada al Parque y cierre18. Búsqueda determinista acotada, sin mínimo global demostrado. Primero flota física por base para todos los días, después Hot anual; añadir reserva20% del Visor. El pliego incluye30 vehículos, también utilizables en otros servicios: contraste numérico, no disponibilidad confirmada. No modificar demanda o plazas para alcanzar el objetivo energético.',
                'F062 pliego TITSA pp.2–3 y5; F035 Visor, tabla de dimensionamiento Medianías y reserva20%; F127 híbridas; D157/D172 horarios y demanda; D173/H116',
                'Propuesta técnica de horarios y límite de contraste; disponibilidad y operación real pendientes')
    from movilidad_teide.operacion.criterios_estudio import NUEVOS as LUIS_NUEVOS
    if campo.clave=='estrategia_refuerzo_interior':
        return ('D172: reservo ida y regreso a la misma cabecera. Conservo toda la oferta comercial base y priorizo plazas interiores existentes por tramo; añado salidas completas solo cuando la construcción necesita enlaces, sin reducir demanda. Recalculo guaguas, reposiciones y consumo híbrido. No certifica mínimo global, disponibilidad o tiempo real de viaje.', 'F127; D157 reservas anticipadas; D172/H114 coordinación por tramos con espera20/margen10 y estancia120 desde llegada al Parque', 'Propuesta operativa construida y comprobada, pendiente de viabilidad real')
    if campo.clave in LUIS_NUEVOS:
        return ('D172: respuesta de Luis F127 confirma híbridas ECO/Euro6 y ausencia de circulación privada tras aparcar, con excepción oficial sin cantidad. H114 representa cada visita tipo por llegada a un núcleo próximo, conservando acceso/salida al aparcamiento en ambos escenarios; una zona como referencia, otras frecuencias/dos zonas en sensibilidad. Actividad oficial común como hipótesis, no consumo nulo. H115 usa la referencia urbana híbrida disponible como sustituto técnico, sin marca/modelo/masa verificados.',
                'F127 respuesta de Luis transcrita por Beatriz; F073 catálogo COPERT; D170/H112 consumo turismos; D172/H114/H115',
                'Criterios futuros confirmados y aproximaciones técnicas diferenciados; no previsión validada o porcentaje de visita observado')

    if campo.clave in {'patron_visita_coche_interior','fraccion_interior_sin','fraccion_interior_autorizados'}:
        return ('D171/H113: recorridos documentados de ida/regreso al mismo acceso, con consumo D170. Núcleo próximo como referencia geográfica entre Parador/Roques y Teleférico, sin frecuencia observada o carácter conservador del ahorro. Las cuotas permanecen pendientes; los contrastes muestran su efecto sin adoptar automáticamente100% o una cuota que dé ahorro.',
                'D163/H105 patrones sobre el eje interior; D170/H112 consumo ponderado; P033 regla de circulación autorizada pendiente; D171/H113',
                'Distancias calculadas, frecuencia no medida y condiciones de estudio explícitas')

    if campo.clave in {'criterio_consumo_representativo','control_primario_referencia'}:
        return ('D170/H112: conservar combustible, tamaño y norma conocidos. Estimar dimensiones ausentes con frecuencias de modelos DGT identificados entre comparables, ampliando el grupo solo cuando faltan donantes y documentando el reparto uniforme residual. Control nativo0,5 como referencia técnica simétrica para gas/enchufables; linealidad COPERT comprobada, no uso real medido. Contrastar controles0/1 y referencias anteriores; no promediar sus extremos para elegir el principal.',
                'F072 DGT2025; F123 tamaños documentados; D148 linealidad nativa; D169 sustitución; D170/H112',
                'Hipótesis técnica para estudio, no consumo medido o certeza sobre flota visitante')

    from movilidad_teide.opciones import CRITERIOS_MEZCLA as CRITERIOS
    if campo.clave in CRITERIOS:
        return ('D168/H110/H111: alquiler para fuera de Canarias únicamente entre viajes en coche. Tenerife particular como aproximación; España no Tenerife conserva dos asignaciones agregadas porque no separa otras islas. Para consumo sin factor, media ponderada de comparables por servicio/combustible y composición del servicio si faltan; originales y aporte sustituido separados.',
                'D168/H110/H111 — hipótesis de estudio y fuentes DGT/COPERT/Visor conservadas',
                'Supuestos, no observaciones; sensibilidad y demás condiciones modales pendientes')

    """Texto legible de las referencias, incluidos sus límites y estado."""
    k = campo.clave
    if k == 'perdida_rendimiento_guaguas_contraste':
        return ('Referencia externa de sensibilidad: el informe FTA/WVU2007 reduce10% las millas por galón por climatización/ralentí no reflejados en su ensayo. A igual distancia equivale a11,111% más combustible, no10%. Solo ensayo exploratorio sobre Hot identificado de nuevas guaguas; no dato Teide, límite conservador, corrección nativa COPERT o incremento real. No sumar a otra estimación de los mismos consumos.',
                'F126 — FTA-WV-26-7004.2007.1, Fuel Costs, página impresa9/PDF18; D166/H108. F125: módulo A/C publicado no cubre guaguas.',
                'Referencia para contraste; elección pendiente. Contexto estadounidense, unos12m y modelo2007; aplicabilidad local sin validar')
    if k == 'ubicacion_cocheras_lanzaderas':
        return ('Asumo estacionamiento en las cabeceras de las cuatro lanzaderas de acceso y en Boca Tauce/El Portillo para el servicio interior. En la representación puntual no hay recorrido adicional entre base y extremo. Compruebo inicio/fin y equilibrio de vehículos por terminal; conservo reposiciones existentes. No acredita instalaciones, maniobras o consumo parado nulos.',
                'Mi elección explícita del 30/10 y aclaración del estacionamiento interior; D165/H107; simplificación de extremos H059',
                'Hipótesis adoptada para estudio; sin ubicación construida o validación operativa')
    if k == 'alcance_consumo_anual':
        return ('Uso factores Hot EC en ambos escenarios para cerrar la primera comparación anual. Excluyo el exceso de consumo durante calentamiento; no afirmo que sea cero, despreciable, cancelado o conservador. Mantengo demás componentes sin cuantificar como pendientes y la conversión modal como condicionada.',
                'Mi indicación expresa del 30/10/2026; COPERT Factors > Hot/Cold; D162/H104',
                'Hipótesis adoptada para la primera versión; energía final completa y validación pendientes')
    if k=='intervalo_minimo_subidas_min':
        return ('Propongo30 minutos para no concentrar las capacidades adelantadas en pocos minutos. La oferta fuente del caso es principalmente horaria; media hora permite refuerzo repartido, no acredita llegada real de personas o espera admisible. Los últimos regresos se redondean con un paso de la mitad de este intervalo (15 min en este caso) y una referencia común de llegada derivada del cierre máximo y el regreso más corto. No es una obligación de terminar todos a la misma hora.', 'D142/H091 — regla técnica de planificación; F035 — oferta fuente y H088 tiempos por sentido', 'Propuesta de organización provisional, editable y no observada')
    if k=='hora_limite_bajada_parque':
        return ('Adopto provisionalmente las18:00 como última salida de bajada desde el Parque por mi elección explícita. Las llegadas a cabecera son posteriores según el recorrido. Coordino subidas, interior y refuerzos dentro del cierre, conservando la demanda original y mostrando qué oferta exige organizar otra franja. No horario oficial, aceptación medida o visita anual trasladada automáticamente.', 'D141/H090 — mi elección explícita en el chat; H088 tiempos y H089 margen de planificación', 'Criterio provisional elegido para el estudio')
    if k=='tratamiento_regresos':
        return ('Conservo la oferta inicial del Visor y añado solo capacidades de regreso faltantes bajo los criterios de revisión. El cierre interior no genera otra cohorte que requiera vuelta indefinida. Recalculo vehículos, reposición y kilómetros. Si estancia sigue pendiente se usa únicamente su referencia propuesta, identificada como tal. No operación aprobada ni demanda nueva.', 'D139/D140/H089 — ampliación de regresos y cierre escalonado; F035 — oferta inicial; H041 — misma visita', 'Propuesta operativa provisional para el cálculo')
    if k=='margen_enlace_interior_min':
        return ('Propongo 10 minutos como margen técnico de planificación en terminal para revisar el enlace. Reutilizo la escala temporal de regulación publicada por el Visor como referencia práctica, pero son magnitudes distintas: no medición de caminata, embarque, accesibilidad o transbordo. Puede revisarse independientemente; 0 solo sería cota favorable. No añado otra estancia de visita al interior.', 'D140/H089 — propuesta propia de margen; F035 — regulación de 10 min como referencia de escala, no evidencia de tiempo de transferencia', 'Hipótesis de diseño sin validación de transbordo')
    if k.startswith(('tiempo_ida_','tiempo_vuelta_')):
        punto=k.split('_')[2]
        if punto in {'OROTAVA','VILAFLOR'}:
            return ('Referencia entre paradas comparables del GTFS conservado:348 Aguamansa–El Portillo o342 Castaños–Boca Tauce. Máximo de tiempos programados retenidos redondeado al siguiente múltiplo de5 minutos para planificar. No medición, observaciones independientes o garantía de tiempos de nuevas cabeceras.', 'F045 — GTFS2026–2027; D138/H088 — pares de paradas y referencia programada', 'Hipótesis de planificación por sentido')
        return ('No hay referencia del mismo recorrido. Proxy30 km/h de planificación: mediana de equivalencias longitud del estudio/tiempo GTFS de tres pares comparables, redondeada a5 km/h. Tiempo longitud/30 y redondeo superior a5 minutos; no velocidad observada, límite de vía, condición COPERT o cota conservadora.', 'F045 — GTFS; perfiles operativos; D138/H088 — transferencia provisional a Chío y La Esperanza', 'Hipótesis provisional entre corredores; no validación vial/operativa')
    if k == 'distancias_actividad_lanzaderas':
        return ('Utilizo las longitudes por sentido de los perfiles operativos existentes para los recorridos definidos en el estudio. Las distancias publicadas/manuales del Excel permanecen como referencias y pueden elegirse como alternativa explícita. No cambio tiempos proporcionalmente a la distancia ni doy por validados horarios, flota o accesos internos.', 'D137/H086 — catálogo y perfiles operativos del estudio; F065/F066/F075; referencias del Visor conservadas', 'Elección provisional de alcance para actividad; operación pendiente')
    if k == 'criterio_tara_turismos':
        return ('Propongo mediana de la tara utilizable del mismo perfil DGT, sin promediar cuantiles ni identificar tamaño comercial. P25/P75 describen dispersión registral, no límites o intervalo de incertidumbre de visitantes.', 'F072/F073 — DGT2025; D134 — taras por perfil; D135/H084', 'Propuesta pendiente de elección')
    if k == 'masa_persona_turismo_kg':
        return ('Propongo75 kg por ocupante como simplificación a partir de la masa estándar del conductor del Reglamento General de Vehículos. Extenderla a pasajeros es una hipótesis de estudio, no una obligación normativa o media medida. La ocupación ya incluye al conductor.', 'F121 — RD2822/1998, anexoIX §§1.1–1.3; D135/H084', 'Propuesta pendiente; no masa observada de visitantes')
    if k == 'equipaje_turismo_kg_coche':
        return ('Sin dato de equipaje/carga por turismo en el Teide. Exige una elección explícita y motivada; no se rellena con cero ni con la carga útil máxima. Se suma una sola vez por coche, no por persona.', 'D135/H084; masa en carga del anexoIX del Reglamento General de Vehículos; equipaje no observado', 'Pendiente de hipótesis justificada')
    if k == 'crecimiento_personas':
        return ('D130/H082: comparar nueve referencias regulares 2024/2025, todas Formato2025 y calendario fijo2025. Anclar2025 y aplicar una tasa común provisional; solo un intervalo, no previsión robusta. Las tasas2022–2025 mezclan formatos y quedan como diagnósticos. No crecimiento por cohortes, tasas de coches o calibración de escalas.', 'F035 — Visor Teide, catálogo con versiones y perfiles; D130/H082', 'Propuesta provisional del mismo formato; expansión y tendencia pendientes de validación')
    if k == 'anualizacion_personas':
        return ('Mi elección del 28/10: media de marzo, julio y octubre de 2025 por tipo de día, expandida al calendario. Lunes-viernes aproxima laborable sin reclasificar festivos. Captación del Excel antes del p85. No crecimiento de personas, asignación anual de orígenes, coches retirados ni energía; estacionalidad pendiente.', 'D127/H080 — elección de aproximación anual; F035 — Visor Teide, matrices y simulador Medianías', 'Aproximación adoptada para primera referencia anual')
    if k == 'espera_max_lanzadera_min':
        return ("Criterio de servicio pendiente de elegir y justificar. La revisión conserva cotas de espera por bloques horarios; sin minutos de salida no acredita una espera exacta ni transporte efectivo.", "Revisión de cobertura y retornos del 23/10/2026; no hay un límite acordado", "Pendiente de elección operativa")
    if k == 'estancia_min_visita_min':
        return ("Tiempo mínimo de visita para revisar retornos por la misma cabecera. No es la permanencia máxima de los coches con reserva. Sin elección calculo solo una cota favorable sin estancia; no adopto cero como duración real.", "Mi regla de regreso H041 y revisión operativa del 23/10/2026; estancia sin dato", "Pendiente de elección operativa")
    if k in {'min_vuelta_interior', 'hora_fin_interior', 'min_buses_hora_interior', 'fraccion_captados_coche', 'captacion_extranjero', 'hora_inicio_acceso', 'captacion_frecuente', 'captacion_nacional', 'percentil_diseno', 'regulacion_min', 'captacion_local', 'hora_inicio_interior', 'min_ida_interior', 'umbral_demanda', 'reserva_flota', 'hora_fin_acceso', 'origen_oferta'}:
        fuente = "F035 — Visor Teide, simulador de Medianías; JavaScript conservado y parámetros publicados"
        if k.startswith("captacion_"):
            return "Coeficiente del escenario Base turístico del Visor. Se aplica a cada colectivo antes del percentil. Es utilización propuesta del sistema, no fracción demostrada de coches retirados ni respuesta medida al cupo.", fuente, "Hipótesis de diseño publicada"
        if k == "fraccion_captados_coche":
            return "La memoria oficial de 2019, p. 140 (PDF p. 142), estima el 73,87 % de visitantes en coche. Trasladarlo a captados supone igual reparto modal previo, sin evidencia de independencia entre modo y captación. Solo cálculo condicionado, no medición de 2028 o elección central.", "F042 — Memoria de actividades 2019 del Parque Nacional del Teide, p. 140; D144/H093", "Antecedente prepandemia; caso central pendiente por indicación expresa"
        if k == "origen_oferta":
            return "Uso el simulador para ajustar expediciones y flota a la captación elegida. Expediciones manuales mantiene los valores anteriores como elección explícita y requiere comprobar su capacidad.", "Mi decisión del 23/10/2026: dimensionamiento adaptable basado en el Visor", "Regla de cálculo adoptada"
        if k == "percentil_diseno":
            return "P85 de las observaciones disponibles, calculado después de aplicar captación. No es ocupación de asientos ni una previsión anual; sumar percentiles horarios no da el percentil del total diario.", fuente, "Método de dimensionamiento"
        return "Valor del simulador para reproducir horarios, flota y regulación. Interior sirve a las mismas visitas, no añade entradas; regreso por la misma cabecera, con horarios y permanencia por comprobar.", fuente, "Referencia operativa provisional"
    if k in {"anio_base", "anio_objetivo"}:
        return "Acuerdo de trabajo: aforos 2025 y cálculo 2028. Esta primera conexión está preparada para esos años.", "Contexto del modelo y plan de entradas", "Marco de esta versión"
    if k in {"calendario", "dias_servicio"}:
        return "Mantengo el servicio nuevo constante todos los días del año, 366 en 2028 (H035). El número manual de días solo se usa si se elige ese calendario y se justifica.", "H035 — hipótesis adoptada de servicio anual constante; F035 — oferta del Visor Teide", "Hipótesis adoptada para la primera prueba"
    if k in {"plazas_guagua", "ocupacion_diseno"}:
        return "El Visor Teide usa guaguas de 55 plazas y un 85 % de plazas de diseño. Es capacidad de planificación, distinta de la carga física del 50 % de COPERT; todavía no limita la oferta calculada.", "F035 — Visor Teide, Base turístico / Medianías; tabla de dimensionamiento", "Referencia publicada; capacidad pendiente de conectar"
    if k in {"flota_interior", "km_interior"}:
        return "El diseño Base turístico / Medianías publica 5 guaguas interiores y 29 km de un sentido. Son referencias del servicio interior, distinto de las tres guaguas por acceso; actividad, trazado y consumo aún pendientes.", "F035 — Visor Teide, Base turístico / Medianías; servicio interior", "Referencia publicada; interior pendiente de conectar"
    if k in {"cupo_global", "permanencia_min", "franja_reserva_min"}:
        return "Máximo global 500 coches/día, trabajadores, turistas y otros; todos con reserva y permanencia. Duración y franjas aún sin dato.", "H034 — decisión de reserva y cupo del 20/10/2026", "Acuerdo; detalles horarios pendientes"
    if k.startswith("cuota_") or k == "reparto_cupo":
        return "Referencia: proporción de entradas proyectadas de cada día; no reparto equitativo. Un reparto manual debe sumar 100 %. No implica reparto de personas.", "H036 — aproximación técnica proporcional; aforos F038", "Hipótesis técnica provisional"
    if k.startswith("personas_") or k in {"alimentacion_coche", "transferencia_lanzadera", "induccion"}:
        return "Sin valor respaldado para este colectivo. ODviewer aporta viajes de personas; aforos aportan pasos de vehículos. Faltan asignación modal, grupos y recorridos.", "ODviewer F040/F041; preguntas de cambio modal P026", "Pendiente; no se sustituye por cero"
    if k == "ocupacion_guagua_aforo":
        return ("35,99 personas/guagua es la ocupación implícita aproximada reconstruida para2019:4.443.628 visitantes×26,13%/32.261guaguas. No es medición independiente o actual. Trasladarla uniformemente a aforos2024/2025 y tomar su categoría guagua como transporte de pasajeros son hipótesis del contraste; no describe las nuevas lanzaderas.",
                "F042 — memoria2019, pp.136 y140 (PDF138 y142), y memoria2021 p.193 (PDF197); revisión de ocupación conservada; D145/H094",
                "Referencia histórica para cálculo condicionado; elección pendiente")
    if k == "regimen_reserva_lanzaderas":
        return ("Las visitas reservan antes de viajar una subida y un regreso con plazas vinculadas. Para planificar admito otra franja ofrecida el mismo día, sin imponer las horas históricas de llegada ni eliminar demanda. Esto no acredita aceptación real, cambios de fecha o reservas efectivas. Mantengo el cupo de coches separado de las plazas de lanzadera.",
                "Mi decisión de compra anticipada para laminar visitas; D157/H099", "Hipótesis adoptada para el estudio; sistema real pendiente")
    if k == "referencia_guagua_acceso":
        return ("Uso provisionalmente el autocar diésel de hasta18t de la biblioteca COPERT para los cuatro accesos. No atribuyo esa categoría al interior ni doy por confirmados masa, tecnología, norma o disponibilidad de la futura guagua ECO. Conservo factores y alternativas previos.",
                "Mi elección de referencia de acceso; biblioteca COPERT D131; pliego TITSA F062; D157/H100", "Referencia adoptada para estudio; ficha técnica pendiente")
    if k == "criterio_reparto_territorial_anual":
        return ("Propongo repartir las cantidades anuales D144 por las cuotas medias de personas de las 57 matrices dentro de cada corredor fuente, colectivo y sentido. Las cantidades anuales no proceden de multiplicar esas medias: se conservan las referencias anuales D127 y su proyección. Supongo que esa distribución espacial representa también a los captables de origen coche; no está observada por origen durante todo el año. No cambia corredores fuente por cabeceras del estudio ni completa los orígenes sin ámbito anual. La elección Central sigue pendiente.",
                "F035 — Visor Teide; D125/D126 — correspondencias geográficas; D127/D144 — actividad anual condicionada; D154/H096 — hipótesis espacial propuesta",
                "Propuesta de simplificación territorial; no adoptada por defecto")
    if k.startswith("velocidad_turismo_"):
        return ("Propongo20/40/80 km/h para calles locales, convencional/enlaces y vías rápidas como puntos de trabajo sobre nodos COPERT ya consultados. No son velocidades medidas ni se deducen de maxspeed, tiempos GTFS o pendientes. Solo se admiten nodos con factores disponibles(20,40,60,80,100); no interpolo. Contrasto el nodo contiguo inferior/superior sin presentarlo como intervalo estadístico. La agrupación OSM a entorno es una aproximación y puede incluir travesías.",
                "F124 — significado de etiquetas OSM; bibliotecas COPERT D146–D149; D153/H095 — velocidades técnicas propuestas, no datos observados",
                "Propuesta propia revisable; pendiente de elección")
    if k == "criterio_categoria_incompleta_turismos":
        return ("Propongo un contraste separado usando el tipo DGT TURISMOS cuando la categoría europea está vacía. Conservo el vacío, no escribo M1 ni asimilo N1 u otras categorías contradictorias. Requiere combustible y referencias compatibles, junto al criterio de norma si también falta. Es aproximación de estudio, no reclasificación documental o flota visitante observada.",
                "F072/F073 — DGT2025, tipo y categoría; D147/D152/H009 — aproximación condicionada para vacíos",
                "Propuesta no adoptada; categoría original conservada")
    if k == "criterio_norma_incompleta_turismos":
        return ("Propongo comparar las curvas completas ya consultadas del combustible documentado cuando el campo original de norma está vacío. Conservo la norma vacía y las claves nativas sin malla; no asigno Euro por edad/distintivo, ni traslado curvas a literales informados sin equivalencia revisada. Son referencias comparativas, no dominio completo, consumo real, límites conservadores o media elegida.",
                "F072 — campos DGT; bibliotecas COPERT verificadas D146–D149; D152/H009 — contraste sin norma imputada",
                "Propuesta no adoptada; dominio consultado incompleto explícito")
    if k == "criterio_tamanos_turismos":
        return ("Propongo conservar el tamaño de las familias documentadas D150 y comparar todos los tamaños nativos disponibles para el resto, sin asignarles porcentajes. Los controles de gas/PHEV siguen como alternativas separadas, no uso observado. No imputa norma, categoría o energía a registros sin factores; no calcula una media completa ni activa la propuesta por defecto.",
                "F072 — DGT2025; F123 — familias y puente comercial propuestos; D148–D151/H009 — factores y contraste condicionado",
                "Propuesta de representación para contraste; composición visitante y uso pendientes")
    if k == "criterio_pesos_turismos":
        return ("Propongo usar las cuotas del stock DGT 2025 identificado dentro de cada servicio como pesos, solo bajo igual kilometraje medio por vehículo. No es actividad observada del Teide ni fija cuánto alquiler circula. Conservo desconocidos y denominadores completos; no elijo tamaños o uso de tecnologías y no obtengo una media completa. Composición futura pendiente de contraste.",
                "F072 — microdatos DGT 2025; D146–D149/H009 — referencias y contraste condicionado, sin nueva medición de actividad",
                "Propuesta de estudio, no adoptada por defecto")
    if k == "ocupacion_coche":
        return "Propuesta histórica 3,2: próxima a cocientes reconstruidos para 2019 y 2021 (aprox. 3,18 y 3,19). No es medición de 2025 ni dato por colectivo.", "F042 — revisión de memorias del Parque, LEEME y páginas identificadas en Silver", "Propuesta pendiente de adoptar"
    if k.startswith("tasa_") or k in {"metodo_crecimiento", "anios_excluidos"}:
        return "Ajuste de log(media diaria) frente al año real, excluyendo 2020–2021 e incidencias; contraste con tasas compuestas entre extremos. No imputa 2024 ni identifica causalmente COVID.", "H033 — propuesta de crecimiento; F038 — aforos integrados", "Propuesta técnica provisional"
    if k in {"velocidad_copert", "carga_copert"}:
        return "Condiciones de los siete factores del piloto: 34 km/h y 50 % de carga física. Cambiarlas requiere factores compatibles; no se aplican desde esta conexión de actividad.", "F039 — reproducción CLI COPERT 5.10.1; configuración piloto", "Referencia del piloto; no controla COPERT todavía"
    return "Oferta de Base turístico / Medianías publicada en el Visor. Tres guaguas por acceso; las expediciones son totales del corredor. Días de servicio según H035; capacidad, trazado y otros vacíos pendientes.", "F035 — Visor Teide; H035 — servicio anual constante", "Propuesta publicada / primera prueba"
