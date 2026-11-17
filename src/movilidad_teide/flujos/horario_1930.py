"""Compruebo nueve perfiles, p85 y cumplimiento parcial con regreso a las19:30."""
from pathlib import Path
import json
import platform
import numpy as np
import pandas as pd

from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.operacion.reservas import auditar_perfil_reservado_p85
from movilidad_teide.operacion.ventana_horaria import cerrar_en_ventana
from movilidad_teide.operacion.refinar_reservas import refinar_perfil
from movilidad_teide.operacion.reloj_integrado import RelojIntegrado
from movilidad_teide.operacion.luz_diurna import leer_tabla_ign,FUENTE_IGN,URL_IGN
from movilidad_teide.flujos.redistribucion_2028 import relojes_iniciales
from movilidad_teide.trazabilidad import sha256_archivo
from .compartida_2028 import BASE,PARADAS
from .tipos import Etapa

ANTERIOR="data/silver/demanda/referencias_temporales/p85_P15_P20"
DEMANDA="data/silver/movilidad/redistribucion_2028/20261108_excursiones_y_fechas"
SALIDAS="data/silver/movilidad/horario_1930_2028"


def preparar_horario_1930(root):
    root=Path(root).resolve();fuentes={}
    def registrar(p,h=None):
        actual=sha256_archivo(root/p)
        if h is not None and h!=actual:raise ValueError(f"Referencia previa modificada: {p}")
        fuentes[p]=actual
    registrar(ANTERIOR+"/metadatos.json");old=json.loads((root/ANTERIOR/"metadatos.json").read_text())
    for p,h in old["fuentes_sha256"].items():registrar(p,h)
    for p,h in old["resultados_sha256"].items():registrar(ANTERIOR+"/"+p,h)
    rd=lambda p:pd.read_csv(root/p,sep=";",float_precision="round_trip")
    param=leer_parametros(root);v={p["id"]:p["valor_utilizado"] for p in param["parametros"]}
    if (v["cupo_global"]!=500 or v["reserva_minima_dentro_flota"]!=3 or v["vehiculos_contrato_contraste"]!=30
        or v["intervalo_refuerzo_punta_min"]!=15 or int(v["plazas_guagua"]*v["ocupacion_diseno"])!=46
        or v["regulacion_min"]!=10 or v["estancia_min_visita_min"]!=120):raise ValueError("Revisar condiciones conservadas.")
    # Solo cambia la ventana operativa. La captación OD7–19 y la demanda
    # previamente calculada no se recalculan o expanden al ampliar el servicio.
    operacion={**v,"hora_inicio_acceso":7.,"hora_limite_bajada_parque":19.5}
    inicio,fin=420.,1290.
    cuotas=json.loads((root/DEMANDA/"metadatos.json").read_text())["cuotas_coches_dia"]
    if sum(cuotas.values())!=550:raise ValueError("El contraste conserva el cupo de550.")
    inv=rd(ANTERIOR+"/inventario_30.csv");ids=inv.groupby("base_red").unidad_fisica_id.apply(list).to_dict();caps={b:len(z) for b,z in ids.items()}
    red=RedOperativa(rd(BASE+"/movimientos_diagnosticos.csv"),rd(BASE+"/pares_diagnosticos.csv"),rd(PARADAS))
    diario=rd(ANTERIOR+"/observaciones_diarias.csv").loc[lambda t:t.referencia_festivos.eq("Domingo")&t.anio_fuente.eq(2025)]
    p85=rd(ANTERIOR+"/p85_diario.csv").loc[lambda t:t.referencia_festivos.eq("Domingo")]
    hp=rd(ANTERIOR+"/p85_horario.csv").loc[lambda t:t.referencia_festivos.eq("Domingo")]
    tablas={};resumen=[]
    def add(n,t,**tag):tablas.setdefault(n,[]).append(t.assign(**tag))
    jobs=[]
    for (alt,cumpl,obs),g in diario.groupby(["alternativa","cumplimiento_cambio_fecha","matrix_index"]):
        jobs.append(({"alternativa":alt,"cumplimiento_cambio_fecha":cumpl,"tipo_comprobacion":"Perfil2025","observacion":int(obs),
            "perfil":g.mes_publicado.iloc[0]+" · "+g.tipo_fuente.iloc[0]},g[["punto","demanda_lanzadera_dia"]].copy()))
    for (alt,cumpl),g in p85.groupby(["alternativa","cumplimiento_cambio_fecha"]):
        jobs.append(({"alternativa":alt,"cumplimiento_cambio_fecha":cumpl,"tipo_comprobacion":"p85 compuesto","observacion":-85,"perfil":"p85 por acceso de57 matrices"},
                     g[["punto","personas_p85_total_dia"]].rename(columns={"personas_p85_total_dia":"demanda_lanzadera_dia"})))
    for tag,pt in jobs:
        pt=pt.copy();pt["demanda_bruta_lanzadera_dia"]=pt.demanda_lanzadera_dia+pt.punto.map(cuotas)*v["ocupacion_coche"]
        cs=relojes_iniciales(pt,red,operacion,cuotas)
        cerrado=cerrar_en_ventana(cs,red,operacion,caps,ids,inicio_min=inicio,fin_min=fin)
        if cerrado is None:
            seed=24400+(15 if tag["alternativa"]=="P15" else 20)+int(tag["observacion"])+int(tag["cumplimiento_cambio_fecha"]*100)
            ajuste=refinar_perfil(pt,red,operacion,cuotas,pasos=1200,semilla=seed)
            reloj=RelojIntegrado(pt,red,operacion,cuotas);vt=ajuste["viajes"].set_index("id_salida");us=[];bs=[]
            for q in red.puntos:
                grupos=ajuste["reservas"].loc[lambda t:t.punto.eq(q)].sort_values("id_subida")
                us.append(vt.loc[grupos.id_subida,"salida_min"].to_numpy());bs.append(grupos.regreso_parque_min.to_numpy())
            n,e=reloj.evaluar(us,bs);cs.append(((n,-e,"ajuste_individual",0.),reloj,us,bs));cs.sort(key=lambda c:c[0])
            add("refinamiento",ajuste["reinicios"],**tag)
            cerrado=cerrar_en_ventana(cs,red,operacion,caps,ids,inicio_min=inicio,fin_min=fin)
        add("objetivos",pt,**tag)
        row={**tag,"demanda_lanzadera_visitas_persona_dia":float(pt.demanda_lanzadera_dia.sum()),"menor_programacion_siete_formas":cs[0][0][0],
             "cierre_con_30_y_tres_sustitutas":cerrado is not None,"programadas":np.nan,"sin_programar":np.nan,"minimo_global_demostrado":False}
        if cerrado:
            row.update({"programadas":cerrado["programadas"],"sin_programar":30-cerrado["programadas"],
                "primera_salida_base_min":float(cerrado["movimientos"].salida_min.min()),"ultima_llegada_base_min":float(cerrado["movimientos"].llegada_min.max()),
                "ultimo_paso_regreso_parque_min":float(cerrado["reservas"].regreso_parque_min.max()),"forma":cerrado["forma"],"fraccion_regreso":cerrado["fraccion_regreso"]})
            comerciales=cerrado["viajes"].loc[lambda t:t.destino.str.startswith("cabecera:")]
            row["ultima_llegada_cabecera_min"]=float(comerciales.llegada_min.max())
            if abs(cerrado["reservas"].personas.sum()-pt.demanda_lanzadera_dia.sum())>1e-8:raise ValueError("El horario pierde viajeros.")
            for n in ["cronologias","reservas","movimientos"]:add(n,cerrado["viajes" if n=="cronologias" else n],**tag)
            disp=[];moves=cerrado["movimientos"]
            for unidad in inv.itertuples():
                m=moves[moves.unidad_fisica_id.eq(unidad.unidad_fisica_id)].sort_values("salida_min")
                if not m.empty and m.iloc[0].origen!=unidad.base_red:raise ValueError("La identidad no parte de su base original.")
                disp.append({"unidad_fisica_id":unidad.unidad_fisica_id,"programada":not m.empty,"base_inicial":unidad.base_red,"base_final":m.iloc[-1].destino if not m.empty else unidad.base_red})
            add("disponibilidad_30",pd.DataFrame(disp),**tag)
            if tag["observacion"]==-85:
                hh=hp[hp.alternativa.eq(tag["alternativa"])&hp.cumplimiento_cambio_fecha.eq(tag["cumplimiento_cambio_fecha"])&hp.dentro_ventana_fuente]
                pares=cerrado["reservas"].merge(cerrado["viajes"][["id_salida","salida_min"]],left_on="id_subida",right_on="id_salida",validate="one_to_one")
                fuera=0.
                for punto,g in hh.groupby("punto"):
                    test=auditar_perfil_reservado_p85(g,pares[pares.punto.eq(punto)],capacidad=46,espera=v["espera_max_lanzadera_min"],cambio_franja=True)
                    fuera+=test["sin_asignacion"];add("asignacion_p85_horaria",test["por_hora"].assign(punto=punto),**tag)
                row["p85_ventana_sin_asignacion_personas"]=fuera;row["p85_diario_y_ventana_atendidos"]=fuera<1e-8
        resumen.append(row)
    joined={n:pd.concat(z,ignore_index=True) for n,z in tablas.items()};joined["resumen"]=pd.DataFrame(resumen);joined["inventario_30"]=inv
    joined["sintesis"]=joined["resumen"].groupby(["alternativa","cumplimiento_cambio_fecha","tipo_comprobacion"],as_index=False).agg(
        perfiles=("observacion","size"),perfiles_con_cierre=("cierre_con_30_y_tres_sustitutas","sum"),maximo_programadas=("programadas","max"),minimo_sin_programar=("sin_programar","min"),
        mayor_menor_programacion_catalogo=("menor_programacion_siete_formas","max"),ultimo_paso_parque_min=("ultimo_paso_regreso_parque_min","max"),ultima_llegada_base_min=("ultima_llegada_base_min","max"))
    registrar(FUENTE_IGN)
    solar=leer_tabla_ign(root/FUENTE_IGN);joined["referencia_solar_2028"]=solar
    sol=[]
    for (alt,cumpl),g in joined["resumen"].groupby(["alternativa","cumplimiento_cambio_fecha"]):
        if not g.cierre_con_30_y_tres_sustitutas.all():continue
        tiempos={"ultimo_paso_parque":g.ultimo_paso_regreso_parque_min.max(),"ultima_llegada_cabecera":g.ultima_llegada_cabecera_min.max(),"ultima_llegada_base":g.ultima_llegada_base_min.max()}
        ss=solar.copy()
        for k,t in tiempos.items():ss[k+"_min"]=t;ss[k+"_menos_ocaso_min"]=t-ss.ocaso_min
        sol.append(ss.assign(alternativa=alt,cumplimiento_cambio_fecha=cumpl))
    if sol:joined["contraste_solar"]=pd.concat(sol,ignore_index=True)
    meta={"decision":"D244","hipotesis":"H134","fecha":"2026-11-08","parametros_conservados":param,"fuentes_sha256":fuentes,
        "ventana_operativa_contrastada":{"primera_salida_cabecera":"07:00","ultimo_paso_regreso_entrada_parque":"19:30","fin_ventana_bases":"21:30","horas_locales":"Atlantic/Canary"},
        "captacion_OD_original_sin_cambios":True,"cumplimientos_cambio_fecha":[1.,.5,0.],"cuotas_coches_dia":cuotas,
        "busqueda":{"formas_por_perfil":7,"refinamiento_si_no_cierra":{"reinicios":2,"pasos_por_reinicio":1200,"semilla":"24400 +15/20 +observación +100×cumplimiento"},"minimo_global_demostrado":False},
        "fuente_solar":{"registro":"F163","url":URL_IGN,"lugar":"Santa Cruz de Tenerife","anio":2028,"pagina":1,
                        "alcance":"Referencia de horizonte ideal, sin rasante, relieve, nubes o niebla; no acredita luz efectiva del itinerario ni un horario permitido."},
        "limites":["El cierre de flota no acredita operación anual completa, horarios aprobados, turnos o personal.",
            "Los nueve perfiles y el p85 compuesto son comprobaciones diferentes. El p85 sigue conservando las limitaciones de muestra y extensión D243.",
            "Cumplimiento1/0,5/0 se aplica al cambio de fecha, no al incremento de excursiones. Las alternativas conservan la misma demanda anual por escenario de planificación.",
            "Reservas flexibles y visita interior representada conservadas; excursiones con servicio propio, otros usuarios interiores, destinos y giros pendientes.",
            "19:30 es el paso por la entrada del Parque en regreso hacia cabeceras, no la llegada de todos los viajeros a su origen. Las bases pueden cerrar hasta21:30.",
            "El encaje de vehículos no garantiza luz diurna: la estacionalidad debe contrastarse aparte sin cambiar aquí demanda o horarios para obtener un saldo favorable.",
            "No se calcula energía o ahorro, modifica el libro, actualiza el informe o sobrescribe una ejecución anterior."],
        "entorno":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__}}
    return Etapa(joined),meta


def generar_horario_1930(root,destino):
    root,destino=Path(root).resolve(),Path(destino).resolve();permitido=(root/SALIDAS).resolve()
    if destino==permitido or destino.is_relative_to(root) and not destino.is_relative_to(permitido):raise ValueError("Elegir una captura nueva fuera de fuentes e informe.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):raise FileExistsError("La ejecución anterior se conserva.")
    etapa,meta=preparar_horario_1930(root);destino.mkdir(parents=True,exist_ok=True)
    for n,t in etapa.tablas.items():t.to_csv(destino/(n+".csv"),sep=";",index=False,encoding="utf-8-sig",float_format="%.17g")
    paquete=Path(__file__).parents[1];nombres=["flujos/horario_1930.py","operacion/ventana_horaria.py","flujos/redistribucion_2028.py","operacion/reloj_integrado.py",
        "operacion/horarios_compartidos.py","operacion/circulacion_compartida.py","operacion/inventario_comun.py","operacion/red_compartida.py","operacion/reservas.py","operacion/refinar_reservas.py","operacion/luz_diurna.py"]
    meta["codigo_sha256"]={"movilidad_teide/"+n:sha256_archivo(paquete/n) for n in nombres}
    meta["codigo_sha256"]["scripts/comprobar_horario_1930.py"]=sha256_archivo(paquete.parents[1]/"scripts/comprobar_horario_1930.py")
    meta["resultados_sha256"]={p.name:sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    (destino/"metadatos.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
    return etapa,meta
