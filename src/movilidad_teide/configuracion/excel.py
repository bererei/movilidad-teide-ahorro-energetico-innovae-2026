"""configuracion: excel. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from io import BytesIO
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableColumn, TableStyleInfo
from openpyxl.worksheet.filters import AutoFilter
from openpyxl.utils.cell import range_boundaries
from openpyxl.workbook.properties import CalcProperties
from openpyxl.formatting.formatting import ConditionalFormattingList
from movilidad_teide.configuracion.parametros_tipos import AZUL
from movilidad_teide.configuracion.parametros_tipos import CASOS
from movilidad_teide.configuracion.parametros_tipos import LIBRO
from movilidad_teide.configuracion.parametros_tipos import TEXTO
from movilidad_teide.configuracion.parametros_tipos import ACCESOS
from movilidad_teide.configuracion.parametros_tipos import ErrorParametros
from movilidad_teide.configuracion.parametros_tipos import JADE
from movilidad_teide.configuracion.parametros_tipos import MODOS


def _cabecera(ws, titulo, instrucciones, encabezados, anchos):
    ws.sheet_view.showGridLines = False
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(encabezados))
    ws.cell(1, 1, titulo).font = Font(name="Arial", size=19, bold=True, color=AZUL)
    ws.row_dimensions[1].height = 32
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(encabezados))
    ws.cell(3, 1, instrucciones).alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[3].height = 42
    for i, (h, ancho) in enumerate(zip(encabezados, anchos), 1):
        ws.cell(6, i, h).font = Font(name="Arial", bold=True, color="FFFFFF")
        ws.cell(6, i).fill = PatternFill("solid", fgColor=AZUL)
        ws.cell(6, i).alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[ws.cell(6, i).column_letter].width = ancho
    ws.row_dimensions[6].height = 32
    ws.freeze_panes = "D7"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "1:6"




def crear_libro(root, destino=None):
    """Crear una vez; nunca regenerar sobre un libro con decisiones ya introducidas."""
    from movilidad_teide.configuracion.catalogo import _firma_referencias
    from movilidad_teide.configuracion.referencias import _fundamento
    from movilidad_teide.configuracion.referencias import _referencias
    from movilidad_teide.configuracion.catalogo import _valor
    from movilidad_teide.configuracion.catalogo import catalogo
    from movilidad_teide.trazabilidad import sha256_archivo
    root = Path(root); destino = Path(destino) if destino else root / LIBRO
    if destino.exists():
        raise FileExistsError("El libro ya existe; no se sobrescriben propuestas ni elecciones.")
    plantilla, valores = _referencias(root)
    campos = catalogo(); wb = Workbook(); inicio = wb.active; inicio.title = "Inicio"
    inicio.sheet_view.showGridLines = False
    inicio.column_dimensions["A"].width = 32
    inicio.column_dimensions["B"].width = 38
    for col in "CDEFGH": inicio.column_dimensions[col].width = 13
    inicio.merge_cells("A1:H2"); inicio["A1"] = "Movilidad Teide · parámetros y escenarios"
    inicio["A1"].font = Font(name="Arial", size=21, color=AZUL, bold=True)
    inicio["A5"] = "Caso que se va a calcular"; inicio["B5"] = "Central"
    inicio["B5"].fill = PatternFill("solid", fgColor="EEF5F2")
    inicio["B5"].protection = Protection(locked=False)
    dv = DataValidation(type="list", formula1='"' + ",".join(CASOS) + '"'); dv.errorTitle = "Elige un caso de la lista"; dv.showErrorMessage = True
    inicio.add_data_validation(dv); dv.add(inicio["B5"])
    # Las instrucciones y vínculos se definen en _preparar_interfaz.
    inicio.protection.sheet = True
    props = wb.create_sheet("Propuestas")
    _cabecera(props, "Propuestas y referencias conservadas", "Solo lectura: punto de partida, fundamento, procedencia y alcance. Las elecciones se editan en Escenarios.", ["Grupo", "Parámetro", "Unidad", "Propuesta / referencia", "Justificación de la propuesta", "Fuente y estado", "Aplicación actual", "Id"], [22, 48, 19, 27, 65, 55, 42, 24])
    esc = wb.create_sheet("Escenarios")
    _cabecera(esc, "Elecciones por caso", "Editar únicamente Elección, Valor manual y Motivo manual (verde). La referencia y su fundamento se conservan; filtrar por Caso y Grupo. Valor usado se recalcula al abrir Excel.", ["Caso", "Grupo", "Parámetro", "Unidad", "Referencia original (vinculada)", "Fundamento de propuesta", "Elección", "Valor manual", "Motivo manual", "Valor usado", "Fuente / estado de referencia", "Aplicación", "Id", "Clave"], [17, 20, 48, 18, 25, 62, 22, 25, 62, 25, 52, 40, 24, 28])
    resumen = wb.create_sheet("Resumen")
    _cabecera(resumen, "Caso seleccionado: valores y fundamento", "Consulta: la elección de caso está en Inicio!B5. No es un informe de ahorro. Los parámetros pendientes de conectar se identifican expresamente.", ["Grupo", "Parámetro", "Unidad", "Valor usado", "Elección", "Justificación utilizada", "Aplicación"], [22, 48, 18, 28, 23, 75, 44])
    origen = wb.create_sheet("_Origen")
    origen.append(["Version", "1.0"]); origen.append(["Plantilla inicial", json.dumps(plantilla, ensure_ascii=False)])
    origen.append(["Configuración anterior", "config/actividad_corredor_norte.json"])
    origen.append(["SHA256 configuración anterior", sha256_archivo(root / "config/actividad_corredor_norte.json")])
    origen.sheet_state = "veryHidden"
    filas_prop = {}
    for fila, campo in enumerate(campos.values(), 7):
        motivo, fuente, estado = _fundamento(campo)
        valor = valores.get(campo.clave)
        props.append([campo.grupo, campo.nombre, campo.unidad, valor, motivo, fuente + " · " + estado, campo.aplicacion, campo.clave])
        filas_prop[campo.clave] = fila
    pendientes = {k for k in campos if valores.get(k) is None} | {"ocupacion_coche", "fraccion_captados_coche", "ocupacion_guagua_aforo", "criterio_pesos_turismos", "criterio_tamanos_turismos", "criterio_categoria_incompleta_turismos", "criterio_norma_incompleta_turismos", "velocidad_turismo_local", "velocidad_turismo_convencional", "velocidad_turismo_rapida", "criterio_reparto_territorial_anual", "criterio_tara_turismos", "masa_persona_turismo_kg", "equipaje_turismo_kg_coche"}
    pendientes.add('perdida_rendimiento_guaguas_contraste')
    for caso in CASOS:
        for campo in campos.values():
            fila = esc.max_row + 1; pr = filas_prop[campo.clave]
            modo = ("Pendiente" if campo.clave in pendientes else "Propuesta") if caso == "Central" else "Heredar central"
            manual = motivo_manual = None
            if caso != "Central" and campo.clave == "metodo_crecimiento":
                modo = "Manual"; manual = "Tasa compuesta 2019–2025" if caso == "Variante A" else "Tasa compuesta 2023–2025"
                motivo_manual = "Contraste histórico ya calculado; mantiene el resto de decisiones del caso Central. No es un escenario operativo aprobado."
            # Las columnas derivadas se rellenan desde _formulas_vista, en un único sitio.
            esc.append([caso, campo.grupo, campo.nombre, campo.unidad, None, None,
                        modo, manual, motivo_manual, None, None,
                        campo.aplicacion, campo.clave, f"{caso}|{campo.clave}"])
            for col in [7, 8, 9]:
                esc.cell(fila, col).protection = Protection(locked=False)
                esc.cell(fila, col).fill = PatternFill("solid", fgColor="EEF5F2")
            if campo.tipo == "porcentaje":
                for col in [5, 8, 10]: esc.cell(fila, col).number_format = "0.00%"
                props.cell(pr, 4).number_format = "0.00%"
    for fila, campo in enumerate(campos.values(), 7):
        resumen.append([campo.grupo, campo.nombre, campo.unidad, None, None, None, campo.aplicacion])
        if campo.tipo == "porcentaje": resumen.cell(fila, 4).number_format = "0.00%"
    for nombre, ws, ultima_col in [("TablaPropuestas", props, 8), ("TablaEscenarios", esc, 14), ("TablaResumen", resumen, 7)]:
        for row in ws.iter_rows(min_row=7):
            for c in row:
                c.font = Font(name="Arial", size=11, color=TEXTO)
                c.alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[row[0].row].height = 62 if ws.title == "Resumen" else 92
        tabla = Table(displayName=nombre, ref=f"A6:{ws.cell(6, ultima_col).column_letter}{ws.max_row}")
        tabla.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(tabla); ws.protection.sheet = True
        ws.protection.autoFilter = False; ws.protection.selectLockedCells = False; ws.protection.selectUnlockedCells = False
        ws.print_options.horizontalCentered = True
        ws.print_area = f"A1:{ws.cell(6, ultima_col).column_letter}{ws.max_row}"
    props.column_dimensions["H"].hidden = True
    esc.column_dimensions["M"].hidden = True; esc.column_dimensions["N"].hidden = True
    referencias = {k: {"valor": _valor(props.cell(f, 4).value, campos[k]), "justificacion": props.cell(f, 5).value, "fuente": props.cell(f, 6).value} for k, f in filas_prop.items()}
    origen["A5"] = "Firma de referencias conservadas"; origen["B5"] = _firma_referencias(referencias)
    wb.calculation = CalcProperties(calcId=191029, calcMode="auto", fullCalcOnLoad=True)
    wb.properties.title = "Movilidad Teide — parámetros, referencias y elecciones"
    wb.properties.creator = "Proyecto Movilidad Teide"
    destino.parent.mkdir(parents=True, exist_ok=True)
    _guardar_con_vista(wb, destino)
    return destino

def _mapa_filas(wb):
    props, esc = wb['Propuestas'], wb['Escenarios']
    referencias = {props.cell(f, 8).value: f for f in range(7, props.max_row + 1)}
    filas = {(esc.cell(f, 1).value, esc.cell(f, 13).value): f for f in range(7, esc.max_row + 1)}
    return referencias, filas

def _manual_valido_excel(campo, f, solo_valor=False):
    """Comprobar tipo, rango, años y ausencia de fórmulas en entradas manuales."""
    h, i = f'H{f}', f'I{f}'
    condiciones = [f'NOT(ISBLANK({h}))', f'NOT(_xlfn.ISFORMULA({h}))']
    if not solo_valor: condiciones += [f'LEN(TRIM({i}&""))>0', f'NOT(_xlfn.ISFORMULA({i}))']
    if campo.tipo == 'opcion':
        condiciones.append('OR(' + ','.join(f'{h}="{v}"' for v in campo.opciones) + ')')
    elif campo.tipo == 'anios':
        # No eliminar silenciosamente una lista vacía: para no excluir años se escribe Ninguno.
        limpio = f'SUBSTITUTE({h}," ","")'
        tokens = f'(LEN({limpio})-LEN(SUBSTITUTE({limpio},",",""))+1)'
        reconocidos = f'SUMPRODUCT(--ISNUMBER(SEARCH(","&ROW($1900:$2100)&",",","&{limpio}&",")))'
        condiciones.append(f'IF(LOWER(TRIM({h}&""))="ninguno",TRUE,AND(LEN({limpio})=5*{tokens}-1,{reconocidos}={tokens}))')
    else:
        condiciones.append(f'ISNUMBER({h})')
        if campo.tipo == 'entero': condiciones.append(f'{h}=INT({h})')
        if campo.minimo is not None: condiciones.append(f'{h}>={campo.minimo}')
        if campo.maximo is not None: condiciones.append(f'{h}<={campo.maximo}')
        if campo.clave == 'km_OROTAVA': condiciones.append(f'{h}>0')
    return 'IFERROR(AND(' + ','.join(condiciones) + '),FALSE)'


def _formulas_vista(wb):
    """Una definición de los vínculos; se usa al guardar y al verificar su integridad."""
    from movilidad_teide.configuracion.catalogo import catalogo
    referencias, filas = _mapa_filas(wb)
    campos = catalogo(); ultimo = wb['Escenarios'].max_row
    formulas = {'Inicio': {}, 'Escenarios': {}, 'Resumen': {}}
    esc = formulas['Escenarios']
    def base(caso, clave):
        f = filas[(caso, clave)]; g = f'G{f}'
        if caso != 'Central':
            heredado = base('Central', clave)
            alternativa = f'IF({g}="Heredar central",{heredado},"REVISAR")'
        else: alternativa = '"REVISAR"'
        expresion = (f'IF({g}="Manual",IF({_manual_valido_excel(campos[clave], f)},"CORRECTO","REVISAR"),'
                f'IF({g}="Propuesta",IF(E{f}="PENDIENTE","PENDIENTE","CORRECTO"),'
                f'IF({g}="Pendiente","PENDIENTE",{alternativa})))')
        return f'IF(AND({g}<>"Manual",NOT(ISBLANK(H{f})),NOT({_manual_valido_excel(campos[clave], f, solo_valor=True)})),"REVISAR",{expresion})'
    for (caso, clave), f in filas.items():
        pr = referencias[clave]; cr = filas[('Central', clave)]
        esc[f'E{f}'] = f'=IF(ISBLANK(Propuestas!D{pr}),"PENDIENTE",Propuestas!D{pr})'
        esc[f'F{f}'] = f'=Propuestas!E{pr}'
        esc[f'K{f}'] = f'=Propuestas!F{pr}'
        alternativa = f'IF(G{f}="Heredar central",J{cr},"REVISAR")' if caso != 'Central' else '"REVISAR"'
        esc[f'J{f}'] = (f'=IF(G{f}="Manual",IF({_manual_valido_excel(campos[clave], f)},H{f},"REVISAR"),'
                       f'IF(G{f}="Propuesta",E{f},IF(G{f}="Pendiente","PENDIENTE",{alternativa})))')
        estado = base(caso, clave)
        # Comprobar dependencias de la elección sin introducir ciclos con Valor usado.
        if clave in {'reparto_cupo', 'calendario', 'metodo_crecimiento'}:
            etiqueta, dependencias = {
                'reparto_cupo': ('Porcentajes manuales', [f'cuota_{p}' for p in ACCESOS]),
                'calendario': ('Número de días manual', ['dias_servicio']),
                'metodo_crecimiento': ('Tasas manuales por acceso', [f'tasa_{p}' for p in ACCESOS]),
            }[clave]
            refs = [f'J{filas[(caso, k)]}' for k in dependencias]
            valido = f'COUNT({",".join(refs)})={len(refs)}'
            if clave == 'reparto_cupo': valido = f'AND({valido},ABS(SUM({",".join(refs)})-1)<=0.000000001)'
            estado = f'IF({estado}<>"CORRECTO",{estado},IF(J{f}="{etiqueta}",IF({valido},"CORRECTO","REVISAR"),"CORRECTO"))'
        esc[f'O{f}'] = '=' + estado
    for f, clave in enumerate(referencias, 7):
        indice = f'MATCH(Inicio!$B$5&"|{clave}",Escenarios!$N$7:$N${ultimo},0)'
        def seleccionado(col): return f'INDEX(Escenarios!${col}$7:${col}${ultimo},{indice})'
        cr = filas[('Central', clave)]; pr = referencias[clave]
        formulas['Resumen'][f'D{f}'] = '=' + seleccionado('J')
        formulas['Resumen'][f'E{f}'] = '=' + seleccionado('G')
        modo = seleccionado('G')
        motivo = f'IF({modo}="Manual",{seleccionado("I")},IF({modo}="Heredar central",IF(Escenarios!G{cr}="Manual",Escenarios!I{cr},Propuestas!E{pr}),Propuestas!E{pr}))'
        estado = seleccionado('O')
        formulas['Resumen'][f'F{f}'] = f'=IF({estado}="REVISAR","Revisar elección, valor, motivo y dependencias.",IF({seleccionado("J")}="PENDIENTE","Pendiente de elegir. "&Propuestas!E{pr},{motivo}))'
        formulas['Resumen'][f'H{f}'] = '=' + estado
    necesarios = ['anio_base', 'anio_objetivo', 'metodo_crecimiento', 'anios_excluidos', 'cupo_global',
                  'reparto_cupo', 'calendario', 'subidas_OROTAVA', 'bajadas_OROTAVA', 'reposiciones_OROTAVA', 'km_OROTAVA']
    resumen_filas = {k: f for f, k in enumerate(referencias, 7)}
    pendientes = ','.join(f'Resumen!D{resumen_filas[k]}="PENDIENTE"' for k in necesarios)
    formulas['Inicio']['B6'] = f'=IF(COUNTIF(Escenarios!O7:O{ultimo},"REVISAR")>0,"REVISAR ELECCIONES",IF(OR({pendientes}),"COMPLETAR ACTIVIDAD","ENTRADAS DE ACTIVIDAD COMPLETAS"))'
    casos = ','.join(f'Inicio!B5="{c}"' for c in CASOS)
    formulas['Inicio']['B6'] = f'=IF(OR({casos}),{formulas["Inicio"]["B6"][1:]},"REVISAR CASO")'
    for celda, formula in list(formulas['Resumen'].items()):
        formulas['Resumen'][celda] = f'=IFERROR({formula[1:]},"REVISAR CASO")'
    formulas['Resumen']['A4'] = '="Caso seleccionado: "&Inicio!B5'
    return formulas


def _cache_vista(wb):
    """Resolver la vista inicial desde las entradas, conservando cero y pendientes."""
    from movilidad_teide.configuracion.catalogo import _valor
    from movilidad_teide.configuracion.catalogo import catalogo
    referencias, filas = _mapa_filas(wb); campos = catalogo()
    props, esc = wb['Propuestas'], wb['Escenarios']
    valores, motivos, basicos, estados = {}, {}, {}, {}
    def resolver(caso, clave):
        k = (caso, clave)
        if k in valores: return
        f, pr = filas[k], referencias[clave]
        modo = esc.cell(f, 7).value
        if modo == 'Heredar central' and caso != 'Central':
            resolver('Central', clave)
            valores[k], motivos[k], basicos[k] = valores[('Central', clave)], motivos[('Central', clave)], basicos[('Central', clave)]
            return
        valor = None; motivo = props.cell(pr, 5).value; estado = 'PENDIENTE'
        if modo == 'Manual':
            valor = esc.cell(f, 8).value; motivo = esc.cell(f, 9).value
            try:
                v = _valor(valor, campos[clave])
                correcto = v is not None and isinstance(motivo, str) and bool(motivo.strip()) and not motivo.startswith('=')
                if clave == 'km_OROTAVA' and isinstance(v, (int, float)): correcto &= v > 0
            except ErrorParametros: correcto = False
            estado = 'CORRECTO' if correcto else 'REVISAR'
            if not correcto: valor = 'REVISAR'
        elif modo == 'Propuesta':
            valor = props.cell(pr, 4).value
            estado = 'CORRECTO' if valor is not None else 'PENDIENTE'
        elif modo != 'Pendiente': valor, estado = 'REVISAR', 'REVISAR'
        valores[k], motivos[k], basicos[k] = valor, motivo, estado
    for caso, clave in filas: resolver(caso, clave)
    # Los manuales guardados también se conservan y validan aunque no estén activos.
    for (caso, clave), f in filas.items():
        if esc.cell(f, 7).value != 'Manual':
            try: _valor(esc.cell(f, 8).value, campos[clave])
            except ErrorParametros: basicos[(caso, clave)] = 'REVISAR'
    for (caso, clave), f in filas.items():
        if esc.cell(f, 7).value == 'Heredar central' and basicos[('Central', clave)] == 'REVISAR':
            basicos[(caso, clave)] = 'REVISAR'
    estados.update(basicos)
    for (caso, clave), f in filas.items():
        if basicos[(caso, clave)] != 'CORRECTO': continue
        dependencias = []
        if clave == 'reparto_cupo' and valores[(caso, clave)] == 'Porcentajes manuales': dependencias = [f'cuota_{p}' for p in ACCESOS]
        if clave == 'calendario' and valores[(caso, clave)] == 'Número de días manual': dependencias = ['dias_servicio']
        if clave == 'metodo_crecimiento' and valores[(caso, clave)] == 'Tasas manuales por acceso': dependencias = [f'tasa_{p}' for p in ACCESOS]
        if dependencias:
            v = [valores[(caso, k)] for k in dependencias]
            valido = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)
            if valido and clave == 'reparto_cupo': valido = math.isclose(sum(v), 1, abs_tol=1e-9, rel_tol=0)
            if not valido: estados[(caso, clave)] = 'REVISAR'
    cache = {'Inicio': {}, 'Escenarios': {}, 'Resumen': {}}
    for (caso, clave), f in filas.items():
        pr = referencias[clave]; valor = valores[(caso, clave)]
        for col, v in [('E', props.cell(pr, 4).value), ('F', props.cell(pr, 5).value), ('K', props.cell(pr, 6).value), ('J', valor), ('O', estados[(caso, clave)])]:
            cache['Escenarios'][f'{col}{f}'] = v if v is not None else 'PENDIENTE'
    caso = wb['Inicio']['B5'].value
    if caso not in CASOS:
        cache['Inicio']['B6'] = 'REVISAR CASO'
        cache['Resumen'] = {f'{c}{f}': 'REVISAR CASO' for f in range(7, 59) for c in ('D','E','F','H')}
        cache['Resumen']['A4'] = 'Caso seleccionado: ' + str(caso)
        return cache
    cache['Resumen']['A4'] = 'Caso seleccionado: ' + caso
    for f, clave in enumerate(referencias, 7):
        v = valores[(caso, clave)]; estado = estados[(caso, clave)]
        just = motivos[(caso, clave)]
        if estado == 'REVISAR': just = 'Revisar elección, valor, motivo y dependencias.'
        elif v is None: just = 'Pendiente de elegir. ' + props.cell(referencias[clave], 5).value
        for col, valor in [('D', v), ('E', esc.cell(filas[(caso, clave)], 7).value), ('F', just), ('H', estado)]:
            cache['Resumen'][f'{col}{f}'] = valor if valor is not None else 'PENDIENTE'
    necesarios = ['anio_base', 'anio_objetivo', 'metodo_crecimiento', 'anios_excluidos', 'cupo_global', 'reparto_cupo', 'calendario', 'subidas_OROTAVA', 'bajadas_OROTAVA', 'reposiciones_OROTAVA', 'km_OROTAVA']
    cache['Inicio']['B6'] = ('REVISAR ELECCIONES' if 'REVISAR' in estados.values() else 'COMPLETAR ACTIVIDAD' if any(valores[(caso, k)] is None for k in necesarios) else 'ENTRADAS DE ACTIVIDAD COMPLETAS')
    return cache

def _guardar_con_vista(wb, destino):
    """Conservar vínculos y guardar sus resultados iniciales para visores sin cálculo."""
    _preparar_interfaz(wb)
    formulas = _formulas_vista(wb)
    for nombre, celdas in formulas.items():
        for celda, formula in celdas.items(): wb[nombre][celda] = formula
    wb.calculation = CalcProperties(calcId=191029, calcMode='auto', fullCalcOnLoad=True, forceFullCalc=True)
    cache = _cache_vista(wb)
    buffer = BytesIO(); wb.save(buffer); buffer.seek(0)
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    caches = {f'xl/worksheets/sheet{wb.sheetnames.index(n) + 1}.xml': valores for n, valores in cache.items()}
    with ZipFile(buffer) as entrada, ZipFile(destino, 'w') as salida:
        for miembro in entrada.infolist():
            contenido = entrada.read(miembro.filename)
            if miembro.filename in caches:
                xml = ET.fromstring(contenido)
                for celda in xml.iter(ns + 'c'):
                    if celda.get('r') not in caches[miembro.filename]: continue
                    valor = caches[miembro.filename][celda.get('r')]
                    v = celda.find(ns + 'v')
                    if v is None: v = ET.SubElement(celda, ns + 'v')
                    if isinstance(valor, (int, float)):
                        celda.attrib.pop('t', None); v.text = str(valor)
                    else: celda.set('t', 'str'); v.text = str(valor)
                contenido = ET.tostring(xml, encoding='utf-8')
            salida.writestr(miembro, contenido)

def _comprobar_tablas(wb):
    """Verificar el contrato entre rango, columnas, cabeceras y filtro de cada tabla."""
    for hoja, nombre, ancho in [('Propuestas', 'TablaPropuestas', 8),
                                ('Escenarios', 'TablaEscenarios', 15),
                                ('Resumen', 'TablaResumen', 8)]:
        ws = wb[hoja]
        if set(ws.tables) != {nombre}:
            raise ErrorParametros(f'Estructura de tabla alterada en {hoja}.')
        tabla = ws.tables[nombre]
        esperado = f'A6:{ws.cell(6, ancho).column_letter}{ws.max_row}'
        nombres = [c.name for c in tabla.tableColumns]
        if (tabla.ref != esperado or len(tabla.tableColumns) != ancho
                or [c.id for c in tabla.tableColumns] != list(range(1, ancho + 1))
                or nombres != [ws.cell(6, c).value for c in range(1, ancho + 1)]
                or not all(isinstance(n, str) and n for n in nombres)
                or len({n.casefold() for n in nombres}) != ancho
                or tabla.autoFilter is None or tabla.autoFilter.ref != esperado):
            raise ErrorParametros(f'Estructura de tabla incoherente en {hoja}; revisa columnas, cabeceras y filtros.')

def _comprobar_vinculos(wb):
    """Impedir que una vista manipulada muestre algo distinto del modelo leído."""
    from movilidad_teide.configuracion.catalogo import catalogo
    _comprobar_tablas(wb)
    for nombre, celdas in _formulas_vista(wb).items():
        for celda, formula in celdas.items():
            if wb[nombre][celda].value != formula:
                raise ErrorParametros(f'Vínculo o fórmula alterado en {nombre}!{celda}; restaura el libro de parámetros.')
    referencias, filas = _mapa_filas(wb)
    for f, clave in enumerate(referencias, 7):
        campo = catalogo()[clave]
        for col, esperado in [(1, campo.grupo), (2, campo.nombre), (3, campo.unidad), (7, campo.aplicacion)]:
            if wb['Resumen'].cell(f, col).value != esperado:
                raise ErrorParametros('Significado o unidad alterados en Resumen.')
    for (caso, clave), f in filas.items():
        if wb['Escenarios'].cell(f, 14).value != f'{caso}|{clave}':
            raise ErrorParametros('Clave de enlace alterada en Escenarios.')



def _preparar_interfaz(wb):
    """Explicar el flujo en el propio libro; solo se editan caso y columnas verdes."""
    from movilidad_teide.configuracion.catalogo import catalogo
    from openpyxl.comments import Comment
    from openpyxl.formatting.rule import CellIsRule
    esc, res, inicio = wb['Escenarios'], wb['Resumen'], wb['Inicio']
    esc['E6'] = 'Referencia original (vinculada)'
    esc['O6'] = 'Estado de elección'; res['H6'] = 'Estado de elección'
    for ws, col in [(esc, 15), (res, 8)]:
        ws.cell(6, col)._style = ws['G6']._style
        ws.column_dimensions[ws.cell(6, col).column_letter].width = 22
        for f in range(7, ws.max_row + 1):
            ws.cell(f, col).font = Font(name='Arial', size=11, color=TEXTO)
            ws.cell(f, col).alignment = Alignment(wrap_text=True, vertical='top')
        tabla = next(iter(ws.tables.values()))
        tabla.ref = f'A6:{ws.cell(6, col).column_letter}{ws.max_row}'
        ws.print_area = f'A1:{ws.cell(6, col).column_letter}{ws.max_row}'
        ws.conditional_formatting = ConditionalFormattingList()
        rango = f'{ws.cell(7, col).column_letter}7:{ws.cell(7, col).column_letter}{ws.max_row}'
        ws.conditional_formatting.add(rango, CellIsRule(operator='equal', formula=['"REVISAR"'], fill=PatternFill('solid', fgColor='FCE5D0')))
    for ws in (wb['Propuestas'], esc, res):
        for tabla in ws.tables.values():
            primero, cabecera, ultimo, _ = range_boundaries(tabla.ref)
            tabla.tableColumns = [TableColumn(id=i, name=str(ws.cell(cabecera, c).value))
                                  for i, c in enumerate(range(primero, ultimo + 1), 1)]
            if tabla.autoFilter is None:
                tabla.autoFilter = AutoFilter(ref=tabla.ref)
            else:
                tabla.autoFilter.ref = tabla.ref
    _comprobar_tablas(wb)
    esc['A3'] = ('Propuestas es el único origen de referencias. Verde: Elección, Valor manual y Motivo manual. '
                 'Manual exige valor y motivo; Estado avisa de errores. Filtrar por Caso. Ver límites y aplicación en cada fila.')
    res['A3'] = ('Caso elegido en Inicio!B5. CORRECTO comprueba la elección; no valida físicamente la hipótesis ni indica ahorro. '
                'PENDIENTE conserva una ausencia. Consultar Aplicación para saber qué modifica el cálculo.')
    # Restringir el desplegable de Central y explicar cada entrada al seleccionarla.
    esc.data_validations.dataValidation.clear()
    campos = catalogo()
    for f in range(7, esc.max_row + 1):
        caso, clave = esc.cell(f, 1).value, esc.cell(f, 13).value
        campo = campos[clave]; opciones = MODOS[:3] if caso == 'Central' else MODOS
        dv = DataValidation(type='list', formula1='"' + ','.join(opciones) + '"', allow_blank=False)
        dv.showErrorMessage = True; dv.errorStyle = 'stop'; dv.errorTitle = 'Elección no válida'
        dv.error = 'Central no puede heredarse a sí mismo. Elige una opción de la lista.'
        esc.add_data_validation(dv); dv.add(esc.cell(f, 7))
        if campo.tipo == 'opcion':
            dv = DataValidation(type='list', formula1='"' + ','.join(campo.opciones) + '"', allow_blank=True)
        elif campo.tipo in {'entero', 'numero', 'porcentaje'}:
            dv = DataValidation(type='whole' if campo.tipo == 'entero' else 'decimal',
                operator='between' if campo.minimo is not None and campo.maximo is not None else 'greaterThanOrEqual',
                formula1=campo.minimo if campo.minimo is not None else -1e100, formula2=campo.maximo, allow_blank=True)
        else:
            dv = DataValidation(type='custom', formula1=f'OR(ISBLANK(H{f}),LEN(TRIM(H{f}&""))>0)', allow_blank=True)
        dv.showInputMessage = dv.showErrorMessage = True; dv.errorStyle = 'stop'
        dv.promptTitle = 'Valor manual: ' + campo.unidad
        dv.prompt = 'Porcentajes: 25%. Años: 2020,2021 o Ninguno. Escribir valores directos, sin fórmulas.'
        dv.errorTitle = 'Revisa el valor y su unidad'; dv.error = 'Respeta las opciones y límites. No confundir 25 con 25%.'
        esc.add_data_validation(dv); dv.add(esc.cell(f, 8))
        for c in (7, 8, 9): esc.cell(f, c).protection = Protection(locked=False)
        esc.cell(f, 8).comment = Comment(f'{campo.nombre}. Unidad: {campo.unidad}. '
            f'Límite inferior: {campo.minimo if campo.minimo is not None else "no fijado"}; superior: {campo.maximo if campo.maximo is not None else "no fijado"}. '
            'Solo se usa al elegir Manual. El motivo es obligatorio. ' + campo.aplicacion, 'Movilidad Teide')
        if campo.tipo == 'porcentaje':
            for c in (5, 8, 10): esc.cell(f, c).number_format = '0.00%'
    for ws, celdas in [(esc, {'E6': 'Vínculo a Propuestas: el valor de referencia existe en un único sitio. No implica adopción.',
                              'J6': 'Resultado de la elección. 0 es un valor; PENDIENTE no es cero. REVISAR pide corregir la entrada.',
                              'I6': 'Explicar por qué se elige el valor manual. Cambiar a Propuesta conserva esta justificación.',
                              'O6': 'Control de entrada y dependencias. El lector Python comprueba además años, integridad y condiciones del cálculo.'})]:
        for celda, texto in celdas.items(): ws[celda].comment = Comment(texto, 'Movilidad Teide')
    for dv in inicio.data_validations.dataValidation: dv.errorStyle = 'stop'
    for f in range(22, 25): inicio.cell(f, 1).value = None; inicio.cell(f, 1).hyperlink = None
    instrucciones = [
        '1. Elegir Central, Variante A o Variante B en B5; después filtrar Escenarios por ese Caso.',
        '2. Propuestas es el único origen del valor de referencia, su fundamento y procedencia. Está protegido.',
        '3. Referencia original (vinculada) muestra esa misma referencia en cada caso; no hay copias editables.',
        '4. Propuesta usa la referencia; Manual usa Valor manual y exige Motivo manual. Solo se editan columnas verdes.',
        '5. Pendiente conserva una ausencia. Heredar central mantiene la elección de Central; solo está disponible en variantes.',
        '6. Volver a Propuesta o cambiar de caso conserva los valores manuales y sus motivos anteriores.',
        '7. CORRECTO comprueba la entrada. PENDIENTE no significa cero. REVISAR indica que hay que corregir o completar algo.',
        '8. Para reparto manual del CUPO DE COCHES, completar los cuatro porcentajes hasta sumar 100%; no son porcentajes de personas.',
        '9. Escribir porcentajes como 25%. Años excluidos: 2020,2021; para no excluir años: Ninguno, con motivo.',
        '10. Guardar y ejecutar: integración de aforos si cambian sus entradas, asignación/dimensionamiento y actividad norte. Python comprueba caso y huellas.',
        '11. El resumen muestra el caso seleccionado. Cada caso compara sin/con actuación; A/B no son sin/con proyecto.',
        '12. Captación y oferta de Medianías conectadas. Coches sustituidos requieren ocupación y procedencia modal. Energía, anualización de personas y horarios reales pendientes.',
        '13. Una nueva referencia requiere versión documentada. Para explorar otra cifra, elegir Manual sin sustituir la original.',
        '14. Las ejecuciones nuevas registran valores, elecciones y resultados sin duplicar el Excel vigente; las copias históricas se conservan.',
        'Los visores sin cálculo muestran la última vista guardada. Para editar y actualizar fórmulas, usar Excel con cálculo automático.',
    ]
    for f, texto in enumerate(instrucciones, 8):
        if f'A{f}:H{f}' not in inicio.merged_cells: inicio.merge_cells(start_row=f,start_column=1,end_row=f,end_column=8)
        inicio.cell(f, 1, texto); inicio.cell(f, 1).alignment = Alignment(wrap_text=True, vertical='center')
        inicio.row_dimensions[f].height = 36
    if 'referencia_guagua_interior' in campos:
        inicio['A24'] = ('Versión actual: usar aparcamiento y visitas a primera/segunda zona. Las dos frecuencias interiores globales anteriores se conservan como antecedentes y no controlan el cálculo tras la respuesta de Luis. La compra de guaguas queda fuera de INNOVAE; su consumo se incluye con el sistema.')
        if 'A24:H24' not in inicio.merged_cells: inicio.merge_cells('A24:H24')
        inicio['A24'].alignment = Alignment(wrap_text=True,vertical='center'); inicio.row_dimensions[24].height = 60
    inicio['A6'] = 'Control de entradas'
    inicio['B6'].font = Font(name='Arial', size=11, bold=True, color=AZUL)
    inicio.merge_cells('B6:H6'); inicio.row_dimensions[6].height = 30
    for f, (nombre, hoja) in enumerate([('Referencias: origen único', 'Propuestas'), ('Editar elecciones', 'Escenarios'), ('Ver caso seleccionado', 'Resumen')], 25):
        celda = inicio.cell(f, 1, nombre); celda.hyperlink = f"#'{hoja}'!A1"
        celda.font = Font(name='Arial', color=JADE, underline='single')
    wb.security.lockStructure = True
    if 'TablaOrdenacionVigente' in inicio.tables:
        inicio['A5'] = 'Caso histórico conservado'
        inicio['A28'] = 'Referencia vigente: tabla de ordenación de 2028 desde la fila 30. Las vistas anteriores conservan sus elecciones históricas.'
        inicio['A28'].hyperlink = "#'Inicio'!A30"
        inicio['A28'].alignment = Alignment(wrap_text=True)
        inicio.merge_cells('A28:H28')
        inicio.row_dimensions[28].height = 36
        res['A1'] = 'Referencia histórica: valores y fundamento conservados'
        res['A3'] = 'Este resumen corresponde al caso histórico de Inicio!B5. La ordenación recomendada se edita y consulta en la tabla de Inicio desde la fila 30.'
