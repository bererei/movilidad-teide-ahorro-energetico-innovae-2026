"""Recursos del informe completo: explicación, trazabilidad y sensibilidad vigente."""
from pathlib import Path
import ast,json,shutil,textwrap,re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from .formato import tex,formatear_ejes
from .vigente import _tabla as _tabla_base,numero,intervalo
from .sensibilidad_actual import calcular_sensibilidad_fisica
from movilidad_teide.trazabilidad import sha256_archivo

AZUL='#0C4767';JADE='#397568';NARANJA='#FA7921';GRIS='#53636C'


def nombre_parametro(key,spec):
    grupos={'captacion_extranjero':'extranjeros','captacion_nacional':'España no Tenerife','captacion_local':'Tenerife no frecuentes','captacion_frecuente':'resto de Tenerife'}
    if key in grupos:return 'Transferencia desde excursión a lanzadera: '+grupos[key]
    return spec['nombre'].replace('ensayado','previsto')


def _tabla(path,caption,headers,rows,nota):
    escape=lambda s:re.sub(r'(?<!\\)%',r'\\%',str(s))
    _tabla_base(path,escape(caption),[escape(x) for x in headers],[[escape(x) for x in row] for row in rows],escape(nota))


def registrar_campos_sensibilidad(campo,existing):
    definitions=[
        ('Contraste físico','hipótesis','Mediana y parámetros principales, cuartiles de tara, transmisión 0,95, descenso sin reducción o balance sin ajuste gravitatorio; actividad vigente fija.','No admitida'),
        ('Variación intensidad coche (%)','% de energía de coche','Cambio multiplicativo aplicado coherentemente al coche sin/con, incluida toda alimentación; no cambia visitas ni distancias.','No admitida'),
        ('Variación intensidad lanzaderas (%)','% de energía de lanzaderas','Cambio multiplicativo aplicado a nuevas lanzaderas comerciales, vacíos y posicionamiento.','No admitida'),
        ('Extremo técnico','categoría','Menor o mayor ahorro de una misma asignación; no es un percentil probabilístico.','No admitida'),
        ('Incremento hipotético de visitas (%)','% del total de referencia','Solo denominador algebraico para interpretar margen; no modifica el escenario de 2.500.000 ni simula capacidad.','No admitida'),
        ('Visitas de referencia','visitas-persona','Volumen fijo común del escenario principal: 2.500.000.','No admitida'),
        ('Visitas adicionales hipotéticas','visitas-persona','Incremento hipotético de visitas como denominador; no es demanda atendida por una simulación adicional.','No admitida'),
        ('Ahorro identificado (MWh)','MWh/año','Ahorro del escenario principal dentro de asignación y tratamiento.','No admitida'),
        ('Margen neto sobre 60 tep (MWh)','MWh/año','Ahorro identificado menos 697,8 MWh; consumo neto adicional admisible solo si todo lo demás permanece fijo.','No admitida'),
        ('Margen neto sobre 60 tep (tep)','tep/año','Mismo margen energético dividido por 11,63.','No admitida'),
        ('Presupuesto neto adicional (kWh/visita extra)','kWh/visita adicional hipotética','Margen sobre 60 tep multiplicado por 1.000 y dividido por visitas extra. No acredita capacidad ni una previsión de consumo.','No aplicable si visitas adicionales hipotéticas es cero.')]
    for label in ['Sin','Con mínimo','Con máximo','Ahorro mínimo','Ahorro máximo']:
        definitions.append((label+' (kWh/visita)','kWh/visita-persona','Energía de '+label.lower()+' dividida por las mismas 2.500.000 visitas, tras convertir MWh a kWh.','No admitida'))
    for name,unit,meaning,absence in definitions:
        if name not in existing:campo(name,unit,meaning,absence)


def _longtable(path,caption,headers,rows,widths=None):
    widths=widths or [round(150/len(headers),1)]*len(headers)
    cols=''.join('L{'+str(w)+'mm}' for w in widths)
    head=r'\rowcolor{azul} '+' & '.join(r'\Blanco{'+h+'}' for h in headers)+r'\\'
    corta=len(rows)<=10
    body=[r'\begingroup\fontsize{9}{12}\selectfont']
    if corta:
        # Una tabla breve conserva juntas cabecera, filas y nota de lectura.
        body += [r'\begin{table}[!htbp]\caption{'+caption+r'}\centering',r'\begin{tabular}{@{}'+cols+r'@{}}',head]
    else:
        body += [r'\begin{longtable}{@{}'+cols+r'@{}}',r'\caption{'+caption+r'}\\',head+r'\endfirsthead',head+r'\endhead']
    for i,row in enumerate(rows):body.append((r'\rowcolor{fondo_azul}' if i%2==0 else '')+' & '.join(row)+r'\\\addlinespace[5pt]')
    body += [r'\bottomrule\end{tabular}' if corta else r'\bottomrule\end{longtable}',r'\Fuente{Fuente: elaboración propia desde la configuración, fuentes y límites del estudio. Los procedimientos de explotación son propuestas a acordar por Cabildo y operador.}']
    if corta:body += [r'\end{table}\FloatBarrier']
    body += [r'\endgroup']
    path.write_text('\n'.join(body)+'\n')

def analisis_algebraico(datos,components):
    cfg=datos['referencia']['valores'];N=cfg['visitas_anio'];rows=[];limits=[]
    car_names=['Coches directos e interior','Coche a cabeceras','Alimentación de viajeros de TITSA']
    bus_names=['Lanzaderas comerciales','Lanzaderas en vacío','Posicionamiento externo']
    for treatment,key in [('Consumo en caliente','central'),('Contraste FTA de lanzaderas y posicionamiento','fta')]:
        for r in datos['tablas'][key].itertuples():
            c=components[components.asignacion.eq(r.asignacion_turismos)]
            car=c[c.componente.isin(car_names)];bus=c[c.componente.isin(bus_names)]
            cs=car.sin_mwh.sum();clo=car.con_min_mwh.sum();chi=car.con_max_mwh.sum()
            L=bus.con_min_mwh.sum()/(1-cfg['perdida_rendimiento_fta'] if key=='fta' else 1)
            for dc,dl in [(0,0),(.01,0),(-.01,0),(0,.01),(0,-.01),(.05,0),(-.05,0),(0,.05),(0,-.05),(-.01,.01),(-.05,.05),(.05,.05)]:
                sin=r.sin_identificado_mwh+dc*cs
                lo=r.con_identificado_min_mwh+dc*clo+dl*L
                hi=r.con_identificado_max_mwh+dc*chi+dl*L
                rows.append({'Asignación de turismos':r.asignacion_turismos.replace(': ',' en '),'Tratamiento energético':treatment,'Variación intensidad coche (%)':100*dc,'Variación intensidad lanzaderas (%)':100*dl,'Visitas totales':N,'Sin (MWh)':sin,'Con mínimo (MWh)':lo,'Con máximo (MWh)':hi,'Ahorro mínimo (MWh)':sin-hi,'Ahorro máximo (MWh)':sin-lo})
            for pct in [0,1,5,10]:
                extra=N*pct/100
                for end,A in [('Menor ahorro',r.ahorro_min_mwh),('Mayor ahorro',r.ahorro_max_mwh)]:
                    margin=A-60*cfg['mwh_por_tep']
                    limits.append({'Asignación de turismos':r.asignacion_turismos.replace(': ',' en '),'Tratamiento energético':treatment,'Extremo técnico':end,'Incremento hipotético de visitas (%)':pct,'Visitas de referencia':N,'Visitas adicionales hipotéticas':extra,'Ahorro identificado (MWh)':A,'Margen neto sobre 60 tep (MWh)':margin,'Margen neto sobre 60 tep (tep)':margin/cfg['mwh_por_tep'],'Presupuesto neto adicional (kWh/visita extra)':margin*1000/extra if extra else np.nan})
    joint=pd.DataFrame(rows)
    for name in ['Sin','Con mínimo','Con máximo','Ahorro mínimo','Ahorro máximo']:
        joint[name+' (tep)']=joint[name+' (MWh)']/cfg['mwh_por_tep']
        joint[name+' (kWh/visita)']=joint[name+' (MWh)']*1000/N
    return joint,pd.DataFrame(limits)


def preparar_integracion(root,destino,datos):
    root=Path(root);destino=Path(destino);folder=destino/'tablas/vigente'
    physical,units=calcular_sensibilidad_fisica(root,datos)
    comp=pd.read_csv(destino/'anexos/componentes_identificados.csv',sep=';',float_precision='round_trip')
    joint,limits=analisis_algebraico(datos,comp)
    # Detalle de unidades para el control interno; la entrega exporta solo balances legibles.
    units.to_csv(destino/'anexos/unidades_fisicas_integracion.csv',sep=';',index=False,float_format='%.17g')
    cfg=datos['referencia']['valores'];cal=datos['tablas']['calendario_operativo']
    for name,frame in [('sensibilidad_fisica',physical),('sensibilidad_conjunta',joint),('umbrales_condicionados',limits)]:
        frame.to_csv(destino/'anexos'/(name+'_actual.csv'),sep=';',index=False,float_format='%.17g')
    datos['analisis_integracion']={'sensibilidad_fisica':physical,'sensibilidad_conjunta':joint,'umbrales_condicionados':limits}
    _longtable(folder/'fuentes_y_magnitudes.tex','Qué aporta cada fuente y qué no mide',['Fuente','Uso en el estudio','Límite de interpretación'],[
        ['Visor del Teide','Forma horaria y estacional; referencias de oferta y demanda.','No es un aforo anual de visitas únicas ni valida las 366 fechas futuras.'],
        ['Matrices de telefonía','Proporciones por origen y colectivo; 41 referencias territoriales.','Privado incluye discrecional; expansión y población de referencia no completamente caracterizadas.'],
        ['Aforos de tráfico','Entradas por acceso y categoría para aproximar reparto modal.','Pasos de vehículos no equivalen a visitas-persona; series recibidas como corregidas.'],
        ['Pasajeros TITSA','Separación y contraste de acceso/interior; proyección propia.','Embarques no son visitas nuevas; cobertura mensual incompleta.'],
        ['Parque DGT y COPERT','Mezcla técnica, masas y factores de consumo.','Parque provincial registrado y factores modelizados; no consumos medidos de visitantes.'],
        ['Geometrías y terreno','Distancias, segmentos dirigidos y desniveles.','Orígenes representativos, aproximaciones y terreno sin certificación de rasante.'],
        ['Hipótesis de planificación','2.500.000 visitas, cupos y recursos del sistema.','Condiciones de estudio; requieren seguimiento y compromisos de implantación.']],widths=[30,58,60])
    _longtable(folder/'perimetro_escenarios.tex','Qué se contabiliza sin y con intervención',['Componente','Sin intervención','Con intervención'],[
        ['Coche directo','Acceso, visita interior próxima y regreso de la población asignada al coche.','Hipótesis del balance: acceso, visita interior y regreso en el propio coche para las visitas autorizadas por el cupo.'],
        ['Coche hasta cabecera','Incluido en el recorrido directo cuando corresponde.','Alimentación y regreso de transferidos del coche y antiguos viajeros de TITSA; sustitución del recorrido al reasignar cabecera.'],
        ['Excursiones','Acceso, visita interior y regreso en autocar propio de la excursión. Hipótesis: 35,99 personas por autocar equivalente, reconstruida con datos del Parque de 2019.','Mismas visitas y recorrido en su autocar por origen/colectivo en el principal; crecimiento separado en sensibilidad.'],
        ['TITSA de acceso','Oferta de las líneas 342 y 348: cuatro sentidos GTFS, perfiles de pendiente y una expedición por sentido y día.','Retirada una sola vez y atención en nuevas lanzaderas, añadiendo alimentación privada.'],
        ['Lanzaderas','No se incluyen las nuevas lanzaderas del proyecto.','Cabecera, acceso, visita interior y regreso a la misma cabecera. Movimientos comerciales, vacíos y posicionamiento externo previsto.'],
        ['Otros servicios comunes','Consumo absoluto sin cuantificar.','Se cancela en la diferencia solo bajo hipótesis explícita de igualdad.'],
        ['Frío, instalaciones y otros diferenciales','Sin una estimación completa en esta comparación.','Exclusiones e incertidumbres explícitas; cualquier diferencia neta debe revisar el ahorro.']],widths=[30,59,59])
    inventory=datos['tablas']['inventario_bases']
    # base_red distingue las dos bases interiores, agrupadas en base_inicial.
    names={'cabecera:CHIO':'Chío','cabecera:LAGUNA':'La Esperanza','cabecera:OROTAVA':'Aguamansa','cabecera:VILAFLOR':'Vilaflor','interior_boca_eje_principal':'Boca Tauce','interior_portillo_eje_principal':'El Portillo'}
    counts=inventory.groupby('base_red').size()
    assert counts.sum()==30 and set(counts)=={3,4,5,9}
    invrows=[[name,str(int(counts[key]))] for key,name in names.items()]
    _tabla(folder/'inventario_actual.tex','Treinta unidades propias y bases de estudio',['Base','Unidades propias'],invrows,r'Vehículos distintos, no expediciones o turnos. Las cuatro primeras bases son cabeceras; las dos últimas se sitúan en el eje interior. El equilibrio diario y la continuidad anual se comprueban con identidades.')
    regimes=cal.copy();regimes['grupo']=np.where(regimes.programadas<=27,'Ordinaria',np.where(regimes.programadas.eq(28),'Punta: 28 propias','Punta: 30 propias'))
    rows=[]
    for name,g in [*regimes.groupby('grupo',sort=False),('Año completo',regimes)]:
        visits=g.visitas_lanzadera_dia.sum();n=g.expediciones_comerciales.sum()
        rows.append([name,numero(n,0),numero(g.movimientos_vacios.sum(),0),numero(g.km_comerciales.sum()+g.km_vacios.sum(),0),numero(2*visits/n,2),numero(100*2*visits/(cfg['plazas_diseno']*n),2)+r'\%'])
    _tabla(folder/'servicios_regimen.tex','Servicios efectivos, kilómetros y ocupación por régimen',['Régimen','Expediciones','Vacíos','Vehículo-km','Pasajeros / expedición','Ocupación diseño'],rows,r'Ida y regreso son dos expediciones. Ocupación sobre 46 plazas comerciales por expedición; los kilómetros excluyen aquí los 2.600 de posicionamiento externo, contabilizados por separado en energía.')
    _longtable(folder/'activacion_medidas.tex','Cuándo utilizar cada respuesta operativa',['Situación comprobada','Respuesta prevista','Condición de cierre'],[
        ['Demanda compatible con ordinaria','Ajustar expediciones con hasta 27 propias y cupo ordinario global de 650.','Cadena completa, destinos, regreso, plazas, horarios, intervalo y bases; al menos tres propias sin programar.'],
        ['Necesidad por cabecera o franja que supera ordinaria','Programar hasta 28 propias y comprobar reasignación admisible de cabeceras.','Dos propias sin programar y nuevos alimentadores incluidos en energía.'],
        ['Necesidad que requiere las treinta propias','Confirmar dos sustitutas externas disponibles antes de programar treinta.','Disponibilidad efectiva y respuesta acordada; posicionamiento incluido. No hay expediciones externas comerciales programadas en el principal.'],
        ['Déficit que requiere más acceso privado','Aplicar cupo global de 700 o 750 en las fechas previstas y reconstruir la demanda restante.','No sumar coches y lanzaderas para los mismos viajeros. Comprobar el programa completo y registrar fecha y motivo.'],
        ['Crecimiento voluntario de excursiones','Coordinar operadores y ajustar circulaciones efectivas si el traslado modal lo permite.','Mismas visitas totales y ocupación explícita; no es condición de la referencia principal.'],
        ['Extremo, incidencia o demanda fuera de la programación','Revisar dato y causa; diseñar apoyo, cupo o reprogramación y registrar pendientes.','No afirmar cobertura hasta comprobar cadena y energía; conservar evidencia del extremo.']],widths=[41,54,53])
    p=physical
    rows=[]
    for name,g in p.groupby('Contraste físico',sort=False):
        if name=='Sin ajuste gravitatorio convencional':continue
        row=[name]
        for method in ['Consumo en caliente','Contraste FTA de lanzaderas y posicionamiento']:
            x=g[g['Tratamiento energético'].eq(method)];row.append(intervalo(x['Ahorro mínimo (tep)'].min(),x['Ahorro máximo (tep)'].max()))
        rows.append(row)
    _tabla(folder/'sensibilidad_fisica_actual.tex','Ahorro con contrastes físicos de turismos y actividad vigente',['Hipótesis','En caliente (tep/año)','Con FTA (tep/año)'],rows,r'Mismas 2.500.000 visitas, cupos, ocupación y servicios. La sensibilidad modifica únicamente el ajuste gravitatorio convencional; cada asignación se calcula completa. Rangos técnicos, sin probabilidades. No se selecciona el mayor ahorro como nueva referencia.')
    no=p[p['Contraste físico'].eq('Sin ajuste gravitatorio convencional')&p['Tratamiento energético'].eq('Consumo en caliente')].set_index('Asignación de turismos')
    yes=p[p['Contraste físico'].eq('Mediana, transmisión 0,85 y reducción en descenso')&p['Tratamiento energético'].eq('Consumo en caliente')].set_index('Asignación de turismos')
    rows=[]
    for alt,r in yes.iterrows():
        b=no.loc[alt]
        # Los extremos se emparejan por tratamiento de alimentadores, no por ahorro opuesto.
        ds=r['Sin (MWh)']-b['Sin (MWh)'];dlo=r['Con mínimo (MWh)']-b['Con mínimo (MWh)'];dhi=r['Con máximo (MWh)']-b['Con máximo (MWh)']
        effect=[ds-dlo,ds-dhi]
        rows.append([alt.replace('España no Tenerife en ',''),intervalo(b['Ahorro mínimo (tep)'],b['Ahorro máximo (tep)']),intervalo(r['Ahorro mínimo (tep)'],r['Ahorro máximo (tep)']),numero(r['Ahorro mínimo (tep)']-b['Ahorro mínimo (tep)']),numero(r['Ahorro máximo (tep)']-b['Ahorro máximo (tep)'])])
    _tabla(folder/'aporte_pendiente_actual.tex','Cambio del balance al incluir el ajuste gravitatorio (tep/año)',['España no Tenerife','Sin ajuste','Con ajuste','Cambio límite inferior','Cambio límite superior'],rows,r'Misma actividad en ambos balances. Se restan los límites inferiores entre sí y los superiores entre sí. La clase viaria que determina cada límite puede cambiar al aplicar el ajuste: las diferencias no son cotas físicas del aporte ni ahorro adicional acumulable.')
    rows=[]
    for (dc,dl),g in joint.groupby(['Variación intensidad coche (%)','Variación intensidad lanzaderas (%)'],sort=False):
        row=[numero(dc,0)+r'\%',numero(dl,0)+r'\%']
        for method in ['Consumo en caliente','Contraste FTA de lanzaderas y posicionamiento']:
            x=g[g['Tratamiento energético'].eq(method)];row.append(intervalo(x['Ahorro mínimo (tep)'].min(),x['Ahorro máximo (tep)'].max()))
        rows.append(row)
    _tabla(folder/'sensibilidad_conjunta_actual.tex','Ahorro ante cambios de intensidad, con actividad fija',['Coche','Lanzaderas','En caliente (tep/año)','Con FTA (tep/año)'],rows,r'Los porcentajes multiplican la energía del bloque correspondiente por 1 + porcentaje/100. Coche cambia de forma coherente sin/con; nuevas lanzaderas cambian solo con. No son probabilidades ni nuevos programas de transporte.')
    rows=[]
    for method,g in limits[limits['Incremento hipotético de visitas (%)'].eq(0)].groupby('Tratamiento energético',sort=False):
        x=datos['tablas']['central' if method=='Consumo en caliente' else 'fta'];L=x.lanzaderas_y_posicionamiento_hot_mwh if 'lanzaderas_y_posicionamiento_hot_mwh' in x else None
        rows.append(['En caliente' if method=='Consumo en caliente' else 'Contraste FTA',intervalo(g['Ahorro identificado (MWh)'].min(),g['Ahorro identificado (MWh)'].max()),intervalo(g['Margen neto sobre 60 tep (MWh)'].min(),g['Margen neto sobre 60 tep (MWh)'].max()),intervalo(g['Margen neto sobre 60 tep (tep)'].min(),g['Margen neto sobre 60 tep (tep)'].max())])
    _tabla(folder/'margen_actual.tex','Margen condicionado sobre 60 tep/año',['Tratamiento','Ahorro (MWh/año)','Margen (MWh/año)','Margen (tep/año)'],rows,r'Margen = ahorro identificado − 697,8 MWh. Representa diferencial neto adicional admisible solo si lo demás permanece fijo; no cuantifica partidas pendientes.')
    rows=[]
    for pct,g in limits[limits['Incremento hipotético de visitas (%)'].gt(0)].groupby('Incremento hipotético de visitas (%)',sort=False):
        row=[numero(pct,0)+r'\%',numero(g['Visitas adicionales hipotéticas'].iloc[0],0)]
        for method in ['Consumo en caliente','Contraste FTA de lanzaderas y posicionamiento']:
            x=g[g['Tratamiento energético'].eq(method)]['Presupuesto neto adicional (kWh/visita extra)'];row.append(intervalo(x.min(),x.max(),2))
        rows.append(row)
    _tabla(folder/'umbral_visitas_actual.tex','Cociente condicionado por visita adicional hipotética',['Aumento hipotético','Visitas extra','Hot (kWh/visita extra)','FTA (kWh/visita extra)'],rows,r'Margen neto sobre 60 tep dividido por visitas extra. No modifica el escenario de 2,5 millones ni acredita plazas o transporte. Energía adicional neta = con menos sin para las visitas extra.')
    _origenes(root,folder,datos)
    _seguimiento(folder)
    rows=[]
    for key,value in cfg.items():
        spec=datos['referencia']['indice']['parametros_de_la_referencia'][key]
        label=nombre_parametro(key,spec)
        text=numero(value,0 if float(value).is_integer() else (2 if abs(value)<1 else 2))
        if key.startswith('fin_bases_'):text=f'{int(value)//60:02d}:{int(value)%60:02d} ('+numero(value,0)+' min)'
        if key=='hora_inicio_acceso':text=f'{int(value):02d}:00'
        if key in ['perdida_rendimiento_fta','sensibilidad_excursiones_1','sensibilidad_excursiones_2']:
            text+=r' (='+numero(100*value,0)+r'\%)'
        application='Sensibilidad' if key.startswith('sensibilidad_') else ('Contraste' if key=='perdida_rendimiento_fta' else 'Principal')
        if key=='visitas_anio':origin=r'Estimación del Cabildo; hipótesis~\cite{planificacion}'
        elif key=='propias':origin=r'Previsión comunicada~\cite{respuesta}'
        elif key in ['ocupacion_coche','ocupacion_guagua_aforo']:origin=r'Ocupación de referencia trasladada al estudio~\cite{ocupacion}'
        elif key=='mwh_por_tep':origin=r'Equivalencia de unidades~\cite{unidadesoficiales}'
        elif key=='perdida_rendimiento_fta':origin=r'Referencia externa; sin calibración local~\cite{fta}'
        else:origin=r'Hipótesis de diseño o contraste~\cite{calculo}'
        unit=spec['unidad'].replace('personas/equivalente','personas por autocar equivalente')
        rows.append([tex(label),text,tex(unit),application,origin])
    _longtable(folder/'parametros_completos.tex','Configuración efectiva de la ordenación y sus contrastes',['Elección','Valor','Unidad','Aplicación','Procedencia y estado'],rows,widths=[43,25,23,17,32])
    _guia(root,folder)
    _figuras(destino,datos,comp)
    ref=datos['referencia'];energy=root/ref['indice']['energia'];extra=root/ref['indice']['excepciones']
    physical_folder=root/'data/silver/energia/referencias_unitarias/pendiente_turismos'
    paths=[physical_folder/'curvas_y_masas.parquet',physical_folder/'correccion_por_origen_y_rama.csv',energy/'segmentos_por_via_para_valorar_alimentadores.parquet',extra/'perfiles_alimentadores_excepciones.parquet',extra/'unidades_alimentadores_excepciones.csv',energy/'alimentacion_coche_TITSA_hipotesis_usuario.csv',root/ref['indice']['catalogo_cabeceras']/'catalogo.csv',root/'data/silver/vehiculos/ponderacion/factores.csv',root/'data/silver/geografia/referencias_fisicas/origenes_itinerarios.csv',root/'docs/informe_energetico/tablas/vias_origenes.tex']
    return {'caso_fisico_central_reproducido':True,'contrastes_fisicos':6,'filas_sensibilidad_fisica':len(physical),'filas_sensibilidad_conjunta':len(joint),'filas_umbrales_condicionados':len(limits),'guia_fichas':8,'entradas_adicionales_sha256':{str(p.relative_to(root)):sha256_archivo(p) for p in paths}}


def _origenes(root,folder,datos):
    old=pd.read_csv(root/'data/silver/geografia/referencias_fisicas/origenes_itinerarios.csv',sep=';',encoding='utf-8-sig',float_precision='round_trip')
    cal=datos['tablas']['calendario_operativo'];ref=datos['referencia'];parts=[]
    for (q,mx,profile),days in cal.groupby(['cupo','max_programadas_programa','perfil']):
        x=pd.read_csv(root/ref['indice']['captura']/'ofertas'/str(q)/str(mx)/profile/'origenes.csv',sep=';',float_precision='round_trip')
        parts.append(x[['origen_id','coches_sin_dia']].assign(coches_sin_dia=x.coches_sin_dia*len(days)))
    totals=pd.concat(parts).groupby('origen_id').coches_sin_dia.sum()
    hh=pd.read_csv(root/ref['indice']['demanda_horaria'],sep=';',float_precision='round_trip')
    hh=hh[hh.metodo_calendario.eq('Estacional')]
    np.testing.assert_allclose(totals.sum(),(hh.visitas_coche*hh.dias_calendario).sum()/ref['valores']['ocupacion_coche'],atol=1e-8,rtol=0)
    examples=old[old.ejemplo_cartografico.astype(str).str.lower().eq('true')].sort_values('numero_en_mapa')
    rows=[]
    for x in examples.itertuples():
        name=x.nombre_origen_informe
        if x.origen_id not in totals:raise ValueError('Origen no cotejado: '+name)
        rows.append([str(int(x.numero_en_mapa))+'. '+tex(name),tex(x.cabecera_calculo),numero(x.alimentador_ida_km,1),numero(100*totals.loc[x.origen_id]/totals.sum(),1)])
    _tabla(folder/'origenes_actuales.tex','Ejemplos geográficos y cuota de coche sin intervención',['Origen de referencia','Cabecera habitual','Ida (km)','Cuota anual (%)'],rows,r'Distancia habitual de ida; cuota sobre entradas de coche sin intervención del escenario de 2,5 millones. Los ocho ejemplos corresponden al mapa y no son una nueva selección ordenada por demanda. Las reasignaciones se contabilizan aparte.')
    shutil.copy2(root/'docs/informe_energetico/tablas/vias_origenes.tex',folder/'vias_origenes.tex')


def _seguimiento(folder):
    _longtable(folder/'datos_seguimiento.tex','Datos de explotación y controles propuestos',['Dato','Obtención y control','Frecuencia y responsable propuesto'],[
        ['Expediciones y distancias','Posición y expediciones por unidad, conciliadas con cuentakilómetros. Separar comerciales, vacíos, base, desvíos y posicionamiento.','Registro diario del operador; conciliación mensual con supervisión del Cabildo.'],
        ['Combustible y electricidad','Repostajes, existencias y recargas por vehículo y frontera. Conciliar compra y consumo; registrar auxiliares e incidencias.','Registro por operación y resumen mensual del operador.'],
        ['Visitas, reservas y ocupación','Vincular solicitudes, confirmaciones, ida y regreso de una visita. Registrar viajeros por tramo, solicitudes pendientes y motivos.','Registro continuo de reservas y explotación; control diario de capacidad.'],
        ['Entradas privadas y ocupación','Aforos o cámaras por acceso y sentido, depurados de duplicados; autorizaciones, excepciones y muestras de personas por coche.','Control diario y muestreo acordado; gestor del acceso y Cabildo.'],
        ['Disponibilidad y sustituciones','Unidades aptas y programadas por base; averías y tiempos de solicitud, llegada y sustitución.','Parte diario del operador y revisión de cada incidencia.'],
        ['TITSA y excursiones','Servicios sustituidos y mantenidos; viajeros, capacidad y kilómetros efectivos por operador, evitando duplicidad de visitas.','Conciliación mensual con operadores y coordinación del Cabildo.'],
        ['Referencia sin proyecto','Actualizar demanda comparable, reparto territorial, ocupación y servicios independientes; contrastar con aforos y encuestas.','Revisión anual de la referencia por el equipo técnico designado.'],
        ['Contexto y cambios','Cierres, meteorología, cambios de oferta o vehículo, visitas inducidas y desplazadas; fecha, fuente y efecto energético.','Registro de cada cambio y evaluación conjunta anual.']],widths=[30,72,46])
    _longtable(folder/'indicadores_seguimiento.tex','Indicadores y criterios de interpretación propuestos',['Indicador','Cálculo y unidad','Interpretación y respuesta'],[
        ['Ahorro anual','Energía estimada sin menos energía con para año, visitas y perímetro comparables; MWh/año y tep/año.','Contrastar el objetivo de 60 tep/año y justificar la referencia. No equivale al combustible de las lanzaderas.'],
        ['Consumo por visita','Energía del periodo / visitas-persona del mismo ámbito; kWh/visita y conversión a tep.','Comparar periodos homogéneos. Menor intensidad no garantiza por sí sola ahorro absoluto si crecen las visitas.'],
        ['Intensidad de lanzaderas','Energía / vehículo-km, identificando comerciales, vacíos y otros movimientos.','Investigar cambios de carga, ruta, vehículo, auxiliares o incidencias; no modificar el perímetro para mejorar el indicador.'],
        ['Kilómetros en vacío','km sin pasajeros / km totales del perímetro, en porcentaje.','Reducir reposiciones evitables preservando cobertura, regreso y equilibrio de bases. El objetivo no es cero vacíos.'],
        ['Visitas confirmadas atendidas','Visitas con cadena completa realizada / visitas confirmadas; porcentaje y demanda rechazada aparte.','Objetivo propuesto: atender todas las confirmadas, sin ocultar solicitudes no atendidas o reducir exigencias de visita.'],
        ['Entradas privadas al Parque','Entradas diarias imputables al cupo y diferencia anual frente a referencia comparable.','Comprobar 650 en ordinaria y activaciones de 700/750. No confundir con reducción de todos los viajes privados hasta cabeceras.'],
        ['Ocupación comercial','Pasajeros por tramo o expedición / capacidad comercial declarada; porcentaje y personas.','Distinguir diseño de 46 plazas, nominal técnica y carga COPERT. La media anual no garantiza capacidad en cada franja.'],
        ['Sustitución y respuesta','Unidades aptas menos programadas por base; tiempos de respuesta en minutos.','Ordinaria: al menos tres propias sin programar; punta: dos propias o dos externas disponibles al programar treinta. Revisar ubicación y tiempo real.']],widths=[30,61,57])


def _guia(root,folder):
    fichas=[
      ('demanda','Demanda, aforos y calendario','demanda/calendario_anual.py',['crear_calendario','construir_perfiles_anuales','aplicar_cupo_global'],
       ['visitas_modos_colectivos.csv','calendario_diario.csv','parametros_vigentes.csv'],
       'El libro de parámetros y su índice definen el volumen de 2.500.000 visitas, las ocupaciones y los cupos. Las distribuciones horarias conservadas aportan proporciones por origen, colectivo y tipo de día. Las referencias de marzo, julio y octubre se trasladan a las tres temporadas sin presentar los meses restantes como observaciones.',
       'Sumar las visitas de cada escenario y comprobar el mismo total anual. Contar 366 fechas y 36 combinaciones de mes y tipo de día. Verificar que la ponderación estacional conserva el aporte anual de las referencias y que TITSA mantiene su proyección propia.',
       'La programación no demuestra ausencia de demanda inducida ni exactitud de todos los extremos de aforo. La ocupación y las proporciones son hipótesis o aproximaciones; una redistribución temporal requiere volver a comprobar transporte y energía.'),
      ('titsa','Viajeros de TITSA y servicios de acceso','demanda/titsa.py',['leer_demanda_publica_titsa','clasificar_pasajeros_titsa'],
       ['visitas_modos_colectivos.csv','energia_componentes.csv','visitas_origen_colectivo.csv','titsa_recorridos.csv','titsa_segmentos.csv','titsa_factores.csv'],
       'Las matrices publicadas de 2025 sirven para distinguir acceso e interior y contrastar la rama colectiva. La preparación conserva la falta de agosto no laborable y las incidencias de noviembre. El acceso sustituido se representa con cuatro sentidos GTFS y sus perfiles de pendiente, una expedición por sentido y día. Los embarques de la 341 no generan visitas adicionales.',
       'Comprobar que los viajeros de acceso sustituidos aparecen en nuevas lanzaderas y que se incorpora su alimentación privada. Restar una sola vez el servicio de acceso retirado. El anexo por origen se limita a coche y excursiones con correspondencia territorial: no reparte ficticiamente los usuarios de TITSA.',
       'La oferta y los factores por pendiente estiman consumo: no son combustible medido por línea. El terreno aproxima la rasante; los factores se limitan al intervalo de pendientes de la biblioteca, con la longitud afectada identificada. El consumo interior común se mantiene sin cuantificar bajo hipótesis explícita de igualdad; su ausencia numérica no equivale a cero.'),
      ('recorridos','Orígenes, geometrías y cabeceras','demanda/cabeceras_alternativas.py',['leer_catalogo','trasladar_reservas'],
       ['recorridos_origenes.csv','reasignacion_cabeceras.csv','pendientes_recorridos.csv'],
       'El catálogo relaciona 41 referencias territoriales y sus recorridos de ida y regreso. La geometría habitual y la alimentación alternativa tienen procedencia y longitud propias. La reasignación cambia la cabecera del viajero elegible, conservando origen, colectivo, destino de visita y regreso a su coche.',
       'Cotejar las 82 filas de origen y sentido con 80 geometrías y dos casos condicionales. Comprobar que los traslados no exceden viajeros elegibles y que se retira el alimentador habitual antes de añadir el nuevo. Los mapas habituales no incorporan por sí solos todos los recorridos alternativos.',
       'Los orígenes son representativos y nueve referencias territoriales reutilizan aproximaciones. El terreno aproxima la rasante y persiste la discrepancia espacial documentada en el corredor norte. La consistencia geométrica no acredita itinerarios reales individuales.'),
      ('comunes','Excursiones, acceso TITSA y consumos comunes','flujos/ordenacion_vigente.py',['_preparar_factores','_valorar_programa'],
       ['energia_componentes.csv','balance_anual.csv','sensibilidad_excursiones.csv'],
       'La intensidad de excursiones se obtiene por recorrido representativo y 35,99 personas por autocar equivalente. El principal mantiene sus visitas por origen y colectivo. El acceso de TITSA sin proyecto se valora por los cuatro trazados y sus pendientes; con proyecto se sustituye y se añade su alimentación. Las excursiones mantienen un factor plano: al ser idénticas sin/con, ese bloque se cancela en el ahorro principal, aunque afecta al consumo absoluto.',
       'Separar excursión, acceso TITSA, coches a cabecera y nuevas lanzaderas. Comprobar que ningún bloque se vuelve a sumar por proceder de otra fuente. En sensibilidad de excursiones, el aumento desplaza personas desde lanzadera, conservando el cupo y los 2.500.000 del año. Como cambia su actividad, el factor sin pendiente de excursiones afecta entonces al ahorro y exige interpretar esa sensibilidad con su limitación.',
       'Los autocares equivalentes no son unidades físicas contratadas y su capacidad nominal real permanece desconocida. Los consumos comunes sin cuantificar solo se cancelan bajo igualdad; cualquier diferencial neto adicional reduce o aumenta el ahorro según su signo.'),
      ('operacion','Reservas, circulaciones y vehículos físicos','operacion/calendario_vehiculos.py',['materializar_calendario'],
       ['movimientos_lanzaderas.csv','reservas_visita.csv','disponibilidad_unidades.csv','programacion_anual.csv'],
       'Las circulaciones conservadas conectan cabecera, destino y regreso. Cada reserva enlaza movimientos compatibles con estancia y capacidad. Las unidades tienen identidad y base; se materializan todas las fechas conservando la continuidad entre jornadas. Los vacíos enlazan tareas o devuelven el vehículo y no transportan visitas nuevas.',
       'Conciliar pasajeros de ida y regreso con dos veces las visitas en lanzadera. Comprobar 46 plazas, quince minutos por acceso/sentido, inicio, regulación, estancia, luz y fin de base. Revisar que no se solapan movimientos de una unidad y que se conservan los máximos y sustitutas de cada régimen.',
       'La comprobación física no dimensiona turnos ni acredita disponibilidad contractual. Las dos externas en fechas de treinta propias están disponibles para sustitución y no realizan servicios comerciales programados. Una media de ocupación no demuestra capacidad de todos los extremos.'),
      ('turismos','Parque, factores y ajuste de pendiente','energia/pendiente.py',['energia_pendiente_por_recorrido','aplicar_correcciones_a_actividad'],
       ['factores_turismos_utilizados.csv','parametros_fisicos.csv','sensibilidad_fisica.csv'],
       'La composición DGT y las curvas ponderadas definen los factores base por servicio y clase de circulación. Los atributos incompletos conservan sustituciones identificadas, sin retirar vehículos o renormalizar de forma favorable. El ajuste gravitatorio convencional utiliza tara y carga en cada segmento dirigido.',
       'Revisar m, desnivel, conversión de MJ a MWh y mínimo cero. Aplicar los cambios a sin y con, incluyendo alimentación habitual, reasignada y de antiguos viajeros TITSA. La sensibilidad recombina coeficientes unitarios válidos con actividad vigente y recalcula los alimentadores alternativos; reproduce primero el caso central.',
       'Otras tecnologías mantienen consumo base sin corrección de pendiente estimada. Cuartiles de tara y extremos viarios no son intervalos probabilísticos del ahorro. El contraste sin reducción en descenso no se elige por producir mayor ahorro.'),
      ('balance','Balance anual, regímenes y sensibilidad','flujos/ordenacion_vigente.py',['reproducir_ordenacion','_anualizar_politicas','_anualizar_sensibilidad'],
       ['balance_anual.csv','balance_regimenes.csv','energia_diaria.csv','sensibilidad_conjunta.csv','umbrales_condicionados.csv'],
       'La energía se suma por fecha y asignación de turismos antes de restar escenarios y formar rangos. Los regímenes particionan el año y las puntas sustituyen la programación de sus fechas. La sensibilidad FTA multiplica una sola vez la energía de lanzaderas y posicionamiento por 1/0,9.',
       'Conciliar diario, regímenes y anual por asignación y tratamiento. Comprobar MWh, tep y denominadores por visita. Revisar que excursiones constantes se cancelan sin desaparecer de los consumos y que el posicionamiento solo se añade en sus activaciones. Las perturbaciones algebraicas conservan actividad.',
       'Los rangos no son probabilísticos y sus extremos no se mezclan entre asignaciones. Los cocientes por visita extra no simulan nueva capacidad ni modifican el volumen recomendado. No se obtiene porcentaje global de ahorro mientras el común absoluto permanezca sin cuantificar.'),
      ('informe','Reproducción y preparación de la entrega','informe/integracion.py',['preparar_integracion','analisis_algebraico'],
       ['indice_anexos.csv','diccionario_columnas.csv','guia_calculo.csv'],
       'La reproducción utiliza el libro y las entradas verificadas por sus huellas. La secuencia 00–07 comparte un registro; reconstruye demanda, geografía, clases, masas y coeficientes, conserva la selección técnica y comprueba los programas elegidos. La guía común de ejecución mantiene las instrucciones. El generador consulta la referencia Gold y produce tablas, figuras, CSV, libro de lectura, manifiesto y paquete; reutiliza seis figuras y cinco tablas físicas identificadas y no recalcula el balance principal. Los documentos derivados son salidas de consulta; no sustituyen el libro como punto de edición de hipótesis.',
       'Ejecutar los comandos de reproducción y generación en carpetas nuevas. Comprobar identidad o equivalencia numérica de productos, referencias cruzadas y unidades. Abrir el PDF para revisar tablas, mapas y legibilidad. Verificar que el paquete identifica su edición y contiene los anexos que describe.',
       'Reproducir no significa volver a adquirir fuentes ni ejecutar COPERT. El código y los paquetes de datos deben corresponder a la misma entrega, identificada por sus manifiestos y huellas. Las fuentes conservan sus condiciones de uso. Las huellas prueban identidad de archivos, no calibración o aprobación institucional.')]
    out=[];validation=[]
    recorrido={'demanda':['01_fuentes_y_demanda'],'titsa':['01_fuentes_y_demanda','05_preparacion_y_ejecucion_copert','06_balance_y_sensibilidades'],'recorridos':['02_recorridos_y_pendientes','04_servicio_y_actividad'],'turismos':['03_parque_y_condiciones','05_preparacion_y_ejecucion_copert'],'operacion':['04_servicio_y_actividad'],'balance':['06_balance_y_sensibilidades','07_comprobacion_e_informe'],'comunes':['01_fuentes_y_demanda','05_preparacion_y_ejecucion_copert','06_balance_y_sensibilidades'],'informe':['07_comprobacion_e_informe']}
    for i,(ident,title,module,functions,outputs,inputs,checks,limits) in enumerate(fichas):
        source=root/'src/movilidad_teide'/module
        # El productor se valida tras su instalación; las demás funciones existen ya.
        if source.exists():
            names={x.name for x in ast.walk(ast.parse(source.read_text())) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))}
            assert set(functions)<=names,(module,set(functions)-names)
        cuadernos=recorrido[ident]
        for nombre in cuadernos:
            if not(root/'notebooks'/(nombre+'.ipynb')).is_file():raise FileNotFoundError('Falta un cuaderno vigente: '+nombre)
        validation.append({'ficha':ident,'modulo':module,'funciones':functions,'cuadernos':cuadernos})
        out.extend([r'\Needspace{100mm}',r'\subsection{'+title+r'}\label{calc:'+ident+'}',r'\textbf{Entradas y transformación.} '+inputs,
            r'\textbf{Código que consultar.} \Ruta{src/movilidad_teide/'+module+r'}. Funciones: '+', '.join(r'\Ruta{'+f+'}' for f in functions)+'.',
            r'\textbf{Cuadernos del recorrido.} '+', '.join(r'\Ruta{notebooks/'+n+'.ipynb}' for n in cuadernos)+'.',r'\textbf{Resultados de lectura.} Carpeta común \Ruta{data/gold/anexos/}: '+', '.join(r'\Ruta{'+f+'}' for f in outputs)+'.',r'\textbf{Trazabilidad.} \Ruta{manifiestos/trazabilidad_anexos.csv} identifica el archivo y \Ruta{manifiestos/trazabilidad_columnas.csv}, sus campos; \Ruta{manifiestos/trazabilidad_preparacion_balance.csv} detalla la preparación.',r'\textbf{Qué comprobar.} '+checks,r'\textbf{Límites.} '+limits])
    (folder/'guia_calculos_completa.tex').write_text('\n\n'.join(out)+'\n')
    return validation


def _figuras(destino,datos,comp):
    plt.rcParams.update({'font.family':'Liberation Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    def save(fig,name):
        formatear_ejes(fig)
        for ext in ['pdf','svg','png']:fig.savefig(destino/'figuras'/(name+'.'+ext),dpi=180,bbox_inches='tight')
        plt.close(fig)
    def box(ax,x,y,w,h,text,color=AZUL):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.008',fc='#EFF5F8' if color==AZUL else '#EEF5F2',ec=color,lw=1.3))
        ax.text(x+w/2,y+h/2,text,ha='center',va='center',fontsize=10,color=color)
    def arrow(ax,a,b):ax.annotate('',xy=b,xytext=a,arrowprops={'arrowstyle':'->','color':GRIS,'lw':1.3})
    fig,ax=plt.subplots(figsize=(8,8));ax.axis('off');ax.set(xlim=(0,1),ylim=(0,1))
    box(ax,.05,.85,.9,.12,'FUENTES Y CONFIGURACIÓN\n2.500.000 visitas · 366 fechas · distribución territorial y modal')
    box(ax,.03,.61,.44,.16,'SIN INTERVENCIÓN\nCoche directo y visita interior\nExcursiones y acceso TITSA')
    box(ax,.53,.61,.44,.16,'CON INTERVENCIÓN\nCupo + coche a cabeceras\nLanzaderas integradas y excursiones',JADE)
    arrow(ax,(.3,.85),(.25,.78));arrow(ax,(.7,.85),(.75,.78))
    box(ax,.05,.39,.9,.13,'ACTIVIDAD EFECTIVA Y FACTORES\nRecorridos y vehículos · comerciales y vacíos · ejecución programática COPERT\nAjuste gravitatorio convencional de turismos')
    arrow(ax,(.25,.61),(.3,.53));arrow(ax,(.75,.61),(.7,.53))
    box(ax,.05,.19,.9,.12,'ENERGÍA IDENTIFICADA SIN Y CON\nResta dentro de cada asignación · MWh y tep · energía por visita',JADE)
    arrow(ax,(.5,.39),(.5,.32));arrow(ax,(.5,.19),(.5,.13))
    ax.text(.5,.075,'Sensibilidad → condiciones de explotación → seguimiento',ha='center',color=AZUL)
    save(fig,'cadena_calculo_integrada')
    fig,ax=plt.subplots(figsize=(8,6.5));ax.axis('off');ax.set(xlim=(0,1),ylim=(0,1))
    box(ax,.04,.86,.92,.10,'2028 · 2.500.000 visitas en ambos escenarios')
    box(ax,.04,.59,.92,.20,'SIN INTERVENCIÓN\nCoche: acceso + visita interior + regreso\nExcursión: acceso + visita interior + regreso en su autocar\nLíneas TITSA 342 y 348 de acceso')
    box(ax,.04,.12,.92,.40,'CON INTERVENCIÓN\nCoche autorizado: acceso + visita interior + regreso en su coche\nCoche a cabecera; después, acceso + interior + vuelta en lanzadera\nExcursión: acceso + visita interior + regreso en su autocar\n\nCupo: 650 coches/día; 700 o 750 en fechas previstas\nLanzaderas propias: hasta 27 en ordinaria; 28 o 30 en punta',JADE)
    arrow(ax,(.5,.86),(.5,.80));arrow(ax,(.5,.59),(.5,.53))
    ax.text(.5,.04,'Servicios comunes sin consumo absoluto cuantificado: explicados por separado',ha='center',fontsize=9,color=GRIS)
    save(fig,'escenarios_integrados')
    alts=comp.asignacion.unique();labels=['Coche directo\ne interior','Excursiones','TITSA de acceso','Coche a\ncabeceras','Alimentación\nviajeros TITSA','Lanzaderas\ncomerciales','Lanzaderas\nen vacío','Posicionamiento']
    order=['Coches directos e interior','Excursiones','TITSA de acceso','Coche a cabeceras','Alimentación de viajeros de TITSA','Lanzaderas comerciales','Lanzaderas en vacío','Posicionamiento externo']
    fig,axes=plt.subplots(2,1,figsize=(8,7.5),sharex=True)
    for ax,alt in zip(axes,alts):
        q=comp[comp.asignacion.eq(alt)].set_index('componente').loc[order];y=np.arange(len(q));mid=(q.con_min_mwh+q.con_max_mwh)/2
        ax.barh(y-.17,q.sin_mwh,height=.3,color=AZUL,label='Sin intervención')
        ax.barh(y+.17,mid,height=.3,color=JADE,label='Con intervención')
        spread=(q.con_max_mwh-q.con_min_mwh)/2;mask=spread.gt(1e-9)
        ax.errorbar(mid[mask],(y+.17)[mask],xerr=spread[mask],fmt='none',ecolor=GRIS,capsize=3)
        ax.set(yticks=y,yticklabels=labels,xlabel='MWh/año',title=alt.replace(':',' en'));ax.invert_yaxis();ax.grid(axis='x',alpha=.12)
    axes[0].errorbar([],[],xerr=1,fmt='none',ecolor=GRIS,capsize=3,label='Rango de cálculo del coche a cabeceras');axes[0].legend(loc='lower right',frameon=False,fontsize=8);fig.tight_layout();save(fig,'balance_componentes_actual')
    fig,axes=plt.subplots(2,1,figsize=(8,7.2),sharex=True)
    for ax,alt in zip(axes,alts):
        q=comp[comp.asignacion.eq(alt)].set_index('componente').loc[order];s=q.sin_mwh-(q.con_min_mwh+q.con_max_mwh)/2
        ax.barh(np.arange(len(s)),s,color=[JADE if z>=0 else NARANJA for z in s])
        spread=(q.con_max_mwh-q.con_min_mwh)/2;mask=spread.gt(1e-9)
        ax.errorbar(s[mask],np.arange(len(s))[mask],xerr=spread[mask],fmt='none',ecolor=GRIS,capsize=3)
        ax.axvline(0,color=GRIS,lw=.8);ax.set(yticks=np.arange(len(s)),yticklabels=labels,xlabel='Saldo sin − con (MWh/año)',title=alt.replace(':',' en'));ax.invert_yaxis();ax.grid(axis='x',alpha=.12)
        sec=ax.secondary_xaxis('top',functions=(lambda z:z/11.63,lambda z:z*11.63));sec.set_xlabel('Misma energía en tep/año')
    axes[0].errorbar([],[],xerr=1,fmt='none',ecolor=GRIS,capsize=3,label='Rango de cálculo del coche a cabeceras');axes[0].legend(loc='lower right',frameon=False,fontsize=8)
    fig.tight_layout(h_pad=2);save(fig,'formacion_ahorro_actual')
    phys=datos['analisis_integracion']['sensibilidad_fisica']
    choices=[n for n in phys['Contraste físico'].unique() if n!='Sin ajuste gravitatorio convencional']
    fig,ax=plt.subplots(figsize=(8,4.8))
    labels=['Mediana y parámetros principales','Tara del cuartil inferior','Tara del cuartil superior','Transmisión 0,95','Sin reducción en descenso']
    for label,offset,color in [('Consumo en caliente',-.13,JADE),('Contraste FTA de lanzaderas y posicionamiento',.13,NARANJA)]:
        for i,name in enumerate(choices):
            g=phys[phys['Contraste físico'].eq(name)&phys['Tratamiento energético'].eq(label)]
            lo=g['Ahorro mínimo (tep)'].min();hi=g['Ahorro máximo (tep)'].max();mid=(lo+hi)/2
            ax.errorbar(mid,i+offset,xerr=[[mid-lo],[hi-mid]],fmt='o',capsize=3,color=color,label=('En caliente' if label=='Consumo en caliente' else 'Climatización y ralentí') if i==0 else None)
    ax.axvline(60,ls='--',color=AZUL,lw=1);ax.set(yticks=range(len(choices)),yticklabels=labels,xlabel='Ahorro identificado (tep/año)',xlim=(0,820));ax.invert_yaxis();ax.legend(frameon=False,loc='upper right');ax.grid(axis='x',alpha=.15)
    fig.tight_layout();save(fig,'sensibilidad_fisica_actual')
