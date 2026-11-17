"""Contrasto P20 con llegadas comerciales anteriores al ocaso de referencia."""
from pathlib import Path
import json
import platform
import numpy as np
import pandas as pd

from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.operacion.invierno import limites_llegada_con_luz,relojes_de_invierno
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.operacion.refinar_reservas import mejorar_reloj
from movilidad_teide.operacion.ventana_horaria import cerrar_en_ventana
from movilidad_teide.operacion.reservas import auditar_perfil_reservado_p85
from movilidad_teide.operacion.luz_diurna import FUENTE_IGN,URL_IGN
from movilidad_teide.trazabilidad import sha256_archivo
from .horario_1930 import ANTERIOR,DEMANDA
from .compartida_2028 import BASE,PARADAS
from .tipos import Etapa

PREVIA="data/silver/movilidad/horario_1930_2028/20261108_nueve_p85_y_fechas"
SALIDAS="data/silver/movilidad/invierno_p20_2028"
MESES={"Noviembre":11,"Diciembre":12,"Enero":1,"Febrero":2}


def preparar_invierno_p20(root):
    root=Path(root).resolve();fuentes={}
    def registrar(p,h=None):
        actual=sha256_archivo(root/p)
        if h is not None and h!=actual:raise ValueError(f"Referencia previa modificada: {p}")
        fuentes[p]=actual
    registrar(PREVIA+"/metadatos.json");old=json.loads((root/PREVIA/"metadatos.json").read_text())
    for p,h in old["fuentes_sha256"].items():registrar(p,h)
    for p,h in old["resultados_sha256"].items():registrar(PREVIA+"/"+p,h)
    rd=lambda p:pd.read_csv(root/p,sep=";",float_precision="round_trip")
    param=leer_parametros(root);v={p["id"]:p["valor_utilizado"] for p in param["parametros"]}
    if (v["cupo_global"]!=500 or v["reserva_minima_dentro_flota"]!=3 or v["vehiculos_contrato_contraste"]!=30
        or v["intervalo_refuerzo_punta_min"]!=15 or int(v["plazas_guagua"]*v["ocupacion_diseno"])!=46
        or v["regulacion_min"]!=10 or v["estancia_min_visita_min"]!=120):raise ValueError("Revisar las condiciones conservadas.")
    op={**v,"hora_inicio_acceso":7.};cuotas=old["cuotas_coches_dia"]
    if sum(cuotas.values())!=550:raise ValueError("El contraste conserva el cupo de550.")
    inv=rd(ANTERIOR+"/inventario_30.csv");ids=inv.groupby("base_red").unidad_fisica_id.apply(list).to_dict();caps={b:len(i) for b,i in ids.items()}
    red=RedOperativa(rd(BASE+"/movimientos_diagnosticos.csv"),rd(BASE+"/pares_diagnosticos.csv"),rd(PARADAS))
    solar=rd(PREVIA+"/referencia_solar_2028.csv");solar["mes"]=pd.to_datetime(solar.fecha).dt.month
    ocaso_global=float(solar.ocaso_min.min());minimos=solar.groupby("mes").ocaso_min.min().to_dict()
    diario=rd(ANTERIOR+"/observaciones_diarias.csv").loc[lambda t:t.alternativa.eq("P20")&t.referencia_festivos.eq("Domingo")]
    p85=rd(ANTERIOR+"/p85_diario.csv").loc[lambda t:t.alternativa.eq("P20")&t.referencia_festivos.eq("Domingo")]
    hp=rd(ANTERIOR+"/p85_horario.csv").loc[lambda t:t.alternativa.eq("P20")&t.referencia_festivos.eq("Domingo")&t.dentro_ventana_fuente]
    tablas={};rows=[];jobs=[]
    def add(n,t,**tag):tablas.setdefault(n,[]).append(t.assign(**tag))
    winter=diario.loc[lambda t:t.mes_publicado.isin(MESES)&t.cumplimiento_cambio_fecha.eq(0)]
    for obs,g in winter.groupby("matrix_index"):
        tag={"ambito_demanda":"Muestra meses de poca luz","observacion":int(obs),"cumplimiento_cambio_fecha":0.,
             "perfil":f"{g.mes_publicado.iloc[0]} {int(g.anio_fuente.iloc[0])} · {g.tipo_fuente.iloc[0]}"}
        for calendario,ocaso in [("Fijo invierno",ocaso_global),("Mensual",float(minimos[MESES[g.mes_publicado.iloc[0]]]))]:
            jobs.append((tag,calendario,ocaso,g[["punto","demanda_lanzadera_dia"]].copy()))
    for (cumpl,obs),g in diario.loc[lambda t:t.anio_fuente.eq(2025)].groupby(["cumplimiento_cambio_fecha","matrix_index"]):
        tag={"ambito_demanda":"Estrés nueve2025","observacion":int(obs),"cumplimiento_cambio_fecha":float(cumpl),
             "perfil":g.mes_publicado.iloc[0]+"2025 · "+g.tipo_fuente.iloc[0]}
        jobs.append((tag,"Fijo invierno",ocaso_global,g[["punto","demanda_lanzadera_dia"]].copy()))
    for cumpl,g in p85.groupby("cumplimiento_cambio_fecha"):
        tag={"ambito_demanda":"Estrés p85 multianual","observacion":-85,"cumplimiento_cambio_fecha":float(cumpl),"perfil":"p85 por acceso de57 matrices"}
        jobs.append((tag,"Fijo invierno",ocaso_global,g[["punto","personas_p85_total_dia"]].rename(columns={"personas_p85_total_dia":"demanda_lanzadera_dia"})))
    for tag,calendario,ocaso,original in jobs:
        for margen in [0.,15.,30.]:
            tag={**tag,"calendario_luz":calendario,"margen_min":margen,"alternativa":"P20","caso_id":f"INV{len(rows)+1:03d}"}
            limites=limites_llegada_con_luz(red,op,ocaso_min=ocaso,margen_min=margen)
            # Se recibe la demanda neta ya validada. Este bruto es solo la interfaz
            # del reloj: no añade coches ni agota cuotas sin demanda suficiente.
            pt=original.copy();pt["demanda_bruta_lanzadera_dia"]=pt.demanda_lanzadera_dia+pt.punto.map(cuotas)*v["ocupacion_coche"]
            capacidad=pt.merge(limites,on="punto",validate="one_to_one")
            capacidad["salidas_necesarias"]=np.ceil((capacidad.demanda_lanzadera_dia-1e-8)/46).astype(int)
            capacidad["deficit_intervalo_personas"]=(capacidad.demanda_lanzadera_dia-capacidad.capacidad_maxima_intervalo_personas).clip(lower=0)
            add("limites_y_capacidad",capacidad,**tag);add("objetivos",pt,**tag)
            row={**tag,"demanda_lanzadera_visitas_persona_dia":float(pt.demanda_lanzadera_dia.sum()),"ocaso_referencia_min":ocaso,
                 "limite_llegada_cabecera_min":ocaso-margen,"intervalo_posible":bool(capacidad.deficit_intervalo_personas.max()<=1e-8),
                 "deficit_intervalo_personas":float(capacidad.deficit_intervalo_personas.sum()),"cierre_con_30_y_tres_sustitutas":False,
                 "programadas":np.nan,"sin_programar":np.nan,"mejor_programacion_catalogo":np.nan,"mejor_programacion_ensayada":np.nan,"minimo_global_demostrado":False}
            if not row["intervalo_posible"]:
                row["estado"]="Incompatible por intervalo y ventana";rows.append(row);continue
            cs=relojes_de_invierno(pt,red,op,cuotas,limites);row["mejor_programacion_catalogo"]=cs[0][0][0]
            cerrado=cerrar_en_ventana(cs,red,op,caps,ids,inicio_min=420,fin_min=1200)
            if cerrado is None:
                semilla=24500+int(tag["observacion"])+int(margen)*100+int(tag["cumplimiento_cambio_fecha"]*10)
                for k,entry in enumerate(cs[:2]):
                    key,reloj,u,b=entry
                    out,evaluados=mejorar_reloj(reloj,u,b,semilla=semilla+k,pasos=1200);n,ne,uu,bb=out
                    cs.append(((n,ne,"ajuste_individual",float(k)),reloj,uu,bb))
                    add("refinamiento",pd.DataFrame([{"reinicio":k,"semilla":semilla+k,"pasos_previstos":1200,
                        "relojes_validos_evaluados":evaluados,"cadenas_inicio":key[0],"mejores_cadenas":n}]),**tag)
                cs.sort(key=lambda x:x[0]);cerrado=cerrar_en_ventana(cs,red,op,caps,ids,inicio_min=420,fin_min=1200)
            row["mejor_programacion_ensayada"]=cs[0][0][0]
            row["estado"]="Cierre construido" if cerrado is not None else "Sin cierre en búsqueda acotada"
            if cerrado is not None:
                comercial=cerrado["viajes"].loc[lambda t:t.destino.str.startswith("cabecera:")]
                llegada=float(comercial.llegada_min.max())
                if llegada>ocaso-margen+1e-8:raise ValueError("Una llegada comercial rebasa la referencia de luz.")
                if abs(cerrado["reservas"].personas.sum()-pt.demanda_lanzadera_dia.sum())>1e-8:raise ValueError("El horario pierde viajeros.")
                row.update(cierre_con_30_y_tres_sustitutas=True,programadas=cerrado["programadas"],sin_programar=30-cerrado["programadas"],
                    ultima_llegada_cabecera_min=llegada,ultima_llegada_base_min=float(cerrado["movimientos"].llegada_min.max()),
                    forma=cerrado["forma"],fraccion_regreso=cerrado["fraccion_regreso"])
                for n in ["cronologias","reservas","movimientos"]:add(n,cerrado["viajes" if n=="cronologias" else n],**tag)
                moves=cerrado["movimientos"];disp=[]
                for unidad in inv.itertuples():
                    m=moves[moves.unidad_fisica_id.eq(unidad.unidad_fisica_id)].sort_values("salida_min")
                    if not m.empty and m.iloc[0].origen!=unidad.base_red:raise ValueError("Se pierde la base original.")
                    disp.append({"unidad_fisica_id":unidad.unidad_fisica_id,"programada":not m.empty,"base_inicial":unidad.base_red,
                                 "base_final":m.iloc[-1].destino if not m.empty else unidad.base_red})
                add("disponibilidad_30",pd.DataFrame(disp),**tag)
                if tag["observacion"]==-85:
                    hh=hp[hp.cumplimiento_cambio_fecha.eq(tag["cumplimiento_cambio_fecha"])]
                    pares=cerrado["reservas"].merge(cerrado["viajes"][["id_salida","salida_min"]],left_on="id_subida",right_on="id_salida",validate="one_to_one")
                    for punto,g in hh.groupby("punto"):
                        test=auditar_perfil_reservado_p85(g,pares[pares.punto.eq(punto)],capacidad=46,espera=v["espera_max_lanzadera_min"],cambio_franja=True)
                        add("asignacion_p85_horaria",test["por_hora"].assign(punto=punto),**tag)
            rows.append(row)
    joined={n:pd.concat(z,ignore_index=True) for n,z in tablas.items()};joined["resumen"]=pd.DataFrame(rows);joined["inventario_30"]=inv
    joined["sintesis"]=joined["resumen"].groupby(["ambito_demanda","calendario_luz","margen_min","cumplimiento_cambio_fecha"],as_index=False).agg(
        comprobaciones=("caso_id","size"),cierres=("cierre_con_30_y_tres_sustitutas","sum"),incompatibles_intervalo=("intervalo_posible",lambda x:int((~x).sum())),
        maximo_programadas=("programadas","max"),mayor_mejor_programacion_ensayada=("mejor_programacion_ensayada","max"))
    joined["referencia_solar_2028"]=solar;joined["fechas_ocaso_minimo"]=solar[solar.ocaso_min.eq(ocaso_global)].copy()
    meta={"decision":"D245","hipotesis":"H135","fecha":"2026-11-08","parametros_conservados":param,"fuentes_sha256":fuentes,
        "alternativa":"P20","cuotas_coches_dia":cuotas,"margenes_min":[0,15,30],"inicio_cabeceras":"07:00","ventana_bases_min":[420,1200],
        "ocaso_fijo_referencia_min":ocaso_global,"ocaso_minimo_mensual_min":minimos,"calendarios_luz":["Fijo invierno","Mensual"],
        "muestra_poca_luz":{"meses_buscados":MESES,"matrices":sorted(map(int,winter.matrix_index.unique())),"alcance":"Ocho perfiles históricos escalados en D243, no una muestra completa o actual de invierno2028; enero ausente y festivos con referencia TITSA domingo."},
        "fuente_solar":{"registro":"F163","ruta":FUENTE_IGN,"url":URL_IGN,"horas":"Oficiales de Canarias2028, ya incluido el cambio estacional",
            "alcance":"Santa Cruz, horizonte ideal; márgenes hipotéticos. La luz efectiva depende de relieve, nubes, niebla y condiciones de la carretera."},
        "busqueda":{"formas":7,"reinicios_si_no_cierra":2,"pasos_reinicio":1200,"semilla":"24500 +observación +100×margen +10×cumplimiento +reinicio","minimo_global_demostrado":False},
        "limites":["Se exige el límite de luz a llegadas comerciales a cabecera; los vacíos a base hasta20:00 y las primeras salidas07:00 pueden circular sin luz.",
            "Un cierre de flota no acredita visibilidad real, permisos, turnos, operación anual o atención a todos los destinos/usuarios interiores.",
            "El p85 multianual compuesto y los nueve perfiles son estrés bajo el horario más corto, no demanda observada exclusivamente invernal.",
            "P20 conserva aumento20 % de excursiones solo en perfiles de julio. No se aplica ese aumento a noviembre/diciembre/febrero. No se inventa un p85 de invierno representativo.",
            "Los objetivos netos se conservan exactamente. En los accesos con cero demanda o residuos inferiores a1e-8 personas no se programa una expedición, según la tolerancia previa del constructor.",
            "El cupo550 es máximo, no obligación de llenarlo; el bruto reconstruido neto+cuota×ocupación sirve solo a la interfaz del reloj, no es una nueva estimación modal.",
            "No cambia demanda, captación, reparto, libro, energía o informe; no sobrescribe capturas previas."],
        "entorno":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__}}
    return Etapa(joined),meta


def generar_invierno_p20(root,destino):
    root,destino=Path(root).resolve(),Path(destino).resolve();permitido=(root/SALIDAS).resolve()
    if destino==permitido or destino.is_relative_to(root) and not destino.is_relative_to(permitido):raise ValueError("Elegir una captura nueva fuera de fuentes e informe.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):raise FileExistsError("La ejecución anterior se conserva.")
    etapa,meta=preparar_invierno_p20(root);destino.mkdir(parents=True,exist_ok=True)
    for n,t in etapa.tablas.items():t.to_csv(destino/(n+".csv"),sep=";",index=False,encoding="utf-8-sig",float_format="%.17g")
    paquete=Path(__file__).parents[1];names=["flujos/invierno_p20.py","operacion/invierno.py","operacion/reloj_integrado.py","operacion/refinar_reservas.py",
        "operacion/ventana_horaria.py","operacion/horarios_compartidos.py","operacion/circulacion_compartida.py","operacion/inventario_comun.py","operacion/red_compartida.py","operacion/reservas.py"]
    meta["codigo_sha256"]={"movilidad_teide/"+n:sha256_archivo(paquete/n) for n in names}
    meta["codigo_sha256"]["scripts/comprobar_invierno_p20.py"]=sha256_archivo(paquete.parents[1]/"scripts/comprobar_invierno_p20.py")
    meta["resultados_sha256"]={p.name:sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    (destino/"metadatos.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
    return etapa,meta
