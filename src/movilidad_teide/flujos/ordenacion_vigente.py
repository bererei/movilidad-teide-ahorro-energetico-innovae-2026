"""Reproducción de la ordenación vigente desde circulaciones congeladas.

Reconstruye demanda modal y energía y comprueba cada oferta física. No vuelve
a buscar horarios ni presenta la búsqueda previa como un óptimo global.
"""
from pathlib import Path
from types import SimpleNamespace
from collections import Counter
import json, platform, shutil
import numpy as np
import pandas as pd
from movilidad_teide.configuracion.ordenacion import leer_ordenacion, verificar_entradas, POLITICA
from movilidad_teide.trazabilidad import sha256_archivo
from movilidad_teide.energia.titsa import recalcular_titsa,ruta_producto,leer_producto
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.operacion.invierno import limites_llegada_con_luz
from movilidad_teide.demanda.calendario_anual import aplicar_cupo_global
from movilidad_teide.demanda.cabeceras_alternativas import leer_catalogo, PAREJAS
from movilidad_teide.operacion.calendario_vehiculos import materializar_calendario
from .compartida_2028 import BASE, PARADAS
from .operacion_2028 import FUENTES
from .cierre_anual import INVENTARIO, SOLAR


def _leer(path):
    return pd.read_csv(path, sep=';', float_precision='round_trip', low_memory=False)


def _guardar(path, tabla):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(path, sep=';', index=False, float_format='%.17g')


def _json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
        default=lambda x: x.item() if isinstance(x, np.generic) else str(x))+'\n')


class ContextoOrdenacion:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.referencia = leer_ordenacion(self.root)
        self.entradas = verificar_entradas(self.root, self.referencia)
        self.cfg = self.referencia['valores']; self.v = self.referencia['valores_modelo']
        self.captura = self.root/self.referencia['indice']['captura']
        self.energia = self.root/self.referencia['indice']['energia']
        self.excepciones = self.root/self.referencia['indice']['excepciones']
        self.inv = _leer(self.root/INVENTARIO)
        self.red = RedOperativa(_leer(self.root/BASE/'movimientos_diagnosticos.csv'),
            _leer(self.root/BASE/'pares_diagnosticos.csv'), _leer(self.root/PARADAS))
        self.sun = _leer(self.root/SOLAR).groupby('mes').ocaso_min.min().to_dict()
        self.catalogo = leer_catalogo(self.root)
        self.origins = _leer(self.root/FUENTES['origenes'])
        self.hh = _leer(self.root/self.referencia['indice']['demanda_horaria'])
        self.hh = self.hh[self.hh.metodo_calendario.eq('Estacional')].copy()
        self.cal = _leer(self.captura/'calendario.csv')
        self.weights = self.cal.target.value_counts().to_dict()
        self.modales = {}; self.auditorias = []
        if len(self.cal)!=366 or len(self.weights)!=36:
            raise ValueError('Calendario de referencia incompleto.')
        self.visitas_coche_sin_anio = 0.
        for ident in self.weights:
            z = self.modal(self.cfg['cupo_ordinario'],ident,0.)
            self.visitas_coche_sin_anio += float(z['por_origen_dia'].visitas_coche.sum())*self.weights[ident]

    def modal(self, cupo, perfil, incremento):
        key = cupo, perfil, incremento
        if key not in self.modales:
            z,_ = aplicar_cupo_global(self.hh[self.hh.id_perfil.eq(perfil)],self.origins,
                self.v,cupo=int(cupo),incremento=float(incremento))
            self.modales[key] = z
        return self.modales[key]

    def ventana(self, month):
        lim = limites_llegada_con_luz(self.red,self.v,ocaso_min=self.sun[month],
            margen_min=self.cfg['margen_ocaso_min'])
        fin = self.cfg['fin_bases_verano_min'] if 5<=month<=8 else self.cfg['fin_bases_resto_min']
        return lim,fin

    def comprobar_modal(self, r, folder, incremento=0.):
        """Conciliar origen/colectivo, transferencia disponible y cabecera real."""
        z = self.modal(r.cupo,r.perfil,incremento)
        x,pt = _leer(folder/'origenes.csv'), _leer(folder/'objetivos.csv')
        native = z['por_origen_dia']
        cols = list(native.columns)
        pd.testing.assert_frame_equal(x[cols].reset_index(drop=True),native.reset_index(drop=True),
            check_dtype=False,check_exact=False,rtol=0,atol=1e-8)
        tr = _leer(folder/'traslados.csv') if (folder/'traslados.csv').stat().st_size>2 else pd.DataFrame()
        projected = z['escenarios_por_punto_dia'].set_index('punto').demanda_lanzadera_dia.copy()
        if len(tr):
            moved = tr.groupby(['origen_id','colectivo']).visitas_persona_dia.sum()
            eligible = x.set_index(['origen_id','colectivo']).visitas_coche_transferidas_dia
            if (moved-eligible.reindex(moved.index)).gt(1e-8).any():
                raise ValueError('La reasignación excede población elegible de algún origen/colectivo.')
            for t in tr.itertuples():
                if PAREJAS.get(t.punto_original)!=t.punto_reserva or t.punto_regreso!=t.punto_reserva:
                    raise ValueError('Cabecera o regreso no admisibles.')
                projected[t.punto_original]-=t.visitas_persona_dia
                projected[t.punto_reserva]+=t.visitas_persona_dia
                routes=self.catalogo[self.catalogo.origen_id.eq(t.origen_id)]
                np.testing.assert_allclose(routes.km.sum(),t.km_alimentador_nuevo_ida_vuelta,atol=1e-8,rtol=0)
        np.testing.assert_allclose(projected.sort_index(),pt.set_index('punto').demanda_lanzadera_dia.sort_index(),atol=1e-8,rtol=0)
        np.testing.assert_allclose([pt.visitas_sin_dia.sum(),pt.visitas_con_objetivo_dia.sum()],
            [z['escenarios_por_punto_dia'].visitas_sin_dia.sum()]*2,atol=1e-8,rtol=0)
        np.testing.assert_allclose(x.visitas_excursiones_con_intervencion_dia,
            (1+incremento)*x.visitas_excursiones_resto_colectivo,atol=1e-8,rtol=0)
        if x.visitas_excursiones_transferidas_dia.abs().max()>1e-8:
            raise ValueError('Se ha captado población de excursiones en una referencia que la conserva.')
        return x,pt,tr


def _destino_nuevo(root, destino):
    root, destino = Path(root).resolve(), Path(destino).resolve()
    permitida=(root/'data/silver/ejecuciones').resolve()
    propia=(root/'data').resolve().is_relative_to(root) and permitida==root/'data/silver/ejecuciones'
    protegidas=[(root/name).resolve() for name in ['config','src','data','docs','notebooks','tests']]
    if destino==root or (any(destino.is_relative_to(p) for p in protegidas) and not (propia and destino.is_relative_to(permitida))):
        raise ValueError('El destino debe ser independiente de las entradas y del informe.')
    if destino.exists() and any(destino.iterdir()):
        raise FileExistsError('Conservo las ejecuciones: el destino debe estar vacío.')
    destino.mkdir(parents=True,exist_ok=True)
    return destino


def _comparar_json(actual, esperado, nombre):
    if isinstance(esperado, dict):
        if set(actual)!=set(esperado):raise ValueError(f'{nombre}: estructura JSON diferente.')
        for k in esperado:_comparar_json(actual[k],esperado[k],nombre+'/'+k)
    elif isinstance(esperado, list):
        if len(actual)!=len(esperado):raise ValueError(f'{nombre}: lista diferente.')
        for i,(a,b) in enumerate(zip(actual,esperado)):_comparar_json(a,b,nombre+f'/{i}')
    elif isinstance(esperado,(float,int)) and not isinstance(esperado,bool):
        np.testing.assert_allclose(actual,esperado,atol=1e-8,rtol=0,err_msg=nombre)
    elif actual!=esperado:raise ValueError(f'{nombre}: contenido diferente.')


def reproducir_ordenacion(root, destino):
    """Valorar y auditar las ofertas conservadas en una carpeta nueva."""
    destino = _destino_nuevo(root,destino)
    ctx = ContextoOrdenacion(root)
    ctx.factores = _preparar_factores(ctx)
    op = _leer(ctx.captura/'resultados_operacion.csv')
    costs=[]
    for i,r in enumerate(op[op.cierre].itertuples(),1):
        folder=ctx.captura/'ofertas'/str(r.cupo)/str(r.max_programadas)/r.perfil
        costs.extend(_valorar_programa(ctx,r,folder))
        if i%25==0:print(f'Ofertas principales comprobadas: {i}',flush=True)
    _guardar(destino/'energia_por_programa.csv',pd.DataFrame(costs))
    _anualizar_politicas(ctx,destino)
    _materializar_recomendada(ctx,destino)
    acts=_leer(ctx.captura/'sensibilidad_excursiones/actividad_por_programa.csv')
    allcost=[]
    for i,r in enumerate(acts.itertuples(),1):
        folder=ctx.captura/'sensibilidad_excursiones'/str(round(r.incremento_excursiones*100))/('conservada' if r.oferta=='Oferta conservada' else 'ajustada')/r.perfil
        for cc in _valorar_programa(ctx,r,folder,r.incremento_excursiones):
            allcost.append({**cc,'incremento_excursiones':r.incremento_excursiones,
                'oferta':r.oferta,'dias_seleccionados':r.dias})
        if i%36==0:print(f'Ofertas de sensibilidad comprobadas: {i}',flush=True)
    _guardar(destino/'sensibilidad_excursiones/energia_por_programa.csv',pd.DataFrame(allcost))
    _anualizar_sensibilidad(ctx,destino,allcost)
    comparisons=[]
    for name in ctx.referencia['indice']['productos_de_comparacion']:
        actual, esperado = destino/name, ruta_producto(ctx.root,ctx.referencia,name)
        if name.endswith('.csv'):
            a,b=_leer(actual),_leer(esperado)
            pd.testing.assert_frame_equal(a,b,check_dtype=False,check_exact=False,atol=1e-8,rtol=0,obj=name)
            numeric=[]
            for k in b:
                if pd.api.types.is_numeric_dtype(b[k]) and not pd.api.types.is_bool_dtype(b[k]):
                    d=np.abs(pd.to_numeric(a[k]).to_numpy(dtype=float)-pd.to_numeric(b[k]).to_numpy(dtype=float))
                    if np.isfinite(d).any():numeric.append(float(np.nanmax(d)))
            maximum=max(numeric,default=0.)
        else:
            _comparar_json(json.loads(actual.read_text()),json.loads(esperado.read_text()),name)
            maximum=None
        comparisons.append(dict(producto=name,equivalente=True,maxima_diferencia_absoluta=maximum,
            identidad_bytes=sha256_archivo(actual)==sha256_archivo(esperado)))
    cal=_leer(destino/'recomendada_calendario.csv')
    np.testing.assert_allclose(cal.visitas_sin_dia.sum(),ctx.cfg['visitas_anio'],atol=1e-8,rtol=0)
    _guardar(destino/'auditoria_programas.csv',pd.DataFrame(ctx.auditorias))
    _guardar(destino/'comparacion_referencia.csv',pd.DataFrame(comparisons))
    _json(destino/'parametros_efectivos.json',{
        'referencia':'Ordenación recomendada de 2028','elecciones':ctx.referencia['elecciones_vigentes'],
        'valores_modelo':ctx.v,'sha256_libro':ctx.referencia['base']['sha256_libro'],
        'seleccion_historica_conservada':ctx.referencia['base']['caso'],
        'sha256_indice':ctx.referencia['sha256_indice']})
    # También compruebo que ningún archivo de entrada cambió durante la ejecución.
    verificar_entradas(root,ctx.referencia)
    code_root=Path(__file__).parents[1]
    _json(destino/'metadatos.json',{
        'referencia':'Ordenación recomendada de 2028','alcance':ctx.referencia['indice']['alcance'],
        'fecha_referencia':ctx.referencia['indice']['fecha_referencia'],
        'parametros':'parametros_efectivos.json','fuentes_sha256':ctx.entradas,
        'codigo_sha256':{str(p.relative_to(code_root)):sha256_archivo(p) for p in sorted(code_root.rglob('*.py'))},
        'entorno':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__},
        'productos_comparados':len(comparisons),'programas_comprobados':len(ctx.auditorias),
        'fechas':len(cal),'visitas_sin_y_con':ctx.cfg['visitas_anio'],
        'porcentaje_global_ahorro':None,'consumo_comun_absoluto_mwh':None,
        'validacion_institucional_o_extremos_universales':False,
        'salidas_sha256':{str(p.relative_to(destino)):sha256_archivo(p) for p in sorted(destino.rglob('*')) if p.is_file()}})
    return destino,pd.DataFrame(comparisons)


def consultar_ordenacion(root):
    """Consultar salidas selladas; no confundir consulta con nueva reproducción."""
    ref=leer_ordenacion(root);verificar_entradas(root,ref)
    root=Path(root).resolve();c=root/ref['indice']['captura']
    annual=leer_producto(root,ref,'balance_anual_politicas.csv')
    annual=annual[annual.politica.eq(POLITICA)&annual.km_posicionamiento_unidad_activacion.eq(ref['valores']['posicionamiento_km'])]
    daily=leer_producto(root,ref,'actividad_y_energia_diaria_politicas.csv');daily=daily[daily.politica.eq(POLITICA)]
    return {'referencia':ref,'tablas':{
        'central':annual[annual.tratamiento.eq('Hot COPERT')].copy(),
        'fta':annual[annual.tratamiento.ne('Hot COPERT')].copy(),
        'calendario_operativo':leer_producto(root,ref,'recomendada_calendario.csv'),
        'jornadas_vehiculos':leer_producto(root,ref,'recomendada_jornadas_y_sustitucion.csv'),
        'actividad_diaria':daily,
        'sensibilidad_excursiones':leer_producto(root,ref,'sensibilidad_excursiones/balance_anual.csv'),
        'inventario_bases':_leer(root/INVENTARIO),
        'parametros_efectivos':pd.DataFrame(ref['elecciones_vigentes'])}}


def generar_recursos_ordenacion(root,destino):
    """Exportar recursos de la referencia actual sin copiar el maestro v0.14."""
    destino=_destino_nuevo(root,destino)
    data=consultar_ordenacion(root);ref=data['referencia']
    for name,table in data['tablas'].items():_guardar(destino/'anexos'/(name+'.csv'),table)
    _json(destino/'referencia.json',{'nombre':ref['indice']['nombre'],
        'valores':ref['valores'],'parametros':ref['elecciones_vigentes'],
        'sha256_libro':ref['base']['sha256_libro'],'sha256_indice':ref['sha256_indice'],
        'alcance':'Recursos vigentes para integrar en el informe. Maestro y anexos editoriales finales pendientes de actualización.',
        'maestro_anterior_copiado':False,'visitas_sin_y_con':ref['valores']['visitas_anio']})
    (destino/'LEEME.txt').write_text('Recursos de la ordenación recomendada de 2028.\nEsta exportación consulta salidas conservadas y verificadas, no ejecuta de nuevo la reproducción.\nPara reconstruir demanda, comprobar circulaciones y recalcular energía: scripts/reproducir_estudio.py --destino CARPETA_NUEVA.\nEl informe anterior no se copia: su actualización editorial corresponde al siguiente bloque.\n')
    return {'referencia':ref['indice']['nombre'],'visitas_sin_y_con':ref['valores']['visitas_anio'],
        'anexos_csv':len(data['tablas']),'maestro_anterior_copiado':False,'destino':str(destino)}

# INTEGRACION CONSERVADA
# Misma aritmética de los productores de la captura; dependencias y salidas
# explícitas. Los originales permanecen inalterados.


def _preparar_factores(ctx):
    R,E,OLD=ctx.root,ctx.energia,ctx.excepciones
    read=_leer
    coef=read(R/'data/silver/energia/referencias_unitarias/pendiente_turismos/correccion_por_origen_y_rama.csv');coef=coef[coef.caso_pendiente.eq('Referencia del Excel')].copy();coef['unit_mwh']=coef.energia_base_mwh_por_vehiculo_sentido+coef.correccion_mwh_por_vehiculo_sentido;coef=coef.groupby(['alternativa_procedencia','origen_id','colectivo','rama'],as_index=False).unit_mwh.sum()
    common=read(R/'data/silver/energia/excursiones/referencias_por_origen.csv');common=common[['origen_id','colectivo','sentido','longitud_referencia_sentido_km','factor_hot_referencia_mj_km']].drop_duplicates();common['mwh_exc_persona']=common.longitud_referencia_sentido_km*common.factor_hot_referencia_mj_km/3600/ctx.cfg['ocupacion_guagua_aforo'];common=common.groupby(['origen_id','colectivo'],as_index=False).mwh_exc_persona.sum()
    ft=read(E/'alimentacion_coche_TITSA_hipotesis_usuario.csv');ft['mwh_dia']=ft.energia_mwh_anio/ft.peso_dias;ft=ft.groupby(['id_perfil','alternativa_procedencia']).mwh_dia.sum().to_dict()
    ref=getattr(ctx,'referencia',None) or leer_ordenacion(R)
    corrected=recalcular_titsa(R,ref)
    titsa_before=float(corrected.energia_hot_mwh_anio.sum()/366) if corrected is not None else read(E/'TITSA_acceso_sin_oferta_GTFS_referencia_comun.csv').energia_hot_equivalente_mwh_anio.sum()/366
    units=read(OLD/'unidades_alimentadores_excepciones.csv');lookup=units.groupby(['origen_id','grupo_servicio'])[['min_mj','max_mj']].sum()/3600
    factors=read(E/'factores_por_arco_operativo.csv').set_index(['origen','destino','carga_copert']).energia_hot_mj
    empty=read(E/'lanzaderas_resumen_energetico.csv');empty=empty[~empty.componente.eq('comercial')];position_rate=float(empty.hot_mwh_anio.sum()/empty.vehiculo_km_anio.sum())
    return dict(coef=coef,common=common,ft=ft,titsa_before=titsa_before,lookup=lookup,factors=factors,position_rate=position_rate)


def _auditar_oferta(ctx,r,folder,pt):
    red,inv=ctx.red,ctx.inv
    window=ctx.ventana
    month=int(r.perfil.split('_')[1][1:]); max_programadas=int(r.max_programadas)
    c={n:_leer(folder/(n+'.csv')) for n in ['viajes','reservas','movimientos']}
    c['programadas']=c['movimientos'].unidad_fisica_id.nunique()
    if (folder/'inventario_extra.csv').exists(): c['inventario_extra']=_leer(folder/'inventario_extra.csv')
    if c['programadas']!=r.programadas: raise ValueError('Número de identidades distinto al programa.')
    (lim, fin) = window(month)
    (mm, tt, rr) = (c['movimientos'], c['viajes'], c['reservas'])
    assert mm.unidad_fisica_id.nunique() == c['programadas'] <= max_programadas
    assert Counter(mm[mm.componente.eq('comercial')].id_salida) == Counter(tt.id_salida)
    inventory = pd.concat([inv, c.get('inventario_extra', inv.iloc[:0])], ignore_index=True)
    capacities = inventory.groupby('base_red').size().to_dict()
    end = Counter()
    for q in inventory.itertuples():
        z = mm[mm.unidad_fisica_id.eq(q.unidad_fisica_id)].sort_values('salida_min')
        last = q.base_red
        if len(z):
            es = list(z.itertuples())
            assert es[0].origen == q.base_red and es[0].salida_min >= 420 - 1e-08 and (es[-1].llegada_min <= fin + 1e-08)
            last = es[-1].destino
            for (i, e) in enumerate(es):
                route = red.conectar(e.origen, e.destino)
                assert abs(e.llegada_min - e.salida_min - route['minutos']) < 1e-08 and abs(e.km - route['km']) < 1e-08
                if i:
                    assert es[i - 1].destino == e.origen and e.salida_min >= es[i - 1].llegada_min + 10 - 1e-08
        end[last] += 1
    assert end == Counter(capacities)
    physical = len(inventory) if 'inventario_extra' in c else 30 + (2 if max_programadas == 30 else 0)
    assert physical - c['programadas'] >= 2
    assert rr.personas.between(0, 46 + 1e-08).all() and rr.regreso_parque_min.sub(rr.entrada_parque_min).ge(120 - 1e-08).all()
    assert abs(rr.personas.sum() - pt.demanda_lanzadera_dia.sum()) < 1e-08
    trips = tt.set_index('id_salida')
    limit = lim.set_index('punto').limite_llegada_cabecera_min
    for (point, g) in rr.groupby('punto'):
        if len(g) > 1:
            assert np.diff(g.entrada_parque_min.sort_values()).min() >= 15 - 1e-08 and np.diff(g.regreso_parque_min.sort_values()).min() >= 15 - 1e-08
        assert abs(g.personas.sum() - pt[pt.punto.eq(point)].demanda_lanzadera_dia.item()) < 1e-08
        for p in g.itertuples():
            (u, w) = (trips.loc[p.id_subida], trips.loc[p.id_regreso])
            assert u.personas == w.personas == p.personas and u.destino == w.origen == p.parada_destino
            assert u.origen == w.destino == 'cabecera:' + point and w.llegada_min <= limit[point] + 1e-08
    own_end=dict(inv.set_index('unidad_fisica_id').base_red)
    for unit,g in mm.groupby('unidad_fisica_id'):
        if unit in own_end:own_end[unit]=g.sort_values('salida_min').iloc[-1].destino
    if Counter(own_end.values())!=Counter(inv.base_red):raise ValueError('El stock propio no cierra por separado de apoyos.')
    ctx.auditorias.append(dict(perfil=r.perfil,cupo=r.cupo,max_programadas=max_programadas,programadas=c['programadas'],movimientos=len(mm),cierre=True))
    return mm



def _valorar_programa(ctx,r,folder,incremento=0.):
    coef,common,ft,titsa_before,lookup,factors,position_rate=[ctx.factores[k] for k in ['coef','common','ft','titsa_before','lookup','factors','position_rate']]
    red,weights=ctx.red,ctx.weights
    x,pt,tr=ctx.comprobar_modal(r,folder,incremento)
    m=_auditar_oferta(ctx,r,folder,pt)
    rows=[];missing=[]
    xx = x.merge(common, on=['origen_id', 'colectivo'], validate='one_to_one')
    bus = []
    for (comp, mm) in m.groupby('componente'):
        energy = sum((len(g) * sum((factors.loc[a, b, 0.5 if comp == 'comercial' else 0.0] for (a, b) in red.conectar(u, w)['arcos'])) for ((u, w), g) in mm.groupby(['origen', 'destino']))) / 3600
        bus.append((comp, energy))
    commercial = sum((v for (k, v) in bus if k == 'comercial'))
    vacant = sum((v for (k, v) in bus if k != 'comercial'))
    for alt in ['España no Tenerife: alquiler', 'España no Tenerife: particular']:
        rates = coef[coef.alternativa_procedencia.eq(alt)].pivot(index=['origen_id', 'colectivo'], columns='rama', values='unit_mwh')
        z = xx.join(rates, on=['origen_id', 'colectivo'], validate='one_to_one')
        assert z[['antes', 'autorizados', 'transferidos', 'alimentacion_otros']].notna().all().all()
        before_car = float((z.coches_sin_dia * z.antes).sum())
        car = float((z.coches_autorizados_dia * z.autorizados).sum())
        feed = float((z.visitas_coche_transferidas_dia / ctx.cfg['ocupacion_coche'] * z.transferidos).sum())
        other = float((z.visitas_excursiones_transferidas_dia * z.alimentacion_otros).sum())
        assert abs(other) < 1e-10
        exc_before = float((z.visitas_excursiones_resto_colectivo * z.mwh_exc_persona).sum())
        exc = float((z.visitas_excursiones_con_intervencion_dia * z.mwh_exc_persona).sum())
        np.testing.assert_allclose(exc_before*(1+incremento), exc, atol=1e-08, rtol=0)
        old = lo = hi = 0.0
        unresolved = []
        for t in tr.itertuples():
            n = t.visitas_persona_dia / ctx.cfg['ocupacion_coche']
            old += float(rates.loc[t.origen_id, t.colectivo]['transferidos']) * n
            service = 'Alquiler sin conductor (A01)' if t.colectivo == 'extranjero' or (t.colectivo == 'espana_no_tenerife' and 'alquiler' in alt) else 'Particular sin especificar (B00)'
            if (t.origen_id, service) not in lookup.index:
                unresolved.append(t.origen_id)
                continue
            row = lookup.loc[t.origen_id, service]
            lo += float(row.min_mj) * n
            hi += float(row.max_mj) * n
        if unresolved:
            missing.extend(({'cupo': r.cupo, 'max_programadas': r.max_programadas, 'perfil': r.perfil, 'origen_id': o, 'asignacion': alt} for o in unresolved))
        sin = before_car + exc_before + titsa_before
        feed_titsa = float(ft[r.perfil, alt])
        conmin = car + feed - old + lo + other + exc + feed_titsa + commercial + vacant
        conmax = car + feed - old + hi + other + exc + feed_titsa + commercial + vacant
        if unresolved:
            conmin = conmax = np.nan
        rows.append({'cupo': r.cupo, 'max_programadas': r.max_programadas, 'perfil': r.perfil, 'dias': weights[r.perfil], 'asignacion_turismos': alt, 'sin_coche_mwh_dia': before_car, 'sin_excursion_mwh_dia': exc_before, 'sin_TITSA_mwh_dia': titsa_before, 'con_coche_mwh_dia': car, 'con_alimentador_habitual_mwh_dia': feed, 'alimentador_antiguo_retirado_mwh_dia': old, 'alimentador_nuevo_min_mwh_dia': lo, 'alimentador_nuevo_max_mwh_dia': hi, 'con_alimentador_otro_colectivo_mwh_dia': other, 'con_alimentador_TITSA_mwh_dia': feed_titsa, 'con_excursion_mwh_dia': exc, 'con_lanzadera_comercial_mwh_dia': commercial, 'con_lanzadera_vacia_mwh_dia': vacant, 'sin_mwh_dia': sin, 'con_min_mwh_dia_sin_posicionamiento': conmin, 'con_max_mwh_dia_sin_posicionamiento': conmax, 'visitas_sin_dia': float(pt.visitas_sin_dia.sum()), 'visitas_coche_dia': float(pt.visitas_coche_autorizadas_dia.sum()), 'visitas_excursion_dia': float(pt.visitas_excursiones_con_intervencion_dia.sum()), 'visitas_lanzadera_dia': float(pt.demanda_lanzadera_dia.sum()), 'expediciones_comerciales': int(m.componente.eq('comercial').sum()), 'movimientos_vacios': int(m.componente.ne('comercial').sum()), 'km_comerciales': float(m.loc[m.componente.eq('comercial'), 'km'].sum()), 'km_vacios': float(m.loc[m.componente.ne('comercial'), 'km'].sum()), 'externas_disponibles': 2 if r.max_programadas == 30 else 0, 'programadas': r.programadas})
    if missing:raise ValueError(f"Alimentadores sin energía: {missing}")
    return rows


def _anualizar_politicas(ctx,destino):
    O=Path(destino)
    def rd(n):return _leer((O/(n+'.csv')) if (O/(n+'.csv')).exists() else ctx.captura/(n+'.csv'))
    def save(n,t):return _guardar(O/(n+'.csv'),t)
    op=rd('resultados_operacion');op=op[op.cierre].copy();cost=rd('energia_por_programa');cal=rd('calendario');needed=rd('condiciones_necesarias').set_index(['cupo','perfil']);rate=ctx.factores['position_rate']
    definitions=[]
    for q in [650,700,750]:
     definitions.extend([(f'Cupo fijo de {q}; hasta 28 en punta sin apoyos',q,'propias'),(f'Cupo fijo de {q}; hasta 30 en punta con apoyos',q,'apoyos')])
    definitions.extend([('Cupo desde 650; priorizar dotación propia',650,'adaptativa_propias'),('Cupo desde 650; priorizar menor cupo',650,'adaptativa_cupo')])
    annual=[];services=[];daily=[];calendar_export=[]
    for name,base,mode in definitions:
     picks=[];absent=[]
     for d in cal.itertuples():
      options=op[op.perfil.eq(d.target)].copy()
      if mode in ['propias','apoyos']:options=options[options.cupo.eq(base)]
      if mode=='propias':options=options[options.max_programadas.le(28)]
      if options.empty:absent.append(d.fecha);continue
      order=['externas_disponibles','cupo','programadas','max_programadas'] if mode=='adaptativa_propias' else ['cupo','externas_disponibles','programadas','max_programadas']
      row=options.sort_values(order,kind='stable').iloc[0]
      regime='Ordinaria' if row.programadas<=27 and row.externas_disponibles==0 and row.cupo==base else 'Punta'
      key=(int(row.cupo),int(row.max_programadas),d.target)
      records=cost[(cost.cupo.eq(key[0]))&(cost.max_programadas.eq(key[1]))&cost.perfil.eq(key[2])];assert len(records)==2
      pick={'politica':name,'fecha':d.fecha,'perfil':d.target,'cupo':key[0],'max_programadas_programa':key[1],'regimen':regime,'programadas':int(row.programadas),'externas_disponibles':int(row.externas_disponibles),'externas_programadas':int(row.externas_programadas),'sin_programar':30+int(row.externas_disponibles)-int(row.programadas),'visitas_reasignadas_cabecera':row.visitas_reasignadas_dia}
      first=records.iloc[0]
      pick.update({k:first[k] for k in ['visitas_sin_dia','visitas_coche_dia','visitas_excursion_dia','visitas_lanzadera_dia','expediciones_comerciales','movimientos_vacios','km_comerciales','km_vacios']});picks.append(pick)
      for r in records.to_dict('records'):daily.append({**pick,**r})
     calendar_export.extend(picks)
     full=len(picks)==366
     planned=sum(float(needed.loc[(base,d.target)].visitas_sin) for d in cal.itertuples());np.testing.assert_allclose(planned,2500000,atol=1e-8,rtol=0)
     p=pd.DataFrame(picks);source=dict(politica=name,cupo_ordinario=base,modalidad=mode,cierre_anual=full,visitas_objetivo_sin_y_con=2500000,dias_sin_oferta=len(absent),dias_con_oferta=len(picks),dias_ordinarios=int(p.regimen.eq('Ordinaria').sum()),dias_punta=int(p.regimen.eq('Punta').sum()),cupo_maximo_ensayado=int(p.cupo.max()),programadas_ordinaria_max=float(p.loc[p.regimen.eq('Ordinaria'),'programadas'].max()),programadas_punta_max=float(p.loc[p.regimen.eq('Punta'),'programadas'].max()),sustitutas_ordinaria_min=float(p.loc[p.regimen.eq('Ordinaria'),'sin_programar'].min()),sustitutas_punta_min=float(p.loc[p.regimen.eq('Punta'),'sin_programar'].min()),apoyos_unidades_dia=int(p.externas_disponibles.sum()),apoyos_programados_unidades_dia=int(p.externas_programadas.sum()),visitas_en_fechas_pendientes=planned-float(p.visitas_sin_dia.sum()))
     for col in ['visitas_coche_dia','visitas_excursion_dia','visitas_lanzadera_dia','expediciones_comerciales','movimientos_vacios','km_comerciales','km_vacios','visitas_reasignadas_cabecera']:source[col.replace('_dia','')+'_anio']=float(p[col].sum()) if full else np.nan
     if full:
      np.testing.assert_allclose([p.visitas_sin_dia.sum(),p[['visitas_coche_dia','visitas_excursion_dia','visitas_lanzadera_dia']].sum().sum()],[2500000,2500000],atol=1e-8,rtol=0)
      source['entradas_coches_anio']=float(p.visitas_coche_dia.sum()/3.2);source['pasajeros_por_expedicion_lanzadera']=float(2*p.visitas_lanzadera_dia.sum()/p.expediciones_comerciales.sum());source['ocupacion_diseno_pct']=source['pasajeros_por_expedicion_lanzadera']/46*100;source['ocupacion_nominal_pct']=source['pasajeros_por_expedicion_lanzadera']/55*100
     services.append(source)
     dd=pd.DataFrame([x for x in daily if x['politica']==name])
     for alt,g in dd.groupby('asignacion_turismos'):
      for km in [0,50,100]:
       position=float(g.externas_disponibles.sum()*km*rate)
       for treatment in ['Hot COPERT','Contraste FTA lanzaderas y posicionamiento']:
        correction=0. if treatment=='Hot COPERT' else float((g.con_lanzadera_comercial_mwh_dia.sum()+g.con_lanzadera_vacia_mwh_dia.sum()+position)/9)
        sin=float(g.sin_mwh_dia.sum()) if full else np.nan;lo=float(g.con_min_mwh_dia_sin_posicionamiento.sum()+position+correction) if full and g.con_min_mwh_dia_sin_posicionamiento.notna().all() else np.nan;hi=float(g.con_max_mwh_dia_sin_posicionamiento.sum()+position+correction) if full and g.con_max_mwh_dia_sin_posicionamiento.notna().all() else np.nan
        r={**source,'asignacion_turismos':alt,'tratamiento':treatment,'km_posicionamiento_unidad_activacion':km,'sin_identificado_mwh':sin,'con_identificado_min_mwh':lo,'con_identificado_max_mwh':hi,'ahorro_min_mwh':sin-hi,'ahorro_max_mwh':sin-lo,'ahorro_min_tep':(sin-hi)/11.63,'ahorro_max_tep':(sin-lo)/11.63,'con_min_kwh_visita':lo/2500,'con_max_kwh_visita':hi/2500,'ahorro_min_kwh_visita':(sin-hi)/2500,'ahorro_max_kwh_visita':(sin-lo)/2500,'posicionamiento_mwh':position if full else np.nan,'consumo_comun_absoluto_mwh':np.nan,'porcentaje_global_ahorro':np.nan};annual.append(r)
    save('calendarios_politicas',pd.DataFrame(calendar_export))
    save('actividad_y_energia_diaria_politicas',pd.DataFrame(daily));save('servicios_anuales_politicas',pd.DataFrame(services));aa=pd.DataFrame(annual);save('balance_anual_politicas',aa)
    primary=aa[(aa.tratamiento.eq('Hot COPERT'))&aa.km_posicionamiento_unidad_activacion.eq(100)];summary=primary.groupby('politica',sort=False).agg(cierre_anual=('cierre_anual','first'),dias_sin_oferta=('dias_sin_oferta','first'),dias_punta=('dias_punta','first'),cupo_maximo=('cupo_maximo_ensayado','first'),apoyos_unidades_dia=('apoyos_unidades_dia','first'),ahorro_min_tep=('ahorro_min_tep','min'),ahorro_max_tep=('ahorro_max_tep','max'),consumo_min_mwh=('con_identificado_min_mwh','min'),consumo_max_mwh=('con_identificado_max_mwh','max')).reset_index();save('resumen_politicas',summary)



def _materializar_recomendada(ctx,destino):
    O=Path(destino);R=ctx.root
    rd=_leer
    def save(n,t):return _guardar(O/(n+'.csv'),t)
    policy='Cupo desde 650; priorizar dotación propia';cal=rd(O/'calendarios_politicas.csv');cal=cal[cal.politica.eq(policy)].copy().sort_values('fecha');assert len(cal)==366
    inv=rd(R/INVENTARIO);initial=inv.set_index('unidad_fisica_id').base_red.to_dict();assert len(initial)==30
    movs=[];available=[];resumen=[];visits=[]
    for key,g in cal.groupby(['cupo','max_programadas_programa','perfil']):
     q,mx,p=key;folder=ctx.captura/'ofertas'/str(q)/str(mx)/p;m=rd(folder/'movimientos.csv');rr=rd(folder/'reservas.csv');pt=rd(folder/'objetivos.csv');ident=f'Q{q}_L{mx}_{p}'
     assert set(m.unidad_fisica_id).issubset(initial),'La solución recomendada programa solo las treinta propias; los apoyos son sustitución.'
     movs.append(m.assign(id_perfil=ident,metodo_calendario='Ordenación contrastada',margen_min=30));visits.append(rr.assign(id_perfil=ident))
     for z in inv.itertuples():
      mm=m[m.unidad_fisica_id.eq(z.unidad_fisica_id)].sort_values('salida_min');end=mm.iloc[-1].destino if len(mm) else z.base_red
      available.append({'id_perfil':ident,'margen_min':30,'unidad_fisica_id':z.unidad_fisica_id,'programada':not mm.empty,'base_inicial':z.base_red,'base_final':end})
     month=int(p.split('_')[1][1:]);resumen.append({'id_perfil':ident,'metodo_calendario':'Ordenación contrastada','margen_min':30,'ambito':'Calendario','cierre':True,'demanda_lanzadera_personas_dia':float(pt.demanda_lanzadera_dia.sum()),'fin_bases_permitido_min':1290 if 5<=month<=8 else 1200})
    cal['id_perfil']=[f'Q{t.cupo}_L{t.max_programadas_programa}_{t.perfil}' for t in cal.itertuples()];cal['metodo_calendario']='Ordenación contrastada'
    out=materializar_calendario(cal,pd.DataFrame(resumen),pd.concat(movs,ignore_index=True),pd.DataFrame(available),inv,max_programadas=30)
    for name,t in out.items():save('recomendada_'+name,t)
    j=out['jornadas_calendario'].merge(cal[['fecha','regimen','cupo','externas_disponibles']],on='fecha',validate='one_to_one');j['sustitutas_incluidos_apoyos']=j.sin_programar+j.externas_disponibles
    assert j[j.regimen.eq('Ordinaria')].programadas.le(27).all() and j[j.regimen.eq('Ordinaria')].sustitutas_incluidos_apoyos.ge(3).all()
    assert j[j.regimen.eq('Punta')].programadas.le(30).all() and j[j.regimen.eq('Punta')].sustitutas_incluidos_apoyos.ge(2).all()
    assert len(j)==366 and out['disponibilidad_calendario'].shape[0]==366*30
    states=out['disponibilidad_calendario']
    for _,g in states.groupby('fecha'):assert Counter(g.base_final)==Counter(initial.values())
    m=out['movimientos_calendario'];np.testing.assert_allclose(m.km.sum(),cal.km_comerciales.sum()+cal.km_vacios.sum(),atol=1e-7,rtol=0)
    for t in j.itertuples():
     z=m[m.fecha.eq(t.fecha)];assert z.unidad_fisica_id.nunique()==t.programadas
     for unit,g in z.groupby('unidad_fisica_id'):
      g=g.sort_values('salida_min');assert g.salida_min.min()>=420-1e-8 and g.llegada_min.max()<=t.fin_bases_permitido_min+1e-8
      assert (g.salida_min.to_numpy()[1:]-g.llegada_min.to_numpy()[:-1]>=10-1e-8).all()
    save('recomendada_jornadas_y_sustitucion',j);save('recomendada_reservas_por_programa',pd.concat(visits,ignore_index=True));save('recomendada_calendario',cal)
    annual=rd(O/'balance_anual_politicas.csv');annual=annual[annual.politica.eq(policy)];svc=rd(O/'servicios_anuales_politicas.csv');svc=svc[svc.politica.eq(policy)].iloc[0].to_dict()
    main=annual[annual.tratamiento.eq('Hot COPERT')&annual.km_posicionamiento_unidad_activacion.eq(100)];fta=annual[annual.tratamiento.ne('Hot COPERT')&annual.km_posicionamiento_unidad_activacion.eq(100)]
    def bounds(g):return {'sin_mwh_min':float(g.sin_identificado_mwh.min()),'sin_mwh_max':float(g.sin_identificado_mwh.max()),'con_mwh_min':float(g.con_identificado_min_mwh.min()),'con_mwh_max':float(g.con_identificado_max_mwh.max()),'ahorro_tep_min':float(g.ahorro_min_tep.min()),'ahorro_tep_max':float(g.ahorro_max_tep.max()),'ahorro_mwh_min':float(g.ahorro_min_mwh.min()),'ahorro_mwh_max':float(g.ahorro_max_mwh.max()),'con_kwh_visita_min':float(g.con_min_kwh_visita.min()),'con_kwh_visita_max':float(g.con_max_kwh_visita.max()),'ahorro_kwh_visita_min':float(g.ahorro_min_kwh_visita.min()),'ahorro_kwh_visita_max':float(g.ahorro_max_kwh_visita.max())}
    result={'fecha':'2026-11-10','politica_recomendada':policy,'criterio':'Primero soluciones que utilizan las treinta propias; entre ellas el menor cupo ensayado. Apoyos solo donde ninguna solución de dotación propia hasta750 coches cierra. No mínimo global demostrado.','visitas_sin_y_con':2500000,'crecimiento_excursiones':0,'intercambios_compensados_de_excursion':False,'cupo_ordinario':650,'cupo_punta_ensayado':[650,700,750],'max_programadas_ordinaria':27,'max_programadas_punta':30,'min_sustitutas_ordinaria':3,'min_sustitutas_punta':2,'servicios':svc,'dias_por_cupo':{str(int(k)):int(v) for k,v in cal.groupby('cupo').size().items()},'dias_por_regimen_programadas':cal.groupby(['regimen','programadas']).size().rename('dias').reset_index().to_dict('records'),'Hot':bounds(main),'FTA':bounds(fta),'reduccion_entradas_privadas_pct':100*(1-svc['entradas_coches_anio']/(ctx.visitas_coche_sin_anio/ctx.cfg['ocupacion_coche'])),'continuidad_366_fechas_y_30_identidades':True,'apoyos_disponibles_no_programados':int(svc['apoyos_programados_unidades_dia'])==0,'posicionamiento_hipotesis_km_unidad_activacion':100,'limites':'Oferta modelizada; demanda de planificación de366 fechas, no garantía universal de extremos o autorización real. Hot identificado y consumo común pendiente.'}
    _json(O/'recomendacion.json',result)



def _anualizar_sensibilidad(ctx,destino,allcost):
    SO=Path(destino)/'sensibilidad_excursiones';SO.mkdir(exist_ok=True)
    save=_guardar
    rate=ctx.factores['position_rate']
    annual=[]
    for (inc,offer,alt),g in pd.DataFrame(allcost).groupby(['incremento_excursiones','oferta','asignacion_turismos'],sort=False):
     w=g.dias_seleccionados
     assert w.sum()==366
     total=lambda col:float((g[col]*w).sum())
     np.testing.assert_allclose([total('visitas_sin_dia'),sum(total(k) for k in ['visitas_coche_dia','visitas_excursion_dia','visitas_lanzadera_dia'])],[2500000,2500000],atol=1e-8,rtol=0)
     position=total('externas_disponibles')*100*rate
     for method in ['Hot COPERT','Contraste FTA lanzaderas y posicionamiento']:
      correction=0 if method=='Hot COPERT' else (total('con_lanzadera_comercial_mwh_dia')+total('con_lanzadera_vacia_mwh_dia')+position)/9
      sin=total('sin_mwh_dia');lo=total('con_min_mwh_dia_sin_posicionamiento')+position+correction;hi=total('con_max_mwh_dia_sin_posicionamiento')+position+correction
      annual.append({'incremento_excursiones':inc,'oferta':offer,'asignacion_turismos':alt,'tratamiento':method,'visitas':2500000,'visitas_coche':total('visitas_coche_dia'),'visitas_excursion':total('visitas_excursion_dia'),'visitas_lanzadera':total('visitas_lanzadera_dia'),'expediciones':total('expediciones_comerciales'),'vacios':total('movimientos_vacios'),'km_comerciales':total('km_comerciales'),'km_vacios':total('km_vacios'),'apoyos_unidades_dia':total('externas_disponibles'),'ocupacion_diseno_pct':total('visitas_lanzadera_dia')*2/total('expediciones_comerciales')/46*100,'sin_mwh':sin,'con_min_mwh':lo,'con_max_mwh':hi,'ahorro_min_mwh':sin-hi,'ahorro_max_mwh':sin-lo,'ahorro_min_tep':(sin-hi)/11.63,'ahorro_max_tep':(sin-lo)/11.63,'con_min_kwh_visita':lo/2500,'con_max_kwh_visita':hi/2500,'ahorro_min_kwh_visita':(sin-hi)/2500,'ahorro_max_kwh_visita':(sin-lo)/2500})
    a=pd.DataFrame(annual);save(SO/'balance_anual.csv',a)
    summary=a.groupby(['incremento_excursiones','oferta','tratamiento'],sort=False).agg(ahorro_min_tep=('ahorro_min_tep','min'),ahorro_max_tep=('ahorro_max_tep','max'),visitas_excursion=('visitas_excursion','first'),visitas_lanzadera=('visitas_lanzadera','first'),expediciones=('expediciones','first'),ocupacion_diseno_pct=('ocupacion_diseno_pct','first'),apoyos_unidades_dia=('apoyos_unidades_dia','first')).reset_index()
    save(SO/'resumen.csv',summary)
