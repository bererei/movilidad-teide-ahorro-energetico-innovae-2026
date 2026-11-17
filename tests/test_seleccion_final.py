"""Selección, condiciones de difusión y preservación de las fuentes."""
import csv,hashlib,json,zipfile
from pathlib import Path
import pytest
from movilidad_teide.publicacion.seleccion import preparar,evaluar_seleccion
from movilidad_teide.publicacion.empaquetado import empaquetar
from movilidad_teide.publicacion.reserva import INICIO,FIN,PATRONES

def tabla(p,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter=';');w.writeheader();w.writerows(rows)

@pytest.fixture
def entrega_final(tmp_path):
    root=tmp_path/'fuente';root.mkdir()
    (root/'.gitignore').write_text(INICIO+'\n'+'\n'.join(PATRONES)+'\n'+FIN+'\n')
    f=root/'data/bronze/fuente.csv';f.parent.mkdir(parents=True);f.write_text('visitas;2500000\n')
    doc=root/'docs/informe_energetico/informe.pdf';doc.parent.mkdir(parents=True);doc.write_text('Documento de la referencia')
    names=['.gitignore','data/bronze/fuente.csv','docs/informe_energetico/informe.pdf','manifiestos/seleccion_entrega_publica.csv','manifiestos/condiciones_entrega_publica.csv']
    tabla(root/'manifiestos/seleccion_entrega_publica.csv',[dict(ruta=n,decision_final_8_2='incluir',caso_externo='fuente' if n.endswith('fuente.csv') else '') for n in names+['manifiestos/archivos.json']])
    tabla(root/'manifiestos/condiciones_entrega_publica.csv',[dict(condicion='fuente',estado='pendiente',comprobacion_para_cierre='Documentar el alcance de reutilización')])
    manifest={'version':'2.8','archivos':[dict(ruta=n,bytes=(root/n).stat().st_size,sha256=hashlib.sha256((root/n).read_bytes()).hexdigest()) for n in names]}
    (root/'manifiestos/archivos.json').write_text(json.dumps(manifest))
    return root

def actualizar(root,n):
    p=root/'manifiestos/archivos.json';m=json.loads(p.read_text())
    for row in m['archivos']:
        if row['ruta']==n:row.update(bytes=(root/n).stat().st_size,sha256=hashlib.sha256((root/n).read_bytes()).hexdigest())
    p.write_text(json.dumps(m))

def test_condicion_pendiente_impide_preparar_difusion(entrega_final,tmp_path):
    target=tmp_path/'difusion'
    with pytest.raises(ValueError,match='Difusión pendiente'):preparar(entrega_final,target)
    assert not target.exists()

def test_ensayo_local_es_explicito_y_conserva_fuente(entrega_final,tmp_path):
    original=(entrega_final/'data/bronze/fuente.csv').read_bytes()
    target=tmp_path/'ensayo';tree=preparar(entrega_final,target,ensayo_local=True)
    control=json.loads((target/'CONTROL_SELECCION.json').read_text())
    assert control['ensayo_local'] and not control['apta_para_difusion'] and control['casos_pendientes']==['fuente']
    assert (tree/'data/bronze/fuente.csv').read_bytes()==original
    assert not (tree/'docs/informe_energetico/informe.pdf').exists()
    assert (entrega_final/'data/bronze/fuente.csv').read_bytes()==original

@pytest.mark.parametrize('modo',['ausente','duplicado','extra','sin_decision'])
def test_selector_incompleto_o_ambiguo_no_se_acepta(entrega_final,modo):
    p=entrega_final/'manifiestos/seleccion_entrega_publica.csv'
    with p.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f,delimiter=';'))
    if modo=='ausente':rows.pop()
    elif modo=='duplicado':rows.append(rows[0])
    elif modo=='extra':rows.append(dict(rows[0],ruta='no_inventariado.txt'))
    else:rows[0]['decision_final_8_2']='pendiente'
    tabla(p,rows)
    with pytest.raises(ValueError):evaluar_seleccion(entrega_final)

def test_caso_desconocido_no_se_interpreta_como_permiso(entrega_final):
    tabla(entrega_final/'manifiestos/condiciones_entrega_publica.csv',[dict(condicion='otra',estado='cumplida',comprobacion_para_cierre='Otra condición')])
    with pytest.raises(ValueError,match='sin condición'):evaluar_seleccion(entrega_final)

def test_condicion_documentada_permite_preparar_sin_excepcion(entrega_final,tmp_path):
    n='manifiestos/condiciones_entrega_publica.csv'
    tabla(entrega_final/n,[dict(condicion='fuente',estado='cumplida',comprobacion_para_cierre='Condición documentada en este caso de prueba')]);actualizar(entrega_final,n)
    tree=preparar(entrega_final,tmp_path/'correcta')
    assert evaluar_seleccion(tree)['apta_para_difusion']

def test_empaquetado_directo_tampoco_elude_condiciones(entrega_final,tmp_path):
    with pytest.raises(ValueError,match='condiciones pendientes'):empaquetar(entrega_final,tmp_path/'zip')

def test_zip_repetidos_tienen_misma_huella_y_distinguen_ensayo(entrega_final,tmp_path):
    first=empaquetar(entrega_final,tmp_path/'uno',ensayo_local=True)
    for p in entrega_final.rglob('*'):
        if p.is_file():
            import os
            os.utime(p,(1700000000,1700000000))
    second=empaquetar(entrega_final,tmp_path/'dos',ensayo_local=True)
    assert [x['sha256'] for x in first]==[x['sha256'] for x in second]
    meta=json.loads((tmp_path/'uno/manifiesto_paquetes.json').read_text())
    assert meta['ensayo_local'] and not meta['apta_para_difusion'] and meta['zip_determinista']
    for row in first:
        with zipfile.ZipFile(tmp_path/'uno'/row['archivo']) as z:
            assert not any(n.startswith('docs/informe_energetico/') for n in z.namelist())
