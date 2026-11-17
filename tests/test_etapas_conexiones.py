"""Comprobar cableado de productos reales de archivo sin repetir fórmulas científicas."""
import json
from pathlib import Path
from types import SimpleNamespace
import pandas as pd


def test_recargar_geografia_conserva_tipo_crs_y_geometria_para_el_productor(tmp_path):
    import geopandas as gpd
    from shapely.geometry import Point
    from movilidad_teide.flujos.etapas_registradas import _tablas_geografia
    folder=tmp_path/'tablas/operativos/corredor';folder.mkdir(parents=True)
    original=gpd.GeoDataFrame({'cota':[120.]},geometry=[Point(300000,3100000)],crs=32628)
    original.to_parquet(folder/'perfil.parquet',index=False)
    tabla=_tablas_geografia(tmp_path)['operativos/corredor/perfil']
    assert isinstance(tabla,gpd.GeoDataFrame) and tabla.crs==original.crs
    assert tabla.geometry.iloc[0].equals_exact(original.geometry.iloc[0],0)
    tabla.to_parquet(tmp_path/'producto.parquet',index=False)
    assert gpd.read_parquet(tmp_path/'producto.parquet').crs==original.crs


def test_geografia_usa_la_demanda_recibida_sin_reextraer_sus_fuentes(tmp_path,monkeypatch):
    from movilidad_teide.cartografia import preparacion_referencias as modulo
    (tmp_path/'config').mkdir()
    (tmp_path/'config/asignacion_demanda.json').write_text(json.dumps({'corredores':{},'aproximaciones_geograficas_estudio':{'casos':[]}}))
    catalogo={k:{} for k in ['origin_access_comparisons','study_origin_access_comparisons','coastal_valley_comparisons']}
    monkeypatch.setattr(modulo,'normalizar_recorridos_estudio',lambda *a:({},pd.DataFrame(columns=['origen_id','comparacion_id','sentido','directa_km'])))
    def prohibida(*a,**kw):raise AssertionError('No se debe reextraer una demanda ya conectada')
    for name in ['extraer_visor','preparar_zonas','preparar_gtfs']:monkeypatch.setattr(modulo,name,prohibida)
    prep=SimpleNamespace(root=tmp_path,cat=catalogo,tables={},demanda_conectada={
        'territorio/demanda_por_origen':pd.DataFrame({'origen_id':list(range(41)),'viajes_persona_media_57_matrices':[0.]*41}),
        'territorio/origenes':pd.DataFrame({'origen_id':list(range(41))})})
    modulo.reconstruir_referencias(prep)
    assert len(prep.tables['referencias/recorridos_referencia_calculo'])==82


def test_balance_propaga_factores_flota_programacion_y_demanda_de_la_ejecucion(tmp_path,monkeypatch):
    from movilidad_teide.flujos import etapas_registradas as flujo,balance_desde_perfiles as balance
    from movilidad_teide.energia import preparacion_coeficientes as coef
    root=tmp_path/'root';(root/'config').mkdir(parents=True);(root/'config/marcador.json').write_text('{}')
    (root/'manifiestos').mkdir();(root/'manifiestos/preparacion_balance.json').write_text('{}')
    deps={k:tmp_path/('etapa_'+k) for k in ['01','02','03','04','05']}
    for p in deps.values():p.mkdir()
    p=deps['01']/'tablas_parquet/territorio';p.mkdir(parents=True)
    pd.DataFrame({'marcador':['demanda_nueva']}).to_parquet(p/'origenes_por_modo_2025.parquet',index=False)
    (deps['02']/'catalogo_resuelto.json').write_text('{}');(deps['02']/'clasificacion').mkdir()
    for n in ['segmentos_habituales','segmentos_osrm']:
        pd.DataFrame({'marcador':['perfil_nuevo']}).to_parquet(deps['02']/('clasificacion/'+n+'.parquet'),index=False)
    calls=[]
    def turismos(root,calc,prep,seg,demanda,parametros,**kw):
        assert demanda['territorio/origenes_por_modo_2025'].marcador.item()=='demanda_nueva'
        assert seg.marcador.item()=='perfil_nuevo'
        assert kw==dict(factores=deps['05'],flota=deps['03']/'seleccion/data/silver/vehiculos/flota_teide',operacion=deps['04']/'insumos')
        calls.append('turismos');return {}
    def autobuses(root,calc,prep,parametros,**kw):
        assert kw==dict(factores=deps['05'],operacion=deps['04']/'insumos');calls.append('autobuses')
    def alimentacion(root,calc,demanda,parametros,**kw):
        assert kw['operacion']==deps['04']/'insumos';calls.append('alimentacion')
    def completar(root,calc,demanda,**kw):
        assert kw['operacion']==deps['04']/'insumos';calls.append('programacion')
    def calcular(calc,destino):
        destino.mkdir();pd.DataFrame({'visitas_sin_dia':[2500000/366]*366}).to_csv(destino/'recomendada_calendario.csv',sep=';',index=False)
        calls.append('balance');return SimpleNamespace(auditorias=[1])
    monkeypatch.setattr(coef,'preparar_turismos',turismos);monkeypatch.setattr(coef,'preparar_autobuses',autobuses)
    monkeypatch.setattr(coef,'preparar_alimentacion_titsa',alimentacion)
    monkeypatch.setattr(coef,'preparar_excursiones',lambda *a:None);monkeypatch.setattr(coef,'preparar_unidades_reasignadas',lambda *a:None)
    monkeypatch.setattr(balance,'completar_raiz_calculo',completar);monkeypatch.setattr(balance,'calcular_balance',calcular)
    out=tmp_path/'salida';out.mkdir();ref=dict(base={},valores={'visitas_anio':2500000},indice={'productos_actualizados':{'producto':'resultado'}})
    m=flujo._balance(root,ref,deps,out)
    assert calls==['turismos','autobuses','alimentacion','programacion','balance']
    assert m['energia_calculada'] and m['visitas_sin_y_con']==2500000


def test_inventario_fijado_no_se_confunde_con_demanda_previa(tmp_path):
    import pytest
    from movilidad_teide.flujos.etapas_registradas import lecturas_de_etapa
    from movilidad_teide.trazabilidad import sha256_archivo
    root=tmp_path/'root';run=tmp_path/'run';dest=run/'resultados/04/intento';dest.mkdir(parents=True)
    rutas=['data/silver/demanda/referencias_temporales/p85_P15_P20/inventario_30.csv','data/silver/demanda/origenes.csv']
    fuentes=[]
    for n in rutas:
        p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('dato\n')
        fuentes.append(dict(ruta=n,sha256=sha256_archivo(p),bytes=p.stat().st_size,rol='entrada_de_calculo'))
    with lecturas_de_etapa(root,run,dest,fuentes,[],'04',demanda_original=[rutas[1]]):
        assert (root/rutas[0]).read_text()=='dato\n'
        with pytest.raises(PermissionError,match='demanda de la ejecución'):(root/rutas[1]).read_text()
