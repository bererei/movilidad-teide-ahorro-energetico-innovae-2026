"""Contrasto excursiones moderadas y fechas de visita con operación conservada."""
from pathlib import Path
import json
import platform

import numpy as np
import pandas as pd

from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.demanda.escenarios_2028 import construir_escenarios
from movilidad_teide.demanda.excursiones_2028 import reasignar_excursiones
from movilidad_teide.demanda.redistribucion_temporal import redistribuir_fechas
from movilidad_teide.demanda.perfiles_operacion_2028 import reconstruir_observaciones, COLECTIVOS
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.operacion.reloj_integrado import RelojIntegrado
from movilidad_teide.operacion.refinar_reservas import FORMAS
from movilidad_teide.operacion.circulacion_compartida import encadenar_viajes, materializar
from movilidad_teide.operacion.inventario_comun import bases_posibles, asignar_bases
from movilidad_teide.trazabilidad import sha256_archivo
from .operacion_2028 import FUENTES, BASE as REFERENCIA
from .compartida_2028 import BASE, PARADAS
from .tipos import Etapa


ANTERIOR = "data/silver/movilidad/excursiones_2028/20261107_reasignacion_y_puntas"
SALIDAS = "data/silver/movilidad/redistribucion_2028"
E15 = {"Marzo":0.,"Julio":.15,"Octubre":0.}
Q15 = {"Marzo":0.,"Julio":.15,"Octubre":.10}
CASOS = {
    "P15":(E15,Q15),
    "P20":({**E15,"Julio":.20},Q15),
    "P20_fecha_175":({**E15,"Julio":.20},{**Q15,"Julio":.175}),
    "P15_sin_cambio_fecha":(E15,{m:0. for m in Q15}),
    "P15_mitad_cambio_fecha":(E15,{m:q/2 for m,q in Q15.items()}),
    "P15_mas_cambio_fecha":(E15,{**Q15,"Julio":.20}),
}


def relojes_iniciales(puntos,red,valores,cuotas):
    reloj=RelojIntegrado(puntos,red,valores,cuotas);out=[]
    for forma,alpha in FORMAS:
        u,b=reloj.inicial(forma,alpha);n,e=reloj.evaluar(u,b)
        out.append(((n,-e,forma,alpha),reloj,u,b))
    return sorted(out,key=lambda x:x[0])


def cerrar_perfil(candidatos,red,valores,capacidades,identidades):
    """Busco cierre entre siete relojes; no sustituyo un fallo por un supuesto."""
    for key,reloj,u,b in candidatos:
        if key[0]>27:continue
        viajes,reservas=reloj.tablas(u,b)
        for criterio in ("distancia","tiempo","servicio"):
            t,cadenas=encadenar_viajes(viajes,red,regulacion=valores["regulacion_min"],criterio=criterio)
            ss,ee=bases_posibles(t,cadenas,red,regulacion=valores["regulacion_min"])
            cierre,_=asignar_bases(ss,ee,red.bases,capacidades)
            if cierre is None:continue
            a,bases_finales=cierre
            fisicos=materializar(t,cadenas,a,red,regulacion=valores["regulacion_min"],bases_finales=bases_finales)
            ids={b:vv.copy() for b,vv in identidades.items()}
            equivalencias={f"TF{k+1:02d}":ids[base].pop(0) for k,base in enumerate(a)}
            for original,real in equivalencias.items():
                mask=fisicos.unidad_fisica_id.eq(original)&fisicos.familia.eq("Vacío")
                fisicos.loc[mask,"id_salida"]=fisicos.loc[mask,"id_salida"].str.replace(original+"_",real+"_",n=1,regex=False)
            fisicos["unidad_fisica_id"]=fisicos.unidad_fisica_id.map(equivalencias)
            return {"viajes":viajes,"reservas":reservas,"movimientos":fisicos,
                    "n":len(cadenas),"forma":key[2],"regreso":key[3],"criterio":criterio}
    return None


def preparar_redistribucion_2028(root):
    root=Path(root).resolve();fuentes={}
    def registrar(p,esperado=None):
        huella=sha256_archivo(root/p)
        if esperado is not None and huella!=esperado:raise ValueError(f"Fuente previa modificada: {p}")
        fuentes[p]=huella
    registrar(ANTERIOR+"/metadatos.json")
    previa=json.loads((root/ANTERIOR/"metadatos.json").read_text())
    for p,h in previa["fuentes_sha256"].items():registrar(p,h)
    for p,h in previa["resultados_sha256"].items():registrar(ANTERIOR+"/"+p,h)
    rd=lambda p:pd.read_csv(root/p,sep=";",float_precision="round_trip")
    parametros=leer_parametros(root);v={p["id"]:p["valor_utilizado"] for p in parametros["parametros"]}
    if v["cupo_global"]!=500 or v["reserva_minima_dentro_flota"]!=3 or v["intervalo_refuerzo_punta_min"]!=15:
        raise ValueError("Revisar condiciones del libro antes de otro contraste.")
    inv=rd(ANTERIOR+"/inventario_30_identidades.csv")
    if len(inv)!=30 or inv.unidad_fisica_id.duplicated().any():raise ValueError("Inventario distinto de treinta identidades.")
    ids=inv.groupby("base_red").unidad_fisica_id.apply(list).to_dict();caps={b:len(z) for b,z in ids.items()}
    cuotas=rd(ANTERIOR+"/cuotas_comunes.csv").query("caso == 'D_2500000'")
    cuotas=dict(zip(cuotas.punto,cuotas.coches_dia))
    if sum(cuotas.values())!=550:raise ValueError("El contraste conserva 550 coches/día.")
    red=RedOperativa(rd(BASE+"/movimientos_diagnosticos.csv"),rd(BASE+"/pares_diagnosticos.csv"),rd(PARADAS))
    for p in [*FUENTES.values(),BASE+"/movimientos_diagnosticos.csv",BASE+"/pares_diagnosticos.csv",PARADAS,REFERENCIA+"/demanda_horaria_2028.csv",REFERENCIA+"/metadatos.json"]:registrar(p)
    frac=json.loads((root/REFERENCIA/"metadatos.json").read_text())["fraccion_coche_conservada"]
    ho=reconstruir_observaciones(rd(FUENTES["perfiles"]),rd(FUENTES["indices"]),rd(REFERENCIA+"/demanda_horaria_2028.csv"),
        total=2500000,fraccion_coche=frac,hora_inicio=v["hora_inicio_acceso"],hora_fin=v["hora_fin_acceso"])
    perfiles=ho[["matrix_index","mes_publicado","tipo_dia_publicado","dias_equivalentes"]].drop_duplicates().rename(
        columns={"matrix_index":"observacion","mes_publicado":"mes","tipo_dia_publicado":"tipo"})
    capt=dict(zip(COLECTIVOS,[v[k] for k in ["captacion_extranjero","captacion_nacional","captacion_local","captacion_frecuente"]]))
    bases={obs:construir_escenarios(g,rd(FUENTES["origenes"]),ocupacion=v["ocupacion_coche"],cupo=550,captaciones=capt,
        hora_inicio=v["hora_inicio_acceso"],hora_fin=v["hora_fin_acceso"],cuotas_por_tipo={g.tipo_dia_publicado.iloc[0]:cuotas}) for obs,g in ho.groupby("matrix_index")}
    def transformar(es,qs):
        zs={int(obs):reasignar_excursiones(b,incremento=es[perfiles.set_index("observacion").loc[obs,"mes"]],ocupacion=v["ocupacion_coche"]) for obs,b in bases.items()}
        return redistribuir_fechas(zs,perfiles,qs,ocupacion=v["ocupacion_coche"])
    tablas={k:[] for k in ["perfiles","origenes","titsa","puntos","transferencias_fecha","cronologias","reservas","movimientos","disponibilidad","modos_por_perfil","resumen","rejilla_julio"]}
    for caso,(es,qs) in CASOS.items():
        zs,tr=transformar(es,qs);tablas["transferencias_fecha"].append(tr.assign(caso=caso));cerrados=[];nums=[]
        for obs,z in zs.items():
            row=perfiles.set_index("observacion").loc[obs];pt=z["escenarios_por_punto_dia"]
            candidatos=relojes_iniciales(pt,red,v,cuotas);cierre=cerrar_perfil(candidatos,red,v,caps,ids)
            n=cierre["n"] if cierre else candidatos[0][0][0];nums.append(n);cerrados.append(cierre is not None)
            tag={"caso":caso,"observacion":obs,"mes":row.mes,"tipo":row.tipo,"dias_equivalentes":row.dias_equivalentes}
            tablas["perfiles"].append(pd.DataFrame([{**tag,"incremento_excursiones_sobre_sin":es[row.mes],
                "fraccion_fin_semana_elegible_trasladada":qs[row.mes],"menor_programacion_catalogo":candidatos[0][0][0],
                "programadas_con_cierre":cierre["n"] if cierre else np.nan,"cierre_30":cierre is not None,
                "visitas_sin_dia":pt.visitas_sin_dia.sum(),"visitas_con_dia":pt.visitas_con_objetivo_dia.sum(),
                "lanzadera_antes_fecha_dia":pt.demanda_lanzadera_dia.sum()-pt.cambio_fecha_entrada_dia.sum()+pt.cambio_fecha_salida_dia.sum(),
                "lanzadera_despues_fecha_dia":pt.demanda_lanzadera_dia.sum(),
                "visitas_entrantes_cambio_fecha_dia":pt.cambio_fecha_entrada_dia.sum(),"visitas_salientes_cambio_fecha_dia":pt.cambio_fecha_salida_dia.sum()}]))
            for k,nombre in [("por_origen_dia","origenes"),("titsa_por_corredor_colectivo_dia","titsa"),("escenarios_por_punto_dia","puntos")]:tablas[nombre].append(z[k].assign(**tag))
            if cierre:
                for k in ["cronologias","reservas","movimientos"]:tablas[k].append(cierre["viajes" if k=="cronologias" else k].assign(**tag))
                moves=cierre["movimientos"]
                for unidad in inv.itertuples():
                    mm=moves[moves.unidad_fisica_id.eq(unidad.unidad_fisica_id)].sort_values("salida_min")
                    if not mm.empty and mm.iloc[0].origen!=unidad.base_red:raise ValueError("Identidad fuera de su base inicial.")
                    tablas["disponibilidad"].append(pd.DataFrame([{**tag,"unidad_fisica_id":unidad.unidad_fisica_id,"base_inicial":unidad.base_red,
                        "base_final":mm.iloc[-1].destino if not mm.empty else unidad.base_red,"programada":not mm.empty}]))
            for escenario,modos in [("Sin intervención",{"Coche particular y alquiler":pt.visitas_coche.sum(),"TITSA":pt.visitas_titsa.sum(),"Excursiones/resto colectivo":pt.visitas_excursiones_resto_colectivo.sum(),"Lanzadera de acceso":0.}),
                ("Con intervención",{"Coche particular y alquiler":pt.visitas_coche_autorizadas_dia.sum(),"TITSA":0.,"Excursiones/resto colectivo":pt.visitas_excursiones_con_intervencion_dia.sum(),"Lanzadera de acceso":pt.demanda_lanzadera_dia.sum()})]:
                tablas["modos_por_perfil"].append(pd.DataFrame([{**tag,"escenario":escenario,"modo":modo,"visitas_persona_dia":qty,"visitas_persona_anio":qty*row.dias_equivalentes} for modo,qty in modos.items()]))
        tablas["resumen"].append(pd.DataFrame([{"caso":caso,"nueve_perfiles_con_cierre_30":all(cerrados),
            "maximo_programado_o_menor_catalogo_si_falla":max(nums),"visitas_desplazadas_fecha_anio":tr.visitas_persona_anio.sum(),
            "p85_recalculado":False,"energia_calculada":False}]))
    # Frontera de julio con las mismas siete formas: incluye fallos, sin inferir
    # imposibilidad fuera del catálogo. Marzo y octubre no intervienen en ella.
    for e in [0.,.10,.15,.20,.25]:
        for q in [0.,.05,.10,.125,.15,.175,.20]:
            zs,_=transformar({**E15,"Julio":e},{**Q15,"Julio":q})
            for obs in perfiles.loc[perfiles.mes.eq("Julio"),"observacion"]:
                cc=relojes_iniciales(zs[obs]["escenarios_por_punto_dia"],red,v,cuotas)
                tablas["rejilla_julio"].append(pd.DataFrame([{"incremento_excursiones":e,"fraccion_cambio_fecha":q,"observacion":obs,"menor_programacion_catalogo":cc[0][0][0]}]))
    joined={k:pd.concat(a,ignore_index=True) for k,a in tablas.items() if a}
    joined["balance_anual"]=joined["modos_por_perfil"].groupby(["caso","escenario","modo"],as_index=False).visitas_persona_anio.sum()
    for _,g in joined["balance_anual"].groupby(["caso","escenario"]):
        if abs(g.visitas_persona_anio.sum()-2500000)>1e-8:raise ValueError("Total anual distinto sin/con.")
    joined["inventario_30"]=inv.drop(columns=["caso","politica_reasignacion"],errors="ignore")
    joined["origenes_sin_cantidad_anual"]=next(iter(bases.values()))["origenes_sin_cantidad_anual"].copy()
    oo=joined["origenes"].copy();tt=joined["titsa"].copy()
    oo["visitas_sin_anio"]=(oo.visitas_coche+oo.visitas_excursiones_resto_colectivo)*oo.dias_equivalentes
    oo["visitas_con_anio"]=(oo.visitas_coche_autorizadas_dia+oo.visitas_coche_transferidas_dia+oo.visitas_excursiones_con_intervencion_dia+oo.visitas_excursiones_transferidas_dia)*oo.dias_equivalentes
    cc=oo.groupby(["caso","colectivo"],as_index=False)[["visitas_sin_anio","visitas_con_anio"]].sum()
    tit=(tt.visitas_titsa*tt.dias_equivalentes).groupby([tt.caso,tt.colectivo]).sum()
    for c in ["visitas_sin_anio","visitas_con_anio"]:cc[c]+=pd.MultiIndex.from_frame(cc[["caso","colectivo"]]).map(tit).to_numpy()
    if not np.allclose(cc.visitas_sin_anio,cc.visitas_con_anio,rtol=0,atol=1e-8):raise ValueError("Diferencia anual entre colectivos.")
    joined["colectivos_anuales"]=cc
    refs="data/silver/movilidad/referencia_oficial_2025/20261106_oapn_od/contraste_fuentes_2025.csv"
    modal="data/silver/demanda/separacion_titsa/reasignacion/desglose_modal_2025.csv"
    for p in [refs,modal]:registrar(p)
    joined["fuentes_2025"]=rd(refs)
    joined["base_modal_2025_reconstruida"]=rd(modal).query("situacion == 'Referencia 2025'").assign(
        estado="Reconstrucción calibrada a OAPN, no conteos modales observados; no base de crecimiento de 2,5 millones")
    meta={"decision":"D242","hipotesis":"H132","fecha":"2026-11-08","parametros_conservados":parametros,
        "fuentes_sha256":fuentes,"casos":{k:{"incremento_excursiones_por_mes":es,"fraccion_cambio_fecha_fin_semana_por_mes":qs} for k,(es,qs) in CASOS.items()},
        "inventario":caps,"cuotas_coches_dia":cuotas,"excursiones_usan_lanzadera_interior":False,
        "criterio":"Conservación anual de modos/orígenes/colectivos; cambio de calendario solo con intervención. No optimiza energía.",
        "limites":["Las tres guaguas no programadas son margen de sustitución, no un protocolo de averías o disponibilidad de personal acreditado.",
            "La redistribución de fechas es una sensibilidad, no una elasticidad observada o una mejora automática de fiabilidad.",
            "Los nueve perfiles representan tres meses, no un calendario observado de 2028; sábado/domingo no identifica festivos reales.",
            "El porcentaje temporal se aplica a viajeros elegibles previstos en lanzadera después del cambio a excursión, no a todas las visitas.",
            "La conservación es anual por origen/colectivo: sin/con pueden diferir en un perfil diario. No comparar energías de días distintos como efecto modal puro.",
            "Las excursiones cubren acceso, recorrido interior y regreso con sus vehículos, fuera de treinta; no demandan lanzadera interior en esta hipótesis.",
            "El residuo colectivo contiene excursiones y otros servicios no identificados; la disponibilidad de operadores no se deduce de su nombre.",
            "La base modal2025 es reconstruida con OAPN y ocupaciones; 2,5 millones es otra referencia de planificación, no su proyección demográfica.",
            "No se recalcula p85, energía, informe, Excel o se validan giros, otros usuarios interiores, cocheras o turnos."],
        "entorno":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__}}
    return Etapa(joined),meta


def generar_redistribucion_2028(root,destino):
    root,destino=Path(root).resolve(),Path(destino).resolve();permitido=(root/SALIDAS).resolve()
    if destino==permitido or destino.is_relative_to(root) and not destino.is_relative_to(permitido):
        raise ValueError("Elegir una captura nueva fuera de las fuentes.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):raise FileExistsError("La ejecución anterior se conserva.")
    etapa,meta=preparar_redistribucion_2028(root);destino.mkdir(parents=True,exist_ok=True)
    for n,t in etapa.tablas.items():t.to_csv(destino/(n+".csv"),sep=";",index=False,encoding="utf-8-sig",float_format="%.17g")
    from movilidad_teide.operacion.figuras_redistribucion import dibujar_redistribucion
    dibujar_redistribucion(etapa.tablas,destino)
    paquete=Path(__file__).parents[1]
    nombres=["flujos/redistribucion_2028.py","demanda/redistribucion_temporal.py","demanda/escenarios_2028.py","demanda/excursiones_2028.py",
        "demanda/perfiles_operacion_2028.py","operacion/reloj_integrado.py","operacion/inventario_comun.py","operacion/circulacion_compartida.py",
        "operacion/refinar_reservas.py","operacion/horarios_compartidos.py","operacion/cuotas_por_intervalos.py","operacion/red_compartida.py","operacion/figuras_redistribucion.py"]
    meta["codigo_sha256"]={"movilidad_teide/"+n:sha256_archivo(paquete/n) for n in nombres}
    meta["codigo_sha256"]["scripts/contrastar_redistribucion_2028.py"]=sha256_archivo(paquete.parents[1]/"scripts/contrastar_redistribucion_2028.py")
    meta["resultados_sha256"]={p.name:sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    meta["figuras_sha256"]={p.name:sha256_archivo(p) for p in sorted(destino.iterdir()) if p.suffix in [".png",".svg",".pdf"]}
    (destino/"metadatos.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
    return etapa,meta
