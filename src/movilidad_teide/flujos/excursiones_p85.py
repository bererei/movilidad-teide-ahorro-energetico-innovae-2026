"""Contrasto hasta quince por ciento de excursiones con ocho perfiles y p85."""
from pathlib import Path
import json, math, platform
import numpy as np
import pandas as pd
from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.demanda.ajuste_invierno import limites_cuotas
from movilidad_teide.demanda.excursiones_acotadas import reasignar_con_maximos, p85_afin_comprobado
from movilidad_teide.demanda.p85_alternativas import cambiar_fechas_muestra
from movilidad_teide.operacion.contraste_excursiones import BuscadorConMuestra
from movilidad_teide.operacion.equilibrio_invierno import BuscadorEquilibrado
from movilidad_teide.operacion.invierno import limites_llegada_con_luz
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.trazabilidad import sha256_archivo
from .ajuste_invierno import ANTERIOR, REFERENCIA, MUESTRA, CRITICOS, CUOTAS_PREVIAS
from .compartida_2028 import BASE, PARADAS
from .operacion_2028 import FUENTES
from .redistribucion_2028 import Q15
from .tipos import Etapa

SALIDAS = 'data/silver/movilidad/excursiones_p85_2028'
MESES = {5: 12, 6: 12, 7: 12, 20: 2, 21: 2, 22: 2, 23: 2, 29: 11}


def preparar_excursiones_p85(root, *, estados=5000, pasos=1800):
    root = Path(root).resolve()
    rd = lambda p: pd.read_csv(root / p, sep=';', float_precision='round_trip')
    paths = [ANTERIOR + '/' + n for n in ['observaciones_diarias.csv', 'origenes_muestra.csv', 'inventario_30.csv', 'metadatos.json']]
    paths += [REFERENCIA + '/referencia_solar_2028.csv', FUENTES['indices'], BASE + '/movimientos_diagnosticos.csv', BASE + '/pares_diagnosticos.csv', PARADAS, 'config/parametros_modelo.xlsx']
    fuentes = {p: sha256_archivo(root / p) for p in paths}
    params = leer_parametros(root)
    v = {p['id']: p['valor_utilizado'] for p in params['parametros']}
    if (v['cupo_global'] != 500 or v['vehiculos_contrato_contraste'] != 30 or v['reserva_minima_dentro_flota'] != 3
            or v['intervalo_refuerzo_punta_min'] != 15 or int(v['plazas_guagua'] * v['ocupacion_diseno']) != 46
            or v['estancia_min_visita_min'] != 120 or v['regulacion_min'] != 10):
        raise ValueError('Conservar las condiciones del libro; las alternativas se registran fuera de él.')
    v = {**v, 'hora_inicio_acceso': 7.}
    d = rd(ANTERIOR + '/observaciones_diarias.csv')
    d = d.loc[d.alternativa.eq('P20') & d.referencia_festivos.eq('Domingo') & d.cumplimiento_cambio_fecha.eq(0)].copy()
    x = rd(ANTERIOR + '/origenes_muestra.csv')
    x = x.loc[x.alternativa.eq('P20') & x.cumplimiento_cambio_fecha.eq(0)].copy()
    ox = {int(o): g for o, g in x.groupby('matrix_index')}
    puntos = {int(o): g for o, g in d.groupby('matrix_index')}
    if set(puntos) != set(range(57)) or set(ox) != set(puntos):
        raise ValueError('Se requieren las 57 referencias completas, sin retirar perfiles.')
    red = RedOperativa(rd(BASE + '/movimientos_diagnosticos.csv'), rd(BASE + '/pares_diagnosticos.csv'), rd(PARADAS))
    inv = rd(ANTERIOR + '/inventario_30.csv')
    ids = inv.groupby('base_red').unidad_fisica_id.apply(list).to_dict()
    caps = {b: len(i) for b, i in ids.items()}
    solar = rd(REFERENCIA + '/referencia_solar_2028.csv')
    sun = solar.groupby('mes').ocaso_min.min().to_dict()
    indices = rd(FUENTES['indices'])
    bus = BuscadorConMuestra(max_estados=estados, pasos=pasos, configuraciones_refinadas=3)
    filtro = BuscadorConMuestra(max_estados=estados, pasos=pasos, configuraciones_refinadas=3)
    filtro.exigir_muestra = False
    bus.cache = filtro.cache
    tables, searches, syn = {}, [], []

    def add(name, frame, **tag):
        if frame is not None and not frame.empty:
            tables.setdefault(name, []).append(frame.assign(**tag))

    def guardar_cierre(z, tag, demanda, lim):
        if z is None:
            return
        if abs(z['reservas'].personas.sum() - demanda) > 1e-8:
            raise ValueError('El cierre pierde visitas-persona.')
        commercial = z['viajes'].loc[z['viajes'].destino.str.startswith('cabecera:')]
        if commercial.llegada_min.max() > lim.limite_llegada_cabecera_min.iloc[0] + 1e-8:
            raise ValueError('Se rebasa la llegada comercial permitida.')
        for name, key in [('cronologias', 'viajes'), ('reservas', 'reservas'), ('movimientos', 'movimientos')]:
            add(name, z[key], **tag)
        disp = []
        for unit in inv.itertuples():
            mm = z['movimientos'].loc[lambda a: a.unidad_fisica_id.eq(unit.unidad_fisica_id)].sort_values('salida_min')
            if not mm.empty and mm.iloc[0].origen != unit.base_red:
                raise ValueError('Una unidad parte de otra base.')
            disp.append({'unidad_fisica_id': unit.unidad_fisica_id, 'programada': not mm.empty,
                         'base_inicial': unit.base_red, 'base_final': mm.iloc[-1].destino if not mm.empty else unit.base_red})
        add('disponibilidad_30', pd.DataFrame(disp), **tag)

    for cupo in [600, 625, 650]:
        for margen in [15, 30]:
            # Solo escalo el cupo si ningún porcentaje resolvió ese margen.
            if any(z['margen_min'] == margen and z['cierre_conjunto'] for z in syn):
                continue
            lim = {o: limites_llegada_con_luz(red, v, ocaso_min=float(sun[MESES[o]]), margen_min=margen) for o in MUESTRA}
            lim[85] = limites_llegada_con_luz(red, v, ocaso_min=float(solar.ocaso_min.min()), margen_min=margen)
            for rate in [.15, .125, .10]:
                case = f'C{cupo}_E{rate*100:g}_M{margen}'
                tag = {'caso': case, 'cupo_global_coches_dia': cupo, 'incremento_excursiones_sobre_sin': rate, 'margen_min': margen}
                print(f'Inicio {case}: búsqueda conjunta, hasta {estados} estados.', flush=True)
                maximos = pd.concat([limites_cuotas(ox[o], rate, ocupacion=v['ocupacion_coche']) for o in CRITICOS], axis=1).min(axis=1)
                bounds = {p: min(math.floor(maximos[p]), math.floor(650 * CUOTAS_PREVIAS[p] / 550 * 1.75)) for p in red.puntos}
                p85bruto, control = p85_afin_comprobado(ox, d, incremento=rate, ocupacion=v['ocupacion_coche'], cupo_maximo=bounds)
                add('comprobacion_p85_afin', control, **tag)
                datos = {o: puntos[o][['punto']].assign(demanda_bruta_lanzadera_dia=puntos[o].visitas_coche + puntos[o].visitas_titsa - rate * puntos[o].visitas_excursiones_resto_colectivo) for o in CRITICOS}
                datos[85] = p85bruto
                bus.configurar(ox, {o: puntos[o] for o in MUESTRA}, lim, rate)
                filtro.configurar(ox, {o: puntos[o] for o in MUESTRA}, lim, rate)
                entry, closed, log, ref, pref = filtro({85:p85bruto}, {85:lim[85]}, maximos, red, v, caps, ids,
                    cupo=cupo, cuota_previa=CUOTAS_PREVIAS, semilla=248000 + cupo + int(1000*rate) + margen)
                add('busqueda_cuotas', log, fase='Filtro p85', **tag)
                add('refinamiento', ref, fase='Filtro p85', **tag)
                pasa_filtro = closed[85] is not None
                info = pref
                if pasa_filtro:
                    entry, closed, log, ref, info = bus(datos, {o:lim[o] for o in datos}, maximos, red, v, caps, ids,
                        cupo=cupo, cuota_previa=CUOTAS_PREVIAS, semilla=248000 + cupo + int(1000*rate) + margen)
                    add('busqueda_cuotas', log, fase='Cierre conjunto', **tag)
                    add('refinamiento', ref, fase='Cierre conjunto', **tag)
                else:
                    # Sin testigo del p85, los perfiles naturales se comprueban
                    # con el catálogo; no se refinan para fabricar un conjunto.
                    bus.contexto = filtro.contexto
                    for obs in CRITICOS:
                        key,reloj,state,_ = bus._estado(obs,datos[obs],entry['cuotas'],red,v,lim[obs])
                        closed[obs] = BuscadorEquilibrado._cerrar(bus,key,reloj,state,red,v,caps,ids)
                searches.append({**tag, **info, 'prefiltro_p85':pref, 'prefiltro_con_testigo':pasa_filtro, 'cuotas_elegidas':entry['cuotas']})
                q = entry['cuotas']
                add('cuotas', pd.DataFrame([{'punto': p, 'coches_dia': n, 'coches_referencia_550': CUOTAS_PREVIAS[p]} for p, n in q.items()]), **tag)
                modales = {o: reasignar_con_maximos(ox[o], puntos[o], q, incremento=rate, ocupacion=v['ocupacion_coche']) for o in puntos}
                for o, z in modales.items():
                    add('origenes_por_modo', z['por_origen_dia'], observacion=o, **tag)
                    add('objetivos_por_modo', z['escenarios_por_punto_dia'], observacion=o, **tag)
                todos = {**closed, **bus.comprobar_otros(q, red, v, caps, ids)}
                resumen = []
                for obs in MUESTRA:
                    z = todos.get(obs)
                    pt = modales[obs]['escenarios_por_punto_dia']
                    tt = {**tag, 'observacion': obs, 'ambito': 'Perfil histórico', 'cumplimiento_cambio_fecha': 0.}
                    row = {**tt, 'cierre': z is not None, 'programadas': z['programadas'] if z else np.nan,
                           'sin_programar': 30-z['programadas'] if z else np.nan,
                           'demanda_lanzadera_personas_dia': float(pt.demanda_lanzadera_dia.sum()),
                           'visitas_totales_persona_dia': float(pt.visitas_sin_dia.sum()),
                           'coches_autorizados_dia': float(pt.coches_autorizados_dia.sum()),
                           'limite_llegada_cabecera_min': float(lim[obs].limite_llegada_cabecera_min.iloc[0])}
                    resumen.append(row)
                    guardar_cierre(z, tt, row['demanda_lanzadera_personas_dia'], lim[obs])
                # La política de fecha se mantiene separada de los incrementos
                # modales y no se utiliza para aceptar el nominal sin traslados.
                p85nom = False
                for cumpl in [0., .5, 1.]:
                    zs, tr = cambiar_fechas_muestra(modales, indices, Q15, ocupacion=v['ocupacion_coche'], cumplimiento=cumpl)
                    if not tr.empty:
                        add('traspasos_fecha', tr, cumplimiento_cambio_fecha=cumpl, **tag)
                    sample = pd.concat([z['escenarios_por_punto_dia'].assign(matrix_index=o) for o, z in zs.items()], ignore_index=True)
                    add('muestra_p85_diaria', sample, cumplimiento_cambio_fecha=cumpl, **tag)
                    pp = sample.groupby('punto', as_index=False).agg(demanda_lanzadera_dia=('demanda_lanzadera_dia', lambda a: a.quantile(.85, interpolation='linear')))
                    test = pp.merge(lim[85], on='punto')
                    test['deficit_intervalo_personas'] = (test.demanda_lanzadera_dia - test.capacidad_maxima_intervalo_personas).clip(lower=0)
                    add('p85_recalculado', test, cumplimiento_cambio_fecha=cumpl, **tag)
                    zz = None
                    if test.deficit_intervalo_personas.max() <= 1e-8:
                        pp['demanda_bruta_lanzadera_dia'] = pp.demanda_lanzadera_dia + pp.punto.map(q) * v['ocupacion_coche']
                        key, reloj, state, _ = bus._estado(85 + round(100*cumpl), pp, q, red, v, lim[85])
                        zz = BuscadorEquilibrado._cerrar(bus, key, reloj, state, red, v, caps, ids)
                        if cumpl == 0:
                            esperado = p85bruto.set_index('punto').demanda_bruta_lanzadera_dia - pd.Series(q)*v['ocupacion_coche']
                            if not np.allclose(pp.set_index('punto').demanda_lanzadera_dia.sort_index(), esperado.sort_index(), rtol=0, atol=1e-8):
                                raise ValueError('El percentil por cuotas efectivas contradice la búsqueda.')
                    tt = {**tag, 'observacion': 85, 'ambito': 'p85 multianual', 'cumplimiento_cambio_fecha': cumpl}
                    row = {**tt, 'cierre': zz is not None, 'programadas': zz['programadas'] if zz else np.nan,
                           'sin_programar': 30-zz['programadas'] if zz else np.nan,
                           'demanda_lanzadera_personas_dia': float(pp.demanda_lanzadera_dia.sum()),
                           'limite_llegada_cabecera_min': float(lim[85].limite_llegada_cabecera_min.iloc[0]),
                           'deficit_intervalo_personas': float(test.deficit_intervalo_personas.sum())}
                    resumen.append(row)
                    guardar_cierre(zz, tt, row['demanda_lanzadera_personas_dia'], lim[85])
                    if cumpl == 0:
                        p85nom = zz is not None
                res = pd.DataFrame(resumen)
                add('resumen', res)
                naturales = res[res.ambito.eq('Perfil histórico')]
                joint = bool(naturales.cierre.all() and p85nom)
                syn.append({**tag, 'prefiltro_p85_con_cierre':pasa_filtro, 'perfiles_historicos_con_cierre': int(naturales.cierre.sum()), 'p85_sin_cambio_fecha_con_cierre': p85nom,
                            'cierre_conjunto': joint, 'maximo_programadas_con_cierre': res.programadas.max(),
                            'sensibilidades_p85_con_cierre': int(res[res.ambito.eq('p85 multianual')].cierre.sum()),
                            'max_desviacion_proporcional': info['max_desviacion_elegida']})
                print(f'Fin {case}: históricos {int(naturales.cierre.sum())}/8; p85 sin fecha={p85nom}; conjunto={joint}; cuotas={q}.', flush=True)
    result = {n: pd.concat(fs, ignore_index=True) for n, fs in tables.items()}
    result.update(sintesis=pd.DataFrame(syn), inventario_30=inv, referencia_solar_2028=solar,
                  indices_muestra=indices, referencia_D247=rd('data/silver/operacion/inventario/cuotas_positivas_cercanas/sintesis.csv'))
    fuentes['data/silver/operacion/inventario/cuotas_positivas_cercanas/sintesis.csv'] = sha256_archivo(root/'data/silver/operacion/inventario/cuotas_positivas_cercanas/sintesis.csv')
    meta = {'decision': 'D248', 'hipotesis': 'H138', 'fecha': '2026-11-08', 'parametros_conservados': params, 'fuentes_sha256': fuentes,
            'orden_cupos': [600,625,650], 'incrementos_excursiones': [.15,.125,.10], 'margenes_min': [15,30],
            'busquedas': searches, 'presupuesto': {'estados_por_caso': estados, 'configuraciones_refinadas': 3, 'reinicios_por_geometria': 2, 'pasos_por_reinicio': pasos},
            'evaluacion_semillas': 'Evaluación diferida por la cota inferior existente: mismas dos mejores semillas exactas; todas las semillas se conservan si la mejor permite<=27. Mismo catálogo, orden, refinamiento y aceptación.',
            'criterio': 'Usar primero el p85 nominal como filtro necesario con búsqueda acotada. Si se construye un testigo físico, buscar el cierre conjunto de ocho perfiles y p85. Si no, comprobar perfiles naturales con catálogo sin refinamiento adicional. Minimizar mayor desviación proporcional dentro de cierres construidos y banda75%. Escalar por margen solo si ningún porcentaje cierra con el cupo anterior.',
            'muestra_historica': list(MUESTRA), 'p85_matrices': 57, 'percentil': .85, 'interpolacion': 'linear',
            'regla_modal': 'Incremento uniforme de10/12,5/15% respecto a excursiones sin intervención en cada referencia y origen/colectivo. Misma población; TITSA una vez. No se hereda20% de julio.',
            'cupos': 'Cuotas máximas enteras positivas comunes a las57 referencias; en días de menor demanda no se agota la bolsa elegible que permite la excursión adicional. Cuota administrativa distinta de coches autorizados efectivos.',
            'fecha_sensibilidad': Q15, 'cumplimientos': [0.,.5,1.],
            'limites': ['Hipótesis de oferta de excursiones, no demanda observada o acuerdo de operadores. Excursión cubre acceso/interior/regreso fuera de30.',
                       'El saldo coche→lanzadera es neto operativo; no se calculan alimentación bruta ni energía.',
                       'Se conservan bases y30 identidades originales; máximo27 programadas/tres libres,46 plazas,15min,07:00,120 estancia,10 regulación y bases20:00.',
                       'Ocho perfiles históricos con correspondencia temporal inferida, no un calendario invernal completo; p85 compuesto multianual contra ventana mínima invernal como estrés.',
                       'Si el filtro p85 no construye testigo, no se refina después el catálogo de perfiles naturales; no se afirma haber demostrado la inviabilidad global del p85 o del conjunto.',
                       'Si el p85 tiene testigo, los otros seis perfiles son filtro obligatorio de aceptación, con catálogo inicial; una negativa no prueba inviabilidad u óptimo global.',
                       'Sensibilidades de cambio de fecha contrastan catálogo y geometrías ya refinadas; no todos sus relojes reciben refinamiento adicional.',
                       'Ocaso ideal IGN/OAN Santa Cruz2028; no garantiza visibilidad local. Inicio y vacíos pueden circular sin luz.',
                       'No hay oferta anual, energía, Excel o informe nuevos; no se cambia el percentil para lograr cierre.'],
            'entorno': {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__}}
    return Etapa(result), meta


def generar_excursiones_p85(root, destino, *, estados=5000, pasos=1800):
    root, destino = Path(root).resolve(), Path(destino).resolve()
    permitido = (root/SALIDAS).resolve()
    if destino == permitido or destino.is_relative_to(root) and not destino.is_relative_to(permitido):
        raise ValueError('Elegir una captura nueva fuera de fuentes e informe.')
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):
        raise FileExistsError('Conservar la ejecución anterior; el destino debe estar vacío.')
    etapa, meta = preparar_excursiones_p85(root, estados=estados, pasos=pasos)
    destino.mkdir(parents=True, exist_ok=True)
    for n, t in etapa.tablas.items():
        t.to_csv(destino/(n+'.csv'), sep=';', index=False, encoding='utf-8-sig', float_format='%.17g')
    paquete = Path(__file__).parents[1]
    names = ['flujos/excursiones_p85.py','demanda/excursiones_acotadas.py','demanda/ajuste_invierno.py','demanda/p85_alternativas.py',
             'demanda/redistribucion_temporal.py','operacion/contraste_excursiones.py','operacion/equilibrio_invierno.py','operacion/cuotas_cercanas.py',
             'operacion/cierre_con_bases.py','operacion/invierno.py','operacion/reloj_integrado.py','operacion/ventana_horaria.py',
             'operacion/refinar_reservas.py','operacion/circulacion_compartida.py','operacion/red_compartida.py','operacion/horarios_compartidos.py','operacion/inventario_comun.py']
    meta['codigo_sha256'] = {'movilidad_teide/'+n: sha256_archivo(paquete/n) for n in names}
    meta['codigo_sha256']['scripts/contrastar_excursiones_p85.py'] = sha256_archivo(paquete.parents[1]/'scripts/contrastar_excursiones_p85.py')
    meta['resultados_sha256'] = {p.name: sha256_archivo(p) for p in sorted(destino.glob('*.csv'))}
    (destino/'metadatos.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2)+'\n')
    return etapa, meta
