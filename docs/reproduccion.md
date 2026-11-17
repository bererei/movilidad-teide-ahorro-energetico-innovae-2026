# Reproducir la referencia energética

Esta guía permite localizar y comprobar los resultados de la referencia de **2.500.000 visitas-persona en ambos escenarios**. Los mismos pasos sirven en desarrollo y en la copia de publicación. Las rutas parten de la raíz del repositorio; el nombre de la carpeta que lo contiene no importa.

El [mapa del recorrido por cuadernos](recorrido_notebooks.md) sitúa el servicio y la actividad en 04, antes de COPERT en 05, y distingue orden de lectura de dependencia numérica. 00–07 están disponibles; esta guía mantiene los comandos equivalentes y las alternativas técnicas.

## 1. Reunir código y datos de la misma entrega

La entrega se identifica por `manifiesto_paquetes.json`, `SHA256SUMS` y el acta `ACEPTACION_PAQUETES.json` que acompaña a los ZIP. Se utilizan siempre código y datos del mismo corte; el [manifiesto de referencia](../manifiestos/referencia.json) identifica el informe v0.28, su huella y el libro de hipótesis. La [revisión de fuentes](distribucion_fuentes.md) recoge sus criterios y atribuciones, sin una licencia global sobre los materiales ajenos. La [guía de entrega](entrega_publica.md) explica el contenido de los paquetes y el alcance de su aceptación.

1. Obtener el código de la etiqueta indicada en la release, mediante Git o la descarga del repositorio.
2. Obtener los tres paquetes de datos de esa misma entrega y sus archivos `manifiesto_paquetes.json` y `SHA256SUMS`.
3. Comprobar los tres ZIP descargados desde la carpeta que los contiene con `sha256sum -c SHA256SUMS`. Deben aparecer Bronze, Silver y Gold correctamente; no se omiten archivos ausentes.
4. Extraer los datos en la raíz que contiene `README.md`, `config/` y `scripts/`. Los ZIP ya incluyen `data/bronze/`, `data/silver/` y `data/gold/` en sus rutas internas.

Por ejemplo, en Ubuntu/WSL, con los ZIP descargados en la raíz:

```bash
unzip datos_bronze.zip
unzip datos_silver.zip
unzip datos_gold.zip
```

Si se usa una aplicación gráfica de extracción, se elige esa misma raíz como destino. No debe quedar una carpeta adicional como `datos_bronze/data/bronze/`. En desarrollo, donde los datos ya están extraídos, se comienza por la verificación y no se extrae encima de datos modificados.

## 2. Instalar el entorno fijado

El entorno comprobado es Ubuntu/WSL con Python 3.14.6. Se necesita `uv` disponible en la terminal; la [documentación oficial de instalación](https://docs.astral.sh/uv/getting-started/installation/) explica cómo obtenerlo. La prueba utilizó uv 0.11.21 ya disponible, e instaló de nuevo Python y todas las dependencias del proyecto. La versión Python figura en `.python-version`, las dependencias en `pyproject.toml` y sus versiones resueltas en `uv.lock`.

```bash
uv sync --locked
```

La primera instalación puede descargar Python y dependencias. No se cambia el archivo de versiones para resolver una discrepancia: se conserva el error y se comprueba que el código y los paquetes corresponden a la misma entrega. El cálculo sobre los datos locales no necesita volver a consultar las fuentes de Internet. Se ha comprobado una instalación nueva de Python 3.14.6 y las 112 dependencias desde los ZIP, con caché vacía, en Ubuntu/WSL del mismo equipo. La cadena se ejecutó después con la red bloqueada y las carpetas originales ocultas. Una instalación en otro equipo o sistema requiere registrar su propia comprobación; el motor COPERT tiene requisitos separados.

## 3. Verificar integridad y trazabilidad

```bash
uv run python scripts/verificar_entrega.py
uv run python scripts/verificar_trazabilidad.py
```

El primer comando contrasta todos los archivos seleccionados con `manifiestos/archivos.json`: existencia, tamaño y SHA-256, una huella que identifica sus bytes. Ese manifiesto excluye su propia huella para evitar una referencia circular. Los ZIP disponen, además, de sus huellas externas.

El segundo comprueba los 16 productos, los 33 anexos, sus 392 columnas, las 43 tablas, las 20 figuras y las ocho fichas. Verifica nombres de columnas, etapas, etiquetas y localización de las funciones citadas. No demuestra por sí mismo que cada cifra esté calibrada con observaciones reales.

Si falta un archivo, se recupera el paquete de su capa y se comprueba la extracción. Si su huella es diferente, se conserva aparte la copia modificada y se restaura la versión de la entrega antes de volver a verificar. No se edita el manifiesto para aceptar una discrepancia.

## Recorrido principal: cuadernos y etapas de la misma ejecución

La lectura empieza en [00 · Inicio y referencia](../notebooks/00_inicio_y_referencia.ipynb) y [01 · Fuentes y demanda](../notebooks/01_fuentes_y_demanda.ipynb). Se abren con `uv run jupyter lab` después de instalar el entorno; la opción inicial consulta resultados y el cálculo requiere una acción explícita y un registro nuevo. Cada cuaderno explica sus controles y puede utilizar un núcleo nuevo. Se continúa en [02 · Recorridos y pendientes](../notebooks/02_recorridos_y_pendientes.ipynb) y [03 · Parque y condiciones](../notebooks/03_parque_y_condiciones.ipynb). [04 · Servicio y actividad](../notebooks/04_servicio_y_actividad.ipynb) comprueba los servicios y sus kilómetros. [05 · COPERT](../notebooks/05_preparacion_y_ejecucion_copert.ipynb) permite consulta, comparación o motor explícito. [06 · Balance y sensibilidades](../notebooks/06_balance_y_sensibilidades.ipynb) permite consultar o calcular con los productos 01–05 registrados. [07 · Comprobación y vínculo con el informe](../notebooks/07_comprobacion_e_informe.ipynb) consulta o compara 01–06 de la misma ejecución. Permite elegir una tabla o figura del PDF y un anexo para localizar sus fuentes, unidades, productor y comprobación. La comparación guarda sus salidas en Silver; no regenera ni modifica documentos.

La [guía de etapas conectadas](ejecucion_por_etapas.md) contiene la secuencia completa: inicializar un registro nuevo, preparar demanda y geografía, identificar el parque, comprobar el servicio, obtener factores COPERT, calcular energía y comparar con las referencias. Cada comando puede ejecutarse desde una sesión nueva; lee las dependencias aceptadas de la misma ejecución.

La [guía de configuración](configuracion_ejecuciones.md) explica la lectura del Excel y los controles iniciales. Inicializar no equivale a calcular. La acción de COPERT distingue consultar exportaciones distribuidas de ejecutar expresamente su motor. Las condiciones y los resultados de referencia se identifican en el inventario de la entrega.

Los apartados siguientes describen **alternativas técnicas independientes** para revisar una preparación o reproducir la cadena en un solo comando. No hay que ejecutarlas además del recorrido principal para completar la misma ejecución. No añaden productos a su historial: si se eligen, se conserva su propia evidencia de salida.

## Preparación previa: reconstruir la demanda desde Bronze

```bash
uv run python scripts/reproducir_demanda_bronze.py reproducir --destino data/silver/ejecuciones/demanda_01
```

Primero prepara 26 tablas usando solo Bronze y configuración; después compara 21 interfaces con las referencias Silver. Se conserva el total de 2.500.000 visitas y la configuración vigente. La [guía de preparación de demanda](preparacion_demanda.md) explica fuentes, fases separadas, salidas y límites. Los resultados nuevos no sustituyen las referencias ni modifican el informe o Gold.

Este paso se ha comprobado con las capas Silver/Gold vacías y el desarrollo original oculto. Los recorridos y perfiles tienen su propio comando, explicado a continuación; no se debe presentar la preparación de demanda como certificación de todo el cálculo desde bruto.

## Preparación geográfica desde Bronze

```bash
uv run python scripts/reproducir_geografia_bronze.py reproducir --destino data/silver/ejecuciones/geografia_01
```

Prepara 118 tablas y los terrenos necesarios sin leer las preparaciones Silver o Gold anteriores; después compara 115 interfaces Silver y el catálogo nativo de reasignación de cabeceras. La [guía geográfica](preparacion_geografia.md) explica los soportes, las distancias, la interpretación del terreno norte y las columnas comparadas. La clasificación vial y la unión con coeficientes se cierran en el comando encadenado del apartado siguiente. No se modifica el informe o Gold.

## 4. Reconstruir el balance

Para reconstruir también las preparaciones físicas y energéticas, se recomienda:

```bash
uv run python scripts/reproducir_balance_desde_fuentes.py reproducir --destino data/silver/ejecuciones/cadena_01
```

La [guía de la cadena](preparacion_balance.md) distingue fuentes Bronze, decisiones técnicas Silver fijas y resultados reconstruidos. Compara 17 interfaces físicas/energéticas y 16 productos anuales. No lee Gold durante el cálculo. El resumen queda en `cadena_01/comprobacion/verificacion.json` y los productos anuales en `cadena_01/balance/`. La demanda y la geografía se reconstruyen dentro del mismo comando: no es obligatorio ejecutar antes sus comandos individuales.

También se mantiene la opción más corta, que parte de los coeficientes Silver distribuidos:


```bash
uv run python scripts/reproducir_estudio.py --destino data/silver/ejecuciones/balance_01
```

Se utiliza una carpeta nueva. Si ya existe y contiene archivos, se cambia el nombre del destino, conservando la ejecución anterior. Se comprueban las condiciones del libro, se reconstruye el reparto con los cupos, se verifican las circulaciones distribuidas y se calcula la energía por actividad y coeficientes. Se materializan las 366 fechas y se comparan los 16 productos con `data/gold/referencia_anual/`.

| Salida dentro de `balance_01/` | Lectura |
|---|---|
| `comparacion_referencia.csv` | Resultado de la comparación de los 16 productos |
| `auditoria_programas.csv` | Comprobaciones de las programaciones utilizadas |
| `balance_anual_politicas.csv` | Balance técnico anual por política, asignación y tratamiento |
| `actividad_y_energia_diaria_politicas.csv` | Actividad y energía por fecha |
| `recomendada_calendario.csv` | Fechas y recursos de la ordenación recomendada |
| `parametros_efectivos.json` y `metadatos.json` | Elecciones, entradas, código, entorno y salidas de esta ejecución |

Los ficheros técnicos conservan varias políticas de comparación. Para leer directamente el resultado recomendado se consultan los anexos legibles del paso siguiente o se aplica la selección definida en el código; no se suman políticas ni asignaciones alternativas.

Este paso utiliza factores y coeficientes distribuidos: no ejecuta COPERT ni reconstruye todas las preparaciones de demanda y geografía desde Bronze. Tampoco repite la búsqueda de horarios ni demuestra un óptimo global.

## 5. Generar una copia de los recursos y anexos

```bash
uv run python scripts/generar_informe.py --destino data/silver/ejecuciones/recursos_01
```

El generador consulta la referencia validada en Gold. Exporta la copia de `main.tex`, tablas, figuras y anexos en `recursos_01/`, y recalcula los apoyos y sensibilidades editoriales previstos. No reconstruye de nuevo el balance principal. Seis figuras físicas y cinco tablas físicas se reutilizan expresamente desde los recursos identificados de la entrega; la tabla 23 está integrada en el maestro.

Las salidas legibles están en `recursos_01/anexos_vigentes/`: `balance_anual.csv`, `balance_regimenes.csv`, `energia_diaria.csv` y los demás anexos del índice. Son **33 CSV de datos más el índice y el diccionario: 35 CSV**. Se comparan con los de `data/gold/anexos/` sin sustituirlos. En la comprobación documental actual coinciden byte a byte.

Para compilar también una copia PDF, se necesita XeLaTeX, los paquetes LaTeX utilizados en el maestro y la fuente Liberation Sans. Se emplea otro destino nuevo:

```bash
uv run python scripts/generar_informe.py --destino data/silver/ejecuciones/recursos_pdf_01 --compilar
```

El PDF queda en `recursos_pdf_01/compilacion/main.pdf`. La compilación conserva su registro y no sobrescribe el PDF entregado. La igualdad numérica de los CSV no sustituye la revisión visual del documento: los metadatos de PDF pueden cambiar su huella aun cuando el dibujo sea el mismo.

## 6. Comprobar COPERT y su conexión con el balance

La [guía de COPERT](reproduccion_copert.md) separa tres acciones:

| Acción | Qué hace |
|---|---|
| `verificar` | Relee las exportaciones distribuidas y compara 5.294 factores; no lanza COPERT |
| `ejecutar` | Reconstruye las entradas desde CSV y lanza COPERT 5.10.1 instalado |
| `verificar-estudio` | Reconstruye ponderación, masas y coeficientes con las bibliotecas suministradas, y compara cinco productos físicos y 16 anuales |

Al usar las exportaciones Silver distribuidas, `verificar-estudio` comprueba la conexión con el balance a partir de esas ejecuciones previas. Para acreditar una nueva ejecución del motor, se realiza primero `ejecutar` y se proporciona su nuevo destino. Las expresiones informativas de sus metadatos deben interpretarse con esta procedencia, no como prueba de que se ha lanzado el motor durante `verificar-estudio`.

## 7. Comprobaciones complementarias

```bash
uv run pytest -q
uv run python scripts/verificar_terreno_referencia.py --destino data/silver/ejecuciones/terreno_01
```

La evidencia de esta entrega identifica las pruebas del núcleo distribuido y del entorno instalado desde sus paquetes. La comprobación del terreno contrasta nueve respuestas nativas y sus productos derivados; no vuelve a adquirirlos de Internet. El recorrido actual utiliza exclusivamente 00–07. La [comprobación documental](../manifiestos/comprobacion_lectura_final.json) identifica la revisión del informe y sus recursos. El acta externa `ACEPTACION_PAQUETES.json` registra las pruebas efectivas y el entorno de cada conjunto de ZIP; se consulta para conocer el alcance aplicable a los archivos recibidos. Consultar tablas, reconstruir demanda y comparar resultados son acciones distintas; no se infiere una certificación integral desde bruto por abrir un cuaderno.

## Cómo interpretar el cierre

Las tolerancias existentes son **10⁻⁸** de diferencia absoluta por magnitud numérica en los productos anuales y **10⁻¹² MJ/km** en factores COPERT. Son criterios de equivalencia informática, no precisión física del modelo. Las identidades de visitas, unidades, energía y regímenes se comprueban por asignación y tratamiento, antes de redondear.

Se conservan 2.500.000 visitas, 650 coches ordinarios, excepciones de 700/750, treinta lanzaderas propias y los máximos de programación y sustitución del README. No se cambia una hipótesis o tolerancia para obtener coincidencia.

La [trazabilidad](trazabilidad.md) identifica fuentes, preparaciones, código, resultados y límites. La preparación de demanda desde Bronze está comprobada en el alcance indicado; los recorridos y perfiles también están contrastados en su alcance; la clasificación y su unión hasta el balance están contrastadas con las selecciones técnicas y programas fijos declarados. La instalación nueva del motor COPERT y la ejecución en otros equipos o sistemas requieren sus propias comprobaciones. La instalación desde los paquetes está comprobada para la candidata técnica identificada en el manifiesto de aceptación. La reproducción de los resultados sobre las entradas selladas sí se ha comprobado; no equivale a medición real, cobertura de todos los extremos posibles o aprobación operativa.

El informe y los anexos de la edición v0.28 utilizan estas rutas y condiciones. La [guía de lectura](lectura_final.md) permite localizar sus documentos y comprobaciones.

## Evidencia de la instalación y cómo mantenerla válida

`manifiestos/comprobacion_entrega_final.json` identifica los paquetes realmente ensayados, la versión del instalador, el entorno nuevo, los comandos y las comprobaciones. Se conserva la distinción entre repetir las exportaciones COPERT distribuidas y ejecutar de nuevo su motor. Las comprobaciones numéricas mantienen 10⁻⁸ para las interfaces y 10⁻¹² MJ/km para los factores.

La prueba ha verificado una entrada ausente y otra alterada en una copia de ensayo, tanto con el verificador general como con la preparación de la cadena. Se identifica el archivo afectado y no se produce un resultado aceptado. La recuperación sigue el procedimiento del apartado 3: restaurar el paquete de la misma entrega, sin editar los datos, las hipótesis o el manifiesto para aceptar el error.

Cada comprobación identifica los paquetes, código, libro, entorno y datos realmente utilizados. Una modificación posterior exige repetir lo afectado. La igualdad de resultados y la revisión editorial de v0.28 se distinguen de las condiciones necesarias para difundir fuentes y documentos.

## Documentos y contenido de los paquetes

La [guía de entrega](entrega_publica.md) identifica los tres paquetes de datos y sus controles. La [guía documental](disponibilidad_documental.md) localiza el informe, su copia firmada y los anexos. El inventario de la entrega distingue los archivos incluidos de los documentos no distribuidos; la generación documental requiere disponer de sus fuentes y recursos.

La compilación del informe utiliza XeLaTeX y el paquete `fvextra` de TeX Live para mostrar comandos con sus espacios y continuaciones de línea. Se incluye en `texlive-latex-extra`.
