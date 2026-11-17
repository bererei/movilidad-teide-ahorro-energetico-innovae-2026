"""energia: actividad pareada. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import numpy as np
import pandas as pd
from movilidad_teide.energia.balance_condicionado_tipos import CRITERIO_TERRITORIAL
from movilidad_teide.energia.balance_condicionado_tipos import MAGNITUD_ANUAL
from movilidad_teide.energia.balance_condicionado_tipos import SENTIDOS


def repartir_actividad_condicionada(demanda, conversion, *, criterio=None):
    """Repartir una rama anual por cuotas territoriales explícitamente hipotéticas.

    Las 57 matrices solo aportan proporciones dentro de corredor/colectivo/sentido;
    las cantidades anuales proceden de la conversión D144. No anualiza esa media,
    cambia corredores fuente, completa orígenes sin ámbito o identifica coches.
    """
    from movilidad_teide.validacion import _claves
    if criterio not in (None, CRITERIO_TERRITORIAL):
        raise ValueError('Criterio territorial no reconocido.')
    _claves(demanda, ['origen_id', 'colectivo', 'sentido'], 'Demanda')
    _claves(conversion, ['access_corridor', 'colectivo', 'direccion'], 'Conversión')
    if not set(demanda.sentido) <= set(SENTIDOS):
        raise ValueError('Sentido de demanda no reconocido.')
    if not set(conversion.direccion) <= set(SENTIDOS.values()):
        raise ValueError('Sentido de conversión no reconocido.')
    media = pd.to_numeric(demanda.viajes_persona_media_57_matrices, errors='raise')
    cantidad = pd.to_numeric(conversion[MAGNITUD_ANUAL], errors='raise')
    if not np.isfinite(media).all() or (media < 0).any():
        raise ValueError('Cuotas territoriales: cantidades negativas o no finitas.')
    if (cantidad.dropna() < 0).any() or not np.isfinite(cantidad.dropna()).all():
        raise ValueError('Conversión: cantidades negativas o no finitas.')
    if conversion.anio_calendario.nunique(dropna=False) != 1:
        raise ValueError('No mezclar años en una distribución anual.')
    d = demanda.copy(deep=True)
    d['viajes_persona_media_57_matrices'] = media.to_numpy()
    d['direccion'] = d.sentido.map(SENTIDOS)
    claves = ['corredor_fuente', 'colectivo', 'direccion']
    anual = conversion.assign(**{MAGNITUD_ANUAL: cantidad}).rename(columns={'access_corridor': 'corredor_fuente', MAGNITUD_ANUAL: 'recorridos_grupo_anio'})
    d = d.merge(anual[claves + ['anio_calendario', 'recorridos_grupo_anio']].assign(en_ambito_anual=True),
                on=claves, how='left', validate='many_to_one')
    # No perder grupos anuales por un desacuerdo de etiquetas entre fuentes.
    grupos = set(map(tuple, d.loc[d.en_ambito_anual.eq(True), claves].drop_duplicates().to_numpy()))
    if grupos != set(map(tuple, anual[claves].to_numpy())):
        raise ValueError('Hay un grupo anual sin correspondencia territorial.')
    d['en_ambito_anual'] = d.en_ambito_anual.eq(True)
    denominador = d.groupby(claves, dropna=False).viajes_persona_media_57_matrices.transform('sum')
    if ((denominador <= 0) & d.en_ambito_anual).any():
        raise ValueError('Grupo anual sin cuota territorial positiva; no repartir equitativamente.')
    d['cuota_territorial_condicionada'] = np.nan
    if criterio is not None:
        m = d.en_ambito_anual
        d.loc[m, 'cuota_territorial_condicionada'] = d.loc[m, 'viajes_persona_media_57_matrices'] / denominador[m]
    d[MAGNITUD_ANUAL] = d.recorridos_grupo_anio * d.cuota_territorial_condicionada
    d['criterio_territorial_aplicado'] = criterio
    d['estado_reparto'] = np.where(~d.en_ambito_anual,
        'Sin referencia anual: conservar demanda media y ausencia anual',
        np.where(d[MAGNITUD_ANUAL].notna(), 'Reparto anual condicionado; no coches retirados',
                 'Elección territorial o conversión pendiente; no adoptar propuestas'))
    d['coches_efectivamente_sustituidos'] = np.nan
    if criterio is not None:
        for _, g in d.loc[d.en_ambito_anual].groupby(claves, dropna=False):
            if not np.isclose(g.cuota_territorial_condicionada.sum(), 1., rtol=0, atol=1e-12):
                raise ValueError('Las cuotas del grupo no suman uno.')
            original = g.recorridos_grupo_anio.iloc[0]
            if pd.notna(original) and not np.isclose(g[MAGNITUD_ANUAL].sum(min_count=len(g)), original, rtol=1e-12, atol=1e-9):
                raise ValueError('El reparto no conserva la cantidad anual de su grupo.')
    return d

def revisar_cupo_y_oferta(personas, oferta, *, cupo_global_dia, dias, ocupacion, fraccion_coche, plazas):
    """Prueba anual condicionada de conservación de visitas bajo un cupo global.

    Una subida equivale aquí, solo por hipótesis, a una visita. El cupo anual es
    un techo (no disponibilidad diaria demostrada). No usa pasos de aforo como
    visitas ni supone transferencia automática. El reparto proporcional anual
    es diagnóstico; no sustituye reservas diarias ni el reparto del Excel.
    """
    from movilidad_teide.validacion import _claves
    for nombre, valor in [('cupo', cupo_global_dia), ('dias', dias), ('ocupacion', ocupacion), ('plazas', plazas)]:
        if isinstance(valor, bool) or not np.isfinite(valor) or valor <= 0:
            raise ValueError('Valor positivo requerido: ' + nombre)
    if not np.isfinite(fraccion_coche) or not 0 <= fraccion_coche <= 1:
        raise ValueError('Fracción modal fuera de [0,1].')
    _claves(personas, ['access_corridor','colectivo','direccion'], 'Personas')
    _claves(oferta, ['corredor'], 'Oferta de acceso')
    campos=['viajes_persona_proyectados','viajes_persona_captables_proyectados']
    if not np.isfinite(personas[campos]).all().all() or (personas[campos]<0).any().any():
        raise ValueError('Demanda no finita o negativa.')
    if (personas[campos[1]]>personas[campos[0]]).any():
        raise ValueError('Captación superior a su demanda.')
    for campo in ['subidas_dia','bajadas_dia']:
        if not np.isfinite(oferta[campo]).all() or (oferta[campo]<0).any():
            raise ValueError('Oferta negativa o no finita.')
    arriba=personas.loc[personas.direccion.eq('subida')].groupby('access_corridor',as_index=False)[campos].sum()
    if set(arriba.access_corridor)!=set(oferta.corredor):
        raise ValueError('Demanda y oferta no cubren los mismos corredores.')
    x=arriba.merge(oferta[['corredor','subidas_dia','bajadas_dia']],left_on='access_corridor',right_on='corredor',validate='one_to_one')
    x['visitas_coche_sin_condicionadas']=x[campos[0]]*fraccion_coche/ocupacion
    total=x.visitas_coche_sin_condicionadas.sum()
    if total<=0:raise ValueError('No hay base de visitas en coche para repartir el techo.')
    # Un único techo global; nunca 500 coches por acceso.
    techo=min(total,cupo_global_dia*dias)
    x['techo_visitas_coche_autorizadas_condicionado']=techo*x.visitas_coche_sin_condicionadas/total
    x['visitas_coche_que_requeririan_otro_tratamiento']=x.visitas_coche_sin_condicionadas-x.techo_visitas_coche_autorizadas_condicionado
    x['personas_que_requeririan_otro_tratamiento']=x.visitas_coche_que_requeririan_otro_tratamiento*ocupacion
    x['captacion_actual_origen_coche']=x[campos[1]]*fraccion_coche
    x['captacion_actual_otro_origen_modal']=x[campos[1]]*(1-fraccion_coche)
    # Si todas conservan la visita y usan lanzadera, esta sería la necesidad.
    # El resto de captación se conserva una sola vez: no es demanda adicional.
    x['plazas_necesarias_subida_si_transferencia_completa']=x.personas_que_requeririan_otro_tratamiento+x.captacion_actual_otro_origen_modal
    x['plazas_ofertadas_subida_anio']=x.subidas_dia*plazas*dias
    x['plazas_ofertadas_bajada_anio']=x.bajadas_dia*plazas*dias
    x['capacidad_ida_vuelta_teorica_anio']=x[['plazas_ofertadas_subida_anio','plazas_ofertadas_bajada_anio']].min(axis=1)
    x['saldo_plazas_anual_condicionado']=x.capacidad_ida_vuelta_teorica_anio-x.plazas_necesarias_subida_si_transferencia_completa
    x['salidas_minimas_medias_por_sentido_dia']=x.plazas_necesarias_subida_si_transferencia_completa/(plazas*dias)
    x['ocupacion_media_requerida_sobre_capacidad']=x.plazas_necesarias_subida_si_transferencia_completa/x.capacidad_ida_vuelta_teorica_anio.replace(0,np.nan)
    x['coches_efectivamente_sustituidos']=np.nan
    x['operacion_viable_validada']=False
    x['alcance']='Prueba condicionada anual; no previsión, reservas por franja o transporte efectivo. Interior no se suma como otra visita.'
    return x

def emparejar_retornos_condicionados(reparto):
    """Imponer un regreso por origen/colectivo a la subida del ensayo, no al dato.

    Solo para la hipótesis explícita de visitas conservadas y retorno por la
    misma cadena. No deduplica telefonía ni transforma bajadas observadas.
    """
    from movilidad_teide.validacion import _claves
    _claves(reparto,['origen_id','colectivo','sentido'],'Reparto de visitas')
    x=reparto.copy(deep=True);keys=['origen_id','colectivo']
    up=x.loc[x.sentido.eq('hacia_teide')].set_index(keys)
    down=x.loc[x.sentido.eq('desde_teide')]
    if set(up.index)!=set(map(tuple,down[keys].to_numpy())):
        raise ValueError('Falta una pareja origen/colectivo para el regreso.')
    for i,row in down.iterrows():
        base=up.loc[(row.origen_id,row.colectivo)]
        if row.corredor_fuente!=base.corredor_fuente or row.en_ambito_anual!=base.en_ambito_anual:
            raise ValueError('Ámbito distinto en el regreso condicionado.')
        for campo in [MAGNITUD_ANUAL,'cuota_territorial_condicionada','recorridos_grupo_anio']:
            x.loc[i,campo]=base[campo]
    x['regreso_emparejado_por_hipotesis']=True
    return x

def actividad_comparacion_hot(diario,demanda,*,anio,cupo_global):
    """Reconstruir tres ramas anuales del ensayo D157 con un regreso por subida.

    No adopta la conversión histórica o transferencia completa como previsión.
    Conserva el dato de telefonía y solo empareja retornos en la rama hipotética.
    """
    from movilidad_teide.validacion import _claves
    key=['tipo_dia_publicado','access_corridor','colectivo']
    _claves(diario,key,'Conversión diaria')
    fields=['coches_sin_condicionados','recorridos_coche_retirados_condicionados_dia','dias_calendario']
    v=diario[fields].to_numpy(dtype=float)
    if (not np.isfinite(v).all() or (v<0).any() or diario.dias_calendario.eq(0).any()
            or diario.recorridos_coche_retirados_condicionados_dia.gt(diario.coches_sin_condicionados+1e-9).any()):
        raise ValueError('Conversión diaria incoherente.')
    if isinstance(cupo_global,bool) or not np.isfinite(cupo_global) or cupo_global<0:
        raise ValueError('Cupo global inválido.')
    d=diario.copy(deep=True)
    d['coches_autorizados_condicionados_dia']=d.coches_sin_condicionados-d.recorridos_coche_retirados_condicionados_dia
    checks=[]
    for day,g in d.groupby('tipo_dia_publicado'):
        if g.dias_calendario.nunique()!=1 or not float(g.dias_calendario.iloc[0]).is_integer():
            raise ValueError('Días de calendario incompatibles.')
        retained=float(g.coches_autorizados_condicionados_dia.sum())
        if retained>cupo_global+1e-8:raise ValueError('Se supera el cupo global diario.')
        checks.append({'tipo_dia':day,'dias_calendario':int(g.dias_calendario.iloc[0]),
            'coches_sin_condicionados_dia':g.coches_sin_condicionados.sum(),
            'coches_autorizados_condicionados_dia':retained,
            'coches_transferidos_condicionados_dia':g.recorridos_coche_retirados_condicionados_dia.sum()})
    base=demanda[['origen_id','colectivo','sentido','corredor_fuente','viajes_persona_media_57_matrices']].copy()
    branches=[]
    for name,field in [('antes','coches_sin_condicionados'),('autorizados','coches_autorizados_condicionados_dia'),
            ('transferidos','recorridos_coche_retirados_condicionados_dia')]:
        d['actividad_rama_anio']=d[field]*d.dias_calendario
        annual=d.groupby(['access_corridor','colectivo'],as_index=False).actividad_rama_anio.sum()
        up=annual.rename(columns={'actividad_rama_anio':MAGNITUD_ANUAL}).assign(direccion='subida',anio_calendario=anio)
        down=up.assign(direccion='bajada')
        x=repartir_actividad_condicionada(base,pd.concat([up,down],ignore_index=True),criterio=CRITERIO_TERRITORIAL)
        branches.append(emparejar_retornos_condicionados(x).assign(rama=name))
    detail=pd.concat(branches,ignore_index=True)
    group=detail.loc[detail.en_ambito_anual].groupby(['rama','corredor_fuente','sentido'],as_index=False)[MAGNITUD_ANUAL].sum()
    pivot=detail.pivot(index=['origen_id','colectivo','sentido'],columns='rama',values=MAGNITUD_ANUAL)
    known=pivot.antes.notna()
    if not np.allclose(pivot.loc[known,'antes'],pivot.loc[known,'autorizados']+pivot.loc[known,'transferidos'],rtol=1e-12,atol=1e-8):
        raise ValueError('El reparto no conserva las ramas de visitas.')
    return {'detalle':detail,'resumen':group,'control_diario':pd.DataFrame(checks)}
