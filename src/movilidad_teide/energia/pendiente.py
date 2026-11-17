"""Corrección física convencional en las cadenas completas sin/con.

Conserva el resto de tecnologías y su Hot. Su cambio por pendiente queda
sin estimar: no es cero observado, un intervalo probabilístico o ahorro acreditado.
"""
from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd
import geopandas as gpd
from movilidad_teide.vehiculos.dgt import clasificar_microdatos_parque
from movilidad_teide.energia.circulacion import MODOS
from movilidad_teide.energia.fisica_turismos import trabajo_gravitatorio_por_tonelada


GRUPOS = ['grupo_servicio','familia_copert','euro_copert','CAT_EURO','EMISIONES_EURO',
          'categoria_turismo_compatible','segmento_copert_propuesto']
MODELOS = ['ambito_geografico','grupo_servicio','SERVICIO','RENTING','CAT_EURO',
    'categoria_turismo_compatible','PROPULSION','CATELECT','ALIMENTACION','TIPO_DISTINTIVO',
    'familia_copert','estado_tecnologia','EMISIONES_EURO','euro_copert','estado_euro',
    'norma_para_factor_compatible','MARCA','MODELO']


def masas_grupos_desde_dgt(path, municipios, equivalencias, tamanos, diagnostico, *, chunksize=100000):
    """Vincular tara al mismo registro que originó cada grupo COPERT.

    No cruzar una mediana general de gasolina con todos los tamaños. Si un
    grupo carece de tara válida se documenta el préstamo del mismo servicio y
    combustible; P25/P75 pertenecen al mismo conjunto donante.
    """
    def clean(t,keys):
        for k in keys:t[k]=t[k].fillna('').astype(str)
        return t
    sizes=clean(tamanos[MODELOS+['segmento_copert_propuesto']].copy(),MODELOS+['segmento_copert_propuesto'])
    groups=clean(diagnostico[['grupo_id','vehiculos']+GRUPOS].copy(),GRUPOS)
    if sizes.duplicated(MODELOS).any() or groups.duplicated(GRUPOS).any() or groups.grupo_id.duplicated().any():
        raise ValueError('Modelos o grupos de consumo repetidos.')
    fields=['PROVINCIA','MUNICIPIO','TIPO_DGT','CAT_EURO','SERVICIO','RENTING','PROPULSION',
            'CATELECT','ALIMENTACION','TIPO_DISTINTIVO','EMISIONES_EURO','PESO_MAX','TARA','MARCA','MODELO']
    pieces=[]
    for raw in pd.read_csv(path,sep='|',encoding='cp1252',dtype=str,keep_default_na=False,usecols=fields,chunksize=chunksize):
        t=clasificar_microdatos_parque(raw,municipios,equivalencias)
        t['MARCA']=raw.MARCA;t['MODELO']=raw.MODELO
        t=t.loc[t.TIPO_DGT.eq('TURISMOS')&t.ambito_geografico.eq('Tenerife identificado')].copy()
        if t.empty:continue
        tara=pd.to_numeric(raw.loc[t.index,'TARA'],errors='coerce').to_numpy(float)
        mma=pd.to_numeric(raw.loc[t.index,'PESO_MAX'],errors='coerce').to_numpy(float)
        valid=np.isfinite(tara)&(tara>0)&(tara%1==0)&~(np.isfinite(mma)&(mma>0)&(tara>mma))
        t['tara_utilizable_kg']=np.where(valid,tara,np.nan)
        t=clean(t,MODELOS).merge(sizes,on=MODELOS,how='left',validate='many_to_one',indicator=True)
        if t._merge.ne('both').any():raise ValueError('Un registro ha perdido su correspondencia de tamaño existente.')
        t=t.drop(columns='_merge').merge(groups[GRUPOS+['grupo_id']],on=GRUPOS,how='left',validate='many_to_one',indicator=True)
        if t._merge.ne('both').any():raise ValueError('Un registro ha perdido su grupo de consumo existente.')
        pieces.append(t[['grupo_id','grupo_servicio','familia_copert','tara_utilizable_kg']])
    if not pieces:raise ValueError('Sin registros de tara para el stock del estudio.')
    raw=pd.concat(pieces,ignore_index=True)
    counts=raw.groupby('grupo_id').size()
    expected=groups.set_index('grupo_id').vehiculos.astype(int)
    if not counts.sort_index().equals(expected.sort_index().rename(counts.name)):
        raise ValueError('Las masas no conservan exactamente los grupos y conteos del stock.')
    pools={k:g.tara_utilizable_kg.dropna() for k,g in raw.groupby(['grupo_servicio','familia_copert'])}
    records=[]
    for row in groups.itertuples():
        local=raw.loc[raw.grupo_id.eq(row.grupo_id),'tara_utilizable_kg'].dropna()
        chosen=local;method='Mismo grupo DGT de servicio, combustible, norma, categoría y tamaño propuesto'
        if chosen.empty:
            chosen=pools[(row.grupo_servicio,row.familia_copert)]
            method='Préstamo explícito: mismo servicio y combustible; grupo sin tara válida'
        if chosen.empty and row.familia_copert in {'Petrol','Diesel'}:
            raise ValueError('No hay tara compatible para una familia convencional; no asignar masa cero.')
        records.append({'grupo_id':row.grupo_id,'grupo_servicio':row.grupo_servicio,'familia_copert':row.familia_copert,
            'vehiculos':row.vehiculos,'registros_tara_validos_grupo':len(local),'registros_tara_fuente':len(chosen),
            'tara_p25_kg':chosen.quantile(.25),'tara_mediana_kg':chosen.median(),'tara_p75_kg':chosen.quantile(.75),
            'criterio_masa':method,'prestamo_de_masa':local.empty})
    return pd.DataFrame(records)


def recortar_intervalos(segmentos, intervalos):
    """Partir perfiles en límites de vía o visita, conservando su pendiente.

    Las cotas se interpolan solo dentro del mismo tramo lineal ya disponible.
    No se consulta otro terreno, se alisa la pendiente o se cambia el trazado.
    """
    s=segmentos.sort_values('distance_start_m').copy()
    trabajo_gravitatorio_por_tonelada(s)
    ends=s.distance_end_m.to_numpy(float);starts=s.distance_start_m.to_numpy(float)
    if (not np.allclose(ends-starts,s.length_m,rtol=0,atol=1e-7)
            or np.any(np.abs(starts[1:]-ends[:-1])>1e-7)):
        raise ValueError('El perfil no es continuo en distancia.')
    rows=[]
    for idx,interval in enumerate(intervalos.to_dict('records')):
        a,b=interval['distance_start_m'],interval['distance_end_m']
        if not np.isfinite([a,b]).all() or b<=a or a<starts[0]-1e-7 or b>ends[-1]+1e-7:
            raise ValueError('Intervalo fuera del perfil existente o sin longitud.')
        first=int(np.searchsorted(ends,a,side='right'))
        for j in range(first,len(s)):
            if starts[j]>=b:break
            lo=max(a,starts[j]);hi=min(b,ends[j]);length=hi-lo
            if length<=1e-9:continue
            z=s.iloc[j];slope=(z.elevation_end_m-z.elevation_start_m)/z.length_m
            h0=z.elevation_start_m+slope*(lo-starts[j]);h1=z.elevation_start_m+slope*(hi-starts[j])
            rows.append({**interval,'segment_id':f'{idx}:{z.segment_id}',
                'segment_id_fuente':str(z.segment_id),'distance_start_m':lo,'distance_end_m':hi,
                'length_m':length,'elevation_start_m':h0,'elevation_end_m':h1,'slope_pct':100*(h1-h0)/length})
    out=pd.DataFrame(rows)
    if out.empty or abs(out.length_m.sum()-(intervalos.distance_end_m-intervalos.distance_start_m).sum())>1e-6:
        raise ValueError('El recorte pierde longitud; no completar huecos con pendiente cero.')
    return out


def cargar_perfiles_completos(root, aristas, inventario):
    """Enlazar perfiles existentes con los 124 componentes directa/alimentador."""
    root=Path(root);result=[];sources=[]
    for entry in inventario.itertuples():
        folder=(root/entry.archivo_geografico).parent;path=folder/'segmentos.parquet'
        meta_path=folder/'metadatos.json';meta=json.loads(meta_path.read_text())
        expected=meta.get('outputs_sha256',meta.get('archivos_sha256',{})).get(str(path.relative_to(root)))
        if expected!=hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('Perfil distinto del producto geográfico conservado.')
        raw=pd.read_parquet(path);sources.extend([str(path.relative_to(root)),entry.archivo_geografico,str(meta_path.relative_to(root))])
        parts=gpd.read_file(root/entry.archivo_geografico,layer='componentes')
        for (it,role),roads in aristas.loc[aristas.comparacion_id.eq(entry.comparacion_id)&aristas.rol.isin(['directa','alimentador'])].groupby(['itinerary_id','rol'],sort=False):
            if 'itinerary_id' not in raw:
                direction='Hacia el Teide' if '_ida_' in it else 'Regreso'
                alt='directa_tf523' if role=='directa' else 'alimentador_costero'
                seq=[raw.loc[raw.caso.eq(entry.comparacion_id)&raw.sentido.eq(direction)&raw.alternativa.eq(alt)]]
            else:
                ident=it
                if role=='alimentador' and it not in set(raw.itinerary_id):
                    match=parts.loc[parts.source_itinerary_id.eq(it)&parts.componente.eq('origen_cabecera')]
                    if len(match)!=1:raise ValueError('Alimentador sin enlace a su perfil fuente.')
                    ident=match.itinerary_id.item()
                full=raw.loc[raw.itinerary_id.eq(ident)]
                if role=='alimentador':seq=[full.loc[full.componente.eq('origen_cabecera')]]
                elif full.componente.eq('referencia_directa').any():seq=[full.loc[full.componente.eq('referencia_directa')]]
                else:
                    order=parts.loc[parts.itinerary_id.eq(ident),'componente'].tolist()
                    seq=[full.loc[full.componente.eq(k)] for k in order if k in {'origen_cabecera','cabecera_teide'}]
            profile=[];offset=0.
            for k,t in enumerate(seq):
                if t.empty:raise ValueError('Falta un componente de la cadena física.')
                t=t.sort_values('distance_start_m').copy();t['segment_id']=t.segment_id.map(lambda n:f'{k}:{n}')
                t['distance_start_m']+=offset;t['distance_end_m']+=offset
                offset+=float(t.length_m.sum());profile.append(t)
            if not profile:raise ValueError('Recorrido sin perfil; no usar plano por defecto.')
            profile=pd.concat(profile,ignore_index=True)
            if abs(offset-roads.length_m.sum())>1e-5:raise ValueError('El perfil y la vía no conservan la misma longitud.')
            cut=recortar_intervalos(profile,roads)
            cut['comparacion_id']=entry.comparacion_id;cut['fuente_perfil']=str(path.relative_to(root))
            result.append(cut)
    return pd.concat(result,ignore_index=True),sorted(set(sources))


def perfiles_visita_interior(root, patrones):
    """Visita próxima de ida/regreso desde cada entrada, con perfiles dirigidos."""
    root=Path(root);folder=root/'data/silver/geografia/perfiles_altimetricos/interior_boca_tauce_el_portillo'
    originals={d:pd.read_parquet(folder/f'tramos_interior_boca_tauce_el_portillo_{d}_propuesta.parquet') for d in ['ida','vuelta']}
    length=float(originals['ida'].length_m.sum());rows=[]
    chosen=patrones.loc[patrones.patron_id.eq('zona_proxima')]
    if set(chosen.terminal_calculo)!={'Boca Tauce','El Portillo'} or len(chosen)!=2:
        raise ValueError('La visita próxima no está definida para las dos entradas.')
    for p in chosen.itertuples():
        half=p.longitud_interior_ida_vuelta_km*1000/2
        for direction,s in originals.items():
            # Distancia dirigida: ida parte de Boca Tauce y vuelta de El Portillo.
            starts_here=(p.terminal_calculo=='Boca Tauce')==(direction=='ida')
            a,b=(0.,half) if starts_here else (length-half,length)
            interval=pd.DataFrame([{'distance_start_m':a,'distance_end_m':b,
                'clase_propuesta':'convencional','itinerary_id':'visita_proxima_'+p.terminal_calculo,
                'rol':'interior','comparacion_id':'visita_proxima_'+p.terminal_calculo}])
            z=recortar_intervalos(s,interval);z['segment_id']=direction+':'+z.segment_id
            z['fuente_perfil']=str((folder/f'tramos_interior_boca_tauce_el_portillo_{direction}_propuesta.parquet').relative_to(root))
            rows.append(z)
    return pd.concat(rows,ignore_index=True)


def preparar_curvas_convencionales(pesos, perfiles, masas, biblioteca, parametros):
    """Conservar pesos originales y factores nativos, antes del cálculo no lineal."""
    v={p['id']:p['valor_utilizado'] for p in parametros['parametros']}
    speeds={k:v['velocidad_turismo_'+k] for k in MODOS}
    p=perfiles.loc[perfiles.familia_copert.isin(['Petrol','Diesel'])].drop_duplicates(['grupo_id','peso_stock_original'])
    if p.grupo_id.duplicated().any():raise ValueError('Peso de stock ambiguo entre condiciones.')
    c=pesos.loc[pesos.familia_copert.isin(['Petrol','Diesel'])].copy()
    c=c.merge(p[['grupo_id','peso_stock_original']],on='grupo_id',how='left',validate='many_to_one')
    c=c.merge(masas[['grupo_id','tara_p25_kg','tara_mediana_kg','tara_p75_kg','criterio_masa']],on='grupo_id',how='left',validate='many_to_one')
    if (c[['peso_stock_original','tara_p25_kg','tara_mediana_kg','tara_p75_kg']].isna().any().any()
            or not np.allclose(c.groupby('grupo_id').peso_curva.sum(),1,rtol=0,atol=1e-12)):
        raise ValueError('Falta masa o se han perdido pesos de la mezcla convencional.')
    c['peso_total']=c.peso_curva*c.peso_stock_original
    rows=[]
    for road,mode in MODOS.items():
        b=biblioteca.loc[biblioteca.Fuel.isin(['Petrol','Diesel'])&biblioteca.driving_mode.eq(mode)&biblioteca.speed_kmh.eq(speeds[road])]
        b=b[['Fuel','Segment','Euro Standard','hot_ec_mj_per_km']]
        if b.duplicated(['Fuel','Segment','Euro Standard']).any():raise ValueError('Factor nativo convencional repetido.')
        z=c.merge(b,left_on=['familia_copert','segmento_nativo','norma_curva_nativa'],right_on=['Fuel','Segment','Euro Standard'],how='left',validate='many_to_one')
        if z.hot_ec_mj_per_km.isna().any() or z.hot_ec_mj_per_km.le(0).any():raise ValueError('Falta factor de la curva convencional.')
        z['clase_propuesta']=road;z['velocidad_kmh']=speeds[road];z['modo']=mode
        rows.append(z)
    curves=pd.concat(rows,ignore_index=True)
    # La expansión reproduce exactamente el factor D170 de cada grupo/condición.
    rebuilt=(curves.hot_ec_mj_per_km*curves.peso_curva).groupby([curves.grupo_id,curves.modo,curves.velocidad_kmh]).sum()
    selected=perfiles.loc[perfiles.familia_copert.isin(['Petrol','Diesel'])]
    selected=selected.loc[[speeds.get(next((k for k,m in MODOS.items() if m==r.modo),''))==r.velocidad_kmh for r in selected.itertuples()]]
    expected=selected.set_index(['grupo_id','modo','velocidad_kmh']).factor_inferior_mj_km
    if set(rebuilt.index)!=set(expected.index) or not np.allclose(rebuilt.sort_index(),expected.sort_index(),rtol=0,atol=1e-10):
        raise ValueError('Las curvas no reproducen los factores de referencia conservados.')
    return curves


def energia_pendiente_por_recorrido(segmentos, curvas, factores, parametros, *, ocupacion,
                                    estadistico=None, tratamiento=None, multiplicador_eta=1.):
    """Corregir cada curva convencional y después ponderar; resto explícito.

    La masa y conversión se aplican a cada tramo dirigido. La gravedad sobrante
    se disipa, sin convertirla en combustible negativo o electricidad exportada.
    """
    v={p['id']:p['valor_utilizado'] for p in parametros['parametros']}
    choices={'Mediana (P50)':'tara_mediana_kg','Cuartil inferior (P25)':'tara_p25_kg','Cuartil superior (P75)':'tara_p75_kg'}
    stat=estadistico or v['criterio_tara_turismos'];rule=tratamiento or v['tratamiento_descenso_turismos']
    if (stat not in choices or rule not in {'Corte ideal de inyección','Sin reducción de consumo en descenso'}
            or not np.isfinite(ocupacion) or ocupacion<1 or not np.isfinite(multiplicador_eta) or multiplicador_eta<=0):
        raise ValueError('Elecciones de masa/descenso o ocupación inválidas.')
    fields=['comparacion_id','itinerary_id','rol'];rows=[]
    for (comparison,it,role),group in segmentos.groupby(fields,sort=False):
        for service in curvas.grupo_servicio.unique():
            base_conv=adjusted=base_total=0.;kms=0.
            for road,s in group.groupby('clase_propuesta',sort=False):
                if road not in MODOS:raise ValueError('Tramo sin clase de circulación; no usar rural por defecto.')
                x=curvas.loc[curvas.grupo_servicio.eq(service)&curvas.clase_propuesta.eq(road)]
                mass=x[choices[stat]].to_numpy(float)+ocupacion*v['masa_persona_turismo_kg']+v['equipaje_turismo_kg_coche']
                eta=np.where(x.familia_copert.eq('Petrol'),v['eficiencia_incremental_gasolina_pendiente'],v['eficiencia_incremental_diesel_pendiente'])*multiplicador_eta
                if (not np.isfinite(mass).all() or (mass<=0).any() or not np.isfinite(eta).all() or (eta<=0).any() or (eta>1).any()):
                    raise ValueError('Masa o eficiencia de la mezcla sin resolver.')
                length=s.length_m.to_numpy(float)/1000;dh=(s.elevation_end_m-s.elevation_start_m).to_numpy(float)
                energy=length[:,None]*x.hot_ec_mj_per_km.to_numpy(float)[None,:]
                gravity=dh[:,None]*mass[None,:]*9.81/1e6/eta[None,:]
                corrected=np.maximum(energy+gravity,0) if rule=='Corte ideal de inyección' else energy+np.maximum(gravity,0)
                weights=x.peso_total.to_numpy(float)
                base_conv+=float(energy.sum(axis=0)@weights);adjusted+=float(corrected.sum(axis=0)@weights)
                f=factores.loc[factores.grupo_servicio.eq(service)&factores.modo.eq(MODOS[road])&factores.velocidad_kmh.eq(v['velocidad_turismo_'+road])]
                if (len(f)!=1 or not np.isclose(f.aporte_conjunto_condicionado_min_mj_km.item(),f.aporte_conjunto_condicionado_max_mj_km.item(),rtol=0,atol=1e-12)):
                    raise ValueError('La referencia Hot de la mezcla no es única o está ausente.')
                base_total+=float(length.sum()*f.aporte_conjunto_condicionado_min_mj_km.item());kms+=float(length.sum())
            if base_conv>base_total+1e-8 or min(base_conv,adjusted)<0:
                raise ValueError('La cobertura convencional no es compatible con la mezcla completa.')
            rows.append({'comparacion_id':comparison,'itinerary_id':it,'rol':role,'grupo_servicio':service,'ocupacion_coche':ocupacion,
                'criterio_tara':stat,'tratamiento_descenso':rule,'multiplicador_eta':multiplicador_eta,'longitud_km':kms,
                'energia_base_mj_recorrido':base_total,'energia_base_convencional_mj':base_conv,
                'energia_convencional_ajustada_mj':adjusted,'correccion_convencional_mj':adjusted-base_conv,
                'energia_base_otras_tecnologias_mj':base_total-base_conv,'correccion_otras_tecnologias_mj':np.nan,
                'energia_con_ajuste_convencional_mj':base_total+adjusted-base_conv,
                'correccion_completa_de_todas_tecnologias':False})
    return pd.DataFrame(rows)


def coeficiente_por_recorrido(recorrido, lookup, *, alternativa, colectivo, sentido, rama, ocupacion):
    """Obtener un coeficiente unitario sin consultar actividad ni pesos anuales."""
    from movilidad_teide.opciones import ALQUILER, PARTICULAR
    if rama not in {'antes','autorizados','transferidos','alimentacion_otros'}:
        raise ValueError('Rama de recorrido desconocida.')
    service=ALQUILER if colectivo=='extranjero' or ('alquiler' in alternativa and colectivo=='espana_no_tenerife') else PARTICULAR
    role='alimentador' if rama in {'transferidos','alimentacion_otros'} else 'directa'
    it=recorrido.itinerario_alimentador_id if role=='alimentador' else recorrido.itinerario_referencia_id
    cols=['energia_base_mj_recorrido','energia_base_convencional_mj','correccion_convencional_mj','energia_base_otras_tecnologias_mj']
    vals=lookup.loc[(recorrido.comparacion_calculo_id,it,role,service,ocupacion),cols].to_numpy(dtype=float,copy=True)
    if rama in {'antes','autorizados'} and sentido=='hacia_teide':
        interior='visita_proxima_'+recorrido.terminal_calculo
        vals+=lookup.loc[(interior,interior,'interior',service,ocupacion),cols].to_numpy(float)
    return vals, service


def aplicar_correcciones_a_actividad(coches, otros, recorridos, energia):
    """Aplicar el mismo consumo por recorrido a cantidades anuales sin/con.

    Coches conserva antes/autorizados/transferidos; otros mantiene el contraste
    adicional de un coche por persona. La visita interior se cuenta una vez,
    desde subida, y sus dos sentidos ya están en el coeficiente del recorrido.
    """
    from movilidad_teide.opciones import ALQUILER, PARTICULAR
    ids=['alternativa_procedencia','origen_id','colectivo','sentido']
    if coches.duplicated(ids+['rama']).any() or set(coches.rama)!={'antes','autorizados','transferidos'}:
        raise ValueError('Ramas incompletas o cantidades de coches duplicadas.')
    amounts=coches.pivot(index=ids,columns='rama',values='recorridos_coche_anio')
    if amounts.isna().any().any() or not np.allclose(amounts.antes,amounts.autorizados+amounts.transferidos,rtol=0,atol=1e-8):
        raise ValueError('No se conserva antes = autorizados + transferidos.')
    route=recorridos.set_index(['origen_id','sentido'])
    keys=['comparacion_id','itinerary_id','rol','grupo_servicio','ocupacion_coche']
    if energia.duplicated(keys).any():raise ValueError('Coeficiente por recorrido repetido.')
    lookup=energia.set_index(keys)
    cols=['energia_base_mj_recorrido','energia_base_convencional_mj','correccion_convencional_mj','energia_base_otras_tecnologias_mj']
    rows=[]
    for label,activity in [('Coches del reparto modal',coches),('Alimentación adicional desde otros modos',otros)]:
        for r in activity.itertuples():
            rr=route.loc[(r.origen_id,r.sentido)]
            other=label.startswith('Alimentación');branch='alimentacion_otros' if other else r.rama
            occ=1. if other else float(energia.loc[energia.ocupacion_coche.ne(1),'ocupacion_coche'].drop_duplicates().item())
            vals,service=coeficiente_por_recorrido(rr,lookup,alternativa=r.alternativa_procedencia,colectivo=r.colectivo,sentido=r.sentido,rama=branch,ocupacion=occ)
            n=r.personas_trayecto_anio if other else r.recorridos_coche_anio
            if not np.isfinite(n) or n<0:raise ValueError('Actividad anual sin resolver o negativa.')
            if abs(vals[0]/3600-r.energia_mwh_por_vehiculo_sentido)>1e-10:
                raise ValueError('El coeficiente base no reproduce el consumo anterior del mismo recorrido.')
            rows.append({'alternativa_procedencia':r.alternativa_procedencia,'origen_id':r.origen_id,'colectivo':r.colectivo,
                'sentido':r.sentido,'rama':branch,'grupo_servicio':service,'componente':label,'ocupacion_hipotesis':occ,'recorridos_coche_anio':n,
                'energia_base_mwh_por_vehiculo_sentido':vals[0]/3600,'correccion_mwh_por_vehiculo_sentido':vals[2]/3600,
                'energia_base_mwh_anio':n*vals[0]/3600,'energia_base_convencional_mwh_anio':n*vals[1]/3600,
                'correccion_convencional_mwh_anio':n*vals[2]/3600,'energia_base_otras_tecnologias_mwh_anio':n*vals[3]/3600,
                'correccion_otras_tecnologias_mwh_anio':np.nan})
    return pd.DataFrame(rows)


def verificar_activacion_pendiente_anual(anterior, actual):
    """Reutilizar D212 solo si cambian las seis etiquetas de aplicación anual."""
    labels={'criterio_tara_turismos','masa_persona_turismo_kg','equipaje_turismo_kg_coche',
            'eficiencia_incremental_gasolina_pendiente','eficiencia_incremental_diesel_pendiente','tratamiento_descenso_turismos'}
    if (anterior['caso']!=actual['caso'] or actual['caso']!='Central'
            or anterior['elecciones_todos_los_casos']!=actual['elecciones_todos_los_casos']):
        raise ValueError('Cambian caso o elecciones; recalcular también actividad y consumo afectados.')
    old={p['id']:p for p in anterior['parametros']};new={p['id']:p for p in actual['parametros']}
    if set(old)!=set(new):raise ValueError('Cambian las referencias del libro; revisar la reutilización.')
    for key,before in old.items():
        after=new[key]
        if key in labels:
            if (any(before[k]!=after[k] for k in before if k!='aplicacion')
                    or not after['aplicacion'].startswith('Aplicado: ajuste anual condicionado')):
                raise ValueError('Cambio ajeno a la etiqueta anual de pendiente: '+key)
        elif before!=after:raise ValueError('Cambio ajeno a la aplicación anual de pendiente: '+key)
    return {'valores_y_elecciones_previas_conservados':True,'etiquetas_anuales_actualizadas':sorted(labels),
            'demanda_actividad_y_referencias_de_consumo_sin_cambios':True}
