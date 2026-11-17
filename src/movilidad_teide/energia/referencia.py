"""Referencia de consumo ponderada por información DGT identificada."""
from copy import deepcopy
import numpy as np
import pandas as pd
from movilidad_teide.opciones import CRITERIOS_MEZCLA as CRITERIOS
from movilidad_teide.energia.mezcla import verificar_entradas_mezcla, estimar_resto_turismos
from movilidad_teide.energia.compatibilidad import verificar_representacion_tecnica
from movilidad_teide.opciones import METODO_CONSUMO as METODO


NUEVOS = {'criterio_consumo_representativo', 'control_primario_referencia'}


def verificar_referencia(anterior, actual):
    old = {p['id']:p for p in anterior['parametros']}
    new = {p['id']:p for p in actual['parametros']}
    if set(old)&NUEVOS or not NUEVOS <= set(new)-set(old):
        raise ValueError('Faltan las dos adiciones de referencia de consumo.')
    if new['criterio_consumo_representativo']['valor_utilizado'] != METODO:
        raise ValueError('Método de consumo sin elegir.')
    control = new['control_primario_referencia']['valor_utilizado']
    if control is None or not np.isfinite(control) or not 0 <= control <= 1:
        raise ValueError('Control técnico no válido.')
    for key in NUEVOS:
        if new[key]['modo_efectivo'] != 'Manual' or not new[key]['justificacion_utilizada'].strip():
            raise ValueError('Falta elección justificada de referencia.')
    projected = deepcopy(actual)
    projected['parametros'] = [p for p in projected['parametros'] if p['id'] not in NUEVOS]
    projected['elecciones_todos_los_casos'] = [p for p in projected['elecciones_todos_los_casos'] if p['id'] not in NUEVOS]
    validator = verificar_representacion_tecnica if set(CRITERIOS) <= set(old) else verificar_entradas_mezcla
    return validator(anterior, projected) | {'criterios_referencia_aplicados_aparte':sorted(NUEVOS)}


def referencia_ponderada(diagnostico, biblioteca, resumen, *, metodo, control_primario):
    """Conservar atributos conocidos y estimar solo dimensiones sin identificar.

    Las frecuencias de tamaños/normas proceden de grupos DGT con ambos atributos
    identificados. No se promedian los dos vectores técnicos de consumo extremos.
    """
    if metodo != METODO or control_primario is None or not np.isfinite(control_primario) or not 0 <= control_primario <= 1:
        raise ValueError('Elegir método y control técnico entre cero y uno.')
    d = diagnostico.copy(deep=True)
    if d.grupo_id.duplicated().any() or d.vehiculos.le(0).any() or not np.isfinite(d.vehiculos).all():
        raise ValueError('Grupos o cantidades inválidos.')
    for col in ['familia_copert','euro_copert','EMISIONES_EURO','segmento_copert_propuesto']:
        d[col] = d[col].fillna('')
    d['curva_documentada'] = d.euro_copert
    equivalent = d.familia_copert.eq('Battery electric') | (d.euro_copert.eq('') & d.EMISIONES_EURO.str.replace(' ','').str.upper().eq('EURO6'))
    # La equivalencia de estas curvas ya fue comprobada en D149; no asigno una norma original.
    d.loc[equivalent,'curva_documentada'] = 'Euro 6 a/b/c'
    covered = d.representado_en_contraste | d.referencia_condicionada_disponible
    if (d.representado_en_contraste & d.referencia_condicionada_disponible).any():
        raise ValueError('Cobertura duplicada.')
    b = biblioteca.loc[biblioteca.Category.eq('Passenger Cars')].copy()
    b['primary_control_fraction'] = b.primary_control_fraction.fillna(-1.)
    keys = ['Fuel','Segment','Euro Standard','driving_mode','speed_kmh','primary_control_fraction']
    if b.duplicated(keys).any() or not np.isfinite(b.hot_ec_mj_per_km).all() or b.hot_ec_mj_per_km.lt(0).any():
        raise ValueError('Curvas nativas repetidas o factores inválidos.')
    conditions = set(map(tuple,resumen[['modo','velocidad_kmh']].drop_duplicates().to_numpy()))
    bifuel = {'LPG Bifuel','CNG Bifuel','Petrol PHEV','Diesel PHEV'}
    native = {}; omitted = []
    for identity,g in b.groupby(['Fuel','Segment','Euro Standard']):
        fuel,size,euro = identity
        controls = [0.,1.] if fuel in bifuel else [-1.]
        expected = {(m,v,c) for m,v in conditions for c in controls}
        actual = set(map(tuple,g[['driving_mode','speed_kmh','primary_control_fraction']].to_numpy()))
        if actual != expected:
            omitted.append(identity);continue
        if fuel in bifuel and (not g.linearity_verified.fillna(False).all()):
            raise ValueError('No está acreditada la mezcla lineal del control nativo.')
        native[identity] = g.set_index(['driving_mode','speed_kmh','primary_control_fraction']).hot_ec_mj_per_km.to_dict()
    donors = d.loc[covered & d.usa_tamano_propuesto & d.curva_documentada.ne('')].copy()
    donors = donors.loc[[tuple(x) in native for x in donors[['familia_copert','segmento_copert_propuesto','curva_documentada']].itertuples(index=False,name=None)]]
    donor_fields = ['grupo_id','grupo_servicio','familia_copert','segmento_copert_propuesto','curva_documentada','vehiculos']
    donors = donors[donor_fields]
    totals = d.groupby('grupo_servicio').vehiculos.sum()
    assignments = [];profiles = [];proof = []
    for row in d.loc[covered].to_dict('records'):
        fuel = row['familia_copert']
        size = row['segmento_copert_propuesto'] if row['usa_tamano_propuesto'] else ''
        euro = row['curva_documentada']
        candidates = [k for k in native if k[0]==fuel and (not size or k[1]==size) and (not euro or k[2]==euro)]
        if not candidates:raise ValueError('Un perfil representado ha perdido sus curvas compatibles.')
        unknown = ([] if size else ['segmento_copert_propuesto']) + ([] if euro else ['curva_documentada'])
        chosen = None;method = 'Características identificadas';retained = 1.;donor_n = 0
        candidate_projection = {k:tuple({'segmento_copert_propuesto':k[1],'curva_documentada':k[2]}[a] for a in unknown) for k in candidates}
        if not unknown:
            if len(candidates)!=1:raise ValueError('Características identificadas con más de una curva.')
            probabilities = {candidates[0]:1.}
        else:
            pool = donors.loc[donors.familia_copert.eq(fuel)]
            matched = pool
            if size:matched = matched.loc[matched.segmento_copert_propuesto.eq(size)]
            if euro:matched = matched.loc[matched.curva_documentada.eq(euro)]
            tiers = [('Mismo servicio y atributos conocidos',matched.loc[matched.grupo_servicio.eq(row['grupo_servicio'])]),
                ('Mismo servicio y combustible',pool.loc[pool.grupo_servicio.eq(row['grupo_servicio'])]),
                ('Mismo combustible y atributos conocidos en otros servicios',matched),
                ('Mismo combustible en otros servicios',pool)]
            for label,pool_tier in tiers:
                if pool_tier.empty:continue
                distribution = pool_tier.groupby(unknown).vehiculos.sum()
                distribution.index = pd.MultiIndex.from_tuples([i if isinstance(i,tuple) else (i,) for i in distribution.index],names=unknown)
                mass = {k:float(distribution.get(candidate_projection[k],0.)) for k in candidates}
                total_mass = sum(mass.values())
                if total_mass:
                    probabilities = {k:v/total_mass for k,v in mass.items() if v>0}
                    method = label;chosen = pool_tier;donor_n = int(total_mass)
                    retained = total_mass/float(pool_tier.vehiculos.sum());break
            else:
                probabilities = {k:1./len(candidates) for k in candidates}
                method = 'Reparto técnico uniforme de curvas completas; sin frecuencias DGT compatibles'
                retained = np.nan
        if not np.isclose(sum(probabilities.values()),1.,rtol=1e-12):raise ValueError('Pesos de curvas no conservados.')
        for key,weight in probabilities.items():
            assignments.append({'grupo_id':row['grupo_id'],'grupo_servicio':row['grupo_servicio'],
                'familia_copert':fuel,'segmento_nativo':key[1],'norma_curva_nativa':key[2],'peso_curva':weight,
                'metodo_ponderacion':method,'vehiculos_receptores':row['vehiculos'],'cantidad_donantes_compatibles':donor_n,
                'fraccion_masa_donantes_compatible':retained})
        if chosen is not None:
            allowed=set(candidate_projection[k] for k in probabilities)
            selected=chosen.loc[[tuple(x) in allowed for x in chosen[unknown].itertuples(index=False,name=None)]]
            for donor in selected.to_dict('records'):
                proof.append({'grupo_id_receptor':row['grupo_id'],'grupo_id_donante':donor['grupo_id'],
                    'vehiculos_donantes':donor['vehiculos'],'peso_donante':donor['vehiculos']/donor_n,'metodo':method})
        for mode,speed in sorted(conditions):
            energy=0.
            for key,weight in probabilities.items():
                native_f=native[key]
                factor=((1-control_primario)*native_f[mode,speed,0.]+control_primario*native_f[mode,speed,1.]) if fuel in bifuel else native_f[mode,speed,-1.]
                energy+=weight*factor
            profiles.append({'grupo_id':row['grupo_id'],'grupo_servicio':row['grupo_servicio'],'familia_copert':fuel,
                'modo':mode,'velocidad_kmh':speed,'vehiculos':row['vehiculos'],
                'factor_inferior_mj_km':energy,'factor_superior_mj_km':energy,
                'metodo_ponderacion':method,'peso_stock_original':row['vehiculos']/totals[row['grupo_servicio']]})
    profiles=pd.DataFrame(profiles)
    profiles['aporte_referencia_mj_km']=profiles.factor_inferior_mj_km*profiles.peso_stock_original
    grouped=profiles.groupby(['grupo_servicio','modo','velocidad_kmh']).aporte_referencia_mj_km.sum()
    base=resumen.copy()
    for side in ['min','max']:
        base['aporte_conjunto_condicionado_'+side+'_mj_km']=[grouped.loc[(x.grupo_servicio,x.modo,x.velocidad_kmh)] for x in base.itertuples()]
    residual=estimar_resto_turismos(d,profiles,base,criterio=CRITERIOS['criterio_sustitucion_turismos'])
    return {'factores':residual['factores'],'perfiles_referencia':profiles,'pesos_curvas':pd.DataFrame(assignments),
        'donantes_identificados':donors,'donantes_utilizados':pd.DataFrame(proof),
        'sustituciones':residual['sustituciones'],'donantes_sustitucion':residual['donantes'],
        'claves_incompletas_excluidas':pd.DataFrame(omitted,columns=['Fuel','Segment','Euro Standard'])}
