# Preparar la demanda desde las fuentes originales

Este paso reconstruye la **demanda utilizada por el estudio de 2.500.000 visitas-persona anuales**, a partir de los archivos originales de Bronze y las decisiones documentadas en configuración. No calcula energía, busca otra programación ni modifica el informe, Gold o las preparaciones Silver de referencia. Desarrollo y publicación utilizan exactamente estos mismos comandos y rutas relativas.

La entrada narrativa es [01 · Fuentes y demanda](../notebooks/01_fuentes_y_demanda.ipynb), después de [00 · Inicio](../notebooks/00_inicio_y_referencia.ipynb). Permite consultar la etapa registrada o calcularla desde Bronze con una ejecución nueva. Las instrucciones siguientes son una alternativa técnica independiente; no hay que repetirla además del cuaderno para preparar la misma demanda.

## Ejecutar y comparar

Con los tres paquetes de datos de la misma entrega extraídos y el entorno instalado según la [guía general](reproduccion.md), desde la raíz:

```bash
uv run python scripts/reproducir_demanda_bronze.py reproducir --destino data/silver/ejecuciones/demanda_01
```

El destino debe ser nuevo. Se crean dos fases sucesivas: primero se preparan las tablas sin leer Silver o Gold; después se comparan con Silver. La segunda fase no participa en el cálculo de la primera.

| Salida dentro de `demanda_01/` | Qué contiene |
|---|---|
| `tablas/` | 26 tablas reconstruidas, organizadas por materia |
| `metadatos.json` | Fuentes y huellas, código, entorno, restricciones, lecturas y dimensiones de cada tabla |
| `comprobacion/comparacion_equivalencia.csv` | Las 21 comparaciones, sus dimensiones y diferencia máxima |
| `comprobacion/verificacion.json` | Resultado global, tolerancia y límites de la comprobación |

Si se quiere distinguir físicamente ambas fases, por ejemplo para ejecutar la preparación con Silver y Gold ausentes:

```bash
uv run python scripts/reproducir_demanda_bronze.py preparar --destino /tmp/demanda_nueva
uv run python scripts/reproducir_demanda_bronze.py comparar --resultados /tmp/demanda_nueva --destino data/silver/ejecuciones/comparacion_demanda_01
```

Para `preparar` son suficientes `src/`, el comando, `config/`, las fuentes Bronze enumeradas y `manifiestos/preparacion_demanda_bronze.json`. `comparar` necesita además las referencias Silver indicadas en ese contrato. Nunca se extraen datos sobre fuentes modificadas ni se corrigen las huellas para aceptar una discrepancia.

## De dónde procede cada parte

| Preparación | Fuentes y transformación |
|---|---|
| Perfiles y orígenes de movilidad | HTML y JavaScript nativos del Visor del Teide: extraer matrices horarias, centroides y correspondencia entre formato publicado y matriz |
| Reparto entre coche y autocar | Siete archivos originales de aforos; resumir vehículos y aplicar las ocupaciones documentadas para la preparación |
| Consultas de origen y destino | JSON nativos de viajes y horarios: seleccionar las 36 consultas completas de 2025 y comprobar que conservan los viajes; una consulta posterior filtrada por países no sustituye a la consulta completa |
| Territorio y cabeceras | ZIP de zonificación, GTFS —formato de horarios y paradas del transporte público—, mapa nativo de acceso dominante y correspondencias declaradas en configuración; se recuperan 41 orígenes representativos |
| Viajeros de TITSA | Matrices mensuales y paradas originales, límite del Parque y pertenencia de las paradas a la línea 341; separar viajes interiores y de acceso y anualizar sus referencias |
| Reparto anual y temporal | Mantener las proporciones de preparación, la proyección específica de TITSA y las condiciones vigentes; normalizar a 2.500.000 visitas para 2028 y construir los calendarios estacional y de media anual |

El código de orquestación está en `src/movilidad_teide/demanda/preparacion.py`; los lectores de origen, en `src/movilidad_teide/fuentes/preparacion_demanda.py`. Se reutilizan las funciones científicas existentes. El contrato enumera **300 archivos sellados** de fuentes y configuración; no todos sus auxiliares se leen directamente desde Python. Las lecturas observadas se registran aparte. `manifiestos/trazabilidad_preparacion_demanda.csv` relaciona cada salida con fuentes, transformación, productor, referencia y alcance comprobado.

### Aclaraciones necesarias para interpretar las fuentes

**El libro vigente de hipótesis sigue siendo uno solo:** `config/parametros_modelo.xlsx`. Para reconstruir exactamente la tabla de aforos se utiliza también el libro con el que se preparó esa fuente, identificado por su SHA-256 y conservado como documento inmutable en `data/bronze/documentacion/preparacion_aforos/`. Su `procedencia.json` explica esta función y su huella. No es un segundo lugar de edición del escenario ni se utiliza para recuperar una ordenación anterior. Se leen únicamente las dos ocupaciones de la preparación: permite reproducir tanto sus filas diagnósticas incompletas como el reparto condicionado efectivamente aplicado, con **3,2 personas por coche y 35,99 por autocar equivalente**. La fracción resultante de personas en coche es 0,7631452813921072.

Los aforos de 2025 presentan un patrón temporal identificable: en cada una de las 16 series de 8.760 horas, 89 marcas de medianoche de octubre a diciembre figuran en el día anterior. Se reproduce esa corrección ya utilizada, comprobando el patrón antes de aplicarla. Se preservan valores, decimales, ausencias y valores negativos; no se redondean ni se sustituyen extremos para obtener equivalencia.

La cifra de 5.113.021 visitas asociada a la fuente de 2025 aparece en una normalización intermedia de procedencia, identificada por el PDF y sus metadatos. **No es el volumen anual del escenario recomendado.** La preparación posterior fija expresamente 2.500.000 visitas en 2028 para ambos escenarios. No se vuelve a aplicar crecimiento a ese total. El crecimiento específico de TITSA se conserva como parte del reparto.

Algunas tablas originales escriben sus fuentes con nombres anteriores de directorio. La comparación traduce exclusivamente esas cadenas de procedencia mediante el catálogo ya existente `config/rutas_datos.json`. No crea carpetas antiguas ni cambia cantidades, identificadores o decisiones para conseguir coincidencia.

## Qué se ha comprobado y qué queda fuera

La prueba de aceptación se realizó con Silver y Gold vacíos, sin acceso al desarrollo original o a sus antecedentes y con la red bloqueada, utilizando un entorno independiente ya instalado con las versiones fijadas. **Las 21 interfaces comparadas son equivalentes: diferencia numérica máxima cero**, con la tolerancia absoluta existente de 10⁻⁸ sin modificar. También se comparan claves, número de filas, columnas, ausencias y textos; no se exige identidad binaria de CSV serializados de nuevo.

Se compara completo el calendario de **26.128 filas y 28 columnas**, conservando 2.500.000 visitas en cada método de anualización, y la tabla de reparto por origen y modo de **164 filas y 20 columnas**. En la tabla de 328 filas de demanda territorial se comparan las claves y cantidades, no sus columnas adicionales de diagnóstico de distancias y perfiles. Cinco de las 26 tablas son salidas de apoyo sin una comparación histórica completa propia; se identifican como tales en la matriz.

Se han comprobado además errores de fuentes ausentes o alteradas, consultas con filtros ajenos, lecturas indebidas de Silver/Gold y diferencias de demanda, identificadores, ausencias o claves duplicadas. La evidencia resumida está en `manifiestos/comprobacion_entrega_final.json`.

**Esta comprobación corresponde a la preparación de demanda.** La reconstrucción de recorridos y perfiles se describe en la [guía geográfica](preparacion_geografia.md), y su unión con coeficientes y energía en la [guía del balance](preparacion_balance.md). La equivalencia de la demanda no acredita por sí sola la del balance ni una operación real.
