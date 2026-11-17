"""Calendario y energía diaria de la referencia vigente, sin nueva simulación."""
from pathlib import Path
import numpy as np
import pandas as pd

COLORES_FLOTA={20:'#d5e7ef',23:'#99c9b9',24:'#398e83',27:'#174e6b',28:'#e7ae49',30:'#a44437'}
MESES=['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']


def datos_temporales(datos):
    """Reconstruir solo las cuentas de presentación y conciliarlas por asignación."""
    cfg=datos['referencia']['valores'];t=datos['tablas'];cal=t['calendario_operativo'];daily=t['actividad_diaria'];annual=t['central']
    expected=pd.date_range('2028-01-01','2028-12-31').strftime('%Y-%m-%d')
    if cal.fecha.duplicated().any() or sorted(cal.fecha)!=list(expected):
        raise ValueError('La figura necesita las 366 fechas, sin ausencias o duplicados.')
    if daily.duplicated(['fecha','asignacion_turismos']).any():
        raise ValueError('La energía diaria contiene una fecha/asignación repetida.')
    if set(cal.programadas)!=set(COLORES_FLOTA):raise ValueError('La figura requiere los seis tamaños de la referencia.')
    if set(daily.asignacion_turismos)!=set(annual.asignacion_turismos) or len(annual)!=2:
        raise ValueError('Las asignaciones diarias no coinciden con las dos cuentas anuales.')
    cols=['fecha','regimen','programadas','cupo','externas_disponibles','externas_programadas','visitas_sin_dia','visitas_coche_dia','visitas_excursion_dia','visitas_lanzadera_dia']
    keys=['fecha','asignacion_turismos']
    energy=['sin_mwh_dia','con_min_mwh_dia_sin_posicionamiento','con_max_mwh_dia_sin_posicionamiento']
    z=daily[keys+energy].merge(cal[cols],on='fecha',how='outer',validate='many_to_one')
    if len(z)!=732 or z[keys+energy+cols[1:]].isna().any().any():raise ValueError('Fechas o cuentas diarias incompletas.')
    z=z.sort_values(keys).reset_index(drop=True)
    np.testing.assert_allclose(cal.visitas_sin_dia.sum(),cfg['visitas_anio'],atol=1e-8,rtol=0)
    np.testing.assert_allclose(z.visitas_sin_dia,z[['visitas_coche_dia','visitas_excursion_dia','visitas_lanzadera_dia']].sum(axis=1),atol=1e-8,rtol=0)
    if (z.visitas_sin_dia<=0).any():raise ValueError('No se puede dividir por visitas ausentes o nulas.')
    if (cal.externas_programadas!=0).any():raise ValueError('La figura principal no programa comerciales externos.')
    available=float(cal.externas_disponibles.sum());distance=cfg['posicionamiento_km']
    if available<=0 or distance<=0:raise ValueError('La referencia de posicionamiento requiere revisión explícita.')
    rates=annual.posicionamiento_mwh/(available*distance)
    np.testing.assert_allclose(rates,rates.iloc[0],atol=1e-12,rtol=0)
    z['posicionamiento_mwh_dia']=z.externas_disponibles*distance*rates.iloc[0]
    z['con_min_mwh_dia']=z.con_min_mwh_dia_sin_posicionamiento+z.posicionamiento_mwh_dia
    z['con_max_mwh_dia']=z.con_max_mwh_dia_sin_posicionamiento+z.posicionamiento_mwh_dia
    # La resta se realiza dentro de cada asignación antes de formar la banda.
    z['ahorro_min_mwh_dia']=z.sin_mwh_dia-z.con_max_mwh_dia
    z['ahorro_max_mwh_dia']=z.sin_mwh_dia-z.con_min_mwh_dia
    metrics=['sin','con_min','con_max','ahorro_min','ahorro_max']
    for name in metrics:
        z[name+'_tep_dia']=z[name+'_mwh_dia']/cfg['mwh_por_tep']
        z[name+'_mwh_visita']=z[name+'_mwh_dia']/z.visitas_sin_dia
        z[name+'_tep_visita']=z[name+'_mwh_visita']/cfg['mwh_por_tep']
    for alt,g in z.groupby('asignacion_turismos'):
        r=annual[annual.asignacion_turismos.eq(alt)].iloc[0]
        np.testing.assert_allclose(g[[n+'_mwh_dia' for n in metrics]].sum(),[r.sin_identificado_mwh,r.con_identificado_min_mwh,r.con_identificado_max_mwh,r.ahorro_min_mwh,r.ahorro_max_mwh],atol=1e-8,rtol=0)
        np.testing.assert_allclose(g.visitas_sin_dia.sum(),cfg['visitas_anio'],atol=1e-8,rtol=0)
    return z.drop(columns=['con_min_mwh_dia_sin_posicionamiento','con_max_mwh_dia_sin_posicionamiento'])


def envolvente_temporal(tabla):
    """Bandas de las cuentas ya restadas; nunca restar extremos entre asignaciones."""
    groups=tabla.groupby('fecha',sort=True)
    out=groups[['programadas','visitas_sin_dia']].first()
    for unit in ['mwh_dia','tep_dia','mwh_visita','tep_visita']:
        out['sin_min_'+unit]=groups['sin_'+unit].min()
        out['sin_max_'+unit]=groups['sin_'+unit].max()
        for name in ['con','ahorro']:
            out[name+'_min_'+unit]=groups[name+'_min_'+unit].min()
            out[name+'_max_'+unit]=groups[name+'_max_'+unit].max()
    return out.reset_index()


def generar_figura_temporal(datos,destino):
    """Figura de publicación en PDF, SVG y PNG con datos exactos exportados."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.colors import ListedColormap,BoundaryNorm
    from matplotlib.patches import Patch
    from matplotlib.ticker import FuncFormatter,MaxNLocator
    out=Path(destino);(out/'figuras').mkdir(exist_ok=True);(out/'anexos').mkdir(exist_ok=True)
    daily=datos_temporales(datos);band=envolvente_temporal(daily);cfg=datos['referencia']['valores'];conv=cfg['mwh_por_tep']
    daily.to_csv(out/'anexos/figura_temporal_datos.csv',sep=';',index=False,float_format='%.17g')
    x=mdates.date2num(pd.to_datetime(band.fecha));counts=band.programadas.value_counts().to_dict()
    rc={'font.family':'Liberation Sans','font.size':10,'axes.labelsize':9.5,'xtick.labelsize':9.5,'ytick.labelsize':9.5,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'svg.fonttype':'none','svg.hashsalt':'movilidad-teide-temporal-2028','axes.unicode_minus':True}
    with plt.rc_context(rc):
        fig=plt.figure(figsize=(8,9.8),facecolor='white')
        gs=fig.add_gridspec(5,1,height_ratios=[.3,1,1,1,1],left=.13,right=.87,bottom=.102,top=.842,hspace=.57)
        axes=[fig.add_subplot(gs[i]) for i in range(5)]
        fig.text(.13,.974,'Programación y energía identificada · 2028',fontsize=14,weight='bold',color='#0c4767',va='top')
        fig.text(.13,.946,'2.500.000 visitas · consumo en caliente · excursiones existentes conservadas\nApoyos: 100 km totales por unidad disponible y activación',fontsize=9.5,color='#53636c',va='top')
        legend=[Patch(facecolor=COLORES_FLOTA[n],label=f'{n} propias · {counts[n]} días') for n in COLORES_FLOTA]
        fig.legend(handles=legend,ncol=3,loc='upper left',bbox_to_anchor=(.12,.913),frameon=False,fontsize=9.5,columnspacing=1.45,handlelength=1.7,labelspacing=.45)
        bandaxis=axes[0]
        vals=np.array([list(COLORES_FLOTA).index(int(v)) for v in band.programadas])
        bandaxis.pcolormesh(np.r_[x-.5,x[-1]+.5],[0,1],vals[None,:],cmap=ListedColormap(list(COLORES_FLOTA.values())),norm=BoundaryNorm(np.arange(-.5,6.5,1),6),shading='flat',rasterized=False)
        bandaxis.set_ylim(0,1);bandaxis.set_yticks([]);bandaxis.spines['left'].set_visible(False);bandaxis.spines['bottom'].set_visible(False)
        bandaxis.set_ylabel('Propias\nprogramadas',rotation=0,ha='right',va='center',labelpad=6,fontsize=9.5)
        fig.text(.13,.851,'Ordinaria: 20, 23, 24 o 27 propias   |   Punta: 28 o 30 propias',fontsize=9.5,color='#24343d')
        blue='#397568';green='#397568';gray='#0C4767'
        panels=[('Consumo diario identificado','mwh_dia','MWh/día','tep/día',0,1,'consumo'),('Ahorro diario identificado','mwh_dia','MWh/día','tep/día',0,1,'ahorro'),('Consumo identificado por visita','mwh_visita','MWh/visita','tep/visita',4,5,'consumo'),('Ahorro identificado por visita','mwh_visita','MWh/visita','tep/visita',4,5,'ahorro')]
        for ax,(title,unit,lunit,runit,dl,dr,kind) in zip(axes[1:],panels):
            if kind=='consumo':
                lo,hi=band['sin_min_'+unit].to_numpy(),band['sin_max_'+unit].to_numpy()
                ax.fill_between(x,lo,hi,step='mid',color=gray,alpha=.22,lw=0)
                ax.step(x,(lo+hi)/2,where='mid',color=gray,lw=.85,ls='--',label='Sin intervención')
                lo,hi=band['con_min_'+unit].to_numpy(),band['con_max_'+unit].to_numpy()
                ax.fill_between(x,lo,hi,step='mid',color=blue,alpha=.32,lw=0)
                ax.step(x,(lo+hi)/2,where='mid',color=blue,lw=.8,label='Con intervención')
                ax.set_ylim(0,band['sin_max_'+unit].max()*1.13)
            else:
                lo,hi=band['ahorro_min_'+unit].to_numpy(),band['ahorro_max_'+unit].to_numpy()
                ax.fill_between(x,lo,hi,step='mid',color=green,alpha=.38,lw=0)
                ax.step(x,(lo+hi)/2,where='mid',color=green,lw=.85)
                ax.axhline(0,color='#53636c',lw=.7)
                ax.set_ylim(min(0,float(lo.min())*1.15),max(float(hi.max())*1.18,.001))
            ax.set_title(title,loc='left',fontsize=10.5,weight='bold',color='#0c4767',pad=17)
            ax.text(0,1.04,lunit,transform=ax.transAxes,fontsize=9,color='#53636c')
            ax.text(1,1.04,runit,transform=ax.transAxes,fontsize=9,ha='right',color='#53636c')
            ax.yaxis.set_major_locator(MaxNLocator(nbins=3));ax.tick_params(axis='both',length=2.5,color='#a9b8bd')
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v,pos,d=dl:f'{v:.{d}f}'.replace('.',',')))
            ax.spines['left'].set_color('#cbd5db');ax.spines['bottom'].set_color('#cbd5db')
            ax.grid(axis='y',color='#edf0f2',lw=.55,zorder=0)
            right=ax.secondary_yaxis('right',functions=(lambda v:v/conv,lambda v:v*conv))
            right.set_yticks(ax.get_yticks()/conv);right.yaxis.set_major_formatter(FuncFormatter(lambda v,pos,d=dr:f'{v:.{d}f}'.replace('.',',')))
            right.tick_params(length=2.5,labelsize=9.5,color='#a9b8bd');right.spines['right'].set_visible(False)
            if kind=='consumo' and unit=='mwh_dia':ax.legend(loc='lower right',bbox_to_anchor=(1,1.15),ncol=2,frameon=False,fontsize=8.8,handlelength=1.5,columnspacing=1,borderaxespad=0)
        boundaries=mdates.date2num(pd.date_range('2028-01-01','2029-01-01',freq='MS'))
        centers=(boundaries[:-1]+boundaries[1:])/2-.5
        for ax in axes:
            ax.set_xlim(x[0]-.5,x[-1]+.5)
            for xx in boundaries:ax.axvline(xx-.5,color='#cbd5db',lw=.5,zorder=0)
            ax.set_xticks(centers);ax.set_xticklabels(MESES)
            ax.tick_params(axis='x',labelbottom=ax is axes[-1],bottom=ax is axes[-1])
        fig.text(.13,.056,'Bandas: España no Tenerife en alquiler o particular y extremos de alimentadores.\nLíneas: punto medio gráfico. El ahorro se resta dentro de cada asignación, sin interpretación estadística.\nCada posición es una fecha. Incluye coche a cabeceras y apoyos. Escalas: 1 tep = 11,63 MWh.',fontsize=8.5,color='#53636c',linespacing=1.35,va='top')
        target=out/'figuras/distribucion_temporal_anual'
        fig.savefig(target.with_suffix('.pdf'),metadata={'Title':'Programación y energía identificada en 2028','CreationDate':None,'ModDate':None})
        fig.savefig(target.with_suffix('.svg'),metadata={'Title':'Programación y energía identificada en 2028','Date':None})
        fig.savefig(target.with_suffix('.png'),dpi=240)
        plt.close(fig)
    return {'fechas':366,'filas_por_asignacion':len(daily),'programacion':{str(k):int(counts[k]) for k in COLORES_FLOTA},'unidades':['MWh/día','tep/día','MWh/visita','tep/visita'],'tratamiento':'Consumo en caliente','conciliacion_anual_por_asignacion':True,'promedio_diario_o_reparto_uniforme':False}
