# Paquetes y controles de la entrega

El repositorio reúne el código y la release contiene los datos necesarios para reproducir la referencia del **informe v0.28**, con **2.500.000 visitas-persona anuales** y las 31 condiciones del libro. La [guía de reproducción](reproduccion.md) indica cómo obtenerlos, extraerlos y ejecutar el estudio.

## Qué contiene cada paquete

| Archivo | Contenido |
|---|---|
| `datos_bronze.zip` | Fuentes originales, metadatos de adquisición y entradas de COPERT |
| `datos_silver.zip` | Preparaciones, factores, programación y ejecución registrada de referencia |
| `datos_gold.zip` | Resultados validados de la entrega |

El código, el Excel de parámetros, los cuadernos y las guías se obtienen del repositorio. La release contiene únicamente los tres ZIP de datos y sus tres controles. Las rutas internas sitúan los datos bajo `data/bronze/`, `data/silver/` y `data/gold/` al extraerlos en la raíz del código descargado. Los [documentos del informe](disponibilidad_documental.md) conservan sus rutas propias; su inclusión se identifica en el inventario de cada entrega.

## Cómo se identifica una entrega

`manifiesto_paquetes.json` indica el contenido, tamaño y huella de cada ZIP y la referencia a la que corresponde. `SHA256SUMS` permite comprobar esas huellas antes de extraer. El [inventario](../manifiestos/archivos.json) identifica después los archivos extraídos. Su propia huella queda fuera del inventario para evitar una referencia circular.

`ACEPTACION_PAQUETES.json` acompaña a los ZIP e identifica las comprobaciones realizadas y sus límites. Se distribuye junto a los paquetes, sin insertarlo dentro de ellos. Cuando una entrega actualiza documentación y conserva los mismos archivos de cálculo y datos, el acta distingue las nuevas comprobaciones documentales de la reproducción científica previa. Una comprobación de una versión anterior solo respalda los archivos cuyo contenido permanece idéntico y cuyo alcance se identifica expresamente.

## Qué comprueban los controles

La integridad comprueba identidad de archivos; la trazabilidad relaciona fuentes, transformaciones, código y resultados; la equivalencia numérica compara los productos de una ejecución con sus referencias. Cada control responde a una pregunta diferente. Una instalación del entorno Python, la consulta de exportaciones COPERT y una ejecución nueva de su motor también se registran por separado.

El recorrido 00–07 compara 170 interfaces, incluidas 16 anuales, con las tolerancias documentadas. La referencia mantiene los programas y las decisiones técnicas fijadas; no busca otra ordenación ni acredita por sí sola disponibilidad contractual o funcionamiento real. Las comprobaciones y sus límites se relacionan en la [guía de trazabilidad](trazabilidad.md).

## Fuentes y condiciones

La [selección por archivo](../manifiestos/seleccion_entrega_publica.csv) y la [guía de fuentes](distribucion_fuentes.md) identifican las entradas y sus condiciones. Se mantienen todos los datos necesarios para el cálculo. Seis apoyos bibliográficos se citan mediante [referencias y enlaces](../manifiestos/referencias_documentales.csv), sin distribuir sus copias completas ni exigir su descarga para ejecutar. El motor COPERT y su activación tampoco se incluyen.

## Preparar los adjuntos de una release

La herramienta de distribución se ejecuta desde la raíz con:

```bash
uv run python preparar_release_datos.py --destino /ruta/nueva/paquetes
```

Produce exclusivamente `datos_bronze.zip`, `datos_silver.zip`, `datos_gold.zip`, `SHA256SUMS`, `manifiesto_paquetes.json` y `ACEPTACION_PAQUETES.json`. No incorpora un ZIP de código ni copias de las guías. La opción `--datos-existentes /ruta/paquetes` permite reutilizar ZIP ya generados, comprobando antes todos sus miembros y huellas. Desde desarrollo se puede elegir la política pública con `--gitignore-publico /ruta/publica/.gitignore`.

Las instantáneas de configuración del registro de ejecución permanecen en Silver para comprobar qué entradas utilizó el cálculo. Se distinguen de la configuración editable de Git. Esta preparación de entrega no modifica las hipótesis o las ejecuciones científicas. El acta identifica las comprobaciones efectivas de los paquetes; no presenta ese control como una nueva ejecución del balance o de COPERT.

GitHub incorpora automáticamente enlaces para descargar el código de la etiqueta en ZIP y tar.gz. Son descargas de la plataforma, independientes de los seis adjuntos de datos y controles que prepara este proyecto. Véase la [documentación de GitHub](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).
