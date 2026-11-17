"""vehiculos: composicion. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import numpy as np
import pandas as pd
from movilidad_teide.vehiculos.flota_tipos import ErrorFlota


def construir_referencias_turismos(cruce, candidatos, biblioteca, *, velocidades, anio):
    """Conservar el stock completo por servicio y auditar factores exactos.

    Las cuotas describen vehículos registrados, no actividad visitante. Los
    soportes repetidos entre tamaños del catálogo nunca vuelven a sumarse.
    Un perfil solo tiene cobertura completa si están todas sus alternativas
    en todos los nodos/modos técnicos solicitados; no se elige un tamaño.
    """
    campos = ['Category','Fuel','Segment','Euro Standard']
    claves = ['grupo_servicio','familia_copert','euro_copert',
        'categoria_turismo_compatible','norma_para_factor_compatible','estado_tecnologia','estado_euro']
    if not set(claves+['ambito_geografico','vehiculos']) <= set(cruce):
        raise ErrorFlota('Faltan los cruces reales de combustible, Euro y servicio DGT.')
    if not set(campos+['clave_disponible']) <= set(candidatos):
        raise ErrorFlota('Faltan las alternativas identificadas del catálogo COPERT.')
    columnas_b = campos+['year','driving_mode','speed_kmh','hot_ec_mj_per_km','unit']
    if biblioteca.empty or not set(columnas_b) <= set(biblioteca):
        raise ErrorFlota('Biblioteca sin condiciones, unidades o factores identificados.')
    velocidades = list(velocidades)
    if (not velocidades or len(set(velocidades)) != len(velocidades)
            or any(isinstance(v,bool) or not isinstance(v,(int,float,np.integer,np.floating))
                   or not np.isfinite(v) or v <= 0 for v in velocidades)):
        raise ErrorFlota('Los nodos técnicos de velocidad deben ser finitos, positivos y únicos.')
    if isinstance(anio,bool) or not isinstance(anio,(int,np.integer)) or not 1900 <= anio <= 2200:
        raise ErrorFlota('Año de factores no válido.')
    n = pd.to_numeric(cruce.vehiculos,errors='coerce')
    if not np.isfinite(n).all() or n.le(0).any() or n.mod(1).ne(0).any():
        raise ErrorFlota('El soporte de la DGT debe ser un conteo entero positivo.')
    for campo in ['categoria_turismo_compatible','norma_para_factor_compatible']:
        if not cruce[campo].map(lambda v:isinstance(v,(bool,np.bool_))).all():
            raise ErrorFlota('Compatibilidad de categoría/norma sin clasificación booleana revisada.')
    d = cruce.loc[cruce.ambito_geografico.eq('Tenerife identificado')].copy(deep=True)
    if d.empty:raise ErrorFlota('No hay stock identificado de Tenerife; no usar provincia o municipios desconocidos.')
    d['vehiculos'] = n.loc[d.index].to_numpy()
    for c in ['grupo_servicio','familia_copert','euro_copert','estado_tecnologia','estado_euro']:
        d[c] = d[c].fillna('').astype(str)
    if d.grupo_servicio.str.strip().eq('').any():raise ErrorFlota('El servicio DGT debe estar identificado.')
    p = d.groupby(claves,dropna=False,as_index=False).vehiculos.sum()
    alt = candidatos.loc[candidatos.clave_disponible.eq(True),campos].copy()
    if alt[campos].isna().any().any() or alt.duplicated(campos).any() or not alt.Category.eq('Passenger Cars').all():
        raise ErrorFlota('Alternativas de turismo incompletas, repetidas o de otra categoría.')
    b = biblioteca.copy(deep=True)
    if b[columnas_b].isna().any().any() or b.duplicated(campos+['year','driving_mode','speed_kmh']).any():
        raise ErrorFlota('Factores duplicados o sin condiciones completas.')
    factores = pd.to_numeric(b.hot_ec_mj_per_km,errors='coerce')
    if set(b.unit) != {'MJ/km'} or not np.isfinite(factores).all() or factores.le(0).any():
        raise ErrorFlota('Factores ausentes/no positivos o unidades incompatibles.')
    modos = ['urban_peak','urban_off_peak','rural','highway']
    indices = set(b[campos+['year','driving_mode','speed_kmh']].itertuples(index=False,name=None))
    cobertura = {}; comparacion = []
    for (fuel,euro), g in alt.groupby(['Fuel','Euro Standard'],sort=True):
        vehiculos = list(g[campos].itertuples(index=False,name=None))
        requeridos = {(*v,anio,m,s) for v in vehiculos for m in modos for s in velocidades}
        encontrados = len(requeridos & indices)
        completa = encontrados == len(requeridos)
        cobertura[fuel,euro] = (len(vehiculos),encontrados,len(requeridos),completa)
        for modo in modos:
            for velocidad in velocidades:
                buscados = {(*v,anio,modo,velocidad) for v in vehiculos}
                completa_condicion = buscados <= indices
                f = b.loc[b.Fuel.eq(fuel)&b['Euro Standard'].eq(euro)&b.year.eq(anio)
                    &b.driving_mode.eq(modo)&b.speed_kmh.eq(velocidad)&b.Category.eq('Passenger Cars')&b.Segment.isin(g.Segment)]
                comparacion.append({'familia_copert':fuel,'euro_copert':euro,'anio':anio,
                    'modo_tecnico':modo,'velocidad_tecnica_kmh':velocidad,
                    'alternativas_catalogo':len(vehiculos),'alternativas_con_factor':len(buscados & indices),
                    'cobertura_completa_condicion':completa_condicion,
                    'factor_min_alternativas_mj_km':float(f.hot_ec_mj_per_km.min()) if completa_condicion else np.nan,
                    'factor_max_alternativas_mj_km':float(f.hot_ec_mj_per_km.max()) if completa_condicion else np.nan,
                    'interpretacion':'Extremos entre tamaños candidatos; no intervalo estadístico ni tamaño elegido'})
    filas = []
    for row in p.to_dict(orient='records'):
        c = cobertura.get((row['familia_copert'],row['euro_copert']),(0,0,0,False))
        apto = bool(row['categoria_turismo_compatible'] and row['norma_para_factor_compatible'])
        completa = apto and c[3]
        row.update(alternativas_catalogo=c[0],factores_disponibles=c[1],factores_requeridos=c[2],
            factores_completos_para_alternativas=completa,
            estado_cobertura=('Factores de todas las alternativas disponibles; tamaño por elegir' if completa
                else 'Categoría de turismo sin acreditar' if not row['categoria_turismo_compatible']
                else 'Tecnología sin correspondencia revisada' if not row['familia_copert']
                else 'Norma/generación de consumo sin correspondencia revisada' if not row['norma_para_factor_compatible']
                else 'Factores ausentes o incompletos para las alternativas exactas'),
            peso_actividad_elegido=np.nan,
            criterio_hipotesis_pesos='Usar stock como proxy exigiría igual actividad media por vehículo dentro del servicio; no adoptado')
        filas.append(row)
    perfiles = pd.DataFrame(filas)
    perfiles['total_stock_servicio'] = perfiles.groupby('grupo_servicio').vehiculos.transform('sum')
    perfiles['cuota_stock_del_servicio'] = perfiles.vehiculos/perfiles.total_stock_servicio
    resumen = []
    for servicio,g in perfiles.groupby('grupo_servicio',sort=True):
        total = int(g.vehiculos.sum());cubierto = int(g.loc[g.factores_completos_para_alternativas,'vehiculos'].sum())
        assert np.isclose(g.cuota_stock_del_servicio.sum(),1,rtol=0,atol=1e-12)
        resumen.append({'grupo_servicio':servicio,'vehiculos_stock':total,
            'vehiculos_con_factores_para_todas_las_alternativas':cubierto,
            'vehiculos_sin_cobertura_completa':total-cubierto,'fraccion_stock_con_cobertura':cubierto/total,
            'cuota_actividad_teide_elegida':np.nan,'consumo_medio_completo_mj_km':np.nan,
            'estado':'Referencia de stock2025; no mezcla por kilómetros o visitantes elegida'})
    return {'perfiles_stock':perfiles,'cobertura_por_servicio':pd.DataFrame(resumen),
            'contraste_tamanos':pd.DataFrame(comparacion)}

def revisar_cobertura_turismos(cruce, perfiles):
    """Separar carencias simultáneas y un contraste de categoría, sin imputar datos.

    ``cruce`` conserva el tipo DGT TURISMOS y los códigos originales. ``perfiles``
    procede de construir_referencias_turismos con la biblioteca vigente.
    La clasificación alternativa solo contrasta CAT_EURO ausente; nunca
    convierte una categoría contradictoria en M1 ni activa pesos de actividad.
    """
    claves = ['grupo_servicio','familia_copert','euro_copert',
        'categoria_turismo_compatible','norma_para_factor_compatible','estado_tecnologia','estado_euro']
    campos = ['alternativas_catalogo','factores_disponibles','factores_requeridos',
        'factores_completos_para_alternativas']
    requeridos = set(claves+['ambito_geografico','TIPO_DGT','CAT_EURO','EMISIONES_EURO','vehiculos'])
    if not requeridos <= set(cruce) or not set(claves+campos+['vehiculos']) <= set(perfiles):
        raise ErrorFlota('La revisión necesita tipo/categoría originales y cobertura de factores identificada.')
    d = cruce.loc[cruce.ambito_geografico.eq('Tenerife identificado')].copy(deep=True)
    p = perfiles[claves+campos+['vehiculos']].copy(deep=True)
    if d.empty or not d.TIPO_DGT.eq('TURISMOS').all():
        raise ErrorFlota('Revisar solo el cruce original de tipo DGT TURISMOS identificado en Tenerife.')
    for tabla in [d,p]:
        n = pd.to_numeric(tabla.vehiculos,errors='coerce')
        if not np.isfinite(n).all() or n.le(0).any() or n.mod(1).ne(0).any():
            raise ErrorFlota('La revisión requiere conteos enteros positivos, sin pérdidas de soporte.')
        tabla['vehiculos'] = n.astype('int64')
        for c in ['categoria_turismo_compatible','norma_para_factor_compatible']:
            if not tabla[c].map(lambda v:isinstance(v,(bool,np.bool_))).all():
                raise ErrorFlota('La compatibilidad de categoría/norma debe estar revisada y ser booleana.')
        for c in ['grupo_servicio','familia_copert','euro_copert','estado_tecnologia','estado_euro']:
            tabla[c] = tabla[c].fillna('').astype(str)
    if p.duplicated(claves).any():
        raise ErrorFlota('La cobertura contiene perfiles repetidos; no multiplicar los vehículos al cruzarla.')
    soporte = d.groupby(claves,dropna=False,as_index=False).vehiculos.sum()
    comprobacion = soporte.merge(p[claves+['vehiculos']],on=claves,how='outer',
        validate='one_to_one',suffixes=('_original','_referencia'),indicator=True)
    if (not comprobacion['_merge'].eq('both').all()
            or not comprobacion.vehiculos_original.eq(comprobacion.vehiculos_referencia).all()):
        raise ErrorFlota('La cobertura y los microdatos no describen el mismo stock por perfil.')
    d = d.merge(p.drop(columns='vehiculos'),on=claves,how='left',validate='many_to_one')
    # Leer los vacíos sin sustituir el literal original CAT_EURO o EMISIONES_EURO.
    categoria = d.CAT_EURO.fillna('').astype(str).str.strip()
    if not categoria.isin(['M1','M1G']).eq(d.categoria_turismo_compatible).all():
        raise ErrorFlota('La compatibilidad publicada no concuerda con la categoría europea original.')
    for c in ['alternativas_catalogo','factores_disponibles','factores_requeridos']:
        v = pd.to_numeric(d[c],errors='coerce')
        if not np.isfinite(v).all() or v.lt(0).any() or v.mod(1).ne(0).any():
            raise ErrorFlota('Disponibilidad de factores sin conteos enteros válidos.')
        d[c] = v.astype('int64')
    if (d.factores_disponibles.gt(d.factores_requeridos).any()
            or (d.alternativas_catalogo.eq(0) != d.factores_requeridos.eq(0)).any()):
        raise ErrorFlota('La disponibilidad de factores no concuerda con las alternativas requeridas.')
    if not d.factores_completos_para_alternativas.map(lambda v:isinstance(v,(bool,np.bool_))).all():
        raise ErrorFlota('Cobertura completa sin clasificación booleana revisada.')
    d['factores_tecnicos_del_perfil_completos'] = (
        d.factores_requeridos.gt(0) & d.factores_disponibles.eq(d.factores_requeridos))
    base = d.familia_copert.ne('') & d.norma_para_factor_compatible
    documentada = d.categoria_turismo_compatible & base & d.factores_tecnicos_del_perfil_completos
    if not documentada.eq(d.factores_completos_para_alternativas).all():
        raise ErrorFlota('La cobertura declarada no se reproduce desde categoría, norma y factores.')
    d['estado_categoria'] = np.select([d.categoria_turismo_compatible,categoria.eq('')],
        ['Categoría europea M1/M1G documentada','Categoría europea ausente; tipo DGT TURISMOS'],
        default='Categoría europea distinta de M1/M1G; discrepancia por revisar')
    # Los motivos son simultáneos: cada registro conserva todos los que le afectan.
    d['pendiente_categoria'] = ~d.categoria_turismo_compatible
    d['pendiente_tecnologia'] = d.familia_copert.eq('')
    d['pendiente_norma_generacion'] = ~d.norma_para_factor_compatible
    d['pendiente_factores'] = base & ~d.factores_tecnicos_del_perfil_completos
    motivos = {'pendiente_categoria':'Categoría','pendiente_tecnologia':'Tecnología',
        'pendiente_norma_generacion':'Norma/generación','pendiente_factores':'Factores'}
    d['combinacion_pendientes'] = [
        ' + '.join(nombre for c,nombre in motivos.items() if fila[c]) or 'Cobertura documentada completa'
        for fila in d.to_dict('records')]
    d['cobertura_documentada'] = documentada
    d['cobertura_condicionada_tipo_dgt'] = (
        (d.categoria_turismo_compatible | categoria.eq('')) & base & d.factores_tecnicos_del_perfil_completos)
    d['ganancia_condicionada_tipo_dgt'] = d.cobertura_condicionada_tipo_dgt & ~documentada
    d['criterio_contraste_categoria'] = np.where(categoria.eq(''),
        'Propuesta: usar tipo DGT TURISMOS cuando CAT_EURO está ausente; no imputar M1',
        'Conservar categoría europea publicada; no sustituir discrepancias por M1')
    d['estado_contraste'] = 'Solo contraste condicionado; no clasificación adoptada, energía o peso de actividad'

    def tratamiento(fila):
        acciones = []
        if fila['pendiente_categoria']:
            acciones.append('Contrastar tipo DGT sin imputar M1' if not str(fila['CAT_EURO'] or '').strip()
                else 'Revisar discrepancia; conservar fuera de la aproximación para categorías ausentes')
        if fila['pendiente_tecnologia']:acciones.append('Revisar códigos originales de propulsión, categoría eléctrica y alimentación')
        if fila['pendiente_norma_generacion']:
            acciones.append('Definir generación COPERT y frontera de electricidad' if fila['familia_copert']=='Battery electric'
                else 'Preparar hipótesis explícita para norma ausente/ambigua; no inferir por edad o distintivo')
        if fila['pendiente_factores']:
            familia = fila['familia_copert']
            acciones.append('Consultar con reparto explícito entre gas y gasolina' if familia in ['LPG Bifuel','CNG Bifuel']
                else 'Consultar electricidad y combustible con uso eléctrico explícito' if familia in ['Petrol PHEV','Diesel PHEV']
                else 'Completar factores de las claves y condiciones exactas')
        return ' / '.join(acciones) or 'Factores disponibles; tamaño y pesos de actividad pendientes'
    # La lectura para redactar acciones no modifica los códigos originales.
    vista = d.copy();vista['CAT_EURO'] = vista.CAT_EURO.fillna('')
    d['tratamiento_propuesto'] = [tratamiento(fila) for fila in vista.to_dict('records')]
    resumen = d.groupby(['grupo_servicio','combinacion_pendientes',*motivos],dropna=False,as_index=False).vehiculos.sum()
    resumen['total_stock_servicio'] = resumen.groupby('grupo_servicio').vehiculos.transform('sum')
    resumen['fraccion_stock_servicio'] = resumen.vehiculos/resumen.total_stock_servicio
    filas = []
    for servicio,g in d.groupby('grupo_servicio',sort=True):
        total = int(g.vehiculos.sum())
        estricto = int(g.loc[g.cobertura_documentada,'vehiculos'].sum())
        condicionado = int(g.loc[g.cobertura_condicionada_tipo_dgt,'vehiculos'].sum())
        filas.append({'grupo_servicio':servicio,'vehiculos_stock':total,
            'vehiculos_cobertura_documentada':estricto,'vehiculos_cobertura_condicionada':condicionado,
            'vehiculos_adicionales_condicionados':condicionado-estricto,
            'vehiculos_aun_pendientes_bajo_contraste':total-condicionado,
            'estado':'Propuesta de clasificación; no mezcla visitante o consumo completo elegidos'})
    return {'diagnostico':d,'combinaciones_pendientes':resumen,'contraste_categoria':pd.DataFrame(filas)}

def preparar_mezcla_stock_turismos(cruce, catalogo, biblioteca, *, velocidades, anio, criterio_pesos=None):
    """Conservar todo el stock y calcular solo aportes condicionados representados.

    No elige tamaños, utiliza cuotas entre servicios ni imputa normas. Las
    equivalencias Euro6 se admiten solo con las tres curvas completas e iguales
    en toda la malla, para cada tamaño y control nativo. Las alternativas de
    catálogo no son límites del consumo físico o intervalos estadísticos.
    """
    criterio='Igual kilometraje medio dentro de cada servicio'
    if criterio_pesos not in (None,criterio):raise ErrorFlota('Criterio de pesos no reconocido; no adoptar stock como actividad automáticamente.')
    campos=['Category','Fuel','Segment','Euro Standard']
    requeridos=['grupo_servicio','familia_copert','euro_copert','CAT_EURO','EMISIONES_EURO',
        'categoria_turismo_compatible','vehiculos','ambito_geografico']
    if not set(requeridos)<=set(cruce) or not set(campos)<=set(catalogo):raise ErrorFlota('Faltan campos originales o catálogo de vehículos.')
    condiciones=['year','driving_mode','speed_kmh','primary_control_fraction']
    if not set(campos+condiciones+['hot_ec_mj_per_km','unit'])<=set(biblioteca):raise ErrorFlota('Factores sin condiciones completas.')
    speeds=list(velocidades);modos=['urban_peak','urban_off_peak','rural','highway']
    if not speeds or len(set(speeds))!=len(speeds) or any(isinstance(x,bool) or not np.isfinite(x) or x<=0 for x in speeds):
        raise ErrorFlota('Malla de velocidad no válida.')
    d=cruce.loc[cruce.ambito_geografico.eq('Tenerife identificado')].copy(deep=True)
    if d.empty:raise ErrorFlota('No hay turismos identificados en Tenerife.')
    n=pd.to_numeric(d.vehiculos,errors='coerce')
    if not np.isfinite(n).all() or n.le(0).any() or n.mod(1).ne(0).any():raise ErrorFlota('Conteos de stock no válidos.')
    if not d.categoria_turismo_compatible.map(lambda x:isinstance(x,(bool,np.bool_))).all():raise ErrorFlota('Categoría sin compatibilidad revisada.')
    cat=d.CAT_EURO.fillna('').astype(str).str.strip()
    if not cat.isin(['M1','M1G']).eq(d.categoria_turismo_compatible).all():raise ErrorFlota('Categoría original y compatibilidad no concuerdan.')
    d['vehiculos']=n.astype('int64')
    for c in ['familia_copert','euro_copert']:d[c]=d[c].fillna('').astype(str)
    b=biblioteca.copy(deep=True);b['primary_control_fraction']=b.primary_control_fraction.fillna(-1.)
    if b.duplicated(campos+condiciones).any():raise ErrorFlota('Factores repetidos por clave y condición.')
    f=pd.to_numeric(b.hot_ec_mj_per_km,errors='coerce')
    if not b.unit.eq('MJ/km').all() or not np.isfinite(f).all() or f.le(0).any():raise ErrorFlota('Factores no positivos o unidades incompatibles.')
    c=catalogo.loc[catalogo.Category.eq('Passenger Cars'),campos].drop_duplicates()
    if c[campos].isna().any().any():raise ErrorFlota('Catálogo con claves ausentes.')
    euros=['Euro 6 a/b/c','Euro 6 d-temp','Euro 6 d/e']
    bifuel={'LPG Bifuel','CNG Bifuel','Petrol PHEV','Diesel PHEV'}
    indices={tuple(row[:8]):row[8] for row in b[campos+condiciones+['hot_ec_mj_per_km']].itertuples(index=False,name=None)}
    cache={};evidencia=[]
    def alternativas(fuel,euro,equivalencia):
        key=(fuel,euro,equivalencia)
        if key in cache:return cache[key]
        normas=euros if equivalencia else [euro]
        sub=c.loc[c.Fuel.eq(fuel)&c['Euro Standard'].isin(normas)]
        sizes=sorted(sub.Segment.unique());controles=[0.,1.] if fuel in bifuel else [-1.]
        completo=bool(sizes) and set(sub['Euro Standard'])==set(normas)
        values={};max_delta=0.
        for size in sizes:
            for mode in modos:
                for speed in speeds:
                    for control in controles:
                        wanted=[('Passenger Cars',fuel,size,norma,anio,mode,speed,control) for norma in normas]
                        if any(k not in indices for k in wanted):completo=False;continue
                        fs=[indices[k] for k in wanted];delta=max(fs)-min(fs);max_delta=max(max_delta,delta)
                        if equivalencia and delta>1e-10:completo=False
                        # Una curva equivalente por tamaño/control, sin repartir entre normas ficticias.
                        values[size,mode,speed,control]=fs[0]
        state=('Equivalencia Hot EC completa en la malla; sin norma imputada' if equivalencia
            else 'Norma documentada y factores completos') if completo else 'Faltan alternativas completas o curvas equivalentes'
        evidencia.append({'familia_copert':fuel,'norma_consultada':'Tres Euro6 del catálogo' if equivalencia else euro,
            'equivalencia_solicitada':equivalencia,'alternativas_completas':completo,
            'max_diferencia_normas_mj_km':max_delta if values else np.nan,'criterio':state})
        cache[key]=(completo,values,state)
        return cache[key]
    perfiles=[];factores=[]
    # Agrupar sin borrar el literal original o mezclar servicios registrales.
    grupos=['grupo_servicio','familia_copert','euro_copert','CAT_EURO','EMISIONES_EURO','categoria_turismo_compatible']
    source=d.groupby(grupos,dropna=False,as_index=False).vehiculos.sum()
    totals=source.groupby('grupo_servicio').vehiculos.sum()
    for i,row in enumerate(source.to_dict('records')):
        fuel=row['familia_copert'];euro=row['euro_copert']
        literal=str(row['EMISIONES_EURO']).replace(' ','').upper()
        equiv=fuel=='Battery electric' or (not euro and literal=='EURO6')
        complete,vals,state=alternativas(fuel,euro,equiv) if fuel and (euro or equiv) else (False,{},'Tecnología o norma sin representación')
        represented=bool(row['categoria_turismo_compatible'] and complete)
        if not row['categoria_turismo_compatible']:state='Categoría ausente o contradictoria conservada; propuesta D147 no adoptada'
        weight=row['vehiculos']/totals.loc[row['grupo_servicio']]
        perfiles.append({**row,'perfil_id':i,'representado':represented,'criterio_representacion':state,
            'cuota_stock_servicio':weight,'peso_actividad_condicionado':weight if criterio_pesos else np.nan,
            'hipotesis_pesos':criterio_pesos or 'Pendiente; no se adopta la propuesta'})
        for mode in modos:
            for speed in speeds:
                fs=[v for (size,m,s,control),v in vals.items() if m==mode and s==speed] if represented else []
                factores.append({'perfil_id':i,'grupo_servicio':row['grupo_servicio'],'modo':mode,'velocidad_kmh':speed,
                    'factor_min_alternativas_mj_km':min(fs) if fs else np.nan,
                    'factor_max_alternativas_mj_km':max(fs) if fs else np.nan})
    p=pd.DataFrame(perfiles);detail=pd.DataFrame(factores).merge(p[['perfil_id','vehiculos','representado','peso_actividad_condicionado']],on='perfil_id',validate='many_to_one')
    resumen=[]
    for (servicio,mode,speed),g in detail.groupby(['grupo_servicio','modo','velocidad_kmh'],sort=True):
        known=g.loc[g.representado];total=int(g.vehiculos.sum());covered=int(known.vehiculos.sum())
        resumen.append({'grupo_servicio':servicio,'modo':mode,'velocidad_kmh':speed,'vehiculos_stock':total,
            'vehiculos_representados':covered,'vehiculos_pendientes':total-covered,'fraccion_stock_representada':covered/total,
            'aporte_parte_representada_min_mj_km':float((known.peso_actividad_condicionado*known.factor_min_alternativas_mj_km).sum()) if criterio_pesos and covered else np.nan,
            'aporte_parte_representada_max_mj_km':float((known.peso_actividad_condicionado*known.factor_max_alternativas_mj_km).sum()) if criterio_pesos and covered else np.nan,
            'factor_medio_completo_mj_km':np.nan,
            'estado':'Aporte parcial condicionado, sin renormalizar; no media completa, límite físico o intervalo estadístico' if criterio_pesos else 'Elección pendiente; aportes energéticos ausentes'})
    return {'perfiles':p,'factores_por_perfil':detail,'resumen':pd.DataFrame(resumen),'equivalencias':pd.DataFrame(evidencia)}

def preparar_aportes_tamanos_turismos(modelos, catalogo, biblioteca, *, velocidades, anio,
                                     criterio_pesos=None, criterio_tamanos=None):
    """Contrastar tamaños propuestos y alternativas sin completar desconocidos.

    Los controles nativos de gas/PHEV permanecen separados. Los extremos
    agregados comparan referencias consultadas, no consumos físicos límite,
    un uso real elegido o una media completa de toda la flota.
    """
    from movilidad_teide.vehiculos.dgt import resumir_tamanos_turismos
    opciones={'Todas las alternativas de tamaño','Tamaño propuesto; resto alternativas'}
    if criterio_tamanos is not None and criterio_tamanos not in opciones:
        raise ErrorFlota('Criterio de tamaños no reconocido; no asignar un tamaño por defecto.')
    # Reutilizar la comprobación completa de categorías, normas y equivalencias.
    velocidades=list(velocidades)
    base=preparar_mezcla_stock_turismos(modelos,catalogo,biblioteca,
        velocidades=velocidades,anio=anio,criterio_pesos=criterio_pesos)
    revisado=resumir_tamanos_turismos(modelos,base['perfiles'],catalogo)['detalle']
    keys=['grupo_servicio','familia_copert','euro_copert','CAT_EURO','EMISIONES_EURO','categoria_turismo_compatible']
    p=base['perfiles'][keys+['perfil_id','representado']].copy()
    for tabla in (revisado,p):
        for c in keys[:-1]:tabla[c]=tabla[c].fillna('')
    if not set(revisado.segmento_copert_propuesto.fillna(''))<=(set(catalogo.Segment)|{''}):
        raise ErrorFlota('Tamaño propuesto fuera del catálogo.')
    # Agrupar el cruce original por el tamaño propuesto; no fabricar un reparto del resto.
    g=revisado.assign(segmento_copert_propuesto=revisado.segmento_copert_propuesto.fillna(''))
    g=g.groupby(keys+['segmento_copert_propuesto'],dropna=False,as_index=False).vehiculos.sum()
    g=g.merge(p,on=keys,validate='many_to_one');totales=g.groupby('grupo_servicio').vehiculos.sum()
    speeds=list(velocidades);modos=['urban_peak','urban_off_peak','rural','highway']
    b=biblioteca.copy();b['primary_control_fraction']=b.primary_control_fraction.fillna(-1.)
    columns=['Category','Fuel','Segment','Euro Standard','year','driving_mode','speed_kmh','primary_control_fraction']
    indices={tuple(row[:-1]):row[-1] for row in b[columns+['hot_ec_mj_per_km']].itertuples(index=False,name=None)}
    native=catalogo.loc[catalogo.Category.eq('Passenger Cars')]
    bifuel={'LPG Bifuel','CNG Bifuel','Petrol PHEV','Diesel PHEV'}
    aplicar=criterio_pesos is not None and criterio_tamanos is not None
    grupos=[];factores=[]
    for ident,row in enumerate(g.to_dict('records')):
        fuel,euro=row['familia_copert'],row['euro_copert'];size=row['segmento_copert_propuesto']
        equiv=fuel=='Battery electric' or (not euro and str(row['EMISIONES_EURO']).replace(' ','').upper()=='EURO6')
        # La primera curva solo representa las otras después de la equivalencia D149.
        curva='Euro 6 a/b/c' if equiv else euro
        sizes=sorted(native.loc[native.Fuel.eq(fuel)&native['Euro Standard'].eq(curva),'Segment'].unique())
        usar_size=bool(size) and criterio_tamanos=='Tamaño propuesto; resto alternativas'
        if usar_size:sizes=[size] if size in sizes else []
        representado=bool(row['representado'] and sizes)
        estado=('Tamaño de familia propuesto, con factores' if usar_size else 'Alternativas de tamaño sin repartir') if representado else 'Sin factores compatibles; cantidad conservada'
        peso=row['vehiculos']/totales.loc[row['grupo_servicio']]
        grupos.append({**row,'grupo_id':ident,'representado_en_contraste':representado,
            'usa_tamano_propuesto':usar_size,'estado_contraste':estado,'cuota_stock_servicio':peso,
            'peso_actividad_condicionado':peso if aplicar else np.nan,
            'criterio_tamanos':criterio_tamanos or 'Pendiente; no activar la propuesta'})
        controles=[0.,1.] if fuel in bifuel and representado else [-1.]
        for mode in modos:
            for speed in speeds:
                for control in controles:
                    fs=[]
                    if representado:
                        wanted=[('Passenger Cars',fuel,s,curva,anio,mode,speed,control) for s in sizes]
                        if any(k not in indices for k in wanted):
                            raise ErrorFlota('La referencia de tamaño no conserva todas las condiciones verificadas.')
                        fs=[indices[k] for k in wanted]
                    factores.append({'grupo_id':ident,'grupo_servicio':row['grupo_servicio'],'familia_copert':fuel,
                        'modo':mode,'velocidad_kmh':speed,'control_primario_nativo':np.nan if control==-1 else control,
                        'factor_min_tamanos_mj_km':min(fs) if fs else np.nan,
                        'factor_max_tamanos_mj_km':max(fs) if fs else np.nan})
    perfiles=pd.DataFrame(grupos)
    detalle=pd.DataFrame(factores).merge(perfiles[['grupo_id','vehiculos','representado_en_contraste',
        'peso_actividad_condicionado']],on='grupo_id',validate='many_to_one')
    # Los controles son alternativas: nunca se suman como si fueran vehículos distintos.
    un_control=detalle.groupby(['grupo_id','grupo_servicio','modo','velocidad_kmh'],as_index=False).agg(
        factor_min=('factor_min_tamanos_mj_km','min'),factor_max=('factor_max_tamanos_mj_km','max'),
        vehiculos=('vehiculos','first'),representado=('representado_en_contraste','first'),
        peso=('peso_actividad_condicionado','first'))
    resumen=[]
    for (service,mode,speed),part in un_control.groupby(['grupo_servicio','modo','velocidad_kmh']):
        known=part.loc[part.representado];total=int(part.vehiculos.sum());n=int(known.vehiculos.sum())
        resumen.append({'grupo_servicio':service,'modo':mode,'velocidad_kmh':speed,'vehiculos_stock':total,
            'vehiculos_representados':n,'vehiculos_sin_factores':total-n,
            'aporte_parcial_min_mj_km':float((known.peso*known.factor_min).sum()) if aplicar and n else np.nan,
            'aporte_parcial_max_mj_km':float((known.peso*known.factor_max).sum()) if aplicar and n else np.nan,
            'factor_medio_completo_mj_km':np.nan,
            'estado':'Alternativas condicionadas de la parte representada; no media completa ni intervalo físico' if aplicar else 'Elecciones pendientes; aportes ausentes'})
    tecnologia=[]
    for (service,fuel,mode,speed,control),part in detalle.groupby(
            ['grupo_servicio','familia_copert','modo','velocidad_kmh','control_primario_nativo'],dropna=False):
        known=part.loc[part.representado_en_contraste];n=int(known.vehiculos.sum())
        tecnologia.append({'grupo_servicio':service,'familia_copert':fuel,'modo':mode,'velocidad_kmh':speed,
            'control_primario_nativo':control,'vehiculos_representados':n,
            'denominador_stock_servicio':int(totales.loc[service]),
            'aporte_parcial_min_mj_km':float((known.peso_actividad_condicionado*known.factor_min_tamanos_mj_km).sum()) if aplicar and n else np.nan,
            'aporte_parcial_max_mj_km':float((known.peso_actividad_condicionado*known.factor_max_tamanos_mj_km).sum()) if aplicar and n else np.nan,
            'estado':'Control nativo consultado, sin reparto real de utilización elegido' if np.isfinite(control) else 'Tecnología sin control bifuel aplicable o sin representación'})
    estados=perfiles.groupby(['grupo_servicio','estado_contraste'],as_index=False).vehiculos.sum()
    return {'perfiles':perfiles,'factores_por_grupo':detalle,'resumen':pd.DataFrame(resumen),
        'tecnologias_controles':pd.DataFrame(tecnologia),'estados':estados,
        'equivalencias':base['equivalencias']}

def contrastar_registros_incompletos_turismos(modelos, catalogo, biblioteca, *, velocidades, anio,
        criterio_pesos=None, criterio_tamanos=None, criterio_categoria=None, criterio_norma=None):
    """Comparar referencias para vacíos, sin imputar categorías, normas o energía.

    La referencia por norma vacía usa exclusivamente curvas ya consultadas;
    conserva las claves nativas sin malla. No cubre todo consumo posible ni
    convierte una aproximación en representación documental del registro.
    """
    categoria='Contrastar tipo DGT si categoría vacía'
    norma='Contrastar normas consultadas si norma vacía'
    if criterio_categoria not in (None,'Conservar pendientes',categoria) or criterio_norma not in (None,'Conservar pendientes',norma):
        raise ErrorFlota('Tratamiento de registros incompletos no reconocido.')
    if 'TIPO_DGT' not in modelos or not modelos.TIPO_DGT.fillna('').eq('TURISMOS').all():
        raise ErrorFlota('El tipo DGT TURISMOS debe proceder del subconjunto original, no de la categoría imputada.')
    velocidades=list(velocidades)
    base=preparar_aportes_tamanos_turismos(modelos,catalogo,biblioteca,velocidades=velocidades,anio=anio,
        criterio_pesos=criterio_pesos,criterio_tamanos=criterio_tamanos)
    p=base['perfiles'].copy();totales=p.groupby('grupo_servicio').vehiculos.sum()
    modos=['urban_peak','urban_off_peak','rural','highway'];bifuel={'LPG Bifuel','CNG Bifuel','Petrol PHEV','Diesel PHEV'}
    euros=['Euro 6 a/b/c','Euro 6 d-temp','Euro 6 d/e']
    car=catalogo.loc[catalogo.Category.eq('Passenger Cars'),['Fuel','Segment','Euro Standard']].drop_duplicates()
    b=biblioteca.loc[biblioteca.Category.eq('Passenger Cars')&biblioteca.year.eq(anio)].copy()
    b['primary_control_fraction']=b.primary_control_fraction.fillna(-1.)
    cols=['Fuel','Segment','Euro Standard','driving_mode','speed_kmh','primary_control_fraction']
    lookup={tuple(row[:-1]):row[-1] for row in b[cols+['hot_ec_mj_per_km']].itertuples(index=False,name=None)}
    condiciones=[(m,v) for m in modos for v in velocidades]
    aplicar=all(c is not None for c in [criterio_pesos,criterio_tamanos,criterio_categoria,criterio_norma])
    equivalencias=base['equivalencias'];cache={};faltantes=set();diagnostico=[];factores=[]
    for row in p.to_dict('records'):
        ident=row['grupo_id'];fuel=row['familia_copert'];euro=row['euro_copert']
        cat=str(row['CAT_EURO']).strip();literal=str(row['EMISIONES_EURO']).strip()
        usa_cat=False;usa_norm=False;valores={};keys=[];missing=[];estado=''
        if row['representado_en_contraste']:
            estado='Representado previamente; sin tratamiento nuevo'
        elif cat not in {'','M1','M1G'}:
            estado='Categoría contradictoria; sin asimilación'
        elif not fuel:
            estado='Tecnología sin correspondencia; no prestar otro combustible'
        elif not cat and criterio_categoria!=categoria:
            estado='Categoría vacía; contraste no elegido'
        else:
            usa_cat=not bool(cat)
            equiv=fuel=='Battery electric' or (not euro and literal.replace(' ','').upper()=='EURO6')
            if not euro and literal and not equiv:
                estado='Norma informada sin equivalencia revisada; sin reasignación'
            elif not euro and not equiv and criterio_norma!=norma:
                estado='Norma vacía; contraste no elegido'
            elif not usa_cat and (euro or equiv):
                estado='Combinación documentada sin factores completos; no sustituir la norma'
            else:
                usa_norm=not bool(euro) and not equiv and not bool(literal)
                selected=row['segmento_copert_propuesto'] if row['usa_tamano_propuesto'] else ''
                token=(fuel,euro,equiv,selected,usa_norm)
                if token not in cache:
                    candidates=car.loc[car.Fuel.eq(fuel)]
                    if selected:candidates=candidates.loc[candidates.Segment.eq(selected)]
                    if not usa_norm:candidates=candidates.loc[candidates['Euro Standard'].isin(euros if equiv else [euro])]
                    controls=[0.,1.] if fuel in bifuel else [-1.]
                    complete=[];incomplete=[]
                    for f,size,eu in candidates.itertuples(index=False,name=None):
                        wanted=[(f,size,eu,m,v,c) for m,v in condiciones for c in controls]
                        if all(k in lookup for k in wanted):complete.append((f,size,eu))
                        else:incomplete.append((f,size,eu))
                    # Una norma documentada o equivalente exige la malla completa,
                    # igual que D149; no aumentar cobertura omitiendo alternativas faltantes.
                    valid=bool(complete)
                    if not usa_norm:
                        valid=valid and not incomplete
                        evidence=equivalencias.loc[equivalencias.familia_copert.eq(fuel)&
                            equivalencias.equivalencia_solicitada.eq(equiv)&
                            equivalencias.norma_consultada.eq('Tres Euro6 del catálogo' if equiv else euro)]
                        valid=valid and len(evidence)==1 and bool(evidence.iloc[0].alternativas_completas)
                    values={}
                    if valid:
                        for m,v in condiciones:
                            for c in controls:
                                fs=[lookup[(f,size,eu,m,v,c)] for f,size,eu in complete]
                                values[m,v,c]=(min(fs),max(fs))
                    cache[token]=(values,complete,incomplete)
                valores,keys,missing=cache[token]
                estado=('Referencia condicionada: categoría y norma vacías' if usa_cat and usa_norm else
                    'Referencia condicionada: categoría vacía' if usa_cat else
                    'Referencia condicionada: norma vacía') if valores else 'Sin referencias completas compatibles; conservar pendiente'
        for key in missing:faltantes.add(key)
        disponible=bool(valores)
        diagnostico.append({**row,'TIPO_DGT':'TURISMOS','referencia_condicionada_disponible':disponible,
            'usa_tipo_dgt_categoria_vacia':usa_cat and disponible,'usa_normas_consultadas_vacio':usa_norm and disponible,
            'estado_incompletos':estado,'claves_completas_referencia':len(keys),
            'claves_catalogo_sin_malla':len(missing),'dominio_consultado_incompleto':bool(missing),
            'normas_en_referencia':' | '.join(sorted({k[2] for k in keys})) if disponible else '',
            'cuota_stock_servicio_original':row['vehiculos']/totales.loc[row['grupo_servicio']]})
        for (m,v,c),(lo,hi) in valores.items():
            factores.append({'grupo_id':ident,'grupo_servicio':row['grupo_servicio'],'familia_copert':fuel,
                'modo':m,'velocidad_kmh':v,'control_primario_nativo':np.nan if c==-1 else c,
                'factor_referencia_min_mj_km':lo,'factor_referencia_max_mj_km':hi,
                'vehiculos':row['vehiculos'],'cuota_stock_servicio_original':row['vehiculos']/totales.loc[row['grupo_servicio']]})
    d=pd.DataFrame(diagnostico);f=pd.DataFrame(factores,columns=['grupo_id','grupo_servicio','familia_copert','modo',
        'velocidad_kmh','control_primario_nativo','factor_referencia_min_mj_km','factor_referencia_max_mj_km',
        'vehiculos','cuota_stock_servicio_original'])
    # Reducir controles alternativos antes de sumar vehículos y aportes.
    unico=f.groupby(['grupo_id','grupo_servicio','modo','velocidad_kmh'],as_index=False).agg(
        lo=('factor_referencia_min_mj_km','min'),hi=('factor_referencia_max_mj_km','max'),
        vehiculos=('vehiculos','first'),peso=('cuota_stock_servicio_original','first'))
    res=[]
    for row in base['resumen'].to_dict('records'):
        service=row['grupo_servicio'];grupo=d.loc[d.grupo_servicio.eq(service)]
        nref=int(grupo.loc[grupo.referencia_condicionada_disponible,'vehiculos'].sum())
        part=unico.loc[unico.grupo_servicio.eq(service)&unico.modo.eq(row['modo'])&unico.velocidad_kmh.eq(row['velocidad_kmh'])]
        lo=float((part.peso*part.lo).sum()) if aplicar else np.nan
        hi=float((part.peso*part.hi).sum()) if aplicar else np.nan
        nprev=row['vehiculos_representados'];npending=row['vehiculos_stock']-nprev-nref
        prev_lo=row['aporte_parcial_min_mj_km'];prev_hi=row['aporte_parcial_max_mj_km']
        conjunto_lo=(prev_lo if nprev else 0.)+lo if aplicar and nprev+nref else np.nan
        conjunto_hi=(prev_hi if nprev else 0.)+hi if aplicar and nprev+nref else np.nan
        res.append({'grupo_servicio':service,'modo':row['modo'],'velocidad_kmh':row['velocidad_kmh'],
            'vehiculos_stock':row['vehiculos_stock'],'vehiculos_representados_previamente':nprev,
            'vehiculos_con_referencia_condicionada':nref,'vehiculos_aun_sin_referencia':npending,
            'aporte_previo_min_mj_km':prev_lo,'aporte_previo_max_mj_km':prev_hi,
            'aporte_referencia_condicionada_min_mj_km':lo,'aporte_referencia_condicionada_max_mj_km':hi,
            'aporte_conjunto_condicionado_min_mj_km':conjunto_lo,'aporte_conjunto_condicionado_max_mj_km':conjunto_hi,
            'factor_medio_completo_mj_km':np.nan,
            'estado':'Referencias comparativas consultadas, no media completa ni límites físicos' if aplicar else 'Elecciones pendientes; aportes conjuntos ausentes'})
    estados=d.groupby(['grupo_servicio','estado_incompletos'],as_index=False).vehiculos.sum()
    gaps=pd.DataFrame(sorted(faltantes),columns=['Fuel','Segment','Euro Standard'])
    return {'diagnostico':d,'factores_referencia':f,'resumen':pd.DataFrame(res),'estados':estados,
        'claves_catalogo_sin_malla':gaps}

def desglosar_referencias_tecnicas_turismos(diagnostico, anteriores, condicionadas, resumen):
    """Explicar los aportes técnicos por perfil sin sumar controles alternativos.

    Reconcilia exactamente con los dos vectores ya publicados y conserva el
    denominador original. La separación no es incertidumbre estadística.
    """
    if diagnostico.grupo_id.duplicated().any():
        raise ErrorFlota('Identificador de perfil repetido.')
    d=diagnostico.copy(deep=True)
    flags=['representado_en_contraste','referencia_condicionada_disponible']
    if any(not d[k].isin([True,False]).all() for k in flags) or (d[flags[0]]&d[flags[1]]).any():
        raise ErrorFlota('Cobertura repetida o sin clasificación.')
    if not np.isfinite(d.vehiculos).all() or d.vehiculos.le(0).any():
        raise ErrorFlota('Conteos no válidos.')
    total=d.groupby('grupo_servicio').vehiculos.sum()
    old=anteriores.loc[anteriores.representado_en_contraste].rename(columns={
        'factor_min_tamanos_mj_km':'factor_inferior_mj_km','factor_max_tamanos_mj_km':'factor_superior_mj_km'})
    new=condicionadas.rename(columns={'factor_referencia_min_mj_km':'factor_inferior_mj_km',
        'factor_referencia_max_mj_km':'factor_superior_mj_km'})
    if set(old.grupo_id)&set(new.grupo_id):raise ErrorFlota('Un perfil se contaría por dos vías.')
    cols=['grupo_id','grupo_servicio','familia_copert','modo','velocidad_kmh','control_primario_nativo',
        'factor_inferior_mj_km','factor_superior_mj_km','vehiculos']
    f=pd.concat([old[cols],new[cols]],ignore_index=True)
    keys=['grupo_id','modo','velocidad_kmh','control_primario_nativo']
    if f.duplicated(keys).any():raise ErrorFlota('Control o condición repetidos.')
    if (not np.isfinite(f[['factor_inferior_mj_km','factor_superior_mj_km']]).all().all()
            or f.factor_inferior_mj_km.lt(0).any() or f.factor_superior_mj_km.lt(f.factor_inferior_mj_km).any()):
        raise ErrorFlota('Referencias incompletas o invertidas.')
    covered=d.loc[d[flags[0]]|d[flags[1]]].set_index('grupo_id')
    if set(f.grupo_id)!=set(covered.index):raise ErrorFlota('No se conserva la cobertura de perfiles.')
    for row in f.itertuples():
        original=covered.loc[row.grupo_id]
        if row.grupo_servicio!=original.grupo_servicio or row.familia_copert!=original.familia_copert or row.vehiculos!=original.vehiculos:
            raise ErrorFlota('Los factores contradicen el perfil original.')
    g=f.groupby(['grupo_id','grupo_servicio','familia_copert','modo','velocidad_kmh'],as_index=False).agg(
        factor_inferior_mj_km=('factor_inferior_mj_km','min'),
        factor_superior_mj_km=('factor_superior_mj_km','max'),vehiculos=('vehiculos','first'),
        alternativas_control=('control_primario_nativo',lambda x:x.fillna(-1).nunique()))
    g=g.merge(d[['grupo_id','usa_tamano_propuesto','representado_en_contraste','usa_tipo_dgt_categoria_vacia',
        'usa_normas_consultadas_vacio','estado_incompletos']],on='grupo_id',validate='many_to_one')
    g['peso_stock_original']=g.vehiculos/g.grupo_servicio.map(total)
    for side in ['inferior','superior']:
        g['aporte_'+side+'_mj_km']=g.peso_stock_original*g['factor_'+side+'_mj_km']
    g['separacion_referencias_mj_km']=g.aporte_superior_mj_km-g.aporte_inferior_mj_km
    groupkeys=['grupo_servicio','modo','velocidad_kmh']
    rebuilt=g.groupby(groupkeys,as_index=False)[['aporte_inferior_mj_km','aporte_superior_mj_km']].sum()
    wanted=resumen[groupkeys+['aporte_conjunto_condicionado_min_mj_km','aporte_conjunto_condicionado_max_mj_km']]
    check=rebuilt.merge(wanted,on=groupkeys,how='outer',indicator=True,validate='one_to_one')
    if (check._merge.ne('both').any() or not np.allclose(check.aporte_inferior_mj_km,
            check.aporte_conjunto_condicionado_min_mj_km,rtol=1e-12,atol=1e-12)
            or not np.allclose(check.aporte_superior_mj_km,check.aporte_conjunto_condicionado_max_mj_km,rtol=1e-12,atol=1e-12)):
        raise ErrorFlota('El desglose no reproduce los vectores técnicos completos.')
    technologies=g.groupby(groupkeys+['familia_copert'],as_index=False).agg(
        vehiculos_representados=('vehiculos','sum'),aporte_inferior_mj_km=('aporte_inferior_mj_km','sum'),
        aporte_superior_mj_km=('aporte_superior_mj_km','sum'),separacion_referencias_mj_km=('separacion_referencias_mj_km','sum'))
    g['factor_medio_completo_mj_km']=np.nan
    return {'por_grupo_condicion':g,'por_tecnologia_condicion':technologies}
