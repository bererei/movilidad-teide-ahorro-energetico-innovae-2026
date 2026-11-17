"""Presento cotas de vehículos físicos sin convertirlas en oferta suficiente."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator


def dibujar_cotas(tablas, destino):
    c = tablas["cota_todos_los_repartos"]
    c = c.loc[c.cupo_global_coches_dia.eq(500) & ~c.es_media_tipo]
    c = c.loc[c.groupby("volumen_planificacion").cota_con_sustitucion.idxmax()].sort_values("volumen_planificacion")
    anual = tablas["balance_anual"]
    a = anual.loc[anual.cupo_global_coches_dia.eq(500) & anual.politica_cupo.eq("Proporcional OD")
                  & anual.escenario.eq("Con intervención") & anual.modo_entrada.eq("Lanzadera de acceso")]
    c = c.merge(a[["volumen_planificacion", "visitas_persona_anio"]], on="volumen_planificacion", validate="one_to_one")
    with plt.rc_context({"svg.hashsalt": "teide-d238", "font.size": 10}):
        fig, ax = plt.subplots(figsize=(9, 5.6))
        for col, label, color, style in [("cota_acceso", "Cota de vehículos de acceso", "#0C4767", "-"),
                ("cota_interior", "Cota de vehículos interiores", "#397568", "-"),
                ("cota_con_sustitucion", "Cota total, incluidas tres sustitutas", "#FA7921", "--")]:
            ax.plot(c.visitas_persona_anio, c[col], style, marker="o", color=color, label=label)
        ax.axhline(30, color="#24343D", linewidth=1, linestyle=":", label="Inventario: 30 vehículos")
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, pos: f"{x / 1e6:.2f}".replace(".", ",")))
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_xlabel("Visitas-persona anuales en lanzadera de acceso (millones)")
        ax.set_ylabel("Vehículos físicos · cota necesaria")
        ax.set_title("Demanda y flota: límite favorable del modelo", loc="left", color="#0C4767")
        ax.grid(axis="y", alpha=.2)
        ax.legend(loc="center right", fontsize=8)
        fig.text(.11, .035, "Cupo global: 500 coches/día. Mayor cota entre nueve perfiles; tres volúmenes de planificación.\n"
                 "Servicios separados y recorridos interiores completos. No es un horario ni una capacidad acreditada.\n"
                 "El eje X excluye las visitas que entran en coche o permanecen en excursiones. Fuente: D238/H128.", fontsize=8)
        fig.subplots_adjust(bottom=.24, left=.11, right=.97, top=.9)
        for ext in ["png", "svg", "pdf"]:
            metadata = {"Date": None} if ext == "svg" else {"CreationDate": None, "ModDate": None} if ext == "pdf" else None
            fig.savefig(destino / ("demanda_y_cotas_flota." + ext), dpi=180, metadata=metadata)
        plt.close(fig)
