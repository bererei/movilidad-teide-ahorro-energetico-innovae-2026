"""Comparo volumen y cabecera sin confundir actividad construida con ahorro."""
from pathlib import Path
import json
import pandas as pd
from movilidad_teide.trazabilidad import sha256_archivo,verificar_archivo_de_referencia
from .cierre_anual import generar_cierre_anual
from .compartida_2028 import BASE,PARADAS
from movilidad_teide.operacion.red_compartida import RedOperativa

REFERENCIA='data/silver/movilidad/cierre_anual_2028/20261108_650_excursiones25_enero30_dos_reservas'
CASOS={'250_habitual':(2500000,False),'250_alternativa':(2500000,True),'245_habitual':(2450000,False),'245_alternativa':(2450000,True)}


def comparar_capturas(root,capturas,destino):
    """Las sumas de movimientos pendientes no reciben ceros o peso ficticio."""
    root,destino=Path(root),Path(destino);rows=[];pendientes=[];hashes={}
    if any((destino/n).exists() for n in ['comparacion.csv','comprobaciones_pendientes.csv','metadatos_comparacion.json']):raise FileExistsError('Conservar la comparación anterior; elegir un destino nuevo.')
    rd_red=lambda p:pd.read_csv(root/p,sep=';',float_precision='round_trip')
    red=RedOperativa(rd_red(BASE+'/movimientos_diagnosticos.csv'),rd_red(BASE+'/pares_diagnosticos.csv'),rd_red(PARADAS))
    for caso,path in capturas.items():
        path=Path(path);meta=json.loads((path/'metadatos.json').read_text());rd=lambda n:pd.read_csv(path/(n+'.csv'),sep=';',float_precision='round_trip')
        for n,h in meta['resultados_sha256'].items():
            if sha256_archivo(path/n)!=h:raise ValueError('Captura alterada: '+str(path/n))
        for n,h in meta['fuentes_sha256'].items():
            if sha256_archivo(root/n)!=h:raise ValueError('Fuente alterada: '+n)
        for n,h in meta['codigo_sha256'].items():
            relative=Path(n) if n.startswith('scripts/') else Path('src')/n
            if caso=='250_habitual':verificar_archivo_de_referencia(root,relative,h,revision='98bdc828b8285e4af41b73c5937ff1bb93c9c5f8')
            elif sha256_archivo(root/relative)!=h:raise ValueError('Productor alterado: '+n)
        hashes[caso]={'metadatos_sha256':sha256_archivo(path/'metadatos.json'),'ruta':REFERENCIA if caso=='250_habitual' else caso}
        syn,monthly,res=rd('sintesis'),rd('resumen_mensual'),rd('resumen_operacion')
        transfers=rd('traslados_cabecera') if (path/'traslados_cabecera.csv').exists() else pd.DataFrame()
        moves=rd('movimientos')
        for a in syn.to_dict('records'):
            method,margin=a['metodo_calendario'],a['margen_min'];m=monthly[monthly.metodo_calendario.eq(method)&monthly.margen_min.eq(margin)]
            tt=transfers[transfers.metodo_calendario.eq(method)&transfers.ambito.eq('Calendario')].copy() if not transfers.empty else transfers
            profiles=res[res.metodo_calendario.eq(method)&res.ambito.eq('Calendario')&res.margen_min.eq(margin)]
            if not tt.empty:
                tt['peso_dias']=tt.id_perfil.map(profiles.set_index('id_perfil').dias_calendario)
            def weighted(field):return float((tt[field]*tt.peso_dias).sum()) if not tt.empty else 0.
            mm=moves[moves.metodo_calendario.eq(method)&moves.ambito.eq('Calendario')&moves.margen_min.eq(margin)].copy()
            mm['peso_dias']=mm.id_perfil.map(profiles.set_index('id_perfil').dias_calendario)
            row={'caso':caso,'volumen_planificacion':CASOS[caso][0],'cambio_cabecera_permitido':CASOS[caso][1],**a,
                'visitas_sin_anio':float(m.visitas_sin.sum()),'visitas_con_anio':float(m.visitas_con.sum()),'visitas_lanzadera_anio':float(m.visitas_lanzadera_con.sum()),
                'visitas_coche_con_anio':float(m.visitas_coche_con.sum()),'visitas_excursion_con_anio':float(m.visitas_excursion_con.sum()),
                'visitas_cambio_cabecera_anio':weighted('visitas_persona_dia'),'extra_vehiculo_km_alimentacion_anio':weighted('extra_vehiculo_km_dia'),
                'extra_persona_min_anio_a_40_kmh':weighted('extra_persona_min_dia_a_40_kmh'),
                'vehiculo_km_en_dias_construidos':float((mm.km*mm.peso_dias).sum()),
                'vehiculo_min_circulacion_en_dias_construidos':float(((mm.llegada_min-mm.salida_min)*mm.peso_dias).sum()),
                'actividad_programada_cubre_366_dias':bool(profiles.cierre.all()),'energia_nueva_calculada':False}
            for label,field in [('habitual','km_alimentador_original_ida_vuelta'),('alternativa','km_alimentador_nuevo_ida_vuelta')]:
                row['vehiculo_km_alimentacion_'+label+'_de_visitas_trasladadas_anio']=float((tt.vehiculos_alimentadores_dia*tt[field]*tt.peso_dias).sum()) if not tt.empty else 0.
            if abs(row['vehiculo_km_alimentacion_alternativa_de_visitas_trasladadas_anio']-row['vehiculo_km_alimentacion_habitual_de_visitas_trasladadas_anio']-row['extra_vehiculo_km_alimentacion_anio'])>1e-8:
                raise ValueError('Los alimentadores brutos no conservan el incremento.')
            for family,g in mm.groupby('familia'):
                row['vehiculo_km_'+family+'_en_dias_construidos']=float((g.km*g.peso_dias).sum())
            # Una circulación integrada contiene acceso e interior: separo sus
            # arcos, sin contar dos veces la misma guagua o su recorrido.
            for category in ['acceso','interior']:
                for service in ['comercial','vacio']:
                    row[f'vehiculo_km_{category}_{service}_en_dias_construidos']=0.
                    row[f'vehiculo_min_circulacion_{category}_{service}_en_dias_construidos']=0.
            for (origin,destination,family),weight in mm.groupby(['origen','destino','familia']).peso_dias.sum().items():
                for u,v in red.conectar(origin,destination)['arcos']:
                    category='acceso' if u.startswith('cabecera:') or v.startswith('cabecera:') else 'interior'
                    service='vacio' if family=='Vacío' else 'comercial'
                    minutes,km=red.arcos[u,v]
                    row[f'vehiculo_km_{category}_{service}_en_dias_construidos']+=weight*km
                    row[f'vehiculo_min_circulacion_{category}_{service}_en_dias_construidos']+=weight*minutes
            total_split=sum(row[f'vehiculo_km_{a}_{b}_en_dias_construidos'] for a in ['acceso','interior'] for b in ['comercial','vacio'])
            if abs(total_split-row['vehiculo_km_en_dias_construidos'])>1e-8:raise ValueError('El desglose por arcos pierde kilómetros de guagua.')
            rows.append(row)
        bad=res[~res.cierre].copy();bad['caso']=caso;pendientes.append(bad)
    destino.mkdir(parents=True,exist_ok=True)
    outputs={'comparacion':pd.DataFrame(rows),'comprobaciones_pendientes':pd.concat(pendientes,ignore_index=True)}
    for n,t in outputs.items():t.to_csv(destino/(n+'.csv'),sep=';',index=False,encoding='utf-8-sig',float_format='%.17g')
    provenance={'decision':'D251','hipotesis':'H141','fuente_nueva':'F164','capturas':hashes,
        'limites':['2,45 millones es una sensibilidad del-2 % respecto a la referencia aproximada; no nueva observación.',
            'La actividad programada solo suma días con circulación construida. No completa jornadas pendientes ni acredita un ahorro anual.',
            'TITSA mantiene el corredor nativo; traslado únicamente coche→lanzadera con alimentador propio. Regreso al mismo aparcamiento y destino interior conservado.',
            'La regla tiene búsqueda acotada; el traslado elegido minimiza personas y luego km entre las alternativas ensayadas con circulación construida. No acredita mínimo global.',
            'Tiempo incremental auxiliar a40km/h, no calibrado; no afecta a COPERT o a los horarios de guaguas. Tiempo OSRM del recorrido nuevo conservado por separado.',
            'Las cotas de excursión de los tres extremos son diagnósticos SIN reasignación de cabecera: su fórmula conserva los modos por origen. No son aumentos necesarios después del traslado.'],
        'codigo_sha256':{n:sha256_archivo(root/n) for n in ['src/movilidad_teide/flujos/comparacion_cabeceras.py','scripts/contrastar_volumen_cabeceras_2028.py','scripts/auditar_cabeceras_2028.py']},
        'cartografia_validacion_sha256':{str(p.relative_to(root)):sha256_archivo(p) for p in [root/'config/itinerarios.json',root/'data/silver/demanda/asignacion/recorridos_representacion_estudio.csv',*sorted((root/'data/bronze/documentacion/contexto_informe/cartografia_parque/PN_Teide/Limites').glob('Limite_Teide.*'))] if p.is_file()},
        'resultados_sha256':{(n+'.csv'):sha256_archivo(destino/(n+'.csv')) for n in outputs}}
    (destino/'metadatos_comparacion.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    return outputs


def generar_comparacion(root,destino,*,pasos=1800):
    root,destino=Path(root).resolve(),Path(destino).resolve()
    if destino.exists():raise FileExistsError('Conservar capturas anteriores; elegir otro destino.')
    # El guardián del productor comprueba cada captura antes de escribir.
    paths={'250_habitual':root/REFERENCIA}
    for caso,(total,reasignar) in CASOS.items():
        if caso=='250_habitual':continue
        paths[caso]=destino/caso
        generar_cierre_anual(root,paths[caso],pasos=pasos,alternativa='650_enero',total=total,reasignar=reasignar)
    return comparar_capturas(root,paths,destino)
