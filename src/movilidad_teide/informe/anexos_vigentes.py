"""Selección de anexos comprensibles de la referencia efectiva de 2028."""
from pathlib import Path
from .edicion import VERSION,FECHA,ANEXOS,PAQUETE,REPOSITORIO,normalizar_libro,escribir_zip
from collections import Counter
from types import SimpleNamespace
import csv,json,re,zipfile,hashlib
import numpy as np
import pandas as pd
from movilidad_teide.flujos.ordenacion_vigente import _preparar_factores,_leer
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.flujos.compartida_2028 import BASE,PARADAS
from movilidad_teide.informe.temporal import datos_temporales
from movilidad_teide.trazabilidad import sha256_archivo
from movilidad_teide.energia.titsa import leer_producto

NODOS={'cabecera:CHIO':'Cabecera de Chío','cabecera:LAGUNA':'Cabecera de La Esperanza','cabecera:OROTAVA':'Cabecera de Aguamansa','cabecera:VILAFLOR':'Cabecera de Vilaflor','interior_boca_eje_principal':'Boca Tauce · eje principal','interior_portillo_eje_principal':'El Portillo · eje principal','entrada_parador_tf21':'Entrada de Parador / Cañada Blanca','entrada_teleferico_tf21':'Entrada del Teleférico'}
CAB={'CHIO':'Chío','LAGUNA':'La Esperanza','OROTAVA':'Aguamansa','VILAFLOR':'Vilaflor'}
COLECTIVOS={'tenerife_no_frecuente':'Tenerife: no frecuentes','tenerife_resto':'Tenerife: resto del colectivo','extranjero':'Extranjeros','espana_no_tenerife':'España no Tenerife','tinerfeno':'Tenerife','tinerfenos':'Tenerife','local':'Tenerife','tenerife':'Tenerife','frecuente':'Frecuentes','frecuentes':'Frecuentes'}
ESPEC={}
def campo(nombre,unidad,significado,ausencia='No admitida'):
    definition=(unidad,significado,ausencia)
    if nombre in ESPEC and ESPEC[nombre]!=definition:raise ValueError('Definición contradictoria: '+nombre)
    ESPEC[nombre]=definition
    return nombre

def basicos():
    for n,u,d in [('Fecha','fecha ISO','Fecha del calendario de planificación de 2028.'),('Régimen','categoría','Ordinaria, punta o total anual; la punta puede detallarse por número de propias programadas.'),('Asignación de turismos','categoría','Tipo de coche de España no Tenerife; Tenerife usa particular y extranjeros, alquiler en ambas asignaciones.'),('Tratamiento energético','categoría','Consumo en caliente o contraste FTA aplicado una vez solo a lanzaderas y posicionamiento.'),('Colectivo','categoría','Grupo de residencia/frecuencia de la fuente; no censo de conductores.'),('Origen representativo','lugar','Referencia territorial de cálculo; no dirección observada de cada visitante.'),('Cabecera de referencia','lugar','Cabecera habitual del origen antes de una posible reasignación.'),('Autobús','identidad descriptiva','Nombre de estudio de la unidad propia, con base inicial; no matrícula ni vehículo contratado.'),('Base inicial','lugar','Ubicación al inicio de la fecha, o del inventario si la tabla es inicial.'),('Base final','lugar','Ubicación al terminar la fecha. Se conserva equilibrio por base y continuidad, no retorno individual obligatorio a la base inicial.'),('Origen del movimiento','lugar','Nodo de salida del movimiento completo.'),('Destino del movimiento','lugar','Nodo de llegada del movimiento completo.'),('Tipo de movimiento','categoría','Comercial o tipo de reposición en vacío; todos cuentan en energía.'),('Número de movimiento','ordinal por fecha','Identificador legible único dentro de la fecha; permite enlazar reservas y movimientos.'),('Visitas totales','visitas-persona','Entradas de personas del ámbito de la fila; regreso e interior no añaden visitas.'),('Visitas en coche','visitas-persona','Personas que entran al Parque en coches autorizados.'),('Visitas en excursión','visitas-persona','Personas del resto colectivo representado como excursiones.'),('Visitas en lanzadera','visitas-persona','Personas atendidas por lanzaderas nuevas; una visita incluye ida y regreso.'),('Propias programadas','vehículos físicos/fecha','Unidades propias distintas que realizan movimientos, reutilizadas en varias expediciones.'),('Sustitutas disponibles','vehículos físicos/fecha','Unidades no programadas propias y externas disponibles para sustitución.'),('Externas disponibles','vehículos físicos/fecha','Unidades externas disponibles para sustituir; no implica expediciones comerciales programadas.'),('Cupo máximo','coches/fecha','Máximo global de entrada al Parque; reparto territorial estimado, sin cuotas regulatorias por carretera.'),('Entradas de coches','entradas de vehículo','Visitas en coche divididas entre 3,2 personas/coche.'),('Expediciones comerciales','trayectos en un sentido','Cada ida y cada regreso cuentan como una expedición.'),('Movimientos en vacío','trayectos en un sentido','Reposiciones iniciales, entre servicios y de cierre sin pasajeros.'),('Kilómetros comerciales','vehículos-km','Suma de distancias de los movimientos comerciales.'),('Kilómetros en vacío','vehículos-km','Suma de distancias de las reposiciones en vacío.'),('Pasajeros comerciales','embarques','Personas transportadas por las expediciones; ida y regreso son dos embarques.'),('Plazas comerciales','plazas ofertadas','46 por expedición comercial; los vacíos ofertan cero plazas comerciales.'),('Ocupación de diseño','% de plazas comerciales','Pasajeros comerciales / plazas comerciales × 100. No carga física COPERT ni ocupación uniforme.'),('Personas por autocar equivalente','personas/equivalente','Hipótesis de conversión de excursiones; no capacidad nominal.'),('Autocares equivalentes','equivalentes','Visitas en excursión / 35,99; no autobuses físicos contratados.'),('Días representados','fechas','Número de fechas efectivas agregadas, no predicción de extremos.'),('Unidad propia disponible','sí/no','Sí si está sin movimientos programados en esa fecha.'),('Propias disponibles','vehículos físicos','Inventario propio inicial de la base.'),('Cabecera original','lugar','Cabecera de referencia anterior al traslado de la reserva.'),('Cabecera asignada y de regreso','lugar','Cabecera alternativa donde se aparca y a la que se regresa.'),('Visitas reasignadas','visitas-persona','Visitas cuyo coche llega a una cabecera alternativa; no visitas adicionales.'),('Distancia','km','Distancia por movimiento completo o tramo definido por la fila, en un sentido.'),('Tiempo de recorrido','minutos','Tiempo operativo conservado para enlazar movimientos; no velocidad legal.'),('Inicio en minutos','minutos desde 00:00','Hora local canaria sin redondeo usada para comprobaciones.'),('Fin en minutos','minutos desde 00:00','Llegada local canaria sin redondeo usada para comprobaciones.'),('Hora de salida','HH:MM:SS','Lectura de hora local redondeada al segundo; los minutos exactos permiten validar.'),('Hora de llegada','HH:MM:SS','Lectura de llegada local redondeada al segundo.'),('Visitas del grupo','visitas-persona','Personas que comparten una reserva/cadena modelizada; pueden ser fraccionarias por ponderación.'),('Estancia dentro del Parque','minutos','Regreso por la entrada menos entrada al Parque; debe ser al menos 120.'),('Entrada al Parque','minutos desde 00:00','Paso de ida por la entrada, no llegada al punto interior.'),('Regreso por la entrada','minutos desde 00:00','Paso de regreso por la entrada; delimita la estancia mínima.'),('Destino de visita','lugar','Punto interior representado; no parada o conexión peatonal aprobada.'),('Movimiento de ida','ordinal por fecha','Número del movimiento comercial de ida de la misma fecha.'),('Movimiento de regreso','ordinal por fecha','Número del movimiento comercial de regreso de la misma fecha.'),('Componente','categoría','Partida energética diferenciada; los comunes no cuantificados se describen por separado.'),('Ámbito','texto','Población, perímetro o tramo de aplicación explícito.'),('Límite de interpretación','texto','Condición o incertidumbre que impide extender el alcance del dato.')]:campo(n,u,d)
    for n in ['Visitas sin en coche','Visitas con en coche','Visitas sin en excursión','Visitas con en excursión','Visitas transferidas desde coche']:
        campo(n,'visitas-persona','Cantidad anual por origen/colectivo del modo y escenario indicado; no incluye TITSA repartida ficticiamente por origen.')
    for n in ['Sin','Con mínimo','Con máximo','Ahorro mínimo','Ahorro máximo']:
        for u in ['MWh','tep','MWh/visita','tep/visita','kWh/visita']:
            campo(n+' ('+u+')',u,'Energía identificada '+n.lower()+' del periodo/ámbito de la fila; extremos técnicos dentro de la misma asignación, no intervalos de confianza.')
    campo('Ocupación de diseño','% de plazas comerciales','Pasajeros comerciales / plazas comerciales × 100. No carga física COPERT ni ocupación uniforme.')


def _asignar(s):return s.str.replace('España no Tenerife: ','España no Tenerife en ',regex=False)
def _tratamiento(s):return s.map(lambda x:'Consumo en caliente' if x=='Hot COPERT' else 'Contraste FTA de lanzaderas y posicionamiento')
def _nodos(s):
    z=s.map(NODOS)
    if z.isna().any():raise ValueError('Hay un nodo sin nombre explícito.')
    return z

def energias(df,visitas,conv=11.63):
    """Bloque homogéneo de cinco energías, sin cruzar asignaciones."""
    out=pd.DataFrame(index=df.index)
    for key,label in [('sin','Sin'),('con_min','Con mínimo'),('con_max','Con máximo'),('ahorro_min','Ahorro mínimo'),('ahorro_max','Ahorro máximo')]:
        a=df[key].astype(float);out[label+' (MWh)']=a;out[label+' (tep)']=a/conv
        out[label+' (MWh/visita)']=a/visitas;out[label+' (tep/visita)']=a/visitas/conv;out[label+' (kWh/visita)']=a/visitas*1000
    return out


class Anexos:
    def __init__(self,path):
        self.path=Path(path);self.path.mkdir();self.tablas={};self.indice=[];self.diccionario=[]
    def agregar(self,name,title,df,source,grain,scope,periodo='2028'):
        if set(df.columns)-set(ESPEC):raise ValueError('Campos sin definición: '+str(set(df.columns)-set(ESPEC)))
        if df.columns.duplicated().any():raise ValueError('Cabeceras repetidas.')
        for c in df:
            if df[c].isna().any() and ESPEC[c][2]=='No admitida':raise ValueError('Ausencia sin explicar: '+name+'/'+c)
        for col in df.select_dtypes(include=['object','str']).columns:
            bad=df[col].dropna().astype(str).str.contains(r'(?<![A-Za-z])[DHF]\d{3}(?!\d)|E_M\d{2}|Q650_L|M\d+__|TF\d{2}$',regex=True)
            if bad.any():raise ValueError('Código interno sin traducir en '+name+': '+col)
        df.to_csv(self.path/(name+'.csv'),sep=';',decimal=',',index=False,encoding='utf-8-sig',float_format='%.17g')
        self.tablas[name]=(title,df)
        self.indice.append({'Archivo':name+'.csv','Contenido':title,'Filas':len(df),'Granularidad':grain,'Periodo':periodo,'Ámbito':scope,'Fuente y método':source})
        for col in df:
            unit,meaning,absence=ESPEC[col]
            self.diccionario.append({'Archivo':name+'.csv','Columna':col,'Tipo':('Número entero' if pd.api.types.is_integer_dtype(df[col]) else 'Número decimal' if pd.api.types.is_numeric_dtype(df[col]) else 'Texto'),'Unidad':unit,'Periodo':periodo,'Ámbito':scope,'Significado':meaning,'Ausencias':absence,'Fuente y cálculo':source})


def generar_anexos_vigentes(root,destino,datos):
    root=Path(root);destino=Path(destino);basicos();out=Anexos(destino/'anexos_vigentes');t=datos['tablas'];cfg=datos['referencia']['valores'];ref=datos['referencia'];C=root/ref['indice']['captura'];N=cfg['visitas_anio'];conv=cfg['mwh_por_tep'];ctx=SimpleNamespace(root=root,energia=root/ref['indice']['energia'],excepciones=root/ref['indice']['excepciones'],cfg=cfg,v=ref['valores_modelo'],inv=t['inventario_bases'],red=RedOperativa(_leer(root/BASE/'movimientos_diagnosticos.csv'),_leer(root/BASE/'pares_diagnosticos.csv'),_leer(root/PARADAS)))
    ctx.hh=_leer(root/ref['indice']['demanda_horaria']);ctx.hh=ctx.hh[ctx.hh.metodo_calendario.eq('Estacional')]
    factors=_preparar_factores(ctx)
    source='Configuración efectiva, calendario y circulaciones programadas; consumo obtenido con factores de ejecuciones programáticas de COPERT y agregación de la actividad.'
    def add(n,title,z,grain,scope='Movilidad identificada del ámbito de estudio',src=source,periodo='2028'):out.agregar(n,title,z,src,grain,scope,periodo)
    from movilidad_teide.informe.integracion import nombre_parametro
    # Parámetros efectivos explícitos; no se publican elecciones inactivas.
    pp=[]
    for key,value in cfg.items():
        spec=ref['indice']['parametros_de_la_referencia'][key]
        pp.append({'Parámetro':nombre_parametro(key,spec),'Valor':value,'Unidad':spec['unidad'],'Aplicación':'Sensibilidad complementaria' if key.startswith('sensibilidad_') else 'Referencia de cálculo vigente'})
    for n,u,d in [('Parámetro','texto','Nombre completo de la elección efectiva.'),('Valor','según columna Unidad','Valor de estudio, sin elecciones inactivas.'),('Unidad','texto','Unidad o escala del valor de la fila; una fracción no es un porcentaje entero.'),('Aplicación','texto','Referencia principal o sensibilidad vigente que utiliza la elección.')]:campo(n,u,d)
    add('parametros_vigentes','Configuración efectiva',pd.DataFrame(pp),'Parámetro')
    physicalkeys=['velocidad_turismo_local','velocidad_turismo_convencional','velocidad_turismo_rapida','velocidad_copert','masa_persona_turismo_kg','equipaje_turismo_kg_coche']
    phys=[{'Parámetro':p['parametro'],'Valor':p['valor_utilizado'],'Unidad':p['unidad'],'Aplicación':'Factor de circulación y corrección física de referencia'} for p in ref['base']['parametros'] if p['id'] in physicalkeys]
    phys += [{'Parámetro':'Carga técnica COPERT en comercial','Valor':50,'Unidad':'%','Aplicación':'Factor de autocar; no porcentaje de asientos ocupados'},{'Parámetro':'Carga técnica COPERT en vacío','Valor':0,'Unidad':'%','Aplicación':'Factor de autocar en reposición'},{'Parámetro':'Conversión de trabajo gasolina','Valor':ctx.v['eficiencia_incremental_gasolina_pendiente'],'Unidad':'fracción','Aplicación':'0,40 × 0,85, ajuste convencional de pendiente'},{'Parámetro':'Conversión de trabajo diésel','Valor':ctx.v['eficiencia_incremental_diesel_pendiente'],'Unidad':'fracción','Aplicación':'0,48 × 0,85, ajuste convencional de pendiente'}]
    add('parametros_fisicos','Condiciones físicas y de los factores utilizados',pd.DataFrame(phys),'Parámetro',src='Libro y coeficientes físicos de consumo aplicados; no son mediciones locales.')
    # Cuentas anuales completas por asignación y tratamiento.
    annual=pd.concat([t['central'],t['fta']],ignore_index=True)
    vals=annual.rename(columns={'sin_identificado_mwh':'sin','con_identificado_min_mwh':'con_min','con_identificado_max_mwh':'con_max','ahorro_min_mwh':'ahorro_min','ahorro_max_mwh':'ahorro_max'})
    a=pd.DataFrame({'Asignación de turismos':_asignar(vals.asignacion_turismos),'Tratamiento energético':_tratamiento(vals.tratamiento),'Visitas totales':N})
    a=pd.concat([a,energias(vals,N,conv)],axis=1);add('balance_anual','Consumos sin/con y ahorro anual',a,'Asignación y tratamiento')
    rawcomp=_leer(destino/'anexos/componentes_identificados.csv');comp=rawcomp.rename(columns={'componente':'Componente','sin_mwh':'Sin (MWh)','con_min_mwh':'Con mínimo (MWh)','con_max_mwh':'Con máximo (MWh)'})
    comp['Asignación de turismos']=_asignar(rawcomp.asignacion);comp=comp.drop(columns='asignacion')
    for k in ['Sin','Con mínimo','Con máximo']:comp[k+' (tep)']=comp[k+' (MWh)']/conv
    add('energia_componentes','Ocho componentes de energía identificados',comp,'Componente y asignación')
    cal=t['calendario_operativo'];calendar=cal.rename(columns={'fecha':'Fecha','regimen':'Régimen','programadas':'Propias programadas','cupo':'Cupo máximo','externas_disponibles':'Externas disponibles','sin_programar':'Sustitutas disponibles','visitas_sin_dia':'Visitas totales','visitas_coche_dia':'Visitas en coche','visitas_excursion_dia':'Visitas en excursión','visitas_lanzadera_dia':'Visitas en lanzadera','expediciones_comerciales':'Expediciones comerciales','movimientos_vacios':'Movimientos en vacío','km_comerciales':'Kilómetros comerciales','km_vacios':'Kilómetros en vacío'})
    calendar=calendar[[c for c in calendar if c in ESPEC]];calendar['Entradas de coches']=calendar['Visitas en coche']/cfg['ocupacion_coche'];add('calendario_diario','Programación y demanda de las 366 fechas',calendar,'Fecha')
    summary=calendar.groupby(['Régimen','Propias programadas'],as_index=False).agg(**{'Días representados':('Fecha','size'),'Visitas totales':('Visitas totales','sum'),'Visitas en coche':('Visitas en coche','sum'),'Visitas en excursión':('Visitas en excursión','sum'),'Visitas en lanzadera':('Visitas en lanzadera','sum'),'Expediciones comerciales':('Expediciones comerciales','sum'),'Movimientos en vacío':('Movimientos en vacío','sum')})
    summary['Pasajeros comerciales']=2*summary['Visitas en lanzadera'];summary['Plazas comerciales']=46*summary['Expediciones comerciales'];summary['Ocupación de diseño']=100*summary['Pasajeros comerciales']/summary['Plazas comerciales'];summary['Personas por autocar equivalente']=cfg['ocupacion_guagua_aforo'];summary['Autocares equivalentes']=summary['Visitas en excursión']/cfg['ocupacion_guagua_aforo'];add('programacion_anual','Los seis tamaños de programación y su actividad',summary,'Régimen y unidades propias programadas')
    # Energía diaria y regímenes, con posicionamiento solo en activaciones.
    day=datos_temporales(datos);parts=[]
    for method in ['Consumo en caliente','Contraste FTA de lanzaderas y posicionamiento']:
        z=day.copy();extra=np.zeros(len(z))
        if method!='Consumo en caliente':
            dd=t['actividad_diaria'][['fecha','asignacion_turismos','con_lanzadera_comercial_mwh_dia','con_lanzadera_vacia_mwh_dia']]
            e=z[['fecha','asignacion_turismos','posicionamiento_mwh_dia']].merge(dd,on=['fecha','asignacion_turismos'],validate='one_to_one')
            extra=(e.con_lanzadera_comercial_mwh_dia+e.con_lanzadera_vacia_mwh_dia+e.posicionamiento_mwh_dia)/9
        v=pd.DataFrame({'sin':z.sin_mwh_dia,'con_min':z.con_min_mwh_dia+extra,'con_max':z.con_max_mwh_dia+extra,'ahorro_min':z.ahorro_min_mwh_dia-extra,'ahorro_max':z.ahorro_max_mwh_dia-extra})
        pub=pd.DataFrame({'Fecha':z.fecha,'Régimen':z.regimen,'Propias programadas':z.programadas,'Asignación de turismos':_asignar(z.asignacion_turismos),'Tratamiento energético':method,'Visitas totales':z.visitas_sin_dia})
        parts.append(pd.concat([pub,energias(v,z.visitas_sin_dia,conv)],axis=1))
    daily=pd.concat(parts,ignore_index=True);add('energia_diaria','Energía de cada fecha y por visita',daily,'Fecha, asignación y tratamiento',periodo='Cada fecha de 2028')
    cols=['Visitas totales']+[c for c in daily if c.endswith('(MWh)')]
    detail=daily.copy()
    peak=detail['Régimen'].eq('Punta')
    detail.loc[peak,'Régimen']=detail.loc[peak,'Propias programadas'].map({28:'Punta: 28 propias',30:'Punta: 30 propias'})
    agg=detail.groupby(['Régimen','Asignación de turismos','Tratamiento energético'],as_index=False)[cols].sum()
    year=agg.groupby(['Asignación de turismos','Tratamiento energético'],as_index=False)[cols].sum();year['Régimen']='Año completo';reg=pd.concat([agg,year],ignore_index=True)
    values=reg.rename(columns={label+' (MWh)':name for name,label in [('sin','Sin'),('con_min','Con mínimo'),('con_max','Con máximo'),('ahorro_min','Ahorro mínimo'),('ahorro_max','Ahorro máximo')]})
    pub=pd.concat([reg[['Régimen','Asignación de turismos','Tratamiento energético','Visitas totales']],energias(values,reg['Visitas totales'],conv)],axis=1);add('balance_regimenes','Cuentas ordinaria, punta y año completo',pub,'Régimen, asignación y tratamiento')
    for _,r in year.iterrows():
        match=a[(a['Asignación de turismos']==r['Asignación de turismos'])&(a['Tratamiento energético']==r['Tratamiento energético'])].iloc[0]
        np.testing.assert_allclose(r[cols].astype(float),match[cols].astype(float),atol=1e-8,rtol=0)
    s=t['sensibilidad_excursiones'];rename={'visitas':'Visitas totales','visitas_coche':'Visitas en coche','visitas_excursion':'Visitas en excursión','visitas_lanzadera':'Visitas en lanzadera','expediciones':'Expediciones comerciales','vacios':'Movimientos en vacío','ocupacion_diseno_pct':'Ocupación de diseño'}
    z=s.rename(columns=rename);ss=z[[*rename.values()]].copy();ss['Asignación de turismos']=_asignar(s.asignacion_turismos);ss['Tratamiento energético']=_tratamiento(s.tratamiento)
    campo('Incremento de excursiones','% de visitas en excursión sin proyecto','Multiplica sus visitas sin por 1 + incremento/100; los nuevos viajeros proceden de lanzadera, sin añadir visitantes.')
    campo('Oferta de lanzaderas','categoría','Conservada: todas las circulaciones principales; ajustada: selección de circulaciones físicas comprobadas según demanda restante.')
    ss['Incremento de excursiones']=100*s.incremento_excursiones;ss['Oferta de lanzaderas']=s.oferta.str.replace('Oferta ','',regex=False);ss['Personas por autocar equivalente']=35.99;ss['Autocares equivalentes']=s.visitas_excursion/35.99
    ss=pd.concat([ss,energias(s.rename(columns={'sin_mwh':'sin','con_min_mwh':'con_min','con_max_mwh':'con_max','ahorro_min_mwh':'ahorro_min','ahorro_max_mwh':'ahorro_max'}),s.visitas,conv)],axis=1);campo('Tratamiento de excursiones','hipótesis energética','Factor plano sin corrección de pendiente. El bloque se cancela solo en el principal con actividad idéntica; cuando crece la excursión afecta al ahorro estimado.')
    ss['Tratamiento de excursiones']='Factor plano; sin corrección de pendiente'
    add('sensibilidad_excursiones','Excursiones adicionales y ajuste efectivo de lanzaderas',ss,'Incremento, oferta, asignación y tratamiento')
    pos=leer_producto(root,ref,'balance_anual_politicas.csv');pos=pos[pos.politica.eq(cal.politica.iloc[0])]
    if len(pos)!=12:raise ValueError('Selección de posicionamiento no unívoca.')
    p=pd.DataFrame({'Asignación de turismos':_asignar(pos.asignacion_turismos),'Tratamiento energético':_tratamiento(pos.tratamiento),'Visitas totales':pos.visitas_objetivo_sin_y_con,'Distancia de posicionamiento':pos.km_posicionamiento_unidad_activacion})
    campo('Distancia de posicionamiento','km/unidad disponible/activación','Distancia total de ida y retirada por apoyo disponible, sin modificar los servicios comerciales.')
    p=pd.concat([p,energias(pos.rename(columns={'sin_identificado_mwh':'sin','con_identificado_min_mwh':'con_min','con_identificado_max_mwh':'con_max','ahorro_min_mwh':'ahorro_min','ahorro_max_mwh':'ahorro_max'}),N,conv)],axis=1);add('sensibilidad_posicionamiento','Posicionamiento de apoyos con 0, 50 y 100 km',p,'Distancia, asignación y tratamiento')
    # Nombres geográficos tomados del catálogo, sin cantidades de resultados previos.
    geo=_leer(root/'data/silver/demanda/asignacion/recorridos_referencia_calculo.csv');orig=_leer(root/'data/silver/demanda/asignacion/origenes_representativos.csv').set_index('origen_id');catalog=json.loads((root/'config/itinerarios.json').read_text());compar={}
    for col in ['origin_access_comparisons','coastal_valley_comparisons','study_origin_access_comparisons']:compar.update(catalog.get(col,{}))
    names={}
    for r in geo[geo.sentido.eq('hacia_teide')].itertuples():
        names[r.origen_id]=compar.get(r.comparacion_calculo_id,{}).get('origin_label',orig.loc[r.origen_id,'municipio_referencia'])
        if r.comparacion_calculo_id=='columbus_vilaflor':names[r.origen_id]='Referencia costera de Arona'
        if r.comparacion_calculo_id=='duque_chio':names[r.origen_id]='Referencia costera de Adeje'
    originparts=[];transfers=[];reserveparts=[]
    for (q,mx,profile),dates in cal.groupby(['cupo','max_programadas_programa','perfil'],sort=True):
        folder=C/'ofertas'/str(q)/str(mx)/profile;x=_leer(folder/'origenes.csv');rr=_leer(folder/'reservas.csv');tr=_leer(folder/'traslados.csv') if (folder/'traslados.csv').stat().st_size>3 else pd.DataFrame()
        z=x[['origen_id','colectivo','punto','visitas_coche','visitas_coche_autorizadas_dia','visitas_excursiones_resto_colectivo','visitas_excursiones_con_intervencion_dia','visitas_coche_transferidas_dia']].copy();numeric=list(z.columns[3:]);z[numeric]*=len(dates);originparts.append(z)
        for date in dates.fecha:
            if len(tr):transfers.append(tr.assign(fecha=date))
            reserveparts.append(rr.assign(fecha=date))
    oo=pd.concat(originparts).groupby(['origen_id','colectivo','punto'],as_index=False)[numeric].sum();oo['Origen representativo']=oo.origen_id.map(names);oo['Colectivo']=oo.colectivo.map(COLECTIVOS);oo['Cabecera de referencia']=oo.punto.map(CAB)
    if oo[['Origen representativo','Colectivo','Cabecera de referencia']].isna().any().any():raise ValueError('Origen o colectivo sin traducción.')
    oo=oo.rename(columns=dict(zip(numeric,['Visitas sin en coche','Visitas con en coche','Visitas sin en excursión','Visitas con en excursión','Visitas transferidas desde coche'])));oo=oo[[c for c in oo if c in ESPEC]].sort_values(['Origen representativo','Colectivo']).reset_index(drop=True);add('visitas_origen_colectivo','Visitas anuales de coche y excursión por origen y colectivo',oo,'Origen, colectivo y cabecera habitual','Solo coche y excursiones con correspondencia territorial; TITSA no se reparte ficticiamente por origen.')
    hh=ctx.hh;v=hh.groupby('colectivo').apply(lambda g:pd.Series({c:float((g[c]*g.dias_calendario).sum()) for c in ['visitas_coche','visitas_titsa','visitas_excursiones_resto_colectivo']}),include_groups=False);mode=[]
    for collective,r in v.iterrows():
        for scenario in ['Sin intervención','Con intervención']:
            for mode_name,n in [('Coche',r.visitas_coche if scenario.startswith('Sin') else oo.loc[oo.Colectivo.eq(COLECTIVOS[collective]),'Visitas con en coche'].sum()),('Excursiones / resto colectivo',r.visitas_excursiones_resto_colectivo),('TITSA de acceso',r.visitas_titsa if scenario.startswith('Sin') else 0),('Lanzaderas nuevas',0 if scenario.startswith('Sin') else r.visitas_titsa+oo.loc[oo.Colectivo.eq(COLECTIVOS[collective]),'Visitas transferidas desde coche'].sum())]:mode.append({'Colectivo':COLECTIVOS[collective],'Escenario':scenario,'Modo de acceso':mode_name,'Visitas totales':n})
    campo('Escenario','categoría','Sin intervención o con intervención; misma población anual.');campo('Modo de acceso','categoría','Modo que realiza la entrada de la visita; la alimentación en coche de una lanzadera no se cuenta otra vez como entrada.')
    modes=pd.DataFrame(mode);np.testing.assert_allclose(modes.groupby('Escenario')['Visitas totales'].sum(),[N,N],atol=1e-8,rtol=0);add('visitas_modos_colectivos','Visitas sin/con por modo y colectivo',modes,'Escenario, modo y colectivo')
    # Movimientos con identidades de estudio comprensibles y energía por ruta efectiva.
    inv=t['inventario_bases'].sort_values('unidad_fisica_id');bybase=Counter();unitlabels={}
    for r in inv.itertuples():bybase[r.base_red]+=1;unitlabels[r.unidad_fisica_id]='Autobús '+str(bybase[r.base_red])+' · '+NODOS[r.base_red]
    iv=pd.DataFrame({'Base inicial':[NODOS[k] for k in bybase],'Propias disponibles':list(bybase.values())});add('inventario_bases','Treinta unidades propias y sus bases iniciales',iv,'Base')
    m=_leer(root/'data/gold/referencia_anual/recomendada_movimientos_calendario.csv').sort_values(['fecha','salida_min','unidad_fisica_id']).reset_index(drop=True);m['Número de movimiento']=m.groupby('fecha').cumcount()+1
    rates={};usedarcs=set()
    for (u,v,comp),g in m.groupby(['origen','destino','componente']):
        route=ctx.red.conectar(u,v);load=.5 if comp=='comercial' else 0.;energy=sum(factors['factors'].loc[a,b,load] for a,b in route['arcos'])/3600;rates[u,v,comp]=energy
        usedarcs.update((a,b,load) for a,b in route['arcos'])
        np.testing.assert_allclose(g.km,route['km'],atol=1e-8,rtol=0)
    m['Energía en caliente (MWh)']=[rates[r.origen,r.destino,r.componente] for r in m.itertuples()]
    campo('Energía en caliente (MWh)','MWh','Combustible Hot del movimiento/tramo completo; no incluye un recargo FTA adicional.');campo('Energía en caliente (tep)','tep','Mismo consumo en caliente dividido entre 11,63.');campo('Plazas de diseño','plazas','46 en un comercial; cero plazas ofertadas en un vacío.');campo('Pasajeros','personas','Pasajeros de la expedición; cero explícito en vacío, no dato faltante.')
    pub=pd.DataFrame({'Fecha':m.fecha,'Número de movimiento':m['Número de movimiento'],'Autobús':m.unidad_fisica_id.map(unitlabels),'Origen del movimiento':_nodos(m.origen),'Destino del movimiento':_nodos(m.destino),'Tipo de movimiento':m.componente.map({'comercial':'Comercial','reposicion_inicial':'Vacío inicial','reposicion_entre_servicios':'Vacío entre servicios','reposicion_cierre':'Vacío de cierre'}),'Inicio en minutos':m.salida_min,'Fin en minutos':m.llegada_min,'Distancia':m.km,'Pasajeros':m.personas.where(m.componente.eq('comercial'),0),'Plazas de diseño':np.where(m.componente.eq('comercial'),46,0),'Energía en caliente (MWh)':m['Energía en caliente (MWh)']});pub['Energía en caliente (tep)']=pub['Energía en caliente (MWh)']/conv
    hhmm=lambda v:f'{int(round(v*60))//3600:02}:{int(round(v*60))//60%60:02}:{int(round(v*60))%60:02}'
    pub['Hora de salida']=pub['Inicio en minutos'].map(hhmm);pub['Hora de llegada']=pub['Fin en minutos'].map(hhmm)
    assert len(pub)==70075 and m.componente.eq('comercial').sum()==51428
    np.testing.assert_allclose(pub.Distancia.sum(),cal.km_comerciales.sum()+cal.km_vacios.sum(),atol=1e-8,rtol=0)
    expected=rawcomp[rawcomp.asignacion.eq(rawcomp.asignacion.iloc[0])&rawcomp.componente.isin(['Lanzaderas comerciales','Lanzaderas en vacío'])].con_min_mwh.sum();np.testing.assert_allclose(pub['Energía en caliente (MWh)'].sum(),expected,atol=1e-8,rtol=0);add('movimientos_lanzaderas','Movimientos comerciales y en vacío con energía',pub,'Fecha y número de movimiento')
    dis=_leer(root/'data/gold/referencia_anual/recomendada_disponibilidad_calendario.csv');ds=pd.DataFrame({'Fecha':dis.fecha,'Autobús':dis.unidad_fisica_id.map(unitlabels),'Unidad propia disponible':(~dis.programada).map({True:'Sí',False:'No'}),'Base inicial':_nodos(dis.base_inicial),'Base final':_nodos(dis.base_final)});assert len(ds)==10980;add('disponibilidad_unidades','Disponibilidad y bases de las treinta identidades',ds,'Fecha y autobús')
    # Reservas enlazadas con números de movimientos de la misma fecha.
    reserves=pd.concat(reserveparts,ignore_index=True);lookup=m[m.componente.eq('comercial')].set_index(['fecha','id_salida'])['Número de movimiento'].to_dict();rs=pd.DataFrame({'Fecha':reserves.fecha,'Cabecera asignada y de regreso':reserves.punto.map(CAB),'Destino de visita':_nodos(reserves.parada_destino),'Visitas del grupo':reserves.personas,'Entrada al Parque':reserves.entrada_parque_min,'Regreso por la entrada':reserves.regreso_parque_min,'Estancia dentro del Parque':reserves.regreso_parque_min-reserves.entrada_parque_min,'Movimiento de ida':[lookup[d,s] for d,s in zip(reserves.fecha,reserves.id_subida)],'Movimiento de regreso':[lookup[d,s] for d,s in zip(reserves.fecha,reserves.id_regreso)]});np.testing.assert_allclose(rs['Visitas del grupo'].sum(),cal.visitas_lanzadera_dia.sum(),atol=1e-8,rtol=0);assert rs['Estancia dentro del Parque'].min()>=120-1e-8;add('reservas_visita','Reservas completas de ida, visita y regreso',rs,'Fecha y pareja de movimientos')
    if transfers:
        tr=pd.concat(transfers,ignore_index=True);trpub=pd.DataFrame({'Fecha':tr.fecha,'Origen representativo':tr.origen_id.map(names),'Colectivo':tr.colectivo.map(COLECTIVOS),'Cabecera original':tr.punto_original.map(CAB),'Cabecera asignada y de regreso':tr.punto_reserva.map(CAB),'Visitas reasignadas':tr.visitas_persona_dia,'Distancia original de alimentación':tr.km_alimentador_original_ida_vuelta,'Distancia nueva de alimentación':tr.km_alimentador_nuevo_ida_vuelta})
        for n,d in [('Distancia original de alimentación','Origen–cabecera habitual–origen, por vehículo.'),('Distancia nueva de alimentación','Origen–cabecera asignada–origen, por vehículo; sustituye a la distancia anterior.')]:campo(n,'km ida y regreso',d)
        np.testing.assert_allclose(trpub['Visitas reasignadas'].sum(),cal.visitas_reasignadas_cabecera.sum(),atol=1e-8,rtol=0);add('reasignacion_cabeceras','Cambios de cabecera conservando la visita',trpub,'Fecha, origen y colectivo')
    examples=calendar.sort_values('Fecha').groupby('Propias programadas',as_index=False).first();add('jornadas_representativas','Una fecha efectiva de cada tamaño de programación',examples,'Primera fecha de cada tamaño','Ejemplos para lectura; las cuentas anuales utilizan todas las fechas, no seis días uniformes.')
    # Solo factores energéticos de arcos y cargas efectivamente utilizados.
    ff=_leer(ctx.energia/'factores_por_arco_operativo.csv');ff=ff[[ (r.origen,r.destino,r.carga_copert) in usedarcs for r in ff.itertuples()]]
    campo('Carga técnica COPERT','% de carga','Condición del factor: 50 comercial o 0 vacío; no porcentaje de plazas ocupadas.')
    field=pd.DataFrame({'Origen del movimiento':_nodos(ff.origen),'Destino del movimiento':_nodos(ff.destino),'Carga técnica COPERT':ff.carga_copert*100,'Distancia':ff.km,'Energía en caliente (MWh)':ff.energia_hot_mj/3600,'Energía en caliente (tep)':ff.energia_hot_mj/3600/conv});add('factores_lanzaderas_utilizados','Factores de consumo con motor caliente en los arcos efectivos',field,'Arco y carga técnica',src='Factores calculados programáticamente con COPERT 5.10.1, autocar diésel Euro VI D/E hasta 18 t, 34 km/h; solo combinaciones utilizadas en el balance.')
    # Tres tablas físicas útiles, con cabeceras legibles y sin identificadores opacos.
    physical=[('pendientes_recorridos',{'recorrido_informe':('Recorrido','texto','Eje geográfico, ida y regreso.'),'intervalo_pendiente':('Intervalo de pendiente','%','Intervalo longitudinal de terreno estimado.'),'longitud_intervalo_km':('Longitud del intervalo','km','Longitud dentro de la clase de pendiente.'),'porcentaje_longitud':('Porcentaje de longitud','%','Fracción de longitud en el intervalo; no energía.'),'longitud_ida_regreso_km':('Longitud ida y regreso','km','Longitud total de ambos sentidos.'),'longitud_fuera_rango_km':('Longitud fuera del factor','km','Longitud física fuera de menos seis a más seis por ciento; no error energético acotado.')}),('perfiles_recorridos',{'recorrido_informe':('Recorrido','texto','Eje geográfico, ida y regreso.'),'sentido_perfil':('Sentido','texto','Ida o regreso del perfil.'),'distancia_inicio_km':('Distancia desde inicio','km','Posición longitudinal en el perfil.'),'longitud_tramo_km':('Longitud del tramo','km','Longitud del segmento altimétrico.'),'cota_inicio_m':('Cota inicial','m','Cota de terreno al inicio; no rasante medida.'),'cota_fin_m':('Cota final','m','Cota de terreno al final; no rasante medida.'),'pendiente_tramo_pct':('Pendiente del tramo','%','Desnivel dividido entre longitud del segmento.'),'fuera_rango_factor':('Fuera del rango del factor','sí/no','Sí si excede menos seis a más seis por ciento.')}),('puntos_servicio_interior',{'lugar':('Lugar','texto','Referencia geográfica o destino turístico.'),'longitud':('Longitud geográfica','grados WGS84','Coordenada geográfica longitudinal.'),'latitud':('Latitud geográfica','grados WGS84','Coordenada geográfica latitudinal.'),'atencion_en_estudio':('Atención propuesta','texto','Forma de atención contemplada; no aprobación de parada.'),'limite_interpretacion':('Límite de interpretación','texto','Condición o incertidumbre que impide extender el alcance del dato.')})]
    for name,fields in physical:
        z=_leer(root/'data/silver/geografia/referencias_fisicas'/(name+'.csv'))[list(fields)].copy()
        for k,(label,unit,meaning) in fields.items():campo(label,unit,meaning)
        z=z.rename(columns={k:v[0] for k,v in fields.items()})
        for c in z.select_dtypes('bool'):z[c]=z[c].map({True:'Sí',False:'No'})
        add(name,{'pendientes_recorridos':'Pendientes de los cinco ejes','perfiles_recorridos':'Perfiles longitudinales de los cinco ejes','puntos_servicio_interior':'Puntos y condiciones de atención interior'}[name],z,'Tramo, intervalo o punto de referencia','Geografía y terreno; sin dependencia del volumen anual de visitas',src='Geometrías, terreno y puntos utilizados por la referencia; aproximaciones físicas vigentes, sin nuevas rutas.',periodo='Referencia física aplicada en 2028')
    # Perímetro y condiciones de uso, manteniendo ausencias como tales.
    campo('Estado en el balance','categoría','Identificado, común por hipótesis, excluido o diferencial incierto; no equivale a cero.')
    perimeter=pd.DataFrame([{'Componente':'Coches, excursiones, TITSA de acceso, lanzaderas y posicionamiento','Estado en el balance':'Identificado','Límite de interpretación':'Ocho componentes cuantificados; sin porcentaje global.'},{'Componente':'Línea 341 interior y servicios comunes no identificados','Estado en el balance':'Común por hipótesis','Límite de interpretación':'Consumo absoluto no cuantificado; igualdad sin/con no demostrada exhaustivamente.'},{'Componente':'Arranque en frío e instalaciones fijas','Estado en el balance':'Excluido','Límite de interpretación':'No se interpreta como consumo nulo.'},{'Componente':'Auxiliares, paradas, maniobras y logística exterior no representada','Estado en el balance':'Diferencial incierto','Límite de interpretación':'Cuantificar sin doble conteo; cada MWh neto adicional con proyecto resta un MWh al ahorro identificado.'}]);add('perimetro_balance','Qué está cuantificado y qué permanece fuera',perimeter,'Ámbito energético')
    # Distancias de la representación territorial vigente, sin cantidades anuales ajenas.
    for n,unit,desc in [('Sentido territorial','texto','Hacia el Parque o regreso por la referencia territorial.'),('Distancia directa de referencia','km','Recorrido completo del origen al Parque, por sentido.'),('Distancia a cabecera de referencia','km','Alimentación habitual del origen a la cabecera, por sentido.'),('Distancia de cadena por cabecera','km','Alimentación y montaña de la representación, por sentido; no ruta mínima garantizada.')]:campo(n,unit,desc,'No cuantificada si falta representación compatible; no es cero' if unit=='km' else 'No admitida')
    campo('Correspondencia anual','sí/no','Sí si el origen pertenece al reparto anual utilizado; No no equivale a demanda anual nula.')
    gg=pd.DataFrame({'Origen representativo':geo.origen_id.map(names),'Cabecera de referencia':geo.cabecera_calculo,'Sentido territorial':geo.sentido.map({'hacia_teide':'Hacia el Parque','desde_teide':'Regreso desde el Parque'}),'Distancia directa de referencia':geo.directa_km,'Distancia a cabecera de referencia':geo.alimentador_km,'Distancia de cadena por cabecera':geo.cadena_km,'Correspondencia anual':geo.origen_id.isin(set(pd.concat(originparts).origen_id)).map({True:'Sí',False:'No'})})
    add('recorridos_origenes','Distancias y correspondencia de los orígenes',gg,'Origen y sentido','Representación territorial, no origen observado de todos los visitantes',src='Catálogo y referencias físicas vigentes; los cambios de cabecera efectivos figuran en su tabla específica.',periodo='Referencia física aplicada en 2028')
    # COPERT de turismos: solo dos servicios y tres entornos/velocidades activos.
    fc=_leer(root/'data/silver/vehiculos/ponderacion/factores.csv');car=[]
    for service,label in [('Alquiler sin conductor (A01)','Alquiler sin conductor'),('Particular sin especificar (B00)','Particular')]:
        for mode,speed,key in [('urban_off_peak',ctx.v['velocidad_turismo_local'],'Local / urbano fuera de punta'),('rural',ctx.v['velocidad_turismo_convencional'],'Convencional / rural'),('highway',ctx.v['velocidad_turismo_rapida'],'Rápida / autopista')]:
            q=fc[fc.grupo_servicio.eq(service)&fc.modo.eq(mode)&fc.velocidad_kmh.eq(speed)]
            if len(q)!=1:raise ValueError('Factor de turismos activo no unívoco.')
            r=q.iloc[0];np.testing.assert_allclose(r.aporte_conjunto_condicionado_min_mj_km,r.aporte_conjunto_condicionado_max_mj_km,atol=1e-12,rtol=0)
            car.append({'Servicio del turismo':label,'Clase de circulación':key,'Velocidad técnica':speed,'Factor Hot ponderado':r.aporte_conjunto_condicionado_min_mj_km})
    for n,u,d in [('Servicio del turismo','texto','Parque particular o alquiler; la asignación de visitantes se indica en los balances.'),('Clase de circulación','texto','Clase cartográfica asociada a entorno COPERT; hipótesis, no tráfico observado.'),('Velocidad técnica','km/h','Condición seleccionada para el factor, no velocidad medida ni límite legal.'),('Factor Hot ponderado','MJ/vehículo-km','Consumo base ponderado con sustituciones de referencias incompletas; la corrección convencional de pendiente se aplica después.')]:campo(n,u,d)
    add('factores_turismos_utilizados','Factores base Hot de turismos efectivamente utilizados',pd.DataFrame(car),'Servicio y clase/velocidad',src='Mezclas DGT y factores de ejecuciones programáticas de COPERT; solo combinaciones utilizadas en el balance.')
    # Guía de reproducción de las etapas efectivas; no fichas de otras ofertas.
    for n,u,d in [('Etapa','texto','Etapa de la cadena vigente de cálculo.'),('Lectura y ejecución','ruta descriptiva','Módulo o comando actual; no es un identificador de ensayo.'),('Salida de lectura','archivo CSV','Anexo que permite revisar esa etapa.'),('Qué comprobar','texto','Relación o conservación que debe verificarse sin confundirla con validación institucional.')]:campo(n,u,d)
    # Único recorrido de lectura: los detalles de comandos se mantienen en la guía común.
    guide=pd.DataFrame([
      {'Etapa':'00 · Inicio y configuración','Lectura y ejecución':'notebooks/00_inicio_y_referencia.ipynb; config/parametros_modelo.xlsx; docs/ejecucion_por_etapas.md','Salida de lectura':'parametros_vigentes.csv','Qué comprobar':'31 condiciones y 2.500.000 visitas sin/con; consultar la referencia o iniciar expresamente una ejecución nueva.'},
      {'Etapa':'01 · Fuentes y demanda','Lectura y ejecución':'notebooks/01_fuentes_y_demanda.ipynb; src/movilidad_teide/flujos/preparacion_demanda.py','Salida de lectura':'visitas_modos_colectivos.csv; calendario_diario.csv','Qué comprobar':'Reconstrucción desde Bronze, 366 fechas y 21 interfaces de demanda; los pasos y los embarques no son nuevas visitas.'},
      {'Etapa':'02 · Recorridos y pendientes','Lectura y ejecución':'notebooks/02_recorridos_y_pendientes.ipynb; src/movilidad_teide/flujos/preparacion_geografia.py','Salida de lectura':'recorridos_origenes.csv; pendientes_recorridos.csv','Qué comprobar':'Geometrías, cotas, distancias y clases viales desde fuentes identificadas; 116 interfaces, con límites de cobertura explícitos.'},
      {'Etapa':'03 · Parque y condiciones','Lectura y ejecución':'notebooks/03_parque_y_condiciones.ipynb; src/movilidad_teide/configuracion/estudio.py','Salida de lectura':'parametros_fisicos.csv','Qué comprobar':'Selección técnica fijada y ámbito de los microdatos; distinguir base identificable y contraste municipal agregado.'},
      {'Etapa':'04 · Servicio y actividad','Lectura y ejecución':'notebooks/04_servicio_y_actividad.ipynb; src/movilidad_teide/flujos/etapas_registradas.py','Salida de lectura':'movimientos_lanzaderas.csv; reservas_visita.csv; disponibilidad_unidades.csv','Qué comprobar':'Identidades, plazas, reloj, estancia y equilibrio de bases; comprobar la oferta fijada sin energía ni otra búsqueda.'},
      {'Etapa':'05 · Preparación y ejecución de COPERT','Lectura y ejecución':'notebooks/05_preparacion_y_ejecucion_copert.ipynb; docs/reproduccion_copert.md; src/movilidad_teide/vehiculos/copert_publico.py','Salida de lectura':'factores_lanzaderas_utilizados.csv; titsa_factores.csv','Qué comprobar':'Distinguir consultar factores distribuidos, compararlos y ejecutar realmente el motor; 34 consultas y 5294 factores de referencia.'},
      {'Etapa':'06 · Balance y sensibilidades','Lectura y ejecución':'notebooks/06_balance_y_sensibilidades.ipynb; src/movilidad_teide/flujos/etapas_registradas.py','Salida de lectura':'balance_anual.csv; energia_componentes.csv; energia_diaria.csv','Qué comprobar':'El registro contiene 16 productos técnicos; el balance_anual.csv legible lo exporta generar_informe.py en anexos_vigentes/. Restar dentro de cada asignación, sin cruzar extremos.'},
      {'Etapa':'07 · Comprobación y vínculo con el informe','Lectura y ejecución':'notebooks/07_comprobacion_e_informe.ipynb; docs/trazabilidad.md; scripts/generar_informe.py','Salida de lectura':'indice_anexos.csv; diccionario_columnas.csv; guia_calculo.csv','Qué comprobar':'170 interfaces y 16 productos; consultar el anexo en data/gold/anexos/. Generar recursos en una carpeta nueva de Silver, con entorno fijado; no repetir el motor por consultar o exportar.'}])
    add('guia_calculo','Guía de lectura y reproducción vigente',guide,'Etapa')
    # Contrastes actuales: misma actividad y supuestos principales, sin balances obsoletos.
    from movilidad_teide.informe.integracion import registrar_campos_sensibilidad
    registrar_campos_sensibilidad(campo, ESPEC)
    for name, title in [('sensibilidad_fisica','Masa, transmisión, descenso y aporte gravitatorio'), ('sensibilidad_conjunta','Cambios de intensidad con actividad fija'), ('umbrales_condicionados','Margen y cocientes por visitas adicionales hipotéticas')]:
        add(name,title,datos['analisis_integracion'][name],'Asignación, tratamiento y contraste',src='Actividad vigente y coeficientes físicos conservados; alimentadores reasignados recalculados. Contrastes sin probabilidades ni cambio del escenario principal.')
    from movilidad_teide.informe.recursos_contexto import actividad_privada
    for n,u,d in [('Rama de actividad privada','categoría','Directos sin, autorizados con, alimentación de transferidos del coche o alimentación de antiguos viajeros de acceso TITSA.'),('Visitas representadas','visitas-persona/año','Personas de la rama; cadenas multiplicadas por 3,2 personas por coche. Las ramas con se agregan entre sí, sin sumarlas a sin.'),('Cadenas privadas','ida y regreso de coche/año','Una cadena de ida y regreso atribuida a su visita; no vehículos físicos distintos. Incluye visita interior en directos/autorizados.'),('Vehículos-kilómetro','vehículo-km/año','Kilometraje de ida, regreso e interior aplicable. Reasignación: retirar alimentación habitual y añadir la nueva. Sin doble suma de asignaciones de turismos.')]:
        campo(n,u,d)
    add('actividad_privada','Actividad de coches por escenario y rama',actividad_privada(root,datos),'Escenario y rama de actividad',src='Actividad vigente por origen/colectivo/fecha, longitudes dirigidas conservadas, visita interior próxima y alimentadores alternativos. No utiliza cantidades anuales de otra configuración.')
    from movilidad_teide.informe.titsa import anexos_titsa
    tables,definitions=anexos_titsa(root,datos)
    for n,(u,d) in definitions.items():
        if n not in ESPEC:campo(n,u,d)
    for n,title,frame in tables:add(n,title,frame,'Línea, sentido y segmento cuando corresponde',src='Trazados GTFS y perfiles de terreno; factores calculados programáticamente con COPERT para autocar diésel Euro VI D/E, 34 km/h y carga50%. No son consumos observados.')
    # Catálogo y diccionario exhaustivo se calculan a partir del conjunto realmente exportado.
    index=pd.DataFrame(out.indice);dictionary=pd.DataFrame(out.diccionario)
    for tabla,col in [(index,'Fuente y método'),(dictionary,'Fuente y cálculo')]:
        tabla[col]=[texto+' Trazabilidad: manifiestos/trazabilidad_anexos.csv, archivo '+archivo+'; manifiestos/trazabilidad_columnas.csv, archivo y columna cuando corresponda. La preparación se detalla en manifiestos/trazabilidad_preparacion_balance.csv.' for texto,archivo in zip(tabla[col],tabla['Archivo'])]

    index.to_csv(out.path/'indice_anexos.csv',sep=';',index=False,encoding='utf-8-sig')
    dictionary.to_csv(out.path/'diccionario_columnas.csv',sep=';',index=False,encoding='utf-8-sig')
    (out.path/'LEEME.txt').write_text('ANEXOS DE LA ORDENACIÓN VIGENTE DE 2028\n2.500.000 visitas-persona sin y con intervención.\nComenzar por indice_anexos.csv; diccionario_columnas.csv define todas las columnas de los anexos de datos, unidades, periodo, ámbito y ausencias.\nFormato: UTF-8 con marca de codificación, separador punto y coma y coma decimal; sin separador de millares. Fechas ISO. CSV y libro son exportaciones de lectura, no puntos de edición.\nLos valores fraccionarios proceden de ponderaciones; no son personas partidas ni reservas contratadas.\nVacío significa dato no cuantificado/no aplicable según diccionario; no se convierte en cero. El cero de una partida sustituida o de plazas comerciales de un vacío sí es explícito.\nUna fecha está repetida por asignación/tratamiento en las cuentas: no se suman poblaciones entre asignaciones. Ahorro = sin menos con dentro de la misma asignación.\nPrimero sumar por asignación y después formar rangos. Por visita: usar visitas de la misma fila/grupo; los ratios no se suman ni se promedian sin ponderar.\nSin porcentaje global: el consumo común absoluto sigue sin cuantificar. Frío e instalaciones fijas excluidos, otros diferenciales inciertos.\nLos nombres de autobús y números de movimiento son referencias de estudio comprensibles, no matrículas o contratos. Las jornadas representativas son ejemplos; el año usa las 366 fechas.\nLos factores se obtuvieron mediante ejecuciones programáticas de COPERT. La secuencia notebooks/00–07 explica el cálculo; docs/ejecucion_por_etapas.md mantiene los comandos. Consultar factores o exportar estos anexos no ejecuta nuevamente el motor. Las rutas parten de la raíz; esta carpeta de entrega es data/gold/anexos/. Las matrices manifiestos/trazabilidad_anexos.csv y manifiestos/trazabilidad_columnas.csv respaldan archivos y campos.\nEl libro resume tablas de hasta 5000 filas; el detalle completo de movimientos, reservas y disponibilidad está en CSV.\n',encoding='utf-8')
    leeme=out.path/'LEEME.txt'
    leeme.write_text('Informe v'+VERSION+' · '+FECHA+'\nRepositorio público: '+REPOSITORIO+'\n\n'+leeme.read_text(encoding='utf-8'),encoding='utf-8')
    # Libro de lectura: conserva números y evita truncar detalles grandes sin avisarlo.
    from openpyxl import Workbook
    from openpyxl.styles import Font,PatternFill,Alignment
    wb=Workbook();wb.remove(wb.active)
    wb.properties.title='Anexos energéticos de la movilidad del Parque Nacional del Teide'
    wb.properties.subject='Informe v'+VERSION+' · '+FECHA+' · '+str(N)+' visitas-persona anuales'
    wb.properties.creator='Beatriz González Domínguez'
    wb.properties.identifier=REPOSITORIO
    wb.properties.description='Tablas de lectura del estudio. Código, datos y metodología: '+REPOSITORIO
    for title,df in [('Índice',index),('Diccionario',dictionary),*[(name[:31],z[1]) for name,z in out.tablas.items() if len(z[1])<=5000]]:
        ws=wb.create_sheet(title);ws.append(list(df.columns))
        for row in df.itertuples(index=False,name=None):ws.append([None if pd.isna(x) else x.item() if isinstance(x,np.generic) else x for x in row])
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for c in ws[1]:c.font=Font(name='Arial',bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='0C4767');c.alignment=Alignment(wrap_text=True)
        ws.row_dimensions[1].height=42
        ws.sheet_view.showGridLines=False
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                header=ws.cell(1,cell.column).value
                cell.font=Font(name='Arial',size=10)
                if isinstance(cell.value,(int,float)):
                    cell.number_format='#,##0' if pd.api.types.is_integer_dtype(df.iloc[:,cell.column-1]) else '0.00000000' if '/visita' in header and 'kWh' not in header else '0.000' if 'kWh/visita' in header else '#,##0.00'
                else:cell.alignment=Alignment(vertical='top',wrap_text=True)
            ws.row_dimensions[row[0].row].height=44 if title in ['Índice','Diccionario'] else 30
        for col in ws.columns:
            longitud=max((len(str(c.value)) for c in col if isinstance(c.value,str)),default=0)
            ws.column_dimensions[col[0].column_letter].width=min(72,max(18,len(str(col[0].value))*.95,longitud*.9))
        # La altura fija ocultaba notas largas. Ajustar presentación sin cambiar valores.
        from textwrap import wrap
        for row in ws.iter_rows():
            lineas=1
            for cell in row:
                if not isinstance(cell.value,str):continue
                ancho=max(8,int(ws.column_dimensions[cell.column_letter].width*.85))
                lineas=max(lineas,sum(max(1,len(wrap(parrafo,width=ancho))) for parrafo in cell.value.split('\n')))
            ws.row_dimensions[row[0].row].height=min(409,max(42 if row[0].row==1 else 30,lineas*13+8))

    wb.save(out.path/'Anexos_energeticos_2028.xlsx');normalizar_libro(out.path/'Anexos_energeticos_2028.xlsx')
    # Registro las entradas adicionales de etiquetas y referencias físicas.
    extra=['config/itinerarios.json','data/silver/demanda/asignacion/recorridos_referencia_calculo.csv','data/silver/demanda/asignacion/origenes_representativos.csv','data/silver/vehiculos/ponderacion/factores.csv']+[
        'data/silver/geografia/referencias_fisicas/'+n+'.csv' for n in ['pendientes_recorridos','perfiles_recorridos','puntos_servicio_interior']]
    inputs={n:sha256_archivo(root/n) for n in extra}
    hashes={p.name:sha256_archivo(p) for p in out.path.iterdir() if p.is_file()}
    (out.path/'manifiesto_archivos.json').write_text(json.dumps({'version_informe':VERSION,'repositorio_publico':REPOSITORIO,'referencia':'Ordenación vigente de 2028','visitas_sin_y_con':N,'anexos_de_datos':len(out.tablas),'columnas_definidas':len(dictionary),'archivos_sha256':hashes,'escenarios_descartados_incluidos':False,'ejecucion_nueva_COPERT':False},ensure_ascii=False,indent=2)+'\n')
    escribir_zip(destino/PAQUETE,{ANEXOS+'/'+p.name:p.read_bytes() for p in out.path.iterdir() if p.is_file()})
    # Índice de lectura que se incorpora al maestro, con las mismas filas del catálogo.
    from movilidad_teide.informe.formato import tex,numero
    lines=[r'\begingroup\fontsize{9}{12}\selectfont',r'\begin{longtable}{@{}p{58mm}p{77mm}r@{}}',r'\rowcolor{azul}\Blanco{Archivo CSV} & \Blanco{Contenido} & \Blanco{Filas}\\\endfirsthead',r'\rowcolor{azul}\Blanco{Archivo CSV} & \Blanco{Contenido} & \Blanco{Filas}\\\endhead']
    for i,row in enumerate(out.indice):lines.append((r'\rowcolor{fondo_azul}' if i%2==0 else '')+r'\path{'+row['Archivo']+'} & '+tex(row['Contenido'])+' & '+numero(row['Filas'],0)+r'\\')
    lines += [r'\bottomrule\end{longtable}\endgroup']
    (destino/'tablas/vigente/indice_anexos.tex').write_text('\n'.join(lines)+'\n')
    return {'anexos_datos':len(out.tablas),'columnas_definidas':len(dictionary),'filas_movimientos':len(m),'filas_reservas':len(rs),'disponibilidad':len(ds),'libro_resumen':True,'paquete':PAQUETE,'escenarios_descartados_incluidos':False,'entradas_adicionales_sha256':inputs}
