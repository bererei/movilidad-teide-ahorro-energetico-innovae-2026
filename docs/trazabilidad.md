# Seguir un resultado desde sus fuentes

Esta documentación corresponde al informe v0.28, con las mismas 2.500.000 visitas-persona sin y con intervención y los datos aceptados. Permite localizar la fuente o hipótesis, la preparación, el código y las salidas de cada resultado. La edición actual incorpora la URL pública, las referencias comunes y la lectura final comprobada, manteniendo las cuentas energéticas.

El [recorrido oficial 00–07](recorrido_notebooks.md) utiliza estas matrices y el registro de la misma ejecución. [07 · Comprobación](../notebooks/07_comprobacion_e_informe.ipynb) permite consultar tablas y figuras por número, saltar a su página actual del PDF y revisar anexos y columnas. El [inventario de cuadernos](../manifiestos/cuadernos_implantados.csv) identifica los ocho archivos vigentes, sus celdas y sus huellas.

## Por dónde empezar

| Se busca… | Consultar |
|---|---|
| Una tabla o figura del informe | `manifiestos/trazabilidad_recursos.csv`: número, página PDF, título, etiqueta, anexos, entradas y productor |
| Un anexo de datos | `manifiestos/trazabilidad_anexos.csv`: fuentes, entradas, transformación, código y comprobación |
| Una columna, unidad o ausencia | `manifiestos/trazabilidad_columnas.csv`: las 392 definiciones originales, con su vínculo al productor del archivo |
| Un producto técnico del balance | `manifiestos/trazabilidad_resultados.csv`: los 16 productos comparados con Gold |
| La explicación de una etapa | `manifiestos/trazabilidad_etapas.csv`: doce materias y el alcance de su reproducción |
| Una hipótesis y su celda exacta del libro | `manifiestos/trazabilidad_hipotesis.csv`: valor, unidad, motivo, origen y celda de las 31 elecciones |
| Una referencia de la bibliografía | `manifiestos/fuentes_bibliograficas.csv`: 22 referencias, copia disponible o condición de hipótesis/referencia externa |
| Una ficha del anexo de cálculo | `manifiestos/trazabilidad_fichas.csv`: ocho fichas y sus funciones comprobadas |
| La identidad de las entradas | `manifiestos/trazabilidad_archivos.csv` y el inventario completo `manifiestos/archivos.json` |
| Un nombre de archivo de la organización anterior | `manifiestos/procedencia/rutas_originales.csv` |
| Un límite o preparación pendiente | `manifiestos/alcance_y_pendientes.csv` |

Los CSV se leen con separador punto y coma. Las rutas parten de la raíz común. Una referencia de código como `archivo.py:137::funcion` indica el archivo, su línea de definición y la función. Es una ayuda de consulta; no es un código de escenario. `scripts/verificar_trazabilidad.py` comprueba que esas definiciones y las correspondencias documentales sigan existiendo.

## Ejemplo: ahorro anual

La tabla 24 del informe presenta consumo y ahorro anual. En la matriz de recursos se vincula con `data/gold/anexos/balance_anual.csv`. Su fila de trazabilidad identifica el libro de hipótesis, la oferta y los coeficientes Silver, y las funciones que anualizan y exportan el resultado. `manifiestos/trazabilidad_resultados.csv` identifica los productos técnicos comparados por la etapa 07, después de su cálculo en 06.

La energía se suma por fecha y asignación antes de restar sin menos con. Se añade el posicionamiento en sus activaciones, se conserva el coche a cabeceras y se convierten MWh a tep con 11,63 MWh/tep. Los cocientes se dividen por las visitas del mismo periodo. No se restan extremos de asignaciones diferentes. El diccionario aclara las unidades y la ausencia de consumos comunes absolutos.

Para comprobar la cadena numérica se sigue el recorrido 00–07: 06 produce los resultados de su propia ejecución y 07 compara las 170 interfaces, incluidas las 16 anuales. El archivo técnico `balance_anual_politicas.csv` se distingue del anexo legible `data/gold/anexos/balance_anual.csv`. Este último pertenece a la entrega editorial y su productor es `generar_informe.py`; no se genera al comparar. Los comandos independientes son alternativas descritas en la [guía de reproducción](reproduccion.md).

## Cobertura comprobada y recursos reutilizados

La matriz cubre 16 productos anuales, 33 anexos de datos, 392 columnas, 43 tablas numeradas, 20 figuras numeradas y ocho fichas. La tabla 23, sobre parámetros de pendiente, está dentro de `main.tex`; el archivo que contiene las fichas no es una tabla numerada adicional.

La generación documental comprobada reproduce los 35 CSV de anexos, índice y diccionario byte a byte. Los 43 recursos de tabla conservan su texto. Siete figuras PDF conservan también sus bytes; trece tienen distinta huella binaria y el mismo renderizado a 120 puntos por pulgada. `manifiestos/comparacion_recursos_editoriales.csv`, `manifiestos/comparacion_visual_recursos.csv` y `manifiestos/comprobacion_entrega_final.json` registran esa distinción. El renderizado acredita esa resolución concreta, no una comparación independiente de cada instrucción vectorial del PDF.

El generador reutiliza seis figuras físicas y cinco tablas físicas identificadas de la entrega. Las demás figuras se generan desde los datos y preparaciones indicados. La tabla de parámetros de pendiente se conserva dentro del maestro. Esta reutilización se declara por recurso; generar el informe no implica reconstruir todos los mapas y perfiles desde sus fuentes originales.

## Qué significa que la trazabilidad esté cerrada

Queda cerrada la **matriz documental de la referencia distribuida**: se han localizado y comprobado sus relaciones, archivos, funciones, unidades y comprobaciones disponibles. La conciliación contrasta las identidades energéticas de los anexos, sus exportaciones Excel y la conservación numérica de las tablas. No constituye una auditoría externa de las fuentes ni una validación de explotación. La existencia de una fuente y de su código no demuestra que todas las preparaciones se hayan repetido desde bruto.

La preparación de demanda desde Bronze ya se ha comprobado con el alcance indicado más abajo. La reconstrucción de recorridos y perfiles está contrastada desde Bronze con el alcance específico de la guía geográfica. La [clasificación y la unión hasta el balance](preparacion_balance.md) se reconstruyen y comparan con decisiones técnicas y programas fijos declarados; no se afirma generar todas esas elecciones desde bruto. La entrega identifica 62 archivos fuente o de preparación documental: captura nativa del Visor, memorias de ocupación y su revisión, bibliografía física y documentos de contexto. `manifiestos/fuentes_reincorporadas.csv` identifica su procedencia y destino. La disponibilidad documental se distingue de una ejecución de las preparaciones. Las referencias externas sin copia local y las directrices sin constancia escrita independiente quedan indicadas en la matriz bibliográfica. Las hipótesis de planificación, ocupación y operación se distinguen de observaciones y compromisos confirmados. La capacidad nominal real de los autocares de excursión no está identificada: 35,99 personas por equivalente no permite afirmar un porcentaje real de llenado.

El cuaderno 05 distingue consultar una etapa aceptada, comprobar factores distribuidos y ejecutar el motor. Las ejecuciones identificadas de COPERT 5.10.1 conservan 34 consultas y 5.294 factores. La reproducción con exportaciones distribuidas comprueba su conexión con el balance sin repetir el motor. La selección fija del parque y los programas adoptados se explican sin atribuirles otra optimización. La instalación nueva del entorno Python desde paquetes está documentada en manifiestos/comprobacion_entrega_final.json; la instalación del motor COPERT en un equipo nuevo continúa separada. El [cierre documental de distribución](distribucion_fuentes.md) aplica avisos y metadatos con la evidencia disponible, conserva todas las entradas del cálculo, sustituye seis copias bibliográficas por sus referencias y documenta el criterio institucional para visores y marcas y registra la titularidad institucional de los aforos y su confirmación de procedencia, con su criterio de inclusión bajo el régimen general del Cabildo. El registro por archivo separa condiciones, créditos y procedencia, incluidas asociaciones por huella. La edición v0.28 y sus créditos están conciliados. El acta externa de los paquetes identifica su comprobación; la confirmación operativa tiene un alcance separado.

La [guía de lectura](lectura_final.md) localiza el informe y sus anexos, y el [mapa de vigencia](vigencia_y_procedencia.md) explica el criterio de selección y procedencia.

## Preparación de demanda desde Bronze

La [guía específica](preparacion_demanda.md) permite reconstruir 26 tablas sin leer Silver o Gold y comparar después 21 interfaces con Silver. El contrato `manifiestos/preparacion_demanda_bronze.json` identifica las 300 fuentes y configuraciones selladas, las claves y la cobertura de cada comparación; `manifiestos/trazabilidad_preparacion_demanda.csv` relaciona sus salidas con lectores y transformaciones. La diferencia máxima observada es cero, manteniendo 2.500.000 visitas y todas las restricciones.

El libro original de la preparación de aforos se conserva como fuente inmutable en Bronze, con procedencia explícita; el único libro editable del estudio sigue en `config/`. No se sustituyen las preparaciones Silver de referencia. La equivalencia de cantidades territoriales no certifica sus columnas adicionales de perfiles geográficos; los recorridos y pendientes se contrastan en la preparación geográfica, manteniendo explícitos sus límites.

## Recorridos y perfiles desde Bronze

La [guía geográfica](preparacion_geografia.md), el contrato `manifiestos/preparacion_geografia_bronze.json` y la matriz `manifiestos/trazabilidad_preparacion_geografia.csv` relacionan las fuentes originales, la resolución nativa de los auxiliares GTFS, las conversiones de terreno y las 118 salidas. Se comparan 115 interfaces Silver y un catálogo Bronze, incluyendo geometrías, CRS, cotas y pendientes. Las 82 referencias dirigidas se comprueban en sus columnas físicas e identificadores.

Las ocho respuestas nativas de terreno y sus metadatos están identificados en el contrato de preparación. La clasificación vial y la unión de segmentos con sus coeficientes se comprueban en el comando encadenado descrito en la [guía del balance desde fuentes](preparacion_balance.md). No se confunde equivalencia informática con validación de rasante u operación real.

## Clasificación y unión hasta el balance

`manifiestos/preparacion_balance.json` identifica las fuentes y las selecciones técnicas fijas. `manifiestos/trazabilidad_preparacion_balance.csv` enlaza las 33 interfaces reconstruidas con sus referencias y funciones. `manifiestos/fuentes_clasificacion_balance.csv` documenta las capturas cartográficas reincorporadas y la proyección de actividad usada para el factor de posicionamiento. Los coeficientes anteriores no se usan como entradas; los resultados Gold solo intervienen al comparar. La guía detalla los tramos no clasificados y la normalización de distancias OSRM.

## Evidencia de instalación y reproducción

La comprobación de instalación usa únicamente los ZIP recibidos y un entorno Python nuevo. La cadena, factores, pruebas y recursos se ejecutan con los repositorios de origen y sus temporales ocultos y sin red IP. Se permite la comunicación local que necesita el instalador. El manifiesto de aceptación distingue lo ensayado en ese entorno de una validación en otra máquina o de una ejecución del motor COPERT.

El mapa documental vincula las instrucciones, las salidas, las fichas y sus productores. La evidencia de cada comprobación identifica la edición, el entorno y los archivos que efectivamente utilizó.

## Alcance de la comprobación final por cuaderno

La [aceptación de 07](../manifiestos/comprobacion_lectura_final.json) diferencia tres controles: las huellas acreditan identidad de archivos, los contratos numéricos comprueban equivalencia y las matrices permiten localizar la cadena documental. Las 170 interfaces no son 170 celdas impresas: se comparan claves, columnas y unidades de cada contrato, con tolerancia vigente de 10⁻⁸. Los máximos de diferencias no deben interpretarse todos como MWh, porque se comparan magnitudes distintas.

El cuaderno presenta los productos nuevos de Silver junto a su referencia Gold, el índice de 63 recursos, los 33 anexos y sus 392 definiciones, y las ocho fichas metodológicas. Comprueba las huellas actuales de los 63 recursos entregados. La comparación de recursos de esta edición conserva las huellas actuales y el contraste gráfico con la edición aceptada; 07 consulta esos controles sin volver a generar el PDF o sus recursos.

La matriz documental conserva las funciones que produjeron la entrega. La nueva ruta registrada utiliza `flujos.etapas_registradas` y sus productores compartidos; el [mapa de código](../manifiestos/mapa_recorrido_codigo.csv) localiza las funciones de consulta y comparación actuales por línea y huella. La matriz identifica las funciones de generación documental y las de reproducción registrada por separado. Ambas conservan la procedencia y las condiciones de la referencia.
