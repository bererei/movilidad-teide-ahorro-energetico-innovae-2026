"""Interfaz compatible; las responsabilidades se organizan en configuracion."""

from movilidad_teide.configuracion.catalogo import _firma_referencias, _valor, catalogo

from movilidad_teide.configuracion.ejecuciones import conservar_ejecucion

from movilidad_teide.configuracion.excel import _cabecera, _cache_vista, _comprobar_tablas, _comprobar_vinculos, _formulas_vista, _guardar_con_vista, _manual_valido_excel, _mapa_filas, _preparar_interfaz, crear_libro

from movilidad_teide.configuracion.lectura import configuracion_actividad, leer_parametros

from movilidad_teide.configuracion.parametros_tipos import ACCESOS, AZUL, CASOS, Campo, ErrorParametros, FONDO, JADE, LIBRO, METODOS, MODOS, NARANJA, TEXTO

from movilidad_teide.configuracion.referencias import _fundamento, _referencias

from movilidad_teide.trazabilidad import sha256_archivo

__all__ = ['ACCESOS', 'AZUL', 'CASOS', 'Campo', 'ErrorParametros', 'FONDO', 'JADE', 'LIBRO', 'METODOS', 'MODOS', 'NARANJA', 'TEXTO', 'catalogo', 'configuracion_actividad', 'conservar_ejecucion', 'crear_libro', 'leer_parametros', 'sha256_archivo']
