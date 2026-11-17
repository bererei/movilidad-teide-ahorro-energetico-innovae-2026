# Identificar las fuentes, las preparaciones y las referencias

La entrega corresponde al **informe v0.28**, con **2.500.000 visitas-persona anuales** sin y con intervención, las 31 condiciones del libro y el recorrido 00–07. El [inventario](../manifiestos/archivos.json) identifica los archivos de esta edición y sus huellas.

## Función de cada material

La [clasificación por archivo](../manifiestos/uso_y_vigencia.csv) distingue fuentes, preparaciones, resultados de comparación, productos aceptados y documentación. Un archivo declarado en un contrato es una dependencia identificada; una lectura para comprobar su huella no demuestra que todos sus valores entren en una fórmula. Las [matrices de trazabilidad](trazabilidad.md) relacionan el uso concreto con el código y los resultados.

| Material | Función en el estudio |
|---|---|
| Siete series originales de aforos | Preparar la demanda y estimar el reparto entre coches y autocares |
| Visor Teide, ODviewer y zonificación | Construir el reparto territorial, las asignaciones y sus controles; el mapa también se interpreta en la preparación |
| Instituto para la Diversificación y Ahorro de la Energía (IDAE) | Referencia del mecanismo de retención en descenso, sin medir su duración local |
| Informe para la Administración Federal de Transporte estadounidense (FTA) | Referencia del contraste por climatización y ralentí de autobuses |
| Documentación COPERT | Método y uso del programa; se distingue de los CSV de entrada y del motor |
| Centro Común de Investigación de la Comisión Europea (JRC, por Joint Research Centre) | Referencia institucional sobre COPERT |
| Marcas institucionales | Identificación editorial; sin efecto en el consumo calculado |

## Procedencia de las series de aforos

El Parque Nacional del Teide facilitó las siete series originales. El [registro de procedencia](../manifiestos/procedencia_series_aforos.csv) distingue suministro, correcciones recibidas y preparaciones realizadas para el estudio. Los libros y resultados derivados no se presentan como mediciones originales. Las condiciones aplicables y el fundamento de su inclusión están en la [guía de fuentes](distribucion_fuentes.md).

## Metadatos originales y estructura de esta entrega

Los metadatos de adquisición se conservan con los originales. Pueden mencionar nombres de carpetas anteriores o describir conjuntamente varios recursos. Se utilizan como evidencia de procedencia; el inventario vigente determina qué archivos se distribuyen. La reproducción utiliza las rutas relativas actuales y no necesita aquellas carpetas.

El [índice de documentación](../manifiestos/procedencia_documentacion_vigente.json) relaciona los apoyos de la referencia. Los seis apoyos citados mediante enlaces se identifican en [referencias_documentales.csv](../manifiestos/referencias_documentales.csv). Consultarlos ayuda a revisar el método; descargar sus copias completas no es un requisito informático.

## Referencias de cálculo y alcance

La ejecución distribuida está en `data/silver/ejecuciones/referencia_2028_final_20261116/`. Las nuevas ejecuciones se guardan en un destino nuevo de Silver y se comparan con los resultados técnicos de Gold. El [recorrido 00–07](recorrido_notebooks.md) explica el orden de lectura y la [guía de reproducción](reproduccion.md) concentra las instrucciones.

Las hipótesis de planificación, ocupación y operación se distinguen de observaciones y compromisos confirmados. La igualdad numérica verifica la reproducción bajo las condiciones fijadas; no certifica calibración local o disponibilidad operativa. La identidad del informe y de su copia firmada se consulta en la [guía documental](disponibilidad_documental.md), y el alcance de las comprobaciones de los paquetes en la [guía de entrega](entrega_publica.md).
