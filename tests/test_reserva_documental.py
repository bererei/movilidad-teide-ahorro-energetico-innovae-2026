"""Reserva documental, protección de datos y paquetes con el único control Git."""
from pathlib import Path
import hashlib,json,zipfile
import pytest
from movilidad_teide.publicacion.reserva import INICIO,FIN,PATRONES,leer_politica,proyectar
from movilidad_teide.publicacion.nucleo import verificar,copiar_nucleo
from movilidad_teide.publicacion.empaquetado import empaquetar


def politica(activa=True):
    return '# Datos por release\ndata/\n'+INICIO+'\n'+'\n'.join(PATRONES if activa else ['# '+p for p in PATRONES])+'\n'+FIN+'\n'


def write(p,s):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s);return p


@pytest.fixture
def proyecto(tmp_path):
    r=tmp_path/'original';write(r/'.gitignore',politica())
    files={'.gitignore':politica(),'src/calculo.py':'resultado=2500000\n','data/bronze/fuente.csv':'visitas;2500000\n',
           'data/silver/referencia.csv':'energia;12\n','data/gold/referencia_anual/resultado.csv':'ahorro;403.1\n',
           'docs/informe_energetico/main.tex':'DOCUMENTO_RESERVADO_LATEX',
           'docs/informe_energetico/informe.pdf':'DOCUMENTO_RESERVADO_PDF',
           'data/gold/anexos/balance_anual.csv':'ANEXO_DOCUMENTAL_RESERVADO',
           'data/gold/ANEXOS_ENERGETICOS_2028_v0.27.zip':'ZIP_DOCUMENTAL_RESERVADO',
           'data/silver/ejecuciones/recursos_prueba/compilacion/main.pdf':'COPIA_RESERVADA_EN_SILVER'}
    rows=[]
    for n,s in files.items():
        p=write(r/n,s);rows.append(dict(ruta=n,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    m={'archivos':rows,'visitas_sin_y_con':2500000,'informe':'v0.27',
       'gitignore_editable':{'sha256_fuera_del_bloque':leer_politica(r).sha256_base}}
    write(r/'manifiestos/archivos.json',json.dumps(m));return r


def test_reglas_completas_o_comentadas(tmp_path):
    write(tmp_path/'.gitignore',politica());p=leer_politica(tmp_path);assert p.reservada
    assert p.excluye('docs/informe_energetico/main.tex') and p.excluye('data/silver/ejecuciones/recursos_nuevo/main.tex')
    for n in ['data/gold/referencia_anual/resultado.csv','data/bronze/origen.pdf','src/calculo.py']:
        assert not p.excluye(n)
    write(tmp_path/'.gitignore',politica(False));assert not leer_politica(tmp_path).reservada


@pytest.mark.parametrize('reglas',[['/data/'],list(PATRONES[:3]),list(PATRONES)+[PATRONES[0]]])
def test_no_se_pueden_ocultar_datos_o_activar_reserva_parcial(tmp_path,reglas):
    write(tmp_path/'.gitignore',INICIO+'\n'+'\n'.join(reglas)+'\n'+FIN)
    with pytest.raises(ValueError,match='cuatro reglas'):leer_politica(tmp_path)


@pytest.mark.parametrize('texto',[INICIO+'\n'+PATRONES[0],FIN,INICIO+'\n'+FIN+'\n'+INICIO+'\n'+FIN])
def test_marcadores_incompletos_se_rechazan(tmp_path,texto):
    write(tmp_path/'.gitignore',texto)
    with pytest.raises(ValueError,match='incompleto o repetido'):leer_politica(tmp_path)


def test_seleccion_publica_no_contiene_documentos(proyecto,tmp_path):
    copy=copiar_nucleo(proyecto,tmp_path/'publico')
    assert not (copy/'docs/informe_energetico/informe.pdf').exists()
    assert not (copy/'data/gold/anexos').exists()
    assert (copy/'data/gold/referencia_anual/resultado.csv').read_text()=='ahorro;403.1\n'
    z=verificar(copy);assert z['documentacion_reservada'] and z['documentos_reservados']==5
    assert not any(x['ruta'].startswith('docs/informe_energetico/') for x in json.loads((copy/'manifiestos/archivos.json').read_text())['archivos'])


@pytest.mark.parametrize('nombre',['data/bronze/fuente.csv','data/gold/referencia_anual/resultado.csv'])
def test_falta_de_entrada_numerica_falla_tambien_en_reserva(proyecto,nombre):
    (proyecto/nombre).unlink()
    with pytest.raises(ValueError,match='Falta'):verificar(proyecto)


def test_dato_alterado_no_se_tolera(proyecto):
    (proyecto/'data/silver/referencia.csv').write_text('otro')
    with pytest.raises(ValueError,match='modificado'):verificar(proyecto)


def test_solo_editar_bloque_levanta_la_reserva(proyecto,tmp_path):
    write(proyecto/'.gitignore',politica(False))
    assert verificar(proyecto)['bloque_gitignore_editado_desde_preparacion']
    copy=copiar_nucleo(proyecto,tmp_path/'completo');assert (copy/'docs/informe_energetico/informe.pdf').is_file()
    assert not verificar(copy)['documentacion_reservada']
    assert json.loads((copy/'manifiestos/archivos.json').read_text())['documentos_no_distribuidos']==[]


def test_eliminar_bloque_tambien_levanta_reserva(proyecto,tmp_path):
    write(proyecto/'.gitignore','# Datos por release\ndata/\n')
    assert not verificar(proyecto)['documentacion_reservada']
    assert (copiar_nucleo(proyecto,tmp_path/'completo')/'docs/informe_energetico/main.tex').is_file()


def test_cambiar_reglas_ajenas_al_bloque_falla(proyecto):
    write(proyecto/'.gitignore',politica().replace('data/','data/\n*.py',1))
    with pytest.raises(ValueError,match='fuera del bloque'):verificar(proyecto)


def test_levantar_reserva_con_documentos_ausentes_no_simula_entrega_completa(proyecto,tmp_path):
    copy=copiar_nucleo(proyecto,tmp_path/'publico');write(copy/'.gitignore',politica(False))
    with pytest.raises(ValueError,match='entrega documental completa'):verificar(copy)


def test_no_se_puede_poner_un_dato_en_lista_documental(proyecto):
    p=proyecto/'manifiestos/archivos.json';m=json.loads(p.read_text());m['documentos_no_distribuidos']=[m['archivos'].pop(1)];p.write_text(json.dumps(m))
    with pytest.raises(ValueError,match='no puede declararse'):verificar(proyecto)


def test_zip_reservado_filtra_incluso_arbol_completo(proyecto,tmp_path):
    out=tmp_path/'zip';packages=empaquetar(proyecto,out);assert len(packages)==4
    extracted=tmp_path/'extraido';extracted.mkdir()
    for x in packages:
        with zipfile.ZipFile(out/x['archivo']) as z:
            assert not any(leer_politica(proyecto).excluye(n) for n in z.namelist())
            assert not any(b'DOCUMENTO_RESERVADO' in z.read(n) or b'ANEXO_DOCUMENTAL_RESERVADO' in z.read(n) for n in z.namelist())
            z.extractall(extracted)
    assert verificar(extracted)['documentos_reservados']==5


def test_zip_completo_solo_necesita_cambiar_gitignore(proyecto,tmp_path):
    write(proyecto/'.gitignore',politica(False));out=tmp_path/'zip';packages=empaquetar(proyecto,out)
    names=[]
    for x in packages:
        with zipfile.ZipFile(out/x['archivo']) as z:names+=z.namelist()
    assert 'docs/informe_energetico/main.tex' in names and 'data/gold/anexos/balance_anual.csv' in names


def test_politica_publica_puede_seleccionarse_sin_cambiar_desarrollo(proyecto,tmp_path):
    publico=write(tmp_path/'publico.gitignore',politica());write(proyecto/'.gitignore',politica(False));before=(proyecto/'.gitignore').read_bytes()
    copy=copiar_nucleo(proyecto,tmp_path/'destino',politica=leer_politica(proyecto,publico))
    assert not (copy/'docs/informe_energetico/main.tex').exists() and (proyecto/'.gitignore').read_bytes()==before
