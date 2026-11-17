"""Compruebo un objetivo diario fijo; los coches se leen del reparto OD."""
import hashlib,json
import numpy as np
import pandas as pd
from .contraste_excursiones import BuscadorConMuestra
from .cierre_con_bases import cerrar_reloj_con_bases
from .refinar_reservas import mejorar_reloj


class ComprobadorAnual:
    """Reutilizo geometrías, no pasajeros. Cada cierre respeta sus propias bases.

    Refino dos semillas y compruebo sus relojes finales completos. Evito
    materializar cientos de veces tablas durante cada ajuste individual.
    Una negativa acotada no demuestra imposibilidad global.
    """
    def __init__(self, red, valores, capacidades, identidades, *, pasos=1800, max_programadas=27):
        if isinstance(max_programadas,(bool,np.bool_)) or int(max_programadas)!=max_programadas or not 1<=max_programadas<=30:
            raise ValueError('Límite de guaguas programadas inválido.')
        self.max_programadas=int(max_programadas)
        self.red,self.v,self.caps,self.ids,self.pasos = red,valores,capacidades,identidades,pasos
        self.bus=BuscadorConMuestra()
        self.bus.max_programadas=self.max_programadas
        self.testigos={}
        self.bus.contexto=hashlib.sha256(json.dumps({'capacidades':capacidades,'identidades':identidades,
            'parametros':{k:valores[k] for k in ['plazas_guagua','ocupacion_diseno','ocupacion_coche','regulacion_min','estancia_min_visita_min','hora_inicio_acceso']}},sort_keys=True).encode()).hexdigest()

    def comprobar(self, objetivos, limites, *, fin_bases_min):
        test=objetivos[['punto','demanda_lanzadera_dia']].merge(limites,on='punto',validate='one_to_one')
        test['deficit_intervalo_personas']=(test.demanda_lanzadera_dia-test.capacidad_maxima_intervalo_personas).clip(lower=0)
        if test.deficit_intervalo_personas.max()>1e-8:
            return None,test,[],{'motivo':'Faltan plazas en la ventana y el intervalo conservados.','mejores_cadenas_ensayadas':np.nan}
        # Una circulación ya construida también sirve con idénticos pasajeros
        # y ventanas que admiten todas sus llegadas. No confundo una búsqueda
        # sin resultado con la inexistencia de ese testigo más restrictivo.
        firma=tuple(sorted((r.punto,float(r.demanda_lanzadera_dia)) for r in objetivos.itertuples()))
        llegadas=limites.set_index('punto').limite_llegada_cabecera_min
        for anterior in self.testigos.get(firma,[]):
            movimientos=anterior['movimientos']
            regresos=anterior['viajes'].loc[lambda t:t.destino.str.startswith('cabecera:')]
            if (movimientos.llegada_min.max()<=fin_bases_min+1e-8
                and all(r.llegada_min<=llegadas[r.destino.split(':',1)[1]]+1e-8 for r in regresos.itertuples())):
                return anterior,test,[],{'motivo':'Circulación construida en una ventana anterior y válida en esta.',
                    'mejores_cadenas_ensayadas':np.nan,'minimo_global_demostrado':False}
        # El objetivo ya contiene la demanda neta asignada; cero es solo la
        # compensación contable del constructor, nunca un cupo por carretera.
        q={p:0 for p in self.red.puntos}
        pt=objetivos[['punto','demanda_lanzadera_dia']].copy()
        pt['demanda_bruta_lanzadera_dia']=pt.demanda_lanzadera_dia
        key,reloj,state,_=self.bus._estado(0,pt,q,self.red,self.v,limites)
        def cerrar():
            cs=[(score,reloj,u,b) for score,u,b in sorted(state['curvas'],key=lambda a:a[0])]
            limite=getattr(self,'max_programadas',27)
            opcion={} if limite==27 else {'max_programadas':limite}
            return cerrar_reloj_con_bases(cs,self.red,reloj.v,self.caps,self.ids,inicio=420,fin=fin_bases_min,**opcion)
        cerrado=cerrar();logs=[]
        if cerrado is None and not state['refinado']:
            seedbase=int(hashlib.sha256(repr(key).encode()).hexdigest()[:8],16)
            for k,(score,u,b) in enumerate(state['semillas'][:2]):
                seed=249000+seedbase+k
                (n,ne,uu,bb),validos=mejorar_reloj(reloj,u,b,semilla=seed,pasos=self.pasos)
                state['curvas'].append(((n,ne,'Ajuste anual',float(k)),uu,bb))
                logs.append({'geometria':repr(key),'reinicio':k,'semilla':seed,'pasos_previstos':self.pasos,
                             'relojes_validos':validos,'cadenas_iniciales':score[0],'mejores_cadenas':n})
            state['curvas'].sort(key=lambda a:a[0]);state['refinado']=True
            cerrado=cerrar()
        best=state['curvas'][0][0][0]
        info={'motivo':'Circulación construida.' if cerrado is not None else f'Sin circulación de hasta{getattr(self,"max_programadas",27)} construida dentro de la búsqueda.',
              'mejores_cadenas_ensayadas':int(best),'minimo_global_demostrado':False}
        if cerrado is not None:
            self.testigos.setdefault(firma,[]).append(cerrado)
        return cerrado,test,logs,info
