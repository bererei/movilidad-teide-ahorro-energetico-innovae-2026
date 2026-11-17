"""Contratos de las rutas comunes, fuentes inmutables y resultados aprobados."""
from pathlib import Path
import hashlib,json
import pandas as pd
import pytest
from movilidad_teide.flujos.ordenacion_vigente import _destino_nuevo
from movilidad_teide.publicacion.gold import comprobar_gold

ROOT=Path(__file__).resolve().parents[1]

def test_destino_nuevo_en_silver_es_permitido(tmp_path):
    root=tmp_path/'proyecto';root.mkdir();dest=root/'data/silver/ejecuciones/prueba'
    assert _destino_nuevo(root,dest)==dest

def test_enlace_no_convierte_gold_en_un_destino_de_ejecucion(tmp_path):
    root=tmp_path/'proyecto';(root/'data/gold').mkdir(parents=True);(root/'data/silver').mkdir();(root/'data/silver/ejecuciones').symlink_to(root/'data/gold',target_is_directory=True)
    with pytest.raises(ValueError):_destino_nuevo(root,root/'data/silver/ejecuciones/nueva')
    assert not (root/'data/gold/nueva').exists()

def test_indice_actual_usa_las_rutas_medallion_directamente():
    index=json.loads((ROOT/'config/referencia_ordenacion_2028.json').read_text())
    assert index['parametros_de_la_referencia']['visitas_anio']['valor_sellado']==2500000
    assert len(index['gold_sha256'])==55
    assert not any(n.startswith(('data/silver/energia_turismos/','data/silver/movilidad/')) for n in index['entradas_sha256'])

def test_gold_se_contrasta_con_su_huella_y_no_con_una_copia_de_si_mismo(tmp_path):
    root=tmp_path/'proyecto';gold=root/'data/gold';gold.mkdir(parents=True);expected={}
    for i in range(55):
        f=gold/(str(i)+'.csv');f.write_text('referencia');expected[str(f.relative_to(root))]=hashlib.sha256(f.read_bytes()).hexdigest()
    cfg=root/'config/referencia_ordenacion_2028.json';cfg.parent.mkdir();cfg.write_text(json.dumps({'arquitectura':'Medallion','gold_sha256':expected}))
    assert len(comprobar_gold(root))==55
    (gold/'0.csv').write_text('otra referencia')
    with pytest.raises(ValueError,match='cierre aprobado'):comprobar_gold(root)

def test_excursiones_solo_aporta_unidades_sin_cantidades_de_otra_actividad():
    x=pd.read_csv(ROOT/'data/silver/energia/excursiones/referencias_por_origen.csv',sep=';')
    assert len(x)==312 and not x.duplicated(['origen_id','colectivo','sentido']).any()
    assert set(x)=={'origen_id','colectivo','sentido','longitud_referencia_sentido_km','factor_hot_referencia_mj_km'}
