"""Enumero estados de cuotas positivas y mido su cercanía territorial."""
from fractions import Fraction
from itertools import product
import heapq
import math
import numpy as np


def metricas_cercania(q,referencia,*,cupo):
    """Comparo proporciones por acceso, separando el aumento del cupo global."""
    total=sum(referencia);desv=[abs(Fraction(v*total,cupo*b)-1) for v,b in zip(q,referencia)]
    return max(desv),sum(desv),sum(abs(Fraction(v)-Fraction(cupo*b,total)) for v,b in zip(q,referencia))


def cuota_mas_cercana(intervalos,referencia,*,cupo):
    """Minimax exacto con aritmética racional; después mínima desviación sumada."""
    total=sum(referencia)
    if any(lo>hi or lo<1 for lo,hi in intervalos) or sum(z[0] for z in intervalos)>cupo or sum(z[1] for z in intervalos)<cupo:return None
    cambios=sorted({abs(Fraction(q*total,cupo*b)-1) for (lo,hi),b in zip(intervalos,referencia) for q in range(lo,hi+1)})
    def limites(t):
        num,den=t.numerator,t.denominator
        ls=[max(lo,-(-cupo*b*(den-num)//(total*den))) for (lo,hi),b in zip(intervalos,referencia)]
        hs=[min(hi,cupo*b*(den+num)//(total*den)) for (lo,hi),b in zip(intervalos,referencia)]
        return ls,hs
    def posible(t):
        ls,hs=limites(t);return all(a<=b for a,b in zip(ls,hs)) and sum(ls)<=cupo<=sum(hs)
    low,high=0,len(cambios)-1
    while low<high:
        mid=(low+high)//2
        if posible(cambios[mid]):high=mid
        else:low=mid+1
    if not posible(cambios[low]):return None
    q,hi=limites(cambios[low]);heap=[]
    def costo(k):
        return abs(Fraction((q[k]+1)*total,cupo*referencia[k])-1)-abs(Fraction(q[k]*total,cupo*referencia[k])-1)
    for k in range(len(q)):
        if q[k]<hi[k]:heapq.heappush(heap,(costo(k),k))
    for _ in range(cupo-sum(q)):
        _,k=heapq.heappop(heap);q[k]+=1
        if q[k]<hi[k]:heapq.heappush(heap,(costo(k),k))
    return tuple(q)


def catalogo_cercano(datos,limites,maximos,*,puntos,cupo,ocupacion,cuota_previa,banda=.75):
    """Represento todos los estados de viajes de dos perfiles dentro de la banda.

    El catálogo de cuotas es exhaustivo en esa banda; la búsqueda posterior
    de horas y cadenas sigue siendo acotada y no demuestra un óptimo global.
    """
    if (not 0<=banda<=1 or any(cuota_previa[p]<=0 for p in puntos)
        or not isinstance(cupo,int) or cupo<=0):raise ValueError('Referencia o banda de cercanía no válidas.')
    fraction=Fraction(str(banda));total=sum(cuota_previa.values());ref=[cuota_previa[p] for p in puntos]
    bruto={o:g.set_index('punto').loc[puntos].demanda_bruta_lanzadera_dia.to_numpy() for o,g in datos.items()}
    caps={o:limites[o].set_index('punto').loc[puntos].capacidad_maxima_intervalo_personas.to_numpy() for o in datos}
    intervalos=[];boxes=[]
    for k,p in enumerate(puntos):
        nom=cupo*ref[k];den=total*fraction.denominator
        lo=max(1,-(-nom*(fraction.denominator-fraction.numerator)//den))
        hi=min(cupo,math.floor(maximos[p]+1e-10),nom*(fraction.denominator+fraction.numerator)//den)
        lo=max(lo,*[max(0,math.ceil((bruto[o][k]-caps[o][k])/ocupacion-1e-10)) for o in datos])
        options=[]
        for q in range(lo,hi+1):
            sig=tuple(int(math.ceil((bruto[o][k]-q*ocupacion-1e-8)/46)) for o in datos)
            if any(n<0 for n in sig):continue
            if options and options[-1][0]==sig:options[-1][2]=q
            else:options.append([sig,q,q])
        intervalos.append(options);boxes.append((lo,hi))
    result=[]
    for combo in product(*intervalos):
        ranges=[(c[1],c[2]) for c in combo]
        if sum(z[0] for z in ranges)>cupo or sum(z[1] for z in ranges)<cupo:continue
        q=cuota_mas_cercana(ranges,ref,cupo=cupo)
        if q is None:continue
        metric=metricas_cercania(q,ref,cupo=cupo)
        sig=tuple(n for c in combo for n in c[0]);result.append({'cuotas':q,'clave_cercania':metric,'firma':sig})
    result.sort(key=lambda z:(*z['clave_cercania'],z['cuotas']))
    return result,{'banda':float(banda),'intervalos_por_acceso':{p:len(z) for p,z in zip(puntos,intervalos)},'limites_cuota':dict(zip(puntos,boxes)),
        'estados_factibles':len(result),'cuotas_cero_permitidas':False,'referencia_proporcional_al_cupo':cuota_previa}
