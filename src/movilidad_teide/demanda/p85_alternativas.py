"""Construyo la muestra de diseño con la escala y los cambios modales vigentes."""
import numpy as np
import pandas as pd

from movilidad_teide.opciones import PUNTOS
from .escenarios_2028 import calendario
from .perfiles_operacion_2028 import COLECTIVOS
from .redistribucion_temporal import redistribuir_fechas


def adaptar_reparto_titsa(referencia,capacidad):
    """Conservo el total conocido y adapto solo su reparto estimado por colectivo.

    Si un colectivo OD no puede contener el TITSA que el reparto de referencia
    le atribuiría, distribuyo la diferencia entre los demás sin superar su
    población colectiva. No es una corrección de pasajeros observados de TITSA.
    """
    referencia=np.asarray(referencia,dtype=float);capacidad=np.asarray(capacidad,dtype=float)
    if referencia.shape!=capacidad.shape or not np.isfinite([referencia,capacidad]).all() or (referencia<0).any() or (capacidad<0).any():raise ValueError("Reparto TITSA no físico.")
    if referencia.sum()>capacidad.sum()+1e-8:raise ValueError("TITSA excede toda la población colectiva; no se fuerza el encaje.")
    actual=np.minimum(referencia,capacidad)
    for _ in range(len(actual)+1):
        falta=referencia.sum()-actual.sum()
        if falta<1e-12:break
        libres=capacidad-actual;w=np.where(libres>1e-12,referencia,0.)
        if w.sum()==0:w=libres
        if w.sum()==0:raise ValueError("No queda población compatible para TITSA.")
        actual+=np.minimum(libres,falta*w/w.sum())
    if abs(actual.sum()-referencia.sum())>1e-8:raise ValueError("Se pierde TITSA al adaptar colectivos.")
    return actual


def representar_ceros_numericos(base,*,ocupacion):
    """Registro residuos negativos de redondeo en flujos matemáticamente nulos.

    El límite depende de ocho epsilones de la magnitud de la resta; no es la
    tolerancia de conservación ni permite eliminar una demanda negativa real.
    No modifica fuentes, hipótesis, parámetros o el productor histórico.
    """
    x=base["por_origen_dia"].copy();pt=base["escenarios_por_punto_dia"].copy();filas=[]
    for c in ["visitas_coche_transferidas_dia","visitas_excursiones_transferidas_dia"]:
        limite=8*np.finfo(float).eps*np.maximum(x[c+"_referencia"].abs(),1.)
        bad=x[c].lt(0)
        if (-x.loc[bad,c]>limite.loc[bad]).any():raise ValueError("Flujo negativo material, no redondeo.")
        for row in x.loc[bad,["origen_id","colectivo","punto",c]].to_dict("records"):
            filas.append({**{k:row[k] for k in ["origen_id","colectivo","punto"]},"flujo":c,"residuo":row[c]})
        x.loc[bad,c]=0.
        pt[c]=pt.punto.map(x.groupby("punto")[c].sum())
    pt["demanda_lanzadera_dia"]=pt.visitas_coche_transferidas_dia+pt.visitas_excursiones_transferidas_dia+pt.visitas_titsa
    pt["visitas_con_objetivo_dia"]=pt.visitas_coche_autorizadas_dia+pt.visitas_excursiones_con_intervencion_dia+pt.demanda_lanzadera_dia
    pt["demanda_bruta_lanzadera_dia"]=pt.demanda_lanzadera_dia+pt.coches_autorizados_dia*ocupacion
    pt["regresos_lanzadera_pareados_dia"]=pt.demanda_lanzadera_dia
    return {**base,"por_origen_dia":x,"escenarios_por_punto_dia":pt},pd.DataFrame(filas)


def reconstruir_muestra(perfiles,indices,media,*,total,fraccion_coche,hora_inicio,hora_fin,festivos="Domingo",registrar_residuos=False):
    """Escalo las 57 observaciones una vez, usando la anualización OD de 2025.

    No igualo el volumen de cada matriz ni convierto 57 referencias en días
    anuales. Para días especiales contrasto domingo y extremos de las tres
    referencias TITSA por corredor/colectivo/ventana: no son datos de festivo.
    """
    keys=["matrix_index","access_corridor","hora_servicio"]
    up=perfiles.loc[perfiles.direccion.eq("subida")].copy()
    if (set(indices.matrix_index)!=set(range(57)) or indices.matrix_index.duplicated().any()
        or set(up.matrix_index)!=set(range(57)) or up.duplicated(keys).any()
        or not np.isfinite(up[COLECTIVOS]).all().all() or up[COLECTIVOS].lt(0).any().any()
        or not up.hora_servicio.isin(range(24)).all()):raise ValueError("Muestra de 57 matrices inválida.")
    if (not np.isfinite([total,fraccion_coche]).all() or total<=0 or not 0<=fraccion_coche<=1
        or festivos not in ["Domingo","minimo","maximo"]):raise ValueError("Escala o contraste TITSA inválidos.")
    tags=indices[["matrix_index","anio","mes_publicado","tipo_dia_publicado"]].rename(columns={"anio":"anio_fuente"})
    up=up.merge(tags,on="matrix_index",validate="many_to_one")
    h=up.melt(id_vars=keys+["anio_fuente","mes_publicado","tipo_dia_publicado"],value_vars=COLECTIVOS,var_name="colectivo",value_name="personas_od")
    cal=calendario(2028);ref=h.loc[h.anio_fuente.eq(2025)].copy()
    if ref.matrix_index.nunique()!=9 or ref.tipo_dia_publicado.map(cal).isna().any():raise ValueError("Falta la referencia anual de 2025.")
    denominador=(ref.personas_od*ref.tipo_dia_publicado.map(cal)/3).sum()
    if denominador<=0:raise ValueError("Referencia anual no positiva.")
    escala=total/denominador
    h["visitas_persona_dia"]=h.personas_od*escala
    h["visitas_coche"]=h.visitas_persona_dia*fraccion_coche
    h["ventana_captacion"]=h.hora_servicio.between(hora_inicio,hora_fin)
    group=["access_corridor","colectivo","ventana_captacion"]
    n=media.assign(ventana_captacion=media.hora_servicio.between(hora_inicio,hora_fin))
    n=n.groupby([*group,"tipo_dia_publicado"]).visitas_titsa.sum().unstack("tipo_dia_publicado")
    if set(n.columns)!=set(cal):raise ValueError("Referencias TITSA incompletas.")
    n["Festivo/especial"]=(n.Domingo if festivos=="Domingo" else n[list(cal)].min(axis=1) if festivos=="minimo" else n[list(cal)].max(axis=1))
    native=n.stack(future_stack=True).rename("titsa_grupo_dia").reset_index()
    h=h.merge(native,on=[*group,"tipo_dia_publicado"],how="left",validate="many_to_one")
    if h.titsa_grupo_dia.isna().any():raise ValueError("Tipo de día sin referencia TITSA declarada.")
    h["titsa_grupo_dia_referencia"]=h.titsa_grupo_dia
    ck=["matrix_index",*group]
    reparto=h.groupby(ck,as_index=False).agg(referencia=("titsa_grupo_dia","first"),poblacion=("visitas_persona_dia","sum"))
    partes=[]
    for _,g in reparto.groupby(["matrix_index","access_corridor","ventana_captacion"]):
        g=g.copy();g["titsa_adaptado"]=adaptar_reparto_titsa(g.referencia.to_numpy(),g.poblacion.to_numpy()*(1-fraccion_coche));partes.append(g)
    rp=pd.concat(partes).set_index(ck).titsa_adaptado
    h["titsa_grupo_dia"]=pd.MultiIndex.from_frame(h[ck]).map(rp).to_numpy()
    h["reparto_titsa_adaptado"]=(h.titsa_grupo_dia-h.titsa_grupo_dia_referencia).abs()>1e-12
    den=h.groupby(ck).personas_od.transform("sum")
    h["visitas_titsa"]=h.titsa_grupo_dia*np.divide(h.personas_od,den,out=np.zeros(len(h)),where=den.gt(0))
    h["visitas_excursiones_resto_colectivo"]=h.visitas_persona_dia-h.visitas_coche-h.visitas_titsa
    residuos=[]
    negativos=h.visitas_excursiones_resto_colectivo.lt(0)
    if negativos.any():
        limite=8*np.finfo(float).eps*h.visitas_persona_dia.abs().clip(lower=1)
        if not registrar_residuos or (-h.loc[negativos,'visitas_excursiones_resto_colectivo']>limite[negativos]).any():
            raise ValueError("Residuo colectivo negativo.")
        for a in h.loc[negativos].itertuples():
            residuos.append({'matrix_index':int(a.matrix_index),'access_corridor':a.access_corridor,'colectivo':a.colectivo,'hora_servicio':int(a.hora_servicio),
                'residuo':float(a.visitas_excursiones_resto_colectivo),'limite_8eps':float(limite.loc[a.Index])})
        h.loc[negativos,'visitas_excursiones_resto_colectivo']=0.

    h["dias_calendario"]=h.tipo_dia_publicado.map(cal).fillna(1).astype(int)
    h["estado_dias"]=np.where(h.tipo_dia_publicado.eq("Festivo/especial"),"Una referencia diagnóstica, sin anualización","Días 2028 solo para ponderar traspasos dentro de la terna")
    h["referencia_titsa_dia_especial"]=festivos
    calibracion={"escala_comun_OD":float(escala),"denominador_nueve_perfiles_2025_calendario_2028":float(denominador),"volumen_anual_planificacion":total}
    if registrar_residuos:calibracion["ceros_numericos_excursion"]=residuos
    return h,calibracion


def cambiar_fechas_muestra(escenarios,indices,fracciones,*,ocupacion,cumplimiento):
    """Extiendo la regla a ternas completas del mismo año y mes; especiales intactos."""
    if not np.isfinite(cumplimiento) or not 0<=cumplimiento<=1:raise ValueError("Cumplimiento temporal inválido.")
    result=dict(escenarios);trazas=[]
    for (anio,mes),g in indices.groupby(["anio","mes_publicado"]):
        q=fracciones.get(mes,0.)*cumplimiento
        if q==0:continue
        normal=g.loc[g.tipo_dia_publicado.isin(["Laborable","Sábado","Domingo"])]
        if sorted(normal.tipo_dia_publicado.tolist())!=["Domingo","Laborable","Sábado"]:
            raise ValueError(f"No se inventa una terna receptora ausente: {anio}/{mes}.")
        p=normal[["matrix_index","mes_publicado","tipo_dia_publicado"]].rename(columns={"matrix_index":"observacion","mes_publicado":"mes","tipo_dia_publicado":"tipo"})
        p["dias_equivalentes"]=p.tipo.map(calendario(2028))/3
        subset={int(obs):escenarios[int(obs)] for obs in p.observacion}
        nuevo,tr=redistribuir_fechas(subset,p,{mes:q},ocupacion=ocupacion)
        result.update(nuevo);trazas.append(tr.assign(anio_fuente=anio))
    return result,pd.concat(trazas,ignore_index=True) if trazas else pd.DataFrame()


def repartir_horas_muestra(escenarios,horaria):
    """Reparto modal antes de cambiar fechas; no son llegadas observadas.

    El reparto usa las horas publicadas, sin rellenar con ceros las ausentes.
    El percentil horario excluye agregados que no reúnen todos sus corredores.
    Las observaciones diarias conservan sus sumas de entrada publicadas.
    """
    h=horaria.copy();group=["matrix_index","access_corridor","colectivo"]
    h["peso_coche_hora"]=h.visitas_coche/h.groupby(group).visitas_coche.transform("sum").replace(0,np.nan)
    h["excursion_ventana"]=h.visitas_excursiones_resto_colectivo*h.ventana_captacion
    h["peso_excursion_hora"]=h.excursion_ventana/h.groupby(group).excursion_ventana.transform("sum").replace(0,np.nan)
    xs=pd.concat([z["por_origen_dia"].assign(matrix_index=obs) for obs,z in escenarios.items()],ignore_index=True)
    b=xs.merge(h[[*group,"hora_servicio","peso_coche_hora","peso_excursion_hora"]],on=group,validate="many_to_many")
    for flow,peso in [("visitas_coche_transferidas_dia","peso_coche_hora"),("visitas_excursiones_transferidas_dia","peso_excursion_hora")]:
        if (b[flow].gt(0)&b[peso].isna()).any():raise ValueError("Viajeros positivos sin forma horaria compatible.")
    b["personas_coche"]=b.visitas_coche_transferidas_dia*b.peso_coche_hora.fillna(0)
    b["personas_excursion"]=b.visitas_excursiones_transferidas_dia*b.peso_excursion_hora.fillna(0)
    # Un peso cero de un flujo nulo no convierte una hora no publicada en cero.
    keys=["matrix_index","punto","hora_servicio"]
    z=b.groupby(keys,as_index=False)[["personas_coche","personas_excursion"]].sum()
    nt=h.copy();nt["punto"]=nt.access_corridor.map(PUNTOS)
    nt=nt.groupby(keys,as_index=False).visitas_titsa.sum()
    z=z.merge(nt,on=keys,how="outer",validate="one_to_one")
    # Las columnas son contribuciones distribuidas del modelo, no conteos OD.
    # Una contribución ausente en la unión no recibe viajeros. La cobertura
    # de fuentes se marca aparte y excluye la hora incompleta del percentil.
    z[["personas_coche","personas_excursion","visitas_titsa"]]=z[["personas_coche","personas_excursion","visitas_titsa"]].fillna(0.)
    z["personas_lanzadera"]=z.personas_coche+z.personas_excursion+z.visitas_titsa
    # Cobertura: todas las fuentes con viajeros diarios que alimentan ese punto.
    expected=xs.groupby(["matrix_index","punto"]).access_corridor.agg(set).to_dict()
    for row in h[["matrix_index","access_corridor"]].drop_duplicates().itertuples():expected[row.matrix_index,PUNTOS[row.access_corridor]].add(row.access_corridor)
    published=h[["matrix_index","access_corridor","hora_servicio"]].drop_duplicates().groupby(["matrix_index","hora_servicio"]).access_corridor.agg(set).to_dict()
    z["cobertura_horaria_completa"]=[expected[i,p].issubset(published[i,hr]) for i,p,hr in z[keys].itertuples(index=False,name=None)]
    z["dentro_ventana_fuente"]=z.hora_servicio.between(int(h.loc[h.ventana_captacion,"hora_servicio"].min()),int(h.loc[h.ventana_captacion,"hora_servicio"].max()))
    for obs,base in escenarios.items():
        target=base["escenarios_por_punto_dia"].set_index("punto").demanda_lanzadera_dia.sort_index()
        got=z[z.matrix_index.eq(obs)].groupby("punto").personas_lanzadera.sum().sort_index()
        if not np.allclose(got,target,rtol=0,atol=1e-8):raise ValueError("La forma horaria pierde viajeros de un acceso.")
    return z


def trasladar_horas(horarios,indices,fracciones,*,cumplimiento,hora_inicio,hora_fin):
    """Quien cambia de fecha conserva su preferencia horaria de origen.

    Así no hace falta inventar una curva receptora para un colectivo que era
    nulo en el laborable. Una hora añadida por traspaso queda identificada y no
    se convierte en un cero observado de la matriz receptora.
    """
    result={int(i):g.copy().set_index(["punto","hora_servicio"]) for i,g in horarios.groupby("matrix_index")}
    flujos=["personas_coche","personas_excursion"]
    for (_,mes),g in indices.groupby(["anio","mes_publicado"]):
        q=fracciones.get(mes,0.)*cumplimiento
        if q==0:continue
        normal=g.loc[g.tipo_dia_publicado.isin(["Laborable","Sábado","Domingo"])]
        if sorted(normal.tipo_dia_publicado.tolist())!=["Domingo","Laborable","Sábado"]:raise ValueError("Falta una terna para el traspaso horario.")
        dest=int(normal.loc[normal.tipo_dia_publicado.eq("Laborable"),"matrix_index"].item())
        w=calendario(2028);receptor=result[dest]
        for row in normal.loc[normal.tipo_dia_publicado.ne("Laborable")].itertuples():
            fuente=result[int(row.matrix_index)];mov=fuente[flujos]*q
            fuente[flujos]-=mov
            union=receptor.index.union(mov.index)
            ampliado=receptor.reindex(union).copy()
            ampliado[flujos+["visitas_titsa"]]=ampliado[flujos+["visitas_titsa"]].fillna(0.)
            ampliado[flujos]+=mov.reindex(union,fill_value=0.)*w[row.tipo_dia_publicado]/w["Laborable"]
            ampliado["cobertura_horaria_completa"]=(receptor.cobertura_horaria_completa.reindex(union,fill_value=False)
                & fuente.cobertura_horaria_completa.reindex(union,fill_value=False))
            ampliado["matrix_index"]=dest
            receptor=ampliado
        result[dest]=receptor
    rows=[]
    for obs,g in result.items():
        g=g.reset_index();g["personas_lanzadera"]=g.personas_coche+g.personas_excursion+g.visitas_titsa
        g["dentro_ventana_fuente"]=g.hora_servicio.between(hora_inicio,hora_fin)
        rows.append(g)
    return pd.concat(rows,ignore_index=True)


def resumir_percentiles(diarios,horarios,*,percentil=.85):
    """Percentil lineal por acceso después del cupo, modos y cambios de fecha."""
    if (not 0<percentil<1 or diarios.duplicated(["matrix_index","punto"]).any()
        or not np.isfinite(diarios.demanda_lanzadera_dia).all() or diarios.demanda_lanzadera_dia.lt(0).any()
        or not np.isfinite(horarios.personas_lanzadera).all() or horarios.personas_lanzadera.lt(0).any()
        or horarios.duplicated(["matrix_index","punto","hora_servicio"]).any()):raise ValueError("Percentil, demanda o claves inválidos.")
    if any(set(g.matrix_index)!=set(range(57)) for _,g in diarios.groupby("punto")):raise ValueError("No están las 57 referencias por acceso.")
    d=diarios.groupby("punto",as_index=False).agg(personas_p85_total_dia=("demanda_lanzadera_dia",lambda x:x.quantile(percentil,interpolation="linear")),observaciones=("matrix_index","nunique"))
    completos=horarios.loc[horarios.cobertura_horaria_completa]
    h=completos.groupby(["punto","hora_servicio","dentro_ventana_fuente"],as_index=False).agg(personas_p85=("personas_lanzadera",lambda x:x.quantile(percentil,interpolation="linear")),observaciones_publicadas=("matrix_index","nunique"))
    d["suma_p85_horarios"]=d.punto.map(h.groupby("punto").personas_p85.sum())
    d["suma_p85_horarios_ventana"]=d.punto.map(h.loc[h.dentro_ventana_fuente].groupby("punto").personas_p85.sum())
    total=diarios.groupby("matrix_index").demanda_lanzadera_dia.sum()
    return d,h,{"p85_total_sistema":float(total.quantile(percentil,interpolation="linear")),"suma_p85_por_acceso":float(d.personas_p85_total_dia.sum()),"percentil":percentil,"interpolacion":"linear","matrices":57}
