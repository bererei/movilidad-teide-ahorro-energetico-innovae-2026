"""Proyección provisional de aforos y actividad de la oferta de transporte.

Trabaja con pasos de vehículos por sentido. Los cupos solo limitan demanda en
el mismo día: su exceso no predice cambio modal, cancelación ni ahorro.
"""
from __future__ import annotations
from movilidad_teide.validacion import numero_actividad as _numero
from movilidad_teide.demanda.oferta import calcular_oferta_acceso
from numbers import Integral, Real
import numpy as np
import pandas as pd


CRITERIOS_PROYECCION = {
    "total_anual_objetivo",
    "perfil_medio_por_mes_y_dia_semana",
}




def proyectar_trafico_diario(diarios, anio_objetivo, criterio, *, tasa_anual=0.0):
    """Aplicar un calendario futuro sin confundir crecimiento y efecto calendario.

    diarios: fecha, sentido y pasos_vehiculo; un año completo por sentido.
    Los perfiles medios por mes y día de semana son una hipótesis explícita.
    Con volumen anual constante se normalizan para conservar cada total anual.
    El otro criterio conserva esas medias y permite cambiar el total por calendario.
    """
    if isinstance(tasa_anual, (bool, np.bool_)) or not isinstance(tasa_anual, Real) or not np.isfinite(tasa_anual) or tasa_anual <= -1:
        raise ValueError("La tasa anual debe ser finita y mayor que -1.")
    if criterio not in CRITERIOS_PROYECCION:
        raise ValueError("Criterio de proyección no reconocido.")
    if isinstance(anio_objetivo, bool) or not isinstance(anio_objetivo, Integral) or not 1 <= anio_objetivo <= 9998:
        raise ValueError("El año objetivo debe ser un entero válido.")
    requeridas = {"fecha", "sentido", "pasos_vehiculo"}
    if not requeridas <= set(diarios.columns) or diarios.empty:
        raise ValueError("Faltan fecha, sentido o pasos de la base diaria.")
    base = diarios[["fecha", "sentido", "pasos_vehiculo"]].copy()
    base["fecha"] = pd.to_datetime(base["fecha"], errors="raise")
    if base["fecha"].isna().any() or base["sentido"].isna().any():
        raise ValueError("Hay fechas o sentidos ausentes.")
    if not base["fecha"].eq(base["fecha"].dt.normalize()).all():
        raise ValueError("La base debe contener fechas diarias sin hora.")
    if base["fecha"].dt.tz is not None:
        raise ValueError("No se convierte la referencia horaria de la fuente.")
    if base.duplicated(["fecha", "sentido"]).any():
        raise ValueError("Hay días repetidos por sentido.")
    if base["fecha"].dt.year.nunique() != 1:
        raise ValueError("La base debe corresponder a un único año.")
    anio_base = int(base["fecha"].dt.year.iloc[0])
    valores = pd.to_numeric(base["pasos_vehiculo"], errors="raise")
    if not np.isfinite(valores).all() or valores.lt(0).any():
        raise ValueError("Los pasos deben ser finitos y no negativos; revisar la fuente.")
    base["pasos_vehiculo"] = valores.astype(float)
    calendario_base = pd.date_range(f"{anio_base}-01-01", f"{anio_base}-12-31", freq="D")
    for sentido, bloque in base.groupby("sentido"):
        if not pd.DatetimeIndex(bloque["fecha"].sort_values()).equals(calendario_base):
            raise ValueError(f"Faltan días en {sentido}; no se imputan sin regla.")
    base["mes"] = base["fecha"].dt.month
    base["dia_semana"] = base["fecha"].dt.dayofweek
    perfiles = base.groupby(["sentido", "mes", "dia_semana"], as_index=False)["pasos_vehiculo"].mean()

    # Crear cada fecha del año futuro; 2028 tiene 366 días, no 365.
    futuro = pd.DataFrame({"fecha": pd.date_range(f"{anio_objetivo}-01-01", f"{anio_objetivo}-12-31", freq="D")})
    futuro["mes"] = futuro["fecha"].dt.month
    futuro["dia_semana"] = futuro["fecha"].dt.dayofweek
    futuro = futuro.merge(base[["sentido"]].drop_duplicates(), how="cross")
    futuro = futuro.merge(perfiles, on=["sentido", "mes", "dia_semana"], how="left", validate="many_to_one")
    if futuro["pasos_vehiculo"].isna().any():
        raise ValueError("Faltan perfiles mensuales para el calendario objetivo.")
    futuro["factor_normalizacion"] = 1.0
    if criterio == "total_anual_objetivo":
        total_base = base.groupby("sentido")["pasos_vehiculo"].sum()
        total_bruto = futuro.groupby("sentido")["pasos_vehiculo"].sum()
        # Una serie totalmente nula conserva cero sin producir una división 0/0.
        factores = total_base.div(total_bruto.where(total_bruto.gt(0))).fillna(1.0)
        futuro["factor_normalizacion"] = futuro["sentido"].map(factores)
        futuro["pasos_vehiculo"] *= futuro["factor_normalizacion"]
    # Anclar el crecimiento en el último año base, sin usar la ordenada del ajuste.
    factor_crecimiento = float((1 + tasa_anual) ** (int(anio_objetivo) - anio_base))
    if not np.isfinite(factor_crecimiento):
        raise ValueError("El factor de crecimiento no es finito.")
    futuro["pasos_vehiculo"] *= factor_crecimiento
    futuro["tasa_anual"] = float(tasa_anual)
    futuro["factor_crecimiento"] = factor_crecimiento
    futuro["criterio"] = criterio
    futuro["anio_base"] = anio_base
    futuro["anio_objetivo"] = int(anio_objetivo)
    return futuro.sort_values(["fecha", "sentido"]).reset_index(drop=True)


def evaluar_cupos_diarios(pasos_entrada, cupos):
    """Acotar admisión en el mismo día, sin inferir vehículos retirados.

    No se incluyen excepciones, incumplimiento, inducción ni reasignación a otros
    días. El cupo debe aplicarse al mismo colectivo que la demanda de entrada.
    """
    valores = np.asarray(pasos_entrada, dtype=float)
    if valores.ndim != 1 or valores.size == 0 or not np.isfinite(valores).all() or (valores < 0).any():
        raise ValueError("La demanda diaria debe ser una serie finita, no negativa y no vacía.")
    umbrales = [_numero(c, "cupo") for c in cupos]
    if not umbrales or len(set(umbrales)) != len(umbrales):
        raise ValueError("Los cupos deben ser no vacíos y no repetidos.")
    if any(c != int(c) for c in umbrales):
        raise ValueError("Un cupo de coches debe ser entero.")
    filas = []
    for cupo in sorted(umbrales):
        # Contar exceso en el día, sin interpretarlo como transferencia a guagua.
        admitidos = np.minimum(valores, cupo).sum()
        filas.append({
            "cupo_coches_dia": int(cupo),
            "dias_evaluados": int(valores.size),
            "pasos_entrada_referencia": float(valores.sum()),
            "pasos_que_caben_mismo_dia": float(admitidos),
            "pasos_que_exceden_cupo_mismo_dia": float(np.maximum(valores - cupo, 0).sum()),
            "dias_con_exceso": int((valores > cupo).sum()),
        })
    return pd.DataFrame(filas)




def comparar_tendencias_aforos(anuales, anios_excluidos=(2020, 2021)):
    """Comparar crecimiento por acceso sin imputar el año 2024 ausente.

    Central: log(media diaria) frente al año real, excluyendo 2020/2021 y años
    con huecos, ausencias, negativos o totales no positivos. La exclusión
    temporal es una decisión de modelización, no una identificación causal
    de COVID. Comparo con CAGR 2019–2025 y 2023–2025, si sus extremos son válidos.
    Estimo ambos sentidos y su suma; esta última da una tasa común por acceso.
    """
    columnas = ["anio", "punto", "sentido", "tipo_vehiculo", "total_valores_fuente", "horas_esperadas", "horas_ausentes", "valores_negativos", "valores_ausentes"]
    if not set(columnas) <= set(anuales.columns):
        raise ValueError("Faltan columnas de calidad en el resumen anual.")
    datos = anuales.loc[anuales["tipo_vehiculo"].eq("coche"), columnas].copy()
    if datos.empty or datos.duplicated(["anio", "punto", "sentido"]).any():
        raise ValueError("El resumen de coches está vacío o tiene series repetidas.")
    if not set(datos["sentido"]) <= {"entrada", "salida"}:
        raise ValueError("Sentidos de aforo no reconocidos.")
    grupos = datos.groupby(["anio", "punto"])
    if not grupos["sentido"].nunique().eq(2).all():
        raise ValueError("Falta un sentido en algún acceso/año.")
    conjuntos = []
    for (anio, punto), bloque in grupos:
        if bloque["horas_esperadas"].nunique() != 1:
            raise ValueError("Los sentidos no comparten calendario esperado.")
        conjuntos.append({
            "anio": anio, "punto": punto, "sentido": "ambos_sentidos", "tipo_vehiculo": "coche",
            "total_valores_fuente": bloque["total_valores_fuente"].sum(min_count=2),
            "horas_esperadas": bloque["horas_esperadas"].iloc[0],
            "horas_ausentes": bloque["horas_ausentes"].sum(),
            "valores_negativos": bloque["valores_negativos"].sum(),
            "valores_ausentes": bloque["valores_ausentes"].sum(),
        })
    datos = pd.concat([datos, pd.DataFrame(conjuntos)], ignore_index=True)
    filas = []
    for (punto, sentido), bloque in datos.groupby(["punto", "sentido"], sort=True):
        bloque = bloque.sort_values("anio").copy()
        bloque["media_diaria"] = bloque["total_valores_fuente"].div(bloque["horas_esperadas"] / 24)
        calidad = bloque[["horas_ausentes", "valores_negativos", "valores_ausentes"]].eq(0).all(axis=1)
        valido = calidad & np.isfinite(bloque["media_diaria"]) & bloque["media_diaria"].gt(0)
        fuera_periodo = bloque["anio"].isin(anios_excluidos)
        ajustes = [("ajuste_log_lineal_con_exclusiones", bloque.loc[valido & ~fuera_periodo])]
        for inicio in [2019, 2023]:
            extremos = bloque.loc[valido & bloque["anio"].isin([inicio, 2025])]
            ajustes.append((f"cagr_{inicio}_2025", extremos if set(extremos["anio"]) == {inicio, 2025} else extremos.iloc[:0]))
        for metodo, muestra in ajustes:
            tasa = None
            if len(muestra) >= 2:
                x = muestra["anio"].to_numpy(dtype=float)
                y = np.log(muestra["media_diaria"].to_numpy(dtype=float))
                if metodo.startswith("ajuste_"):
                    pendiente = np.polyfit(x - x.min(), y, 1)[0]
                else:
                    # 2023–2025 son dos años transcurridos, aunque no exista 2024.
                    pendiente = (y[-1] - y[0]) / (x[-1] - x[0])
                tasa = float(np.expm1(pendiente))
            filas.append({
                "punto": punto, "sentido": sentido, "metodo": metodo,
                "anios_utilizados": ",".join(str(int(v)) for v in muestra["anio"]),
                "anios_excluidos_periodo": ",".join(str(int(v)) for v in bloque.loc[fuera_periodo, "anio"]),
                "anios_excluidos_calidad": ",".join(str(int(v)) for v in bloque.loc[~valido, "anio"]),
                "numero_anios": len(muestra), "tasa_anual": tasa,
                "tasa_anual_pct": None if tasa is None else 100 * tasa,
                "estado": "comparacion_provisional_no_intervalo_estadistico" if tasa is not None else "datos_insuficientes",
            })
    return pd.DataFrame(filas)


def repartir_cupo_global(demanda, cupo_diario, *, pesos=None):
    """Reparto proporcional TEÓRICO del cupo global entre accesos por fecha.

    Las cuotas pueden ser fraccionarias como valores esperados, no reservas
    operativas. El exceso no se convierte en pasajeros ni coches retirados.
    demanda contiene fecha, punto y pasos_vehiculo de entrada, sin salidas.
    """
    cupo = _numero(cupo_diario, "cupo_diario")
    if cupo != int(cupo):
        raise ValueError("El cupo global de coches debe ser entero.")
    requeridas = ["fecha", "punto", "pasos_vehiculo"]
    if not set(requeridas) <= set(demanda.columns) or demanda.empty:
        raise ValueError("Falta demanda por fecha y punto.")
    salida = demanda[requeridas].copy()
    if salida[requeridas].isna().any().any() or salida.duplicated(["fecha", "punto"]).any():
        raise ValueError("Hay accesos/fechas ausentes o repetidos.")
    if "sentido" in demanda and not demanda["sentido"].eq("entrada").all():
        raise ValueError("El cupo de subida solo se aplica a las entradas.")
    valores = pd.to_numeric(salida["pasos_vehiculo"], errors="raise")
    if not np.isfinite(valores).all() or valores.lt(0).any():
        raise ValueError("La demanda de entrada debe ser finita y no negativa.")
    if not salida.groupby("fecha")["punto"].nunique().eq(salida["punto"].nunique()).all():
        raise ValueError("Falta algún acceso en una fecha; no se redistribuye silenciosamente.")
    salida["pasos_vehiculo"] = valores.astype(float)
    total = salida.groupby("fecha")["pasos_vehiculo"].transform("sum")
    factor = np.minimum(1.0, cupo / total.where(total.gt(0))).fillna(0.0)
    salida["cupo_global_coches_dia"] = int(cupo)
    salida["entrada_total_referencia_dia"] = total
    if pesos is None:
        salida["cuota_teorica_coches_dia"] = salida["pasos_vehiculo"] * factor
    else:
        # Reparto fijo explícito: la cuota no utilizada de un acceso no se reasigna.
        if set(pesos) != set(salida["punto"]):
            raise ValueError("Los porcentajes deben cubrir exactamente los accesos presentes.")
        valores_peso = {p: _numero(v, "porcentaje de " + str(p)) for p, v in pesos.items()}
        if any(v > 1 for v in valores_peso.values()) or not np.isclose(sum(valores_peso.values()), 1, rtol=0, atol=1e-9):
            raise ValueError("Los porcentajes manuales deben sumar 100 %.")
        salida["cuota_teorica_coches_dia"] = np.minimum(salida["pasos_vehiculo"], cupo * salida["punto"].map(valores_peso))
    salida["exceso_sobre_cuota_teorica"] = salida["pasos_vehiculo"] - salida["cuota_teorica_coches_dia"]
    return salida.sort_values(["fecha", "punto"]).reset_index(drop=True)


def anualizar_referencias_visor(perfiles, indices, captacion, *, anio_base, anio_calendario, criterio, hora_inicio=0, hora_fin=23):
    """Expandir referencias diarias antes del p85 bajo una hipótesis explícita.

    Media de los meses disponibles por tipo de día. Lunes-viernes aproxima la
    etiqueta laborable sin reclasificar festivos. No aplica crecimiento, modos,
    ocupaciones o asignación territorial de la media histórica de 57 matrices.
    """
    from calendar import monthrange
    from movilidad_teide.demanda.asignacion_tipos import SEGMENTOS
    regla='Media de meses 2025 por tipo de día'
    if criterio not in {regla,'Media de meses de referencia por tipo de día','Sin anualizar',None}:
        raise ValueError('Criterio de anualización desconocido.')
    for y in [anio_base,anio_calendario]:
        if isinstance(y,bool) or not isinstance(y,Integral) or not 1<=y<=9998:
            raise ValueError('Los años deben ser enteros válidos.')
    if anio_base!=2025 and criterio!='Media de meses de referencia por tipo de día':
        raise ValueError('La referencia elegida conserva las matrices identificadas de 2025.')
    meses={'Marzo':3,'Julio':7,'Octubre':10}
    tipos={'Laborable','Sábado','Domingo'}
    ind=indices.loc[indices.anio.eq(anio_base)].copy()
    if (len(ind)!=9 or ind.matrix_index.duplicated().any() or
        ind.duplicated(['mes_publicado','tipo_dia_publicado']).any() or
        set(zip(ind.mes_publicado,ind.tipo_dia_publicado))!={(m,t) for m in meses for t in tipos}):
        raise ValueError('Se requieren las nueve referencias únicas de marzo, julio y octubre de 2025.')
    if set(captacion)!=set(SEGMENTOS):raise ValueError('La captación debe identificar los cuatro colectivos.')
    for val in captacion.values():
        if _numero(val,'captación')>1:raise ValueError('La captación debe estar entre cero y uno.')
    if any(isinstance(v,bool) or not isinstance(v,Integral) or not 0<=v<=23 for v in [hora_inicio,hora_fin]) or hora_inicio>hora_fin:
        raise ValueError('Ventana horaria inválida.')
    p=perfiles.loc[perfiles.matrix_index.isin(ind.matrix_index)].copy()
    key=['matrix_index','access_corridor','direccion','hora_servicio']
    if p.empty or p.duplicated(key).any() or set(p.matrix_index)!=set(ind.matrix_index):
        raise ValueError('Faltan matrices de perfiles o hay horas duplicadas.')
    if set(p.direccion)!={'subida','bajada'} or p.access_corridor.isna().any():
        raise ValueError('Los perfiles deben conservar ambos sentidos y corredores identificados.')
    a=p[list(SEGMENTOS)].to_numpy(dtype=float)
    if not np.isfinite(a).all() or (a<0).any():raise ValueError('Demanda ausente, negativa o no finita.')
    corredores=set(p.access_corridor)
    if not p.groupby(['matrix_index','access_corridor']).direccion.nunique().eq(2).all():
        raise ValueError('Falta un sentido en una matriz/corredor.')
    if len(p[['matrix_index','access_corridor','direccion']].drop_duplicates())!=9*len(corredores)*2:
        raise ValueError('Falta un corredor o sentido en alguna matriz.')
    daily=p.groupby(['matrix_index','access_corridor','direccion'],as_index=False)[list(SEGMENTOS)].sum()
    daily=daily.merge(ind,on='matrix_index',validate='many_to_one').melt(
        id_vars=['matrix_index','access_corridor','direccion','mes_publicado','tipo_dia_publicado'],
        value_vars=list(SEGMENTOS),var_name='colectivo',value_name='viajes_persona_dia_referencia')
    # Conservar demanda de todo el día y separar la captación dentro de la ventana.
    dentro=p.copy()
    dentro[list(SEGMENTOS)]=p[list(SEGMENTOS)].mul(p.hora_servicio.between(hora_inicio,hora_fin),axis=0)
    cd=dentro.groupby(['matrix_index','access_corridor','direccion'],as_index=False)[list(SEGMENTOS)].sum().melt(
        id_vars=['matrix_index','access_corridor','direccion'],value_vars=list(SEGMENTOS),
        var_name='colectivo',value_name='viajes_persona_ventana')
    daily=daily.merge(cd,on=['matrix_index','access_corridor','direccion','colectivo'],validate='one_to_one')
    daily['coeficiente_captacion']=daily.colectivo.map(captacion)
    daily['viajes_persona_captables_dia_referencia']=daily.viajes_persona_ventana*daily.coeficiente_captacion
    daily['viajes_persona_captables_fuera_ventana']=daily.viajes_persona_dia_referencia*daily.coeficiente_captacion-daily.viajes_persona_captables_dia_referencia
    means=daily.groupby(['access_corridor','direccion','colectivo','tipo_dia_publicado'],as_index=False).agg(
        viajes_persona_dia_referencia=('viajes_persona_dia_referencia','mean'),
        viajes_persona_captables_dia_referencia=('viajes_persona_captables_dia_referencia','mean'),
        viajes_persona_captables_fuera_ventana=('viajes_persona_captables_fuera_ventana','mean'),
        numero_meses=('mes_publicado','nunique'))
    if not means.numero_meses.eq(3).all():raise ValueError('No promediar meses incompletos por colectivo/corredor/sentido.')
    fechas=pd.date_range(f'{anio_calendario}-01-01',f'{anio_calendario}-12-31')
    cal=pd.DataFrame({'fecha':fechas});cal['mes']=cal.fecha.dt.month
    cal['tipo_dia_publicado']=np.select([cal.fecha.dt.dayofweek.eq(5),cal.fecha.dt.dayofweek.eq(6)],['Sábado','Domingo'],default='Laborable')
    calendar=cal.groupby(['mes','tipo_dia_publicado']).size().rename('dias_calendario').reset_index()
    calendar['mes_con_referencia_2025']=calendar.mes.isin(meses.values())
    calendar['regla_calendario']='Laborable aproximado por lunes-viernes; festivos sin reclasificar'
    count=calendar.groupby('tipo_dia_publicado').dias_calendario.sum()
    means['dias_calendario']=means.tipo_dia_publicado.map(count)
    means['anio_perfiles']=anio_base;means['anio_calendario']=anio_calendario
    active=criterio in {regla,'Media de meses de referencia por tipo de día'}
    for original,out in [('viajes_persona_dia_referencia','viajes_persona_anuales_referencia'),
                         ('viajes_persona_captables_dia_referencia','viajes_persona_captables_anuales_referencia'),
                         ('viajes_persona_captables_fuera_ventana','viajes_persona_captables_anuales_fuera_ventana')]:
        means[out]=means[original]*means.dias_calendario if active else np.nan
    annual=means.groupby(['access_corridor','direccion','colectivo','anio_perfiles','anio_calendario'],as_index=False)[
        ['viajes_persona_anuales_referencia','viajes_persona_captables_anuales_referencia','viajes_persona_captables_anuales_fuera_ventana']].sum(min_count=1)
    annual['criterio']=criterio or 'Pendiente'
    annual['estado']=f'Aproximación con perfiles {anio_base}; solo cambia calendario, sin crecimiento de personas' if active else 'Anualización pendiente'
    annual['coches_sustituidos_anuales']=np.nan
    return {'referencias_diarias_visor_2025':daily,'medias_por_tipo_dia':means,
            'calendario_anualizacion':calendar,'demanda_anual_referencia_visor':annual}


def comparar_tendencias_personas_visor(perfiles, indices, captacion):
    """Comparar años con los mismos nueve tipos de referencia y calendario fijo.

    No traslada tasas de coches a personas. Los cambios por colectivo se muestran
    como diagnóstico; la hipótesis de proyección utiliza una tasa común del total.
    """
    from movilidad_teide.demanda.asignacion_tipos import SEGMENTOS
    meses={'Marzo','Julio','Octubre'};tipos={'Laborable','Sábado','Domingo'}
    if indices.matrix_index.duplicated().any():raise ValueError('Índices de matriz repetidos.')
    if 'formato_publicado' not in indices or indices.formato_publicado.isna().any():
        raise ValueError('La tendencia requiere el formato publicado de cada matriz.')
    regulares=indices.loc[indices.mes_publicado.isin(meses)&indices.tipo_dia_publicado.isin(tipos)].copy()
    cobertura=[];historico=[]
    for year,b in indices.groupby('anio'):
        seleccion=regulares.loc[regulares.anio.eq(year)]
        completo=(len(seleccion)==9 and not seleccion.duplicated(['mes_publicado','tipo_dia_publicado']).any())
        elegido=year in [2022,2023,2024,2025]
        cobertura.append({'anio':int(year),'matrices_publicadas':len(b),'matrices_regulares_comparables':len(seleccion),
            'cobertura_nueve_referencias':bool(completo),'utilizado_en_ajuste':elegido,
            'formatos_regulares':', '.join(sorted(set(seleccion.formato_publicado))),
            'uso':'Diagnóstico histórico; aplicación condicionada a formato común',
            'tratamiento':'Base comparable' if elegido and completo else 'Fuera de 2022–2025; cobertura parcial o periodo distinto'})
        if elegido:
            if not completo:raise ValueError('No estimar tendencia con un año de cobertura distinta.')
            t=anualizar_referencias_visor(perfiles,seleccion,captacion,anio_base=int(year),anio_calendario=2025,
                criterio='Media de meses de referencia por tipo de día')['demanda_anual_referencia_visor']
            t=t[['access_corridor','direccion','colectivo','anio_perfiles','viajes_persona_anuales_referencia']].rename(
                columns={'viajes_persona_anuales_referencia':'viajes_persona_equivalentes_calendario_fijo'})
            t['formatos_del_ano']=', '.join(sorted(set(seleccion.formato_publicado)))
            historico.append(t)
    if {int(t.anio_perfiles.iloc[0]) for t in historico}!={2022,2023,2024,2025}:
        raise ValueError('Falta algún año de 2022 a 2025.')
    hist=pd.concat(historico,ignore_index=True)
    cohort=hist.groupby(['anio_perfiles','colectivo'],as_index=False).viajes_persona_equivalentes_calendario_fijo.sum()
    total=hist.groupby('anio_perfiles',as_index=False).viajes_persona_equivalentes_calendario_fijo.sum();total['colectivo']='total_sistema'
    tablas=pd.concat([cohort,total],ignore_index=True);filas=[]
    for group,b in tablas.groupby('colectivo'):
        b=b.sort_values('anio_perfiles');x=b.anio_perfiles.to_numpy(dtype=float);y=b.viajes_persona_equivalentes_calendario_fijo.to_numpy(dtype=float)
        for metodo in ['ajuste_2022_2025','cagr_2022_2025','cagr_2023_2025','cagr_2024_2025_mismo_formato']:
            mask=x>=2024 if metodo=='cagr_2024_2025_mismo_formato' else x>=2023 if metodo=='cagr_2023_2025' else np.ones(len(x),dtype=bool)
            xx=x[mask];yy=y[mask]
            if metodo.startswith('cagr'):xx=xx[[0,-1]];yy=yy[[0,-1]]
            valido=np.isfinite(yy).all() and (yy>0).all()
            tasa=np.nan
            if valido:
                pendiente=np.polyfit(xx-xx.min(),np.log(yy),1)[0] if metodo.startswith('ajuste') else (np.log(yy[-1])-np.log(yy[0]))/(xx[-1]-xx[0])
                tasa=float(np.expm1(pendiente))
            formatos=set(regulares.loc[regulares.anio.isin(xx),'formato_publicado'])
            comparable=len(formatos)==1
            filas.append({'colectivo':group,'metodo':metodo,
                'formatos_utilizados':', '.join(sorted(formatos)),'aplicable_mismo_formato':comparable,'anios_utilizados':','.join(str(int(v)) for v in xx),
                'tasa_anual':tasa,'tasa_anual_pct':100*tasa,'estado':'Comparación provisional, no intervalo estadístico' if valido else 'Serie nula/no positiva: tasa ausente',
                'aplicacion':('Tasa común candidata del mismo formato' if comparable else 'Solo diagnóstico: mezcla formatos') if group=='total_sistema' else 'Diagnóstico; no aplicar automáticamente al colectivo'})
    return {'cobertura_matrices_tendencia_personas':pd.DataFrame(cobertura),
            'personas_historicas_comparables':hist,'tendencias_personas_visor':pd.DataFrame(filas)}


def proyectar_personas_desde_referencia(referencia, tendencias, metodo, anio_objetivo):
    """Aplicar una tasa común anclada en 2025 sobre el calendario ya expandido.

    Conserva los desajustes de subida/bajada. No implica cambio modal, capacidad,
    coches retirados o asignación territorial de los perfiles históricos.
    """
    metodos={'Ajuste comparable del Visor 2022–2025':'ajuste_2022_2025',
             'Tasa compuesta del Visor 2022–2025':'cagr_2022_2025',
             'Tasa compuesta del Visor 2023–2025':'cagr_2023_2025',
             'Tasa comparable del Visor 2024–2025':'cagr_2024_2025_mismo_formato'}
    if metodo not in {*metodos,'Sin crecimiento',None}:raise ValueError('Método de crecimiento de personas desconocido.')
    if isinstance(anio_objetivo,bool) or not isinstance(anio_objetivo,Integral) or anio_objetivo<2025:
        raise ValueError('Año objetivo inválido para esta referencia.')
    r=referencia.loc[referencia.anio_calendario.eq(anio_objetivo)].copy()
    if r.empty or not r.anio_perfiles.eq(2025).all() or r.duplicated(['access_corridor','direccion','colectivo']).any():
        raise ValueError('Falta referencia única de 2025 expandida al calendario objetivo.')
    tasa=np.nan
    if metodo=='Sin crecimiento':tasa=0.
    elif metodo is not None:
        t=tendencias.loc[tendencias.colectivo.eq('total_sistema')&tendencias.metodo.eq(metodos[metodo])]
        if len(t)!=1 or not np.isfinite(t.tasa_anual.iloc[0]) or t.tasa_anual.iloc[0]<=-1:
            raise ValueError('La tasa común debe estar disponible, ser única y mayor que −1.')
        if 'aplicable_mismo_formato' not in t or not t.aplicable_mismo_formato.all():
            raise ValueError('El método mezcla formatos o carece de control de versión; elegir referencia comparable.')
        tasa=float(t.tasa_anual.iloc[0])
    factor=(1+tasa)**(anio_objetivo-2025) if np.isfinite(tasa) else np.nan
    if np.isfinite(tasa) and not np.isfinite(factor):raise ValueError('Factor de crecimiento no finito.')
    r['metodo_crecimiento_personas']=metodo or 'Pendiente';r['tasa_anual_personas']=tasa;r['factor_crecimiento_personas']=factor
    for original,nuevo in [('viajes_persona_anuales_referencia','viajes_persona_proyectados'),
                           ('viajes_persona_captables_anuales_referencia','viajes_persona_captables_proyectados'),
                           ('viajes_persona_captables_anuales_fuera_ventana','viajes_persona_captables_proyectados_fuera_ventana')]:
        if original not in r:raise ValueError('Falta una pieza de referencia anual.')
        conocidos=r[original].dropna()
        if not np.isfinite(conocidos).all() or conocidos.lt(0).any():raise ValueError('Referencia anual no física.')
        r[nuevo]=r[original]*factor
    r['estado_proyeccion']='Proyección provisional con tasa común; composición 2025 y limitaciones de H080' if np.isfinite(factor) else 'Crecimiento de personas pendiente'
    r['unidad']='viajes-persona/año; no personas únicas o vehículos'
    r['fuente']='F035 — Visor Teide, referencias regulares con control de formato; D130/H082'
    return r.reset_index(drop=True)


def desglosar_captacion_horaria_visor(perfiles, indices, captacion, *, anio_base, hora_inicio, hora_fin):
    """Explicar qué bloques del perfil quedan dentro/fuera de la ventana elegida.

    hora_servicio no acredita por sí sola llegadas al Parque o salidas de cabecera.
    Se conserva ese límite temporal; no se inventan horarios ni atención efectiva.
    """
    from movilidad_teide.demanda.asignacion_tipos import SEGMENTOS
    # Reutilizar la validación de las nueve matrices y la captación física.
    anual=anualizar_referencias_visor(perfiles,indices,captacion,anio_base=anio_base,anio_calendario=anio_base,
        criterio='Media de meses 2025 por tipo de día',hora_inicio=hora_inicio,hora_fin=hora_fin)
    ids=anual['referencias_diarias_visor_2025'].matrix_index.unique()
    i=indices.loc[indices.matrix_index.isin(ids)]
    p=perfiles.loc[perfiles.matrix_index.isin(ids)].merge(i[['matrix_index','mes_publicado','tipo_dia_publicado']],on='matrix_index',validate='many_to_one')
    k=['matrix_index','mes_publicado','tipo_dia_publicado','direccion','hora_servicio']
    a=p.groupby(k,as_index=False)[list(SEGMENTOS)].sum()
    # Una franja siempre ausente no se interpreta como cero. Rechazar cobertura irregular.
    for sentido,grupo in a.groupby('direccion'):
        conjuntos=grupo.groupby('matrix_index').hora_servicio.agg(lambda x:tuple(sorted(set(x))))
        if conjuntos.nunique()!=1:raise ValueError('No promediar horas con distinta cobertura entre matrices.')
    a=a.melt(id_vars=k,value_vars=list(SEGMENTOS),var_name='colectivo',value_name='viajes_persona_dia')
    h=a.groupby(['tipo_dia_publicado','direccion','hora_servicio','colectivo'],as_index=False).viajes_persona_dia.mean()
    days=anual['calendario_anualizacion'].groupby('tipo_dia_publicado').dias_calendario.sum()
    h['viajes_persona_anuales']=h.viajes_persona_dia*h.tipo_dia_publicado.map(days)
    h['captables_anuales']=h.viajes_persona_anuales*h.colectivo.map(captacion)
    h=h.groupby(['direccion','hora_servicio','colectivo'],as_index=False)[['viajes_persona_anuales','captables_anuales']].sum(min_count=1)
    rejilla=pd.MultiIndex.from_product([['subida','bajada'],range(24),list(SEGMENTOS)],
        names=['direccion','hora_servicio','colectivo']).to_frame(index=False)
    h=rejilla.merge(h,on=['direccion','hora_servicio','colectivo'],how='left',validate='one_to_one')
    h['valor_publicado_disponible']=h.viajes_persona_anuales.notna()
    h['estado_valor']=np.where(h.valor_publicado_disponible,'Suma de registros publicados',
        'Sin registros publicados en esta hora y sentido; no imputado como cero')
    h['en_ventana_diseno']=h.hora_servicio.between(hora_inicio,hora_fin)
    h['bloque_ventana']=np.select([h.hora_servicio.lt(hora_inicio),h.hora_servicio.gt(hora_fin)],
        [f'Bloques anteriores a {hora_inicio}',f'Bloques posteriores a {hora_fin}'],default=f'Bloques incluidos de {hora_inicio} a {hora_fin}')
    h['unidad']='viajes-persona/año aproximados con perfiles y calendario 2025'
    h['limite_temporal']='hora_servicio del perfil Visor; no confirma salida de cabecera o llegada al Parque (P029)'
    return h


def contrastar_escala_personas_aforos(personas, coches, corredores, *, ocupacion_referencia=None):
    """Contrastar escalas sin adoptar ocupación, calibrar telefonía o retirar coches.

    El cociente entre fuentes no es una ocupación observada. La prueba con una
    ocupación histórica solo pregunta qué ocurriría SI ambos ámbitos coincidieran.
    Las ausencias y los saldos negativos permanecen visibles.
    """
    pkeys=['anio','access_corridor','direccion'];ckeys=['anio','punto','direccion']
    if (not {*pkeys,'viajes_persona_anuales'}<=set(personas) or
            not {*ckeys,'pasos_coche'}<=set(coches) or personas.empty or coches.empty):
        raise ValueError('Faltan personas o pasos de coche por año, corredor y sentido.')
    p=personas[[*pkeys,'viajes_persona_anuales']].copy();c=coches[[*ckeys,'pasos_coche']].copy()
    if p[pkeys].isna().any().any() or c[ckeys].isna().any().any() or p.duplicated(pkeys).any() or c.duplicated(ckeys).any():
        raise ValueError('Claves ausentes o repetidas en el contraste de fuentes.')
    mapa={f['corredor']:f['aforo'] for f in corredores}
    nombres={f['corredor']:f['nombre'] for f in corredores}
    if len(mapa)!=len(corredores) or len(set(mapa.values()))!=len(mapa) or not mapa:
        raise ValueError('La correspondencia nominal de corredores y aforos debe ser única.')
    if set(p.access_corridor)!=set(mapa) or set(c.punto)!=set(mapa.values()) or set(p.anio)!=set(c.anio):
        raise ValueError('Las fuentes deben conservar todos los años y accesos previstos.')
    for t,k in [(p,pkeys),(c,ckeys)]:
        if set(t.direccion)!={'subida','bajada'}:
            raise ValueError('Conservar subida y bajada separadas.')
        if len(t)!=len(set(t.anio))*len(mapa)*2:
            raise ValueError('Falta un acceso o sentido en algún año.')
        col='viajes_persona_anuales' if t is p else 'pasos_coche'
        t[col]=pd.to_numeric(t[col],errors='raise').astype(float)
        known=t[col].dropna()
        if not np.isfinite(known).all() or known.lt(0).any():
            raise ValueError('No usar valores negativos o no finitos como actividad comparable.')
    ocupacion=np.nan if ocupacion_referencia is None else _numero(ocupacion_referencia,'ocupación de referencia',positivo=True)
    if np.isfinite(ocupacion) and ocupacion<1:raise ValueError('La referencia de ocupación no puede ser menor que uno.')
    p['punto']=p.access_corridor.map(mapa)
    r=p.merge(c,on=ckeys,validate='one_to_one');r['nombre_ambito']=r.access_corridor.map(nombres)
    r['tipo_ambito']='Correspondencia nominal de corredor fuente y aforo; no recorrido validado'
    # El total del Parque requiere los cuatro accesos, sin convertir cada sentido en visitas.
    total=r.groupby(['anio','direccion'],as_index=False)[['viajes_persona_anuales','pasos_coche']].sum(min_count=len(mapa))
    total['access_corridor']='total_parque';total['punto']='total_parque';total['nombre_ambito']='Conjunto de los accesos';total['tipo_ambito']='Suma de accesos, sentidos separados'
    r=pd.concat([r,total],ignore_index=True)
    r['cociente_personas_por_paso_no_ocupacion']=r.viajes_persona_anuales/r.pasos_coche.where(r.pasos_coche.gt(0))
    r['ocupacion_referencia_para_prueba']=ocupacion
    r['personas_en_coches_si_coincidieran_ambitos']=r.pasos_coche*ocupacion
    r['saldo_personas_menos_prueba_coches']=r.viajes_persona_anuales-r.personas_en_coches_si_coincidieran_ambitos
    r['relacion_entre_escalas_no_factor_de_calibracion']=r.viajes_persona_anuales/r.personas_en_coches_si_coincidieran_ambitos.where(r.personas_en_coches_si_coincidieran_ambitos.gt(0))
    r['prueba_mismo_ambito_no_descartada']=pd.array([pd.NA]*len(r),dtype='boolean')
    known=r.saldo_personas_menos_prueba_coches.notna()
    r.loc[known,'prueba_mismo_ambito_no_descartada']=r.loc[known,'saldo_personas_menos_prueba_coches'].ge(0)
    r['comparabilidad_validada']=False;r['coches_sustituidos_anuales']=np.nan
    r['unidad']='Viajes-persona/año frente a pasos de coches/año; cociente entre fuentes no conciliadas'
    r['fuente']='F035 — Visor Teide; F038 — aforos; referencia histórica de ocupación F042'
    r['limite']='Prueba condicional, no ocupación medida o factor de expansión. Un saldo negativo impide asumir el mismo ámbito con esa referencia; uno positivo no valida comparabilidad.'
    return r


def adjuntar_formato_publicado(indices, catalogo):
    """Vincular la versión publicada por nombre de matriz, sin confundir sus IDs."""
    cols={'Matriz','Año','Versión'}
    if not cols<=set(catalogo) or catalogo.Matriz.duplicated().any() or indices.matriz_publicada.duplicated().any():
        raise ValueError('Catálogo o correspondencia sin nombres de matriz únicos.')
    version=catalogo[['Matriz','Año','Versión']].rename(columns={'Matriz':'matriz_publicada','Año':'anio_catalogo','Versión':'formato_publicado'})
    out=indices.merge(version,on='matriz_publicada',how='left',validate='one_to_one')
    if out.formato_publicado.isna().any() or not out.anio.eq(out.anio_catalogo).all():
        raise ValueError('Falta versión o el año del catálogo no coincide.')
    if not out.formato_publicado.isin(['Formato 2021','Formato 2025']).all():
        raise ValueError('Formato publicado desconocido; revisar su ámbito antes de comparar.')
    return out.drop(columns='anio_catalogo')


def contrastar_ambito_od_visor(consultas, relaciones, perfiles, indices):
    """Verificar entrada/salida externa e internos con las relaciones conservadas.

    No interpreta coincidencia numérica como visitantes únicos, expansión validada
    o equivalencia con aforos. Los IDs API y del simulador permanecen separados.
    """
    meses={'Marzo':3,'Julio':7,'Octubre':10};tipos={'Laborable':'laborable','Sábado':'sabado','Domingo':'domingo'}
    base=indices.loc[indices.anio.eq(2025)].copy()
    if len(base)!=9 or not base.formato_publicado.eq('Formato 2025').all():
        raise ValueError('El contraste usa nueve matrices 2025 del mismo formato.')
    q=consultas.loc[consultas.anio.eq(2025)&consultas.modo.eq('todos_modos')].copy()
    keys=['anio','mes','tipo_dia','sentido']
    if len(q)!=18 or q.duplicated(keys).any():raise ValueError('Faltan consultas únicas en ambos sentidos de las nueve matrices.')
    rel=relaciones.loc[relaciones.modo.eq('todos_modos')&relaciones.anio.eq(2025)].copy()
    if rel.duplicated(['id_matriz','sentido','origen','destino']).any():raise ValueError('Relaciones OD repetidas.')
    vals=pd.to_numeric(rel.viajes,errors='raise')
    if not np.isfinite(vals).all() or vals.lt(0).any():raise ValueError('Viajes OD no físicos.')
    totals=perfiles.loc[perfiles.matrix_index.isin(base.matrix_index)].copy()
    from movilidad_teide.demanda.asignacion_tipos import SEGMENTOS
    totals['viajes_visor']=totals[list(SEGMENTOS)].sum(axis=1)
    totals=totals.groupby(['matrix_index','direccion'],as_index=False).viajes_visor.sum()
    totals=totals.merge(base,on='matrix_index',validate='many_to_one')
    totals['mes']=totals.mes_publicado.map(meses);totals['tipo_dia']=totals.tipo_dia_publicado.map(tipos)
    totals['sentido']=totals.direccion.map({'subida':'hacia_teide','bajada':'desde_teide'})
    if len(totals)!=18 or totals[keys].isna().any().any() or totals.duplicated(keys).any():
        raise ValueError('No hay cruce temporal único del Visor con las consultas OD.')
    out=q.merge(totals[keys+['matrix_index','formato_publicado','viajes_visor']],on=keys,how='outer',validate='one_to_one',indicator=True)
    if not out['_merge'].eq('both').all():raise ValueError('Las fuentes no conservan las mismas matrices y sentidos.')
    out=out.drop(columns='_merge');rows=[]
    for row in out.itertuples():
        b=rel.loc[rel.id_matriz.eq(row.id_matriz)&rel.sentido.eq(row.sentido)]
        if b.empty:raise ValueError('Consulta sin relaciones OD conservadas.')
        target='destino' if row.sentido=='hacia_teide' else 'origen'
        if not b[target].isin([187,222]).all():raise ValueError('La consulta contiene un extremo fuera de las zonas destino/origen seleccionadas.')
        interno=b.origen.isin([187,222])&b.destino.isin([187,222])
        inside=b.loc[interno,'viajes'].sum();outside=b.loc[~interno,'viajes'].sum();total=inside+outside
        if not np.allclose([total,inside,outside],[row.viajes_total,row.viajes_internos,row.viajes_externos],atol=1e-8,rtol=0):
            raise ValueError('La consulta no conserva la separación interna/externa de sus relaciones.')
        rows.append((inside,outside,total))
    out[['internos_verificados','externos_verificados','total_verificado']]=pd.DataFrame(rows,index=out.index)
    out['diferencia_visor_menos_od_externo']=out.viajes_visor-out.externos_verificados
    out['coincidencia_numerica']=np.isclose(out.viajes_visor,out.externos_verificados,atol=1e-8,rtol=0)
    out['unidad']='Viajes-persona de la referencia publicada; no coches, visitantes únicos o total anual'
    out['ambito']='Movimientos externos hacia/desde zonas187 y222; internos separados, no añadidos a entradas'
    out['expansion_y_equivalencia_con_aforos_validadas']=False
    out['limite']='Coincidir numéricamente no valida expansión o ámbito de aforos. Diferencias conservadas sin calibración; IDs de API y simulador distintos.'
    return out.reset_index(drop=True)


def convertir_captacion_anual_a_coches(proyeccion, *, ocupacion, fraccion_desde_coche):
    """Expresar viajes-persona captables como recorridos equivalentes condicionados.

    No acredita transporte efectivo, retirada del coche completo o parejas de
    ida/vuelta. Los componentes de alimentación/interior se calculan aparte.
    Una elección pendiente no se sustituye por una propuesta o por cero.
    """
    from movilidad_teide.operacion.dimensionamiento import estimar_coches_sustituidos

    claves = ['access_corridor', 'direccion', 'colectivo', 'anio_calendario']
    magnitudes = ['viajes_persona_proyectados', 'viajes_persona_captables_proyectados']
    if proyeccion.empty or not set(claves + magnitudes) <= set(proyeccion):
        raise ValueError('Falta proyección anual de personas por corredor, sentido y colectivo.')
    r = proyeccion.copy(deep=True)
    if (r[claves].isna().any().any() or r.duplicated(claves).any()
            or not set(r.direccion) <= {'subida', 'bajada'} or r.anio_calendario.nunique() != 1):
        raise ValueError('La proyección necesita un año y claves únicas con sentido identificado.')
    for col in magnitudes:
        valores = r[col].dropna().to_numpy(dtype=float)
        if not np.isfinite(valores).all() or (valores < 0).any():
            raise ValueError('La demanda anual debe ser no negativa y finita cuando es conocida.')
    total, captadas = [pd.to_numeric(r[c], errors='raise') for c in magnitudes]
    if (captadas.notna() & total.isna()).any() or (captadas > total+1e-8).any():
        raise ValueError('La captación no puede exceder o carecer de demanda de referencia.')
    if ocupacion is not None and _numero(ocupacion, 'ocupación', positivo=True) < 1:
        raise ValueError('La ocupación debe ser al menos una persona por coche.')
    if fraccion_desde_coche is not None and _numero(fraccion_desde_coche, 'fracción desde coche') > 1:
        raise ValueError('La fracción desde coche debe estar entre cero y uno.')
    r['ocupacion_aplicada'] = np.nan if ocupacion is None else float(ocupacion)
    r['fraccion_desde_coche_aplicada'] = np.nan if fraccion_desde_coche is None else float(fraccion_desde_coche)
    r['viajes_persona_captables_origen_coche'] = captadas*r.fraccion_desde_coche_aplicada
    r['viajes_persona_captables_otro_origen_modal'] = captadas-r.viajes_persona_captables_origen_coche
    # Reutilizar la conversión existente solo en observaciones conocidas.
    r['recorridos_coche_equivalentes_condicionados'] = np.nan
    conocidos = captadas.notna()
    r.loc[conocidos, 'recorridos_coche_equivalentes_condicionados'] = estimar_coches_sustituidos(
        captadas.loc[conocidos], ocupacion, fraccion_desde_coche)
    r['coches_efectivamente_sustituidos'] = np.nan
    r['coches_alimentacion_cabecera'] = np.nan
    r['estado_conversion'] = ('Elecciones pendientes: no conversión activa' if ocupacion is None or fraccion_desde_coche is None
        else 'Cálculo condicionado: no transporte efectivo, retirada de grupos o visitas identificadas')
    r['unidad_conversion'] = 'Recorridos equivalentes de coche/año por sentido; no coches únicos o visitas'
    cantidades = ['viajes_persona_proyectados', 'viajes_persona_captables_proyectados',
        'viajes_persona_captables_origen_coche', 'viajes_persona_captables_otro_origen_modal',
        'recorridos_coche_equivalentes_condicionados', 'coches_efectivamente_sustituidos', 'coches_alimentacion_cabecera']

    def sumar_sin_imputar(grupo):
        # Un subtotal incompleto debe seguir ausente, incluso si otras filas sí tienen cero.
        return grupo[cantidades].sum(min_count=len(grupo))

    filas = []
    for (corredor, sentido, anio), g in r.groupby(['access_corridor', 'direccion', 'anio_calendario'], sort=False):
        filas.append({'access_corridor':corredor, 'direccion':sentido, 'anio_calendario':anio,
                      **sumar_sin_imputar(g).to_dict()})
    resumen = pd.DataFrame(filas)
    sentidos = []
    for (corredor, anio), g in resumen.groupby(['access_corridor', 'anio_calendario'], sort=False):
        def valor(sentido):
            x = g.loc[g.direccion.eq(sentido), 'recorridos_coche_equivalentes_condicionados']
            return x.iloc[0] if len(x) else np.nan
        subida, bajada = valor('subida'), valor('bajada')
        sentidos.append({'access_corridor':corredor, 'anio_calendario':anio,
            'recorridos_equivalentes_subida':subida, 'recorridos_equivalentes_bajada':bajada,
            'diferencia_subida_menos_bajada':subida-bajada,
            'visitas_ida_vuelta_identificadas':np.nan,
            'interpretacion':'Conservo saldos; no emparejo movimientos ni cuento dos veces una visita.'})
    return {'detalle':r, 'por_corredor_sentido':resumen, 'coherencia_sentidos':pd.DataFrame(sentidos)}


def estimar_reparto_personas_aforos(resumen, *, ocupacion_coche, ocupacion_guagua,
                                    anios, puntos):
    """Contrastar personas-paso con conteos actuales y ocupaciones explícitas.

    Conservo las etiquetas entregadas coche/guagua. Su interpretación modal y
    las ocupaciones deben justificarse aparte; no identifico visitas únicas,
    procedencia de captados o retirada de coches. Entradas y salidas no se suman.
    """
    import calendar

    claves = ['anio', 'punto', 'sentido', 'tipo_vehiculo']
    calidad = ['medidas', 'valores_presentes', 'horas_esperadas', 'horas_ausentes',
               'marcas_fuera_calendario', 'valores_negativos', 'valores_ausentes']
    if resumen.empty or not set(claves + calidad + ['total_valores_fuente']) <= set(resumen):
        raise ValueError('Falta resumen anual con cobertura y calidad por categoría.')
    anios, puntos = list(anios), list(puntos)
    if (not anios or len(set(anios)) != len(anios)
            or any(isinstance(a, bool) or not isinstance(a, Integral) or not 1900 <= a <= 2200 for a in anios)
            or not puntos or len(set(puntos)) != len(puntos)
            or any(not isinstance(p, str) or not p.strip() for p in puntos)):
        raise ValueError('Años y puntos esperados deben estar identificados y ser únicos.')
    for nombre, valor in [('ocupación coche', ocupacion_coche), ('ocupación guagua', ocupacion_guagua)]:
        if valor is not None and _numero(valor, nombre, positivo=True) < 1:
            raise ValueError('Cada ocupación debe ser al menos una persona por vehículo.')
    d = resumen.loc[resumen.anio.isin(anios)].copy(deep=True)
    esperadas = {(a,p,s,t) for a in anios for p in puntos
                 for s in ['entrada','salida'] for t in ['coche','guagua']}
    if (d[claves].isna().any().any() or d.duplicated(claves).any()
            or set(d[claves].itertuples(index=False,name=None)) != esperadas):
        raise ValueError('Se exige una serie por año, punto, sentido y categoría; no sumar un ámbito parcial.')
    q = d[calidad].to_numpy(dtype=float)
    if not np.isfinite(q).all() or (q < 0).any() or not np.equal(q, np.floor(q)).all():
        raise ValueError('Los indicadores de cobertura/calidad deben ser enteros presentes y no negativos.')
    filas = []
    for (anio, punto, sentido), g in d.groupby(['anio','punto','sentido'], sort=True):
        horas = 24*(366 if calendar.isleap(int(anio)) else 365)
        fila = {'anio':anio, 'punto':punto, 'sentido':sentido, 'n_accesos':1, 'accesos':punto}
        incidencias = []
        for tipo in ['coche','guagua']:
            s = g.loc[g.tipo_vehiculo.eq(tipo)].iloc[0]
            pasos = float(s.total_valores_fuente) if pd.notna(s.total_valores_fuente) else np.nan
            fila[f'pasos_{tipo}'] = pasos
            fila[f'valores_decimales_{tipo}'] = int(s.get('valores_decimales',0))
            cobertura = (s.horas_esperadas == horas and s.medidas == horas and s.valores_presentes == horas
                         and s.horas_ausentes == 0 and s.marcas_fuera_calendario == 0 and s.valores_ausentes == 0)
            if not cobertura:incidencias.append(tipo+': cobertura anual incompleta o irregular')
            if s.valores_negativos or not np.isfinite(pasos) or pasos < 0:
                incidencias.append(tipo+': negativos o total ausente/no válido')
        fila['conteos_aptos_para_contraste'] = not incidencias
        fila['incidencias'] = '; '.join(incidencias) if incidencias else 'Sin incidencias de cobertura/negativos en las series seleccionadas'
        filas.append(fila)
    por_acceso = pd.DataFrame(filas)
    filas = []
    for (anio, sentido), g in por_acceso.groupby(['anio','sentido'], sort=True):
        fila = {'anio':anio, 'punto':'Conjunto de accesos seleccionados', 'sentido':sentido,
                'n_accesos':len(puntos), 'accesos':', '.join(sorted(puntos)),
                'conteos_aptos_para_contraste':bool(g.conteos_aptos_para_contraste.all()),
                'incidencias':'Conservo el conjunto solo si todos los accesos tienen series aptas'}
        for tipo in ['coche','guagua']:
            fila[f'pasos_{tipo}'] = g[f'pasos_{tipo}'].sum(min_count=len(g))
            fila[f'valores_decimales_{tipo}'] = int(g[f'valores_decimales_{tipo}'].sum())
        filas.append(fila)
    conjunto = pd.DataFrame(filas)
    for tabla in [por_acceso, conjunto]:
        valida = tabla.conteos_aptos_para_contraste
        suma_vehiculos = (tabla.pasos_coche+tabla.pasos_guagua).where(valida)
        tabla['fraccion_pasos_vehiculo_coche'] = tabla.pasos_coche/suma_vehiculos.where(suma_vehiculos.gt(0))
        tabla['ocupacion_coche_aplicada'] = np.nan if ocupacion_coche is None else float(ocupacion_coche)
        tabla['ocupacion_guagua_aplicada'] = np.nan if ocupacion_guagua is None else float(ocupacion_guagua)
        tabla['personas_paso_en_coche'] = (tabla.pasos_coche*tabla.ocupacion_coche_aplicada).where(valida)
        tabla['personas_paso_en_guagua'] = (tabla.pasos_guagua*tabla.ocupacion_guagua_aplicada).where(valida)
        tabla['personas_paso_estimadas'] = tabla.personas_paso_en_coche+tabla.personas_paso_en_guagua
        total = tabla.personas_paso_estimadas.where(tabla.personas_paso_estimadas.gt(0))
        tabla['fraccion_personas_paso_en_coche'] = tabla.personas_paso_en_coche/total
        tabla['fraccion_personas_paso_en_guagua'] = tabla.personas_paso_en_guagua/total
        tabla['clasificacion_modal_confirmada'] = False
        tabla['visitas_unicas_identificadas'] = False
        tabla['procedencia_coche_de_captados'] = np.nan
        tabla['estado_estimacion'] = np.select(
            [~valida, tabla.ocupacion_coche_aplicada.isna() | tabla.ocupacion_guagua_aplicada.isna(),
             tabla.personas_paso_estimadas.eq(0)],
            ['Sin estimación: series incompletas o con incidencias', 'Ocupaciones pendientes: sin reparto activo',
             'Sin reparto: cero pasos en ambas categorías'],
            default='Condicionado a ocupaciones y clasificación entregada; no visitantes únicos o captados')
        tabla['alcance'] = 'Solo categorías declaradas coche/guagua; sentidos separados, sin deduplicar visitas ni validar clasificación'
    return {'por_acceso':por_acceso, 'conjunto_por_sentido':conjunto}
