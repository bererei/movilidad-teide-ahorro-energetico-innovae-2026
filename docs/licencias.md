# Licencias y condiciones de esta entrega

Las condiciones distinguen **código propio, documentación propia, datos de origen y materiales de terceros**. Cada ámbito mantiene sus avisos y condiciones; no existe una licencia única para todo el paquete.

## Código y documentación originales

El código original de `src/`, `scripts/` y `tests/`, la configuración propia y las celdas de código originales de los cuadernos se comparten bajo **MIT**, una licencia permisiva de software. El [texto completo](../LICENSE) exige conservar su aviso de autoría y condiciones. Los valores o clasificaciones procedentes de otras fuentes conservan su procedencia y condiciones; incluirlos en configuración no los convierte en creación propia.

Los textos originales de documentación Markdown, las explicaciones de anexos, las celdas de texto de cuadernos y los metadatos descriptivos propios se comparten bajo **Creative Commons Reconocimiento 4.0 (CC BY 4.0)**. Hay que conservar la atribución, enlazar la licencia e identificar cambios. El [texto completo](../LICENSES/CC-BY-4.0.txt) acompaña a la entrega.

Estas licencias no conceden derechos sobre datos, imágenes, citas, programas o documentos ajenos. La adopción de la edición pública y las condiciones de sus recursos se comprueban por separado de la aceptación del contenido. Las fuentes ajenas conservan sus condiciones específicas.

## Bases geográficas y resultados

Las bases derivadas de OpenStreetMap indicadas en el [registro cartográfico](../manifiestos/condiciones_cartograficas.csv) conservan **Open Database License 1.0 (ODbL 1.0)** sobre la compilación. Se mantienen además los créditos y condiciones de los contenidos que incorporan: terreno IGN/SCNE, vías del Cabildo y referencias de TITSA cuando corresponden. El [texto completo](../LICENSES/ODbL-1.0.txt) acompaña a las bases legibles por máquina ya distribuidas en las capas de datos.

Se distinguen bases con geometrías, identificadores de red o secuencias físicas, metadatos descriptivos y tablas de control o resumen. La asignación usa la identidad de archivos ya revisados y el contenido de sus esquemas. La licencia ODbL no se asigna a todo CSV, al código o a la colección completa. Compartir una imagen exige conservar el crédito del producto y las obligaciones de su base subyacente; el archivo de imagen no se convierte automáticamente en la base de datos.

Los resultados numéricos propios conservan sus fuentes, transformaciones y supuestos. La duda sobre una copia original no se interpreta automáticamente como prohibición de comunicar cualquier resultado agregado. Tampoco se atribuye una licencia propia a todos sus datos de origen.

## COPERT: entradas, resultados, proyectos y programa

Las **entradas y proyectos del estudio** se distinguen del motor COPERT y su base de aplicación. La entrega contiene 34 consultas con 2.836 tablas nativas serializadas en CSV, además de dos índices. Cada consulta de turismos contiene 83 hojas y cada consulta de autocar 84. Los valores por defecto y la estructura procedentes del programa permanecen explícitos y atribuidos; no se presentan como decisiones propias ni como una biblioteca de coeficientes extraída del ejecutable.

Los 34 proyectos se han generado con la opción oficial `-keep`. Cada contenedor revisado contiene un `copuser.saf`; no contiene el ejecutable, bibliotecas DLL o `copapp.saf` en su directorio. No se ha descompilado la base. La [documentación oficial de la interfaz automática](https://copert.emisia.com/mediawiki/Command_Line_Interface_(CLI)), apartados Input data y -keep, describe estas entradas y proyectos. El [registro de contenido](../manifiestos/contenido_copert.csv) documenta las tablas, consultas, miembros y huellas comprobados.

El criterio de inclusión adoptado es compartir estas entradas, salidas calculadas y proyectos producidos por el usuario para repetir el estudio. El [acuerdo público del programa](https://copert.emisia.com/mediawiki/License_Agreement) regula el software y no identifica una prohibición específica de comunicar estos archivos de usuario. Esto es un criterio razonado sobre la selección comprobada, **no una autorización expresa de EMISIA ni una licencia sobre su programa o todos sus contenidos internos**. Los valores por defecto conservan su origen. Las capturas completas del manual web tienen un caso distinto en el registro externo.

Quien ejecute el motor debe instalar y utilizar legítimamente la versión compatible y aceptar las condiciones aplicables. No se distribuye el motor, su activación o el producto comercial COPERT Data. La relectura de exportaciones permite verificar factores sin instalarlo.

## Licencia específica del informe de visitantes

El PDF `data/bronze/documentacion/visitas_parque/Visitantes_OAPN_2025.pdf` declara en su página 2 **CC BY-NC-SA 4.0**, Reconocimiento–NoComercial–CompartirIgual. La publicación es de mayo 2026 y trata la anualidad 2025. Esta condición específica prevalece sobre el aviso general del portal para ese documento.

Se conserva el PDF sin modificar, sus autores, fotografías OAPN, fuente y [texto de licencia](../LICENSES/CC-BY-NC-SA-4.0.txt). Su redistribución y las adaptaciones sujetas a ella deben respetar atribución, no comercial y compartir igual cuando corresponda. No se presume permiso de uso comercial del documento. La [licencia oficial](https://creativecommons.org/licenses/by-nc-sa/4.0/) permite examinar ese alcance. No se extiende por el mero enlace a hechos, código propio o resultados independientes; tampoco se declara todo el paquete de datos abierto sin restricciones.

## Referencias bibliográficas y condiciones particulares

Las seis copias de apoyo identificadas en el [registro de referencias](../manifiestos/referencias_documentales.csv) no se distribuyen. Se mantienen sus citas, enlaces, fechas, localizadores y huellas; los originales completos se conservan en desarrollo. No son entradas numéricas ni hay que descargarlas para ejecutar. Este criterio cierra cuatro casos de difusión sin asignarles una licencia de copia íntegra.

La [guía de fuentes](distribucion_fuentes.md) documenta el criterio de inclusión de visores y marcas para el encargo del Cabildo y la inclusión de aforos bajo el régimen general del Cabildo con la confirmación de titularidad identificada en el registro de procedencia. Las condiciones del resto de fuentes y de COPERT permanecen como se han documentado en este texto. Se conserva la atribución de cada archivo y no se asigna una licencia global a los datos.

La entrega se identifica en `manifiestos/referencia.json` y en el acta externa que acompaña a sus paquetes. Las condiciones de fuentes y la reproducción científica tienen comprobaciones diferentes, descritas en la [guía de entrega](entrega_publica.md).
