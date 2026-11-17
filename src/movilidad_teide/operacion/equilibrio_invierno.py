"""Busco cuotas positivas cercanas sin confundir cantidades y geometría horaria."""
import hashlib,json
import numpy as np
import pandas as pd
from .cuotas_cercanas import catalogo_cercano,metricas_cercania
from .invierno import relojes_de_invierno
from .reloj_integrado import RelojIntegrado
from .refinar_reservas import mejorar_reloj
from .ventana_horaria import cerrar_en_ventana
from .cierre_con_bases import cerrar_reloj_con_bases


class BuscadorEquilibrado:
    """Comparto relojes entre estados con igual número de viajes y ventana.

    El número de viajeros solo cambia la ocupación de cada grupo. La red,
    regulación, plazas y ventanas forman parte explícita de la clave de caché.
    No reutilizo cantidades de pasajeros de otra alternativa.
    """
    def __init__(self,*,max_estados=5000,pasos=1800,configuraciones_refinadas=3):
        self.cache={};self.contexto='';self.max_estados=max_estados;self.pasos=pasos;self.configuraciones_refinadas=configuraciones_refinadas

    def _reloj(self,pt,red,v,q,lim):
        cierres=dict(zip(lim.punto,lim.ultimo_paso_regreso_parque_min))
        op={**v,'intervalo_minimo_subidas_min':15.,'hora_limite_bajada_parque':max(cierres.values())/60}
        return RelojIntegrado(pt,red,op,q,limites_regreso_por_punto=cierres,admitir_accesos_sin_demanda=True)

    def _estado(self,obs,g,q,red,v,lim):
        pt=g.copy();pt['demanda_lanzadera_dia']=pt.demanda_bruta_lanzadera_dia-pt.punto.map(q)*v['ocupacion_coche']
        reloj=self._reloj(pt,red,v,q,lim)
        key=(self.contexto,int(obs),tuple(map(int,reloj.n)),tuple(map(float,reloj.cierres)),float(reloj.inicio),float(reloj.estancia),float(v['regulacion_min']))
        hit=key in self.cache
        if not hit:
            seeds=[];seen=set()
            for ordinary in [15,30]:
                op={**v,'intervalo_minimo_subidas_min':ordinary}
                for score,_,u,b in relojes_de_invierno(pt,red,op,q,lim):
                    fingerprint=tuple(np.concatenate(u+b))
                    if fingerprint in seen:continue
                    seen.add(fingerprint);reloj.validar(u,b)
                    n,e=reloj.evaluar(u,b);seeds.append(((n,-e,score[2]+f'_{ordinary}',score[3]),u,b))
            seeds.sort(key=lambda z:z[0]);self.cache[key]={'semillas':seeds,'curvas':list(seeds),'version':0,'cierre_version':-1,'cerrado':None,'refinado':False}
        return key,reloj,self.cache[key],hit

    def _cerrar(self,key,reloj,state,red,v,caps,ids):
        if state['cierre_version']!=state['version']:
            cs=[(score,reloj,u,b) for score,u,b in state['curvas']]
            state['cerrado']=cerrar_en_ventana(cs,red,reloj.v,caps,ids,inicio_min=420,fin_min=1200)
            if state['cerrado'] is None:state['cerrado']=cerrar_reloj_con_bases(cs,red,reloj.v,caps,ids,inicio=420,fin=1200)
            state['cierre_version']=state['version']
        z=state['cerrado']
        if z is None:return None
        # Repongo las cantidades del caso actual; el testigo previo solo aporta
        # horarios, cadenas e identidades. Los ID y la geometría son iguales.
        groups=z['reservas'].groupby('punto').size().to_dict();demand=reloj.g.set_index('punto').demanda_lanzadera_dia.to_dict()
        trips=z['viajes'].copy();res=z['reservas'].copy();moves=z['movimientos'].copy()
        for p,n in groups.items():res.loc[res.punto.eq(p),'personas']=demand[p]/n
        people={}
        for row in res.itertuples():people[row.id_subida]=row.personas;people[row.id_regreso]=row.personas
        trips['personas']=trips.id_salida.map(people)
        mask=moves.componente.eq('comercial');moves.loc[mask,'personas']=moves.loc[mask,'id_salida'].map(people)
        if trips.personas.isna().any() or moves.loc[mask,'personas'].isna().any() or res.personas.gt(46+1e-8).any():raise ValueError('La caché no conserva pasajeros/plazas del estado actual.')
        return {**z,'viajes':trips,'reservas':res,'movimientos':moves}

    def __call__(self,datos,limites,maximos,red,valores,capacidades,identidades,*,cupo,cuota_previa,semilla):
        routes=[(a,b,red.conectar(a,b)) for a in red.nodos for b in red.nodos]
        context=(routes,red.destinos[['parada_entrada','parada_destino']].to_dict(orient='index'),sorted(capacidades.items()),sorted((b,tuple(i)) for b,i in identidades.items()),[(k,valores[k]) for k in ['plazas_guagua','ocupacion_diseno','ocupacion_coche','regulacion_min','estancia_min_visita_min','hora_inicio_acceso','intervalo_refuerzo_punta_min']])
        self.contexto=hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
        pool,info=catalogo_cercano(datos,limites,maximos,puntos=red.puntos,cupo=cupo,ocupacion=valores['ocupacion_coche'],cuota_previa=cuota_previa,banda=.75)
        if not pool:raise ValueError('No hay estados de cuotas positivas dentro de la banda contrastada.')
        logs=[];refs=[];entries=[]
        for ix,row in enumerate(pool[:self.max_estados]):
            q=dict(zip(red.puntos,row['cuotas']));states={};scores=[];hits=[]
            for obs,g in datos.items():
                key,reloj,state,hit=self._estado(obs,g,q,red,valores,limites[obs]);states[obs]=(key,state);scores.append(state['curvas'][0][0][0]);hits.append(hit)
            distance=row['clave_cercania'];entry={'cuotas':q,'states':states,'distance':distance,'indice':ix,'initial':tuple(scores)};entries.append(entry)
            logs.append({'indice_estado':ix,'cuotas':','.join(map(str,row['cuotas'])),'max_desviacion_relativa':float(distance[0]),'suma_desviaciones_relativas':float(distance[1]),
                'mayor_mejor_catalogo':max(scores),'suma_mejores_catalogos':sum(scores),'estados_geometricos_reutilizados':sum(hits),**{f'mejor_matriz_{o}':n for o,n in zip(datos,scores)}})
            if max(scores)<=27:
                closed={o:self._cerrar(*self._estado(o,datos[o],q,red,valores,limites[o])[:3],red,valores,capacidades,identidades) for o in states}
                if all(z is not None for z in closed.values()):break
        # Refino estados próximos que se quedan a menos vehículos del cierre;
        # las configuraciones con la misma geometría pendiente se evalúan una vez.
        pendientes=sorted(entries,key=lambda z:(max(z['initial']),*z['distance'],sum(z['initial'])))
        selected=[];used=set()
        for e in pendientes:
            signature=tuple(key for key,state in e['states'].values() if state['curvas'][0][0][0]>27)
            if not signature or signature in used:continue
            used.add(signature);selected.append(e)
            if len(selected)==self.configuraciones_refinadas:break
        for e in selected:
            for obs,(key,state) in e['states'].items():
                _,reloj,_,_=self._estado(obs,datos[obs],e['cuotas'],red,valores,limites[obs])
                if state['refinado'] or self._cerrar(key,reloj,state,red,valores,capacidades,identidades) is not None:continue
                base=int(hashlib.sha256(json.dumps(key).encode()).hexdigest()[:8],16)
                for k,(score,u,b) in enumerate(state['semillas'][:2]):
                    seed=247000+base+k
                    # Compruebo bases cuando aparece una geometría de <=27;
                    # no cambio la función de cálculo ni la regla de aceptación.
                    class CierreEncontrado(Exception):pass
                    original=reloj.evaluar;found=[];evaluaciones=[0]
                    def evaluar_con_testigo(us,bs):
                        nn,ee=original(us,bs);evaluaciones[0]+=1
                        if nn<=27:
                            zz=cerrar_reloj_con_bases([((nn,-ee,'refinado_con_bases',float(k)),reloj,us,bs)],red,reloj.v,capacidades,identidades,inicio=420,fin=1200)
                            if zz is not None:
                                found.append((nn,-ee,[a.copy() for a in us],[a.copy() for a in bs]));raise CierreEncontrado
                        return nn,ee
                    reloj.evaluar=evaluar_con_testigo
                    try:
                        try:result,nvalid=mejorar_reloj(reloj,u,b,semilla=seed,pasos=self.pasos)
                        except CierreEncontrado:result=found[0];nvalid=max(0,evaluaciones[0]-1)
                    finally:reloj.evaluar=original
                    n,ne,uu,bb=result
                    state['curvas'].append(((n,ne,'ajuste_individual',float(k)),uu,bb))
                    refs.append({'observacion':obs,'estado_geometrico':repr(key),'reinicio':k,'semilla':seed,'pasos_previstos':self.pasos,'relojes_validos_evaluados':nvalid,'paro_por_testigo':bool(found),'cadenas_inicio':score[0],'mejores_cadenas':n})
                state['curvas'].sort(key=lambda z:z[0]);state['refinado']=True;state['version']+=1
        successes=[]
        for e in entries:
            scores=[state['curvas'][0][0][0] for _,state in e['states'].values()]
            if max(scores)>27:continue
            closed={o:self._cerrar(*self._estado(o,datos[o],e['cuotas'],red,valores,limites[o])[:3],red,valores,capacidades,identidades) for o in e['states']}
            if all(z is not None for z in closed.values()):successes.append((e,closed))
        if successes:
            chosen,closed=min(successes,key=lambda z:(*z[0]['distance'],max(a['programadas'] for a in z[1].values()),tuple(z[0]['cuotas'].values())))
        else:
            chosen=min(entries,key=lambda e:(max(z[1]['curvas'][0][0][0] for z in e['states'].values()),*e['distance']))
            closed={o:self._cerrar(*self._estado(o,datos[o],chosen['cuotas'],red,valores,limites[o])[:3],red,valores,capacidades,identidades) for o in chosen['states']}
        candidates={}
        for o,(key,state) in chosen['states'].items():
            _,reloj,_,_=self._estado(o,datos[o],chosen['cuotas'],red,valores,limites[o])
            candidates[o]=[(score,reloj,u,b) for score,u,b in state['curvas']]
        ns=[cs[0][0][0] for cs in candidates.values()];dist=chosen['distance']
        entry={'clave':(max(ns),sum(ns),float(dist[0])),'cuotas':chosen['cuotas'],'operacion':{**valores,'intervalo_minimo_subidas_min':15.},'candidatos':candidates}
        info.update(estados_horarios_ensayados=len(entries),max_estados_presupuestados=self.max_estados,max_desviacion_elegida=float(dist[0]),suma_desviaciones_elegida=float(dist[1]),
            criterio='Mínima mayor desviación proporcional entre cierres construidos, después suma de desviaciones. Catálogo de cuotas exacto en banda75%; relojes/búsqueda acotados, sin óptimo global.',
            refinamiento={'configuraciones':self.configuraciones_refinadas,'reinicios_por_geometria':2,'pasos_reinicio':self.pasos,'semilla':'247000 +primeros8 hex SHA256 JSON clave geométrica +reinicio'},
            cierre_en_banda=bool(successes))
        return entry,closed,pd.DataFrame(logs),pd.DataFrame(refs),info
