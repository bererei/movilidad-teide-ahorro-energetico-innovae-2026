"""Comprobar las cadenas documentales de la referencia, sin escribir resultados."""
from pathlib import Path
import argparse
import ast
import csv
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from movilidad_teide.publicacion.nucleo import verificar
from movilidad_teide.publicacion.reserva import leer_politica,catalogo_completo


def comprobar(root):
    root = Path(root).resolve()
    integrity = verificar(root)
    politica = leer_politica(root)
    documentos_omitidos = 0

    def rows(name):
        with (root / 'manifiestos' / name).open(encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f, delimiter=';'))

    annex = rows('trazabilidad_anexos.csv')
    columns = rows('trazabilidad_columnas.csv')
    resources = rows('trazabilidad_recursos.csv')
    products = rows('trazabilidad_resultados.csv')
    fichas = rows('trazabilidad_fichas.csv')
    stages = rows('trazabilidad_etapas.csv')
    if len(rows('fuentes_bibliograficas.csv')) != 22 or len(rows('trazabilidad_hipotesis.csv')) != 31:
        raise ValueError('Bibliografía o hipótesis sin correspondencia con la entrega.')
    if [len(x) for x in [annex, columns, resources, products, fichas, stages]] != [33, 392, 63, 16, 8, 12]:
        raise ValueError('La cobertura documental no corresponde a la edición vigente.')

    names = {x['Etapa'] for x in stages}
    for frame in [annex, products, resources]:
        for row in frame:
            if not set(row['Etapas'].split(' | ')) <= names:
                raise ValueError('Etapa sin definición en la trazabilidad.')
    index = json.loads((root / 'config/referencia_ordenacion_2028.json').read_text())
    if {x['Producto'] for x in products} != set(index['productos_actualizados'].values()):
        raise ValueError('Los productos documentados no coinciden con el índice del cálculo.')
    if len(index['parametros_de_la_referencia']) != 31:
        raise ValueError('La referencia no conserva sus 31 condiciones efectivas.')

    pairs = {(x['Archivo'], x['Columna']) for x in columns}
    if len(pairs) != 392:
        raise ValueError('Columna duplicada o sin documentar.')
    for a in annex:
        path = root / a['Anexo']
        if politica.excluye(a['Anexo']):
            documentos_omitidos += 1
            continue
        with path.open(encoding='utf-8-sig', newline='') as f:
            header = next(csv.reader(f, delimiter=';'))
        if set(header) != {col for name, col in pairs if name == path.name}:
            raise ValueError('Diccionario y cabecera diferentes: ' + str(path))

    for kind, maximum in [('Tabla', 43), ('Figura', 20)]:
        subset = [x for x in resources if x['Tipo'] == kind]
        if sorted(int(x['Número']) for x in subset) != list(range(1, maximum + 1)):
            raise ValueError('Numeración incompleta o duplicada de ' + kind)
    main = '' if politica.reservada else (root / 'docs/informe_energetico/main.tex').read_text()
    for row in resources:
        p = root / row['Recurso']
        if politica.excluye(row['Recurso']):
            documentos_omitidos += 1
            continue
        if not p.is_file():
            raise ValueError('Recurso ausente: ' + str(p))
        text = main if row['Tipo'] == 'Figura' else p.read_text()
        if row['Etiqueta'] not in text:
            raise ValueError('Etiqueta documental ausente: ' + row['Etiqueta'])

    symbols = set()
    for frame in [annex, products, resources, fichas, stages]:
        for row in frame:
            for text in row.values():
                symbols.update(re.findall(r'(src/[^\s|;]+\.py):(\d+)::(\w+)', text))
    for module, line, function in symbols:
        definitions = [n for n in ast.walk(ast.parse((root / module).read_text()))
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                       and n.name == function and n.lineno == int(line)]
        if len(definitions) != 1:
            raise ValueError('Función o localización cambiada: ' + module + '::' + function)

    inventory = catalogo_completo(json.loads((root / 'manifiestos/archivos.json').read_text()))
    for row in rows('trazabilidad_archivos.csv'):
        nombre = row['Ruta']
        p = root / nombre
        miembros = [n for n in inventory if n.startswith(nombre + '/')]
        members = miembros if miembros else [nombre]
        if len(members) != int(row['Archivos identificados']) or not all(n in inventory for n in members):
            raise ValueError('Conjunto sin correspondencia con el inventario: ' + nombre)
        if not p.exists() and not (politica.excluye(nombre) or all(politica.excluye(n) for n in members)):
            raise ValueError('Entrada de trazabilidad ausente: ' + nombre)

    return {**integrity, 'trazabilidad_documental_verificada': not politica.reservada,
            'trazabilidad_del_calculo_verificada': True,
            'recursos_documentales_no_exigidos_por_reserva': documentos_omitidos,
            'alcance_documental': 'Catálogo y código comprobados; documentos reservados sin cotejo de sus bytes.' if politica.reservada else 'Documentos, catálogo y código comprobados.',
            'productos_anuales': 16, 'anexos': 33, 'columnas': 392,
            'tablas': 43, 'figuras': 20, 'fichas': 8,
            'funciones_localizadas': len(symbols),
            'hipotesis_localizadas_en_excel': 31, 'referencias_bibliograficas': 22,
            'informe_modificado': False,
            'regeneracion_integral_desde_bruto_certificada': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(comprobar(args.root), ensure_ascii=False, indent=2))
