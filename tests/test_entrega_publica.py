"""Integridad del núcleo directo y rechazo de alteraciones o destinos indebidos."""
from pathlib import Path
import hashlib,json
import pytest
from movilidad_teide.publicacion.nucleo import verificar,copiar_nucleo

@pytest.fixture
def entrega(tmp_path):
    root=tmp_path/'entrega';f=root/'data/gold/dato.csv';f.parent.mkdir(parents=True);f.write_text('visitas;2500000\n')
    m=root/'manifiestos/archivos.json';m.parent.mkdir();m.write_text(json.dumps({'archivos':[{'ruta':'data/gold/dato.csv','bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}]}));return root,f

def test_verifica_las_rutas_directas(entrega):
    assert verificar(entrega[0])['materializacion_de_rutas_anteriores'] is False

def test_archivo_ausente_indica_recuperacion(entrega):
    root,f=entrega;f.rename(f.with_suffix('.ausente'))
    with pytest.raises(ValueError,match='extraer'):verificar(root)

def test_archivo_alterado_no_se_acepta(entrega):
    root,f=entrega;f.write_text('alterado')
    with pytest.raises(ValueError,match='modificado'):verificar(root)

def test_copia_independiente_no_crea_puentes(entrega,tmp_path):
    root,f=entrega;copy=copiar_nucleo(root,tmp_path/'copia');assert (copy/'data/gold/dato.csv').read_bytes()==f.read_bytes();assert not (copy/'manifiestos/rutas_calculo.json').exists()

def test_destinos_solapados_o_existentes_se_rechazan(entrega,tmp_path):
    root,_=entrega
    with pytest.raises(ValueError):copiar_nucleo(root,root/'copia')
    out=tmp_path/'existente';out.mkdir();(out/'dato').write_text('conservar')
    with pytest.raises(FileExistsError):copiar_nucleo(root,out)
