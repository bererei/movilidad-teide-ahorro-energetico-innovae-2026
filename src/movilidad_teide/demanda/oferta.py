"""Actividad comercial y reposición de las lanzaderas de acceso."""
import math
import numpy as np
import pandas as pd
from movilidad_teide.validacion import numero_actividad as _numero

def calcular_oferta_acceso(km_sentido, subidas_dia, bajadas_dia, reposiciones_equivalentes_dia, dias_operacion=None):
    """Separar kilómetros comerciales, reposición y actividad anual si hay calendario.

    La reposición equivalente publicada no identifica dirección ni cubre cocheras.
    Un calendario ausente produce actividad anual ausente, nunca cero.
    """
    distancia = _numero(km_sentido, 'km_sentido', positivo=True)
    subidas = _numero(subidas_dia, 'subidas_dia')
    bajadas = _numero(bajadas_dia, 'bajadas_dia')
    reposiciones = _numero(reposiciones_equivalentes_dia, 'reposiciones_equivalentes_dia')
    if subidas != int(subidas) or bajadas != int(bajadas):
        raise ValueError('Las expediciones comerciales deben ser enteras.')
    dias = None if dias_operacion is None else _numero(dias_operacion, 'dias_operacion')
    if dias is not None and (dias != int(dias) or dias > 366):
        raise ValueError('Los días de operación deben ser enteros entre 0 y 366.')
    filas = []
    for (componente, sentido, recorridos) in [('comercial', 'subida', subidas), ('comercial', 'bajada', bajadas), ('reposicion_equivalente', 'sin_desglose', reposiciones)]:
        filas.append({'componente': componente, 'sentido': sentido, 'recorridos_dia': recorridos, 'km_por_recorrido': distancia, 'vehiculo_km_dia': recorridos * distancia, 'dias_operacion': dias, 'recorridos_anio': None if dias is None else recorridos * dias, 'vehiculo_km_anio': None if dias is None else recorridos * distancia * dias})
    return pd.DataFrame(filas)
