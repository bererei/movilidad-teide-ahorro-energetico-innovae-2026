"""Identidad documental y empaquetado estable; no contiene hipótesis del modelo."""
from pathlib import Path
import re,zipfile

VERSION='0.28'
FECHA='2026-11-16'
REPOSITORIO='https://github.com/bererei/movilidad-teide-ahorro-energetico-innovae-2026'
ANEXOS='data/gold/anexos'
PAQUETE='ANEXOS_ENERGETICOS_2028_v0.28.zip'
REGISTRO='data/silver/ejecuciones/referencia_2028_final_20261116'


def escribir_zip(destino,archivos):
    """Conservar rutas Medallion y evitar fechas variables en el contenedor."""
    with zipfile.ZipFile(destino,'w',zipfile.ZIP_DEFLATED) as archivo:
        for nombre,contenido in sorted(archivos.items()):
            ficha=zipfile.ZipInfo(nombre,date_time=(1980,1,1,0,0,0))
            ficha.compress_type=zipfile.ZIP_DEFLATED;ficha.create_system=3;ficha.external_attr=0o100644<<16
            archivo.writestr(ficha,contenido)


def normalizar_libro(path):
    """Fijar solo metadatos de creación/modificación; conservar datos y fórmulas."""
    path=Path(path)
    with zipfile.ZipFile(path) as libro:archivos={n:libro.read(n) for n in libro.namelist()}
    core=archivos['docProps/core.xml'].decode()
    for etiqueta in ['created','modified']:
        core=re.sub(r'(<dcterms:'+etiqueta+r'[^>]*>)[^<]+',lambda m:m.group(1)+FECHA+'T00:00:00Z',core)
    archivos['docProps/core.xml']=core.encode();escribir_zip(path,archivos)
