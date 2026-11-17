"""Reconstruyo las nueve referencias OD de 2025 para contrastar la operación."""
import numpy as np
import pandas as pd

from .escenarios_2028 import calendario


COLECTIVOS = ["extranjero", "espana_no_tenerife", "tenerife_no_frecuente", "tenerife_resto"]


def reconstruir_observaciones(perfiles, indices, media, *, total, fraccion_coche,
                             hora_inicio, hora_fin):
    """Escalo una vez la forma OD y mantengo la referencia TITSA por tipo de día.

    TITSA no se convierte en medición mensual: mantengo el total por corredor,
    colectivo y ventana de captación de D237. Solo distribuyo sus horas dentro
    de esa ventana según la forma OD de cada observación. La ponderación de los
    tres meses conserva exactamente la separación modal anual anterior.
    """
    seleccion = indices.loc[indices.anio.eq(2025),
        ["matrix_index", "mes_publicado", "tipo_dia_publicado"]]
    if (len(seleccion) != 9 or seleccion.matrix_index.duplicated().any()
            or not seleccion.groupby("tipo_dia_publicado").size().eq(3).all()):
        raise ValueError("Se requieren las nueve referencias de 2025, tres por tipo de día.")
    p = perfiles.loc[perfiles.direccion.eq("subida")].merge(seleccion, on="matrix_index", validate="many_to_one")
    keys = ["matrix_index", "mes_publicado", "tipo_dia_publicado", "access_corridor", "hora_servicio"]
    if (p.duplicated(["matrix_index", "access_corridor", "hora_servicio"]).any()
            or set(p.matrix_index) != set(seleccion.matrix_index)
            or not p.hora_servicio.isin(range(24)).all()
            or not np.isfinite(p[COLECTIVOS]).all().all() or p[COLECTIVOS].lt(0).any().any()):
        raise ValueError("Las observaciones OD no son físicas o están repetidas.")
    h = p.melt(id_vars=keys, value_vars=COLECTIVOS, var_name="colectivo", value_name="personas_od")
    h["dias_calendario"] = h.tipo_dia_publicado.map(calendario(2028))
    base = float((h.personas_od * h.dias_calendario / 3).sum())
    if not np.isfinite(total) or total <= 0 or base <= 0 or not 0 <= fraccion_coche <= 1:
        raise ValueError("Volumen o cuota modal inválidos.")
    h["visitas_persona_dia"] = h.personas_od * total / base
    h["visitas_coche"] = h.visitas_persona_dia * fraccion_coche
    h["ventana_captacion"] = h.hora_servicio.between(hora_inicio, hora_fin)
    grupos = ["access_corridor", "colectivo", "tipo_dia_publicado", "ventana_captacion"]
    n = media.assign(ventana_captacion=media.hora_servicio.between(hora_inicio, hora_fin))
    n = n.groupby(grupos, as_index=False).visitas_titsa.sum().rename(columns={"visitas_titsa": "titsa_grupo_dia"})
    h = h.merge(n, on=grupos, validate="many_to_one")
    if h.titsa_grupo_dia.isna().any():
        raise ValueError("Una referencia OD carece de correspondencia TITSA.")
    den = h.groupby(["matrix_index", *grupos]).personas_od.transform("sum")
    if (den.eq(0) & h.titsa_grupo_dia.gt(0)).any():
        raise ValueError("TITSA positivo sin peso horario compatible; no se asigna cero.")
    h["visitas_titsa"] = h.titsa_grupo_dia * np.divide(h.personas_od, den,
        out=np.zeros(len(h)), where=den.gt(0))
    h["visitas_excursiones_resto_colectivo"] = h.visitas_persona_dia - h.visitas_coche - h.visitas_titsa
    if h.visitas_excursiones_resto_colectivo.lt(0).any():
        raise ValueError("La referencia OD deja un residuo colectivo negativo.")
    # Cada observación conserva el TITSA de su tipo; las ausencias no se rellenan.
    for _, b in h.groupby("matrix_index"):
        expected = n.loc[n.tipo_dia_publicado.eq(b.tipo_dia_publicado.iloc[0])].set_index(grupos).titsa_grupo_dia
        actual = b.groupby(grupos).visitas_titsa.sum()
        if (set(expected.loc[expected.gt(0)].index) - set(actual.index)
                or not np.allclose(actual, expected.reindex(actual.index), atol=1e-8, rtol=0)):
            raise ValueError("Una observación pierde TITSA; no se recorta la referencia nativa.")
    h["anio"] = 2028
    h["dias_equivalentes"] = h.dias_calendario / 3
    h["unidad"] = "visitas-persona/día; referencia OD escalada, no observación de 2028"
    return h
