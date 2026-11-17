"""Vinculo demanda, calendario y servicio de una alternativa anual explícita."""
from pathlib import Path
import json,platform
import numpy as np
import pandas as pd
from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.demanda.calendario_anual import construir_perfiles_anuales,aplicar_cupo_global,REFERENCIA_MES,HipotesisModalNoAplicable
from movilidad_teide.demanda.p85_alternativas import reconstruir_muestra
from movilidad_teide.operacion.jornada_anual import ComprobadorAnual
from movilidad_teide.operacion.calendario_vehiculos import materializar_calendario
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.operacion.invierno import limites_llegada_con_luz
from movilidad_teide.trazabilidad import sha256_archivo
from .operacion_2028 import FUENTES,BASE as REFERENCIA
from .compartida_2028 import BASE,PARADAS
from .tipos import Etapa

SOLAR='data/silver/operacion/inventario/cuotas_positivas_cercanas/referencia_solar_2028.csv'
INVENTARIO='data/silver/demanda/referencias_temporales/p85_P15_P20/inventario_30.csv'
SALIDAS='data/silver/movilidad/cierre_anual_2028'
MESES={'Enero':1,'Febrero':2,'Marzo':3,'Abril':4,'Mayo':5,'Junio':6,'Julio':7,'Agosto':8,'Septiembre':9,'Octubre':10,'Noviembre':11,'Diciembre':12}
POLITICAS={
    'referencia':{'cupo':600,'incremento_general':.15,'incremento_enero':.15,'max_programadas':27,'decision':'D249','hipotesis':'H139'},
    '650_enero':{'cupo':650,'incremento_general':.25,'incremento_enero':.30,'max_programadas':28,'decision':'D250','hipotesis':'H140'},
}


def politica_cierre(alternativa,mes):
    """La excepción de enero se aplica al mes representado, no al año fuente."""
    if alternativa not in POLITICAS or mes not in range(1,13):
        raise ValueError('Alternativa o mes de cálculo no definidos.')
    p=POLITICAS[alternativa]
    return {**p,'incremento':p['incremento_enero'] if mes==1 else p['incremento_general']}


def preparar_cierre_anual(root,*,pasos=1800,alternativa='referencia',total=2500000,reasignar=False):
    if isinstance(total,bool) or total not in [2500000,2450000]:raise ValueError('Volumen de planificación no autorizado.')
    if reasignar and alternativa!='650_enero':raise ValueError('El contraste de cabeceras conserva la política650_enero.')
    politica=politica_cierre(alternativa,1)
    root=Path(root).resolve();rd=lambda p:pd.read_csv(root/p,sep=';',float_precision='round_trip')
    paths=[FUENTES[k] for k in ['perfiles','indices','origenes']]+[REFERENCIA+'/demanda_horaria_2028.csv',REFERENCIA+'/metadatos.json',
        BASE+'/movimientos_diagnosticos.csv',BASE+'/pares_diagnosticos.csv',PARADAS,SOLAR,INVENTARIO,'config/parametros_modelo.xlsx']
    fuentes={p:sha256_archivo(root/p) for p in paths}
    params=leer_parametros(root);v={p['id']:p['valor_utilizado'] for p in params['parametros']}
    if (v['cupo_global']!=500 or v['vehiculos_contrato_contraste']!=30 or v['reserva_minima_dentro_flota']!=3
        or v['intervalo_refuerzo_punta_min']!=15 or int(v['plazas_guagua']*v['ocupacion_diseno'])!=46
        or v['regulacion_min']!=10 or v['estancia_min_visita_min']!=120):raise ValueError('Conservar las condiciones de partida.')
    v={**v,'hora_inicio_acceso':7.}
    media=rd(REFERENCIA+'/demanda_horaria_2028.csv');frac=json.loads((root/REFERENCIA/'metadatos.json').read_text())['fraccion_coche_conservada']
    h,calibracion=reconstruir_muestra(rd(FUENTES['perfiles']),rd(FUENTES['indices']),media,total=total,fraccion_coche=frac,
        hora_inicio=v['hora_inicio_acceso'],hora_fin=v['hora_fin_acceso'],**({'registrar_residuos':True} if total==2450000 else {}))
    origenes=rd(FUENTES['origenes']);inv=rd(INVENTARIO);ids=inv.groupby('base_red').unidad_fisica_id.apply(list).to_dict();caps={b:len(i) for b,i in ids.items()}
    red=RedOperativa(rd(BASE+'/movimientos_diagnosticos.csv'),rd(BASE+'/pares_diagnosticos.csv'),rd(PARADAS))
    solar=rd(SOLAR);sun=solar.groupby('mes').ocaso_min.min().to_dict()
    operador=ComprobadorAnual(red,v,caps,ids,pasos=pasos,max_programadas=politica['max_programadas'])
    reasignador=None
    if reasignar:
        from movilidad_teide.demanda.cabeceras_alternativas import leer_catalogo,FUENTE
        from movilidad_teide.operacion.reasignacion_cabeceras import ReasignadorCabeceras
        catalogo=leer_catalogo(root)
        reasignador=ReasignadorCabeceras(red,v,caps,ids,sun,catalogo,pasos=pasos)
        fuentes.update({str(p.relative_to(root)):sha256_archivo(p) for p in sorted((root/FUENTE).glob('*')) if p.is_file()})
    tables={};rows=[];modales={};perfiles_cal={};indisponibles=set()
    def add(n,t,**tag):
        if t is not None and not t.empty:tables.setdefault(n,[]).append(t.assign(**tag))
    def registrar_modal(idp,g,metodo,ambito,mes):
        tag={'id_perfil':idp,'metodo_calendario':metodo,'ambito':ambito,'mes_modelo':mes}
        try:
            regla=politica_cierre(alternativa,mes)
            z,res=aplicar_cupo_global(g,origenes,v,cupo=regla['cupo'],incremento=regla['incremento'])
        except HipotesisModalNoAplicable as e:
            indisponibles.add(idp);add('aplicabilidad',pd.DataFrame([{'aplicable':False,'motivo':str(e)}]),**tag)
            return None
        if reasignador is not None:
            z,traslados,revision=reasignador.aplicar(z,mes)
            add('traslados_cabecera',traslados,**tag)
            add('busqueda_cabeceras',pd.DataFrame([revision]),**tag)
        modales[idp]=z
        add('aplicabilidad',pd.DataFrame([{'aplicable':True,'motivo':'Conserva visitantes y cumple el máximo global.'}]),**tag)
        add('origenes_por_modo',z['por_origen_dia'],**tag)
        add('objetivos_por_modo',z['escenarios_por_punto_dia'],**tag)
        add('titsa_nativo',z['titsa_por_corredor_colectivo_dia'],**tag)
        add('residuos_numericos',res,**tag)
        return z
    def comprobar(idp,pt,*,metodo,ambito,mes,margen,dias=0,ocaso=None,fin=None):
        tag={'id_perfil':idp,'metodo_calendario':metodo,'ambito':ambito,'mes_modelo':mes,'margen_min':margen}
        fin=int(fin if fin is not None else 1290 if 5<=mes<=8 else 1200)
        lim=limites_llegada_con_luz(red,v,ocaso_min=float(sun[mes] if ocaso is None else ocaso),margen_min=margen)
        if pt is None:
            rows.append({**tag,'dias_calendario':dias,'cierre':False,'motivo':'Hipótesis modal no aplicable.','programadas':np.nan,'fin_bases_permitido_min':fin})
            return
        cerrado,test,logs,info=operador.comprobar(pt,lim,fin_bases_min=fin)
        add('limites_y_demanda',test,**tag);add('refinamiento',pd.DataFrame(logs),**tag)
        row={**tag,**info,'dias_calendario':dias,'cierre':cerrado is not None,'programadas':cerrado['programadas'] if cerrado else np.nan,
             'sin_programar':30-cerrado['programadas'] if cerrado else np.nan,
             'demanda_lanzadera_personas_dia':float(pt.demanda_lanzadera_dia.sum()),'deficit_intervalo_personas':float(test.deficit_intervalo_personas.sum()),
             'limite_llegada_cabecera_min':float(lim.limite_llegada_cabecera_min.iloc[0]),'fin_bases_permitido_min':fin}
        rows.append(row)
        if cerrado is not None:
            if abs(cerrado['reservas'].personas.sum()-row['demanda_lanzadera_personas_dia'])>1e-8:raise ValueError('El cierre pierde pasajeros.')
            for n,k in [('cronologias','viajes'),('reservas','reservas'),('movimientos','movimientos')]:add(n,cerrado[k],**tag)
            disp=[]
            for unit in inv.itertuples():
                m=cerrado['movimientos'].loc[lambda a:a.unidad_fisica_id.eq(unit.unidad_fisica_id)].sort_values('salida_min')
                if not m.empty and m.iloc[0].origen!=unit.base_red:raise ValueError('Una unidad no sale de su base original.')
                disp.append({'unidad_fisica_id':unit.unidad_fisica_id,'programada':not m.empty,'base_inicial':unit.base_red,'base_final':m.iloc[-1].destino if not m.empty else unit.base_red})
            add('disponibilidad_30',pd.DataFrame(disp),**tag)
        print(f'{metodo}/{ambito}/{idp}/M{margen}: cierre={row["cierre"]}; déficit plazas={row["deficit_intervalo_personas"]:.2f}',flush=True)

    calendarios=[]
    for metodo in ['Estacional','Media anual']:
        c,hh=construir_perfiles_anuales(h,metodo=metodo)
        prefijo='E' if metodo=='Estacional' else 'A'
        c['id_perfil']=prefijo+'_'+c.apply(lambda z:f'M{z.mes:02d}_{z.tipo_dia_publicado}',axis=1)
        calendarios.append(c.assign(metodo_calendario=metodo))
        hh['id_perfil']=prefijo+'_'+hh.id_perfil
        add('demanda_horaria_calendario',hh)
        for (mes,tipo),g in hh.groupby(['mes_modelo','tipo_dia_publicado']):
            idp=g.id_perfil.iloc[0];dias=int(g.dias_calendario.iloc[0]);perfiles_cal[idp]={'mes':int(mes),'tipo':tipo,'dias':dias,'metodo':metodo,'fuente':g.referencia_temporal.iloc[0]}
            z=registrar_modal(idp,g,metodo,'Calendario',int(mes));pt=None if z is None else z['escenarios_por_punto_dia']
            for margen in [30,15]:comprobar(idp,pt,metodo=metodo,ambito='Calendario',mes=int(mes),margen=margen,dias=dias)
    add('calendario',pd.concat(calendarios,ignore_index=True))

    # Las observaciones históricas NO reciben peso anual o el ajuste temporal
    # de las referencias2025; se prueban en el mes de su fuente inferida.
    historicos=[]
    for obs,g in h.groupby('matrix_index'):
        mes=MESES[g.mes_publicado.iloc[0]];idp=f'H{int(obs):02d}'
        z=registrar_modal(idp,g,'Histórico','Histórico',mes)
        if z is not None:
            historicos.append(z['escenarios_por_punto_dia'][['punto','demanda_lanzadera_dia']].assign(matrix_index=int(obs),mes_modelo=mes,temporada_referencia=REFERENCIA_MES[mes]))
        for margen in [30,15]:comprobar(idp,None if z is None else z['escenarios_por_punto_dia'],metodo='Histórico',ambito='Histórico',mes=mes,margen=margen)
    hm=pd.concat(historicos,ignore_index=True) if historicos else pd.DataFrame()
    add('muestra_p85',hm)
    # Enero representa la estación con su propia política. Reasigno cada una
    # de las19 referencias antes del percentil, sin modificar su prueba nativa.
    enero=[]
    if politica['incremento_enero']!=politica['incremento_general']:
        invierno=h[h.mes_publicado.map(MESES).map(REFERENCIA_MES).eq(3)]
        for obs,g in invierno.groupby('matrix_index'):
            z=registrar_modal(f'J_H{int(obs):02d}',g,'Estacional','Referencia p85 enero',1)
            if z is not None:
                enero.append(z['escenarios_por_punto_dia'][['punto','demanda_lanzadera_dia']].assign(matrix_index=int(obs),mes_modelo=1,temporada_referencia=3))
        add('muestra_p85_enero',pd.concat(enero,ignore_index=True) if enero else pd.DataFrame())
    for mes in range(1,13):
        expected=h.loc[h.mes_publicado.map(MESES).map(REFERENCIA_MES).eq(REFERENCIA_MES[mes]),'matrix_index'].nunique()
        if reasignador is not None:
            muestras=[]
            # Cada matriz recibe la regla con la ventana del mes representado
            # antes del percentil. El p85 compuesto no se reencamina después.
            for obs,g in h[h.mes_publicado.map(MESES).map(REFERENCIA_MES).eq(REFERENCIA_MES[mes])].groupby('matrix_index'):
                z=registrar_modal(f'P{mes:02d}_H{int(obs):02d}',g,'Estacional','Referencia p85 mensual',mes)
                if z is not None:
                    muestras.append(z['escenarios_por_punto_dia'][['punto','demanda_lanzadera_dia']].assign(matrix_index=int(obs),mes_modelo=mes,temporada_referencia=REFERENCIA_MES[mes]))
            gg=pd.concat(muestras,ignore_index=True) if muestras else hm.iloc[:0]
            add('muestra_p85_mensual_reasignada',gg)
        elif mes==1 and politica['incremento_enero']!=politica['incremento_general']:
            gg=pd.concat(enero,ignore_index=True) if enero else hm.iloc[:0]
        else:
            gg=hm[hm.temporada_referencia.eq(REFERENCIA_MES[mes])]
        ok=gg.matrix_index.nunique()==expected
        p=gg.groupby('punto',as_index=False).agg(demanda_lanzadera_dia=('demanda_lanzadera_dia',lambda a:a.quantile(.85,interpolation='linear'))) if ok else None
        if p is not None:add('p85_estacional',p,mes_modelo=mes,temporada_referencia=REFERENCIA_MES[mes],matrices=expected)
        for margen in [30,15]:comprobar(f'P{mes:02d}',p,metodo='Estacional',ambito='p85 estacional',mes=mes,margen=margen)
    if hm.matrix_index.nunique()==57:
        pg=hm.groupby('punto',as_index=False).agg(demanda_lanzadera_dia=('demanda_lanzadera_dia',lambda a:a.quantile(.85,interpolation='linear')))
        add('p85_global',pg)
        for margen in [30,15]:comprobar('PGLOBAL',pg,metodo='Estrés',ambito='p85 global invierno',mes=12,margen=margen,ocaso=float(solar.ocaso_min.min()),fin=1200)

    res=pd.DataFrame(rows);add('resumen_operacion',res)
    if alternativa!='referencia':
        calendario_mov=materializar_calendario(pd.concat(calendarios,ignore_index=True),res,
            pd.concat(tables.get('movimientos',[]),ignore_index=True) if tables.get('movimientos') else pd.DataFrame(),
            pd.concat(tables.get('disponibilidad_30',[]),ignore_index=True) if tables.get('disponibilidad_30') else pd.DataFrame(),
            inv,max_programadas=politica['max_programadas'])
        for nombre,tabla in calendario_mov.items():add(nombre,tabla)
    if alternativa=='650_enero':
        # Diagnóstico de los extremos: los umbrales solo expresan la condición
        # necesaria de plazas con el reparto de coches conservado. No se adoptan.
        limext=pd.concat(tables['limites_y_demanda'],ignore_index=True)
        limext=limext[limext.id_perfil.isin(['H10','H11','H12'])]
        cotas=[];fuentes_ext=[]
        indice=rd(FUENTES['indices']).set_index('matrix_index')
        for obs in [10,11,12]:
            key=f'H{obs:02d}';g=h[h.matrix_index.eq(obs)];p=modales[key]['escenarios_por_punto_dia']
            tag=indice.loc[obs].to_dict()
            fuentes_ext.append({'matrix_index':obs,**tag,'filas_horarias_colectivo':len(g),
                'duplicados_clave_horaria':int(g.duplicated(['access_corridor','colectivo','hora_servicio']).sum()),
                'colectivos':g.colectivo.nunique(),'corredores':g.access_corridor.nunique(),
                'total_OD_sin_escalar':float(g.personas_od.sum()),'visitas_modelizadas_dia':float(g.visitas_persona_dia.sum()),
                'escala_comun_OD':calibracion['escala_comun_OD'],'incremento_excursiones_aplicado':politica_cierre(alternativa,MESES[g.mes_publicado.iloc[0]])['incremento']})
            for row in limext[limext.id_perfil.eq(key)].itertuples():
                a=p[p.punto.eq(row.punto)].iloc[0];E=float(a.visitas_excursiones_resto_colectivo)
                numerador=float(a.visitas_coche-a.visitas_coche_autorizadas_dia+a.visitas_titsa-row.capacidad_maxima_intervalo_personas)
                minimo=max(0.,numerador/E) if E>0 else (np.nan if numerador>1e-8 else 0.)
                cotas.append({'matrix_index':obs,'matriz_publicada':tag['matriz_publicada'],'id_perfil':key,
                    'punto':row.punto,'margen_min':row.margen_min,'coches_autorizados_dia':a.coches_autorizados_dia,
                    'visitas_excursiones_sin_dia':E,'incremento_excursiones_aplicado':politica['incremento_general'],
                    'demanda_lanzadera_dia':row.demanda_lanzadera_dia,'capacidad_maxima_intervalo_personas':row.capacidad_maxima_intervalo_personas,
                    'deficit_intervalo_personas':row.deficit_intervalo_personas,'maximo_salidas_intervalo':row.maximo_salidas_intervalo,
                    'salidas_necesarias_46_plazas':int(np.ceil(row.demanda_lanzadera_dia/46)),
                    'incremento_excursiones_minimo_para_plazas_con_reparto_actual':minimo,
                    'umbral_adoptado':False,'peso_anual_dias':0})
        add('revision_fuentes_extremos',pd.DataFrame(fuentes_ext));add('cotas_extremos',pd.DataFrame(cotas))
    mensual=[];sintesis=[]
    for metodo in ['Estacional','Media anual']:
        for margen in [30,15]:
            calres=res[res.metodo_calendario.eq(metodo)&res.ambito.eq('Calendario')&res.margen_min.eq(margen)]
            hist=res[res.ambito.eq('Histórico')&res.margen_min.eq(margen)]
            dis=res[res.ambito.eq('p85 estacional')&res.margen_min.eq(margen)]
            anual=bool(len(calres)==36 and calres.cierre.all() and len(hist)==57 and hist.cierre.all() and len(dis)==12 and dis.cierre.all())
            sintesis.append({'metodo_calendario':metodo,'margen_min':margen,'perfiles_calendario_con_cierre':int(calres.cierre.sum()),
                'dias_con_cierre':int(calres.loc[calres.cierre,'dias_calendario'].sum()),'historicos_con_cierre':int(hist.cierre.sum()),
                'p85_estacionales_con_cierre':int(dis.cierre.sum()),'oferta_anual_construida':anual,
                'dias_sin_cierre':int(calres.loc[~calres.cierre,'dias_calendario'].sum()),
                'maximo_programadas_en_perfiles_cerrados':calres.programadas.max()})
            if alternativa!='referencia':
                sintesis[-1]['calendario_y_p85_con_cierre']=bool(len(calres)==36 and calres.cierre.all() and len(dis)==12 and dis.cierre.all())
                sintesis[-1]['maximo_programadas_permitido']=politica['max_programadas']
                sintesis[-1]['sustitucion_minima']=30-politica['max_programadas']
                jornadas=calendario_mov['jornadas_calendario']
                sintesis[-1]['continuidad_calendario_comprobada']=bool(not jornadas.empty and len(jornadas[jornadas.metodo_calendario.eq(metodo)&jornadas.margen_min.eq(margen)])==366)
            for mes,g in calres.groupby('mes_modelo'):
                tot={'metodo_calendario':metodo,'mes':mes,'margen_min':margen,'dias_calendario':int(g.dias_calendario.sum()),
                     'dias_sin_cierre':int(g.loc[~g.cierre,'dias_calendario'].sum()),'maximo_programadas_en_cierres':g.programadas.max()}
                for name,field in [('visitas_sin','visitas_sin_dia'),('visitas_coche_sin','visitas_coche'),('visitas_titsa_sin','visitas_titsa'),('visitas_excursion_sin','visitas_excursiones_resto_colectivo'),
                    ('visitas_coche_con','visitas_coche_autorizadas_dia'),('visitas_excursion_con','visitas_excursiones_con_intervencion_dia'),('visitas_lanzadera_con','demanda_lanzadera_dia'),('visitas_con','visitas_con_objetivo_dia')]:
                    tot[name]=sum(float(modales[row.id_perfil]['escenarios_por_punto_dia'][field].sum())*row.dias_calendario for row in g.itertuples() if row.id_perfil in modales)
                tot['visitas_lanzadera_en_perfiles_sin_cierre']=sum(float(modales[row.id_perfil]['escenarios_por_punto_dia'].demanda_lanzadera_dia.sum())*row.dias_calendario for row in g.itertuples() if not row.cierre and row.id_perfil in modales)
                mensual.append(tot)
    add('resumen_mensual',pd.DataFrame(mensual));add('sintesis',pd.DataFrame(sintesis))
    # No se atribuye un ahorro anual a una oferta con jornadas sin resolver.
    balance=pd.DataFrame([{'metodo_calendario':z['metodo_calendario'],'margen_min':z['margen_min'],'oferta_anual_construida':z['oferta_anual_construida'],
        'estado':'Pendiente de valoración completa de componentes.' if z['oferta_anual_construida'] else 'No calculado: falta una oferta anual completa.',
        'sin_total_mwh_anio':np.nan,'con_total_mwh_anio':np.nan,'ahorro_total_mwh_anio':np.nan,'ahorro_total_tep_anio':np.nan} for z in sintesis])
    add('estado_balance',balance)
    result={n:pd.concat(ts,ignore_index=True) for n,ts in tables.items()}
    result.update(inventario_30=inv,referencia_solar_2028=solar,indices_muestra=rd(FUENTES['indices']),origenes_sin_cantidad_anual=origenes[~origenes.en_ambito_anual])
    meta={'decision':politica['decision'],'hipotesis':politica['hipotesis'],'fecha':'2026-11-08','parametros_excel_conservados':params,'fuentes_sha256':fuentes,
          'calibracion_conservada':calibracion,'politica':{'visitas_anuales':total,'cupo_global_maximo_coches_dia':politica['cupo'],'incremento_excursiones_sobre_sin':politica['incremento_general'],
          'reparto_coches':'Proporcional OD por día; no cuotas regulatorias por acceso o redistribución para favorecer flota.',
          'referencia_meses':REFERENCIA_MES,'margen_principal_min':30,'margen_sensibilidad_min':15,'fin_bases_mayo_agosto':'21:30','fin_bases_resto':'20:00'},
          'criterio_previo':'Oferta anual construida solo si 36 perfiles cubren 366 días y cierran 57 históricos en su mes y 12 p85 estacionales. El p85 global contra invierno queda como estrés separado; no suma días o visitas.',
          'presupuesto':{'semillas':'15/30 minutos ordinarios compatibles con mínimo 15','reinicios_por_geometria_pendiente':2,'pasos_por_reinicio':pasos,'semilla':'249000 + primeros 8 hexadecimales de SHA256(geometría) + reinicio','minimo_global_demostrado':False,
              'reutilizacion_testigos':'Mismos pasajeros exactos por acceso; se comprueba llegada comercial y fin de bases del caso actual.'},
          'limites':['El calendario estacional es una hipótesis de representación, no datos observados de meses ausentes. Sus factores solo conservan los aportes anuales originales; no se ajustan para encajar flota.',
              'Media anual es sensibilidad de distribución temporal, no nueva evidencia de estacionalidad. Las57matrices no se anualizan.',
              'TITSA conserva su total anual nativo y su corredor; la distribución mensual por perfiles es una hipótesis temporal, no expansión OD o nuevas mediciones.',
              f'Excursiones/resto colectivo es un residuo modelizado. Aumento {100*politica["incremento_general"]:g} % desde viajeros de lanzadera con servicio propio acceso/interior/regreso, fuera de treinta.',
              'Las autorizaciones efectivas pueden ser inferiores al máximo global para mantener viajeros elegibles por origen/colectivo; se elige el mayor total compatible con la regla proporcional OD.',
              'Los horarios usan reservas flexibles dentro del día, no llegadas horarias observadas. Quedan destinos interiores, giros, turnos y eventual demanda interior adicional de quienes acceden en coche.',
              f'Mismas treinta identidades y distribución inicial por bases; hasta {politica["max_programadas"]} programadas y {30-politica["max_programadas"]} libres, 46 plazas, 15 minutos, 120 de estancia y 10 de regulación. Si no cierran todos los días, no se afirma continuidad anual de identidades.',
              'Fuente solar IGN/OAN SantaCruz2028, hora canaria y horizonte ideal; no luz efectiva local. Inicio07:00 y vacíos pueden circular sin luz.',
              'Los p85estacionales tienen muestras limitadas e inferencia temporal original; no demuestran probabilidad85%de servicio futuro.',
              'No se calcula ahorro realizable mientras falte la operación anual. Datos, libro, capturas e informe se conservan.'],
          'entorno':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__}}
    if alternativa!='referencia':
        meta['alternativa']=alternativa
        meta['politica'].update(incremento_excursiones_enero_sobre_sin=politica['incremento_enero'],maximo_programadas=politica['max_programadas'],
            sustitucion_minima=30-politica['max_programadas'],inicio='07:00',intervalo_minimo_min=15,plazas_diseno=46,estancia_min=120,regulacion_min=10)
        meta['limites'] += ['El 30 % se aplica al mes representado de enero antes del p85. Las referencias históricas de marzo conservan el 25 %; no se eliminan los tres extremos o se rebaja el criterio de aceptación.',
            'El p85 global contra el mínimo invernal usa la política general del 25 %, adecuada al mínimo de noviembre/diciembre. Sigue siendo un estrés separado, sin días o visitas anuales añadidos.',
            'Los umbrales de excursión de los históricos son cotas diagnósticas de plazas, sujetas al reparto de coches supuesto. No son porcentajes adoptados u oferta de operadores confirmada.']
    if reasignar or total!=2500000:
        meta.update(decision='D251',hipotesis='H141')
        meta['contraste_cabeceras']={'reasignacion':reasignar,'volumen':total,'sensibilidad_volumen_sobre_2500000':total/2500000-1,
            'ventana_regla':'Mensual, margen30; misma reserva en sensibilidad15.',
            'presupuesto':'Nativo: dos reinicios1800. Traslados: hasta12 umbrales de46 por dirección después de plazas; hasta tres por dirección para dos parejas; semillas de todos hasta primer cierre y refinamiento de los primeros ocho. No mínimo global.',
            'prioridad':'Circulación construida; menor número de visitas trasladadas y luego menor incremento de km entre candidatos ensayados.',
            'tiempo_auxiliar':'Extra km /40 km/h; hipótesis de comparación, no tiempo observado, COPERT o restricción de horarios. OSRM ofrece tiempo del alimentador nuevo por separado.'}
        meta['limites'] += ['El volumen2,45 millones es una sensibilidad de planificación del-2 %, no una nueva medición. TITSA conserva su estimación nativa; se recalcula el residuo de excursiones, no se multiplica todo por0,98.',
            'Los traslados conservan origen/colectivo/fecha y cadena interior. TITSA queda en su corredor; los coches autorizados mantienen el repartoOD y el máximo650. Solo cambia la cabecera de reserva de viajeros coche→lanzadera con trazado propio.',
            'OSRM/FOSSGIS y OpenStreetMap, ODbL: conexiones orientativas fuera del Parque, no autorización de circulación o aparcamientos. Ajuste geométrico máximo1m frente al eje (observado máximo0,111m), separado de la tolerancia numérica1e-8.',
            'No se estima energía nueva. Las pendientes y clases viarias de alimentadores nuevos requieren valoración en el bloque energético posterior. Los recorridos y tiempos estimados no validan aparcamientos, conducción, aceptación del cambio de cabecera o condiciones meteorológicas.']
    return Etapa(result),meta


def generar_cierre_anual(root,destino,*,pasos=1800,alternativa='referencia',total=2500000,reasignar=False):
    root,destino=Path(root).resolve(),Path(destino).resolve();permitido=(root/SALIDAS).resolve()
    if destino==permitido or destino.is_relative_to(root) and not destino.is_relative_to(permitido):raise ValueError('Elegir captura nueva fuera de fuentes e informe.')
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):raise FileExistsError('Conservar las ejecuciones anteriores.')
    etapa,meta=preparar_cierre_anual(root,pasos=pasos,alternativa=alternativa,total=total,reasignar=reasignar);destino.mkdir(parents=True,exist_ok=True)
    for n,t in etapa.tablas.items():t.to_csv(destino/(n+'.csv'),sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
    paquete=Path(__file__).parents[1]
    names=['flujos/cierre_anual.py','demanda/calendario_anual.py','demanda/escenarios_2028.py','demanda/ajuste_invierno.py','demanda/excursiones_2028.py','demanda/p85_alternativas.py',
           'operacion/jornada_anual.py','operacion/contraste_excursiones.py','operacion/equilibrio_invierno.py','operacion/reloj_integrado.py','operacion/cierre_con_bases.py','operacion/refinar_reservas.py','operacion/horarios_compartidos.py','operacion/red_compartida.py','operacion/invierno.py','operacion/circulacion_compartida.py']
    if reasignar:names+=['demanda/cabeceras_alternativas.py','operacion/reasignacion_cabeceras.py']
    meta['codigo_sha256']={'movilidad_teide/'+n:sha256_archivo(paquete/n) for n in names}
    if alternativa!='referencia':
        meta['codigo_sha256']['movilidad_teide/trazabilidad.py']=sha256_archivo(paquete/'trazabilidad.py')
        meta['codigo_sha256']['movilidad_teide/operacion/calendario_vehiculos.py']=sha256_archivo(paquete/'operacion/calendario_vehiculos.py')
    meta['codigo_sha256']['scripts/comprobar_cierre_anual.py']=sha256_archivo(paquete.parents[1]/'scripts/comprobar_cierre_anual.py')
    meta['resultados_sha256']={p.name:sha256_archivo(p) for p in sorted(destino.glob('*.csv'))}
    (destino/'metadatos.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    return etapa,meta
