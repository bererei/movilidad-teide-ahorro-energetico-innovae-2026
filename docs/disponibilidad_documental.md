# Informe, anexos y archivos de la entrega

El estudio corresponde al **informe v0.28**, edición de 16 de noviembre de 2026, y compara **2.500.000 visitas-persona anuales** sin y con intervención. Las condiciones y los resultados se identifican en la [referencia de la entrega](../manifiestos/referencia.json).

## Localizar los documentos

| Documento | Ubicación y función |
|---|---|
| [Informe original reproducible](informe_energetico/INFORME_ENERGETICO_v0.28_2026-11-16.pdf) | `docs/informe_energetico/`; explica método, resultados, implantación y límites |
| [Informe firmado](informe_energetico/INFORME_ENERGETICO_v0.28_2026-11-16_firmado.pdf) | Copia firmada de la misma edición |
| [Fuentes del informe](informe_energetico/main.tex) | Maestro LaTeX y recursos de tablas y figuras en la misma carpeta |
| [Anexos de lectura](../data/gold/anexos/) | Tablas de datos, índice, diccionario y libro de consulta |
| [Resultados técnicos](../data/gold/referencia_anual/) | Los 16 productos anuales de referencia que compara el cálculo |

Las [releases del repositorio](https://github.com/bererei/movilidad-teide-ahorro-energetico-innovae-2026/releases) agrupan código, datos y documentos de cada entrega. El PDF completo se ofrece como descarga independiente de la misma edición. Los paquetes de datos se extraen en la raíz del proyecto, siguiendo la [guía de reproducción](reproduccion.md).

## Original reproducible y copia firmada

Los dos PDF contienen la misma edición del estudio y se identifican por separado en [firma_informe.json](../manifiestos/firma_informe.json), con sus rutas, tamaños y huellas SHA-256. La huella permite comprobar que el archivo descargado coincide con el identificado en la entrega. El original es la referencia de las fuentes LaTeX; la copia firmada se conserva sin editar ni recompilar.

## Comprobar el contenido recibido

El [inventario](../manifiestos/archivos.json) distingue los archivos distribuidos de los documentos no incluidos en cada paquete. La presencia de un documento en ese catálogo no significa que sus bytes se hayan entregado o comprobado. Las rutas documentales se mantienen para poder localizar la misma edición.

La reproducción numérica utiliza las fuentes y los resultados técnicos. El cuaderno [07 · Comprobación e informe](../notebooks/07_comprobacion_e_informe.ipynb) relaciona 33 anexos, 392 columnas, 43 tablas, 20 figuras y ocho fichas con datos y código. Para generar o compilar el informe se necesitan además sus fuentes y recursos documentales. Los verificadores explican si falta una entrada de cálculo o un recurso necesario para la generación documental.
