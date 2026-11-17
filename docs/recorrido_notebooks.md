# Comprender y reproducir el estudio con los cuadernos

La secuencia 00–07 es la entrada común al estudio en desarrollo y en publicación. Mantiene **2.500.000 visitas-persona anuales en ambos escenarios**, el mismo libro de hipótesis y las restricciones operativas. Los cuadernos explican los pasos y llaman al código compartido: las fórmulas no se mantienen en copias independientes.

## Qué significa consultar o reproducir

La opción inicial consulta una ejecución completada, con resultados identificados y comprobaciones guardadas. Abrir y recorrer un cuaderno en ese modo no recalcula los resultados ni ejecuta COPERT. Para producir resultados nuevos se elige la acción indicada y una carpeta de ejecución nueva. La guía [Ejecución por etapas](ejecucion_por_etapas.md) mantiene en un único lugar las acciones, los comandos y sus dependencias.

El registro conserva las condiciones leídas del Excel, las entradas y sus huellas, las acciones realmente completadas y los productos. Se puede reiniciar Python entre cuadernos: la continuidad depende de archivos, no de variables que sigan en memoria. Las hipótesis se editan en `config/parametros_modelo.xlsx`. El índice JSON identifica la referencia, sus entradas y sus huellas; no es otro lugar para cambiar valores del estudio.

## Orden de lectura

| Paso | Qué explica y comprueba |
|---|---|
| [00 · Inicio](../notebooks/00_inicio_y_referencia.ipynb) | Las 31 condiciones, el entorno, las entradas, el registro y la elección entre consultar o iniciar una ejecución nueva |
| [01 · Fuentes y demanda](../notebooks/01_fuentes_y_demanda.ipynb) | Preparación desde Bronze, proyección, reparto y calendario de 366 fechas, con 21 interfaces de comparación |
| [02 · Recorridos y pendientes](../notebooks/02_recorridos_y_pendientes.ipynb) | Geometrías, distancias, cotas, pendientes y clasificación vial desde fuentes;116 interfaces con sus límites |
| [03 · Parque y condiciones](../notebooks/03_parque_y_condiciones.ipynb) | Selección técnica fijada, procedencia y diferencia entre la base identificable de microdatos y el contraste municipal |
| [04 · Servicio y actividad](../notebooks/04_servicio_y_actividad.ipynb) | Personas, cupos, expediciones, movimientos en vacío, identidades, horarios, reservas, ocupaciones y kilómetros; sin consumo energético |
| [05 · COPERT](../notebooks/05_preparacion_y_ejecucion_copert.ipynb) | Entradas públicas de 34 consultas, comparación de 5294 factores y acción explícita para ejecutar el motor instalado |
| [06 · Balance](../notebooks/06_balance_y_sensibilidades.ipynb) | Coeficientes,16 productos anuales, energía y sensibilidades desde los productos de las etapas anteriores |
| [07 · Comprobación e informe](../notebooks/07_comprobacion_e_informe.ipynb) | Equivalencia, integridad,33 anexos,392 columnas,43 tablas,20 figuras y ocho fichas, distinguiendo el alcance de cada comprobación |

El servicio se estudia antes de aplicar los factores energéticos. La preparación de las consultas COPERT normaliza la actividad necesaria para obtener factores; el balance los multiplica después por la actividad de transporte real. Esa normalización técnica no sustituye los kilómetros anuales del servicio.

## Una única estructura de datos

Bronze conserva fuentes originales y entradas públicas de COPERT. Silver contiene preparaciones, factores, programación y ejecuciones nuevas. Gold contiene resultados y anexos validados. Los resultados nuevos se escriben en una carpeta nueva de `data/silver/ejecuciones/` o en el destino externo exigido por la herramienta. No se usan enlaces hacia antecedentes privados.

La referencia registrada actual está en `data/silver/ejecuciones/referencia_2028_final_20261116/`. La comprobación de esta edición se describe en [el registro de conciliación](../manifiestos/comprobacion_entrega_final.json). El [índice de cuadernos](../notebooks/README.md) identifica los ocho archivos de este recorrido.

## COPERT: consultar y ejecutar son acciones diferentes

05 permite consultar una etapa completada, comparar los factores distribuidos o ejecutar el motor. Solo la última acción acredita un motor nuevo en esa ejecución. Las 34 consultas y sus 5294 factores tienen una procedencia identificada; volver a consultarlos o generar el informe no ejecuta el programa. La [guía COPERT](reproduccion_copert.md) explica instalación, intercambio Windows, entradas y salidas. El programa instalado y su activación no forman parte del paquete de datos.

## Qué demuestra la comprobación

La cadena reconstruye demanda, geografía, clasificación, masas y coeficientes. Conserva como decisiones fijadas la representación técnica del parque, las bibliotecas COPERT identificadas y los programas elegidos, que se comprueban. Gold interviene después al comparar los resultados. La documentación de [demanda](preparacion_demanda.md), [geografía](preparacion_geografia.md) y [balance](preparacion_balance.md) explica fuentes, transformaciones, unidades y límites.

Se distinguen identidad de archivos, equivalencia numérica y trazabilidad. Las 170 interfaces comprenden 21 de demanda,116 geográficas y 33 del balance, incluidas 16 anuales. Esas comparaciones no acreditan por sí solas representatividad estadística, calibración física o disponibilidad institucional. Los extremos energéticos son contrastes técnicos; no probabilidades.

## Del cálculo al informe y sus anexos

Los anexos legibles están en `data/gold/anexos/`; el índice describe sus 33 tablas y el diccionario define 392 columnas. La guía de cálculo de esos anexos sigue los mismos ocho pasos. Las [matrices de trazabilidad](trazabilidad.md) vinculan resultados, datos, código y recursos del informe; el mapa de código localiza funciones y clases.

El generador documental consulta la referencia validada, produce los anexos de lectura y recursos editoriales y reutiliza seis figuras y cinco tablas físicas identificadas. Su exportación `anexos_vigentes/balance_anual.csv` tiene una función de lectura; no debe confundirse con los nombres de los 16 productos técnicos del balance. Los recursos nuevos se generan en Silver y solo se incorporan a la entrega después de comprobarlos.

Las fuentes originales y sus metadatos conservan la procedencia de adquisición o preparación, incluso si mencionan un nombre anterior. Eso no constituye una instrucción para ejecutar un cuaderno sustituido. La [guía de vigencia](vigencia_y_procedencia.md) explica esa distinción. El contenido de los paquetes y sus controles se describe en [Entrega pública](entrega_publica.md).
