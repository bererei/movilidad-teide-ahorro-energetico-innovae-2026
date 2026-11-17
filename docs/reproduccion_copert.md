# Entradas y factores COPERT: lectura y reproducción

Esta guía permite localizar los CSV completos de las 34 consultas, reconstruir sus entradas nativas, verificar factores y repetir el motor cuando esté instalado. Todas las rutas parten de la raíz del repositorio y sirven en desarrollo y publicación. La comparación principal conserva 2.500.000 visitas y las condiciones del [README](../README.md).

## Entrada recomendada desde el cuaderno

El [cuaderno 05](../notebooks/05_preparacion_y_ejecucion_copert.ipynb) reúne la explicación y las acciones registradas. Permite `consultar` una etapa 05 completada, `comprobar_factores` distribuidos en una nueva etapa o `ejecutar_motor` expresamente. La preparación de cada XLSX desde CSV forma parte de la acción del motor; el cuaderno también reconstruye una entrada temporal para inspección. Los comandos siguientes son alternativas que utilizan los mismos módulos, no otro recorrido obligatorio. La [aceptación](../manifiestos/comprobacion_entrega_final.json) identifica lo probado en ambas copias.

## Consultas y condiciones


| Grupo | Consultas | Condiciones |
|---|---:|---|
| Autocar elegido | 14 | 34 km/h, siete pendientes entre −6 % y +6 %, carga técnica 0 o 0,5. Una sola categoría en cada ejecución. |
| Biblioteca principal de turismos | 5 | 20, 40, 60, 80 y 100 km/h; mismas categorías necesarias para preparar la biblioteca del estudio. |
| Extremos multienergía | 10 | Controles nativos 0 y 1 en las cinco velocidades técnicas. |
| Comprobación multienergía | 5 | Control intermedio 0,37 para verificar la combinación lineal de los extremos. |
| **Total** | **34** | Se distinguen factores aplicados, controles y preparación técnica. |

Los recorridos del estudio utilizan 20/40/80 km/h para coches y 34 km/h para autocares. Los nodos de turismos a 60/100 km/h sostienen la malla completa exigida por el preparador vigente; no se asignan como velocidades de circulación a esas rutas. De las 34 consultas, 23 aportan factores al consumo, tres comprueban linealidad en las velocidades aplicadas y ocho completan esa malla técnica.

La carga de autocar 0,5 es una condición técnica de COPERT, no una ocupación del 50 % de sus asientos. El control primario de vehículos multienergía es otra magnitud y no equivale a un reparto energético observado. La referencia del estudio mantiene el control técnico elegido; los controles 0, 1 y 0,37 sirven para obtenerla y verificar su aplicación.

El factor plano de excursiones y los factores por pendiente de TITSA proceden de estas mismas consultas de autocar; no se añaden ejecuciones o consumos duplicados por servicio o escenario. Los factores se refieren a motor caliente, o Hot. El ajuste físico de pendiente de los turismos se reconstruye fuera de COPERT con el método del estudio, sin atribuírselo al programa.


## Archivos, tipos y unidades
| Elemento | Contenido y función |
|---|---|
| `entradas_publicas/consultas.csv` | Resumen legible de las 34 consultas, condiciones y función. Es un índice de lectura, no un segundo maestro de hipótesis. |
| `entradas_publicas/vehiculos.csv` | Claves completas de las categorías consultadas en cada caso. Las etiquetas nativas en inglés permiten su identificación inequívoca en COPERT. |
| `entradas_publicas/tablas/` | Una carpeta por consulta y un CSV por hoja nativa de COPERT: vehículos, actividad técnica, ambiente, combustible, carga, pendiente y demás ajustes. |
| `estructura.json` de cada consulta | Orden de hojas y tipos de celda para reconstruir exactamente las tablas. |
| `referencia_comparacion/factores_esperados.csv` (Silver) | Valores de referencia contra los que se comparan las ejecuciones nuevas. Se utilizan para verificar, no para producir las salidas de COPERT. |
| `entradas_publicas/manifiesto.json` | Configuración de cada consulta y huellas SHA-256 de todos los archivos de entrada. |
| `data/silver/copert/ejecuciones/consultas/` | Entradas XLSX generadas desde CSV, exportaciones y registros de las ejecuciones distribuidas; son salidas Silver. Una ejecución nueva utiliza su propio destino. |
| `DESTINO_NUEVO/comparacion_factores.csv` | Diferencia entre cada factor nuevo y el correspondiente factor de referencia. |
| Bibliotecas `factores_*.parquet` | Bibliotecas normalizadas en `data/silver/copert/factores/`, o en el destino de una ejecución nueva, utilizadas para reconstruir coeficientes y comprobar el balance. Parquet es un formato de tablas utilizado por el código; los CSV facilitan su inspección. |

Los CSV usan UTF-8 con marca de codificación, punto y coma como separador y punto decimal, sin separador de millares. En las tablas nativas se mantienen las filas y columnas de COPERT; `estructura.json` distingue texto, entero, decimal, booleano y vacío. Así, el texto `2028` de una cabecera, el número cero y una celda vacía no se confunden al importar. Los vacíos no se convierten en ceros.

Las unidades nativas se conservan en las tablas `SHEETS`. Algunos campos aparecen identificados como `[%]` pero utilizan fracciones en las entradas de estas consultas: 0,5 representa el 50 % y 0,06 representa una pendiente del 6 %. El resumen `consultas.csv` expresa la pendiente en porcentaje y la carga y el control como fracción. El código aplica estas convenciones explícitas y no deduce conversiones por el aspecto de los números.

La actividad técnica normaliza factores: stock de una unidad y 17 km por categoría, con el reparto técnico de modos documentado en las entradas de turismos. No representa el número de autobuses o coches del estudio ni añade visitas al Parque. Las condiciones ambientales y de combustible mantienen los valores técnicos de la referencia, incluida la especificación de combustible de 1996; no se presentan como mediciones locales o una previsión del combustible de 2028.


## Ubicación de las entradas y resultados

- Entradas selladas: `data/bronze/copert/entradas_publicas/`.
- Proyectos, exportaciones y registros de ejecución: `data/silver/copert/ejecuciones/`.
- Bibliotecas vigentes: `data/silver/copert/factores/`.
- Referencia numérica esperada: `data/silver/copert/referencia_comparacion/`.
- Comparaciones distribuidas: `data/silver/copert/comprobaciones/`.

Estas son velocidades técnicas del cálculo energético. Los tiempos que permiten enlazar las expediciones proceden de sus itinerarios; no se sustituyen automáticamente por distancia dividida entre 34 km/h. Los factores compartidos se aplican a la actividad de cada servicio sin duplicar viajeros.

COPERT se utiliza mediante su interfaz programática con las tablas nativas reconstruidas desde CSV tipados. Comparar los factores normalizados distribuidos no ejecuta de nuevo el motor ni vuelve a leer sus XLSX originales. Para ejecutar se requiere la versión 5.10.1 y un destino nuevo; la versión y huella del ejecutable utilizado quedan documentadas en la procedencia de la ejecución. El motor y su instalación no se distribuyen en estos paquetes.

## Comprobar los factores sin instalar COPERT

El comando de esta sección comprueba factores normalizados. Las exportaciones nativas permanecen en Silver para inspección, pero este comando no vuelve a normalizarlas desde sus XLSX. Una ejecución nueva del motor sí obtiene y normaliza otras exportaciones.

Con el entorno y los datos preparados según la [guía general](reproduccion.md), ejecutar desde la raíz:

```bash
uv run python scripts/reproducir_copert_publico.py verificar --entradas data/bronze/copert/entradas_publicas --resultados data/silver/copert/ejecuciones --referencia data/silver/copert/referencia_comparacion --destino ../verificacion_factores_01
```

El destino es una carpeta externa nueva. La acción lee `factores_nuevos.csv` distribuido y compara los 5.294 factores con tolerancia absoluta de 10⁻¹² MJ/km. Es una comprobación numérica; no lanza el motor. La referencia de comparación no se utiliza como salida del motor ni se incluye en las entradas Bronze.

## Reconstruir una entrada XLSX desde sus CSV

Para inspeccionar una consulta concreta sin abrir COPERT:

```bash
uv run python scripts/reproducir_copert_publico.py crear-entrada --csv data/bronze/copert/entradas_publicas/tablas/autocar_carga050_pendientem06 --xlsx ../entrada_autocar_01.xlsx
```

Se reconstruyen todas sus hojas y tipos. El archivo de salida debe ser nuevo. Las condiciones de esta consulta de ejemplo son carga técnica 0,5, pendiente −6 % y 34 km/h; no son otra hipótesis anual de transporte. No basta con importar un CSV aislado: `estructura.json` conserva el orden y los tipos de todas las hojas.

## Repetir las 34 consultas con el motor

La interfaz automatizada actual utiliza COPERT **5.10.1 instalado en Windows**, desde WSL, con `wslpath` disponible. La carpeta de salida debe estar en una unidad local de Windows accesible desde WSL, por ejemplo bajo `/mnt/c/`, porque COPERT no acepta en esta interfaz una ruta de intercambio UNC de Linux. Se necesita permiso de escritura y espacio para entradas, exportaciones y registros. La instalación y el ejecutable no forman parte de la release.

En el comando siguiente deben sustituirse `RUTA_REAL` y `RUTA_LOCAL_WINDOWS` por ubicaciones existentes del equipo. El último componente del destino debe ser nuevo:

```bash
uv run python scripts/reproducir_copert_publico.py ejecutar --entradas data/bronze/copert/entradas_publicas --referencia data/silver/copert/referencia_comparacion --copert "/mnt/c/RUTA_REAL/COPERT.exe" --destino "/mnt/c/RUTA_LOCAL_WINDOWS/copert_nuevo_01"
```

Esta acción reconstruye los XLSX desde los CSV, valida las condiciones, lanza el ejecutable y conserva salidas, bibliotecas y comprobaciones en el destino. No modifica Bronze, las ejecuciones Silver distribuidas ni Gold. El registro identifica entradas y ejecutable. Una instalación de otra versión requiere comprobar equivalencia; no se presupone por compartir el nombre del programa.

Si se interrumpe una consulta, primero se revisan sus registros y si el proceso sigue activo. `--reanudar` permite retomar una ejecución con resultados ya verificados; no convierte un proceso incompleto en éxito ni sustituye la revisión de su estado.

## Comprobar la conexión de los factores con el balance

Para las ejecuciones distribuidas:

```bash
uv run python scripts/reproducir_copert_publico.py verificar-estudio --resultados-copert data/silver/copert/ejecuciones --destino ../balance_desde_copert_01
```

La comprobación crea una copia temporal de entradas, reconstruye ponderaciones, masas, ajuste físico de turismos y factores por recorrido, y compara cinco productos físicos y 16 anuales. Se revisan `verificacion_estudio.json`, `comparacion_coeficientes_privados.csv` y `comparacion_anual.csv` del destino. Los originales permanecen intactos.

Este comando **no lanza COPERT**. Al utilizar las ejecuciones Silver distribuidas, verifica la conexión con el balance a partir de su procedencia registrada. Los indicadores informativos `motor_copert_ejecutado` del registro de origen y `bibliotecas_recien_ejecutadas` del comprobador no prueban una ejecución nueva en esta invocación. Para verificar un motor recién ejecutado se hace primero el paso anterior y se proporciona ese destino nuevo en `--resultados-copert`; el destino de comprobación también debe ser nuevo.

## Qué se puede concluir

La igualdad de los factores verifica la parte COPERT. La igualdad del balance requiere además actividad de transporte, reparto modal, composición del parque y el ajuste físico propio de pendiente de los turismos. El resultado no procede solo de introducir un CSV anual en COPERT.

La ocupación de pasajeros, la carga técnica y el número de autobuses son magnitudes diferentes. Las excursiones mantienen un factor sin corrección de pendiente: su actividad idéntica sin/con cancela ese bloque en el ahorro principal, pero afecta al consumo absoluto y a la sensibilidad de crecimiento. TITSA 342/348 y las lanzaderas sí utilizan pendiente. Estas condiciones se mantienen; no se recalibran para lograr coincidencia.

Las entradas, factores, funciones y límites están relacionados en el [mapa de trazabilidad](trazabilidad.md). Se han comprobado las ejecuciones y los factores distribuidos; la instalación nueva del motor en otro equipo permanece pendiente de certificación. Los comandos sin motor pueden utilizarse para revisar su conexión con el balance de forma independiente. La evidencia distribuida identifica las consultas realizadas y sus factores. Quien repita el motor debe conservar su propia comprobación y utilizar sus salidas nuevas al contrastar el balance.
