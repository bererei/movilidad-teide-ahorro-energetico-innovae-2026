"""Elecciones justificadas y conservación de referencias/ejecuciones del Excel."""
from pathlib import Path
import json
import shutil

from openpyxl import load_workbook
import pytest

from movilidad_teide.parametros import (
    ErrorParametros, LIBRO, catalogo, configuracion_actividad, conservar_ejecucion,
    crear_libro, leer_parametros, sha256_archivo,
)


@pytest.fixture
def proyecto(tmp_path, parametros_historicos):
    # Estructura versionada y elecciones históricas selladas: no dependen del estado actual de Central.
    referencia = Path(__file__).resolve().parents[1] / LIBRO
    destino = tmp_path / LIBRO
    destino.parent.mkdir()
    shutil.copy2(referencia, destino)
    # Las pruebas de edición parten del estado D182, anterior a la referencia principal.
    from movilidad_teide.parametros import _guardar_con_vista
    wb=load_workbook(destino)
    initial={(p['caso'],p['id']):p for p in parametros_historicos['elecciones_todos_los_casos']}
    for row in wb['Escenarios'].iter_rows(min_row=7):
        if (row[0].value,row[12].value) not in initial:continue
        p=initial[row[0].value,row[12].value]
        row[6].value=p['eleccion'];row[7].value=p['valor_manual'];row[8].value=p['justificacion_manual']
    _guardar_con_vista(wb,destino)
    return tmp_path


def cambiar(root, clave, *, caso="Central", eleccion="Manual", valor=None, motivo="Prueba justificada"):
    p = root / LIBRO; wb = load_workbook(p); ws = wb["Escenarios"]
    for fila in range(7, ws.max_row + 1):
        if ws.cell(fila, 1).value == caso and ws.cell(fila, 13).value == clave:
            ws.cell(fila, 7, eleccion); ws.cell(fila, 8, valor); ws.cell(fila, 9, motivo)
            wb.save(p); return
    raise AssertionError(clave)


def datos(root, caso=None):
    return leer_parametros(root, caso=caso)


def test_base_y_variantes_conservan_la_referencia(proyecto):
    d = datos(proyecto); cfg = configuracion_actividad(d)
    assert cfg["cupo"]["coches_privados_dia"] == 500
    assert cfg["oferta_norte_elegida"]["subidas"] == 10
    ocupacion = next(r for r in d["parametros"] if r["id"] == "ocupacion_coche")
    assert ocupacion["propuesta"]["valor"] == 3.2
    assert ocupacion["valor_utilizado"] is None
    modal = next(r for r in d["parametros"] if r["id"] == "fraccion_captados_coche")
    assert modal["propuesta"]["valor"] == .7387
    assert modal["valor_utilizado"] is None
    guagua = next(r for r in d["parametros"] if r["id"] == "ocupacion_guagua_aforo")
    assert guagua["propuesta"]["valor"] == 35.99
    assert guagua["valor_utilizado"] is None
    assert configuracion_actividad(datos(proyecto, "Variante A"))["tendencia"]["metodo_central"] == "cagr_2019_2025"
    assert configuracion_actividad(datos(proyecto, "Variante B"))["tendencia"]["metodo_central"] == "cagr_2023_2025"


def test_manual_no_borra_propuesta_y_se_puede_volver(proyecto):
    cambiar(proyecto, "cupo_global", valor=600, motivo="Explorar otra política sin alterar el acuerdo de partida")
    r = next(r for r in datos(proyecto)["parametros"] if r["id"] == "cupo_global")
    assert r["propuesta"]["valor"] == 500 and r["valor_utilizado"] == 600
    assert "H034" in r["propuesta"]["fuente"]
    cambiar(proyecto, "cupo_global", eleccion="Propuesta", valor=600, motivo=r["eleccion"]["justificacion_manual"])
    r = next(r for r in datos(proyecto)["parametros"] if r["id"] == "cupo_global")
    assert r["valor_utilizado"] == 500 and r["eleccion"]["valor_manual"] == 600
    assert "Explorar" in r["eleccion"]["justificacion_manual"]


@pytest.mark.parametrize("valor,motivo", [(600, None), (600, " "), (None, "Falta completar"), ("=500+100", "No se evalúan fórmulas")])
def test_manual_incompleto_o_formula_se_rechaza(proyecto, valor, motivo):
    cambiar(proyecto, "cupo_global", valor=valor, motivo=motivo)
    with pytest.raises(ErrorParametros): datos(proyecto)


def test_cero_manual_es_distinto_de_pendiente(proyecto):
    cambiar(proyecto, "cupo_global", valor=0, motivo="Cierre a coches en una variante")
    assert configuracion_actividad(datos(proyecto))["cupo"]["coches_privados_dia"] == 0
    cambiar(proyecto, "cupo_global", eleccion="Pendiente", valor=0, motivo="Borrador")
    with pytest.raises(ErrorParametros, match="Falta elegir"): configuracion_actividad(datos(proyecto))


def test_herencia_y_sustitucion_por_caso(proyecto):
    cambiar(proyecto, "cupo_global", valor=600)
    assert configuracion_actividad(datos(proyecto, "Variante A"))["cupo"]["coches_privados_dia"] == 600
    cambiar(proyecto, "cupo_global", caso="Variante A", valor=400, motivo="Otro cupo de contraste")
    assert configuracion_actividad(datos(proyecto, "Variante A"))["cupo"]["coches_privados_dia"] == 400
    assert configuracion_actividad(datos(proyecto))["cupo"]["coches_privados_dia"] == 600


def test_no_autorreferencia_del_central(proyecto):
    cambiar(proyecto, "cupo_global", eleccion="Heredar central")
    with pytest.raises(ErrorParametros): datos(proyecto)


def test_reparto_manual_requiere_cuatro_pesos_y_cien_por_cien(proyecto):
    cambiar(proyecto, "reparto_cupo", valor="Porcentajes manuales")
    with pytest.raises(ErrorParametros, match="Falta elegir"): configuracion_actividad(datos(proyecto))
    for punto, peso in [("OROTAVA", .4), ("VILAFLOR", .3), ("LAGUNA", .2), ("CHIO", .1)]:
        cambiar(proyecto, f"cuota_{punto}", valor=peso)
    assert configuracion_actividad(datos(proyecto))["cupo"]["pesos_manuales"]["OROTAVA"] == .4
    cambiar(proyecto, "cuota_OROTAVA", valor=.5)
    with pytest.raises(ErrorParametros, match="100 %"): configuracion_actividad(datos(proyecto))


def test_porcentaje_no_se_confunde_con_numero_entero(proyecto):
    cambiar(proyecto, "cuota_OROTAVA", valor=40)
    with pytest.raises(ErrorParametros, match="límites"): datos(proyecto)


def test_calendario_manual_y_cero_justificado(proyecto):
    cambiar(proyecto, "calendario", valor="Número de días manual")
    with pytest.raises(ErrorParametros): configuracion_actividad(datos(proyecto))
    cambiar(proyecto, "dias_servicio", valor=0)
    assert configuracion_actividad(datos(proyecto))["lanzadera_acceso"]["dias_operacion_manual"] == 0


def test_tasas_manual_usa_valores_documentados_o_modificados(proyecto):
    cambiar(proyecto, "metodo_crecimiento", valor="Tasas manuales por acceso")
    cfg = configuracion_actividad(datos(proyecto))
    assert cfg["tendencia"]["tasas_manuales"]["OROTAVA"] == pytest.approx(0.019091099923966032)
    cambiar(proyecto, "tasa_OROTAVA", valor=-.01, motivo="Contraste con tráfico decreciente")
    assert configuracion_actividad(datos(proyecto))["tendencia"]["tasas_manuales"]["OROTAVA"] == -.01


def test_exclusion_vacia_tiene_eleccion_explicita(proyecto):
    cambiar(proyecto, "anios_excluidos", valor="Ninguno", motivo="Contraste que incluye todos los años")
    assert configuracion_actividad(datos(proyecto))["tendencia"]["anios_excluidos_periodo"] == []


def test_lectura_no_modifica_libro_y_no_se_regenera_encima(proyecto):
    p = proyecto / LIBRO; antes = sha256_archivo(p)
    datos(proyecto)
    assert sha256_archivo(p) == antes
    with pytest.raises(FileExistsError): crear_libro(proyecto)
    assert sha256_archivo(p) == antes


@pytest.mark.parametrize("componente", ["actividad_norte", "conciliacion_demanda"])
def test_archivo_preserva_valores_y_resultados_sin_duplicar_excel(proyecto, componente):
    salida = proyecto / "resultado.csv"; salida.write_text("resultado\n1\n")
    d = datos(proyecto); a = conservar_ejecucion(proyecto, d, componente, [salida])
    assert conservar_ejecucion(proyecto, d, componente, [salida]) == a
    cambiar(proyecto, "cupo_global", valor=600)
    salida.write_text("resultado\n2\n")
    b = conservar_ejecucion(proyecto, datos(proyecto), componente, [salida])
    assert a != b and (a / "resultado.csv").read_text() == "resultado\n1\n"
    assert json.loads((a / "parametros_resueltos.json").read_text())["sha256_libro"] == d["sha256_libro"]
    assert not (a / "parametros_modelo.xlsx").exists()
    assert not (b / "parametros_modelo.xlsx").exists()

    assert a.parent.name == componente


def test_no_archiva_si_cambian_entradas_en_mitad_del_calculo(proyecto):
    salida = proyecto / "resultado.csv"; salida.write_text("resultado\n1\n")
    d = datos(proyecto); cambiar(proyecto, "cupo_global", valor=600)
    with pytest.raises(ErrorParametros, match="ha cambiado"): conservar_ejecucion(proyecto, d, "actividad_norte", [salida])


def test_detecta_archivo_alterado(proyecto):
    salida = proyecto / "resultado.csv"; salida.write_text("resultado\n1\n")
    d = datos(proyecto); a = conservar_ejecucion(proyecto, d, "actividad_norte", [salida])
    (a / "resultado.csv").write_text("alterado")
    with pytest.raises(ErrorParametros, match="integridad"): conservar_ejecucion(proyecto, d, "actividad_norte", [salida])


def test_referencia_de_partida_no_se_modifica_silenciosamente(proyecto):
    p = proyecto / LIBRO; wb = load_workbook(p); ws = wb["Propuestas"]
    for row in range(7, ws.max_row + 1):
        if ws.cell(row, 8).value == "cupo_global": ws.cell(row, 4, 600)
    wb.save(p)
    with pytest.raises(ErrorParametros, match="referencia conservada"):
        datos(proyecto)


def test_vista_muestra_referencia_y_manual_sin_necesitar_recalculo(proyecto):
    from movilidad_teide.parametros import _guardar_con_vista
    p = proyecto / LIBRO
    cambiar(proyecto, "cupo_global", valor=600, motivo="Comparar con el límite original")
    antes = datos(proyecto)
    wb = load_workbook(p)
    _guardar_con_vista(wb, p)
    despues = datos(proyecto)
    assert despues["parametros"] == antes["parametros"]
    assert despues["elecciones_todos_los_casos"] == antes["elecciones_todos_los_casos"]
    vista = load_workbook(p, data_only=True)
    for caso in ("Central", "Variante A", "Variante B"):
        fila = next(f for f in range(7, wb["Escenarios"].max_row + 1)
                    if wb["Escenarios"].cell(f, 1).value == caso
                    and wb["Escenarios"].cell(f, 13).value == "cupo_global")
        assert vista["Escenarios"].cell(fila, 5).value == 500
        assert vista["Escenarios"].cell(fila, 10).value == 600
        assert "H034" in vista["Escenarios"].cell(fila, 11).value
        assert wb["Escenarios"].cell(fila, 10).data_type == "f"
    fila_res = next(f for f in range(7, vista["Resumen"].max_row + 1)
                    if vista["Resumen"].cell(f, 2).value == next(r["parametro"] for r in antes["parametros"] if r["id"] == "cupo_global"))
    assert vista["Resumen"].cell(fila_res, 4).value == 600
    assert vista["Resumen"].cell(fila_res, 6).value == "Comparar con el límite original"
    assert all(vista["Escenarios"].cell(f, 5).value is not None
               for f in range(7, vista["Escenarios"].max_row + 1))


def test_referencias_vinculadas_y_cache_con_cero_y_pendientes(proyecto):
    from movilidad_teide.parametros import _guardar_con_vista
    p = proyecto / LIBRO; wb = load_workbook(p)
    pr = {wb['Propuestas'].cell(f, 8).value: f for f in range(7, wb['Propuestas'].max_row + 1)}
    for f in range(7, wb['Escenarios'].max_row + 1):
        k = wb['Escenarios'].cell(f, 13).value
        for col, origen in [(5, 4), (6, 5), (11, 6)]:
            assert wb['Escenarios'].cell(f, col).data_type == 'f'
            assert f'Propuestas!{chr(64+origen)}{pr[k]}' in wb['Escenarios'].cell(f, col).value
    # En una copia de auditoría, un cambio en el origen debe actualizar las tres vistas.
    wb['Propuestas'].cell(pr['cupo_global'], 4, 0)
    _guardar_con_vista(wb, p)
    vista = load_workbook(p, data_only=True)
    for f in range(7, wb['Escenarios'].max_row + 1):
        if wb['Escenarios'].cell(f, 13).value == 'cupo_global':
            assert vista['Escenarios'].cell(f, 5).value == 0
            assert vista['Escenarios'].cell(f, 10).value == 0
    # Mostrar un cambio no equivale a autorizar una nueva referencia sin documentarla.
    with pytest.raises(ErrorParametros, match='referencia conservada'):
        datos(proyecto)


@pytest.mark.parametrize('nombre,celda,valor', [('Escenarios', 'E7', 2025), ('Escenarios', 'J7', 2025), ('Escenarios', 'F7', 'Otro fundamento'), ('Resumen', 'D7', 2025), ('Escenarios', 'N7', 'Central|otro')])
def test_vinculo_manipulado_no_diverge_silenciosamente_del_modelo(proyecto, nombre, celda, valor):
    p = proyecto / LIBRO; wb = load_workbook(p); wb[nombre][celda] = valor; wb.save(p)
    with pytest.raises(ErrorParametros, match='alterad'):
        datos(proyecto)


def test_interfaz_explica_y_protege_referencias_permite_editar_elecciones(proyecto):
    from movilidad_teide.parametros import MODOS
    wb = load_workbook(proyecto / LIBRO)
    assert wb.security.lockStructure
    assert wb['Inicio']['B5'].protection.locked is False
    assert wb['_Origen'].sheet_state == 'veryHidden'
    for f in range(7, wb['Escenarios'].max_row + 1):
        assert all(not wb['Escenarios'].cell(f, c).protection.locked for c in (7, 8, 9))
        assert all(wb['Escenarios'].cell(f, c).protection.locked for c in (5, 6, 10, 11, 15))
        assert wb['Escenarios'].cell(f, 8).comment
        dv = next(d for d in wb['Escenarios'].data_validations.dataValidation if f'G{f}' in d.sqref)
        assert ('Heredar central' in dv.formula1) == (wb['Escenarios'].cell(f, 1).value != 'Central')
        assert dv.errorStyle == 'stop'
    for hoja in ('Propuestas', 'Escenarios', 'Resumen'):
        assert wb[hoja].protection.sheet
        for row in wb[hoja].iter_rows(min_row=7):
            if hoja == 'Propuestas': assert all(c.protection.locked for c in row)
    assert wb['Escenarios'].tables['TablaEscenarios'].ref == f'A6:O{6 + 3 * len(catalogo())}'
    assert wb['Resumen'].tables['TablaResumen'].ref == f'A6:H{6 + len(catalogo())}'
    assert not wb._external_links


@pytest.mark.parametrize('valor,motivo', [(600, ''), (1.5, 'No es un número entero'), (-1, 'Fuera de rango'), ('=500+100', 'No se admiten fórmulas')])
def test_vista_advierte_manuales_invalidos(proyecto, valor, motivo):
    from movilidad_teide.parametros import _guardar_con_vista
    cambiar(proyecto, 'cupo_global', valor=valor, motivo=motivo)
    p = proyecto / LIBRO; wb = load_workbook(p); _guardar_con_vista(wb, p)
    vista = load_workbook(p, data_only=True)
    assert vista['Inicio']['B6'].value == 'REVISAR ELECCIONES'
    f = next(f for f in range(7, 163) if wb['Escenarios'].cell(f, 13).value == 'cupo_global')
    assert vista['Escenarios'].cell(f, 10).value == 'REVISAR'
    with pytest.raises(ErrorParametros): datos(proyecto)


@pytest.mark.parametrize('modo,dependencia,valor', [('reparto_cupo', 'Porcentajes manuales', None), ('calendario', 'Número de días manual', None)])
def test_vista_advierte_dependencias_pendientes(proyecto, modo, dependencia, valor):
    from movilidad_teide.parametros import _guardar_con_vista
    cambiar(proyecto, modo, valor=dependencia)
    p = proyecto / LIBRO; wb = load_workbook(p); _guardar_con_vista(wb, p)
    assert load_workbook(p, data_only=True)['Inicio']['B6'].value == 'REVISAR ELECCIONES'
    with pytest.raises(ErrorParametros): configuracion_actividad(datos(proyecto))


@pytest.mark.parametrize('valor', [',', '2020,2020', '1899', '2101', '2020,foo'])
def test_anios_ambiguos_no_se_convierten_en_lista_vacia(proyecto, valor):
    cambiar(proyecto, 'anios_excluidos', valor=valor)
    with pytest.raises(ErrorParametros): datos(proyecto)


def test_generacion_nueva_incluye_vinculos_y_avisos_sin_datos_externos(proyecto, monkeypatch):
    import movilidad_teide.configuracion.referencias as m
    wb = load_workbook(proyecto / LIBRO)
    plantilla = json.loads(wb['_Origen']['B2'].value)
    valores = {wb['Propuestas'].cell(f, 8).value: wb['Propuestas'].cell(f, 4).value for f in range(7, wb['Propuestas'].max_row + 1)}
    (proyecto / 'config/actividad_corredor_norte.json').write_text(json.dumps(plantilla))
    monkeypatch.setattr(m, '_referencias', lambda root: (plantilla, valores))
    nuevo = crear_libro(proyecto, proyecto / 'nuevo.xlsx')
    d = leer_parametros(proyecto, path=nuevo)
    assert all(p['valor_utilizado'] is None for p in d['parametros'] if p['id'] in {'ocupacion_coche','fraccion_captados_coche','ocupacion_guagua_aforo'})
    assert configuracion_actividad(d)['cupo']['coches_privados_dia'] == 500
    vista = load_workbook(nuevo, data_only=True)
    assert vista['Inicio']['B6'].value == 'ENTRADAS DE ACTIVIDAD COMPLETAS'
    assert all(vista['Escenarios'].cell(f, 5).value is not None for f in range(7, 163))


def test_valor_manual_guardado_invalido_tambien_se_advierte(proyecto):
    from movilidad_teide.parametros import _guardar_con_vista
    cambiar(proyecto, 'ocupacion_diseno', eleccion='Propuesta', valor=85)
    p = proyecto / LIBRO; wb = load_workbook(p); _guardar_con_vista(wb, p)
    assert load_workbook(p, data_only=True)['Inicio']['B6'].value == 'REVISAR ELECCIONES'
    with pytest.raises(ErrorParametros): datos(proyecto)


def test_caso_invalido_se_explica_en_el_libro(proyecto):
    from movilidad_teide.parametros import _guardar_con_vista
    p = proyecto / LIBRO; wb = load_workbook(p); wb['Inicio']['B5'] = 'Caso inexistente'
    _guardar_con_vista(wb, p)
    vista = load_workbook(p, data_only=True)
    assert vista['Inicio']['B6'].value == 'REVISAR CASO'
    assert vista['Resumen']['D7'].value == 'REVISAR CASO'
    with pytest.raises(ErrorParametros, match='Selecciona'): datos(proyecto)


@pytest.mark.parametrize('guardados', [1, 3])
def test_tablas_ooxml_coherentes_tras_guardados_repetidos(proyecto, guardados):
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    from openpyxl.utils.cell import range_boundaries
    from movilidad_teide.parametros import _guardar_con_vista
    p = proyecto / LIBRO
    antes = datos(proyecto)
    for _ in range(guardados):
        _guardar_con_vista(load_workbook(p), p)
    despues = datos(proyecto)
    assert antes['parametros'] == despues['parametros']
    assert antes['elecciones_todos_los_casos'] == despues['elecciones_todos_los_casos']
    # Comprobar el XML realmente guardado: leerlo con OpenPyXL no detectaba este fallo.
    with ZipFile(p) as paquete:
        for ruta in ['xl/tables/table1.xml', 'xl/tables/table2.xml', 'xl/tables/table3.xml']:
            tabla = ET.fromstring(paquete.read(ruta))
            x1, y1, x2, y2 = range_boundaries(tabla.get('ref'))
            columnas = tabla.find('{*}tableColumns')
            assert int(columnas.get('count')) == len(columnas) == x2 - x1 + 1
            assert [int(c.get('id')) for c in columnas] == list(range(1, len(columnas) + 1))
            assert len({c.get('name').casefold() for c in columnas}) == len(columnas)
            assert tabla.find('{*}autoFilter').get('ref') == tabla.get('ref')


@pytest.mark.parametrize('defecto', ['columna_extra', 'filtro_antiguo', 'cabecera_distinta'])
def test_lector_rechaza_tablas_internas_incoherentes(proyecto, defecto):
    from openpyxl.worksheet.table import TableColumn
    p = proyecto / LIBRO; wb = load_workbook(p)
    tabla = wb['Escenarios'].tables['TablaEscenarios']
    if defecto == 'columna_extra':
        tabla.tableColumns.append(TableColumn(id=16, name='Columna que no existe'))
    elif defecto == 'filtro_antiguo':
        tabla.autoFilter.ref = 'A6:N162'
    else:
        tabla.tableColumns[0].name = 'Encabezado distinto de la celda'
    wb.save(p)
    with pytest.raises(ErrorParametros, match='tabla incoherente'):
        datos(proyecto)


def test_detecta_parametros_archivados_alterados_en_registro_nuevo(proyecto):
    salida = proyecto / "resultado.csv"; salida.write_text("resultado\n1\n")
    d = datos(proyecto); carpeta = conservar_ejecucion(proyecto, d, "actividad_norte", [salida])
    (carpeta / "parametros_resueltos.json").write_text("{}")
    with pytest.raises(ErrorParametros, match="integridad"):
        conservar_ejecucion(proyecto, d, "actividad_norte", [salida])


def test_registro_historico_mantiene_control_integridad_del_excel(proyecto):
    salida = proyecto / "resultado.csv"; salida.write_text("resultado\n1\n")
    d = datos(proyecto); carpeta = conservar_ejecucion(proyecto, d, "actividad_norte", [salida])
    manifiesto = carpeta / "manifiesto.json"
    ficha = json.loads(manifiesto.read_text())
    ficha.pop("registro_entradas"); ficha.pop("sha256_parametros_resueltos")
    manifiesto.write_text(json.dumps(ficha))
    shutil.copy2(proyecto / LIBRO, carpeta / "parametros_modelo.xlsx")
    assert conservar_ejecucion(proyecto, d, "actividad_norte", [salida]) == carpeta
    (carpeta / "parametros_modelo.xlsx").write_text("alterado")
    with pytest.raises(ErrorParametros, match="integridad"):
        conservar_ejecucion(proyecto, d, "actividad_norte", [salida])


def test_tres_controles_de_masa_pendientes_en_estado_historico(proyecto,parametros_historicos):
    d=datos(proyecto);rows={r['id']:r for r in d['parametros']}
    for k in ['criterio_tara_turismos','masa_persona_turismo_kg','equipaje_turismo_kg_coche']:
        assert rows[k]['valor_utilizado'] is None
        historical=next(p for p in parametros_historicos['parametros'] if p['id']==k)
        assert 'Exploración excluida del balance principal' in historical['aplicacion']
        assert rows[k]['aplicacion'].startswith('Aplicado: ajuste anual condicionado')
    assert rows['masa_persona_turismo_kg']['propuesta']['valor']==75
    assert rows['equipaje_turismo_kg_coche']['propuesta']['valor'] is None
    assert rows['ocupacion_coche']['valor_utilizado'] is None
    cambiar(proyecto,'equipaje_turismo_kg_coche',valor=0,motivo='Caso sintético sin equipaje')
    assert next(x for x in datos(proyecto)['parametros'] if x['id']=='equipaje_turismo_kg_coche')['valor_utilizado']==0


def test_distancia_de_servicios_es_eleccion_explicita_sin_cambiar_referencias(proyecto):
    d=datos(proyecto);r=next(x for x in d['parametros'] if x['id']=='distancias_actividad_lanzaderas')
    assert r['valor_utilizado']=='Recorridos del estudio'
    assert next(x for x in d['parametros'] if x['id']=='km_interior')['propuesta']['valor']==29
    cambiar(proyecto,'distancias_actividad_lanzaderas',valor='Referencias de distancia del Excel',motivo='Contraste de referencia')
    r=next(x for x in datos(proyecto)['parametros'] if x['id']=='distancias_actividad_lanzaderas')
    assert r['valor_utilizado']=='Referencias de distancia del Excel'
    assert r['propuesta']['valor']=='Recorridos del estudio'


def test_cierre_y_margen_se_controlan_en_excel_sin_adoptar_estancia(proyecto):
    d=datos(proyecto);rows={x['id']:x for x in d['parametros']}
    assert rows['tratamiento_regresos']['valor_utilizado']=='Horario coordinado'
    assert rows['tratamiento_regresos']['propuesta']['valor']=='Refuerzos de regreso'
    assert rows['hora_limite_bajada_parque']['valor_utilizado']==18
    assert rows['margen_enlace_interior_min']['valor_utilizado']==10
    assert rows['estancia_min_visita_min']['valor_utilizado'] is None
    cambiar(proyecto,'tratamiento_regresos',valor='Horario inicial',motivo='Comparar oferta sin refuerzos')
    changed={x['id']:x for x in datos(proyecto,'Variante A')['parametros']}
    assert changed['tratamiento_regresos']['valor_utilizado']=='Horario inicial'
    assert changed['tratamiento_regresos']['propuesta']['valor']=='Refuerzos de regreso'


def test_maximo_y_separacion_estan_identificados_sin_perder_referencia(proyecto):
    rows={x['id']:x for x in datos(proyecto)['parametros']}
    assert rows['hora_limite_bajada_parque']['valor_utilizado']==18
    assert 'máxima' in rows['hora_limite_bajada_parque']['parametro']
    assert rows['intervalo_minimo_subidas_min']['valor_utilizado']==30
    assert rows['estancia_min_visita_min']['valor_utilizado'] is None
    assert rows['tratamiento_regresos']['propuesta']['valor']=='Refuerzos de regreso'


def test_tamanos_es_propuesta_vinculada_y_pendiente_conserva_la_referencia(proyecto):
    key='criterio_tamanos_turismos'
    cambiar(proyecto,key,eleccion='Pendiente')
    row=next(r for r in datos(proyecto)['parametros'] if r['id']==key)
    assert row['valor_utilizado'] is None
    assert row['propuesta']['valor']=='Tamaño propuesto; resto alternativas'
    assert 'F123' in row['propuesta']['fuente']
    cambiar(proyecto,key,eleccion='Propuesta')
    for caso in ['Central','Variante A','Variante B']:
        x=next(r for r in datos(proyecto,caso)['parametros'] if r['id']==key)
        assert x['valor_utilizado']=='Tamaño propuesto; resto alternativas'
    cambiar(proyecto,key,eleccion='Manual',valor='Todas las alternativas de tamaño',motivo='Contrastar sin aplicar las familias propuestas')
    x=next(r for r in datos(proyecto)['parametros'] if r['id']==key)
    assert x['valor_utilizado']=='Todas las alternativas de tamaño'
    assert x['propuesta']==row['propuesta']


@pytest.mark.parametrize('key,value',[
    ('criterio_categoria_incompleta_turismos','Contrastar tipo DGT si categoría vacía'),
    ('criterio_norma_incompleta_turismos','Contrastar normas consultadas si norma vacía')])
def test_incompletos_referencias_conservadas_y_elecciones_independientes(proyecto,key,value):
    cambiar(proyecto,key,eleccion='Pendiente')
    row=next(r for r in datos(proyecto)['parametros'] if r['id']==key)
    assert row['valor_utilizado'] is None and row['propuesta']['valor']==value
    cambiar(proyecto,key,eleccion='Propuesta')
    for caso in ['Central','Variante A','Variante B']:
        x=next(r for r in datos(proyecto,caso)['parametros'] if r['id']==key)
        assert x['valor_utilizado']==value
    cambiar(proyecto,key,eleccion='Manual',valor='Conservar pendientes',motivo='Mantener separado el contraste de registros incompletos')
    x=next(r for r in datos(proyecto)['parametros'] if r['id']==key)
    assert x['valor_utilizado']=='Conservar pendientes' and x['propuesta']==row['propuesta']


@pytest.mark.parametrize('key,value',[
    ('velocidad_turismo_local',20),('velocidad_turismo_convencional',40),('velocidad_turismo_rapida',80)])
def test_velocidades_turismos_son_propuestas_explicitas_pendientes(proyecto,key,value):
    row=next(r for r in datos(proyecto)['parametros'] if r['id']==key)
    assert row['valor_utilizado'] is None and row['propuesta']['valor']==value
    assert 'no datos observados' in row['propuesta']['fuente']
    cambiar(proyecto,key,eleccion='Propuesta')
    assert next(r for r in datos(proyecto,'Variante A')['parametros'] if r['id']==key)['valor_utilizado']==value


def test_referencia_principal_elige_sin_perder_propuestas(parametros_historicos):
    root=Path(__file__).resolve().parents[1]
    # Contrato D183/D184 sellado; las elecciones posteriores se prueban aparte.
    actual=json.loads((root/'tests/fixtures/parametros_contrato_comunes.json').read_text())['parametros']
    old={p['id']:p for p in parametros_historicos['parametros']}
    now={p['id']:p for p in actual['parametros']}
    assert {k:now[k]['propuesta'] for k in old}=={k:p['propuesta'] for k,p in old.items()}
    assert set(now)-set(old)=={'criterio_guaguas_comunes','consumo_comun_complementario_mwh_anio'}
    for key,value in [('ocupacion_coche',3.2),('transferencia_lanzadera',1),('induccion',0),('fraccion_visita_primera_zona',1),('fraccion_visita_segunda_zona',0)]:
        assert now[key]['valor_utilizado']==value and 'D183/H121' in now[key]['justificacion_utilizada']
    assert now['fraccion_captados_coche']['propuesta']['valor']==.7387
    assert now['fraccion_captados_coche']['valor_utilizado']==pytest.approx(.7631452813921072)
