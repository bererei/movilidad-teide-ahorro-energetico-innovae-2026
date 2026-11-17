"""Controles de fidelidad y detección de alteraciones en las entradas públicas."""
from pathlib import Path
import json
import pytest
from openpyxl import Workbook,load_workbook
from movilidad_teide.vehiculos.copert_publico import export_workbook,import_workbook,verify_package,digest
from movilidad_teide.vehiculos.copert_publico import normalize,KEYS
import pandas as pd
from io import StringIO

def test_csv_preserva_textos_numericos_ceros_vacios_y_orden(tmp_path):
    source=tmp_path/'origen.xlsx';w=Workbook();s=w.active;s.title='SHEETS'
    s.append(['Hoja','Unidad']);s.append(['STOCK','[n]'])
    s=w.create_sheet('STOCK');s.append(['Category','Fuel','Segment','Euro Standard','2028'])
    s.append(['Passenger Cars','Petrol','001','Euro 6 d/e',0]);s.append(['texto;con separador','comillas "',None,False,17.25]);w.save(source);w.close()
    export_workbook(source,tmp_path/'csv');import_workbook(tmp_path/'csv',tmp_path/'nuevo.xlsx')
    a=load_workbook(source,read_only=True);b=load_workbook(tmp_path/'nuevo.xlsx',read_only=True)
    try:
        assert a.sheetnames==b.sheetnames
        for name in a.sheetnames:assert list(a[name].values)==list(b[name].values)
        assert b['STOCK']['C2'].value=='001' and b['STOCK']['E1'].value=='2028'
        assert b['STOCK']['E2'].value==0 and b['STOCK']['D3'].value is False
    finally:a.close();b.close()

def test_paquete_rechaza_csv_alterado(tmp_path):
    p=tmp_path/'tabla.csv';p.write_text('valor;unidad\n34;km/h\n')
    m={'consultas':[{'nombre':str(i)} for i in range(34)],'archivos_sha256':{'tabla.csv':digest(p)}}
    (tmp_path/'manifiesto.json').write_text(json.dumps(m))
    verify_package(tmp_path)
    p.write_text('valor;unidad\n35;km/h\n')
    with pytest.raises(ValueError,match='modificada'):verify_package(tmp_path)

def test_conversion_rechaza_celdas_con_formula(tmp_path):
    w=Workbook();w.active.append(['=1+1']);w.save(tmp_path/'formula.xlsx');w.close()
    with pytest.raises(ValueError,match='fórmulas'):export_workbook(tmp_path/'formula.xlsx',tmp_path/'csv')

def test_comparacion_no_confunde_campo_vacio_con_tipo_texto(tmp_path):
    vehicle=['Passenger Cars','Petrol','Mini','Euro 4'];year=2028
    c={'vehicles':[vehicle],'year':year,'mode_shares':dict.fromkeys(['urban_peak','urban_off_peak','rural','highway'],.25),
        'stock_per_category':1,'mean_activity_km':17.,'speed_kmh':20,'fuel_year_specification':1996,'slope_correction':'Factor nativo'}
    w=Workbook();w.active.title='SHEETS';w.active.append(['Hoja','Unidad']);w.active.append(['EC_HOT','[TJ]'])
    s=w.create_sheet('EC_HOT');s.append(['Category','Fuel','Segment','Euro Standard','Componente','Indicador',*[f'{year}_{m}' for m in ['PK','OP','R','H','T']]])
    s.append([*vehicle,'Hot','EC',.00000425,.00000425,.00000425,.00000425,.000017]);w.save(tmp_path/'resultado.xlsx');w.close()
    actual=normalize(tmp_path/'resultado.xlsx',c,'turismos20','explicit_car_reference')
    expected=pd.read_csv(StringIO(actual.to_csv(index=False)))
    joined=expected.merge(actual,on=KEYS,validate='one_to_one')
    assert len(joined)==4


def paquete_medallion(tmp_path):
    from movilidad_teide.vehiculos.copert_publico import dump
    bronze=tmp_path/'bronze'/'entradas';silver=tmp_path/'silver'/'referencia'
    bronze.mkdir(parents=True);silver.mkdir(parents=True)
    (bronze/'tabla.csv').write_text('valor;unidad\n34;km/h\n')
    (silver/'factores_esperados.csv').write_text('factor\n1.25\n')
    h=digest(silver/'factores_esperados.csv')
    dump(bronze/'manifiesto.json',{'version':'1.1','capa':'Bronze','consultas':[{'nombre':str(i)} for i in range(34)],
        'archivos_sha256':{'tabla.csv':digest(bronze/'tabla.csv')},'referencia_comparacion_sha256':h})
    dump(silver/'manifiesto.json',{'capa':'Silver','archivos_sha256':{'factores_esperados.csv':h}})
    return bronze,silver


def test_referencia_silver_separada_no_contamina_bronze(tmp_path):
    from movilidad_teide.vehiculos.copert_publico import load_reference
    bronze,silver=paquete_medallion(tmp_path)
    assert not (bronze/'factores_esperados.csv').exists()
    verify_package(bronze)
    assert load_reference(bronze,silver).factor.item()==1.25
    with pytest.raises(ValueError,match='separada'):load_reference(bronze,bronze)


def test_referencia_alterada_se_rechaza_aunque_bronze_sea_valido(tmp_path):
    from movilidad_teide.vehiculos.copert_publico import load_reference
    bronze,silver=paquete_medallion(tmp_path)
    (silver/'factores_esperados.csv').write_text('factor\n1.26\n')
    verify_package(bronze)
    with pytest.raises(ValueError,match='modificada'):load_reference(bronze,silver)


def test_referencia_de_otro_paquete_no_se_admite(tmp_path):
    from movilidad_teide.vehiculos.copert_publico import load_reference,dump
    bronze,silver=paquete_medallion(tmp_path)
    (silver/'factores_esperados.csv').write_text('factor\n1.26\n')
    dump(silver/'manifiesto.json',{'capa':'Silver','archivos_sha256':{'factores_esperados.csv':digest(silver/'factores_esperados.csv')}})
    with pytest.raises(ValueError,match='no corresponde'):load_reference(bronze,silver)
