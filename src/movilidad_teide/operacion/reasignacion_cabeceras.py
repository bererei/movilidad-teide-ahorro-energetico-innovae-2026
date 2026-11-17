"""Contrasto reservas en otra cabecera con el comprobador de flota existente."""
import itertools
import numpy as np
import pandas as pd
from movilidad_teide.demanda.cabeceras_alternativas import PAREJAS,capacidad_elegible,trasladar_reservas
from .invierno import limites_llegada_con_luz
from .jornada_anual import ComprobadorAnual


class ReasignadorCabeceras:
    """Búsqueda acotada: primero menos visitas cambiadas, después menos km.

    Examino umbrales de expedición de 46 plazas, hasta doce por dirección
    después del mínimo necesario por intervalo. Permito una dirección por
    pareja y un máximo de dos parejas; no optimizo energía o cuotas de coches.
    La selección no acredita un mínimo entre todos los horarios posibles.
    """
    def __init__(self,red,valores,caps,ids,solar,catalogo,*,pasos=1800):
        self.red,self.v,self.sun,self.catalogo=red,valores,solar,catalogo
        self.rapido=ComprobadorAnual(red,valores,caps,ids,pasos=0,max_programadas=28)
        self.refinado=ComprobadorAnual(red,valores,caps,ids,pasos=pasos,max_programadas=28)
        self.logs=[];self.cache={}
        for a,b in PAREJAS.items():
            if not red.destinos.loc[a].equals(red.destinos.loc[b]):raise ValueError('Las parejas cambian el destino interior.')

    def aplicar(self,modal,mes):
        pt=modal['escenarios_por_punto_dia'];signature=(mes,tuple(sorted((a.punto,float(a.demanda_lanzadera_dia)) for a in pt.itertuples())),tuple(modal['por_origen_dia'].visitas_coche_transferidas_dia))
        if signature in self.cache:
            moves,info=self.cache[signature];out,detail=trasladar_reservas(modal,self.catalogo,moves,ocupacion=self.v['ocupacion_coche']);return out,detail,info
        lim=limites_llegada_con_luz(self.red,self.v,ocaso_min=self.sun[mes],margen_min=30);fin=1290 if 5<=mes<=8 else 1200
        native,test,_,info=self.refinado.comprobar(pt,lim,fin_bases_min=fin)
        if native is not None:
            moves=[];info={'cierre_principal_regla':True,'candidatos':1,'refinados':1,'visitas_cambiadas_dia':0.,'estado_regla':'Sin cambio: ya hay circulación.'}
        else:
            demand=pt.set_index('punto').demanda_lanzadera_dia;capacity=lim.set_index('punto').capacidad_maxima_intervalo_personas
            eligible=capacidad_elegible(modal,self.catalogo);options={};cap=46
            for a,b in PAREJAS.items():
                minimum=max(0.,demand[a]-capacity[a]);maximum=min(float(eligible.get(a,0.)),max(0.,capacity[b]-demand[b]))
                kmax=int(np.floor((demand[a]-minimum+1e-8)/cap));vals=sorted({float(demand[a]-cap*k) for k in range(max(0,kmax-11),kmax+1) if minimum-1e-8<=demand[a]-cap*k<=maximum+1e-8 and demand[a]-cap*k>1e-8})
                options[a]=[[(a,b,n)] for n in vals]
            candidates=[]
            north=[[]]+options['OROTAVA']+options['LAGUNA'];south=[[]]+options['CHIO']+options['VILAFLOR']
            # Para dos parejas contrasto tres umbrales por dirección; evita un
            # optimizador nuevo y conserva un presupuesto explícito reproducible.
            two_n=[[]]+options['OROTAVA'][:3]+options['LAGUNA'][:3];two_s=[[]]+options['CHIO'][:3]+options['VILAFLOR'][:3]
            raw=north[1:]+south[1:]+[a+b for a,b in itertools.product(two_n[1:],two_s[1:])]
            for moves0 in raw:
                mod,detail=trasladar_reservas(modal,self.catalogo,moves0,ocupacion=self.v['ocupacion_coche']);p=mod['escenarios_por_punto_dia']
                excess=(p.set_index('punto').demanda_lanzadera_dia-capacity).clip(lower=0).sum()
                if excess>1e-8:continue
                candidates.append((sum(a[2] for a in moves0),float(detail.extra_vehiculo_km_dia.sum()),moves0,p))
            candidates.sort(key=lambda a:(a[0],a[1],repr(a[2])))
            found=[];fallback=[];tested=0;refined=0
            # Las semillas ordinarias son económicas; refino ocho candidatos
            # por número de visitas. Si aparece un cierre, contrasto primero
            # todos los candidatos anteriores de menor traslado con refinamiento.
            for i,(people,km,mv,p) in enumerate(candidates):
                z,tt,_,inf=self.rapido.comprobar(p,lim,fin_bases_min=fin);tested+=1
                metric=inf.get('mejores_cadenas_ensayadas',np.inf)
                fallback.append((metric if np.isfinite(metric) else np.inf,people,km,mv))
                if z is not None:found.append((people,km,mv));break
                if i<8:
                    z,_,_,_=self.refinado.comprobar(p,lim,fin_bases_min=fin);refined+=1
                    if z is not None:found.append((people,km,mv));break
            if found:
                moves=min(found,key=lambda a:(a[0],a[1],repr(a[2])))[2];closed=True;state='Circulación principal construida con traslado.'
            else:
                # Si falta el cierre físico, dejo visible el mejor contraste de
                # relojes que supera plazas. No lo convierto en oferta viable.
                moves=min(fallback,key=lambda a:(a[0],a[1],a[2],repr(a[3])))[3] if fallback else [];closed=False;state='Pendiente: ninguna circulación principal construida en el catálogo.'
            info={'cierre_principal_regla':closed,'candidatos':tested+1,'refinados':refined+1,'visitas_cambiadas_dia':sum(a[2] for a in moves),'estado_regla':state}
        self.cache[signature]=(moves,info)
        out,detail=trasladar_reservas(modal,self.catalogo,moves,ocupacion=self.v['ocupacion_coche'])
        return out,detail,info
