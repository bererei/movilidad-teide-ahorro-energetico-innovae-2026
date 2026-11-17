"""La promoción no debe publicar otra referencia ni sobrescribir antecedentes."""
from pathlib import Path
import hashlib,json
import pytest
from movilidad_teide.publicacion.gold import promover_gold,seleccionar_gold


def fixture_root(tmp_path):
    root=tmp_path/'desarrollo'
    def save(name,text):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
    save('config/referencia_ordenacion_2028.json',json.dumps({'captura':'data/silver/calculo','productos_de_comparacion':['balance.csv'],'productos_actualizados':{}}))
    save('docs/informe_energetico/metadatos.json',json.dumps({'version_informe':'0.25'}))
    save('data/silver/calculo/balance.csv','visitas\n2500000\n')
    save('docs/informe_energetico/anexos_vigentes/visitas.csv','2500000\n')
    save('docs/informe_energetico/ANEXOS_ENERGETICOS_2028_v0.25.zip','paquete de prueba')
    return root


def test_promocion_verificable_e_idempotente(tmp_path):
    root=fixture_root(tmp_path)
    first=promover_gold(root);assert first['archivos_creados']==3
    second=promover_gold(root,verificar=True);assert second['archivos_creados']==0
    assert promover_gold(root)['archivos_creados']==0
    assert (root/'data/silver/calculo/balance.csv').read_text()=='visitas\n2500000\n'


def test_conflicto_se_rechaza_antes_de_copiar(tmp_path):
    root=fixture_root(tmp_path);existing=root/'data/gold/anexos/visitas.csv'
    existing.parent.mkdir(parents=True);existing.write_text('antecedente a conservar')
    with pytest.raises(FileExistsError,match='no se sobrescribe'):promover_gold(root)
    assert existing.read_text()=='antecedente a conservar'
    assert not (root/'data/gold/referencia_anual/balance.csv').exists()


def test_candidata_alterada_no_promueve_resultados(tmp_path):
    root=fixture_root(tmp_path);candidate=tmp_path/'candidata';manifest=[]
    for dest,source in seleccionar_gold(root).items():
        p=candidate/dest;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((root/source).read_bytes())
        manifest.append({'ruta':dest,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    (candidate/'manifiestos').mkdir();(candidate/'manifiestos/archivos.json').write_text(json.dumps({'archivos':manifest}))
    (candidate/'data/gold/referencia_anual/balance.csv').write_text('otra referencia')
    with pytest.raises(ValueError,match='desalineada'):promover_gold(root,candidate)
    assert not (root/'data/gold').exists()


def test_no_se_admiten_origenes_fuera_del_proyecto(tmp_path):
    root=fixture_root(tmp_path);p=root/'config/referencia_ordenacion_2028.json'
    d=json.loads(p.read_text());d['productos_actualizados']={'balance.csv':'../externo.csv'};p.write_text(json.dumps(d))
    (root.parent/'externo.csv').write_text('fuera')
    with pytest.raises(ValueError,match='no portable'):promover_gold(root)
    assert not (root/'data/gold').exists()
