# Reconstruir recorridos, distancias y perfiles desde Bronze

Este paso reconstruye la geografía utilizada por la referencia de **2.500.000 visitas-persona anuales**, conservando el catálogo de recorridos, las cabeceras, las trazas de cada sentido y todas las restricciones vigentes. Comprueba la equivalencia de las preparaciones; no busca rutas nuevas ni recalcula consumo o ahorro.

La entrada narrativa es [02 · Recorridos y pendientes](../notebooks/02_recorridos_y_pendientes.ipynb), después de 00–01. La etapa registrada recibe la demanda de su misma ejecución y añade la clasificación vial sin energía. El comando independiente descrito aquí reconstruye las 118 tablas geográficas; por sí solo no incluye esa clasificación adicional. Son rutas alternativas, no dos pasos obligatorios para preparar la misma geografía.

## Ejecutar

Con código, entorno y datos de la misma entrega, siguiendo la [guía general](reproduccion.md), desde la raíz de cualquiera de los dos repositorios:

```bash
uv run python scripts/reproducir_geografia_bronze.py reproducir --destino data/silver/ejecuciones/geografia_01
```

El destino debe ser nuevo. Primero se preparan los datos desde Bronze y configuración. Durante esa fase se pueden leer los terrenos que el propio proceso acaba de convertir en su destino nuevo, pero no las preparaciones Silver o Gold anteriores. Después se comparan las salidas con las referencias distribuidas.

Las fases se pueden ejecutar por separado:

```bash
uv run python scripts/reproducir_geografia_bronze.py preparar --destino /tmp/geografia_nueva
uv run python scripts/reproducir_geografia_bronze.py comparar --resultados /tmp/geografia_nueva --destino data/silver/ejecuciones/comparacion_geografia_01
```

La primera fase necesita únicamente código, configuración, el contrato y los archivos Bronze enumerados. Para comparar se añaden las referencias Silver. Se utiliza el mismo comando y las mismas rutas relativas en desarrollo y publicación. No se consulta Internet para volver a adquirir trazas o terreno: cambiar esas fuentes sería otra referencia de cálculo.

| Salida dentro del destino nuevo | Contenido |
|---|---|
| `terrenos/` | Modelos de terreno reconstruidos desde las respuestas originales |
| `tablas/operativos/` | Perfiles y pendientes de los cinco recorridos de lanzadera, en ambos sentidos |
| `tablas/origenes/` y `tablas/costa/` | Comparaciones físicas de acceso: recorridos directos y cadenas por cabecera, con perfiles propios |
| `tablas/referencias/` | Las 82 referencias dirigidas de cálculo: longitudes, sentidos, itinerarios y anclajes |
| `tablas/cabeceras/` | Las 54 distancias del catálogo de reasignación y los perfiles de acceso ordinario y de refuerzo seleccionados |
| `tablas/titsa/` | Los cuatro perfiles completos de las líneas 342/348 y sus 1.182 segmentos físicos |
| `indice_tablas.csv` y `metadatos.json` | Dimensiones, fuentes, restricciones, lecturas, código, entorno y huellas |
| `comprobacion/` | Las comparaciones de equivalencia y su resumen |

Se generan **118 tablas**. Se realizan **116 comparaciones: 115 con Silver y una con el catálogo nativo de Bronze**. Dos tablas adicionales de segmentos de los accesos reasignados son apoyos calculados sin una referencia histórica individual propia. La matriz `manifiestos/trazabilidad_preparacion_geografia.csv` declara la cobertura exacta de cada salida y las columnas comparadas.

## Fuentes y método

| Parte | Fuente y transformación conservadas |
|---|---|
| Ejes y puntos de referencia | Archivos originales de carreteras del Cabildo, datos de OpenStreetMap —cartografía abierta—, paradas y trazas GTFS —formato de datos de transporte público— y decisiones documentadas del catálogo |
| Terreno | Respuestas WCS originales —servicio de descarga de coberturas— del MDT05 del IGN, modelo digital del terreno con celdas de 5 × 5 m; conversión a GeoTIFF sin alterar cotas o malla |
| Ampliaciones | Copia de celdas de la misma malla, preservando la base y comprobando el solape; ocho respuestas originales de ampliaciones y soporte para accesos a cabeceras se reincorporan a Bronze |
| Perfiles | Estaciones cada 200 m y extremos exactos; método y fase específicos ya definidos en el catálogo, con interpolación bilineal donde corresponde y las mismas muestras por sentido |
| Pendientes físicas | Diferencia de altitud dividida por longitud entre estaciones; conservar valores fuera de ±6 %, sin recortarlos al rango de factores COPERT |
| Reasignación de cabeceras | Geometrías originales de OSRM —motor de cálculo de rutas—; seleccionar el primer soporte bilineal completo, ordenado por área de cobertura y nombre, según el criterio del productor |
| TITSA | Trazas completas del GTFS original: dos sentidos de la 342 y dos de la 348; muestreo de terreno y cálculo de segmentos, sin reutilizar sus perfiles Silver |

**Las dos distancias de las rutas OSRM se distinguen.** La respuesta nativa proporciona kilómetros y minutos; la geometría proyectada proporciona la longitud sobre la que se sitúan las muestras del perfil. Ambas se reconstruyen y se contrastan con el catálogo. La posterior unión con clases de vía y la normalización de los segmentos a la distancia de actividad energética son una transformación adicional, fuera de este comando.

El proceso reconstruye 31 comparaciones territoriales de acceso y conserva los regresos propios. En las 82 referencias dirigidas se aplican las aproximaciones territoriales declaradas en configuración. La referencia condicional con demanda media nula mantiene sus distancias ausentes: el proceso exige una revisión si esa demanda pasa a ser positiva, en vez de inventar un recorrido.

### Resolución de dependencias

Tres auxiliares del catálogo remitían a GeoPackage de TITSA preparados previamente. El comando resuelve sus paradas y trazas directamente desde el ZIP GTFS nativo, en memoria, manteniendo puntos y geometrías. Registra esta resolución sin cambiar el catálogo maestro, inventar coordenadas o materializar carpetas anteriores.

Las ocho respuestas originales de ampliación de terreno y sus metadatos se conservan en `data/bronze/geografia/mdt05/ampliaciones_cabeceras_20261109/` y `data/bronze/geografia/mdt05/refuerzos_cabeceras_20261109/`. Sus conversiones de referencia se localizan en las mismas materias de Silver. El proceso puede reconstruirlas desde Bronze aunque Silver esté vacío. Las fuentes documentales de cabeceras y recorrido interior también quedan disponibles con sus bytes originales.

En una ampliación encadenada puede ocurrir que la base ya declare los huecos como NaN —marca numérica de ausencia— y que una nueva respuesta completa no declare ausencias. Se armoniza únicamente esa representación de metadatos en una copia. Antes de unir se comprueba que **no cambia ninguna celda ni máscara de validez**. No se rellena terreno, suaviza, cambia la interpolación o altera la resolución. Las huellas de los terrenos reconstruidos se contrastan con las ya configuradas o documentadas.

Algunos perfiles originales guardan nombres absolutos de antiguas carpetas de trabajo. El contrato traduce solo esas cadenas documentales a las rutas comunes actuales. Ninguna lectura necesita aquellas carpetas y no se crea un puente físico hacia ellas.

## Resultado y límites de la comprobación

Las 116 comparaciones son equivalentes. La **diferencia máxima de coordenadas es cero** y la **diferencia numérica máxima es 1,4210854715202004 × 10⁻¹⁴**, conservando la tolerancia absoluta de 10⁻⁸. Se comprueban tipos, vértices y orden de las geometrías, sus sistemas de referencia de coordenadas —CRS—, filas, claves, ausencias, cotas, pendientes y soportes de interpolación. Las cifras no se redondean para conseguir coincidencia.

La prueba de aceptación oculta el desarrollo y los archivos de trabajo originales y presenta Silver y Gold vacíos. La conexión de red se bloquea durante la preparación. Se utiliza un entorno independiente previamente instalado con las versiones fijadas; esa comprobación no acredita otra instalación del entorno. Se conserva evidencia del código, las fuentes y los resultados.

Esta es una comprobación informática. Las cotas son del terreno, **no una medición de la rasante de la carretera**; se mantiene la interpretación provisional del CRS del terreno norte ya declarada en configuración. No se acredita circulación autorizada, aptitud de paradas, conexiones a aparcamientos, maniobras o disponibilidad operativa.

Se compara completo el contenido de perfiles y segmentos geográficos. En las tablas de longitudes y las 82 referencias se comparan las columnas físicas e identificadores enumerados; sus textos de diagnóstico y los atributos territoriales adicionales de la demanda quedan fuera. Tampoco se reconstruye aquí la clasificación vial ni la unión de segmentos y coeficientes energéticos. Su alcance es la equivalencia geográfica en las columnas declaradas; la clasificación vial y la aplicación energética se comprueban por separado.

El contrato está en `manifiestos/preparacion_geografia_bronze.json`; la evidencia resumida, en `manifiestos/comprobacion_entrega_final.json`. El código se organiza en `src/movilidad_teide/cartografia/preparacion*.py` y el flujo de ejecución en `src/movilidad_teide/flujos/preparacion_geografia.py`.

La [clasificación, los coeficientes y el balance](preparacion_balance.md) completan esa unión con entradas técnicas fijas explícitas; las 116 comparaciones geográficas mantienen el alcance aquí descrito.
