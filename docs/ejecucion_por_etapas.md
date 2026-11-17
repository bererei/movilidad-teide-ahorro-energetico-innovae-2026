# Seguir el cálculo mediante una ejecución registrada

Esta guía es la entrada principal para ejecutar las etapas conectadas. Se mantienen las **2.500.000 visitas-persona anuales en ambos escenarios** y las condiciones del Excel. El [registro inicial](configuracion_ejecuciones.md) identifica la configuración y la entrega; el historial de etapas añade qué se ha realizado, con qué entradas y qué productos pueden utilizarse después.

[00 · Inicio](../notebooks/00_inicio_y_referencia.ipynb) abre el recorrido oficial 00–07. Todos sus cuadernos utilizan estas funciones y el mismo registro; [07 · Comprobación](../notebooks/07_comprobacion_e_informe.ipynb) completa la comparación y la navegación documental. Los comandos de esta guía ofrecen las mismas etapas para quien prefiera ejecutarlas fuera del cuaderno. El informe y los anexos están alineados con este recorrido y conservan los datos aceptados.

## 1. Una ejecución y productos con procedencia

Cada etapa recibe la ruta del mismo registro y localiza sus dependencias desde disco. No hay que copiar archivos entre carpetas ni conservar variables de un cuaderno anterior. Antes de ejecutar se comprueban la configuración, el código, las entradas y los productos ya aceptados.

El registro inicial permanece inmutable. Se añaden sucesos de **inicio**, **etapa completada** o **etapa fallida**, enlazados por huellas SHA-256. El índice de estado identifica el último suceso. Cada cierre válido conserva las dependencias concretas y, para sus productos, ruta relativa, tamaño, huella, formato, papel y contexto de unidades. Las unidades detalladas y el significado de las columnas siguen los contratos, productores y diccionarios del estudio.

Las comprobaciones de integridad se distinguen del cálculo: leer los bytes de una referencia para verificar su huella no equivale a utilizar sus cifras para construir un resultado. Las referencias Silver y Gold de comparación se identifican separadamente de las entradas que necesita la preparación.

## 2. Qué hace cada etapa

| Etapa | Acción | Productos y dependencia efectiva |
|---|---|---|
| 01. Demanda | Calcular desde Bronze | Tablas de fuentes y demanda, conservando tipos en Parquet y la lectura CSV. Utiliza las condiciones del registro |
| 02. Geografía | Calcular recorridos, perfiles y clasificación vial | Recibe la demanda territorial de 01; produce perfiles y segmentos físicos, catálogo resuelto y clasificación para el balance |
| 03. Parque | Registrar la selección técnica fijada | Copia e identifica las entradas técnicas seleccionadas. Se conserva la decisión existente; no se presenta como nueva selección automática desde bruto |
| 04. Servicio y actividad | Comprobar la programación fijada | Recibe demanda de 01 y distancias de 02; verifica personas, plazas, idas y regresos, existencias de vehículos y kilómetros. Identifica los programas e insumos físicos que utilizará 06 |
| 05. COPERT | Consultar factores distribuidos o ejecutar el motor expresamente | Produce bibliotecas normalizadas y comparación de factores. Su origen queda identificado; las consultas fijas son autocontenidas y no reciben los kilómetros anuales de 04 |
| 06. Energía | Calcular coeficientes, balance y sensibilidades | Consume los productos de 01–05. Recibe factores de 05, selección técnica de 03, programación de 04 y perfiles de 02; no vuelve a construir demanda o geografía ni toma sus coeficientes previos como entrada |
| 07. Comprobación | Comparar los resultados con las referencias | Contrasta demanda, geografía y balance en una fase posterior; produce tablas de diferencias y un resumen integrado. No actualiza el informe ni sus anexos |

El orden recomendado de lectura conserva **04 Servicio → 05 COPERT → 06 Balance**. La tabla distingue ese relato de las dependencias numéricas: por ejemplo, 03 y las consultas fijas de 05 pueden prepararse independientemente. La etapa 07 comprueba resultados y trazabilidad; la generación del informe se realiza mediante el comando documental indicado en la guía de reproducción.

Los programas de servicio se comprueban con las restricciones vigentes: cupo ordinario de 650 coches y hasta 27 propias programadas, reservas de sustitución y opciones de punta adoptadas. Este recorrido reproduce y comprueba esa programación; no busca horarios nuevos ni acredita por sí solo disponibilidad contractual o funcionamiento real.

## 3. Comandos para un recorrido completo

Después de reunir código y datos de la misma entrega e instalar el entorno según la [guía general](reproduccion.md), se elige una carpeta de ejecución nueva. Las rutas relativas parten de la raíz del proyecto.

```bash
uv run python scripts/registrar_ejecucion.py iniciar --destino data/silver/ejecuciones/mi_cadena_01 --modo reproduccion
uv run python scripts/ejecutar_etapa.py ejecutar --registro data/silver/ejecuciones/mi_cadena_01 --etapa 01
uv run python scripts/ejecutar_etapa.py ejecutar --registro data/silver/ejecuciones/mi_cadena_01 --etapa 02
uv run python scripts/ejecutar_etapa.py ejecutar --registro data/silver/ejecuciones/mi_cadena_01 --etapa 03
uv run python scripts/ejecutar_etapa.py ejecutar --registro data/silver/ejecuciones/mi_cadena_01 --etapa 04
uv run python scripts/ejecutar_etapa.py ejecutar --registro data/silver/ejecuciones/mi_cadena_01 --etapa 05 --accion consultar
uv run python scripts/ejecutar_etapa.py ejecutar --registro data/silver/ejecuciones/mi_cadena_01 --etapa 06
uv run python scripts/ejecutar_etapa.py ejecutar --registro data/silver/ejecuciones/mi_cadena_01 --etapa 07
uv run python scripts/ejecutar_etapa.py estado --registro data/silver/ejecuciones/mi_cadena_01
```

Cada comando puede ejecutarse desde una sesión nueva. La acción de 05 se indica expresamente para que quede claro que este ejemplo utiliza exportaciones COPERT distribuidas, no una ejecución nueva de su motor. Las demás etapas calculan, registran o comparan lo indicado en la tabla; el modo solicitado al crear el registro no sustituye esas acciones efectivas.

También se puede utilizar `ejecutar_etapa(RAIZ, ruta_registro, "02")` desde Python, importando la función de `movilidad_teide.flujos.etapas_registradas`. `RAIZ` identifica la copia elegida en esa sesión. Los comandos anteriores ofrecen el mismo punto de entrada sin depender de memoria compartida.

## 4. Cuándo se ejecuta realmente COPERT

En 05, `consultar` normaliza las exportaciones distribuidas y comprueba sus factores con la referencia de las consultas públicas. Queda registrada como consulta, aunque la procedencia original de esas exportaciones indique una ejecución anterior del motor.

La acción `ejecutar_motor` requiere el ejecutable instalado y una carpeta de intercambio nueva y accesible desde Windows, según la [guía COPERT](reproduccion_copert.md). Se proporcionan `--copert` y `--intercambio` al mismo comando de etapa. El adaptador llama al ejecutor existente, conserva sus registros y copia los productos al intento de 05. Solo un cierre completado con esa acción acredita una ejecución nueva en el resumen del recorrido. Una solicitud fallida no se presenta como una ejecución completada.

Cada etapa completada se conserva una vez en la ejecución. Para comparar un recorrido con factores distribuidos con otro que utilice el motor se crean dos registros nuevos. Así no se reemplaza una biblioteca después de haber calculado un balance con otra procedencia.

## 5. Continuar, revisar y detectar un fallo

`estado` muestra qué etapas están pendientes, iniciadas, completadas o fallidas. Una etapa completada identifica productos aceptados; iniciar un comando no basta para acreditar resultados. La etapa siguiente exige que todas sus dependencias estén completadas y que sus archivos conserven las huellas registradas.

Si una etapa falla, sus archivos se conservan en su carpeta de intento y no se aceptan como productos. Al reintentar se crea otra carpeta y queda trazado el intento anterior. Si un proceso se interrumpe antes del cierre, se registra ese intento como fallido antes de iniciar el siguiente. El bloqueo de escritores se libera al terminar el proceso en el entorno Ubuntu/WSL comprobado.

Cambiar un producto aceptado, borrar un suceso, mezclar historiales o utilizar archivos de otro intento impide continuar. Se recupera la copia de la entrega o se inicia otra ejecución documentada; no se editan huellas para aceptar el cambio. Las hipótesis se mantienen en el Excel y cualquier referencia distinta requiere su propio registro y comprobación.

## 6. Dónde se localizan los resultados

Dentro de la carpeta de ejecución se mantienen los controles iniciales. `estado_ejecucion.json` y `eventos/` permiten seguir el trabajo; `resultados/` contiene las carpetas identificadas de cada etapa e intento. El índice de estado indica cuál está completado, por lo que no hay que deducirlo de la fecha o del nombre de una carpeta.

Los archivos copiados para conservar la selección técnica o la programación se distinguen de los resultados calculados y de los controles. La raíz temporal de cálculo de 06 conserva las mismas rutas relativas que necesitan los productores existentes, pero sus coeficientes se preparan con los productos registrados. La configuración copiada allí es un insumo de ejecución, no otro lugar de edición de hipótesis.

La comprobación final utiliza las tolerancias de los contratos existentes. La equivalencia numérica no convierte una hipótesis en una observación ni demuestra la implantación del servicio. La [guía de vigencia](vigencia_y_procedencia.md) identifica la función y procedencia de los materiales de la referencia.

Se mantienen las capas Medallion y las mismas rutas y código en desarrollo y publicación. La entrega y sus comprobaciones se identifican mediante los controles que acompañan a sus ZIP.

## 7. Ejecución comprobada de la referencia

La carpeta [referencia_2028_final_20261116](../data/silver/ejecuciones/referencia_2028_final_20261116/registro_ejecucion.json) conserva el recorrido completo de esta edición, con las mismas rutas y contenido en desarrollo y publicación. Se consulta con `uv run python scripts/ejecutar_etapa.py estado --registro data/silver/ejecuciones/referencia_2028_final_20261116`. Para recalcular se elige otra carpeta: la referencia se conserva.

La comprobación contrasta **21 interfaces de demanda,116 geográficas y 33 del balance**, incluidos 16 productos anuales. Las tolerancias son las de los contratos existentes, sin ampliarlas. 04 comprueba 261 programas distintos de la comparación principal y las sensibilidades, además de ocho recorridos dirigidos; no son 261 días ni autobuses físicos.

La referencia fue comprobada mediante el recorrido 01–07 y la consulta de los ocho cuadernos con sesiones nuevas de Python. La [evidencia de equivalencia](../manifiestos/comprobacion_entrega_final.json) conserva el alcance de esa comprobación. El acta externa que acompaña a los ZIP identifica además las verificaciones de la entrega recibida; no se infiere una validación en otro equipo.

En 05 se utiliza la acción registrada **consultar** para comprobar y utilizar los 5294 factores distribuidos, procedentes de las ejecuciones identificadas de 34 consultas. No se ejecuta nuevamente el motor COPERT. En el cuaderno, `comprobar_factores` corresponde a esa acción registrada, mientras `ejecutar_motor` ejecuta el programa. La opción inicial del cuaderno, `consultar`, solo lee 05 completada y no añade otro intento.

04 expone `consultar` y `comprobar`; la segunda requiere 01 y 02 completadas en el mismo registro. Presenta personas, actividad, vehículos y continuidad, sin energía. 06 expone `consultar` y `calcular`; utiliza 01–05 del mismo registro y no sustituye dependencias ausentes por tablas anteriores. La vista física adicional mantiene sus 24 filas identificadas y no se suma al recuento de 170 interfaces.

### Comprobación final desde 07

Después de completar 01–06, `ACCION_COMPROBACION="comparar"` con la misma `RUTA_EJECUCION` produce `verificacion_integrada.json` y las comparaciones de demanda, geografía y balance en un intento nuevo. Si 07 ya está completada se elige `consultar`; los selectores de tabla, figura y anexo solo cambian la lectura documental. El verificador localiza relaciones y archivos, sin generar o editar el informe.
