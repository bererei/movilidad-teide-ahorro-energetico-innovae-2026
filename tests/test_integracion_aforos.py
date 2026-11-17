"""Regresión de los formatos recibidos: lectores del propio notebook, sin Bronze."""
import ast
import csv
import json
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def lector():
    # Pruebo los mismos lectores, ahora importados desde su módulo compartido.
    from movilidad_teide.fuentes.aforos import leer_filas_aforo, leer_csv_aforos, normalizar_horas_aforo
    return {'leer_filas_aforo': leer_filas_aforo, 'leer_csv_aforos': leer_csv_aforos,
            'normalizar_horas_aforo': normalizar_horas_aforo}


@pytest.mark.parametrize('separador,anio,hora', [(',', 'anio', '00:00:00'), (';', 'year', '0:00')])
def test_csv_recibidos_conservan_valores_y_procedencia(tmp_path, lector, separador, anio, hora):
    path = tmp_path / 'aforos.csv'
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter=separador)
        w.writerow(['PUNTO','Fecha','dia','mes',anio,'Hora','Ecoches','Eguaguas','Scoches','Sguaguas','',''])
        w.writerow(['OROTAVA','29/02/2024',29,2,2024,hora,7,0,-1,3,'',''])
    tabla, control = lector['leer_csv_aforos'](path)
    assert control['separador_csv'] == separador
    assert control['alias_columnas'] == ({'year': 'anio'} if anio == 'year' else {})
    fila = tabla.iloc[0]
    assert fila['anio'] == '2024' and fila['fila_origen'] == 2 and fila['hoja_origen'] == 'CSV'
    assert fila['ecoches'] == '7' and fila['sguaguas'] == '3' and fila['scoches'] == '-1'
    fecha = pd.to_datetime(tabla['fecha'], dayfirst=True) + lector['normalizar_horas_aforo'](tabla['hora'])
    assert fecha.iloc[0] == pd.Timestamp('2024-02-29 00:00:00')


@pytest.mark.parametrize('hora', ['0:00','01:00','23:00:00'])
def test_horas_con_o_sin_segundos_representan_el_mismo_intervalo(lector, hora):
    assert lector['normalizar_horas_aforo'](pd.Series([hora])).iloc[0] == pd.Timedelta(hours=int(hora.split(':')[0]))


@pytest.mark.parametrize('hora', ['24:00','12:30','-01:00:00'])
def test_no_se_aceptan_horas_exteriores_o_intervalos_no_horarios(lector, hora):
    with pytest.raises((AssertionError, ValueError)):
        lector['normalizar_horas_aforo'](pd.Series([hora]))


def test_alias_no_oculta_dos_columnas_de_anio(lector, tmp_path):
    filas = [['punto','fecha','hora','year','anio','ecoches','eguaguas','scoches','sguaguas']]
    with pytest.raises(AssertionError, match='Columnas repetidas'):
        lector['leer_filas_aforo'](tmp_path/'duplicado.csv','CSV',filas)
