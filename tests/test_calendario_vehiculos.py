"""No cuento dos guaguas distintas al enlazar plantillas de días sucesivos."""
import pandas as pd
import pytest
from movilidad_teide.operacion.calendario_vehiculos import materializar_calendario


def caso():
    inventario=pd.DataFrame([{'unidad_fisica_id':f'{b}{i:02d}','base_red':b} for b in ['A','B'] for i in range(15)])
    cal=pd.DataFrame([{'fecha':f'2028-01-{d:02d}','metodo_calendario':'Estacional','id_perfil':'P'} for d in [1,2]])
    res=pd.DataFrame([{'ambito':'Calendario','metodo_calendario':'Estacional','margen_min':30,'id_perfil':'P','cierre':True,
                      'demanda_lanzadera_personas_dia':90.,'fin_bases_permitido_min':1200}])
    moves=pd.DataFrame([{'id_perfil':'P','margen_min':30,'unidad_fisica_id':u,'origen':a,'destino':b,
        'salida_min':480.,'llegada_min':540.,'familia':'Control','id_salida':u+'_viaje'} for u,a,b in [('A00','A','B'),('B00','B','A')]])
    av=inventario.rename(columns={'base_red':'base_inicial'}).assign(id_perfil='P',margen_min=30)
    av['base_final']=av.base_inicial;av['programada']=av.unidad_fisica_id.isin(['A00','B00'])
    av.loc[av.unidad_fisica_id.eq('A00'),'base_final']='B';av.loc[av.unidad_fisica_id.eq('B00'),'base_final']='A'
    return cal,res,moves,av,inventario


def test_las_unidades_intercambiadas_parten_de_su_posicion_real_al_dia_siguiente():
    result=materializar_calendario(*caso(),max_programadas=28)
    estados=result['disponibilidad_calendario'];moves=result['movimientos_calendario']
    assert len(estados)==60 and estados.groupby('fecha').unidad_fisica_id.nunique().eq(30).all()
    inicio=estados[estados.fecha.eq('2028-01-02')].set_index('unidad_fisica_id').base_inicial.sort_index()
    final=estados[estados.fecha.eq('2028-01-01')].set_index('unidad_fisica_id').base_final.sort_index()
    pd.testing.assert_series_equal(inicio,final,check_names=False)
    segundo=moves[moves.fecha.eq('2028-01-02')].set_index('unidad_fisica_id_plantilla').unidad_fisica_id.to_dict()
    assert segundo=={'A00':'B00','B00':'A00'}
    assert result['jornadas_calendario'].programadas.eq(2).all()


def test_no_reubico_una_reserva_sin_un_recorrido():
    cal,res,m,av,inv=caso()
    av.loc[av.unidad_fisica_id.eq('A01'),'base_final']='B'
    av.loc[av.unidad_fisica_id.eq('B01'),'base_final']='A'
    with pytest.raises(ValueError,match='reserva cambia de base'):
        materializar_calendario(cal,res,m,av,inv,max_programadas=28)


def test_un_calendario_pendiente_no_genera_circulaciones_ficticias():
    cal,res,m,av,inv=caso();res['cierre']=False
    result=materializar_calendario(cal,res,m,av,inv,max_programadas=28)
    assert all(t.empty for t in result.values())
