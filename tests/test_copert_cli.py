"""Contratos de entrada/salida; las tablas de prueba no son datos del modelo."""
from pathlib import Path

from openpyxl import Workbook, load_workbook
import pytest

from movilidad_teide.copert_cli import (
    VEHICLE, file_hash, inspect_input, prepare_case, read_hot_ec, validate_pilot_input,
    read_hot_factor, make_base_reference,
)


def template(path: Path):
    book = Workbook()
    book.active.title = 'SHEETS'
    book['SHEETS'].append(['SHEET_NAME', 'Unit'])
    values = {'STOCK': 1, 'MEAN_ACTIVITY': 17, 'RURAL_SPEED': 34,
              'RURAL_SHARE': 1, 'RURAL_LOAD': 0.5, 'RURAL_ROAD_SLOPE': 0.02,
              'URBAN_PEAK_SHARE': 0, 'URBAN_OFF_PEAK_SHARE': 0, 'HIGHWAY_SHARE': 0}
    for name, value in values.items():
        s = book.create_sheet(name)
        s.append(['Category', 'Fuel', 'Segment', 'Euro Standard', '2028'])
        s.append([*VEHICLE, value])
        book['SHEETS'].append([name, 'fixture'])
    s = book.create_sheet('FB~FUEL_BALANCE')
    s.append(['2028']); s.append([0])
    book.save(path)


def output(path: Path, unit='[TJ]', vehicle=VEHICLE, highway=0):
    book = Workbook()
    book.active.title = 'SHEETS'
    book['SHEETS'].append(['SHEET_NAME', 'Unit'])
    book['SHEETS'].append(['EC_HOT', unit])
    s = book.create_sheet('EC_HOT')
    s.append(['Category', 'Fuel', 'Segment', 'Euro Standard', 'Emission', 'Pollutant\n[TJ]',
              '2028_PK', '2028_OP', '2028_R', '2028_H', '2028_T'])
    s.append([*vehicle, 'Hot', 'EC', 0, 0, 0.000255, highway, 0.000255 + highway])
    book.save(path)


def configuration():
    return {'vehicle_km': 17, 'year': 2028, 'vehicle': list(VEHICLE), 'slope_pct': 0}


def test_incomplete_template_cannot_launch_case(tmp_path):
    source = tmp_path / 'originales'; source.mkdir()
    project = source / 'project.cop'; project.write_bytes(b'fixture_no_ejecutable')
    book = Workbook(); book.save(source / 'input.xlsx')
    info = inspect_input(source / 'input.xlsx')
    assert 'RURAL_SPEED' in info['fields_inherited_from_base']
    with pytest.raises(ValueError, match='Completar la exportación'):
        prepare_case(project, source / 'input.xlsx', tmp_path / 'caso', 0)
    assert not (tmp_path / 'caso').exists()


def test_case_keeps_sources_and_sets_explicit_slope_fraction(tmp_path):
    source = tmp_path / 'originales'; source.mkdir()
    project = source / 'project.cop'; project.write_bytes(b'fixture_no_ejecutable')
    original = source / 'input.xlsx'; template(original)
    hashes = (file_hash(project), file_hash(original))
    dest = tmp_path / 'caso'
    manifest = prepare_case(project, original, dest, -4)
    assert (file_hash(project), file_hash(original)) == hashes
    assert (dest / 'proyecto.cop').read_bytes() == project.read_bytes()
    assert manifest['configuration']['values']['RURAL_ROAD_SLOPE'] == -0.04
    assert manifest['configuration']['values']['RURAL_SPEED'] == 34
    assert manifest['configuration']['vehicle_km'] == 17
    with pytest.raises(FileExistsError):
        prepare_case(project, original, dest, -4)


def test_hot_energy_is_normalized_once_from_tj(tmp_path):
    path = tmp_path / 'output.xlsx'; output(path)
    result = read_hot_ec(path, configuration())
    assert result['hot_ec_mj'] == pytest.approx(255)
    assert result['hot_ec_mj_per_km'] == pytest.approx(15)


def test_unexpected_unit_is_rejected(tmp_path):
    path = tmp_path / 'output.xlsx'; output(path, unit='[kg]')
    with pytest.raises(ValueError, match='Unidad'):
        read_hot_ec(path, configuration())


def test_other_vehicle_is_not_selected(tmp_path):
    path = tmp_path / 'output.xlsx'; output(path, vehicle=('Passenger Cars', 'Diesel', 'Small', 'Euro 6'))
    with pytest.raises(ValueError, match='ambiguo'):
        read_hot_ec(path, configuration())


def test_nonrural_energy_is_not_silently_added(tmp_path):
    path = tmp_path / 'output.xlsx'; output(path, highway=0.000001)
    with pytest.raises(ValueError, match='reparto'):
        read_hot_ec(path, configuration())


@pytest.mark.parametrize('sheet,cell,value', [('FB~FUEL_BALANCE','A2',1), ('RURAL_LOAD','E2',0.85)])
def test_input_balance_and_load_must_match_pilot(tmp_path, sheet, cell, value):
    path = tmp_path / 'input.xlsx'; template(path)
    book = load_workbook(path)
    book['RURAL_SPEED']['E2'] = 34
    book['RURAL_ROAD_SLOPE']['E2'] = 0
    book[sheet][cell] = value
    book.save(path)
    with pytest.raises(ValueError):
        validate_pilot_input(path, 0)


def factor_export(path, value=15):
    book = Workbook(); book.active.title = 'SHEETS'
    book['SHEETS'].append(['SHEET_NAME','Unit']); book['SHEETS'].append(['HOT_EC','[MJ/km]'])
    s=book.create_sheet('HOT_EC')
    s.append(['Category','Fuel','Segment','Euro Standard','Pollutant\n[MJ/km]',
              '2028_PK\n[MJ/km]','2028_OP\n[MJ/km]','2028_R\n[MJ/km]','2028_H\n[MJ/km]','2028_T\n[MJ/km]'])
    s.append([*VEHICLE,'EC',0,0,value,0,value]);book.save(path)


def test_partial_export_can_inherit_only_from_frozen_matching_base(tmp_path):
    source=tmp_path/'originales';source.mkdir()
    project=source/'base.cop';project.write_bytes(b'fixture_no_ejecutable')
    path=source/'input.xlsx';template(path)
    book=load_workbook(path);del book['RURAL_SPEED'];del book['MEAN_ACTIVITY'];book.save(path)
    gui_factor=source/'factors.xlsx';factor_export(gui_factor)
    gui=source/'gui.xlsx';output(gui)
    cli=source/'cli.xlsx';output(cli)
    reference=make_base_reference(project,path,gui_factor,gui,cli)
    assert read_hot_factor(gui_factor)==15
    assert reference['vehicle_km']==pytest.approx(17)
    with pytest.raises(ValueError,match='Acreditar'):
        prepare_case(project,path,tmp_path/'sin_referencia',0)
    # Igualdad de energía GUI/CLI no verifica una velocidad que falta en el Excel.
    with pytest.raises(ValueError,match='Velocidad heredada sin verificación'):
        prepare_case(project,path,tmp_path/'no_acreditado',0,base_reference=reference)
    reference['rural_speed_verified_kmh']=34.0
    reference['speed_verification']='Metadato sintético del ensayo unitario; no dato del modelo'
    manifest=prepare_case(project,path,tmp_path/'caso',0,base_reference=reference)
    config=manifest['configuration']
    assert config['vehicle_km']==pytest.approx(17)
    assert not config['speed_read_directly_from_export']
    assert set(config['inherited_fields'])=={'RURAL_SPEED','MEAN_ACTIVITY'}
    assert [c['sheet'] for c in manifest['changes']]==['RURAL_ROAD_SLOPE']
    project.write_bytes(b'otro_proyecto')
    with pytest.raises(ValueError,match='no coinciden'):
        prepare_case(project,path,tmp_path/'otro_caso',0,base_reference=reference)


def test_baseline_reference_rejects_a_different_cli_energy(tmp_path):
    project=tmp_path/'base.cop';project.write_bytes(b'fixture_no_ejecutable')
    path=tmp_path/'input.xlsx';template(path)
    factors=tmp_path/'factor.xlsx';factor_export(factors)
    gui=tmp_path/'gui.xlsx';output(gui)
    cli=tmp_path/'cli.xlsx';output(cli)
    book=load_workbook(cli);book['EC_HOT']['I2']=0.000300;book['EC_HOT']['K2']=0.000300;book.save(cli)
    with pytest.raises(ValueError,match='no reproduce'):
        make_base_reference(project,path,factors,gui,cli)


def test_explicit_speed_is_checked_without_silently_overwriting_it(tmp_path):
    source=tmp_path/'originales';source.mkdir()
    project=source/'base.cop';project.write_bytes(b'fixture_no_ejecutable')
    path=source/'input.xlsx';template(path)
    book=load_workbook(path);book['RURAL_SPEED']['E2']=100;book.save(path)
    before=file_hash(path)
    with pytest.raises(ValueError,match='RURAL_SPEED'):
        prepare_case(project,path,tmp_path/'caso',0)
    assert file_hash(path)==before

# Las referencias explícitas son ensayos técnicos; no una flota inventada.
from movilidad_teide.copert_cli import (
    prepare_reference_case, validate_reference_input, run_reference_case,
)

COACH = ('Buses','Diesel','Coaches Standard <=18 t','Euro VI D/E')
HYBRID = ('Buses','Diesel Hybrid','Urban Buses Diesel Hybrid','Euro VI D/E')


def reference_sources(tmp_path):
    import csv
    path=tmp_path/'input.xlsx';template(path)
    # La fuente real exporta actividad y velocidad incompletas.
    book=load_workbook(path)
    for name in ['MEAN_ACTIVITY','RURAL_SPEED']:
        del book[name]
        for row in list(book['SHEETS'].iter_rows(min_row=2)):
            if row[0].value==name:
                book['SHEETS'].delete_rows(row[0].row)
                break
    for name,unit in {'STOCK':'[n]','RURAL_LOAD':'[%]','RURAL_ROAD_SLOPE':'[%]',
        'RURAL_SHARE':'[%]','URBAN_PEAK_SHARE':'[%]','URBAN_OFF_PEAK_SHARE':'[%]',
        'HIGHWAY_SHARE':'[%]'}.items():
        for row in book['SHEETS'].iter_rows(min_row=2):
            if row[0].value==name:row[1].value=unit
    book['SHEETS'].append(['FB~FUEL_BALANCE','[1/0]']);book.save(path);book.close()
    catalog=tmp_path/'catalog.csv'
    with catalog.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['Category','Fuel','Segment','Euro Standard','Include'])
        for vehicle in [VEHICLE,COACH,HYBRID]:writer.writerow([*vehicle,False])
    return path,catalog


def reference_case(tmp_path, **kwargs):
    template_path,catalog=reference_sources(tmp_path)
    return prepare_reference_case(template_path,catalog,tmp_path/'caso',
        [VEHICLE,COACH,HYBRID],slope_pct=kwargs.get('slope',0),
        speed_kmh=kwargs.get('speed',34),load_fraction=kwargs.get('load',.5),
        mean_activity_km=kwargs.get('activity',17))


def test_reference_has_explicit_speed_and_no_hidden_project(tmp_path):
    manifest=reference_case(tmp_path)
    c=manifest['configuration']
    assert c['rural_speed_kmh']==34 and c['inherited_fields']==[]
    assert c['vehicle_km_per_category']==17
    assert not (tmp_path/'caso/proyecto.cop').exists()
    assert manifest['case_kind']=='explicit_bus_reference'
    book=load_workbook(tmp_path/'caso/entrada.xlsx',data_only=True)
    units=dict(list(book['SHEETS'].values)[1:])
    assert units['RURAL_SPEED']=='[km/h]' and units['MEAN_ACTIVITY']=='[km]'
    assert [row[4] for row in list(book['RURAL_SPEED'].values)[1:]]==[34]*3
    book.close()


def test_reference_originals_remain_unchanged(tmp_path):
    source,catalog=reference_sources(tmp_path);before=[file_hash(p) for p in [source,catalog]]
    prepare_reference_case(source,catalog,tmp_path/'caso',[COACH],slope_pct=-6,speed_kmh=34,load_fraction=.5)
    assert [file_hash(p) for p in [source,catalog]]==before
    with pytest.raises(FileExistsError):
        prepare_reference_case(source,catalog,tmp_path/'caso',[COACH],slope_pct=-6,speed_kmh=34,load_fraction=.5)


@pytest.mark.parametrize('speed,load,slope,activity',[(0,.5,0,17),(float('nan'),.5,0,17),
    (34,1.1,0,17),(34,.5,8,17),(34,.5,0,0),(101,.5,0,17)])
def test_reference_rejects_invalid_conditions_before_creating_case(tmp_path,speed,load,slope,activity):
    with pytest.raises(ValueError):reference_case(tmp_path,speed=speed,load=load,slope=slope,activity=activity)
    assert not (tmp_path/'caso').exists()


@pytest.mark.parametrize('vehicles',[[COACH,COACH],[],[('Buses','Diesel','Coaches Standard >18 t','Euro VI D/E')],
    [('Passenger Cars','Petrol','Medium','Euro 6 d/e')]])
def test_reference_requires_documented_complete_bus_keys(tmp_path,vehicles):
    source,catalog=reference_sources(tmp_path)
    with pytest.raises(ValueError,match='Referencia no acreditada'):
        prepare_reference_case(source,catalog,tmp_path/'caso',vehicles,slope_pct=0,speed_kmh=34,load_fraction=.5)


@pytest.mark.parametrize('sheet,cell,value',[('RURAL_SPEED','E2',100),('RURAL_LOAD','E2',.6),
    ('MEAN_ACTIVITY','E2',34),('RURAL_SHARE','E2',.8),('FB~FUEL_BALANCE','A2',1)])
def test_reference_detects_mismatch_in_explicit_input(tmp_path,sheet,cell,value):
    c=reference_case(tmp_path)['configuration'];p=tmp_path/'caso/entrada.xlsx'
    book=load_workbook(p);book[sheet][cell]=value;book.save(p);book.close()
    with pytest.raises(ValueError):
        validate_reference_input(p,c['vehicles'],slope_pct=0,speed_kmh=34,load_fraction=.5)


def test_reference_requires_units_and_exact_stock_categories(tmp_path):
    c=reference_case(tmp_path)['configuration'];p=tmp_path/'caso/entrada.xlsx'
    book=load_workbook(p);book['STOCK'].append([*COACH,1]);book.save(p);book.close()
    with pytest.raises(ValueError,match='categorías adicionales'):
        validate_reference_input(p,c['vehicles'],slope_pct=0,speed_kmh=34,load_fraction=.5)


def test_reference_run_rejects_tampered_input_without_launching(tmp_path):
    reference_case(tmp_path);p=tmp_path/'caso/entrada.xlsx'
    book=load_workbook(p);book['STOCK']['E2']=2;book.save(p);book.close()
    with pytest.raises(ValueError):run_reference_case(tmp_path/'caso',tmp_path/'no_ejecutable')
    assert not (tmp_path/'caso/ejecucion.json').exists()


def test_reference_catalog_missing_key_cannot_be_silently_created(tmp_path):
    source,catalog=reference_sources(tmp_path)
    catalog.write_text('Category,Fuel,Segment,Euro Standard\n',encoding='utf-8-sig')
    with pytest.raises(ValueError,match='Referencia no acreditada'):
        prepare_reference_case(source,catalog,tmp_path/'caso',[COACH],slope_pct=0,speed_kmh=34,load_fraction=.5)


from movilidad_teide.copert_cli import read_reference_library


def library_fixture(path):
    import pandas as pd
    return pd.DataFrame([{**dict(zip(['Category','Fuel','Segment','Euro Standard'],COACH)),
        'year':2028,'slope_class_pct':p,'hot_ec_mj_per_km':10+p,
        'rural_speed_kmh':34,'load_fraction':.5,'unit':'MJ/km'} for p in [-6,-4,-2,0,2,4,6]])


def test_library_does_not_substitute_another_speed_or_vehicle(tmp_path):
    path=tmp_path/'factores.parquet';table=library_fixture(path);table.to_parquet(path,index=False)
    assert len(read_reference_library(path,COACH,speed_kmh=34,load_fraction=.5))==7
    for vehicle,speed in [(COACH,100),(HYBRID,34)]:
        with pytest.raises(ValueError,match='siete factores únicos'):
            read_reference_library(path,vehicle,speed_kmh=speed,load_fraction=.5)


@pytest.mark.parametrize('error',['duplicado','ausente','unidad','negativo'])
def test_library_rejects_incomplete_or_invalid_nodes(tmp_path,error):
    import pandas as pd
    path=tmp_path/'factores.parquet';table=library_fixture(path)
    if error=='duplicado':table=pd.concat([table,table.iloc[[0]]],ignore_index=True)
    if error=='ausente':table=table.iloc[:-1]
    if error=='unidad':table.loc[0,'unit']='g/km'
    if error=='negativo':table.loc[0,'hot_ec_mj_per_km']=-1
    table.to_parquet(path,index=False)
    with pytest.raises(ValueError):read_reference_library(path,COACH,speed_kmh=34,load_fraction=.5)


from movilidad_teide.copert_cli import apply_reference_factors_by_segment


def segment_speed_fixture(tmp_path):
    import pandas as pd
    path=tmp_path/'library.parquet';base=library_fixture(path)
    second=base.copy();second['rural_speed_kmh']=50;second['hot_ec_mj_per_km']*=2
    pd.concat([base,second],ignore_index=True).to_parquet(path,index=False)
    segments=pd.DataFrame({'segment_id':['a','b'],'length_m':[1000.,2000.],'slope_pct':[0.,0.],
                           'elevation_start_m':[10.,20.]},index=[9,3])
    conditions=pd.DataFrame({'segment_id':['b','a'],'velocidad_media_kmh':[50.,34.],
        'carga_fisica':[.5,.5],'bloque_velocidad_id':['segundo','primero'],
        'fuente_velocidad':['Referencia sintética de prueba']*2,'tipo_via':['rural']*2})
    return segments,conditions,path


def test_segment_speeds_are_selected_before_summing_energy(tmp_path):
    import pandas as pd
    segments,conditions,path=segment_speed_fixture(tmp_path);before=segments.copy(deep=True)
    out=apply_reference_factors_by_segment(segments,conditions,path,COACH)
    assert out.segment_id.tolist()==['a','b'] and out.index.tolist()==[9,3]
    assert out.velocidad_media_kmh.tolist()==[34,50]
    assert out.energia_mj.tolist()==[10,40] and out.energia_mj.sum()==50
    assert out.tiempo_a_media_elegida_min.sum()==pytest.approx(60/34+120/50)
    pd.testing.assert_frame_equal(segments,before)
    pd.testing.assert_frame_equal(out[segments.columns],before)


def test_same_speed_block_can_cover_multiple_slope_segments(tmp_path):
    segments,conditions,path=segment_speed_fixture(tmp_path)
    conditions['velocidad_media_kmh']=34;conditions['bloque_velocidad_id']='bloque_comun'
    segments['slope_pct']=[1.,-8.]
    out=apply_reference_factors_by_segment(segments,conditions,path,COACH)
    assert out.hot_ec_mj_per_km.tolist()==[11,4]
    assert out.pendiente_real_pct.tolist()==[1,-8]
    assert out.pendiente_asignacion_pct.tolist()==[1,-6]
    assert out.fuera_dominio.tolist()==[False,True]
    assert out.criterio_asignacion.tolist()==['interpolacion_lineal_interior','extremo_-6_exploratorio']


@pytest.mark.parametrize('problem',['missing','extra','duplicate','unavailable_speed','urban','no_source','contradictory_block','nan_slope','negative_length','nan_speed','load'])
def test_segment_conditions_do_not_hide_missing_or_conflicting_inputs(tmp_path,problem):
    import pandas as pd
    segments,conditions,path=segment_speed_fixture(tmp_path)
    if problem=='missing':conditions=conditions.iloc[:1]
    if problem=='extra':conditions=pd.concat([conditions,conditions.iloc[[0]].assign(segment_id='c')])
    if problem=='duplicate':conditions=pd.concat([conditions,conditions.iloc[[0]]])
    if problem=='unavailable_speed':conditions.loc[0,'velocidad_media_kmh']=42
    if problem=='urban':conditions.loc[0,'tipo_via']='urbano'
    if problem=='no_source':conditions.loc[0,'fuente_velocidad']=''
    if problem=='contradictory_block':conditions['bloque_velocidad_id']='mismo'
    if problem=='nan_slope':segments.loc[9,'slope_pct']=float('nan')
    if problem=='negative_length':segments.loc[9,'length_m']=-1
    if problem=='nan_speed':conditions.loc[0,'velocidad_media_kmh']=float('nan')
    if problem=='load':conditions.loc[0,'carga_fisica']=1.1
    with pytest.raises(ValueError):apply_reference_factors_by_segment(segments,conditions,path,COACH)


from movilidad_teide.copert_cli import (
    CAR_MODES,vehicle_value,prepare_car_reference_case,validate_car_reference_input,
    read_car_hot_ec,read_car_reference_library,
)

CAR = ('Passenger Cars','Petrol','Medium','Euro 4')
NEW_CAR = ('Passenger Cars','Petrol','Medium','Euro 6 d/e')


def car_sources(tmp_path):
    import csv
    p=tmp_path/'plantilla.xlsx';template(p);b=load_workbook(p)
    units={'STOCK':'[n]','MEAN_ACTIVITY':'[km]','RURAL_SPEED':'[km/h]',
           'RURAL_SHARE':'[%]','HIGHWAY_SHARE':'[%]','URBAN_PEAK_SHARE':'[%]','URBAN_OFF_PEAK_SHARE':'[%]'}
    for row in b['SHEETS'].iter_rows(min_row=2):
        if row[0].value in units:row[1].value=units[row[0].value]
    for name,value,unit in [('EXCLUDE_EVAPORATIVE',0,'[1/0]'),('AC_EFFECT',0,'[1/0]'),
                           ('CO2_REDUCTION',0,'[1/0]'),('FUEL_YEAR',1996,'[Integer]')]:
        sh=b.create_sheet(name);sh.append(['2028']);sh.append([value]);b['SHEETS'].append([name,unit])
    b.save(p);b.close()
    fields=['Category','Fuel','Segment','Euro Standard']
    catalog=tmp_path/'catalog.csv';candidates=tmp_path/'candidates.csv'
    for out,delimiter in [(catalog,','),(candidates,';')]:
        with out.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f,delimiter=delimiter);w.writerow([*fields,'Include'])
            for v in [CAR,NEW_CAR]:w.writerow([*v,False])
    return p,catalog,candidates


def car_case(tmp_path,**kwargs):
    a,b,c=car_sources(tmp_path)
    return prepare_car_reference_case(a,b,c,tmp_path/'caso',speed_kmh=kwargs.get('speed',40),
        mode_shares=kwargs.get('shares'),mean_activity_km=kwargs.get('activity',17),fuel_year=kwargs.get('fuel'))


def test_car_query_does_not_copy_bus_load_slope_or_vehicle_adjustments(tmp_path):
    a,b,c=car_sources(tmp_path);hashes=[file_hash(p) for p in [a,b,c]]
    m=prepare_car_reference_case(a,b,c,tmp_path/'caso',speed_kmh=40)
    assert m['case_kind']=='explicit_car_reference' and m['configuration']['fuel_year_specification']==1996
    assert [file_hash(p) for p in [a,b,c]]==hashes
    book=load_workbook(tmp_path/'caso/entrada.xlsx',data_only=True)
    assert len(list(book['RURAL_LOAD'].values))==1 and len(list(book['RURAL_ROAD_SLOPE'].values))==1
    assert vehicle_value(book,'STOCK',vehicle=CAR)==1
    assert vehicle_value(book,'RURAL_SPEED',vehicle=CAR)==40
    assert vehicle_value(book,'RURAL_SHARE',vehicle=CAR)==.25
    assert book['EXCLUDE_EVAPORATIVE']['A2'].value==1
    book.close()


@pytest.mark.parametrize('shares',[{'rural':1},{k:.3 for k in CAR_MODES},{k:(-1 if k=='rural' else 2/3) for k in CAR_MODES}])
def test_car_mode_shares_cannot_be_missing_or_normalized_silently(tmp_path,shares):
    with pytest.raises(ValueError,match='reparto técnico'):car_case(tmp_path,shares=shares)
    assert not (tmp_path/'caso').exists()


@pytest.mark.parametrize('speed,activity',[(0,17),(float('nan'),17),(140,17),(40,0)])
def test_car_query_rejects_invalid_speed_or_activity(tmp_path,speed,activity):
    with pytest.raises(ValueError):car_case(tmp_path,speed=speed,activity=activity)
    assert not (tmp_path/'caso').exists()


def test_car_keys_must_be_native_and_exact_even_when_include_is_false(tmp_path):
    a,b,c=car_sources(tmp_path);c.write_text('Category;Fuel;Segment;Euro Standard\nPassenger Cars;Diesel;Unknown;Euro 4\n')
    with pytest.raises(ValueError,match='no existe en el catálogo'):
        prepare_car_reference_case(a,b,c,tmp_path/'caso',speed_kmh=40)


@pytest.mark.parametrize('sheet,cell,value',[('RURAL_SPEED','E2',100),('RURAL_SHARE','E2',.5),
    ('MEAN_ACTIVITY','E2',34),('FB~FUEL_BALANCE','A2',1),('AC_EFFECT','A2',1)])
def test_car_validator_detects_changed_input_conditions(tmp_path,sheet,cell,value):
    m=car_case(tmp_path);p=tmp_path/'caso/entrada.xlsx';b=load_workbook(p);b[sheet][cell]=value;b.save(p);b.close()
    with pytest.raises(ValueError):validate_car_reference_input(p,m['configuration']['vehicles'],speed_kmh=40,mode_shares={k:.25 for k in CAR_MODES})


def car_output(path,configuration,unit='[TJ]',total_factor=1):
    b=Workbook();b.active.title='SHEETS';b['SHEETS'].append(['SHEET_NAME','Unit']);b['SHEETS'].append(['EC_HOT',unit])
    s=b.create_sheet('EC_HOT');s.append(['Category','Fuel','Segment','Euro Standard','Emission','Pollutant\n[TJ]',
        '2028_PK','2028_OP','2028_R','2028_H','2028_T'])
    km=configuration['mean_activity_km'];shares=configuration['mode_shares']
    energies=[15*km*shares[k]/1e6 for k in CAR_MODES]
    for v in configuration['vehicles']:s.append([*v,'Hot','EC',*energies,sum(energies)*total_factor])
    b.save(path);b.close()


def test_car_energy_is_normalized_by_each_modes_activity_once(tmp_path):
    c=car_case(tmp_path)['configuration'];p=tmp_path/'out.xlsx';car_output(p,c)
    r=read_car_hot_ec(p,c)
    assert len(r)==8 and all(row['hot_ec_mj_per_km']==pytest.approx(15) for row in r)
    assert all(row['normalization_vehicle_km']==4.25 for row in r)
    assert sum(row['hot_ec_mj'] for row in r[:4])==pytest.approx(255)


@pytest.mark.parametrize('unit,total',[('[kg]',1),('[TJ]',2)])
def test_car_output_units_and_mode_sum_are_checked(tmp_path,unit,total):
    c=car_case(tmp_path)['configuration'];p=tmp_path/'out.xlsx';car_output(p,c,unit,total)
    with pytest.raises(ValueError):read_car_hot_ec(p,c)


def test_car_zero_share_is_not_used_as_zero_consumption_factor(tmp_path):
    c=car_case(tmp_path,shares={k:int(k=='rural') for k in CAR_MODES})['configuration']
    p=tmp_path/'out.xlsx';car_output(p,c);rows=read_car_hot_ec(p,c)
    assert len(rows)==2 and all(r['driving_mode']=='rural' for r in rows)
    assert all(r['hot_ec_mj_per_km']==pytest.approx(15) for r in rows)


def test_car_library_requires_exact_mode_speed_category_and_year(tmp_path):
    import pandas as pd
    c=car_case(tmp_path)['configuration'];p=tmp_path/'out.xlsx';car_output(p,c)
    rows=read_car_hot_ec(p,c)
    df=pd.DataFrame([{**dict(zip(['Category','Fuel','Segment','Euro Standard'],r['vehicle'])),
                     **{k:v for k,v in r.items() if k!='vehicle'}} for r in rows])
    library=tmp_path/'f.parquet';df.to_parquet(library,index=False)
    assert read_car_reference_library(library,CAR,driving_mode='rural',speed_kmh=40).hot_ec_mj_per_km==pytest.approx(15)
    for kwargs in [dict(driving_mode='rural',speed_kmh=34),dict(driving_mode='rural',speed_kmh=40,year=2025),dict(driving_mode='other',speed_kmh=40)]:
        with pytest.raises(ValueError):read_car_reference_library(library,CAR,**kwargs)
    with pytest.raises(ValueError):read_reference_library(library,CAR,speed_kmh=40,load_fraction=.5)


def test_car_query_output_is_never_overwritten(tmp_path):
    a,b,c=car_sources(tmp_path);target=tmp_path/'caso'
    prepare_car_reference_case(a,b,c,target,speed_kmh=40)
    with pytest.raises(FileExistsError):prepare_car_reference_case(a,b,c,target,speed_kmh=40)


def test_car_fuel_specification_is_a_named_technical_condition(tmp_path):
    c=car_case(tmp_path,fuel=2009)['configuration'];assert c['fuel_year_specification']==2009


@pytest.fixture
def caso_anual_lanzaderas():
    """Caso pequeño con resultado analítico, sin datos de prueba en el modelo."""
    import pandas as pd
    a = pd.DataFrame([
        dict(punto='A', componente='comercial', sentido='ida', itinerary_id='ruta',
             recorridos_dia=2, km_por_recorrido=10, vehiculo_km_dia=20,
             dias_operacion=366, recorridos_anio=732, vehiculo_km_anio=7320),
        dict(punto='A', componente='reposicion_por_horario', sentido='ida', itinerary_id='ruta',
             recorridos_dia=1, km_por_recorrido=10, vehiculo_km_dia=10,
             dias_operacion=366, recorridos_anio=366, vehiculo_km_anio=3660),
        dict(punto='A', componente='cocheras', sentido='pendiente', itinerary_id=None,
             dias_operacion=366)])
    a['base_distancias']='Recorridos del estudio';a['caso_excel']='Central';a['sha256_libro']='libro'
    r = pd.DataFrame([dict(referencia_id='alternativa', referencia='Guagua de prueba',
        Category='Buses', Fuel='Diesel', Segment='Prueba', **{'Euro Standard':'VI'},
        punto='A', sentido='ida', itinerary_id='ruta', carga_fisica=carga, longitud_km=10,
        velocidad_media_kmh=34, energia_mj_recorrido=float(energia),
        energia_exterior_mj_recorrido=energia/4, longitud_exterior_km=2, anio=2028)
        for carga,energia in [(0,50),(.5,100)]])
    return a,r,dict(caso_excel='Central',sha256_libro='libro',carga_comercial=.5,anio=2028)


def test_anual_lanzaderas_resultado_analitico_y_ausencias(caso_anual_lanzaderas):
    import pandas as pd
    from movilidad_teide.copert_cli import anualizar_consumos_lanzaderas
    a,r,kw=caso_anual_lanzaderas;prev_a=a.copy(deep=True);prev_r=r.copy(deep=True)
    salida=anualizar_consumos_lanzaderas(a,r,**kw);s=salida['por_referencia'].iloc[0]
    # 2 viajes cargados de100MJ + 1 vacío de50MJ, por366 días.
    assert s.energia_comercial_mj_anio == 73200
    assert s.energia_vacios_modelizados_mj_anio == 18300
    assert s.energia_identificada_mj_anio == 91500
    assert s.energia_identificada_kwh_anio == pytest.approx(25416.666666666668)
    assert s.vehiculo_km_anio == 10980
    assert s.energia_exterior_mj_anio == 22875
    assert s.vehiculo_km_exterior_anio == 2196
    assert pd.isna(s.energia_total_sistema_mj_anio)
    assert pd.isna(s.ahorro_sistema_mj_anio)
    assert pd.isna(s.error_tratamiento_exterior_mj_anio)
    assert salida['detalle'].loc[lambda t:t.componente.eq('cocheras'),'energia_mj_anio'].isna().all()
    pd.testing.assert_frame_equal(a,prev_a);pd.testing.assert_frame_equal(r,prev_r)


def test_anual_alternativas_separadas_y_orden_indiferente(caso_anual_lanzaderas):
    import pandas as pd
    from movilidad_teide.copert_cli import anualizar_consumos_lanzaderas
    a,r,kw=caso_anual_lanzaderas;otra=r.copy();otra['referencia_id']='otra'
    otra['Segment']='Otra categoría';otra['energia_mj_recorrido']*=2;otra['energia_exterior_mj_recorrido']*=2
    rr=pd.concat([otra,r],ignore_index=True).sample(frac=1,random_state=8)
    s=anualizar_consumos_lanzaderas(a.sample(frac=1,random_state=3),rr,**kw)['por_referencia'].set_index('referencia_id')
    assert len(s)==2
    assert s.loc['alternativa','energia_identificada_mj_anio']==91500
    assert s.loc['otra','energia_identificada_mj_anio']==183000
    assert s.vehiculo_km_anio.tolist()==[10980,10980]


@pytest.mark.parametrize('cambio',[
    'sin_factor_vacio','duplicado_factor','libro_distinto','caso_distinto','longitud_distinta',
    'anual_mal','actividad_negativa','fraccion_recorrido','carga_no_cubierta','cochera_cero',
    'sin_componente','categoria_mezclada','factor_infinito','exterior_excesivo','anio_distinto',
    'distancia_excel','duplicado_actividad','calendario_no_bisiesto'])
def test_anual_rechaza_incompatibilidades(caso_anual_lanzaderas,cambio):
    import pandas as pd
    from movilidad_teide.copert_cli import anualizar_consumos_lanzaderas
    a,r,kw=caso_anual_lanzaderas
    if cambio=='sin_factor_vacio':r=r.loc[r.carga_fisica.ne(0)]
    elif cambio=='duplicado_factor':r=pd.concat([r,r.iloc[[0]]])
    elif cambio=='libro_distinto':a['sha256_libro']='otro'
    elif cambio=='caso_distinto':kw['caso_excel']='Otro'
    elif cambio=='longitud_distinta':r['longitud_km']=11
    elif cambio=='anual_mal':a.loc[0,'recorridos_anio']=733
    elif cambio=='actividad_negativa':a.loc[0,'recorridos_dia']=-2
    elif cambio=='fraccion_recorrido':a.loc[0,'recorridos_dia']=2.5
    elif cambio=='carga_no_cubierta':kw['carga_comercial']=.7
    elif cambio=='cochera_cero':a.loc[2,'vehiculo_km_anio']=0
    elif cambio=='sin_componente':a.loc[0,'componente']='desconocido'
    elif cambio=='categoria_mezclada':r.loc[0,'Fuel']='Otro'
    elif cambio=='factor_infinito':r.loc[0,'energia_mj_recorrido']=float('inf')
    elif cambio=='exterior_excesivo':r.loc[0,'longitud_exterior_km']=11
    elif cambio=='anio_distinto':r['anio']=2027
    elif cambio=='distancia_excel':a['base_distancias']='Referencias de distancia del Excel'
    elif cambio=='duplicado_actividad':a=pd.concat([a,a.iloc[[0]]])
    elif cambio=='calendario_no_bisiesto':r['anio']=2027;kw['anio']=2027
    with pytest.raises(ValueError):anualizar_consumos_lanzaderas(a,r,**kw)


def multi_sources(tmp_path):
    import csv
    template_path,catalog,candidates=car_sources(tmp_path)
    vehicles=[('Passenger Cars',f,s,'Euro 6 d/e') for f,s in [
        ('LPG Bifuel','Small'),('CNG Bifuel','Medium'),('Petrol PHEV','Small'),
        ('Diesel PHEV','Large-SUV-Executive'),('Battery electric','Small')]]
    for path,delimiter in [(catalog,','),(candidates,';')]:
        with path.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f,delimiter=delimiter);w.writerow(['Category','Fuel','Segment','Euro Standard'])
            w.writerows(vehicles)
    return template_path,catalog,candidates,vehicles


def test_multienergy_input_requires_exact_fuels_and_preserves_sources(tmp_path):
    a,b,c,vehicles=multi_sources(tmp_path);before=[file_hash(p) for p in [a,b,c]]
    manifest=prepare_car_reference_case(a,b,c,tmp_path/'multi',speed_kmh=40,primary_fuel_share=.37)
    assert [file_hash(p) for p in [a,b,c]]==before
    assert manifest['configuration']['export_energy_breakdown']
    book=load_workbook(tmp_path/'multi/entrada.xlsx',data_only=True)
    primary=list(book['PRIMARY_FUEL_BIFUEL_SHARE'].values);secondary=list(book['SECONDARY_FUEL_BIFUEL_SHARE'].values)
    assert len(primary)==5 and len(secondary)==5
    assert primary[1][4:]==('LPG','Petrol',.37)
    assert secondary[1][4:]==('LPG','Petrol',.63)
    assert all(row[1]!='Battery electric' for row in primary[1:])
    assert len(list(book['RURAL_LOAD'].values))==1
    book.close()


@pytest.mark.parametrize('fraction',[None,-.1,1.1,float('nan'),True])
def test_multienergy_missing_or_invalid_control_not_adopted(tmp_path,fraction):
    a,b,c,_=multi_sources(tmp_path)
    with pytest.raises(ValueError,match='reparto primario explícito'):
        prepare_car_reference_case(a,b,c,tmp_path/'multi',speed_kmh=40,primary_fuel_share=fraction)
    assert not (tmp_path/'multi').exists()


@pytest.mark.parametrize('change',['grade_label','secondary_fraction','missing_row','repeated_row'])
def test_multienergy_validator_rejects_ignored_labels_and_incoherent_pairs(tmp_path,change):
    a,b,c,vehicles=multi_sources(tmp_path)
    m=prepare_car_reference_case(a,b,c,tmp_path/'multi',speed_kmh=40,primary_fuel_share=.37)
    path=tmp_path/'multi/entrada.xlsx';book=load_workbook(path)
    if change=='grade_label':book['PRIMARY_FUEL_BIFUEL_SHARE']['E2']='LPG Grade 1'
    elif change=='secondary_fraction':book['SECONDARY_FUEL_BIFUEL_SHARE']['G2']=.5
    elif change=='missing_row':book['SECONDARY_FUEL_BIFUEL_SHARE'].delete_rows(2)
    elif change=='repeated_row':book['PRIMARY_FUEL_BIFUEL_SHARE'].append(list(book['PRIMARY_FUEL_BIFUEL_SHARE'].values)[1])
    book.save(path);book.close()
    with pytest.raises(ValueError):validate_car_reference_input(path,vehicles,speed_kmh=40,
        mode_shares={k:.25 for k in CAR_MODES},primary_fuel_share=.37)


def multi_output_files(tmp_path):
    # Caso analítico: Hot10+frío2=total12MJ. El total mezcla7MJ de combustible y5MJ eléctricos.
    vehicle=['Passenger Cars','Petrol PHEV','Small','Euro 6 d/e']
    output=tmp_path/'native.xlsx';breakdown=tmp_path/'breakdown.xlsx'
    book=Workbook();book.active.title='SHEETS';book.active.append(['SHEET_NAME','Unit'])
    for name,emission,mj in [('EC_HOT','Hot',10),('EC_COLD','Cold',2),('EC_TOTAL','Total',12)]:
        book['SHEETS'].append([name,'[TJ]']);s=book.create_sheet(name)
        s.append(['Category','Fuel','Segment','Euro Standard','Emission','Pollutant\n[TJ]','2028_T'])
        s.append([*vehicle,emission,'EC',mj/1e6])
    book.save(output);book.close()
    book=Workbook();book.active.title='SHEETS';book.active.append(['SHEET_NAME','Unit']);book.active.append(['EC_TOTAL','[TJ]'])
    s=book.create_sheet('EC_TOTAL');s.append(['Category','Fuel','Segment','Euro Standard','Fuel Category','Primary Fuel','Emission','Pollutant\n[TJ]','2028_T'])
    for cat,fuel,mj in [('Fossil','Fossil Petrol',7),('Electricity','Electricity',5),('Bio','Bioethanol',0)]:
        s.append([*vehicle,cat,fuel,'Total','EC',mj/1e6])
    book.save(breakdown);book.close()
    return output,breakdown,{'vehicles':[vehicle],'year':2028,'stock_per_category':1,'mean_activity_km':2}


def test_multienergy_breakdown_is_total_with_cold_not_added_to_hot(tmp_path):
    from movilidad_teide.copert_cli import read_car_energy_breakdown
    a,b,c=multi_output_files(tmp_path);result=read_car_energy_breakdown(a,b,c)
    totals=result['checks'][0]
    assert totals['hot_energy_mj']==10 and totals['cold_energy_mj']==2
    assert totals['total_energy_mj']==12
    assert totals['fuel_total_mj']==7 and totals['electricity_total_mj']==5
    assert len(result['components'])==3
    assert sum(x['total_energy_mj_per_km'] for x in result['components'])==6
    assert all('no componente Hot' in x['scope'] for x in result['components'])


@pytest.mark.parametrize('change',['missing_electricity','duplicate_component','unit','negative',
    'missing_value','wrong_indicator','cold_discrepancy','electricity_label'])
def test_multienergy_energy_loss_or_double_count_is_rejected(tmp_path,change):
    from movilidad_teide.copert_cli import read_car_energy_breakdown
    a,b,c=multi_output_files(tmp_path);book=load_workbook(b)
    if change=='missing_electricity':book['EC_TOTAL'].delete_rows(3)
    elif change=='duplicate_component':book['EC_TOTAL'].append(list(book['EC_TOTAL'].values)[1])
    elif change=='unit':book['SHEETS']['B2']='[MJ]'
    elif change=='negative':book['EC_TOTAL']['I2']=-1
    elif change=='missing_value':book['EC_TOTAL']['I2']=None
    elif change=='wrong_indicator':book['EC_TOTAL']['H2']='CO2'
    elif change=='electricity_label':book['EC_TOTAL']['E3']='Fossil'
    book.save(b);book.close()
    if change=='cold_discrepancy':
        book=load_workbook(a);book['EC_COLD']['G2']=3/1e6;book.save(a);book.close()
    with pytest.raises(ValueError):read_car_energy_breakdown(a,b,c)


def multi_library():
    import pandas as pd
    return pd.DataFrame([dict(Category='Passenger Cars',Fuel='Petrol PHEV',Segment='Small',
        **{'Euro Standard':'Euro 6 d/e'},year=2028,driving_mode='rural',speed_kmh=40,
        primary_control_fraction=control,hot_ec_mj_per_km=factor,unit='MJ/km',
        linearity_verified=True,reference_kind='Extremos de control nativo') for control,factor in [(0.,1.),(1.,3.)]])


def test_multienergy_factor_requires_explicit_control_and_exact_speed():
    from movilidad_teide.copert_cli import seleccionar_referencia_multienergia
    lib=multi_library();v=('Passenger Cars','Petrol PHEV','Small','Euro 6 d/e')
    result=seleccionar_referencia_multienergia(lib,v,driving_mode='rural',speed_kmh=40,primary_fuel_share=.37)
    assert result['hot_ec_mj_per_km']==pytest.approx(1.74)
    with pytest.raises(ValueError):seleccionar_referencia_multienergia(lib,v,driving_mode='rural',speed_kmh=40)
    with pytest.raises(ValueError):seleccionar_referencia_multienergia(lib,v,driving_mode='rural',speed_kmh=35,primary_fuel_share=.37)


@pytest.mark.parametrize('change',['missing_endpoint','duplicate','no_verification','bad_unit'])
def test_multienergy_unverified_interpolation_or_ambiguous_factor_is_rejected(change):
    import pandas as pd
    from movilidad_teide.copert_cli import seleccionar_referencia_multienergia
    lib=multi_library();v=('Passenger Cars','Petrol PHEV','Small','Euro 6 d/e')
    if change=='missing_endpoint':lib=lib.iloc[[0]]
    elif change=='duplicate':lib=pd.concat([lib,lib.iloc[[0]]])
    elif change=='no_verification':lib['linearity_verified']=False
    elif change=='bad_unit':lib['unit']='g/km'
    with pytest.raises(ValueError):seleccionar_referencia_multienergia(lib,v,driving_mode='rural',speed_kmh=40,primary_fuel_share=.5)


def test_multienergy_bev_needs_no_bifuel_or_exhaust_mapping():
    from movilidad_teide.copert_cli import seleccionar_referencia_multienergia
    lib=multi_library().iloc[[0]].copy();lib['Fuel']='Battery electric';lib['primary_control_fraction']=float('nan')
    lib['reference_kind']='BEV nativo';lib['hot_ec_mj_per_km']=.6
    v=('Passenger Cars','Battery electric','Small','Euro 6 d/e')
    assert seleccionar_referencia_multienergia(lib,v,driving_mode='rural',speed_kmh=40)['hot_ec_mj_per_km']==.6
    with pytest.raises(ValueError):seleccionar_referencia_multienergia(lib,v,driving_mode='rural',speed_kmh=40,primary_fuel_share=0.)
