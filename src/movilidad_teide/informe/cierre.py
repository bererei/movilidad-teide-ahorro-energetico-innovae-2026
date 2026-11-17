"""Cierre documental: desgloses y sensibilidad algebraica de balances existentes."""
from pathlib import Path
import json
import math
import re
import pandas as pd
from .formato import numero, tex


def balance_perturbado(cs, cc, lanzaderas, comun_sin, comun_con, ds=0., dc=0., db=0., dt=0.):
    """Perturbo cada escenario: los coches se cuentan tanto sin como con intervención.

    Las fracciones son pruebas de tensión, no factores físicos transferidos de FTA.
    Los servicios comunes reciben la misma variación en ambas ramas.
    """
    valores = [cs, cc, lanzaderas, comun_sin, comun_con, ds, dc, db, dt]
    if not all(math.isfinite(float(v)) for v in valores) or min(ds,dc,db,dt) <= -1:
        raise ValueError('Energías finitas y variaciones mayores que -1.')
    if min(cs, cc, lanzaderas, comun_sin, comun_con) < 0:
        raise ValueError('Las energías de partida no pueden ser negativas.')
    sin = cs*(1+ds) + comun_sin*(1+dt)
    con = cc*(1+dc) + lanzaderas*(1+db) + comun_con*(1+dt)
    return sin, con, sin-con


def tabla(destino, nombre, titulo, heads, rows, cols, nota, size=10):
    enc = lambda s: r'\shortstack{' + r'\\'.join(r'\strut '+tex(x) for x in s.split('\n')) + '}'
    lines=[r'\begin{table}[!htbp]',r'\caption{'+titulo+r'}\label{tab:'+nombre+'}',
           r'\centering{\fontsize{'+str(size)+r'}{13}\selectfont',r'\begin{tabularx}{\linewidth}{@{}'+cols+'@{}}',
           r'\rowcolor{azul} '+' & '.join(r'\Blanco{'+enc(s)+'}' for s in heads)+r'\\']
    for i,row in enumerate(rows):
        lines.append((r'\rowcolor{fondo_azul} ' if i%2 else '')+' & '.join(tex(v) for v in row)+r'\\')
    lines += [r'\bottomrule\end{tabularx}}',r'\Fuente{Fuente: '+re.sub(r'(?<!\\)%',r'\\%',nota)+'}',r'\end{table}']
    (destino/'tablas'/f'{nombre}.tex').write_text('\n'.join(lines)+'\n')


def preparar_cierre(root, destino):
    root,destino=Path(root),Path(destino)
    read=lambda n:pd.read_csv(destino/'anexos'/f'{n}.csv',sep=';',float_precision='round_trip')
    export=lambda n,d:d.to_csv(destino/'anexos'/f'{n}.csv',sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
    components=read('energia_por_componente'); central=read('resultado_central')
    metadata=json.loads((destino/'metadatos.json').read_text())
    loss=next(float(r['valor_utilizado']) for r in metadata['parametros']['parametros'] if r['id']=='perdida_rendimiento_guaguas_contraste')
    fta=1/(1-loss)-1
    casos=[('Referencia Hot',0.,0.,0.,0.),('Solo lanzaderas: FTA',0.,0.,fta,0.),
           ('Coches: -5 % en sin y con',-.05,-.05,0.,0.),
           ('Coches: +5 % en sin y con',.05,.05,0.,0.),
           ('Coches: -5 % simétrico y FTA en lanzaderas',-.05,-.05,fta,0.),
           ('Coches: +5 % simétrico y FTA en lanzaderas',.05,.05,fta,0.),
           ('Todos: +5 % simétrico',.05,.05,.05,.05),
           ('Adverso: -1 % coche sin; +1 % coche con y lanzaderas',-.01,.01,.01,0.),
           ('Adverso: +1 % coche con; FTA en lanzaderas',0.,.01,fta,0.)]
    resultados=[];umbrales=[];adversos=[]
    n_visitas=float(read('cobertura_colectivos').visitas_fuente_anio.sum())
    for alt,g in components.groupby('alternativa_procedencia',sort=False):
        def energia(esc,grupo):
            mask=g.escenario_balance.eq(esc)
            mask &= g.componente_balance.str.startswith('Turismos') if grupo=='coches' else g.componente_balance.str.startswith('Lanzaderas') if grupo=='lanzaderas' else g.componente_balance.eq('TITSA y excursiones: bloque común')
            return float(g.loc[mask,'energia_mwh_anio'].sum())
        cs,cc=energia('Sin intervención','coches'),energia('Con intervención','coches')
        bus=energia('Con intervención','lanzaderas');ts,tc=energia('Sin intervención','comun'),energia('Con intervención','comun')
        asignacion='A' if alt.endswith(': alquiler') else 'B'
        sin,con,ahorro=balance_perturbado(cs,cc,bus,ts,tc)
        c=central[central.alternativa_procedencia.eq(alt)].iloc[0]
        if abs(sin-c.sin_componentes_mwh_anio)>1e-8 or abs(con-c.con_construccion_condicionada_mwh_anio)>1e-8:
            raise ValueError('El desglose no reproduce el balance conservado.')
        adversos.append((ahorro-60*11.63)/(cs+cc+bus)*100)
        for nombre,ds,dc,db,dt in casos:
            es,ec,a=balance_perturbado(cs,cc,bus,ts,tc,ds,dc,db,dt)
            resultados.append(dict(prueba_cierre=nombre,asignacion_cierre=asignacion,delta_coche_sin=ds,delta_coche_con=dc,
                                   delta_lanzaderas=db,delta_comun=dt,sin_cierre_mwh_anio=es,con_cierre_mwh_anio=ec,
                                   ahorro_cierre_mwh_anio=a,ahorro_cierre_tep_anio=a/11.63))
        for q in [-.10,-.05,-.01,.01,.05,.10]:
            extra=n_visitas*q;margen=ahorro-60*11.63
            umbrales.append(dict(asignacion_cierre=asignacion,variacion_visitas_cierre=q,incremento_visitas_cierre=extra,
                                 visitas_con_cierre=n_visitas+extra,margen_cierre_mwh_anio=margen,
                                 limite_kwh_visita_adicional=margen*1000/extra if q>0 else float('nan')))
    (destino/'tablas/cierre_cifras.tex').write_text(r'\newcommand{\UmbralAdversoMin}{'+numero(min(adversos))+r'}'+'\n'+r'\newcommand{\UmbralAdversoMax}{'+numero(max(adversos))+r'}'+'\n')
    joint=pd.DataFrame(resultados);visits=pd.DataFrame(umbrales)
    export('sensibilidad_conjunta_cierre',joint);export('umbrales_demanda_cierre',visits)
    filas=[]
    etiquetas=['Referencia Hot','Solo lanzaderas: FTA','Coches: mismo porcentaje −5 %','Coches: mismo porcentaje +5 %',
               'Coches −5 % y lanzaderas FTA','Coches +5 % y lanzaderas FTA','Todos los consumos +5 %',
               'Menos consumo sin; más con','Más consumo de coches con; FTA']
    def variacion(v):
        return ('+' if v>0 else '')+numero(v*100,2 if abs(v-fta)<1e-12 else 0)+' %'
    for etiqueta,(nombre,ds,dc,db,dt) in zip(etiquetas,casos):
        q=joint[joint.prueba_cierre.eq(nombre)].set_index('asignacion_cierre')
        filas.append([etiqueta,variacion(ds),variacion(dc),variacion(db),
                      numero(q.loc['A','ahorro_cierre_tep_anio']),numero(q.loc['B','ahorro_cierre_tep_anio'])])
    tabla(destino,'sensibilidad_conjunta_cierre','Variaciones aplicadas a cada consumo y efecto sobre el ahorro',
          ['Prueba','Coches\nsin','Coches\ncon','Nuevas\nlanzaderas','Ahorro A\ntep/año','Ahorro B\ntep/año'],filas,'Xrrrrr',
          'consumos conservados del balance y sensibilidad\\_conjunta\\_cierre.csv. Las columnas centrales son variaciones relativas del consumo, no de visitas o expediciones; 0 % conserva el bloque. A/B incluyen todos los colectivos. FTA aplica +11,11 % solo a las nuevas lanzaderas. TITSA/excursiones se mantienen iguales entre escenarios: solo en Todos los consumos +5 % reciben también +5 % en ambas ramas y se cancelan. Los ensayos del 1 y 5 % no son probabilidades ni errores medidos.')
    filas=[]
    for q in [.01,.05,.10]:
        g=visits[visits.variacion_visitas_cierre.eq(q)].set_index('asignacion_cierre')
        filas.append([numero(q*100,0)+' %',numero(g.iloc[0].incremento_visitas_cierre,0),
                      numero(g.loc['A','limite_kwh_visita_adicional']),numero(g.loc['B','limite_kwh_visita_adicional'])])
    tabla(destino,'umbrales_demanda_cierre','Presupuesto energético por visita adicional compatible con 60 tep/año',
          ['Más visitas\ncon intervención','Visitas adicionales\npor año','Límite A\nkWh/visita','Límite B\nkWh/visita'],filas,'Xrrr',
          'margen Hot dividido entre las visitas adicionales de cada prueba. Es un umbral del consumo neto adicional de todo el sistema, no un consumo previsto ni una comprobación de capacidad. No modifica la demanda central; las reducciones de visitas tampoco permiten recortar proporcionalmente la energía de una oferta fija.')
    # Conservo cada rama y marco directamente el escenario al que pertenece.
    cars=read('actividad_turismos');carrows=[]
    nombres={'antes':('Sin','Directo, interior y regreso'),'autorizados':('Con','Coches autorizados al Parque'),
             'transferidos':('Con','Alimentación de transferidos'),'alimentacion_otros':('Con','Alimentación desde otros modos')}
    for rama,(esc,nombre) in nombres.items():
        g=cars[cars.alternativa_procedencia.eq(cars.alternativa_procedencia.iloc[0]) & cars.rama.eq(rama)]
        carrows.append([esc,nombre,numero(g.loc[g.sentido.eq('hacia_teide'),'recorridos_coche_anio'].sum(),0),numero(g.vehiculos_km_anio.sum(),0)])
    tabla(destino,'actividad_coches','Actividad de coches por escenario y rama en 2028',
          ['Escenario','Rama','Entradas o\nalimentaciones/año','Vehículos-km/año'],carrows,'lXrr',
          'actividad conservada por origen, colectivo, rama y sentido. Las filas Con se suman entre sí, pero no a la fila Sin. El interior se cuenta una vez por visita; los kilómetros incluyen ida y regreso. Alimentación desde otros modos no significa crecimiento de visitas ni coches que entren al Parque.')
    # Cobertura sin/con: misma fuente y sus tres destinos con intervención.
    coverage=read('cobertura_colectivos');fields=['visitas_fuente_anio','personas_coche_sin_anio','personas_colectivo_sin_anio','personas_coche_autorizado_anio','personas_lanzadera_anio','personas_colectivo_permanecen_anio']
    lines=[r'\begin{table}[!htbp]',r'\caption{Visitas-persona de todos los colectivos, sin y con intervención en 2028}\label{tab:cobertura_colectivos}',r'\centering{\fontsize{9}{12}\selectfont',r'\begin{tabularx}{\linewidth}{@{}Xrrrrrr@{}}',
           r' & & \multicolumn{2}{c}{Sin intervención} & \multicolumn{3}{c}{Con intervención}\\',
           r'\rowcolor{azul}\Blanco{Colectivo} & \Blanco{Total} & \Blanco{Coche} & \Blanco{Colect.} & \Blanco{Coche} & \Blanco{Lanz.} & \Blanco{Colect.}\\']
    for i,row in coverage.iterrows():lines.append((r'\rowcolor{fondo_azul} ' if i%2 else '')+tex(row.colectivo_lectura)+' & '+' & '.join(numero(row[f],0) for f in fields)+r'\\')
    lines += [r'\midrule Total & '+' & '.join(numero(coverage[f].sum(),0) for f in fields)+r'\\',r'\bottomrule\end{tabularx}}',
              r'\Fuente{Fuente: Visor del Teide y reparto territorial de telefonía, aforos y ocupaciones de estudio; conciliación en \Archivo{cobertura\_colectivos.csv}, véase Anexo~\ref{calc:demanda}. Sin: coche y transporte colectivo. Con: coche autorizado, nuevas lanzaderas y colectivo que permanece. Colect. reúne TITSA y excursiones; Lanz. cuenta visitas, sin duplicar transbordos. La suma se conserva por colectivo; los redondeos pueden diferir en una unidad. A y B tienen las mismas visitas.}',r'\end{table}']
    (destino/'tablas/cobertura_colectivos.tex').write_text('\n'.join(lines)+'\n')
    # Inventario y programación de ejemplos reales del cálculo, sin crear otra oferta.
    base=root/'data/silver/energia_turismos/20261101_flota_30_tres_sustitutas/balance_de_bases.csv'
    inventory=pd.read_csv(base,sep=';');inventory=inventory[inventory.politica.eq('Accesos e interior según reservas')]
    rows=[]
    for name,g in inventory.groupby('terminal',sort=False):
        total=int(g.inventario_inicial.iloc[0]);vals=[]
        for obs in [30,41,-85]:
            q=g[g.observacion.eq(obs)].iloc[0];vals.append(f'{int(q.programadas_desde_base)} / {int(q.sin_programar_en_base)}')
        tipo='interior' if name in ('Boca Tauce','El Portillo') else 'acceso'
        rows.append([name+' ('+tipo+')',str(total),*vals])
    totales=[]
    for obs in [30,41,-85]:
        q=inventory[inventory.observacion.eq(obs)]
        totales.append(f'{int(q.programadas_desde_base.sum())} / {int(q.sin_programar_en_base.sum())}')
    total=int(inventory.groupby('terminal').inventario_inicial.first().sum())
    rows.append(['Total',str(total),*totales])
    tabla(destino,'inventario','Guaguas físicas por base: inventario y asignación diaria',
          ['Base','Inventario','Marzo laborable\nasign. / libres','Julio domingo\nasign. / libres','Diseño p85\nasign. / libres'],rows,'Xrrrr',
          'inventario y cierre de bases conservados. Acceso/interior identifica la posición de la base en el esquema propuesto, sin exigir uso exclusivo de sus guaguas en un servicio. Todas las cifras cuentan guaguas físicas. Asign. indica guaguas con uno o más viajes en la jornada; libres, guaguas sin viajes asignados, para sustitución por avería o mantenimiento. Los dos perfiles fuente, proyectados a 2028, forman parte de las nueve combinaciones de mes y tipo de día; el p85 es una comprobación adicional sin peso anual. No representan horarios universales ordinario/punta.')
    for name,peso in [('operacion_ordinario','260/3'),('operacion_punta','53/3')]:
        p=destino/'tablas'/f'{name}.tex';s=p.read_text()
        if 'Vacíos: enlaces necesarios' not in s:
            note=(r'\Fuente{Vacíos: enlaces necesarios entre viajes y regreso a base; consumen energía y solo pueden retirarse con otra cadena compatible. Peso anual de este perfil: '+peso+r' días equivalentes; no representa todos los días ordinarios o de punta.}')
            s=s.replace(r'\end{table}',note+r'\end{table}');p.write_text(s)
    # Etiquetas estables para referencias explícitas a las tablas generadas.
    for p in (destino/'tablas').glob('*.tex'):
        s=p.read_text()
        if r'\caption{' in s and r'\label{tab:' not in s:
            s=re.sub(r'(\\caption\{[^}]+\})',lambda m:m[0]+r'\label{tab:'+p.stem+'}',s,count=1)
            p.write_text(s)
    meta=json.loads((destino/'metadatos.json').read_text())
    from movilidad_teide.trazabilidad import sha256_archivo
    meta['inputs_sha256'][str(base.resolve())]=sha256_archivo(base)
    meta['cierre_011']={'calculo_central_modificado':False,'sensibilidad_conjunta':'Pruebas algebraicas sobre los dos escenarios y todas las categorías; no FTA de árbol de fallos.',
                       'demanda':'Umbrales de consumo por visita adicional; sin simular nuevas expediciones o acreditar capacidad fuera de la demanda modelizada.',
                       'tolerancia_conciliacion_mwh':1e-8,'motivo_tolerancia':'Orden de suma de coma flotante; muy inferior al redondeo de 0,01 MWh del documento.'}
    (destino/'metadatos.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
