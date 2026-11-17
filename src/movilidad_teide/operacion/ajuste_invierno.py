"""Busco cuotas y relojes de invierno con un presupuesto explícito."""
from itertools import product
import math
import numpy as np
import pandas as pd
from .invierno import relojes_de_invierno
from .refinar_reservas import mejorar_reloj
from .ventana_horaria import cerrar_en_ventana


def catalogo_invierno(datos,limites,maximos,*,puntos,cupo,ocupacion,cuota_previa):
    """Rejilla de25 coches, extremos y cuota previa; colapso estados de viajes.

    Dos cuotas equivalentes para ambos perfiles construyen los mismos relojes.
    Conservo la más próxima a la cuota previa, sin modificar las poblaciones.
    """
    upper=np.array([min(cupo,math.floor(maximos[p]+1e-10)) for p in puntos]);prev=np.array([cuota_previa[p] for p in puntos])
    lower=np.zeros(len(puntos),dtype=int)
    for obs,g in datos.items():
        lim=limites[obs].set_index('punto').loc[puntos]
        bruto=g.set_index('punto').loc[puntos].demanda_bruta_lanzadera_dia.to_numpy()
        lower=np.maximum(lower,np.maximum(0,np.ceil((bruto-lim.capacidad_maxima_intervalo_personas.to_numpy())/ocupacion-1e-10)).astype(int))
    axes=[sorted({*range(int(lo),int(hi)+1,25),int(hi),int(np.clip(q,lo,hi))}) if lo<=hi else [] for lo,hi,q in zip(lower,upper,prev)]
    states={}
    for abc in product(*axes[:3]):
        qq=(*abc,cupo-sum(abc))
        if not lower[3]<=qq[3]<=upper[3]:continue
        signature=[];work=[];valid=True
        for obs,g in datos.items():
            lim=limites[obs].set_index('punto').loc[puntos]
            bruto=g.set_index('punto').loc[puntos].demanda_bruta_lanzadera_dia.to_numpy();net=bruto-np.array(qq)*ocupacion
            n=np.ceil((net-1e-8)/46).astype(int)
            if (net<0).any() or (n>lim.maximo_salidas_intervalo.to_numpy()).any():valid=False;break
            signature.extend(n);work.append(float(n@(lim.tiempo_subida_min.to_numpy()+lim.tiempo_descenso_min.to_numpy()+20)))
        if not valid:continue
        key=tuple(signature);distance=int(np.abs(np.array(qq)-prev).sum())
        row={'cuotas':qq,'distancia_cuota':distance,'trabajo_proxy':max(work),'suma_viajes':sum(signature),'firma':key}
        if key not in states or (distance,qq)<(states[key]['distancia_cuota'],states[key]['cuotas']):states[key]=row
    rows=list(states.values());selected={}
    for orden in [('distancia_cuota','trabajo_proxy'),('trabajo_proxy','distancia_cuota'),('suma_viajes','distancia_cuota')]:
        for row in sorted(rows,key=lambda z:(z[orden[0]],z[orden[1]],z['cuotas']))[:24]:selected[row['cuotas']]=row
    return list(selected),{'estados_distintos_rejilla':len(rows),'cuotas_seleccionadas':len(selected),'minimos_intervalo':dict(zip(puntos,map(int,lower))),'maximos_elegibles':dict(zip(puntos,map(int,upper)))}


def buscar_ajuste(datos,limites,maximos,red,valores,capacidades,identidades,*,cupo,cuota_previa,semilla):
    """Conservo los mejores relojes ensayados, sin afirmar un mínimo global."""
    puntos=red.puntos;oc=valores['ocupacion_coche'];prev=np.array([cuota_previa[p] for p in puntos]);log=[];evaluados={};refinados=[]
    cuotas,info=catalogo_invierno(datos,limites,maximos,puntos=puntos,cupo=cupo,ocupacion=oc,cuota_previa=cuota_previa)
    def evaluar(qq,ordinario):
        cache=(tuple(qq),ordinario)
        if cache in evaluados:return evaluados[cache]
        q=dict(zip(puntos,map(int,qq)));op={**valores,'intervalo_minimo_subidas_min':float(ordinario)};cs={};ns=[]
        for obs,g in datos.items():
            pt=g.copy();pt['demanda_lanzadera_dia']=pt.demanda_bruta_lanzadera_dia-pt.punto.map(q)*oc
            cs[obs]=relojes_de_invierno(pt,red,op,q,limites[obs]);ns.append(cs[obs][0][0][0])
        key=(max(ns),sum(ns),int(np.abs(np.array(qq)-prev).sum()),ordinario,tuple(qq))
        entry={'clave':key,'cuotas':q,'operacion':op,'candidatos':cs}
        evaluados[cache]=entry;log.append({'cuotas':','.join(map(str,qq)),'separacion_ordinaria_min':ordinario,'mayor_mejor_catalogo':max(ns),
            'suma_mejores_catalogos':sum(ns),'distancia_cuota_previa':key[2],**{f'mejor_matriz_{obs}':n for obs,n in zip(datos,ns)}})
        return entry
    for qq in cuotas:
        for ordinario in [30,15]:evaluar(qq,ordinario)
    if not evaluados:raise ValueError('No hay cuotas elegibles en el catálogo invernal.')
    # Intercambio local de5/10 coches alrededor de las dos mejores cuotas.
    best=sorted(evaluados.values(),key=lambda z:z['clave']);centros=[]
    for z in best:
        t=tuple(z['cuotas'][p] for p in puntos)
        if t not in centros:centros.append(t)
        if len(centros)==2:break
    for qq in centros:
        for a,b in product(range(4),repeat=2):
            if a==b:continue
            for delta in [5,10]:
                z=np.array(qq);z[a]-=delta;z[b]+=delta
                if (z<0).any() or any(z[k]>maximos[p]+1e-10 for k,p in enumerate(puntos)):continue
                # Verifico la cota de intervalo antes de crear un reloj.
                ok=True
                for obs,g in datos.items():
                    net=g.set_index('punto').loc[puntos].demanda_bruta_lanzadera_dia.to_numpy()-z*oc
                    cap=limites[obs].set_index('punto').loc[puntos].capacidad_maxima_intervalo_personas.to_numpy()
                    if (net<0).any() or (net>cap+1e-8).any():ok=False;break
                if ok:
                    for ordinario in [30,15]:evaluar(tuple(z),ordinario)
    def cerrar(entry):
        return {obs:cerrar_en_ventana(cs,red,entry['operacion'],capacidades,identidades,inicio_min=420,fin_min=1200) for obs,cs in entry['candidatos'].items()}
    ordered=sorted(evaluados.values(),key=lambda z:z['clave'])
    viables=[entry for entry in ordered if entry['clave'][0]<=27]
    # Entre los cierres construidos priorizo cambiar menos autorizaciones.
    for entry in sorted(viables,key=lambda z:(z['clave'][2],z['clave'][0],z['clave'][1],z['clave'][3:])):
        closed=cerrar(entry)
        if all(z is not None for z in closed.values()):return entry,closed,pd.DataFrame(log),pd.DataFrame(refinados),info
    # Dos configuraciones distintas; dos reinicios por perfil pendiente.
    seeds=[]
    for entry in ordered:
        signature=tuple(entry['cuotas'].values())
        if signature not in [tuple(z['cuotas'].values()) for z in seeds]:seeds.append(entry)
        if len(seeds)==2:break
    for j,entry in enumerate(seeds):
        for obs,cs in entry['candidatos'].items():
            if cerrar_en_ventana(cs,red,entry['operacion'],capacidades,identidades,inicio_min=420,fin_min=1200) is not None:continue
            for k,(key,reloj,u,b) in enumerate(cs[:2]):
                seed=semilla+100*j+int(obs)*2+k
                result,count=mejorar_reloj(reloj,u,b,semilla=seed,pasos=600);n,ne,uu,bb=result
                cs.append(((n,ne,'ajuste_individual',float(k)),reloj,uu,bb))
                refinados.append({'cuotas':','.join(map(str,entry['cuotas'].values())),'observacion':obs,'reinicio':k,'semilla':seed,'pasos_previstos':600,
                    'relojes_validos_evaluados':count,'cadenas_inicio':key[0],'mejores_cadenas':n})
            cs.sort(key=lambda x:x[0])
        ns=[cs[0][0][0] for cs in entry['candidatos'].values()];entry['clave']=(max(ns),sum(ns),*entry['clave'][2:])
        closed=cerrar(entry)
        if all(z is not None for z in closed.values()):return entry,closed,pd.DataFrame(log),pd.DataFrame(refinados),info
    entry=min(evaluados.values(),key=lambda z:z['clave']);return entry,cerrar(entry),pd.DataFrame(log),pd.DataFrame(refinados),info
