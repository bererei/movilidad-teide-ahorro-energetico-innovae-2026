"""Reasigno modos en perfiles de invierno sin cambiar sus visitas u orígenes."""
import numpy as np
import pandas as pd


def limites_cuotas(origenes,incremento,*,ocupacion):
    """La cuota proporcional no puede agotar el coche destinado a excursiones."""
    if not np.isfinite([incremento,ocupacion]).all() or incremento<0 or ocupacion<1:
        raise ValueError('Incremento u ocupación no válidos.')
    x=origenes;C=x.visitas_coche;E=x.visitas_excursiones_resto_colectivo
    if (not np.isfinite(x[['visitas_coche','visitas_excursiones_resto_colectivo']]).all().all()
        or C.lt(0).any() or E.lt(0).any() or (C.eq(0)&(incremento*E).gt(1e-8)).any()):raise ValueError('No hay población elegible en algún origen/colectivo.')
    fraccion=np.divide(incremento*E,C,out=np.zeros(len(x)),where=C.gt(0))
    t=x.assign(fraccion=fraccion).groupby('punto').agg(visitas_coche=('visitas_coche','sum'),fraccion=('fraccion','max'))
    return (t.visitas_coche/ocupacion*(1-t.fraccion)).clip(lower=0)


def reasignar_invierno(origenes,puntos,cuotas,*,incremento,ocupacion):
    """Las excursiones aumentan sobre la referencia invernal, igual a sin.

    TITSA sigue en su corredor nativo. Coche autorizado se reparte dentro de
    cada acceso según el peso original de coche por origen/colectivo.
    """
    if (set(cuotas)!=set(puntos.punto) or puntos.punto.duplicated().any()
        or any(isinstance(q,bool) or not np.isfinite(q) or q<0 or int(q)!=q for q in cuotas.values())):
        raise ValueError('Cuotas de coches inválidas.')
    maximos=limites_cuotas(origenes,incremento,ocupacion=ocupacion)
    if not np.allclose(puntos.visitas_excursiones_con_intervencion_dia,puntos.visitas_excursiones_resto_colectivo,atol=1e-8,rtol=0):
        raise ValueError('Partir de la referencia de invierno sin incremento previo.')
    # Si no se usa todo el cupo, las autorizaciones efectivas son las visitas
    # disponibles. Con incremento positivo también se respeta la bolsa elegible.
    Ctotal=origenes.groupby('punto').visitas_coche.sum()
    efectivos=pd.Series({p:min(float(q),float(Ctotal[p]/ocupacion)) for p,q in cuotas.items()})
    if (efectivos-maximos.reindex(efectivos.index)>1e-8).any():raise ValueError('Cupo incompatible con excursiones en algún origen/colectivo.')
    keys=['origen_id','colectivo','access_corridor','punto','peso_origen_condicionado']
    x=origenes[keys+['visitas_coche','visitas_excursiones_resto_colectivo']].copy()
    ratio=efectivos*ocupacion/Ctotal.replace(0,np.nan)
    x['visitas_coche_autorizadas_dia']=x.visitas_coche*x.punto.map(ratio).fillna(0)
    x['visitas_adicionales_excursion_dia']=incremento*x.visitas_excursiones_resto_colectivo
    x['visitas_excursiones_con_intervencion_dia']=x.visitas_excursiones_resto_colectivo+x.visitas_adicionales_excursion_dia
    x['visitas_coche_a_lanzadera_dia']=x.visitas_coche-x.visitas_coche_autorizadas_dia-x.visitas_adicionales_excursion_dia
    limite=8*np.finfo(float).eps*np.maximum(x.visitas_coche.abs(),1)
    bad=x.visitas_coche_a_lanzadera_dia.lt(0)
    if (-x.loc[bad,'visitas_coche_a_lanzadera_dia']>limite[bad]).any():raise ValueError('Reasignación negativa material.')
    x.loc[bad,'visitas_coche_a_lanzadera_dia']=0.
    x['visitas_sin_parcial_coche_excursion_dia']=x.visitas_coche+x.visitas_excursiones_resto_colectivo
    x['visitas_con_parcial_coche_excursion_dia']=x.visitas_coche_autorizadas_dia+x.visitas_excursiones_con_intervencion_dia+x.visitas_coche_a_lanzadera_dia
    if not np.allclose(x.visitas_sin_parcial_coche_excursion_dia,x.visitas_con_parcial_coche_excursion_dia,atol=1e-8,rtol=0):raise ValueError('Se pierde un origen/colectivo.')
    fields=['visitas_coche_autorizadas_dia','visitas_adicionales_excursion_dia','visitas_excursiones_con_intervencion_dia','visitas_coche_a_lanzadera_dia']
    p=puntos[['punto','visitas_coche','visitas_excursiones_resto_colectivo','visitas_titsa','visitas_sin_dia']].merge(x.groupby('punto',as_index=False)[fields].sum(),on='punto',validate='one_to_one')
    p['coches_autorizados_dia']=p.visitas_coche_autorizadas_dia/ocupacion;p['cuota_maxima_coches_dia']=p.punto.map(cuotas)
    p['demanda_lanzadera_dia']=p.visitas_coche_a_lanzadera_dia+p.visitas_titsa
    p['demanda_bruta_lanzadera_dia']=p.demanda_lanzadera_dia+p.punto.map(cuotas)*ocupacion
    p['visitas_con_objetivo_dia']=p.visitas_coche_autorizadas_dia+p.visitas_excursiones_con_intervencion_dia+p.demanda_lanzadera_dia
    p['regresos_lanzadera_pareados_dia']=p.demanda_lanzadera_dia
    if not np.allclose(p.visitas_sin_dia,p.visitas_con_objetivo_dia,atol=1e-8,rtol=0):raise ValueError('Se pierde población del perfil.')
    return x,p
