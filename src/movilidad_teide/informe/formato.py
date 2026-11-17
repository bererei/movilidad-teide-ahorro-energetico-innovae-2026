"""Formato numérico y escape LaTeX compartidos."""
import numpy as np
import pandas as pd

def numero(x, dec=2):
    return f'{float(x):,.{dec}f}'.replace(',', '_').replace('.', ',').replace('_', '.')

def tex(s):
    mapping = {'\\': '\\textbackslash{}', '&': '\\&', '%': '\\%', '_': '\\_', '#': '\\#', '$': '\\$', '{': '\\{', '}': '\\}'}
    return ''.join((mapping.get(c, c) for c in str(s)))


def formatear_ejes(fig):
    """Aplico coma decimal y punto de millar a los ejes numéricos del informe."""
    import math
    from matplotlib.ticker import ScalarFormatter, FuncFormatter
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            if not isinstance(axis.get_major_formatter(), ScalarFormatter):
                continue
            ticks = axis.get_majorticklocs()
            pasos = [abs(b-a) for a,b in zip(ticks,ticks[1:]) if b != a]
            dec = max(0, min(6, math.ceil(-math.log10(min(pasos)) - 1e-9))) if pasos else 0
            axis.set_major_formatter(FuncFormatter(lambda v, pos, d=dec: numero(v,d)))
