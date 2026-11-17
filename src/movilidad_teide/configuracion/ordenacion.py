"""Referencia vigente en el mismo libro, con elecciones históricas intactas."""
from pathlib import Path
import math
from .parametros_tipos import ErrorParametros, LIBRO
from movilidad_teide.trazabilidad import sha256_archivo

TABLA = 'TablaOrdenacionVigente'
INDICE = 'config/referencia_ordenacion_2028.json'
POLITICA = 'Cupo desde 650; priorizar dotación propia'




def leer_ordenacion(root):
    """Conservar la interfaz anterior utilizando la lectura común vigente."""
    from .estudio import leer_configuracion
    datos = leer_configuracion(root)
    return {k: v for k, v in datos.items() if k != 'procedencia_parametros'}


def verificar_entradas(root, referencia):
    """Rechazar una entrada distinta o ausente, con rutas relativas portables."""
    root = Path(root).resolve()
    for name, expected in referencia['indice']['entradas_sha256'].items():
        p = Path(name)
        if p.is_absolute() or '..' in p.parts:
            raise ErrorParametros('El índice contiene una ruta no portable.')
        if not (root / p).is_file() or sha256_archivo(root / p) != expected:
            raise ErrorParametros(f'Entrada de referencia ausente o modificada: {name}')
    return dict(referencia['indice']['entradas_sha256'])


def _resolver_ordenacion(root, base, wb, index, huella_indice):
    """Resolver las condiciones vigentes desde la misma apertura del Excel."""
    ws = wb['Inicio']
    if TABLA not in ws.tables:
        raise ErrorParametros('Falta la tabla de ordenación vigente en Inicio del libro.')
    table = ws.tables[TABLA]
    data = list(ws[table.ref])
    if [c.value for c in data[0]] != ['Id', 'Grupo', 'Parámetro', 'Valor efectivo', 'Unidad', 'Motivo', 'Estado', 'Origen']:
        raise ErrorParametros('Cabeceras de ordenación alteradas.')
    definitions = index['parametros_de_la_referencia']
    values, choices, procedencia = {}, [], []
    for row in data[1:]:
        key, group, name, value, unit, reason, state, source = [c.value for c in row]
        if key not in definitions or key in values:
            raise ErrorParametros('Parámetro de ordenación desconocido o repetido.')
        expected = definitions[key]
        if (group, name, unit) != (expected['grupo'], expected['nombre'], expected['unidad']):
            raise ErrorParametros(f'{key}: significado o unidad alterados.')
        if not isinstance(reason, str) or not reason.strip() or reason.startswith('='):
            raise ErrorParametros(f'{key}: falta el motivo de la elección efectiva.')
        if state != 'Elegido para el estudio' or not isinstance(source, str) or not source.strip():
            raise ErrorParametros(f'{key}: estado o procedencia incompletos.')
        if isinstance(value, bool) or value is None or isinstance(value, str) and value.startswith('='):
            raise ErrorParametros(f'{key}: valor efectivo inválido.')
        if isinstance(value, (float, int)) and not math.isfinite(value):
            raise ErrorParametros(f'{key}: valor no finito.')
        if type(value) not in (str, int, float) or value != expected['valor_sellado']:
            raise ErrorParametros(f'{key}: el valor difiere de las circulaciones conservadas; reconstruye y documenta la referencia antes de reproducirla.')
        values[key] = value
        choices.append(dict(id=key, valor=value, unidad=unit, motivo=reason, estado=state, origen=source))
        procedencia.append(dict(id=key, grupo=group, nombre=name, valor=value, unidad=unit, motivo=reason, estado=state, origen=source, celda=f'{ws.title}!{row[3].coordinate}'))
    if set(values) != set(definitions):
        raise ErrorParametros('Faltan parámetros de la ordenación vigente.')
    # La referencia incorpora exactamente el contenido base usado en la captura;
    # una modificación de una elección, incluso inactiva, requiere otra edición.
    content = {k: v for k, v in base.items() if k != 'sha256_libro'}
    if content != index['parametros_base_conservados']:
        raise ErrorParametros('Las elecciones históricas del libro difieren de las entradas de esta referencia.')
    effective = {p['id']: p['valor_utilizado'] for p in base['parametros']}
    for key in ['captacion_extranjero', 'captacion_nacional', 'captacion_local', 'captacion_frecuente', 'hora_inicio_acceso', 'ocupacion_coche', 'ocupacion_guagua_aforo']:
        effective[key] = values[key]
    effective['cupo_global'] = values['cupo_ordinario']
    if sha256_archivo(root / LIBRO) != base['sha256_libro']:
        raise ErrorParametros('El libro cambió durante la lectura.')
    return {'indice': index, 'valores': values, 'valores_modelo': effective,
            'elecciones_vigentes': choices, 'base': base, 'raiz': root,
            'sha256_indice': huella_indice, 'procedencia_parametros': procedencia}
