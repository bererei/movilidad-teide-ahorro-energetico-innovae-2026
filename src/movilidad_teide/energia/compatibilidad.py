"""energia: compatibilidad. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations


def verificar_reutilizacion_hot(anterior,actual):
    """Permitir reutilización solo con iguales entradas, salvo el alcance Hot.

    Se conservan la huella histórica y la actual: no se reetiqueta una ejecución
    anterior como si hubiera usado el nuevo libro. Cualquier otro cambio exige
    regenerar los productores afectados.
    """
    scope='alcance_consumo_anual';value='Solo consumo en caliente (Hot EC)'
    old={p['id']:p for p in anterior['parametros']}
    new={p['id']:p for p in actual['parametros']}
    if len(old)!=len(anterior['parametros']) or len(new)!=len(actual['parametros']):
        raise ValueError('Parámetros repetidos en la trazabilidad.')
    if (anterior['caso']!=actual['caso'] or anterior['plantilla_tecnica']!=actual['plantilla_tecnica']
            or scope not in new or new[scope]['valor_utilizado']!=value
            or set(old)-{scope}!=set(new)-{scope}):
        raise ValueError('Las ejecuciones no son compatibles para la comparación Hot.')
    for key in set(new)-{scope}:
        if old[key]!=new[key]:
            raise ValueError('Ha cambiado otra entrada; regenerar productores: '+key)
    if scope in old and old[scope]['valor_utilizado']!=value:
        raise ValueError('El productor no pertenece al alcance Hot.')
    choices=lambda p:[x for x in p['elecciones_todos_los_casos'] if x['id']!=scope]
    if choices(anterior)!=choices(actual):
        raise ValueError('Hay elecciones de otros casos modificadas.')
    return {'reutilizacion_verificada':True,'sha256_libro_productor':anterior['sha256_libro'],
        'sha256_libro_comparacion':actual['sha256_libro'],'parametros_previos_identicos':len(new)-1,
        'unico_parametro_nuevo_permitido':scope}

def verificar_reutilizacion_sin_cocheras(anterior, actual):
    """Reutilizar productores que no calcularon cocheras, con trazabilidad.

    Solo se proyecta la NUEVA elección de estacionamiento si el productor no la
    conocía. Se comparan íntegramente sus otras entradas/elecciones y se conserva
    su huella histórica. Un criterio ya presente tampoco puede cambiarse.
    """
    key = 'ubicacion_cocheras_lanzaderas'
    value = 'Cabeceras de acceso y extremos del interior'
    old_ids = [p['id'] for p in anterior['parametros']]
    new_ids = [p['id'] for p in actual['parametros']]
    if len(set(old_ids)) != len(old_ids) or len(set(new_ids)) != len(new_ids):
        raise ValueError('Parámetros repetidos en la reutilización.')
    chosen = [p for p in actual['parametros'] if p['id'] == key]
    if len(chosen) != 1 or chosen[0]['valor_utilizado'] != value:
        raise ValueError('Falta la hipótesis explícita de cocheras en extremos.')
    projected = dict(actual)
    introduced = key not in old_ids
    if introduced:
        projected['parametros'] = [p for p in actual['parametros'] if p['id'] != key]
        projected['elecciones_todos_los_casos'] = [p for p in actual['elecciones_todos_los_casos'] if p['id'] != key]
    check = verificar_reutilizacion_hot(anterior, projected)
    return check | {'criterio_cocheras_nuevo_no_usado_por_productor': key if introduced else None,
        'criterio_cocheras': value, 'productor_reetiquetado': False,
        'alcance_reutilizado': 'Solo contribuciones anteriores sin cocheras; el criterio nuevo se aplica aparte'}

def verificar_reutilizacion_sensibilidad(anterior, actual):
    """Proyectar solo el nuevo control externo no usado por productores previos."""
    key = 'perdida_rendimiento_guaguas_contraste'
    old_ids = [p['id'] for p in anterior['parametros']]
    new_ids = [p['id'] for p in actual['parametros']]
    if len(set(old_ids)) != len(old_ids) or len(set(new_ids)) != len(new_ids) or key not in new_ids:
        raise ValueError('Control de sensibilidad ausente o parámetros repetidos.')
    projected = dict(actual)
    introduced = key not in old_ids
    if introduced:
        projected['parametros'] = [p for p in actual['parametros'] if p['id'] != key]
        projected['elecciones_todos_los_casos'] = [p for p in actual['elecciones_todos_los_casos'] if p['id'] != key]
    check = verificar_reutilizacion_sin_cocheras(anterior, projected)
    return check | {'control_nuevo_no_usado_por_productor': key if introduced else None,
        'alcance_sensibilidad': 'Recargo externo y dominio de cuotas calculados aparte; no alterar contribuciones previas'}

def verificar_representacion_tecnica(anterior, actual):
    """Permitir solo activar cuatro criterios previos idénticos a sus propuestas.

    No se reutiliza una elección antigua bajo una nueva huella: se mantienen
    ambas y se documenta la activación. Los factores elegidos se regeneran aparte.
    """
    from copy import deepcopy
    expected={
        'criterio_pesos_turismos':'Igual kilometraje medio dentro de cada servicio',
        'criterio_tamanos_turismos':'Tamaño propuesto; resto alternativas',
        'criterio_categoria_incompleta_turismos':'Contrastar tipo DGT si categoría vacía',
        'criterio_norma_incompleta_turismos':'Contrastar normas consultadas si norma vacía'}
    old={p['id']:p for p in anterior['parametros']};new={p['id']:p for p in actual['parametros']}
    if len(old)!=len(anterior['parametros']) or len(new)!=len(actual['parametros']):
        raise ValueError('Parámetros repetidos.')
    projected=deepcopy(actual);activated=[]
    for key,value in expected.items():
        if key not in old or key not in new or new[key]['valor_utilizado']!=value:
            raise ValueError('Representación técnica incompleta o distinta de la propuesta comprobada.')
        if old[key]['valor_utilizado'] is None:
            if old[key]['propuesta']!=new[key]['propuesta'] or old[key]['propuesta']['valor']!=value:
                raise ValueError('No se conserva la propuesta técnica anterior.')
            fixed=['id','grupo','parametro','unidad','aplicacion']
            if any(old[key][k]!=new[key][k] for k in fixed):raise ValueError('Ha cambiado el significado del criterio.')
            if new[key]['eleccion']['eleccion']!='Manual' or not str(new[key]['eleccion']['justificacion_manual'] or '').strip():
                raise ValueError('La activación necesita elección Manual y justificación.')
            projected['parametros']=[deepcopy(old[key]) if p['id']==key else p for p in projected['parametros']]
            activated.append(key)
    old_choices={(p['caso'],p['id']):p for p in anterior['elecciones_todos_los_casos']}
    for i,p in enumerate(projected['elecciones_todos_los_casos']):
        if p['id'] in activated:
            before=old_choices.get((p['caso'],p['id']))
            if before is None:raise ValueError('Falta elección histórica del criterio.')
            if p['caso']=='Central':
                if (p['eleccion']!='Manual' or p['valor_manual']!=expected[p['id']]
                        or not str(p['justificacion_manual'] or '').strip()):
                    raise ValueError('Elección central no documentada.')
                if any(p[k]!=before[k] for k in p if k not in {'eleccion','valor_manual','justificacion_manual'}):
                    raise ValueError('Cambio ajeno a la activación técnica.')
                projected['elecciones_todos_los_casos'][i]=deepcopy(before)
            elif p!=before:raise ValueError('No se permite cambiar otra variante al activar el criterio.')
    check=verificar_reutilizacion_sensibilidad(anterior,projected)
    return check|{'criterios_activados_desde_propuesta':activated,
        'factores_elegidos_regenerados_por_separado':True,'criterios_numericos_distintos_de_los_ensayados':False}
