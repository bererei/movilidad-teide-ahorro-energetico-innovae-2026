"""Contrasto cuotas y excursiones puntuales, conservando las capturas previas."""
from pathlib import Path
import json,platform
import numpy as np
import pandas as pd
from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.demanda.ajuste_invierno import reasignar_invierno,limites_cuotas
from movilidad_teide.operacion.ajuste_invierno import buscar_ajuste
from movilidad_teide.operacion.invierno import limites_llegada_con_luz,relojes_de_invierno
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.operacion.ventana_horaria import cerrar_en_ventana
from movilidad_teide.trazabilidad import sha256_archivo
from .horario_1930 import ANTERIOR
from .invierno_p20 import PREVIA as HORARIO_1930
from .compartida_2028 import BASE,PARADAS
from .tipos import Etapa

REFERENCIA='data/silver/movilidad/invierno_p20_2028/20261108_cabeceras_con_luz'
SALIDAS='data/silver/movilidad/ajuste_invierno_2028'
CRITICOS=(6,22)
MUESTRA=(5,6,7,20,21,22,23,29)
CUOTAS_PREVIAS={'CHIO':352,'LAGUNA':107,'OROTAVA':82,'VILAFLOR':9}


def preparar_ajuste_invierno(root, *, buscador=None, orden_cupos=(550,575,600), orden_incrementos=(0.,.05,.10), orden_margenes=(15,30)):
    root=Path(root).resolve();fuentes={}
    def registrar(p,h=None):
        actual=sha256_archivo(root/p)
        if h is not None and actual!=h:raise ValueError(f'Captura anterior modificada: {p}')
        fuentes[p]=actual
    registrar(REFERENCIA+'/metadatos.json');old=json.loads((root/REFERENCIA/'metadatos.json').read_text())
    for p,h in old['fuentes_sha256'].items():registrar(p,h)
    for p,h in old['resultados_sha256'].items():registrar(REFERENCIA+'/'+p,h)
    rd=lambda p:pd.read_csv(root/p,sep=';',float_precision='round_trip')
    params=leer_parametros(root);v={p['id']:p['valor_utilizado'] for p in params['parametros']}
    if (v['cupo_global']!=500 or v['vehiculos_contrato_contraste']!=30 or v['reserva_minima_dentro_flota']!=3
        or v['intervalo_refuerzo_punta_min']!=15 or int(v['plazas_guagua']*v['ocupacion_diseno'])!=46
        or v['regulacion_min']!=10 or v['estancia_min_visita_min']!=120):raise ValueError('Revisar las condiciones conservadas.')
    v={**v,'hora_inicio_acceso':7.}
    d=rd(ANTERIOR+'/observaciones_diarias.csv').loc[lambda t:t.alternativa.eq('P20')&t.referencia_festivos.eq('Domingo')]
    ox=rd(ANTERIOR+'/origenes_muestra.csv').loc[lambda t:t.alternativa.eq('P20')&t.cumplimiento_cambio_fecha.eq(0)]
    diario=d[d.cumplimiento_cambio_fecha.eq(0)&d.matrix_index.isin(MUESTRA)]
    if set(diario.matrix_index)!=set(MUESTRA):raise ValueError('Muestra de invierno incompleta.')
    puntos={int(obs):g.copy() for obs,g in diario.groupby('matrix_index')};origenes={int(obs):g.copy() for obs,g in ox[ox.matrix_index.isin(MUESTRA)].groupby('matrix_index')}
    red=RedOperativa(rd(BASE+'/movimientos_diagnosticos.csv'),rd(BASE+'/pares_diagnosticos.csv'),rd(PARADAS))
    inv=rd(ANTERIOR+'/inventario_30.csv');ids=inv.groupby('base_red').unidad_fisica_id.apply(list).to_dict();caps={b:len(i) for b,i in ids.items()}
    solar=rd(REFERENCIA+'/referencia_solar_2028.csv');sun=solar.groupby('mes').ocaso_min.min().to_dict()
    mes={5:12,6:12,7:12,20:2,21:2,22:2,23:2,29:11}
    tablas={};resumen=[];busquedas=[];cache_normales={}
    def add(n,t,**tag):
        if t is not None and not t.empty:tablas.setdefault(n,[]).append(t.assign(**tag))
    for margen in orden_margenes:
        limites={obs:limites_llegada_con_luz(red,v,ocaso_min=float(sun[mes[obs]]),margen_min=margen) for obs in MUESTRA}
        for cupo in orden_cupos:
            for rate in orden_incrementos:
                case=f'C{cupo}_E{round(rate*100):02d}_M{margen}';tag={'caso':case,'cupo_punta_coches_dia':cupo,'incremento_excursiones_punta':rate,'margen_min':margen}
                # El bruto analítico equivale al balance por origen que se
                # construye y verifica después; solo se usa para buscar relojes.
                datos={obs:puntos[obs][['punto']].assign(demanda_bruta_lanzadera_dia=puntos[obs].visitas_coche-rate*puntos[obs].visitas_excursiones_resto_colectivo+puntos[obs].visitas_titsa) for obs in CRITICOS}
                maximos=pd.concat([limites_cuotas(origenes[obs],rate,ocupacion=v['ocupacion_coche']) for obs in CRITICOS],axis=1).min(axis=1)
                entry,cierres,log,ref,info=(buscar_ajuste if buscador is None else buscador)(datos,{i:limites[i] for i in CRITICOS},maximos,red,v,caps,ids,cupo=cupo,cuota_previa=CUOTAS_PREVIAS,
                    semilla=246000+cupo*10+int(rate*100)*100+margen)
                add('busqueda_cuotas',log,**tag);add('refinamiento',ref,**tag);busquedas.append({**tag,**info,'cuotas_reloj_evaluadas':len(log),'cuotas_elegidas':entry['cuotas'],'minimo_global_demostrado':False})
                for p,q in entry['cuotas'].items():add('cuotas_punta',pd.DataFrame([{'punto':p,'coches_dia':q,'coches_previa_dia':CUOTAS_PREVIAS[p]}]),**tag)
                allclosed=True;maxprog=0
                for obs in MUESTRA:
                    critical=obs in CRITICOS;q=entry['cuotas'] if critical else CUOTAS_PREVIAS;rr=rate if critical else 0.
                    x,pt=reasignar_invierno(origenes[obs],puntos[obs],q,incremento=rr,ocupacion=v['ocupacion_coche'])
                    tt={**tag,'observacion':obs,'perfil':puntos[obs].mes_publicado.iloc[0]+' '+str(int(puntos[obs].anio_fuente.iloc[0]))+' · '+puntos[obs].tipo_fuente.iloc[0],
                        'perfil_punta_con_cambios':critical,'cupo_aplicable_coches_dia':cupo if critical else 550,'incremento_aplicable_excursiones':rr}
                    add('origenes_por_modo',x,**tt);add('objetivos_por_modo',pt,**tt)
                    op=entry['operacion'] if critical else v
                    if critical:
                        closed=cierres[obs];best=entry['candidatos'][obs][0][0][0]
                    else:
                        cachekey=(obs,margen)
                        if cachekey not in cache_normales:
                            cs=relojes_de_invierno(pt,red,v,q,limites[obs]);cache_normales[cachekey]=(cerrar_en_ventana(cs,red,v,caps,ids,inicio_min=420,fin_min=1200),cs[0][0][0])
                        closed,best=cache_normales[cachekey]
                    allclosed &= closed is not None
                    row={**tt,'cierre_con_30_y_tres_sustitutas':closed is not None,'mejor_programacion_ensayada':best,'programadas':np.nan,'sin_programar':np.nan,
                        'separacion_ordinaria_min':op['intervalo_minimo_subidas_min'],'demanda_lanzadera_personas_dia':float(pt.demanda_lanzadera_dia.sum()),
                        'visitas_totales_persona_dia':float(pt.visitas_sin_dia.sum()),'visitas_coche_personas_dia':float(pt.visitas_coche_autorizadas_dia.sum()),
                        'visitas_excursion_personas_dia':float(pt.visitas_excursiones_con_intervencion_dia.sum()),'coches_autorizados_dia':float(pt.coches_autorizados_dia.sum()),
                        'ultimo_llegada_permitida_cabecera_min':float(limites[obs].limite_llegada_cabecera_min.iloc[0])}
                    if closed is not None:
                        maxprog=max(maxprog,closed['programadas']);commercial=closed['viajes'].loc[lambda t:t.destino.str.startswith('cabecera:')]
                        row.update(programadas=closed['programadas'],sin_programar=30-closed['programadas'],ultima_llegada_cabecera_min=float(commercial.llegada_min.max()),ultima_llegada_base_min=float(closed['movimientos'].llegada_min.max()))
                        if abs(closed['reservas'].personas.sum()-pt.demanda_lanzadera_dia.sum())>1e-8:raise ValueError('El reloj pierde viajeros frente a sus orígenes.')
                        if commercial.llegada_min.max()>row['ultimo_llegada_permitida_cabecera_min']+1e-8:raise ValueError('Una llegada rebasa el límite solar.')
                        for n in ['cronologias','reservas','movimientos']:add(n,closed['viajes' if n=='cronologias' else n],**tt)
                        disp=[];moves=closed['movimientos']
                        for unit in inv.itertuples():
                            m=moves[moves.unidad_fisica_id.eq(unit.unidad_fisica_id)].sort_values('salida_min')
                            if not m.empty and m.iloc[0].origen!=unit.base_red:raise ValueError('La identidad no parte de su base original.')
                            disp.append({'unidad_fisica_id':unit.unidad_fisica_id,'programada':not m.empty,'base_inicial':unit.base_red,'base_final':m.iloc[-1].destino if not m.empty else unit.base_red})
                        add('disponibilidad_30',pd.DataFrame(disp),**tt)
                    resumen.append(row)
                # Recalculo el p85 diario solo en las alternativas que cierran
                # los ocho perfiles. Las otras55 matrices no reciben el ajuste.
                if allclosed:
                    for cumpl,source in d.groupby('cumplimiento_cambio_fecha'):
                        sample=source.copy()
                        for obs in CRITICOS:
                            _,pnew=reasignar_invierno(origenes[obs],puntos[obs],entry['cuotas'],incremento=rate,ocupacion=v['ocupacion_coche'])
                            mask=sample.matrix_index.eq(obs);sample.loc[mask,'demanda_lanzadera_dia']=sample.loc[mask,'punto'].map(pnew.set_index('punto').demanda_lanzadera_dia)
                        if sample.matrix_index.nunique()!=57 or sample.duplicated(['matrix_index','punto']).any():raise ValueError('Muestra p85 inválida.')
                        add('muestra_p85_diaria',sample[['matrix_index','punto','demanda_lanzadera_dia']],cumplimiento_cambio_fecha=cumpl,**tag)
                        p=sample.groupby('punto',as_index=False).agg(demanda_lanzadera_dia=('demanda_lanzadera_dia',lambda x:x.quantile(.85,interpolation='linear')))
                        lim=limites_llegada_con_luz(red,v,ocaso_min=float(solar.ocaso_min.min()),margen_min=margen)
                        test=p.merge(lim,on='punto');test['deficit_intervalo_personas']=(test.demanda_lanzadera_dia-test.capacidad_maxima_intervalo_personas).clip(lower=0)
                        add('p85_recalculado',test,cumplimiento_cambio_fecha=cumpl,**tag)
                        fits=bool(test.deficit_intervalo_personas.max()<=1e-8);cerrado=None;best=np.nan
                        if fits:
                            p['demanda_bruta_lanzadera_dia']=p.demanda_lanzadera_dia+p.punto.map(entry['cuotas'])*v['ocupacion_coche']
                            cs=relojes_de_invierno(p,red,entry['operacion'],entry['cuotas'],lim);best=cs[0][0][0];cerrado=cerrar_en_ventana(cs,red,entry['operacion'],caps,ids,inicio_min=420,fin_min=1200)
                        add('resumen_p85',pd.DataFrame([{'cumplimiento_cambio_fecha':cumpl,'intervalo_posible':fits,'deficit_intervalo_personas':test.deficit_intervalo_personas.sum(),
                            'cierre_con_30_y_tres_sustitutas':cerrado is not None,'mejor_catalogo_si_intervalo_posible':best,'p85_exclusivamente_invernal':False}]),**tag)
                print(f'{case}: ocho perfiles cerrados={allclosed}; cuotas={entry["cuotas"]}; mejor crítico={entry["clave"][:2]}',flush=True)
    joined={n:pd.concat(z,ignore_index=True) for n,z in tablas.items()};joined['resumen']=pd.DataFrame(resumen);joined['inventario_30']=inv
    joined['sintesis']=joined['resumen'].groupby(['caso','cupo_punta_coches_dia','incremento_excursiones_punta','margen_min'],as_index=False).agg(
        perfiles=('observacion','size'),perfiles_con_cierre=('cierre_con_30_y_tres_sustitutas','sum'),maximo_programadas=('programadas','max'),minimo_sin_programar=('sin_programar','min'),
        mayor_mejor_programacion_ensayada=('mejor_programacion_ensayada','max'))
    joined['referencia_D245']=rd(REFERENCIA+'/resumen.csv').loc[lambda t:t.ambito_demanda.eq('Muestra meses de poca luz')&t.calendario_luz.eq('Mensual')&t.margen_min.isin([15,30])]
    joined['referencia_solar_2028']=solar
    meta={'decision':'D246','hipotesis':'H136','fecha':'2026-11-08','parametros_conservados':params,'fuentes_sha256':fuentes,'cupo_contrastes':[550,575,600],
        'incremento_excursiones_contrastes':[0,.05,.1],'margenes_antes_ocaso_min':[15,30],'muestra':list(MUESTRA),'perfiles_con_cambios':list(CRITICOS),'cuotas_referencia':CUOTAS_PREVIAS,
        'regla_aplicacion':'Cuotas comunes e incremento solo en matrices6/22; otros seis perfiles mantienen cuota550 y reparto D245. No se aplica a todo el año o se inventan fechas de implantación.',
        'busquedas':busquedas,'semillas':'246000 +10×cupo +100×porcentaje_excursiones +margen; refinamiento suma100×configuración +2×observación +reinicio',
        'presupuesto':'Rejilla25 con extremos y cuota previa; hasta24 estados por cada una de tres prioridades. Vecinos por intercambios5/10 de dos mejores cuotas. Relojes ordinarios30 o15, siete formas; dos configuraciones con dos reinicios600 por perfil pendiente.',
        'criterio':'Cerrar máximo27 con tres libres. Entre candidatos iniciales que cierran priorizo menor variación absoluta de cuotas respecto a D245; después vehículos. Si falta cierre, refinamiento acotado de dos configuraciones. No es mínimo global o selección por ahorro.',
        'limites':['No hay anualización o ahorro nuevo; libro e informe intactos. Los ocho perfiles no representan todo el invierno.',
            'Los rótulos y correspondencia inferida de D243/D245 permanecen:6 fin de semana diciembre/enero2021,22 lunes carnaval febrero2023. TITSA de especiales sigue con referencia domingo.',
            'Más excursiones son visitas reasignadas dentro de origen/colectivo, con cadena propia acceso/interior/regreso fuera de30; oferta de operadores no validada.',
            'Conservo la visita interior representada y el tratamiento previo del coche autorizado; no supongo que los nuevos usuarios de coche necesitan cero lanzadera interior en la explotación real. Otros usuarios, destinos, giros y turnos siguen pendientes.',
            'F163 es horizonte ideal de Santa Cruz2028, hora canaria; margen no garantiza luz local. Vacíos hasta20:00 y primeras salidas07:00 pueden circular sin luz.',
            'El p85 diario usa las57 matrices, cambiando solo6/22 antes del percentil; no es un nuevo p85 invernal ni se valida su envolvente horaria.'],
        'entorno':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__}}
    return Etapa(joined),meta


def generar_ajuste_invierno(root,destino):
    root,destino=Path(root).resolve(),Path(destino).resolve();permitido=(root/SALIDAS).resolve()
    if destino==permitido or destino.is_relative_to(root) and not destino.is_relative_to(permitido):raise ValueError('Elegir una captura nueva fuera de fuentes e informe.')
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):raise FileExistsError('La ejecución anterior se conserva.')
    etapa,meta=preparar_ajuste_invierno(root);destino.mkdir(parents=True,exist_ok=True)
    for n,t in etapa.tablas.items():t.to_csv(destino/(n+'.csv'),sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
    paquete=Path(__file__).parents[1];names=['flujos/ajuste_invierno.py','demanda/ajuste_invierno.py','operacion/ajuste_invierno.py','operacion/invierno.py','operacion/reloj_integrado.py','operacion/refinar_reservas.py','operacion/ventana_horaria.py','operacion/red_compartida.py','operacion/horarios_compartidos.py','operacion/inventario_comun.py','operacion/circulacion_compartida.py']
    meta['codigo_sha256']={'movilidad_teide/'+n:sha256_archivo(paquete/n) for n in names};meta['codigo_sha256']['scripts/contrastar_ajuste_invierno.py']=sha256_archivo(paquete.parents[1]/'scripts/contrastar_ajuste_invierno.py')
    meta['resultados_sha256']={p.name:sha256_archivo(p) for p in sorted(destino.glob('*.csv'))};(destino/'metadatos.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    return etapa,meta
