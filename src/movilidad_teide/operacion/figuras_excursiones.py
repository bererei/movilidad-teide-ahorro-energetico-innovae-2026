"""Muestro la reasignación modal y la circulación dirigida, sin cambiar el informe."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import pandas as pd

from .figura_reloj import dibujar_circulaciones


def dibujar_excursiones(tablas, root, destino):
    caso="D_2500000";p=tablas["perfiles"].loc[lambda t:t.caso.eq(caso)]
    if not p.empty:
        movimientos=tablas["movimientos"].loc[lambda t:t.caso.eq(caso)]
        comp=tablas["comparacion_reasignacion_anual"].loc[lambda t:t.caso.eq(caso)].iloc[0]
        g=f"{100*comp.incremento_anual_sobre_sin:.2f}".replace(".",",")
        local=p.sort_values(["vehiculos_programados_reloj","observacion"]).iloc[-1].incremento_excursiones_sobre_sin
        dibujar_circulaciones(movimientos,p,destino,subtitulo=f"Excursiones: +{g} % anual; +{100*local:g} % en este perfil (respecto a sin intervención)",
                             decision="D241",hipotesis="H131",nombre="circulacion_dirigida")
    a=tablas["balance_anual"].loc[lambda t:t.volumen_planificacion.eq(2500000)]
    if a.empty:return
    modos=["Coche particular y alquiler","TITSA","Excursiones/resto colectivo","Lanzadera de acceso"]
    columns=[];labels=[]
    base=a.loc[a.caso.eq("U_2500000_10") & a.escenario.eq("Sin intervención")]
    if base.empty:base=a.loc[a.caso.eq(a.caso.iloc[0]) & a.escenario.eq("Sin intervención")]
    columns.append(base.set_index("modo_entrada").visitas_persona_anio.reindex(modos,fill_value=0));labels.append("Sin\nintervención")
    ref=pd.read_csv(root/"data/silver/movilidad/horarios_550_2028/20261107_cupo550_reservas/balance_anual.csv",sep=";",float_precision="round_trip")
    ref=ref.loc[ref.volumen_planificacion.eq(2500000)&ref.escenario.eq("Con intervención")]
    columns.append(ref.set_index("modo_entrada").visitas_persona_anio.reindex(modos,fill_value=0));labels.append("Con intervención\nReferencia D240")
    for case,label in [("U_2500000_08","Uniforme\n+8 % excursiones"),("U_2500000_10","Uniforme\n+10 % excursiones"),("U_2500000_12","Uniforme\n+12 % excursiones"),("D_2500000","Dirigida\na las puntas")]:
        g=a.loc[a.caso.eq(case)&a.escenario.eq("Con intervención")]
        if not g.empty:columns.append(g.set_index("modo_entrada").visitas_persona_anio.reindex(modos,fill_value=0));labels.append(label)
    colors=["#9BA4A8","#D28558","#397568","#0C4767"]
    with plt.rc_context({"svg.hashsalt":"teide-d241-modal","font.family":"sans-serif","font.sans-serif":["Liberation Sans","DejaVu Sans"]}):
        fig,ax=plt.subplots(figsize=(11,6));bottom=[0.]*len(columns)
        for mode,color in zip(modos,colors):
            vals=[float(c[mode]) for c in columns];ax.bar(range(len(columns)),vals,bottom=bottom,color=color,label=mode)
            bottom=[x+y for x,y in zip(bottom,vals)]
        ax.set_xticks(range(len(labels)),labels,fontsize=9);ax.set_ylabel("Visitas-persona/año de 2028")
        ax.set_ylim(0,2800000);ax.yaxis.set_major_formatter(FuncFormatter(lambda x,_:f"{x:,.0f}".replace(",",".")))
        ax.set_title("Reparto de las mismas 2.500.000 visitas-persona/año",loc="left",fontsize=14)
        ax.legend(loc="upper center",bbox_to_anchor=(.5,-.16),ncol=2,fontsize=9)
        fig.text(.08,.025,"El cupo de coches es 550/día en todas las variantes con intervención. Los porcentajes se refieren a excursiones sin intervención.\n"
                 "El TITSA sustituido queda incluido una vez en lanzaderas. La demanda modal no certifica oferta o ahorro. Fuente: D240 y D241/H131.",fontsize=8)
        fig.subplots_adjust(left=.1,right=.98,top=.9,bottom=.28)
        for ext in ["png","svg","pdf"]:
            meta={"Date":None} if ext=="svg" else {"CreationDate":None,"ModDate":None} if ext=="pdf" else None
            fig.savefig(destino/("comparacion_modal_excursiones."+ext),dpi=180,metadata=meta)
        plt.close(fig)
