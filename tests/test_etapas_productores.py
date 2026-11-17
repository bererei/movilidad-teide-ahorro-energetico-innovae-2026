"""Contratos de los productores conectados, sin duplicar sus fórmulas físicas."""
import json
import pandas as pd


def test_resumen_de_geografia_sigue_siendo_lista_al_anadir_clasificacion(tmp_path,monkeypatch):
    from movilidad_teide.flujos import preparacion_geografia as flujo
    from movilidad_teide.cartografia import preparacion as cartografia
    from movilidad_teide.energia import preparacion_vial as vial,preparacion_osrm as osrm
    root=tmp_path/'root';(root/'manifiestos').mkdir(parents=True)
    (root/flujo.CONTRATO).write_text(json.dumps({'cabeceras':{'ordinarias':[]}}))
    tabla=pd.DataFrame({'valor':[1.]})
    class Preparador:
        def __init__(self,*a,**kw):self.cat={}
        def preparar(self):return {'tabla':tabla},{'terrenos':[]}
    monkeypatch.setattr(cartografia,'Preparador',Preparador)
    monkeypatch.setattr(flujo,'verificar_fuentes',lambda r:{'fuentes_sha256':{}})
    monkeypatch.setattr(vial,'clasificar_habituales',lambda p:(tabla,tabla,{}))
    monkeypatch.setattr(vial,'unir_perfiles_habituales',lambda *a:tabla)
    monkeypatch.setattr(osrm,'clasificar_reasignados',lambda *a:tabla)
    monkeypatch.setattr(osrm,'unir_reasignados',lambda *a:tabla)
    destino=tmp_path/'salida'
    m=flujo.preparar(root,destino,clasificar_vias=True,referencia={'valores':{'visitas_anio':2500000}})
    guardado=json.loads((destino/'metadatos.json').read_text())
    assert isinstance(m['resumen_tablas'],list)
    assert guardado['resumen_tablas']==[{'producto':'tabla','filas':1,'columnas':1,'geometria':False,'archivo':'tablas/tabla.parquet'}]
    assert guardado['clasificacion_reconstruida']
