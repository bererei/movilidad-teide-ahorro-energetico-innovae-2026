"""Apoyos de lectura actuales: actividad, ejemplos y esquemas funcionales.

Recombina actividad vigente y longitudes conservadas, sin utilizar cantidades
anuales de la organización anterior. No cambia demanda, circulaciones o energía.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from .integracion import _tabla
from .vigente import numero,intervalo
from .formato import tex,formatear_ejes
from movilidad_teide.trazabilidad import sha256_archivo


def actividad_privada(root,datos):
    root=Path(root);ref=datos['referencia'];cfg=ref['valores'];cal=datos['tablas']['calendario_operativo'];cap=root/ref['indice']['captura'];parts=[];moves=[]
    rd=lambda p:pd.read_csv(p,sep=';',float_precision='round_trip')
    for (q,mx,profile),days in cal.groupby(['cupo','max_programadas_programa','perfil']):
        folder=cap/'ofertas'/str(q)/str(mx)/profile
        a=rd(folder/'origenes.csv');a['dias']=len(days);parts.append(a)
        if (folder/'traslados.csv').stat().st_size>3:
            b=rd(folder/'traslados.csv');b['dias']=len(days);moves.append(b)
    a=pd.concat(parts);ids=['origen_id','colectivo']
    fields=['coches_sin_dia','coches_autorizados_dia','visitas_coche_transferidas_dia']
    for f in fields:a[f]*=a.dias
    a=a.groupby(ids)[fields].sum();a['visitas_coche_transferidas_dia']/=cfg['ocupacion_coche']
    routes=rd(root/'data/silver/demanda/asignacion/recorridos_referencia_calculo.csv')
    lengths=rd(root/'data/silver/energia/referencias_unitarias/pendiente_turismos/energia_por_recorrido.csv')
    lengths=lengths[lengths.caso_pendiente.eq('Referencia del Excel')]
    km=[]
    for r in routes.itertuples():
        direct=r.directa_km
        if r.sentido=='hacia_teide' and pd.notna(direct):
            x=lengths.loc[lengths.comparacion_id.eq('visita_proxima_'+r.terminal_calculo),'longitud_km'].unique()
            if len(x)!=1:raise ValueError('Visita interior de referencia no unívoca.')
            direct+=float(x[0])
        km.append({'origen_id':r.origen_id,'sentido':r.sentido,'km_directos':direct,'km_alimentador':r.alimentador_km})
    km=pd.DataFrame(km);lookup=km.groupby('origen_id')[['km_directos','km_alimentador']].sum(min_count=1)
    z=a.join(lookup,on='origen_id',validate='many_to_one')
    for f in ['km_directos','km_alimentador']:
        if z.loc[z[fields].abs().sum(axis=1).gt(1e-10),f].isna().any():raise ValueError('Actividad positiva sin longitud.')
    baseline=float((z.coches_sin_dia*z.km_directos).sum());authorized=float((z.coches_autorizados_dia*z.km_directos).sum())
    feeding=float((z.visitas_coche_transferidas_dia*z.km_alimentador).sum())
    b=pd.concat(moves)
    for r in b.itertuples():
        np.testing.assert_allclose(lookup.loc[r.origen_id,'km_alimentador'],r.km_alimentador_original_ida_vuelta,atol=1e-8,rtol=0)
        feeding+=r.visitas_persona_dia/cfg['ocupacion_coche']*r.dias*(r.km_alimentador_nuevo_ida_vuelta-r.km_alimentador_original_ida_vuelta)
    ft=rd(root/ref['indice']['energia']/'alimentacion_coche_TITSA_hipotesis_usuario.csv')
    weights=cal.perfil.value_counts();ft=ft[ft.id_perfil.isin(weights.index)&ft.alternativa_procedencia.eq(ft.alternativa_procedencia.iloc[0])].copy()
    ft['n']=ft.coches_alimentadores_dia*ft.id_perfil.map(weights)
    directional=ft.groupby('sentido').n.sum()
    np.testing.assert_allclose(directional.to_numpy(),[directional.iloc[0]]*len(directional),atol=1e-8,rtol=0)
    ft=ft.merge(km,on=['origen_id','sentido'],validate='many_to_one')
    if ft.km_alimentador.isna().any():raise ValueError('Alimentación TITSA sin kilómetros.')
    n_titsa=float(ft.loc[ft.sentido.eq('hacia_teide'),'n'].sum());km_titsa=float((ft.n*ft.km_alimentador).sum())
    out=[]
    for esc,label,n,k in [('Sin intervención','Acceso directo, interior y regreso',a.coches_sin_dia.sum(),baseline),('Con intervención','Coches autorizados al Parque',a.coches_autorizados_dia.sum(),authorized),('Con intervención','Alimentación de transferidos desde coche',a.visitas_coche_transferidas_dia.sum(),feeding),('Con intervención','Alimentación de antiguos viajeros de acceso TITSA',n_titsa,km_titsa)]:
        out.append({'Escenario':esc,'Rama de actividad privada':label,'Visitas representadas':n*cfg['ocupacion_coche'],'Cadenas privadas':n,'Vehículos-kilómetro':k})
    out=pd.DataFrame(out)
    central=datos['tablas']['central'].iloc[0]
    np.testing.assert_allclose(out.loc[out.Escenario.eq('Con intervención'),'Visitas representadas'].sum(),central.visitas_coche_anio+central.visitas_lanzadera_anio,atol=1e-8,rtol=0)
    np.testing.assert_allclose(out.iloc[1]['Cadenas privadas'],central.entradas_coches_anio,atol=1e-8,rtol=0)
    datos['actividad_privada_contexto']=out
    return out


def preparar_recursos_contexto(root,destino,datos):
    root=Path(root);destino=Path(destino);folder=destino/'tablas/vigente';pub=destino/'anexos_vigentes'
    rd=lambda n:pd.read_csv(pub/(n+'.csv'),sep=';',decimal=',',float_precision='round_trip',low_memory=False)
    collect=rd('visitas_modos_colectivos');with_project=collect[collect.Escenario.eq('Con intervención')].pivot(index='Colectivo',columns='Modo de acceso',values='Visitas totales').fillna(0)
    before=collect[collect.Escenario.eq('Sin intervención')].groupby('Colectivo')['Visitas totales'].sum()
    np.testing.assert_allclose(with_project.sum(axis=1).sort_index(),before.sort_index(),atol=1e-8,rtol=0)
    rows=[]
    for name,r in with_project.iterrows():
        rows.append([tex(name),numero(r.sum(),0),numero(r['Coche'],0),numero(r['Lanzaderas nuevas'],0),numero(r['Excursiones / resto colectivo'],0)])
    # Los nombres modales se cotejan, sin aceptar silenciosamente una columna ausente.
    assert {'Coche','Lanzaderas nuevas'}<=set(with_project.columns),list(with_project.columns)
    assert any(c.startswith('Excurs') for c in with_project.columns),list(with_project.columns)
    _tabla(folder/'cobertura_colectivos_actual.tex','Visitas por colectivo y modo con intervención',['Colectivo','Total común sin/con','En coche','En lanzadera','En excursión'],rows,r'Personas por año. El total de cada grupo es igual en los dos escenarios; sus columnas de transporte corresponden a con intervención. No se suman asignaciones de turismos. Cantidades redondeadas después de conciliar.')
    table=folder/'cobertura_colectivos_actual.tex'
    text=table.read_text()
    header=r'\rowcolor{azul} '
    pos=text.index(header)
    text=text[:pos]+r'\rowcolor{azul} \multicolumn{1}{l}{\Blanco{Procedencia}} & \multicolumn{1}{c}{\Blanco{Sin y con}} & \multicolumn{3}{c}{\Blanco{Con intervención}}\\'+'\n'+text[pos:]
    table.write_text(text)
    p=datos.get('actividad_privada_contexto')
    assert p is not None
    _tabla(folder/'actividad_privada_actual.tex','Actividad de coches por escenario y rama en 2028',['Escenario / rama','Cadenas anuales','Vehículo-km/año'],[[tex(r['Escenario']+' / '+r['Rama de actividad privada']),numero(r['Cadenas privadas'],0),numero(r['Vehículos-kilómetro'],0)] for r in p.to_dict('records')],r'Una cadena incluye ida y regreso y, para directos, la visita interior asignada una vez. Las filas con intervención se suman entre sí, sin sumar la referencia sin. Alimentadores reasignados: se retira el trayecto anterior y se añade el nuevo; TITSA: 3,2 personas por coche. No son vehículos físicos distintos.')
    daily=rd('jornadas_representativas')
    rows=[]
    for r in daily.to_dict('records'):
        rows.append([r['Fecha'],str(r['Propias programadas']),str(r['Cupo máximo']),numero(r['Visitas en lanzadera'],0),str(r['Expediciones comerciales']),str(r['Movimientos en vacío'])])
    _tabla(folder/'jornadas_ejemplo_actual.tex','Una fecha representativa por tamaño de flota',['Fecha','Propias','Cupo coches','Visitas en lanzadera','Expediciones','Vacíos'],rows,r'Primera fecha del calendario con cada tamaño de flota. Selección reproducible para lectura, no muestra estadística. Las 30 propias requieren dos sustitutas externas disponibles. Los servicios del año se agregan fecha a fecha, no por multiplicación de estos ejemplos.')
    res=rd('reservas_visita');mov=rd('movimientos_lanzaderas').set_index(['Fecha','Número de movimiento']);rows=[]
    examples=[]
    for count in [27,28,30]:
        date=daily.loc[daily['Propias programadas'].eq(count),'Fecha'].item()
        rr=res[res.Fecha.eq(date)].sort_values(['Cabecera asignada y de regreso','Entrada al Parque','Movimiento de ida','Movimiento de regreso']).iloc[0]
        up=mov.loc[date,rr['Movimiento de ida']];down=mov.loc[date,rr['Movimiento de regreso']]
        assert up['Origen del movimiento']==down['Destino del movimiento']
        assert rr['Estancia dentro del Parque']>=120-1e-8
        clock=lambda minute:f'{int(minute)//60:02d}:{int(minute)%60:02d}'
        regime=('Ordinaria' if count==27 else 'Punta')+' ('+str(count)+')'
        datecell=regime+r'\newline '+date
        entrycell=clock(rr['Entrada al Parque'])+' / '+clock(rr['Regreso por la entrada'])+r'\newline ('+numero(rr['Estancia dentro del Parque'],0)+' min)'
        np.testing.assert_allclose(rr['Regreso por la entrada']-rr['Entrada al Parque'],rr['Estancia dentro del Parque'],atol=1e-8,rtol=0)
        rows.append([datecell,tex(rr['Cabecera asignada y de regreso']+' / '+rr['Destino de visita']),up['Hora de salida'][:5]+' / '+up['Hora de llegada'][:5],down['Hora de salida'][:5]+' / '+down['Hora de llegada'][:5],numero(rr['Visitas del grupo'],2),entrycell])
        examples.append({'fecha':date,'propias':count,'ida':int(rr['Movimiento de ida']),'regreso':int(rr['Movimiento de regreso'])})
    _tabla(folder/'reservas_ejemplo_actual.tex','Ejemplos de cadenas de visita y regreso',['Régimen (propias) / fecha','Cabecera / destino','Ida: salida / llegada','Regreso: salida / llegada','Visitas grupo','Paso entrada / estancia'],rows,r'Hora local de Canarias en horas:minutos, sin segundos; el modelo conserva la precisión completa. Los movimientos son cabecera–destino y destino–cabecera. La última columna muestra los dos pasos por la entrada y la estancia entre ellos: no son 120 minutos netos en el destino. Cada cadena se comprueba junto con las restantes, no de forma aislada.')
    m=rd('movimientos_lanzaderas');hot=datos['tablas']['central'];fta=datos['tablas']['fta'];cfg=datos['referencia']['valores']
    rows=[];energies=[]
    for label,mask in [('Comerciales',m['Tipo de movimiento'].eq('Comercial')),('En vacío',m['Tipo de movimiento'].ne('Comercial'))]:
        g=m[mask];e=float(g['Energía en caliente (MWh)'].sum());rows.append([label,str(len(g)),numero(g.Distancia.sum(),0),numero(e),numero(e/cfg['mwh_por_tep'])]);energies.append(e)
    pos=float(hot.posicionamiento_mwh.iloc[0]);rows.append(['Posicionamiento externo','26 unidades-día',numero(26*cfg['posicionamiento_km'],0),numero(pos),numero(pos/cfg['mwh_por_tep'])]);energies.append(pos)
    _tabla(folder/'energia_lanzaderas_actual.tex','Actividad y consumo anual de las nuevas lanzaderas',['Movimiento','Expediciones o disponibilidad','Vehículo-km','Hot (MWh)','Hot (tep)'],rows,r'Programación principal de 2028, con excursiones constantes. Posicionamiento: dos externas en trece fechas, a 100 km por unidad y activación. Las 26 unidades-día no son 26 expediciones o autobuses distintos; el combustible de sustituciones adicionales no programadas requiere incorporación si se realizan.')
    extra=sum(energies)*cfg['perdida_rendimiento_fta']/(1-cfg['perdida_rendimiento_fta'])
    np.testing.assert_allclose(fta.con_identificado_min_mwh.to_numpy()-hot.con_identificado_min_mwh.to_numpy(),extra,atol=1e-8,rtol=0)
    _figuras(destino,datos,sum(energies))
    paths=[root/'data/silver/demanda/asignacion/recorridos_referencia_calculo.csv',root/'data/silver/energia/referencias_unitarias/pendiente_turismos/energia_por_recorrido.csv']
    return {'figuras_recuperadas':4,'tablas_recuperadas':5,'colectivos_conciliados':True,'actividad_privada_sin_doble_recuento':True,'incremento_fta_conciliado':True,'reservas_ejemplo':examples,'entradas_longitud_sha256':{str(p.relative_to(root)):sha256_archivo(p) for p in paths}}


def _figuras(destino,datos,busenergy):
    blue='#0C4767';green='#397568';orange='#FA7921';gray='#53636C'
    plt.rcParams.update({'font.family':'Liberation Sans','font.size':10})
    def save(fig,name):
        formatear_ejes(fig)
        for ext in ['pdf','png','svg']:fig.savefig(destino/'figuras'/(name+'.'+ext),dpi=180,bbox_inches='tight')
        plt.close(fig)
    def box(ax,x,y,w,h,label,c=blue):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.008',ec=c,fc='#EFF5F8' if c==blue else '#EEF5F2',lw=1.2));ax.text(x+w/2,y+h/2,label,ha='center',va='center',fontsize=10,color=c)
    def arrow(ax,a,b,both=False):ax.annotate('',xy=b,xytext=a,arrowprops={'arrowstyle':'<->' if both else '->','color':gray,'lw':1.25})
    fig,ax=plt.subplots(figsize=(8,3.4));ax.axis('off')
    table=ax.table(cellText=[['Extranjeros','Alquiler','Alquiler'],['España no Tenerife','Alquiler','Particular'],['Tenerife no frecuentes','Particular','Particular'],['Resto de Tenerife','Particular','Particular']],colLabels=['Colectivo','Hipótesis alquiler para\nEspaña no Tenerife','Hipótesis particular para\nEspaña no Tenerife'],cellLoc='center',colWidths=[.34,.33,.33],bbox=[0,.2,1,.77]);table.auto_set_font_size(False);table.set_fontsize(10)
    for (r,c),cell in table.get_celld().items():
        cell.set_edgecolor('white');cell.set_facecolor(blue if r==0 else ('#EEF5F2' if r==2 else '#EFF5F8'))
        if r==0:cell.set_text_props(color='white',weight='bold')
    ax.text(.5,.055,'Cada columna se aplica completa a los escenarios sin y con intervención.\nLa asignación afecta a turismos; todos los modos y visitantes siguen incluidos.',ha='center',va='center',fontsize=10,color=gray)
    save(fig,'asignaciones_turismos_actual')
    fig,ax=plt.subplots(figsize=(8,7));ax.axis('off');ax.set(xlim=(0,1),ylim=(0,1))
    blocks=[(.86,'Demanda restante por cabecera, franja y destino\nDespués del cupo y de las excursiones'),(.67,'Agrupar visitas y enlazar ida, estancia y regreso\nPlazas disponibles en la cadena completa'),(.48,'Asignar movimientos a unidades físicas\nRegulación, vacíos, límites horarios y bases'),(.29,'Comprobar el programa completo de la fecha\nCapacidad, intervalos, luz y sustitución')]
    for y,label in blocks:box(ax,.05,y,.9,.11,label)
    for a,b in zip(blocks[:-1],blocks[1:]):arrow(ax,(.5,a[0]),(.5,b[0]+.12))
    arrow(ax,(.35,.29),(.25,.2));arrow(ax,(.7,.29),(.75,.2))
    box(ax,.02,.055,.46,.14,'Programa compatible\nContabilizar actividad y energía\nConfirmar reservas',green)
    box(ax,.54,.055,.44,.14,'Déficit o incompatibilidad\nRevisar cabecera, oferta o cupo\nComprobar otra cadena')
    save(fig,'comprobacion_jornada_actual')
    fig,ax=plt.subplots(figsize=(8,4.8));ax.axis('off');ax.set(xlim=(0,1),ylim=(0,1))
    for x,title in [(.02,'Chío'),(.27,'Vilaflor'),(.52,'Aguamansa'),(.77,'La Esperanza')]:box(ax,x,.8,.21,.1,title)
    box(ax,.07,.5,.22,.12,'Boca Tauce');box(ax,.71,.5,.22,.12,'El Portillo')
    for x,target in [(.125,.18),(.375,.18),(.625,.82),(.875,.82)]:arrow(ax,(x,.8),(target,.63),True)
    arrow(ax,(.3,.56),(.7,.56),True)
    box(ax,.32,.27,.36,.12,'Destino interior de visita\nReferencia en la carretera',green)
    arrow(ax,(.5,.55),(.5,.4),True)
    ax.text(.5,.13,'Acceso y parte interior pueden formar un movimiento integrado.\nLa reserva conserva el regreso a la misma cabecera de aparcamiento.',ha='center',va='center',color=gray,fontsize=10)
    ax.text(.5,.98,'Cabeceras exteriores → acceso y eje interior → visita y regreso',ha='center',color=blue,weight='bold')
    save(fig,'esquema_servicios_actual')
    fig,(ax,bx)=plt.subplots(1,2,figsize=(8,4.4),gridspec_kw={'width_ratios':[.9,1.1]})
    cfg=datos['referencia']['valores'];fta=busenergy/(1-cfg['perdida_rendimiento_fta'])
    ax.bar([0,1],[busenergy,fta],color=[green,orange],width=.6);ax.set(xticks=[0,1],xticklabels=['En caliente','Con contraste'],ylabel='Consumo de lanzaderas (MWh/año)');ax.set_ylim(0,fta*1.23)
    for x,e in enumerate([busenergy,fta]):ax.text(x,e+fta*.03,numero(e,0),ha='center',fontsize=10)
    ax.set_title('Misma actividad, más consumo',fontsize=11)
    for i,(key,label,color) in enumerate([('central','En caliente',green),('fta','Contraste adicional',orange)]):
        t=datos['tablas'][key]
        for j,r in enumerate(t.itertuples()):
            lo,hi=r.ahorro_min_tep,r.ahorro_max_tep;mid=(lo+hi)/2
            bx.errorbar(mid,j+(-.12 if i==0 else .12),xerr=[[mid-lo],[hi-mid]],fmt='o',capsize=3,color=color,label=label if j==0 else None)
    bx.set(yticks=[0,1],yticklabels=['España no Tenerife\nen alquiler','España no Tenerife\nen particular'],xlabel='Ahorro del conjunto (tep/año)',xlim=(0,460),ylim=(1.5,-.5));bx.axvline(60,ls='--',color=blue,lw=1);bx.set_title('Menor ahorro del sistema',fontsize=11);bx.legend(frameon=False,loc='lower right',fontsize=8)
    for a in [ax,bx]:a.spines[['top','right']].set_visible(False);a.grid(axis='y' if a is ax else 'x',alpha=.12)
    fig.tight_layout(w_pad=2);save(fig,'contraste_consumo_lanzaderas_actual')
