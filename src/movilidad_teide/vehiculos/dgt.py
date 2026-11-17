"""vehiculos: dgt. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
import numpy as np
import pandas as pd
from movilidad_teide.vehiculos.flota_tipos import ErrorFlota


def clasificar_microdatos_parque(tabla, municipios_tenerife, equivalencias):
    """Clasificar campos publicados sin inferir Euro por edad o distintivo.

    CAT_EURO es categoría de homologación (M1, N1...), no norma de emisiones.
    El uso A01 identifica alquiler sin conductor; RENTING no lo sustituye.
    """
    import re
    campos = ['PROVINCIA','MUNICIPIO','TIPO_DGT','CAT_EURO','SERVICIO','RENTING',
              'PROPULSION','CATELECT','ALIMENTACION','TIPO_DISTINTIVO','EMISIONES_EURO','PESO_MAX']
    if not set(campos) <= set(tabla) or not municipios_tenerife:
        raise ErrorFlota('Faltan campos del diseño DGT o la referencia municipal insular.')
    if not all(isinstance(c,str) and len(c)==5 and c.startswith('38') and c.isdigit() for c in municipios_tenerife):
        raise ErrorFlota('Los municipios de Tenerife deben ser códigos INE de cinco cifras de provincia 38.')
    t=tabla[campos].copy().fillna('')
    for c in campos:t[c]=t[c].astype(str).str.strip()
    if not t.PROVINCIA.eq('38').all():
        raise ErrorFlota('El fichero debe corresponder íntegramente a Santa Cruz de Tenerife, provincia 38.')
    t['ambito_geografico']=np.select([t.MUNICIPIO.isin(municipios_tenerife),t.MUNICIPIO.eq('')],
        ['Tenerife identificado','Municipio no publicado'],default='Otras islas de la provincia')
    t['grupo_servicio']=np.select([t.SERVICIO.eq('A01'),t.SERVICIO.eq('B00')],
        ['Alquiler sin conductor (A01)','Particular sin especificar (B00)'],default='Otros servicios o sin código')

    def norma(valor):
        # Normalizar espacios y el separador documentado EURO6-AG, nunca letras internas o signos de igualdad.
        limpio=re.sub(r'\s+','',valor.upper())
        limpio=re.sub(r'^EURO6-([A-Z]{2})$',r'EURO6\1',limpio)
        referencia=equivalencias.get(limpio)
        if referencia is None:return ('','Ausente' if not limpio else 'Sin equivalencia revisada')
        if isinstance(referencia,dict):referencia=referencia.get('euro_copert','')
        if referencia not in {'Euro 1','Euro 2','Euro 3','Euro 4','Euro 5','Euro 6 a/b/c','Euro 6 d-temp','Euro 6 d/e'}:
            raise ErrorFlota('Equivalencia Euro no admitida o ambigua; no elegir una subclase por defecto.')
        return (referencia,'Correspondencia documentada')
    normalizadas=t.EMISIONES_EURO.map(norma)
    t['euro_copert']=[v[0] for v in normalizadas]
    t['estado_euro']=[v[1] for v in normalizadas]
    t.loc[t.EMISIONES_EURO.str.replace(' ','').str.upper().eq('EURO6'),'estado_euro']='Euro 6 sin subclase: no repartir'
    t['categoria_turismo_compatible']=t.CAT_EURO.isin(['M1','M1G'])

    def tecnologia(row):
        prop,elec,alimentacion,distintivo=row
        # Conservar contradicciones y combinaciones sin correspondencia; no reasignar ni renormalizar.
        if elec=='HEV' and prop in {'0','1','G','D'}:
            return ('Petrol Hybrid' if prop in {'0','G'} else '', 'HEV gasolina' if prop in {'0','G'} else 'HEV diésel sin clave directa')
        if elec=='PHEV' and prop in {'0','1','G','D'}:
            return ('Petrol PHEV' if prop in {'0','G'} else 'Diesel PHEV','PHEV publicado')
        if elec=='BEV' and prop=='2':return ('Battery electric','BEV publicado')
        if elec:return ('','Categoría eléctrica/propulsión sin correspondencia revisada')
        if prop in {'0','1','G','D'} and alimentacion in {'','0','M'} and distintivo not in {'ECO','CERO'}:
            return ('Petrol' if prop in {'0','G'} else 'Diesel','Sin categoría eléctrica informada; no acredita ausencia de error registral')
        if prop in {'6','7'} and alimentacion=='B':
            return ('LPG Bifuel' if prop=='6' else 'CNG Bifuel','Bifuel publicado')
        return ('','Tecnología o alimentación sin correspondencia revisada')
    tecnologias=[tecnologia(row) for row in t[['PROPULSION','CATELECT','ALIMENTACION','TIPO_DISTINTIVO']].itertuples(index=False,name=None)]
    t['familia_copert']=[v[0] for v in tecnologias];t['estado_tecnologia']=[v[1] for v in tecnologias]
    # Una norma de escape publicada en un BEV no identifica su generación de consumo eléctrico.
    t['norma_para_factor_compatible']=t.euro_copert.ne('') & t.familia_copert.ne('Battery electric')
    return t

def agregar_microdatos_parque(bloques, municipios_tenerife, equivalencias):
    """Agregar registros reales manteniendo ausencias y ámbitos separados.

    Devuelve conteos, no registros de vehículos ni pesos de actividad del Teide.
    Dos filas iguales en las variables elegidas siguen siendo dos vehículos.
    """
    coberturas,cruces,buses=[],[],[]
    claves=['ambito_geografico','grupo_servicio','SERVICIO','RENTING','CAT_EURO',
            'categoria_turismo_compatible','PROPULSION','CATELECT','ALIMENTACION','TIPO_DISTINTIVO',
            'familia_copert','estado_tecnologia','EMISIONES_EURO','euro_copert','estado_euro','norma_para_factor_compatible']
    for bloque in bloques:
        t=clasificar_microdatos_parque(bloque,municipios_tenerife,equivalencias)
        coberturas.append(t.groupby(['ambito_geografico','TIPO_DGT'],dropna=False).size().rename('vehiculos').reset_index())
        coches=t.loc[t.TIPO_DGT.eq('TURISMOS')]
        cruces.append(coches.groupby(claves,dropna=False).size().rename('vehiculos').reset_index())
        guaguas=t.loc[t.TIPO_DGT.eq('AUTOBUSES')].copy()
        masa=pd.to_numeric(guaguas.PESO_MAX,errors='coerce')
        guaguas['intervalo_mma']=np.select([masa.gt(0)&masa.le(15000),masa.gt(15000)&masa.le(18000),masa.gt(18000)],
            ['Hasta 15 t','Más de 15 hasta 18 t','Más de 18 t'],default='MMA ausente o no válida')
        buses.append(guaguas.groupby(['ambito_geografico','SERVICIO','RENTING','CAT_EURO','PROPULSION','CATELECT',
            'EMISIONES_EURO','intervalo_mma'],dropna=False).size().rename('vehiculos').reset_index())
    if not coberturas or sum(x.vehiculos.sum() for x in coberturas)==0:
        raise ErrorFlota('El fichero de microdatos está vacío.')
    def reunir(partes):
        tabla=pd.concat(partes,ignore_index=True)
        grupos=[c for c in tabla if c!='vehiculos']
        return tabla.groupby(grupos,dropna=False,as_index=False).vehiculos.sum().sort_values(grupos).reset_index(drop=True)
    return {'cobertura':reunir(coberturas),'turismos':reunir(cruces),'guaguas':reunir(buses)}

def leer_microdatos_parque(path, municipios_tenerife, equivalencias, *, chunksize=100000):
    """Leer el TXT DGT original por bloques, sin modificar ni cargar modelos personales."""
    if isinstance(chunksize,bool) or not isinstance(chunksize,int) or chunksize<=0:
        raise ErrorFlota('El tamaño de lectura debe ser un entero positivo.')
    campos=['PROVINCIA','MUNICIPIO','TIPO_DGT','CAT_EURO','SERVICIO','RENTING',
            'PROPULSION','CATELECT','ALIMENTACION','TIPO_DISTINTIVO','EMISIONES_EURO','PESO_MAX']
    with pd.read_csv(path,sep='|',encoding='cp1252',dtype=str,keep_default_na=False,
                     usecols=campos,chunksize=chunksize) as lector:
        return agregar_microdatos_parque(lector,municipios_tenerife,equivalencias)

def leer_taras_turismos_dgt(path, municipios_tenerife, equivalencias, *, chunksize=100000):
    """Resumir tara registral sin convertirla en masa cargada o pesos por actividad."""
    fields=['PROVINCIA','MUNICIPIO','TIPO_DGT','CAT_EURO','SERVICIO','RENTING',
            'PROPULSION','CATELECT','ALIMENTACION','TIPO_DISTINTIVO','EMISIONES_EURO','PESO_MAX','TARA']
    pieces=[]
    with pd.read_csv(path,sep='|',encoding='cp1252',dtype=str,keep_default_na=False,
                     usecols=fields,chunksize=chunksize) as reader:
        for raw in reader:
            classified=clasificar_microdatos_parque(raw,municipios_tenerife,equivalencias)
            mask=classified.TIPO_DGT.eq('TURISMOS');cars=classified.loc[mask].copy()
            if cars.empty:continue
            tara=pd.to_numeric(raw.loc[mask,'TARA'],errors='coerce').to_numpy(dtype=float)
            mma=pd.to_numeric(raw.loc[mask,'PESO_MAX'],errors='coerce').to_numpy(dtype=float)
            positive=np.isfinite(tara)&(tara>0)&(tara%1==0)
            inconsistent=positive&np.isfinite(mma)&(mma>0)&(tara>mma)
            cars['estado_tara']=np.select([~positive,inconsistent],
                ['Ausente/no positiva/no entera','Tara superior a MMA declarada'],default='Tara positiva sin contradicción con MMA disponible')
            cars['tara_utilizable_kg']=np.where(positive&~inconsistent,tara,np.nan)
            pieces.append(cars[['ambito_geografico','grupo_servicio','familia_copert','estado_tecnologia',
                                'euro_copert','estado_euro','categoria_turismo_compatible','estado_tara','tara_utilizable_kg']])
    if not pieces:raise ErrorFlota('La fuente no contiene registros de turismo.')
    cars=pd.concat(pieces,ignore_index=True)
    groups=['ambito_geografico','grupo_servicio','familia_copert','estado_tecnologia',
            'euro_copert','estado_euro','categoria_turismo_compatible']
    summary=cars.groupby(groups,dropna=False,as_index=False).agg(
        registros_turismos=('tara_utilizable_kg','size'),registros_tara_utilizable=('tara_utilizable_kg','count'),
        tara_media_kg=('tara_utilizable_kg','mean'),tara_mediana_kg=('tara_utilizable_kg','median'),
        tara_p25_kg=('tara_utilizable_kg',lambda s:s.quantile(.25)),
        tara_p75_kg=('tara_utilizable_kg',lambda s:s.quantile(.75)))
    summary['alcance_masa']='Tara registral; no masa con pasajeros/equipaje, segmento COPERT o peso por vehículos-km'
    controls=cars.groupby(groups+['estado_tara'],dropna=False).size().rename('registros').reset_index()
    if int(summary.registros_turismos.sum())!=len(cars) or int(controls.registros.sum())!=len(cars):
        raise ErrorFlota('La revisión de tara no conserva los registros.')
    return summary,controls

def vincular_taras_a_perfiles(taras, perfiles):
    """Vincular referencias D087 con tara del mismo perfil, sin crear pesos de viaje.

    La cobertura conserva todos los registros, incluidos otros territorios,
    categorías incompatibles y perfiles no representados por la selección.
    """
    keys=['grupo_servicio','familia_copert','euro_copert']
    required=set(keys+['ambito_geografico','categoria_turismo_compatible',
        'registros_turismos','registros_tara_utilizable','tara_mediana_kg','tara_p25_kg','tara_p75_kg'])
    if not required<=set(taras) or not set(keys+['vehiculos'])<=set(perfiles):
        raise ErrorFlota('Faltan campos para vincular los perfiles y sus taras.')
    if perfiles.empty or perfiles[keys].isna().any().any() or perfiles.duplicated(keys).any():
        raise ErrorFlota('Los perfiles deben ser completos, no vacíos y únicos.')
    out=taras.copy(deep=True)
    selected=set(map(tuple,perfiles[keys].to_numpy()))
    # Solo Tenerife identificado y categoría compatible; no reasignar los demás.
    eligible=out.ambito_geografico.eq('Tenerife identificado') & out.categoria_turismo_compatible.eq(True)
    out['perfil_referencia_seleccionado']=[bool(ok and tuple(v) in selected)
        for ok,v in zip(eligible,out[keys].to_numpy(),strict=True)]
    matched=out.loc[out.perfil_referencia_seleccionado]
    if matched.duplicated(keys).any():
        raise ErrorFlota('Varias distribuciones de tara para un mismo perfil; no promediar cuantiles.')
    refs=perfiles.merge(matched,on=keys,how='left',validate='one_to_one',indicator=True)
    if (refs['_merge'].ne('both').any()
            or not refs.vehiculos.eq(refs.registros_turismos).all()):
        raise ErrorFlota('El perfil y la distribución de tara no coinciden en ámbito o conteo.')
    refs=refs.drop(columns='_merge')
    for col in ['registros_turismos','registros_tara_utilizable']:
        v=pd.to_numeric(refs[col],errors='coerce')
        if not np.isfinite(v).all() or v.le(0).any() or v.mod(1).ne(0).any():
            raise ErrorFlota('Cada referencia necesita soporte y tara utilizable documentados.')
    q=refs[['tara_p25_kg','tara_mediana_kg','tara_p75_kg']].to_numpy(dtype=float)
    if (not np.isfinite(q).all() or (q<=0).any() or (np.diff(q,axis=1)<0).any()
            or refs.registros_tara_utilizable.gt(refs.registros_turismos).any()):
        raise ErrorFlota('Distribución de tara no válida o conteos incompatibles.')
    refs['alcance_referencia']='Perfil fiscal propuesto; no peso visitante, tamaño COPERT o cuota por actividad'
    return refs,out

def leer_modelos_turismos_dgt(path, municipios_tenerife, equivalencias, *, chunksize=100000):
    """Agregar marca/modelo con tecnología y norma del mismo registro DGT.

    Solo conserva conteos de turismos identificados en Tenerife. No publica
    registros individuales ni cruza marginales independientes para fabricar tamaños.
    """
    if isinstance(chunksize,bool) or not isinstance(chunksize,int) or chunksize<=0:
        raise ErrorFlota('El tamaño de lectura debe ser un entero positivo.')
    campos=['PROVINCIA','MUNICIPIO','TIPO_DGT','CAT_EURO','SERVICIO','RENTING',
        'PROPULSION','CATELECT','ALIMENTACION','TIPO_DISTINTIVO','EMISIONES_EURO','PESO_MAX']
    claves=['ambito_geografico','grupo_servicio','SERVICIO','RENTING','CAT_EURO',
        'categoria_turismo_compatible','PROPULSION','CATELECT','ALIMENTACION','TIPO_DISTINTIVO',
        'familia_copert','estado_tecnologia','EMISIONES_EURO','euro_copert','estado_euro',
        'norma_para_factor_compatible','MARCA','MODELO']
    partes=[]
    with pd.read_csv(path,sep='|',encoding='cp1252',dtype=str,keep_default_na=False,
                     usecols=campos+['MARCA','MODELO'],chunksize=chunksize) as lector:
        for bloque in lector:
            t=clasificar_microdatos_parque(bloque,municipios_tenerife,equivalencias)
            # Guardar los nombres publicados sin corregirlos con un diccionario comercial.
            t['MARCA']=bloque.MARCA;t['MODELO']=bloque.MODELO
            t=t.loc[t.TIPO_DGT.eq('TURISMOS')&t.ambito_geografico.eq('Tenerife identificado')]
            partes.append(t.groupby(claves,dropna=False).size().rename('vehiculos').reset_index())
    if not partes or sum(x.vehiculos.sum() for x in partes)==0:
        raise ErrorFlota('No hay turismos identificados en Tenerife en el fichero.')
    return pd.concat(partes,ignore_index=True).groupby(claves,dropna=False,as_index=False).vehiculos.sum()

def clasificar_tamanos_turismos(modelos, correspondencias, catalogo):
    """Proponer segmento por familia comercial documentada, conservando dudas.

    Las fuentes y las exclusiones pertenecen al diccionario técnico; ningún
    tamaño, peso de actividad o parámetro de escenario se adopta aquí.
    """
    import re
    import unicodedata
    if not {'MARCA','MODELO','vehiculos'}<=set(modelos) or modelos.empty:
        raise ErrorFlota('Faltan modelos publicados o sus conteos.')
    n=pd.to_numeric(modelos.vehiculos,errors='coerce')
    if not np.isfinite(n).all() or n.le(0).any() or n.mod(1).ne(0).any():
        raise ErrorFlota('Los modelos deben conservar conteos enteros positivos.')
    if not {'Category','Segment'}<=set(catalogo):raise ErrorFlota('Falta el catálogo de tamaños nativos.')
    sizes=set(catalogo.loc[catalogo.Category.eq('Passenger Cars'),'Segment'])
    if correspondencias.get('version')!=1 or not correspondencias.get('fuente_id'):
        raise ErrorFlota('Diccionario sin versión o referencia de fuentes.')
    rules=correspondencias.get('reglas',[])
    if not rules or len({x.get('id') for x in rules})!=len(rules):
        raise ErrorFlota('Las reglas deben ser identificadas, únicas y no vacías.')
    def norm(text):
        # Normalizar solo mayúsculas, acentos y espacios; no borrar sufijos de variantes.
        if pd.isna(text):return ''
        return ' '.join(''.join(c for c in unicodedata.normalize('NFKD',str(text))
            if not unicodedata.combining(c)).upper().split())
    compiled=[]
    for rule in rules:
        required=['id','marcas','modelo_regex','excluir_regex','segmento_fuente',
            'segmento_copert_propuesto','fuente_modelo','fuente_puente','alcance']
        if any(not rule.get(k) for k in required) or rule['segmento_copert_propuesto'] not in sizes:
            raise ErrorFlota('Regla sin fuente, alcance o tamaño de catálogo compatible.')
        if not isinstance(rule['marcas'],list) or any(not isinstance(m,str) or not norm(m) for m in rule['marcas']):
            raise ErrorFlota('Las marcas de una regla deben ser explícitas.')
        if not rule['modelo_regex'].startswith('^'):
            raise ErrorFlota('Las reglas deben empezar en el inicio del nombre, sin búsqueda difusa.')
        try:pat=re.compile(rule['modelo_regex']);exc=re.compile(rule['excluir_regex'])
        except (re.error,TypeError) as error:raise ErrorFlota('Expresión de modelo no válida.') from error
        compiled.append((rule,{norm(m) for m in rule['marcas']},pat,exc))
    cache={}
    def identify(marca,modelo):
        key=(norm(marca),norm(modelo))
        if key in cache:return cache[key]
        fields=dict(regla_tamano='',segmento_fuente='',segmento_copert_propuesto='',fuente_modelo='',fuente_puente='')
        if not all(key) or any('¡' in v or v in {'ND','N/D','NO CONSTA'} for v in key):
            estado='Marca o modelo no identificable'
        else:
            matches=[];excluded=False
            for rule,brands,pat,exc in compiled:
                if key[0] in brands and pat.search(key[1]):
                    if exc.search(key[1]):excluded=True
                    else:matches.append(rule)
            if len(matches)>1:raise ErrorFlota('Más de una regla aplicable al mismo modelo; revisar la ambigüedad.')
            if matches:
                rule=matches[0]
                fields.update(regla_tamano=rule['id'],**{k:rule[k] for k in fields if k!='regla_tamano'})
                estado='Correspondencia de familia propuesta; sin adoptar'
            else:estado='Variante excluida para revisión' if excluded else 'Modelo sin correspondencia revisada'
        result={**fields,'estado_tamano':estado};cache[key]=result
        return result
    annotations=pd.DataFrame([identify(a,b) for a,b in modelos[['MARCA','MODELO']].itertuples(index=False,name=None)])
    if set(annotations)&set(modelos):raise ErrorFlota('La entrada ya contiene una asignación de tamaño.')
    result=modelos.reset_index(drop=True).copy(deep=True)
    result['vehiculos']=n.to_numpy(dtype='int64')
    return pd.concat([result,annotations],axis=1)

def resumir_tamanos_turismos(modelos, perfiles, catalogo):
    """Conciliar tamaño propuesto y factores sin perder el denominador del stock.

    Tener tamaño no acredita norma/factores; tener factores no resuelve tamaño.
    No calcula pesos de actividad ni un consumo completo con desconocidos.
    """
    keys=['grupo_servicio','familia_copert','euro_copert','CAT_EURO','EMISIONES_EURO','categoria_turismo_compatible']
    wanted=keys+['vehiculos','segmento_copert_propuesto','estado_tamano']
    if not set(wanted)<=set(modelos) or not set(keys+['vehiculos','representado'])<=set(perfiles):
        raise ErrorFlota('Faltan tamaños o perfiles completos de representación.')
    m=modelos.copy(deep=True);p=perfiles[keys+['vehiculos','representado']].copy(deep=True)
    for tabla in (m,p):
        for c in keys[:-1]:tabla[c]=tabla[c].fillna('')
        if not tabla.categoria_turismo_compatible.map(lambda v:isinstance(v,(bool,np.bool_))).all():
            raise ErrorFlota('La compatibilidad de categoría debe ser booleana.')
        nums=pd.to_numeric(tabla.vehiculos,errors='coerce')
        if not np.isfinite(nums).all() or nums.le(0).any() or nums.mod(1).ne(0).any():
            raise ErrorFlota('Conteos no válidos para conciliar tamaños y factores.')
    if not p.representado.map(lambda v:isinstance(v,(bool,np.bool_))).all():
        raise ErrorFlota('La representación de factores debe ser booleana.')
    if p.duplicated(keys).any():raise ErrorFlota('Perfiles de factores repetidos.')
    counts=m.groupby(keys,dropna=False).vehiculos.sum().sort_index()
    original=p.set_index(keys).vehiculos.sort_index()
    if not counts.index.equals(original.index) or not np.array_equal(counts.to_numpy(),original.to_numpy()):
        raise ErrorFlota('Los modelos no conservan los conteos conjuntos originales de cada perfil.')
    detail=m.merge(p.drop(columns='vehiculos'),on=keys,how='left',validate='many_to_one')
    detail['tamano_propuesto']=detail.segmento_copert_propuesto.fillna('').ne('')
    native=['Category','Fuel','Segment','Euro Standard']
    if not set(native)<=set(catalogo):raise ErrorFlota('Faltan las claves nativas completas del catálogo.')
    car=catalogo.loc[catalogo.Category.eq('Passenger Cars')]
    available=set(car[['Fuel','Segment','Euro Standard']].itertuples(index=False,name=None))
    def compatible(row):
        fuel,size,euro,literal=row
        equiv=fuel=='Battery electric' or (not euro and str(literal).replace(' ','').upper()=='EURO6')
        normas=['Euro 6 a/b/c','Euro 6 d-temp','Euro 6 d/e'] if equiv else [euro]
        return bool(size) and all((fuel,size,norma) in available for norma in normas)
    detail['tamano_disponible_perfil']=[compatible(row) for row in detail[[
        'familia_copert','segmento_copert_propuesto','euro_copert','EMISIONES_EURO']].fillna('').itertuples(index=False,name=None)]
    detail['tamano_y_factores']=detail.tamano_propuesto&detail.representado&detail.tamano_disponible_perfil
    rows=[]
    for service,g in detail.groupby('grupo_servicio',sort=True):
        total=int(g.vehiculos.sum());sized=int(g.loc[g.tamano_propuesto,'vehiculos'].sum())
        both=int(g.loc[g.tamano_y_factores,'vehiculos'].sum())
        rows.append({'grupo_servicio':service,'vehiculos_stock':total,'vehiculos_tamano_propuesto':sized,
            'vehiculos_sin_tamano':total-sized,'vehiculos_tamano_y_factores':both,
            'fraccion_stock_tamano_propuesto':sized/total,'fraccion_stock_tamano_y_factores':both/total,
            'estado':'Correspondencias propuestas sobre stock; sin actividad, media completa o flota Teide elegidas'})
    # Incluye el tamaño pendiente: las cuotas de tamaños conocidos no se elevan a uno.
    by_size=detail.assign(tamano_resumen=detail.segmento_copert_propuesto.fillna('').replace('','Pendiente'))
    by_size=by_size.groupby(['grupo_servicio','tamano_resumen','estado_tamano'],as_index=False).vehiculos.sum()
    totals=detail.groupby('grupo_servicio').vehiculos.sum()
    by_size['fraccion_stock_servicio']=by_size.vehiculos/by_size.grupo_servicio.map(totals)
    return {'detalle':detail,'resumen':pd.DataFrame(rows),'por_tamano':by_size}
