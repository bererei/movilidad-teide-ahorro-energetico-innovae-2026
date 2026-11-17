"""Distingo las fuentes actuales de los escenarios y el cambio de calendario."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def dibujar_redistribucion(tablas,destino):
    fmt=FuncFormatter(lambda x,_:f"{x:,.0f}".replace(",","."))
    def guardar(fig,nombre):
        for ext in ["png","svg","pdf"]:
            meta={"Date":None} if ext=="svg" else {"CreationDate":None,"ModDate":None} if ext=="pdf" else None
            fig.savefig(destino/(nombre+"."+ext),dpi=180,metadata=meta)
        plt.close(fig)
    with plt.rc_context({"svg.hashsalt":"teide-d242","font.family":"sans-serif","font.sans-serif":["Liberation Sans","DejaVu Sans"],
                         "text.color":"#24343D","axes.labelcolor":"#24343D","axes.titlecolor":"#0C4767"}):
        f,axs=plt.subplots(1,2,figsize=(12,6));src=tablas["fuentes_2025"].set_index("fuente").cantidad
        vals=[src["Visor, anualización anterior de entradas"],src["Aforos 2025 y ocupaciones históricas"],src["OAPN 2025"]]
        axs[0].bar(range(3),vals,color=["#397568","#9BA4A8","#0C4767"])
        axs[0].set_xticks(range(3),["OD / Visor\n2025","Aforos × ocupación\n2025","OAPN\n2025"],fontsize=9)
        axs[0].set_title("Referencias de partida: alcances distintos",loc="left",fontsize=12)
        axs[0].set_ylabel("Entradas modelizadas / personas-paso / visitas al año")
        modos=["Coche particular y alquiler","TITSA","Excursiones/resto colectivo","Lanzadera de acceso"]
        a=tablas["balance_anual"];bottom=[0.,0.,0.]
        for modo,color,hatch in zip(modos,["#9BA4A8","#FA7921","#397568","#0C4767"],["","..","//","\\\\"]):
            qty=[]
            for case,sc in [("P15","Sin intervención"),("P15","Con intervención"),("P20","Con intervención")]:
                qty.append(float(a.loc[a.caso.eq(case)&a.escenario.eq(sc)&a.modo.eq(modo),"visitas_persona_anio"].item()))
            axs[1].bar(range(3),qty,bottom=bottom,color=color,label=modo,hatch=hatch,edgecolor="white",linewidth=.3)
            bottom=[x+y for x,y in zip(bottom,qty)]
        axs[1].set_xticks(range(3),["Sin intervención","Con P15","Con P20"],fontsize=9)
        axs[1].set_title("Escenarios 2028: mismas 2.500.000 visitas",loc="left",fontsize=12)
        axs[1].set_ylabel("Visitas-persona/año de planificación")
        axs[1].legend(loc="upper center",bbox_to_anchor=(.5,-.13),ncol=2,fontsize=8)
        for ax in axs:ax.yaxis.set_major_formatter(fmt);ax.spines[["top","right"]].set_visible(False)
        f.text(.08,.045,"La cifra de 2,5 millones es una hipótesis orientada por la comunicación interna del Cabildo, sin año de observación concreto.\n"
               "No es una proyección de las 5.113.021 visitas OAPN. Los repartos modales son estimados; TITSA sustituido se incluye una vez en lanzadera.\n"
               "P15/P20: excursiones +15/+20 % en julio; cambio de fecha del 15 % de viajeros elegibles de lanzadera en julio y 10 % en octubre. Fuente: D242/H132.",fontsize=8)
        f.subplots_adjust(left=.09,right=.98,top=.89,bottom=.28,wspace=.35)
        guardar(f,"referencias_y_escenarios")
        f,axs=plt.subplots(1,2,figsize=(11,5.5));p=tablas["perfiles"];orden=["Laborable","Sábado","Domingo"]
        ref=p.loc[p.caso.eq("P15")&p.mes.eq("Julio")].set_index("tipo").loc[orden]
        axs[0].plot(orden,ref.visitas_sin_dia,"o--",color="#9BA4A8",label="Sin intervención")
        for caso,color,style in [("P15","#0C4767","o-"),("P20","#397568","s--")]:
            z=p.loc[p.caso.eq(caso)&p.mes.eq("Julio")].set_index("tipo").loc[orden]
            axs[0].plot(orden,z.visitas_con_dia,style,color=color,label="Con "+caso)
            axs[1].plot(orden,z.programadas_con_cierre,style,color=color,label=caso)
        axs[0].set_ylabel("Visitas-persona/día, todos los modos");axs[0].yaxis.set_major_formatter(fmt)
        axs[0].set_title("Julio: se conserva el total ponderado",loc="left",fontsize=12)
        axs[1].axhline(27,color="#D28558",ls="--",label="27 programadas + 3 libres")
        axs[1].set_ylabel("Guaguas físicas programadas por perfil");axs[1].set_title("Accesos e interior: inventario de treinta",loc="left",fontsize=12)
        axs[1].set_ylim(20,30)
        for ax in axs:ax.legend(fontsize=8);ax.spines[["top","right"]].set_visible(False)
        f.text(.08,.04,"Cambio de fecha supuesto, no observado. Se trasladan viajeros de lanzadera de sábado/domingo al perfil laborable del mismo mes.\n"
               "Excursiones con vehículo y recorrido interior propios; 550 coches/día; intervalos mínimos de quince minutos. Nueve perfiles, sin nuevo p85 ni energía. Fuente: D242/H132.",fontsize=8)
        f.subplots_adjust(left=.1,right=.98,top=.87,bottom=.22,wspace=.3)
        guardar(f,"demanda_y_flota_julio")
