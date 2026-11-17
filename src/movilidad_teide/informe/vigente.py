"""Recursos editoriales de la referencia vigente; no altera el cálculo energético."""
from pathlib import Path
from .edicion import VERSION,FECHA,REPOSITORIO
import json,shutil
import numpy as np
import pandas as pd
from movilidad_teide.flujos.ordenacion_vigente import consultar_ordenacion,_destino_nuevo
from movilidad_teide.trazabilidad import sha256_archivo

ASSETS=['localizacion_servicios.pdf','distribucion_pendientes.pdf','servicio_interior_turistico.pdf','cabildo_logo.pdf','marcas_programa.png','origenes_cabeceras.pdf','red_directos.pdf','red_alimentadores.pdf']
FISICAS=['pendientes.tex','composicion_parques.tex','parque_copert.tex','factores_turismos.tex','visita_proxima.tex']

def numero(value,dec=1):
    return f'{value:,.{dec}f}'.replace(',','@').replace('.',',').replace('@','.')


def intervalo(lo,hi,dec=1):
    return numero(lo,dec) if abs(lo-hi)<1e-9 else numero(lo,dec)+'--'+numero(hi,dec)


def _tabla(path,caption,headers,rows,nota):
    # Columnas elásticas y números en formato español; cada tabla explica unidad y perímetro.
    n=len(headers)
    cols='X'+''.join('>{\\RaggedLeft\\arraybackslash}X' for _ in headers[1:])
    out=[r'\begin{table}[H]\caption{'+caption+r'}\centering{\fontsize{9}{12}\selectfont',r'\begin{tabularx}{\linewidth}{@{}'+cols+r'@{}}',r'\rowcolor{azul} '+' & '.join(r'\Blanco{'+h+'}' for h in headers)+r'\\']
    for i,row in enumerate(rows):out.append((r'\rowcolor{fondo_azul}' if i%2==0 else '')+' & '.join(map(str,row))+r'\\')
    out.extend([r'\bottomrule\end{tabularx}}\Fuente{'+nota+r'}\end{table}'])
    path.write_text('\n'.join(out)+'\n')


def preparar_tablas(root,destino,datos):
    ref=datos['referencia'];cfg=ref['valores'];t=datos['tablas'];N=cfg['visitas_anio'];conv=cfg['mwh_por_tep']
    folder=destino/'tablas/vigente';folder.mkdir(parents=True)
    cal=t['calendario_operativo'];daily=t['actividad_diaria'];hot=t['central'];fta=t['fta'];ss=t['sensibilidad_excursiones']
    _tabla(folder/'calendario.tex','Distribución anual de vehículos programados',['Régimen','Propias al día','Fechas','Sustitutas mínimas'],[[('Ordinaria' if p<=27 else 'Punta'),str(p),str(n),('2 externas' if p==30 else str(30-p)+' propias')] for p,n in cal.groupby('programadas').size().items()],r'Vehículos físicos distintos por fecha, reutilizados en varias expediciones. No son circulaciones simultáneas continuas ni turnos de conducción. Total: 366 fechas.')
    h=pd.read_csv(root/ref['indice']['demanda_horaria'],sep=';',float_precision='round_trip');h=h[h.metodo_calendario.eq('Estacional')]
    baseline={mode:float((h[col]*h.dias_calendario).sum()) for mode,col in [('Coche','visitas_coche'),('TITSA de acceso','visitas_titsa'),('Excursión','visitas_excursiones_resto_colectivo')]}
    np.testing.assert_allclose(sum(baseline.values()),N,atol=1e-8,rtol=0)
    first=hot.iloc[0]
    for (q,mx,profile),g in cal.groupby(['cupo','max_programadas_programa','perfil']):
        viajes=pd.read_csv(root/ref['indice']['captura']/'ofertas'/str(q)/str(mx)/profile/'viajes.csv',sep=';',float_precision='round_trip')
        np.testing.assert_allclose(viajes.personas.sum(),2*g.visitas_lanzadera_dia.iloc[0],atol=1e-8,rtol=0)
        if set(viajes.familia)!={'Integrado'}:raise ValueError('La descripción de cadenas requiere revisar la oferta.')

    _tabla(folder/'visitas.tex','Visitas-persona anuales por modo de acceso',['Modo','Sin intervención','Con intervención'],[['Coche',numero(baseline['Coche'],0),numero(first.visitas_coche_anio,0)],['TITSA de acceso',numero(baseline['TITSA de acceso'],0),'Sustituida por lanzadera'],['Excursiones / resto colectivo',numero(baseline['Excursión'],0),numero(first.visitas_excursion_anio,0)],['Lanzaderas nuevas','0',numero(first.visitas_lanzadera_anio,0)],['Total',numero(N,0),numero(N,0)]],r'Mismas visitas, orígenes, colectivos y fechas. Las excursiones son una aproximación del resto colectivo tras separar TITSA. Los valores se redondean para lectura; las sumas se comprueban antes de redondear.')
    rows=[];groups=[('Ordinaria',cal.regimen.eq('Ordinaria')),('Punta: 28 propias',cal.programadas.eq(28)),('Punta: 30 propias',cal.programadas.eq(30)),('Año completo',pd.Series(True,index=cal.index))]
    for name,mask in groups:
        c=cal[mask];rows.append([name,str(len(c)),numero(c.visitas_sin_dia.sum(),0),numero(c.visitas_lanzadera_dia.sum(),0),numero(c.visitas_excursion_dia.sum(),0)])
    _tabla(folder/'visitas_regimen.tex','Visitas atendidas en cada régimen',['Régimen','Fechas','Visitas totales','En lanzadera','En excursión'],rows,r'Cada fecha se cuenta una sola vez. Los desplazamientos de regreso y los embarques interiores se contabilizan como actividad, sin añadir visitas-persona.')
    macro=[]
    for key,tab in [('Hot',hot),('Fta',fta)]:
        macro.extend([(key+'AhorroTep',intervalo(tab.ahorro_min_tep.min(),tab.ahorro_max_tep.max())),(key+'AhorroMwh',intervalo(tab.ahorro_min_mwh.min(),tab.ahorro_max_mwh.max())),(key+'AhorroVisita',intervalo(tab.ahorro_min_kwh_visita.min(),tab.ahorro_max_kwh_visita.max(),3))])
    for tag,tab in [('Hot',hot),('Fta',fta)]:
        macro.extend([(tag+'ConsumoMwh',intervalo(tab.con_identificado_min_mwh.min(),tab.con_identificado_max_mwh.max())),(tag+'ConsumoVisita',intervalo(tab.con_identificado_min_mwh.min()*1000/N,tab.con_identificado_max_mwh.max()*1000/N,3))])
    macro.extend([('SinConsumoMwh',intervalo(hot.sin_identificado_mwh.min(),hot.sin_identificado_mwh.max())),('SinConsumoVisita',intervalo(hot.sin_identificado_mwh.min()*1000/N,hot.sin_identificado_mwh.max()*1000/N,3))])
    rows=[]
    for key,label,scale,dec in [('sin_identificado_mwh','Consumo sin (MWh/año)',1,1),('sin_identificado_mwh','Consumo sin (tep/año)',1/conv,1),('con','Consumo con (MWh/año)',1,1),('con','Consumo con (tep/año)',1/conv,1),('ahorro','Ahorro (MWh/año)',1,1),('ahorro','Ahorro (tep/año)',1/conv,1),('con','Consumo con (kWh/visita)',1000/N,3),('ahorro','Ahorro (kWh/visita)',1000/N,3)]:
        row=[label]
        for tab in [hot,fta]:
            lo,hi=(tab[key].min(),tab[key].max()) if key.startswith('sin') else ((tab.con_identificado_min_mwh.min(),tab.con_identificado_max_mwh.max()) if key=='con' else (tab.ahorro_min_mwh.min(),tab.ahorro_max_mwh.max()))
            row.append(intervalo(lo*scale,hi*scale,dec))
        rows.append(row)
    _tabla(folder/'balance.tex','Consumo y ahorro identificados: año completo',['Indicador','En caliente','Contraste FTA'],rows,r'Envolventes de dos asignaciones de turismos y extremos de alimentadores, no intervalos estadísticos. Cada ahorro se resta dentro de su propia asignación. No incluyen el consumo común absoluto sin cuantificar.')
    rows=[]
    for r in hot.itertuples():
        rows.append(['Alquiler' if 'alquiler' in r.asignacion_turismos else 'Particular',numero(r.sin_identificado_mwh),intervalo(r.con_identificado_min_mwh,r.con_identificado_max_mwh),intervalo(r.ahorro_min_tep,r.ahorro_max_tep)])
    _tabla(folder/'asignaciones.tex','Balance en caliente separado por asignación de turismos',['España no Tenerife','Sin (MWh)','Con (MWh)','Ahorro (tep)'],rows,r'Alquiler y particular se refieren solo a los coches de España no Tenerife. En ambas asignaciones Tenerife usa particular y extranjeros, alquiler; todos los modos y colectivos están incluidos.')
    # Cuentas diarias: mismo posicionamiento por unidad externa/activación que el balance anual.
    rate=first.posicionamiento_mwh/(cal.externas_disponibles.sum()*cfg['posicionamiento_km'])
    accounts=[];components=[]
    for name,mask in groups:
        dates=set(cal.loc[mask,'fecha']);cs=cal[mask];nv=cs.visitas_sin_dia.sum()
        for alt,g in daily[daily.fecha.isin(dates)].groupby('asignacion_turismos',sort=False):
            sin=float(g.sin_mwh_dia.sum());pos=float(cs.externas_disponibles.sum()*cfg['posicionamiento_km']*rate)
            lo=float(g.con_min_mwh_dia_sin_posicionamiento.sum())+pos;hi=float(g.con_max_mwh_dia_sin_posicionamiento.sum())+pos
            accounts.append(dict(regimen=name,asignacion=alt,visitas=nv,sin_mwh=sin,con_min_mwh=lo,con_max_mwh=hi,ahorro_min_mwh=sin-hi,ahorro_max_mwh=sin-lo))
            if name=='Año completo':
                pieces=[('Coches directos e interior','sin_coche_mwh_dia','con_coche_mwh_dia'),('Excursiones','sin_excursion_mwh_dia','con_excursion_mwh_dia'),('TITSA de acceso','sin_TITSA_mwh_dia',None),('Coche a cabeceras',None,None),('Alimentación de viajeros de TITSA',None,'con_alimentador_TITSA_mwh_dia'),('Lanzaderas comerciales',None,'con_lanzadera_comercial_mwh_dia'),('Lanzaderas en vacío',None,'con_lanzadera_vacia_mwh_dia'),('Posicionamiento externo',None,None)]
                for label,before,after in pieces:
                    a=float(g[before].sum()) if before else 0.;b=float(g[after].sum()) if after else 0.;c=b
                    if label=='Coche a cabeceras':
                        b=float((g.con_alimentador_habitual_mwh_dia-g.alimentador_antiguo_retirado_mwh_dia+g.alimentador_nuevo_min_mwh_dia+g.con_alimentador_otro_colectivo_mwh_dia).sum())
                        c=float((g.con_alimentador_habitual_mwh_dia-g.alimentador_antiguo_retirado_mwh_dia+g.alimentador_nuevo_max_mwh_dia+g.con_alimentador_otro_colectivo_mwh_dia).sum())
                    if label=='Posicionamiento externo':b=c=pos
                    components.append(dict(componente=label,asignacion=alt,sin_mwh=a,con_min_mwh=b,con_max_mwh=c))
    acc=pd.DataFrame(accounts);comp=pd.DataFrame(components)
    for alt,g in comp.groupby('asignacion'):
        refrow=hot[hot.asignacion_turismos.eq(alt)].iloc[0]
        np.testing.assert_allclose(g[['sin_mwh','con_min_mwh','con_max_mwh']].sum(),[refrow.sin_identificado_mwh,refrow.con_identificado_min_mwh,refrow.con_identificado_max_mwh],atol=1e-8,rtol=0)
    for n in ['sin_mwh','con_min_mwh','con_max_mwh','ahorro_min_mwh','ahorro_max_mwh']:
        for alt,g in acc.groupby('asignacion'):np.testing.assert_allclose(g.loc[g.regimen.ne('Año completo'),n].sum(),g.loc[g.regimen.eq('Año completo'),n].iloc[0],atol=1e-8,rtol=0)
    _tabla(folder/'componentes.tex','Ocho componentes de energía identificados (MWh/año)',['Componente','Sin','Con'],[[name,intervalo(g.sin_mwh.min(),g.sin_mwh.max()),intervalo(g.con_min_mwh.min(),g.con_max_mwh.max())] for name,g in comp.groupby('componente',sort=False)],r'En caliente, con 100 km por apoyo disponible y activación. Los extremos por fila no se suman para construir el ahorro: se conservan las asignaciones completas. Los consumos comunes sin cuantificar quedan fuera de esta tabla.')
    _tabla(folder/'energia_regimen.tex','Energía en caliente por régimen: cuentas de todas sus fechas',['Régimen','Con (MWh)','Con (tep)','Ahorro (tep)'],[[name,intervalo(g.con_min_mwh.min(),g.con_max_mwh.max()),intervalo(g.con_min_mwh.min()/conv,g.con_max_mwh.max()/conv),intervalo(g.ahorro_min_mwh.min()/conv,g.ahorro_max_mwh.max()/conv)] for name,g in acc.groupby('regimen',sort=False)],r'Primero se suman las fechas dentro de cada asignación; después se forma la envolvente. Las bandas de los grupos no se suman por sus extremos. Cada punta sustituye a su programación ordinaria.')
    _tabla(folder/'energia_visita_regimen.tex','Consumo y ahorro por visita de cada régimen',['Régimen','Con (kWh/visita)','Ahorro (kWh/visita)'],[[name,intervalo((1000*g.con_min_mwh/g.visitas).min(),(1000*g.con_max_mwh/g.visitas).max(),3),intervalo((1000*g.ahorro_min_mwh/g.visitas).min(),(1000*g.ahorro_max_mwh/g.visitas).max(),3)] for name,g in acc.groupby('regimen',sort=False)],r'Los denominadores son las visitas del grupo correspondiente; el total anual usa 2.500.000. No se promedian ratios diarios sin ponderar.')
    ssh=ss[ss.tratamiento.eq('Hot COPERT')];rows=[]
    for (inc,offer),g in ssh.groupby(['incremento_excursiones','oferta'],sort=False):
        r=g.iloc[0];rows.append(['+'+numero(inc*100,0)+r'\%',('sin reducir' if offer=='Oferta conservada' else 'ajustada'),numero(r.visitas_excursion,0),numero(r.expediciones,0),intervalo(g.ahorro_min_tep.min(),g.ahorro_max_tep.max())])
    _tabla(folder/'sensibilidad.tex','Sensibilidad de excursiones con las mismas visitas anuales',['Excursiones','Oferta lanzaderas','Visitas excursión','Expediciones','Ahorro (tep)'],rows,r'Incremento de visitas en excursión frente a sin intervención. Los nuevos viajeros proceden de lanzadera. Servicio sin reducir: todas las circulaciones principales. Ajustado: circulaciones seleccionadas y comprobadas dentro de los límites de cada fecha.')
    _tabla(folder/'sensibilidad_visita.tex','Consumo, ahorro y ocupación en la sensibilidad de excursiones',['Excursiones / oferta','Con (kWh/visita)','Ahorro (kWh/visita)','Ocupación diseño'],[['+'+numero(inc*100,0)+r'\% / '+('sin reducir' if offer=='Oferta conservada' else 'ajustada'),intervalo(g.con_min_kwh_visita.min(),g.con_max_kwh_visita.max(),3),intervalo(g.ahorro_min_kwh_visita.min(),g.ahorro_max_kwh_visita.max(),3),numero(g.ocupacion_diseno_pct.iloc[0])+r'\%'] for (inc,offer),g in ssh.groupby(['incremento_excursiones','oferta'],sort=False)],r'Consumo en caliente y 100 km por apoyo disponible/activación. Ocupación: ida y regreso de los visitantes por plazas comerciales ofertadas, con 46 plazas por expedición; los vacíos cuentan en energía y no en plazas comerciales.')
    for frame,name in [(acc,'cuentas_regimenes'),(comp,'componentes_identificados')]:
        frame.to_csv(destino/'anexos'/(name+'.csv'),sep=';',index=False,float_format='%.17g')
    for name,df in t.items():df.to_csv(destino/'anexos'/(name+'.csv'),sep=';',index=False,float_format='%.17g')
    posrows=[]
    for q in [0,50,100]:
        row=[str(q)]
        for tab,correction in [(hot,1),(fta,1/(1-cfg['perdida_rendimiento_fta']))]:
            saving=(100-q)/100*tab.posicionamiento_mwh*correction
            row.append(intervalo((tab.ahorro_min_mwh+saving).min()/conv,(tab.ahorro_max_mwh+saving).max()/conv))
        posrows.append(row)
    _tabla(folder/'posicionamiento.tex','Distancia de posicionamiento y ahorro anual',['km por unidad y activación','Hot (tep)','FTA (tep)'],posrows,r'Mismo calendario, visitas y circulaciones; solo cambia la distancia de posicionamiento externo. Los apoyos siguen siendo necesarios. Distancia total de ida y retirada.')
    for n,tab in [('Hot',hot),('Fta',fta)]:
        for q in [0,50,100]:
            # El posicionamiento es el único término cambiado de esta sensibilidad.
            saving=(100-q)/100*tab.posicionamiento_mwh
            if n=='Fta':saving/=1-cfg['perdida_rendimiento_fta']
            macro.append((n+'Pos'+{0:'Cero',50:'Cincuenta',100:'Cien'}[q],intervalo((tab.ahorro_min_mwh+saving).min()/conv,(tab.ahorro_max_mwh+saving).max()/conv)))
    macro.extend([('CocheSin',numero(baseline['Coche'],0)),('TitsaSin',numero(baseline['TITSA de acceso'],0)),('EntradasSin',numero(baseline['Coche']/cfg['ocupacion_coche'],0)),('ReduccionCoches',numero(100*(1-first.entradas_coches_anio/(baseline['Coche']/cfg['ocupacion_coche'])),2))])
    macro.append(('HotAhorroTepVisita',intervalo(hot.ahorro_min_tep.min()/N,hot.ahorro_max_tep.max()/N,7)))
    for method,prefix in [('Hot COPERT','Hot'),('Contraste FTA lanzaderas y posicionamiento','Fta')]:
        chosen=ss[ss.incremento_excursiones.eq(.25)&ss.oferta.eq('Oferta ajustada entre circulaciones comprobadas')&ss.tratamiento.eq(method)]
        if len(chosen)!=2:raise ValueError('Sensibilidad +25% no unívoca.')
        macro.append(('ExcVeinticinco'+prefix,intervalo(chosen.ahorro_min_tep.min(),chosen.ahorro_max_tep.max())))
    energy=datos['referencia']['indice']['titsa_pendiente']['consumo_mwh_anio']
    macro.extend([('TitsaMwh',numero(energy)),('TitsaTep',numero(energy/conv))])
    (folder/'cifras.tex').write_text('\n'.join(r'\newcommand{\Vig'+k+'}{'+v+'}' for k,v in macro)+'\n')
    return {'comparaciones_componentes_y_regimenes':True,'visitas_sin_con':N,'tablas_vigentes':len(list(folder.glob('*.tex'))),'anexos_actuales':len(list((destino/'anexos').glob('*.csv')))}


def generar_informe_vigente(root,destino):
    root=Path(root).resolve()
    from movilidad_teide.publicacion.reserva import leer_politica
    if leer_politica(root).reservada:
        raise ValueError('La entrega pública reserva el informe y sus anexos. El cálculo numérico sigue disponible en 00–07; la generación documental requiere levantar la reserva y disponer de las fuentes completas.')
    destino=_destino_nuevo(root,destino)
    datos=consultar_ordenacion(root);source=root/'docs/informe_energetico'
    (destino/'anexos').mkdir();(destino/'figuras').mkdir()
    shutil.copy2(source/'main.tex',destino/'main.tex')
    for name in ASSETS:shutil.copy2(source/'figuras'/name,destino/'figuras'/name)
    summary=preparar_tablas(root,destino,datos)
    for name in FISICAS:
        text=(source/'tablas'/name).read_text().replace('velocidades del caso Central','velocidades elegidas para el estudio')
        (destino/'tablas/vigente'/name).write_text(text)
    from movilidad_teide.informe.integracion import preparar_integracion
    summary['integracion_completa']=preparar_integracion(root,destino,datos)
    from movilidad_teide.informe.temporal import generar_figura_temporal
    figura=generar_figura_temporal(datos,destino)
    summary['figura_temporal']=figura
    summary['anexos_actuales']=len(list((destino/'anexos').glob('*.csv')))
    from movilidad_teide.informe.anexos_vigentes import generar_anexos_vigentes
    summary['anexos_entrega']=generar_anexos_vigentes(root,destino,datos)
    from movilidad_teide.informe.recursos_contexto import preparar_recursos_contexto
    summary['recursos_contexto']=preparar_recursos_contexto(root,destino,datos)
    from movilidad_teide.informe.titsa import recursos_titsa
    summary['titsa_pendiente']=recursos_titsa(root,destino,datos)
    from movilidad_teide.informe.revision_comentarios import preparar_apoyos,revisar_textos
    summary['aclaraciones_comentarios']=preparar_apoyos(root,destino,datos)
    from movilidad_teide.informe.implantacion import preparar_implantacion
    summary['implantacion']=preparar_implantacion(destino)
    from movilidad_teide.informe.perfiles import preparar_perfiles
    summary['perfiles_geograficos']=preparar_perfiles(root,destino,datos)
    from movilidad_teide.informe.editorial import revisar_recursos
    summary['revision_lectura']=revisar_recursos(destino)
    summary['revision_comentarios']=revisar_textos(destino)
    files={str(p.relative_to(destino)):sha256_archivo(p) for p in sorted(destino.rglob('*')) if p.is_file()}
    meta={'extension_futura_lanzadera_interior':{'incluida_en_balance':False,'requiere_dimensionar_capacidad_y_recalcular':True},'version_informe':VERSION,'fecha':FECHA,'referencia':'Ordenación recomendada de 2028','visitas_sin_y_con':datos['referencia']['valores']['visitas_anio'],
        'codigo_anexos_vigentes_sha256':sha256_archivo(Path(__file__).with_name('anexos_vigentes.py')),
        'codigo_figura_temporal_sha256':sha256_archivo(Path(__file__).with_name('temporal.py')),
        'codigo_comentarios_sha256':sha256_archivo(Path(__file__).with_name('revision_comentarios.py')),
        'codigo_implantacion_sha256':sha256_archivo(Path(__file__).with_name('implantacion.py')),'codigo_perfiles_sha256':sha256_archivo(Path(__file__).with_name('perfiles.py')),'maestro':'main.tex','codigo_revision_lectura_sha256':sha256_archivo(Path(__file__).with_name('editorial.py')),'codigo_titsa_informe_sha256':sha256_archivo(Path(__file__).with_name('titsa.py')),'codigo_recursos_contexto_sha256':sha256_archivo(Path(__file__).with_name('recursos_contexto.py')),'codigo_integracion_sha256':sha256_archivo(Path(__file__).with_name('integracion.py')),'codigo_sensibilidad_sha256':sha256_archivo(Path(__file__).with_name('sensibilidad_actual.py')),'codigo_editorial_sha256':sha256_archivo(Path(__file__)),'maestro_sha256':sha256_archivo(source/'main.tex'),
        'indice_entradas_sha256':datos['referencia']['sha256_indice'],'libro_sha256':datos['referencia']['base']['sha256_libro'],
        'fuentes_sha256':datos['referencia']['indice']['entradas_sha256'],
        'recursos_fisicos_sha256':{str(p.relative_to(root)):sha256_archivo(p) for p in [*[source/'figuras'/n for n in ASSETS],*[source/'tablas'/n for n in FISICAS]]},
        'generacion_integrada':{'entrada':'scripts/generar_informe.py','version_editorial':VERSION,'compilacion_pdf_ejecutada':False,'datos_y_escenarios_modificados':False,'criterio_revision':'Lectura final: URL pública, identidad de entrega, claridad, recursos y anexos. Sin cambios numéricos'},
        'comprobaciones':summary,'derivados_sha256':files,'porcentaje_global_ahorro':None,
        'repositorio_publico':REPOSITORIO,'alcance':'Informe de la referencia vigente con contexto, ocho fichas, redes, seguimiento y sensibilidades. Código y datos relacionados mediante versiones, manifiestos y huellas; reproducir conserva las decisiones y restricciones del estudio.'}
    (destino/'metadatos.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    return {'version':VERSION,'destino':str(destino),**summary}
