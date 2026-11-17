# Ahorro energético de la movilidad del Teide

El estudio compara dos formas de atender **2.500.000 visitas-persona anuales** al Parque Nacional del Teide en 2028 y estima su diferencia de energía. Una visita incluye ida, estancia y regreso; los transbordos no añaden visitantes. El código y los datos corresponden al [informe v0.28](docs/informe_energetico/INFORME_ENERGETICO_v0.28_2026-11-16.pdf) y sus [anexos](data/gold/anexos/). El [repositorio público](https://github.com/bererei/movilidad-teide-ahorro-energetico-innovae-2026) comparte las rutas del núcleo de desarrollo y mantiene su propio historial.

En ordinaria se consideran **650 coches diarios y hasta 27 lanzaderas propias programadas**, dejando al menos tres para sustitución. En punta pueden programarse 28 propias con dos libres, o treinta con dos externas disponibles para sustituirlas. El cupo pasa a 700 o 750 en las fechas previstas. Se conserva la excursión existente en el principal y se estudia su crecimiento por separado. El balance incluye el coche hasta cabeceras, también para antiguos viajeros de Transportes Interurbanos de Tenerife (TITSA), y la visita interior en coche de los ocupantes de coches autorizados en ambos escenarios.

Las hipótesis se editan únicamente en `config/parametros_modelo.xlsx`. Su lectura común identifica 31 condiciones efectivas. Los resultados técnicos validados están en `data/gold/referencia_anual/`; las nuevas ejecuciones se guardan en `data/silver/ejecuciones/` sin sobrescribir la referencia.

## Recorrido de lectura y cálculo

| Cuaderno | Qué explica y permite comprobar |
|---|---|
| [00 · Inicio](notebooks/00_inicio_y_referencia.ipynb) | Entorno, configuración y registro de ejecución |
| [01 · Fuentes y demanda](notebooks/01_fuentes_y_demanda.ipynb) | Origen de las visitas, reparto y preparación desde Bronze |
| [02 · Recorridos y pendientes](notebooks/02_recorridos_y_pendientes.ipynb) | Distancias, terreno, perfiles y clasificación vial |
| [03 · Parque y condiciones](notebooks/03_parque_y_condiciones.ipynb) | Selección técnica de vehículos y masas |
| [04 · Servicio y actividad](notebooks/04_servicio_y_actividad.ipynb) | Viajeros, vehículos, expediciones y kilómetros |
| [05 · COPERT](notebooks/05_preparacion_y_ejecucion_copert.ipynb) | Entradas, exportaciones y ejecución explícita del motor |
| [06 · Balance y sensibilidades](notebooks/06_balance_y_sensibilidades.ipynb) | Consumo, ahorro, regímenes e indicadores por visita |
| [07 · Comprobación e informe](notebooks/07_comprobacion_e_informe.ipynb) | Equivalencia y vínculos con tablas, figuras y anexos |

La opción inicial consulta la ejecución distribuida y sus salidas guardadas. Calcular o ejecutar el motor requiere elegir la acción expresamente y un registro nuevo. Cada cuaderno explica qué recibe, qué hace y qué produce; se puede reiniciar Python entre cuadernos. La [guía por etapas](docs/ejecucion_por_etapas.md) mantiene los comandos equivalentes y sus dependencias en un único lugar.

## Obtener los archivos e instalar el entorno

El código y la configuración se distribuyen en Git. **Todos los datos se entregan por release**, mediante `datos_bronze.zip`, `datos_silver.zip` y `datos_gold.zip`. `codigo_y_documentacion.zip` ofrece una copia alternativa del código de la misma entrega. Se extraen en una sola raíz: las rutas internas colocan cada archivo bajo su capa, sin repartirlo manualmente. Se comprueban las huellas de `SHA256SUMS` y `manifiesto_paquetes.json` antes de ejecutar.

```bash
uv sync --locked
uv run python scripts/verificar_entrega.py
uv run python scripts/verificar_trazabilidad.py
uv run jupyter lab
```

La [guía de reproducción](docs/reproduccion.md) explica requisitos, extracción, verificaciones y recuperación de una entrada ausente o alterada. La [configuración registrada](docs/configuracion_ejecuciones.md) identifica la referencia. La [guía COPERT](docs/reproduccion_copert.md) localiza los CSV de entrada, el orden de las consultas y la instalación adicional necesaria para ejecutar el motor. Consultar los factores distribuidos no ejecuta COPERT.

## Organización y trazabilidad

La arquitectura **Medallion** conserva fuentes y entradas en `data/bronze/`, preparaciones y ejecuciones en `data/silver/` y resultados validados en `data/gold/`. Son capas del dato, no grados de certeza. Código, configuración, cuadernos, guías y manifiestos tienen rutas comunes en ambos repositorios; los antecedentes y la planificación interna se conservan en desarrollo.

La [trazabilidad](docs/trazabilidad.md) vincula 16 productos anuales, 33 anexos de datos, 392 columnas, 43 tablas, 20 figuras y ocho fichas. [07](notebooks/07_comprobacion_e_informe.ipynb) permite elegir un recurso y localizar su página y sus fuentes. El [inventario](manifiestos/archivos.json) identifica los archivos vigentes y la [selección](manifiestos/seleccion_entrega_publica.csv) su función y condiciones. La [lectura final](docs/lectura_final.md) documenta la revisión del informe.

## Contenido y comprobación de la entrega

La entrega reúne los archivos necesarios para el cálculo y mantiene sus fuentes y condiciones en la [guía de fuentes](docs/distribucion_fuentes.md). Seis apoyos bibliográficos se citan mediante [referencias y enlaces](manifiestos/referencias_documentales.csv); sus copias completas no son necesarias para ejecutar los cuadernos.

Las [releases](https://github.com/bererei/movilidad-teide-ahorro-energetico-innovae-2026/releases) agrupan los cuatro ZIP y sus controles: `manifiesto_paquetes.json`, `SHA256SUMS` y `ACEPTACION_PAQUETES.json`. La [guía de entrega](docs/entrega_publica.md) explica qué contiene cada paquete y qué acredita su comprobación.

El [informe original](docs/informe_energetico/INFORME_ENERGETICO_v0.28_2026-11-16.pdf) y la [copia firmada](docs/informe_energetico/INFORME_ENERGETICO_v0.28_2026-11-16_firmado.pdf) se identifican por separado mediante sus rutas y huellas en el [registro documental](manifiestos/firma_informe.json). La [guía de documentos](docs/disponibilidad_documental.md) localiza el informe, sus fuentes y los anexos.

## Alcance de los resultados y condiciones de uso

El ahorro principal es **403,1–411,6 toneladas equivalentes de petróleo (tep) al año** bajo las hipótesis y la operación representadas. Se comprueban 170 interfaces: 21 de demanda, 116 geográficas y 33 de balance, incluidas 16 anuales. Las tolerancias informáticas no expresan precisión física. Se conservan decisiones técnicas y programas fijos explícitos: no se afirma reconstruir toda decisión desde datos brutos, ni acreditar capacidad contractual o funcionamiento real. Los consumos comunes absolutos sin cuantificar no se consideran cero y no permiten calcular un porcentaje global de ahorro.

El código original se comparte bajo [MIT](LICENSE), los textos originales bajo Creative Commons Reconocimiento4.0 (CC BY4.0) y los datos ajenos mantienen sus condiciones específicas. [Licencias](docs/licencias.md), [atribuciones](ATRIBUCIONES.md) y [condiciones por fuente](docs/distribucion_fuentes.md) delimitan cada caso; no existe una licencia única para todos los datos. No se distribuyen el motor COPERT, su activación ni una instalación local del programa.
