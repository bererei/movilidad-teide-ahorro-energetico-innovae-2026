"""Presento la circulación construida y los límites de 27 o 28 programadas."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


def dibujar_circulaciones(movimientos, perfiles, destino, *, subtitulo=None,
                         decision="D240", hipotesis="H130", nombre="circulacion_550"):
    central = perfiles.loc[perfiles.volumen_planificacion.eq(2500000)]
    if central.empty or movimientos.empty:return
    obs = int(central.sort_values(["vehiculos_programados_reloj", "observacion"]).iloc[-1].observacion)
    m = movimientos.loc[movimientos.volumen_planificacion.eq(2500000) & movimientos.observacion.eq(obs)]
    if m.empty:return
    units = sorted(m.unidad_fisica_id.unique());colors = {"Subida": "#0C4767", "Regreso": "#397568", "Vacío": "#9BA4A8"}
    with plt.rc_context({"svg.hashsalt": "teide-" + decision.lower(), "font.family": "sans-serif", "font.sans-serif": ["Liberation Sans", "DejaVu Sans"]}):
        fig, ax = plt.subplots(figsize=(11, 8))
        for i, unit in enumerate(units):
            for row in m.loc[m.unidad_fisica_id.eq(unit)].itertuples():
                clase = "Vacío" if row.familia == "Vacío" else "Subida" if row.id_salida.endswith("_ida") else "Regreso"
                ax.broken_barh([(row.salida_min / 60, (row.llegada_min - row.salida_min) / 60)], (i+.15, .7), facecolors=colors[clase])
        ax.axhline(27, linestyle="--", color="#D28558", linewidth=1.2)
        ax.axhline(28, linestyle=":", color="#24343D", linewidth=1.2)
        ax.set_yticks([i+.5 for i in range(len(units))], units, fontsize=8)
        ax.set_xticks(range(7, 21), [f"{h:02d}:00" for h in range(7, 21)])
        ax.set_xlim(6.9, 20.1);ax.set_ylim(0, max(len(units), 28 if subtitulo else 0)+.2);ax.invert_yaxis()
        ax.set_xlabel("Hora de la jornada de estudio");ax.set_ylabel("Guaguas físicas programadas")
        ax.grid(axis="x", alpha=.18)
        name = central.loc[central.observacion.eq(obs), "perfil"].iloc[0]
        title = f"Circulación diagnóstica · {name}\n2.500.000 visitas-persona/año · 550 coches/día · {len(units)} guaguas programadas"
        if subtitulo:title += "\n" + subtitulo
        ax.set_title(title, loc="left", fontsize=13)
        handles = [Patch(color=c, label=n) for n, c in colors.items()]
        handles += [plt.Line2D([], [], color="#D28558", linestyle="--", label="Máximo 27 con tres reservas"),
                    plt.Line2D([], [], color="#24343D", linestyle=":", label="Máximo 28 con dos reservas")]
        ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, -.09), ncol=3, fontsize=9)
        fig.text(.075, .018, "Cada fila identifica una unidad, aunque alterne corredores. Incluye vacíos; las pausas blancas no son viajes.\n"
                 f"Diagnóstico de los recorridos modelizados; no acredita oferta anual de treinta ni aprobación de giros o explotación. Fuente: {decision}/{hipotesis}.", fontsize=8)
        fig.subplots_adjust(left=.085, right=.98, top=.86 if subtitulo else .9, bottom=.17)
        for ext in ["png", "svg", "pdf"]:
            meta = {"Date": None} if ext == "svg" else {"CreationDate": None, "ModDate": None} if ext == "pdf" else None
            fig.savefig(destino / (nombre + "." + ext), dpi=180, metadata=meta)
        plt.close(fig)
