"""Compruebo el p85 de P15/P20 sin sustituir las comprobaciones de las puntas."""
from pathlib import Path
import json
import platform
import math
import numpy as np
import pandas as pd

from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.demanda.escenarios_2028 import construir_escenarios
from movilidad_teide.demanda.excursiones_2028 import reasignar_excursiones
from movilidad_teide.demanda.p85_alternativas import reconstruir_muestra,cambiar_fechas_muestra,repartir_horas_muestra,resumir_percentiles,representar_ceros_numericos,trasladar_horas
from movilidad_teide.demanda.perfiles_operacion_2028 import COLECTIVOS
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.operacion.reservas import auditar_perfil_reservado_p85
from movilidad_teide.operacion.refinar_reservas import refinar_perfil
from movilidad_teide.operacion.reloj_integrado import RelojIntegrado
from movilidad_teide.flujos.redistribucion_2028 import relojes_iniciales,cerrar_perfil,E15,Q15
from movilidad_teide.trazabilidad import sha256_archivo
from .operacion_2028 import FUENTES,BASE as REFERENCIA
from .compartida_2028 import BASE,PARADAS
from .tipos import Etapa

ANTERIOR="data/silver/movilidad/redistribucion_2028/20261108_excursiones_y_fechas"
SALIDAS="data/silver/movilidad/p85_alternativas_2028"


def preparar_p85_alternativas(root):
    root=Path(root).resolve();fuentes={}
    def registrar(p,h=None):
        actual=sha256_archivo(root/p)
        if h is not None and h!=actual:raise ValueError(f"Captura de referencia modificada: {p}")
        fuentes[p]=actual
    registrar(ANTERIOR+"/metadatos.json")
    old=json.loads((root/ANTERIOR/"metadatos.json").read_text())
    for p,h in old["fuentes_sha256"].items():registrar(p,h)
    for p,h in old["resultados_sha256"].items():registrar(ANTERIOR+"/"+p,h)
    rd=lambda p:pd.read_csv(root/p,sep=";",float_precision="round_trip")
    param=leer_parametros(root);v={p["id"]:p["valor_utilizado"] for p in param["parametros"]}
    if (v["cupo_global"]!=500 or v["percentil_diseno"]!=.85 or v["vehiculos_contrato_contraste"]!=30
        or v["reserva_minima_dentro_flota"]!=3 or v["intervalo_refuerzo_punta_min"]!=15
        or int(v["plazas_guagua"]*v["ocupacion_diseno"])!=46):raise ValueError("Revisar las condiciones conservadas.")
    perfiles,indices,origenes=rd(FUENTES["perfiles"]),rd(FUENTES["indices"]),rd(FUENTES["origenes"])
    media=rd(REFERENCIA+"/demanda_horaria_2028.csv")
    frac=json.loads((root/REFERENCIA/"metadatos.json").read_text())["fraccion_coche_conservada"]
    red=RedOperativa(rd(BASE+"/movimientos_diagnosticos.csv"),rd(BASE+"/pares_diagnosticos.csv"),rd(PARADAS))
    inv=rd(ANTERIOR+"/inventario_30.csv");ids=inv.groupby("base_red").unidad_fisica_id.apply(list).to_dict();caps={b:len(a) for b,a in ids.items()}
    if len(inv)!=30 or inv.unidad_fisica_id.duplicated().any():raise ValueError("No son treinta identidades conservadas.")
    cuotas=old["cuotas_coches_dia"]
    capt=dict(zip(COLECTIVOS,[v[k] for k in ["captacion_extranjero","captacion_nacional","captacion_local","captacion_frecuente"]]))
    prev=rd(ANTERIOR+"/puntos.csv");tables={};summ=[];checks=[];calibraciones=[];refinados={}
    def add(n,df,**tag):tables.setdefault(n,[]).append(df.assign(**tag))
    for festivo in ["Domingo","minimo","maximo"]:
        h,cal=reconstruir_muestra(perfiles,indices,media,total=2500000,fraccion_coche=frac,
            hora_inicio=v["hora_inicio_acceso"],hora_fin=v["hora_fin_acceso"],festivos=festivo)
        add("reparto_titsa_diagnostico",h[["matrix_index","access_corridor","colectivo","ventana_captacion","titsa_grupo_dia_referencia","titsa_grupo_dia","reparto_titsa_adaptado"]].drop_duplicates(),referencia_festivos=festivo)
        calibraciones.append({"referencia_festivos":festivo,**cal})
        bases={int(obs):construir_escenarios(g,origenes,ocupacion=v["ocupacion_coche"],cupo=550,captaciones=capt,
            hora_inicio=v["hora_inicio_acceso"],hora_fin=v["hora_fin_acceso"],cuotas_por_tipo={g.tipo_dia_publicado.iloc[0]:cuotas}) for obs,g in h.groupby("matrix_index")}
        for alternativa,es in [("P15",E15),("P20",{**E15,"Julio":.20})]:
            modales={};limitadas=[]
            for obs,z in bases.items():
                dato=indices.set_index("matrix_index").loc[obs]
                rate=es.get(dato.mes_publicado,0.) if dato.tipo_dia_publicado!="Festivo/especial" else 0.
                x=z["por_origen_dia"]
                maximo=float((x.visitas_coche_transferidas_dia/x.visitas_excursiones_resto_colectivo.replace(0,np.nan)).min())
                compatible=rate<=maximo+1e-12
                # Contraste conservador declarado: si el objetivo uniforme no
                # puede proceder de lanzadera en todos los orígenes, mantengo
                # excursión sin incremento en esa observación. No reduzco la
                # demanda de lanzadera para fabricar capacidad. El caso exacto
                # queda identificado como inaplicable, nunca validado.
                aplicado=rate if compatible else 0.
                modal=reasignar_excursiones(z,incremento=aplicado,ocupacion=v["ocupacion_coche"])
                modales[obs],residuos=representar_ceros_numericos(modal,ocupacion=v["ocupacion_coche"])
                if not residuos.empty:add("residuos_redondeo",residuos.assign(matrix_index=obs),alternativa=alternativa,referencia_festivos=festivo)
                if not compatible:limitadas.append(obs)
                add("aplicabilidad_incrementos",pd.DataFrame([{"matrix_index":obs,"incremento_objetivo":rate,
                    "incremento_maximo_compatible_todos_origenes":maximo,"objetivo_exacto_aplicable":compatible,
                    "incremento_contraste_conservador":aplicado}]),alternativa=alternativa,referencia_festivos=festivo)
            horario_modal=repartir_horas_muestra(modales,h)
            for cumplimiento in ([1.,.5,0.] if festivo=="Domingo" else [1.]):
                tag={"alternativa":alternativa,"cumplimiento_cambio_fecha":cumplimiento,"referencia_festivos":festivo}
                zs,tr=cambiar_fechas_muestra(modales,indices,Q15,ocupacion=v["ocupacion_coche"],cumplimiento=cumplimiento)
                ds=pd.concat([z["escenarios_por_punto_dia"].assign(matrix_index=obs) for obs,z in zs.items()],ignore_index=True)
                ds=ds.merge(indices[["matrix_index","anio","mes_publicado","tipo_dia_publicado"]].rename(columns={"anio":"anio_fuente","tipo_dia_publicado":"tipo_fuente"}),on="matrix_index",validate="many_to_one")
                hs=trasladar_horas(horario_modal,indices,Q15,cumplimiento=cumplimiento,hora_inicio=v["hora_inicio_acceso"],hora_fin=v["hora_fin_acceso"])
                got=hs.groupby(["matrix_index","punto"]).personas_lanzadera.sum().sort_index()
                expected=ds.set_index(["matrix_index","punto"]).demanda_lanzadera_dia.sort_index()
                if not np.allclose(got,expected,rtol=0,atol=1e-8):raise ValueError("El cambio horario y el diario no conservan los mismos viajeros.")
                d,hp,globales=resumir_percentiles(ds,hs,percentil=v["percentil_diseno"])
                add("observaciones_diarias",ds,**tag);add("observaciones_horarias",hs,**tag)
                add("p85_diario",d,**tag);add("p85_horario",hp,**tag)
                if not tr.empty:add("traspasos_muestra",tr,**tag)
                if festivo=="Domingo":
                    ox=pd.concat([z["por_origen_dia"].assign(matrix_index=obs) for obs,z in zs.items()],ignore_index=True)
                    add("origenes_muestra",ox,**tag)
                if festivo=="Domingo" and cumplimiento==1:
                    for obs in indices.loc[indices.anio.eq(2025),"matrix_index"]:
                        ref=prev.loc[prev.caso.eq(alternativa)&prev.observacion.eq(obs)].set_index("punto")
                        for col in ["demanda_lanzadera_dia","visitas_coche_autorizadas_dia","visitas_excursiones_con_intervencion_dia","visitas_titsa","visitas_sin_dia","visitas_con_objetivo_dia"]:
                            error=float((zs[obs]["escenarios_por_punto_dia"].set_index("punto")[col]-ref[col]).abs().max())
                            if error>1e-8:raise ValueError(f"Cambio no explicado frente a D242: {alternativa}/{obs}/{col}/{error}")
                            checks.append({**tag,"control":f"D242 matriz{obs}: {col}","error_maximo":error,"tolerancia":1e-8,"correcto":True})
                # El p85 diario no se sustituye por suma de percentiles horarios.
                # Se comprueba aparte la envolvente de la ventana de captación.
                for diseno in ["p85_diario","diario_y_envolvente_ventana"]:
                    target=d.personas_p85_total_dia.to_numpy()
                    if diseno!="p85_diario":target=np.maximum(target,d.suma_p85_horarios_ventana.to_numpy())
                    pt=pd.DataFrame({"punto":d.punto,"demanda_lanzadera_dia":target})
                    pt["demanda_bruta_lanzadera_dia"]=target+pt.punto.map(cuotas)*v["ocupacion_coche"]
                    limites=[]
                    for pto,cantidad in zip(pt.punto,target):
                        a=red.conectar("cabecera:"+pto,red.destinos.loc[pto,"parada_entrada"])["minutos"]
                        ventana=60*v["hora_limite_bajada_parque"]-v["estancia_min_visita_min"]-a-60*v["hora_inicio_acceso"]
                        max_salidas=math.floor(ventana/v["intervalo_refuerzo_punta_min"])+1
                        limites.append({"punto":pto,"demanda_diseno_personas":float(cantidad),"maximo_salidas_con_intervalo":max_salidas,
                            "salidas_necesarias":math.ceil((cantidad-1e-8)/46),"capacidad_maxima_intervalo_personas":46*max_salidas,
                            "exceso_sobre_capacidad_intervalo_personas":max(0.,cantidad-46*max_salidas)})
                    add("limites_acceso_p85",pd.DataFrame(limites),**tag,diseno=diseno)
                    error="";candidatos=[];cierre=None;refid=""
                    if any(l["exceso_sobre_capacidad_intervalo_personas"]>1e-8 for l in limites):
                        error="La ventana de acceso y el intervalo de quince minutos no permiten las salidas requeridas."
                    else:
                        candidatos=relojes_iniciales(pt,red,v,cuotas)
                        clave=tuple(map(float,target))
                        if festivo=="Domingo" and cumplimiento==1 and clave not in refinados:
                            ajuste=refinar_perfil(pt,red,v,cuotas,pasos=1200,semilla=24315 if alternativa=="P15" else 24320)
                            reloj=RelojIntegrado(pt,red,v,cuotas);us=[];bs=[]
                            vt=ajuste["viajes"].set_index("id_salida")
                            for q in red.puntos:
                                grupos=ajuste["reservas"].loc[lambda t:t.punto.eq(q)].sort_values("id_subida")
                                us.append(vt.loc[grupos.id_subida,"salida_min"].to_numpy());bs.append(grupos.regreso_parque_min.to_numpy())
                            n,e=reloj.evaluar(us,bs)
                            if n!=ajuste["cadenas"]:raise ValueError("El reloj refinado no reproduce su encadenamiento.")
                            refid=alternativa+"_nominal"
                            refinados[clave]=(((n,-e,"ajuste_individual",0.),reloj,us,bs),refid)
                            add("refinamiento_p85",ajuste["reinicios"],alternativa=alternativa,referencia_refinamiento=refid)
                            add("reloj_refinado_diagnostico",ajuste["viajes"],alternativa=alternativa,referencia_refinamiento=refid)
                            add("reservas_refinadas_diagnostico",ajuste["reservas"],alternativa=alternativa,referencia_refinamiento=refid)
                        if clave in refinados:
                            candidato,refid=refinados[clave];candidatos.append(candidato);candidatos.sort(key=lambda c:c[0])
                        cierre=cerrar_perfil(candidatos,red,v,caps,ids)
                        if cierre is None:error="El catálogo no construye cierre con hasta27 programadas y las treinta identidades."
                    row={**tag,"diseno":diseno,**globales,"demanda_diseno_visitas_persona_dia":float(target.sum()),
                        "objetivo_uniforme_aplicable_todas_matrices":not limitadas,"matrices_sin_incremento_extra_por_incompatibilidad":len(limitadas),
                        "menor_programacion_catalogo":candidatos[0][0][0] if candidatos else np.nan,"programadas_con_cierre":cierre["n"] if cierre else np.nan,
                        "flota_fisica":30,"minimo_sustitucion":3,"cierre_30_con_tres_libres":cierre is not None,
                        "referencia_reloj_refinado":refid,
                        "motivo_si_no_cierra":error,"energia_calculada":False,"operacion_anual_completa_validada":False}
                    if cierre:
                        plan={**tag,"diseno":diseno}
                        for k in ["cronologias","reservas","movimientos"]:add(k,cierre["viajes" if k=="cronologias" else k],**plan)
                        disp=[];mov=cierre["movimientos"]
                        for unidad in inv.itertuples():
                            mm=mov[mov.unidad_fisica_id.eq(unidad.unidad_fisica_id)].sort_values("salida_min")
                            if not mm.empty and mm.iloc[0].origen!=unidad.base_red:raise ValueError("Identidad fuera de su base inicial.")
                            disp.append({"unidad_fisica_id":unidad.unidad_fisica_id,"base_inicial":unidad.base_red,
                                "base_final":mm.iloc[-1].destino if not mm.empty else unidad.base_red,"programada":not mm.empty})
                        add("disponibilidad",pd.DataFrame(disp),**plan)
                        pares=cierre["reservas"].merge(cierre["viajes"][["id_salida","salida_min"]],left_on="id_subida",right_on="id_salida",validate="one_to_one")
                        fuera=0.
                        for punto,g in hp.loc[hp.dentro_ventana_fuente].groupby("punto"):
                            audit=auditar_perfil_reservado_p85(g,pares[pares.punto.eq(punto)],capacidad=46,espera=v["espera_max_lanzadera_min"],cambio_franja=True)
                            add("asignacion_horaria_p85",audit["por_hora"].assign(punto=punto),**plan)
                            add("asignacion_cadenas_p85",audit["por_cadena"].assign(punto=punto),**plan)
                            fuera+=audit["sin_asignacion"]
                        row["p85_ventana_sin_asignacion_personas"]=fuera
                        row["p85_diario_y_ventana_atendidos"]=fuera<1e-8
                        if not np.isclose(cierre["reservas"].personas.sum(),target.sum(),rtol=0,atol=1e-8):raise ValueError("La reserva no conserva el objetivo p85.")
                    summ.append(row)
    joined={n:pd.concat(frames,ignore_index=True) for n,frames in tables.items()}
    joined["resumen"]=pd.DataFrame(summ);joined["calibracion"]=pd.DataFrame(calibraciones)
    joined["controles_D242"]=pd.DataFrame(checks);joined["inventario_30"]=inv
    joined["indices_muestra"]=indices;joined["origenes_sin_cantidad_anual"]=origenes.loc[~origenes.en_ambito_anual].copy()
    meta={"decision":"D243","hipotesis":"H133","fecha":"2026-11-08","parametros_conservados":param,"fuentes_sha256":fuentes,
        "alternativas":{"P15":E15,"P20":{**E15,"Julio":.20}},"fracciones_cambio_fecha":Q15,
        "busqueda":{"formas_iniciales":7,"reinicios_por_alternativa_nominal":2,"pasos_por_reinicio":1200,"semillas":{"P15":[24315,24316],"P20":[24320,24321]},"minimo_global_demostrado":False},
        "limites":["57 matrices multianuales, con correspondencias inferidas: el percentil de esta muestra no es probabilidad anual de servicio2028.",
            "La escala conserva la referencia anual2,5 millones y la misma regla por matriz; no anualiza el p85 ni normaliza cada matriz.",
            "Cambio de fecha solo entre ternas completas del mismo año/mes; especiales no se trasladan ni reciben aumento de excursión no definido.",
            "El objetivo uniforme no se fuerza si algún origen carece de viajeros suficientes de lanzadera. La observación exacta se marca incompatible y el contraste de p85 mantiene allí excursiones sin incremento, con más viajeros en lanzadera. No se valida el objetivo exacto en toda la muestra.",
            "TITSA de especiales aproximado por domingo, con sensibilidad a extremos de referencias conocidas; no calendario de operador acreditado.",
            "Cuando el reparto estimado de TITSA asignaría más pasajeros a un colectivo que su población colectiva OD, se conserva el total del corredor/ventana y se adapta solo el reparto entre colectivos compatibles. Se registran todas las diferencias;2025 debe reproducirse intacto.",
            "El p85 diario por acceso y el p85 total del sistema no se suman como medidas equivalentes. La envolvente horaria se muestra aparte.",
            "Horas ausentes conservan su falta de cobertura; el percentil horario usa solo agregados con todas sus fuentes publicadas.",
            "Reservas permiten cambiar de franja; no son llegadas observadas a cabeceras. El p85 horario auditado se limita a la ventana de captación, como el precedente.",
            "El acceso y visita interior representados usan cadenas completas; excursiones con su servicio propio y otros usuarios interiores conservan su alcance anterior.",
            "Superar p85 no garantiza las puntas o un cambio de fecha real; tres libres siguen siendo sustitución, no oferta ordinaria.",
            "No se calcula energía, cambia el Excel, actualiza el informe o sobrescriben ejecuciones anteriores."],
        "entorno":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__}}
    return Etapa(joined),meta


def generar_p85_alternativas(root,destino):
    root,destino=Path(root).resolve(),Path(destino).resolve();permitido=(root/SALIDAS).resolve()
    if destino==permitido or destino.is_relative_to(root) and not destino.is_relative_to(permitido):raise ValueError("Elegir una captura nueva fuera de fuentes e informe.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):raise FileExistsError("La ejecución anterior se conserva.")
    etapa,meta=preparar_p85_alternativas(root);destino.mkdir(parents=True,exist_ok=True)
    for n,t in etapa.tablas.items():t.to_csv(destino/(n+".csv"),sep=";",index=False,encoding="utf-8-sig",float_format="%.17g")
    paquete=Path(__file__).parents[1]
    nombres=["demanda/p85_alternativas.py","flujos/p85_alternativas.py","flujos/redistribucion_2028.py","demanda/redistribucion_temporal.py",
        "demanda/excursiones_2028.py","demanda/escenarios_2028.py","demanda/perfiles_operacion_2028.py","operacion/reloj_integrado.py",
        "operacion/reservas.py","operacion/refinar_reservas.py","operacion/horarios_compartidos.py","operacion/inventario_comun.py",
        "operacion/circulacion_compartida.py","operacion/red_compartida.py"]
    meta["codigo_sha256"]={"movilidad_teide/"+n:sha256_archivo(paquete/n) for n in nombres}
    meta["codigo_sha256"]["scripts/comprobar_p85_alternativas.py"]=sha256_archivo(paquete.parents[1]/"scripts/comprobar_p85_alternativas.py")
    meta["resultados_sha256"]={p.name:sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    (destino/"metadatos.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
    return etapa,meta
