"""Anexos y explicación del acceso TITSA con perfiles de pendiente."""
from pathlib import Path
import numpy as np,pandas as pd
from .integracion import _tabla
from .vigente import numero
from .formato import tex,formatear_ejes


def anexos_titsa(root,datos):
    root=Path(root);folder=root/datos['referencia']['indice']['titsa_pendiente']['directorio']
    s=pd.read_csv(folder/'resumen_recorridos.csv',sep=';',float_precision='round_trip');p=pd.read_parquet(folder/'segmentos.parquet');f=pd.read_parquet(folder/'factores_utilizados.parquet')
    labels={int(r.shape_id):(r.origen.replace(' (T)','').strip(),r.destino.replace(' (T)','').strip()) for r in s.itertuples()}
    a=pd.DataFrame({'Línea':s.linea.astype(int),'Origen del recorrido':s.origen.str.replace(' (T)','',regex=False).str.strip(),'Destino del recorrido':s.destino.str.replace(' (T)','',regex=False).str.strip(),'Longitud del recorrido':s.kilometros,'Ascenso acumulado':s.ascenso_m,'Descenso acumulado':s.descenso_m,'Longitud fuera de rango COPERT (%)':s.longitud_fuera_rango_pct,'Energía por expedición (MWh)':s.mwh_por_expedicion,'Energía anual del recorrido (MWh)':366*s.mwh_por_expedicion,'Energía anual del recorrido (tep)':366*s.mwh_por_expedicion/11.63})
    b=pd.DataFrame({'Línea':p.linea.astype(int),'Origen del recorrido':p.shape_id.astype(int).map(lambda x:labels[x][0]),'Destino del recorrido':p.shape_id.astype(int).map(lambda x:labels[x][1]),'Segmento del recorrido':p.segment_id,'Distancia inicial':p.distance_start_m/1000,'Distancia final':p.distance_end_m/1000,'Longitud de segmento':p.length_m/1000,'Altitud inicial':p.elevation_start_m,'Altitud final':p.elevation_end_m,'Pendiente física':p.slope_pct,'Pendiente aplicada al factor':p.pendiente_asignacion_pct,'Factor energético del segmento':p.hot_ec_mj_per_km,'Energía del segmento (MWh)':p.energia_mj/3600})
    c=pd.DataFrame({'Referencia de autobús':['Autocar diésel de hasta 18 t, Euro VI D/E']*len(f),'Pendiente del factor':f.slope_class_pct,'Velocidad de referencia TITSA':f.rural_speed_kmh,'Carga de referencia TITSA (%)':100*f.load_fraction,'Factor energético del segmento':f.hot_ec_mj_per_km})
    definitions={
        'Línea':('número de línea','Línea pública de acceso 342 o 348; no identificador de ensayo.'),
        'Origen del recorrido':('parada GTFS','Parada inicial del sentido conservado en GTFS.'),'Destino del recorrido':('parada GTFS','Parada final del sentido conservado en GTFS.'),
        'Longitud del recorrido':('km','Longitud del trazado GTFS proyectado en EPSG:4083; no se duplica la ida para estimar la vuelta.'),
        'Ascenso acumulado':('m','Suma de desniveles positivos de segmentos muestreados cada 200 m con terreno bilineal.'),'Descenso acumulado':('m','Suma en valor positivo de desniveles descendentes.'),
        'Longitud fuera de rango COPERT (%)':('% de longitud del recorrido','Tramos con pendiente física menor que -6 o mayor que +6; se conserva la física y el factor usa el extremo. No estima error energético.'),
        'Energía por expedición (MWh)':('MWh/expedición','Suma de longitud por factor interpolado en pendiente, para la referencia técnica de vehículo, velocidad y carga.'),
        'Energía anual del recorrido (MWh)':('MWh/año','Una expedición del sentido por día, multiplicada por 366 días de 2028.'),'Energía anual del recorrido (tep)':('tep/año','Misma energía anual dividida por 11,63.'),
        'Segmento del recorrido':('ordinal dentro del recorrido','Número que ordena segmentos entre muestras consecutivas; se interpreta con línea, origen y destino.'),
        'Distancia inicial':('km desde origen','Posición inicial a lo largo del trazado.'),'Distancia final':('km desde origen','Posición final a lo largo del trazado.'),
        'Longitud de segmento':('km','Diferencia positiva entre distancias final e inicial.'),'Altitud inicial':('m','Elevación del terreno en la muestra inicial; no certifica rasante.'),'Altitud final':('m','Elevación del terreno en la muestra final.'),
        'Pendiente física':('%','Cien veces desnivel entre muestras dividido por longitud; conserva valores fuera de biblioteca.'),
        'Pendiente aplicada al factor':('%','Pendiente física limitada a -6/+6 para interpolar los siete factores disponibles, como en las lanzaderas.'),
        'Factor energético del segmento':('MJ/vehículo-km','Factor Hot interpolado linealmente entre pendientes consultadas, a velocidad y carga técnicas fijas.'),
        'Energía del segmento (MWh)':('MWh/expedición','Longitud del segmento por su factor, dividida por 3.600.'),
        'Referencia de autobús':('categoría técnica','Referencia de modelización conservada; no acredita el autobús real de la línea.'),
        'Pendiente del factor':('%','Nodo de pendiente con factor COPERT conservado: -6,-4,-2,0,2,4,6.'),
        'Velocidad de referencia TITSA':('km/h','34 km/h del libro; hipótesis técnica, no tiempo GTFS convertido en velocidad observada.'),
        'Carga de referencia TITSA (%)':('% de carga técnica COPERT','50 % del libro; no es una ocupación de pasajeros medida ni se deduce de visitas/plazas.'),
    }
    return [(name,title,frame) for name,title,frame in [('titsa_recorridos','Recorridos y consumo anual de TITSA 342 y 348',a),('titsa_segmentos','Pendiente, factores y energía por segmento TITSA',b),('titsa_factores','Siete factores Hot utilizados para TITSA',c)]],definitions


def recursos_titsa(root,destino,datos):
    root=Path(root);destino=Path(destino);folder=destino/'tablas/vigente';pub=destino/'anexos_vigentes';a=pd.read_csv(pub/'titsa_recorridos.csv',sep=';',decimal=',')
    rows=[];energy=[]
    for r in a.to_dict('records'):
        labels={'ESTACIÓN COSTA ADEJE':'Estación de Costa Adeje','EL TEIDE - EL PORTILLO':'El Portillo','PUERTO DE LA CRUZ':'Puerto de la Cruz','PARADOR DEL TEIDE':'Parador del Teide'}
        name=str(r['Línea'])+' / '+labels[r['Origen del recorrido']]+' → '+labels[r['Destino del recorrido']]
        rows.append([tex(name),numero(r['Longitud del recorrido'],2),numero(r['Ascenso acumulado'],0),numero(r['Descenso acumulado'],0),numero(r['Longitud fuera de rango COPERT (%)'],1)+r'\%'])
        energy.append([tex(name),numero(r['Energía por expedición (MWh)'],4),numero(r['Energía anual del recorrido (MWh)'],1),numero(r['Energía anual del recorrido (tep)'],2)])
    _tabla(folder/'titsa_geometria.tex','Recorridos de acceso TITSA y cobertura de pendiente',['Línea / recorrido','km','Ascenso (m)','Descenso (m)','Fuera de ±6%'],rows,r'Trazados GTFS independientes por sentido, terreno nativo de 5 m y muestras cada 200 m, con interpolación bilineal. La fracción fuera de rango mide longitud; no cuantifica el error energético.')
    _tabla(folder/'titsa_energia.tex','Consumo de acceso de TITSA con pendiente',['Línea / recorrido','MWh / expedición','MWh / año','tep / año'],energy,r'Autocar diésel de hasta 18 t, Euro VI D/E; rural, 34 km/h y carga técnica COPERT del 50 %. Una expedición por sentido y día durante 366 fechas. Referencia de cálculo, sin calibración local de vehículo, velocidad o carga reales.')
    for name,n in [('titsa_geometria',5),('titsa_energia',4)]:
        q=folder/(name+'.tex');text=q.read_text()
        first=1.75 if n==5 else 1.5;other=(n-first)/(n-1)
        text=text.replace('@{}X','@{}>{\\hsize='+str(first)+r'\hsize\linewidth=\hsize}X',1)
        text=text.replace(r'>{\RaggedLeft\arraybackslash}X',r'>{\hsize='+str(other)+r'\hsize\linewidth=\hsize\RaggedLeft\arraybackslash}X')
        q.write_text(text)
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    raw=root/datos['referencia']['indice']['titsa_pendiente']['directorio'];p=pd.read_parquet(raw/'perfiles.parquet');summary=pd.read_csv(raw/'resumen_recorridos.csv',sep=';')
    fig,axes=plt.subplots(2,2,figsize=(8,5.5))
    for ax,r in zip(axes.flat,summary.itertuples()):
        g=p[p.shape_id.astype(str).eq(str(r.shape_id))].sort_values('distance_m')
        ax.plot(g.distance_m/1000,g.elevation_m,color='#0C4767',lw=1.3)
        ax.set(title=str(r.linea)+' · '+('Subida' if r.desnivel_neto_m>0 else 'Regreso'),xlabel='Distancia desde origen del sentido (km)',ylabel='Elevación del terreno (m)');ax.grid(alpha=.15);ax.spines[['top','right']].set_visible(False)
    formatear_ejes(fig)
    fig.tight_layout()
    for ext in ['pdf','png','svg']:fig.savefig(destino/'figuras'/('perfiles_titsa.'+ext),dpi=180,bbox_inches='tight')
    plt.close(fig)
    return {'recorridos':4,'factores':7,'segmentos':len(pd.read_csv(pub/'titsa_segmentos.csv',sep=';')),'energia_mwh_anio':float(a['Energía anual del recorrido (MWh)'].sum())}
