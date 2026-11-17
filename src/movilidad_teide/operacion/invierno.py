"""Vinculo la llegada comercial a cabecera con el ocaso de referencia."""
import math
import numpy as np
import pandas as pd
from .reloj_integrado import RelojIntegrado
from .refinar_reservas import FORMAS


def limites_llegada_con_luz(red,valores,*,ocaso_min,margen_min):
    """El margen es una hipótesis de contraste, no una garantía de visibilidad."""
    if not np.isfinite([ocaso_min,margen_min]).all() or not 0<ocaso_min<1440 or margen_min<0:
        raise ValueError("Ocaso o margen inválidos.")
    llegada=ocaso_min-margen_min;rows=[]
    cap=int(valores['plazas_guagua']*valores['ocupacion_diseno'])
    for punto in red.puntos:
        entrada=red.destinos.loc[punto,'parada_entrada'];cabecera='cabecera:'+punto
        subida=red.conectar(cabecera,entrada)['minutos'];bajada=red.conectar(entrada,cabecera)['minutos']
        regreso=llegada-bajada;ultima_subida=regreso-valores['estancia_min_visita_min']-subida
        n=max(0,math.floor((ultima_subida-60*valores['hora_inicio_acceso'])/valores['intervalo_refuerzo_punta_min'])+1)
        rows.append({'punto':punto,'ocaso_referencia_min':ocaso_min,'margen_min':margen_min,'limite_llegada_cabecera_min':llegada,
            'tiempo_subida_min':subida,'tiempo_descenso_min':bajada,'ultimo_paso_regreso_parque_min':regreso,
            'ultima_salida_cabecera_min':ultima_subida,'maximo_salidas_intervalo':n,'capacidad_maxima_intervalo_personas':n*cap})
    return pd.DataFrame(rows)


def relojes_de_invierno(objetivos,red,valores,cuotas,limites):
    cierres=dict(zip(limites.punto,limites.ultimo_paso_regreso_parque_min))
    vv={**valores,'hora_limite_bajada_parque':max(cierres.values())/60}
    reloj=RelojIntegrado(objetivos,red,vv,cuotas,limites_regreso_por_punto=cierres,
                         admitir_accesos_sin_demanda=True);out=[]
    for forma,alpha in FORMAS:
        u,b=reloj.inicial(forma,alpha);n,e=reloj.evaluar(u,b);out.append(((n,-e,forma,alpha),reloj,u,b))
    return sorted(out,key=lambda t:t[0])
