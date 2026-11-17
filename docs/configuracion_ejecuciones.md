# Configuración común y registro inicial de ejecución

La lectura común del Excel y el registro permiten reabrir una ejecución desde disco. Identifica **qué configuración, entradas y código corresponden a una ejecución**, manteniendo las 2.500.000 visitas-persona y las condiciones vigentes.

La inicialización **comprueba la configuración y las entradas; todavía no calcula resultados**. Después se utiliza la [guía de etapas conectadas](ejecucion_por_etapas.md) para completar el recorrido con el mismo registro. Las instrucciones detalladas de ejecución se mantienen en esa guía para evitar duplicarlas. El informe y los anexos están alineados con el recorrido actual; las cifras y condiciones aceptadas se conservan.

## 1. Qué se lee del Excel

La entrada editable sigue siendo `config/parametros_modelo.xlsx`. `leer_configuracion`, en `src/movilidad_teide/configuracion/estudio.py`, abre el libro una sola vez y aplica las validaciones existentes.

| Contenido devuelto | Significado y uso |
|---|---|
| `valores` | Las 31 condiciones vigentes: visitas, cupos, flotas, reservas y demás condiciones efectivas |
| `procedencia_parametros` | Nombre, valor, unidad, motivo, estado, fuente y celda real de cada condición |
| `valores_modelo` | Traducción efectiva utilizada por el modelo; por ejemplo, cupo ordinario de 650 coches |
| `base` | Elecciones que necesitan las preparaciones existentes, conservadas para compatibilidad; no representan otro escenario activo |
| `indice` | Entradas y referencias selladas de la edición; no sustituye al Excel como editor |

La capa base contiene 129 parámetros y conserva elecciones adicionales. Algunos valores de esa capa fueron sustituidos al definir las condiciones vigentes. Por eso no debe usarse directamente `base` para decidir el cupo, la flota o la demanda actual: se usan `valores` y su traducción `valores_modelo`. Las interfaces de preparación comparten los resolvedores y mantienen explícita esa distinción.

El libro original de preparación de aforos de Bronze es una fuente inmutable para reconstruir aquella preparación, no otro editor de hipótesis. Ambos libros se mantienen en sus funciones respectivas. Una condición distinta de la referencia sellada se rechaza; adoptar otra hipótesis exige documentar la referencia y comprobar los cálculos afectados. No se editan huellas o instantáneas para aceptar discrepancias.

## 2. Crear un registro nuevo

Después de instalar el entorno y extraer los datos según la [guía de reproducción](reproduccion.md), desde la raíz:

```bash
uv run python scripts/registrar_ejecucion.py iniciar --destino data/silver/ejecuciones/mi_ejecucion_01 --modo consulta
```

Se elige una carpeta nueva. Las rutas relativas del comando parten de la raíz del proyecto, aunque se llame al script desde otra carpeta. También se admite un destino externo absoluto nuevo. Se protegen fuentes, Gold, configuración e informe, y se rechazan destinos existentes o atravesados por enlaces.

El modo admite `consulta` o `reproduccion`. **Expresa lo que se pretende hacer; no acredita que el cálculo ya se haya ejecutado.** En ambos casos este comando solo prepara el registro. Las acciones efectivas quedan acreditadas por los cierres de las etapas, que se consultan desde disco.

Se comprueban configuración, código, entradas del índice y contratos de demanda, geografía y balance, y el paquete completo de entradas públicas de COPERT, incluidos sus CSV nativos y la descripción de tipos. No hace falta instalar el motor COPERT para comprobar estas entradas.

Las referencias Gold se catalogan por separado y no se leen al inicializar. Se pueden comprobar posteriormente mediante una acción explícita. Identificar los archivos de comparación no implica usarlos para preparar un resultado nuevo.

## 3. Qué se guarda

| Archivo dentro de la carpeta nueva | Contenido |
|---|---|
| `registro_ejecucion.json` | Identificador, fecha UTC, modo solicitado, estado inicial, entradas, huellas de código, entorno y destino de resultados |
| `registro_ejecucion.sha256` | Huella del registro, separada del JSON para evitar autorreferencia |
| `configuracion_resuelta.json` | Instantánea portable de las condiciones, su procedencia y las capas de compatibilidad identificadas |
| `parametros_vigentes.csv` | Tabla de las 31 condiciones, unidades y celdas; es un control de ejecución, no un nuevo anexo del informe |
| `resultados/` | Carpeta de productos de las etapas; queda vacía al inicializar |

SHA-256 es una huella de los bytes de un archivo: detecta cambios, pero no es una firma digital ni demuestra aprobación institucional. Los registros contienen rutas relativas y pueden trasladarse entre las dos copias. Si hay información Git se conserva la revisión y si había cambios locales; las huellas identifican los archivos efectivos incluso antes de un commit. La copia de publicación no necesita `.git`.

Los datos se comprueban en sus ubicaciones Medallion, sin duplicarlos dentro del registro. La instantánea y su CSV son controles derivados en Silver; las hipótesis se editan en el Excel. El registro inicial es inmutable y mantiene vacía su lista de productos científicos. Los productos aceptados se identifican mediante el historial de etapas y `estado_ejecucion.json`; no se insertan manualmente en el registro inicial.

## 4. Reabrir desde una sesión nueva

En una terminal o sesión de Python nueva:

```bash
uv run python scripts/registrar_ejecucion.py abrir --registro data/silver/ejecuciones/mi_ejecucion_01
```

La reapertura lee desde disco, comprueba los controles, vuelve a resolver el Excel y contrasta entradas y código. Rechaza entradas ausentes, archivos alterados, registros incoherentes y otras ediciones. Comprueba también que el CSV y la descripción del registro concuerden con las celdas del Excel.

El resumen distingue `modo_solicitado` de `estado_inicial`, que permanece en `preparada_sin_calculo`. Informa de si coincide el entorno actual con el de creación, sin reescribirlo. Los cálculos requieren el entorno fijado en la guía; abrir el registro en otro entorno no acredita equivalencia numérica.

Para comprobar también las referencias Gold:

```bash
uv run python scripts/registrar_ejecucion.py abrir --registro data/silver/ejecuciones/mi_ejecucion_01 --comprobar-referencias
```

Esta acción verifica archivos de referencia y no produce un balance nuevo. Si cambian el código o las entradas durante el desarrollo, se conserva el registro anterior y se crea otro para esa edición. No se continúa atribuyendo un cálculo a condiciones distintas de las que utilizó.

## 5. Uso desde los cuadernos

Las funciones disponibles son `leer_configuracion` en `configuracion.estudio`, e `iniciar_ejecucion` y `abrir_ejecucion` en `configuracion.registro`, dentro de `movilidad_teide`. Reciben la raíz de la copia elegida y la ruta de ejecución. Un cuaderno puede obtener los valores vigentes mediante `abrir_ejecucion(RAIZ, ruta)["configuracion"]["valores"]` sin heredar variables de una sesión anterior; `RAIZ` debe identificarse en la sesión nueva. Tras actualizar el código se reinicia Python para evitar módulos antiguos en memoria.

`ejecutar_etapa`, en `flujos.etapas_registradas`, recibe la raíz, la ruta del registro y la etapa. Localiza desde disco los productos aceptados de sus dependencias; la guía de etapas concentra los comandos equivalentes. Los [ocho cuadernos 00–07](recorrido_notebooks.md) utilizan esas funciones y acciones explícitas. Las fórmulas permanecen en el código común. Los comandos independientes siguen disponibles como alternativas técnicas; no deben ejecutarse además para completar la misma cadena.

## 6. Referencia de la ejecución y alcance

La [guía de etapas](ejecucion_por_etapas.md) identifica la ejecución completa vigente y sus resultados. La inicialización conserva su estado original `preparada_sin_calculo`; al abrir el registro, el resumen añade los estados efectivos y distingue **balance calculado** de **motor COPERT ejecutado**. El segundo solo es verdadero cuando 05 se ha completado mediante `ejecutar_motor`.

Se puede trasladar la carpeta completa a la misma ruta relativa en la otra copia, junto con el código y los datos de la misma entrega. Cada etapa y la reapertura comprueban los archivos efectivos. Si cambian código o entradas, se conserva el registro anterior como antecedente y se crea uno nuevo; no se modifican sus huellas para atribuirle otra edición.

Las pruebas cubren entradas ausentes o alteradas, cambios de configuración o código, portabilidad, productos modificados, mezcla de intentos, fallos e interrupciones y dependencias incompletas. Las pruebas pequeñas verifican esos controles; la equivalencia científica se comprueba además con los datos reales del estudio.

La [guía de vigencia y procedencia](vigencia_y_procedencia.md) explica el papel de cada material de la entrega y sus relaciones con la referencia.
