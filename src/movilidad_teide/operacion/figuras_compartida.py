"""Esquema de los recorridos, sin presentar un trazado o giro nuevo como validado."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def dibujar_parciales(red, destino):
    boca, portillo = red.extremos
    sur = red.destinos.loc["CHIO", "parada_destino"]
    norte = red.destinos.loc["OROTAVA", "parada_destino"]
    pos = [red.posiciones[q] / 1000 for q in [boca, sur, norte, portillo]]
    labels = ["Boca Tauce", "Parador /\nCañada Blanca", "Teleférico", "El Portillo"]
    es = lambda x: f"{x:.2f}".replace(".", ",")
    with plt.rc_context({"svg.hashsalt": "teide-d239", "font.family": "sans-serif", "font.sans-serif": ["Liberation Sans", "DejaVu Sans"]}):
        fig, axes = plt.subplots(2, 1, figsize=(10, 6))
        for ax in axes:
            ax.set_xlim(-.6, pos[-1] + .6);ax.set_ylim(-.6, .8);ax.axis("off")
            for x, label in zip(pos, labels):
                ax.plot(x, 0, "o", color="#24343D", markersize=5)
                ax.text(x, -.15, label, ha="center", va="top", fontsize=10)
        axes[0].plot([pos[0], pos[-1]], [0, 0], color="#0C4767", linewidth=4, zorder=0)
        axes[0].text(0, .6, "Recorrido interior completo", fontsize=14, color="#0C4767")
        axes[0].text(pos[-1] / 2, .18, es(red.conectar(boca, portillo)["km"]) + " km · 45 min por sentido", ha="center", fontsize=11)
        axes[1].plot([pos[0], pos[1]], [0, 0], color="#397568", linewidth=4, zorder=0)
        axes[1].plot([pos[2], pos[3]], [0, 0], color="#397568", linewidth=4, zorder=0)
        axes[1].plot([pos[1], pos[2]], [0, 0], color="#7C858C", linewidth=2, linestyle=":", zorder=0)
        axes[1].text(0, .6, "Parciales para las cadenas de visita modelizadas", fontsize=14, color="#0C4767")
        for a, b in [(boca, sur), (norte, portillo)]:
            x = (red.posiciones[a] + red.posiciones[b]) / 2000
            axes[1].text(x, .18, es(red.conectar(a, b)["minutos"]) + " min", ha="center", fontsize=11)
        axes[1].text((pos[1] + pos[2]) / 2, -.4, "Oferta de continuidad por definir", ha="center", fontsize=8)
        fig.text(.07, .025, "Esquema lineal; no es un mapa ni una autorización de maniobra. Los tiempos parciales son proporcionales al eje existente.\n"
                 "Los giros y el servicio a otros destinos necesitan validación. Acortar recorridos no acredita por sí solo una flota de treinta.\n"
                 "Un vehículo puede alternar funciones de acceso e interior; cada unidad física se cuenta una sola vez. Fuente: D239/H129.", fontsize=8)
        fig.subplots_adjust(left=.07, right=.97, bottom=.18, top=.97, hspace=.1)
        for ext in ["png", "svg", "pdf"]:
            metadata = {"Date": None} if ext == "svg" else {"CreationDate": None, "ModDate": None} if ext == "pdf" else None
            fig.savefig(destino / ("esquema_servicios_parciales." + ext), dpi=180, metadata=metadata)
        plt.close(fig)
