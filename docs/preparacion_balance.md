# Reconstruir vías, coeficientes y balance

Este comando reconstruye la demanda y la geografía desde Bronze, clasifica las carreteras, une cada tramo con su perfil y recalcula los coeficientes y el balance de **2.500.000 visitas-persona**. Mantiene el libro, las 31 condiciones operativas y los programas de servicio elegidos. No busca otra ordenación.

## Ejecutar y localizar resultados

Después de extraer los tres ZIP e instalar el entorno fijado, desde la raíz de cualquiera de los dos repositorios:

```bash
uv run python scripts/reproducir_balance_desde_fuentes.py reproducir --destino data/silver/ejecuciones/cadena_01
```

El destino debe ser nuevo. El comando prepara primero, sin abrir Gold, y después compara. También se pueden separar las fases:

```bash
uv run python scripts/reproducir_balance_desde_fuentes.py preparar --destino data/silver/ejecuciones/cadena_02
uv run python scripts/reproducir_balance_desde_fuentes.py comparar --resultados data/silver/ejecuciones/cadena_02 --destino data/silver/ejecuciones/comparacion_02
```

| Dentro del destino de preparación | Contenido |
|---|---|
| `demanda/` | Las 26 tablas reconstruidas de demanda |
| `geografia/` | Las 118 tablas geográficas y terrenos reconstruidos |
| `clasificacion/` | Aristas, clases de carretera y unión con perfiles |
| `calculo/` | Estructura de cálculo de esta ejecución: decisiones copiadas y coeficientes nuevos, en sus rutas Medallion; utiliza el código del mismo repositorio |
| `balance/` | Los 16 productos anuales y la auditoría de los programas |
| `procedencia_indice_temporal.json` | Índice original, entradas nuevas y motivo de los sellos propios de la ejecución |
| `metadatos.json` | Fuentes, código, lecturas efectivas, restricciones, entorno y huellas de salidas |
| `comprobacion/comparacion_equivalencia.csv` | Las 33 comparaciones, cuando se usa `reproducir` |
| `comprobacion/verificacion.json` | Resultado conjunto y máxima diferencia numérica |

Para la lectura del resultado recomendado se selecciona la política y el posicionamiento del libro, dentro de cada asignación de turismos. No se suman políticas ni asignaciones alternativas. Las salidas nuevas no sustituyen Silver de referencia, Gold o el informe.

## Qué se reconstruye y qué permanece fijo

| Elemento | Tratamiento |
|---|---|
| Demanda, trazados y altimetría | Reconstruidos con las fuentes Bronze y las decisiones de configuración, mediante los productores de demanda y geografía |
| Clase de carretera | Reconstruida desde las vías originales de OpenStreetMap y las anotaciones nativas de los trazados OSRM |
| Masa y consumo de turismos | Masas calculadas desde los microdatos DGT; pesos, curvas y corrección física recalculados con las funciones científicas existentes |
| Selección técnica del parque | Se conservan los grupos, tamaños y condiciones de representación elegidos en `data/silver/vehiculos/flota_teide/`; no se afirma reconstruir esa selección completa desde bruto |
| Factores COPERT | Se utilizan las tres bibliotecas certificadas de `data/silver/copert/factores/`; este comando no vuelve a lanzar el motor |
| Operación | Se conservan red, paradas, inventario y programas seleccionados; se vuelven a comprobar las circulaciones y los regresos |
| Posicionamiento | Se conserva la base técnica de ponderación por kilómetros en vacío; se recalcula su energía con los arcos recién valorados |
| Resultados Gold | Solo se abren al comparar, después del cálculo |

La base de posicionamiento está en `data/silver/operacion/referencias_actividad/actividad_para_factor_posicionamiento.csv`. Contiene exclusivamente identidad de movimientos, arcos, carga técnica, kilómetros y días de ponderación. Es una base fija para obtener el consumo por kilómetro de las activaciones, no la actividad anual de la ordenación recomendada. Se ha extraído de la referencia técnica distribuida, descartando sus columnas de energía. El manifiesto de procedencia identifica ambas huellas y las once columnas. La actividad anual se calcula con las fechas, unidades y activaciones vigentes, una sola vez.

Se mantienen los controles de conciliación del código vigente, por ejemplo el consumo anual de TITSA identificado en el índice. Se utilizan para detectar una discrepancia, sin sustituir la energía recién calculada. La comparación completa con las referencias Silver y Gold se ejecuta después.

El contrato `manifiestos/preparacion_balance.json` sella las entradas y distingue las selecciones fijas Silver de las fuentes Bronze. La auditoría de lectura rechaza cualquier dato no declarado, incluido todo Gold, los perfiles anteriores, la ponderación anterior y los coeficientes energéticos anteriores. La aceptación se realiza además ocultando físicamente esos resultados, el desarrollo original y los antecedentes, y bloqueando la red. Se utiliza un entorno independiente previamente instalado; no se declara una instalación nueva del motor COPERT.

## Clasificación y unión física

Se mantiene la regla de clasificación habitual del estudio sobre 31 comparaciones territoriales. Se reconstruyen **255.173 aristas**, **274 combinaciones de recorrido y clase**, y **210.977 segmentos** al cruzar los límites de vía con los intervalos del perfil. La visita interior se incorpora con el patrón vigente, desde cada entrada y con regreso a ella. No se añade dos veces a las dos direcciones.

Para ocho accesos reasignados se utilizan las respuestas OSRM originales y sus anotaciones de nodos. Antes de aprovecharlas se exige que geometría y distancia coincidan con el trazado de referencia. Se comprueban pares de coordenadas, identidad de nodos y su correspondencia con la precisión de seis decimales del protocolo. En los casos que lo requieren, la vía debe cubrir la arista completa dentro de la banda derivada de esa cuantización y todos los candidatos deben coincidir en clase. No se utiliza la carretera más cercana.

La comprobación de una coordenada admite media celda de 10⁻⁶ grados, con una corrección limitada al redondeo binario de coma flotante. Esto permite los casos situados justo en la mitad de la celda sin aceptar un nodo distinto o próximo. Las vías y archivos fuente quedan identificados por arista.

Se reconstruyen **6.079 aristas** y se mantiene el residuo no clasificado de **34,81390438189864 m**. Ese residuo conserva tres alternativas —vía local, convencional o rápida—, que producen **21.411 segmentos** en total. Los otros 18 trazados dirigidos de refuerzo mantienen su envolvente por segmento entre las tres clases. La incertidumbre no se sustituye por una etiqueta elegida para mejorar el ahorro.

Los perfiles mantienen sus cotas y el desnivel firmado. La unión comprueba que no se pierde longitud ni desnivel. En los accesos OSRM se normaliza únicamente la distancia horizontal a los kilómetros de actividad del catálogo; después se recalcula la pendiente a partir de esa distancia y de las cotas originales. No se normalizan las alturas ni se limita la pendiente física del turismo.

## De cada segmento al balance

1. **Turismos.** Se reconstruyen masas de 816 grupos que representan 509.459 vehículos, 3.423 filas de curvas y masas, 3.780 energías por recorrido/caso y 12.480 coeficientes por origen, colectivo, sentido, rama y contraste físico. Se conserva la separación entre particulares y alquiler. La corrección gravitatoria se aplica a gasolina y diésel convencionales, con el tratamiento de descenso del libro; las demás tecnologías mantienen la base definida en el estudio.
2. **Lanzaderas.** Se valoran los diez recorridos dirigidos y las cargas técnicas del 0 % en vacío y 50 % comercial. Los 28 valores por arco operativo integran los tramos interiores efectivamente recorridos; no reparten la energía del eje entero solo por distancia. Velocidad y categoría proceden del libro y las bibliotecas certificadas.
3. **TITSA.** Se valoran de nuevo los cuatro recorridos de las líneas 342/348 y sus 1.182 segmentos, con pendiente, velocidad y carga del estudio. Las curvas COPERT de autocar se aplican con su intervalo de pendiente ±6 %; esto no altera las cotas originales. Se reconstruye también la alimentación en coche hasta cabeceras de sus viajeros, manteniendo la distribución territorial condicionada y 3,2 personas por coche.
4. **Excursiones.** Las 312 referencias por origen/colectivo/sentido se obtienen con acceso dirigido y la mitad del recorrido interior de ida y vuelta en cada sentido. Se mantiene el factor de autocar a pendiente cero y la ocupación equivalente de 35,99 personas. Esta hipótesis común se conserva en ambos escenarios; el incremento de excursiones se estudia por separado.
5. **Balance.** Se aplican estos coeficientes nuevos a las mismas circulaciones, fechas y visitas, retirando el acceso antiguo antes de incorporar un acceso reasignado. La punta sustituye al día de su fecha y los transbordos no crean visitas. Se reconstruyen también las sensibilidades de excursiones, rendimiento y posicionamiento contenidas en los 16 productos anuales.

## Evidencia, tolerancia y límites

Las 33 interfaces comprenden 17 comparaciones físicas/energéticas con Silver y los 16 productos anuales con Gold. `manifiestos/trazabilidad_preparacion_balance.csv` identifica cada salida, su referencia, claves, columnas, unidades y código. La comparación conserva ausencias e identificadores, además de los números. La tolerancia absoluta sigue siendo **10⁻⁸**; no se modifica para aceptar discrepancias. Las columnas físicas enumeradas de segmentos se distinguen de los textos de procedencia adicionales.

Esta comprobación verifica la unión numérica de fuentes, perfiles, segmentos, coeficientes y balance bajo las decisiones elegidas. No certifica que cada selección técnica del parque o cada programa se haya generado de nuevo desde bruto. Tampoco valida rasante real, recorridos autorizados, disponibilidad de autobuses, turnos, ocupaciones observadas o un óptimo global. La instalación nueva del entorno Python desde los ZIP ya se ha comprobado y está documentada en manifiestos/comprobacion_entrega_final.json. La instalación del motor COPERT en otro equipo, las condiciones de las fuentes y la revisión documental son comprobaciones distintas, con el alcance indicado en sus guías.
