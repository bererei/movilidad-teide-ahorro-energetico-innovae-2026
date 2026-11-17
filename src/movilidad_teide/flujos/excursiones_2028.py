"""Contrasto excursiones adicionales, conservando visitas y antecedentes."""
from pathlib import Path
import json
import platform

import numpy as np
import pandas as pd

from movilidad_teide.configuracion.lectura import leer_parametros
from movilidad_teide.demanda.perfiles_operacion_2028 import reconstruir_observaciones, COLECTIVOS
from movilidad_teide.operacion.red_compartida import RedOperativa
from movilidad_teide.operacion.reasignacion_dirigida import construir_dirigida, INVENTARIO, CUOTAS, REJILLA
from movilidad_teide.trazabilidad import sha256_archivo
from .horarios_550 import preparar_horarios_550
from .compartida_2028 import BASE, PARADAS
from .operacion_2028 import FUENTES, BASE as REFERENCIA
from .tipos import Etapa


ANTERIOR = "data/silver/movilidad/horarios_550_2028/20261107_cupo550_reservas"
SALIDAS = "data/silver/movilidad/excursiones_2028"
CASOS = ((2500000,.08),(2500000,.10),(2500000,.12),(2400000,.10),(2600000,.10))


def preparar_excursiones_2028(root, *, casos=CASOS, incluir_dirigida=True):
    root = Path(root).resolve();old = json.loads((root / ANTERIOR / "metadatos.json").read_text());fuentes = {}
    def registrar(p, expected=None):
        h = sha256_archivo(root / p)
        if expected is not None and h != expected:raise ValueError(f"Referencia modificada: {p}")
        fuentes[p] = h
    registrar(ANTERIOR + "/metadatos.json")
    for p,h in old["fuentes_sha256"].items():registrar(p,h)
    for p,h in old["resultados_sha256"].items():registrar(ANTERIOR+"/"+p,h)
    rd = lambda p: pd.read_csv(root / p, sep=";", float_precision="round_trip")
    ref = rd(ANTERIOR + "/balance_anual.csv")
    v = {p["id"]:p["valor_utilizado"] for p in leer_parametros(root)["parametros"]}
    tables, cases_meta, compare = {}, [], []
    def incorporar(etapa, meta, case, policy):
        anual = etapa.tablas["balance_anual"]
        vol = int(anual.volumen_planificacion.unique().item())
        e0 = float(anual.loc[anual.escenario.eq("Sin intervención") & anual.modo_entrada.eq("Excursiones/resto colectivo"), "visitas_persona_anio"].item())
        e1 = float(anual.loc[anual.escenario.eq("Con intervención") & anual.modo_entrada.eq("Excursiones/resto colectivo"), "visitas_persona_anio"].item())
        re = ref.loc[ref.volumen_planificacion.eq(vol) & ref.escenario.eq("Con intervención")].set_index("modo_entrada").visitas_persona_anio
        delta = e1 - float(re["Excursiones/resto colectivo"]);ratio = e1/e0-1
        tag = {"caso":case,"politica_reasignacion":policy}
        for name,frame in etapa.tablas.items():tables.setdefault(name,[]).append(frame.assign(**tag))
        summary = tables["resumen"][-1]
        summary["incremento_anual_excursiones_sobre_sin"] = ratio
        summary["personas_lanzadera_a_excursiones_anio"] = delta
        compare.append({**tag,"volumen_planificacion":vol,"excursiones_sin_personas_anio":e0,
            "excursiones_con_referencia_D240_personas_anio":float(re["Excursiones/resto colectivo"]),
            "excursiones_con_nuevas_personas_anio":e1,"incremento_anual_sobre_sin":ratio,
            "reasignadas_desde_lanzadera_D240_personas_anio":delta,
            "fraccion_sobre_lanzadera_D240":delta/float(re["Lanzadera de acceso"]),
            "entradas_equivalentes_excursion_sin_anio":e0/v["ocupacion_guagua_aforo"],
            "entradas_equivalentes_excursion_con_anio":e1/v["ocupacion_guagua_aforo"],
            "ocupacion_referencia_personas_por_vehiculo":v["ocupacion_guagua_aforo"],
            "nota_vehiculos":"Equivalentes de entradas; no flota, expediciones verificadas o capacidad del operador"})
        cases_meta.append({**tag,"volumen_planificacion":vol,"incremento_anual_realizado":ratio,
            "maximo_programado":int(summary.mayor_flota_programada_construida.max()),
            "busqueda":meta["busqueda"]})
        fuentes.update(meta["fuentes_sha256"])
    for vol,rate in casos:
        etapa,meta = preparar_horarios_550(root, volumenes=(vol,), incremento_excursiones=rate)
        incorporar(etapa,meta,f"U_{vol}_{round(rate*100):02d}",f"Uniforme: +{round(rate*100)} % en excursión sobre sin intervención")
    if incluir_dirigida:
        media = rd(REFERENCIA+"/demanda_horaria_2028.csv")
        frac = json.loads((root / REFERENCIA / "metadatos.json").read_text())["fraccion_coche_conservada"]
        ho = reconstruir_observaciones(rd(FUENTES["perfiles"]),rd(FUENTES["indices"]),media,total=2500000,
            fraccion_coche=frac,hora_inicio=v["hora_inicio_acceso"],hora_fin=v["hora_fin_acceso"])
        red = RedOperativa(rd(BASE+"/movimientos_diagnosticos.csv"),rd(BASE+"/pares_diagnosticos.csv"),rd(PARADAS))
        capt = dict(zip(COLECTIVOS,[v[k] for k in ["captacion_extranjero","captacion_nacional","captacion_local","captacion_frecuente"]]))
        propuesta = construir_dirigida(root,ho,rd(FUENTES["origenes"]),red,v,capt)
        etapa,meta = preparar_horarios_550(root,volumenes=(2500000,),incremento_excursiones=propuesta["incrementos"],propuesta_operacion=propuesta)
        if not etapa.tablas["resumen"].caben_circulaciones_construidas_en_30.all():
            raise ValueError("La propuesta dirigida no cierra con el inventario común; no se publica como viable.")
        meta["busqueda"] = {"metodo":"Rejilla dirigida por perfil con cuotas e inventario D240/D216 conservados",
            "incrementos_locales_ensayados":list(REJILLA),"relojes_por_incremento":7,"objetivo_maximo_programado":27,
            "minimo_global_demostrado":False,"sin_objetivo_energetico":True}
        incorporar(etapa,meta,"D_2500000","Dirigida a puntas: porcentaje anual calculado, no fijado al 10 %")
        tag={"caso":"D_2500000","politica_reasignacion":"Dirigida a puntas"}
        tables["rejilla_dirigida"]=[propuesta["intentos"].assign(**tag)]
        tables["incrementos_por_perfil_dirigido"]=[propuesta["seleccion"].assign(**tag)]
        tables["inventario_30_identidades"]=[propuesta["inventario"].assign(**tag)]
        dispon=[];moves=etapa.tablas["movimientos"]
        for obs, m in moves.groupby("observacion"):
            for row in propuesta["inventario"].itertuples():
                mm=m[m.unidad_fisica_id.eq(row.unidad_fisica_id)].sort_values("salida_min")
                if not mm.empty and mm.iloc[0].origen != row.base_red:raise ValueError("La identidad no parte de su base de inventario.")
                dispon.append({**tag,"observacion":int(obs),"unidad_fisica_id":row.unidad_fisica_id,
                    "base_inicial":row.base_red,"programada":not mm.empty,
                    "base_final":mm.iloc[-1].destino if not mm.empty else row.base_red})
        tables["disponibilidad_30_por_perfil"]=[pd.DataFrame(dispon)]
        registrar(INVENTARIO);registrar(str(Path(INVENTARIO).parent / "metadatos.json"));registrar(CUOTAS)
    joined={n:pd.concat(frames,ignore_index=True) for n,frames in tables.items()}
    joined["comparacion_reasignacion_anual"]=pd.DataFrame(compare)
    meta={"decision":"D241","hipotesis":"H131","fecha":"2026-11-07",
        "parametros_conservados":leer_parametros(root),"casos":cases_meta,"fuentes_sha256":fuentes,
        "criterio":"Reasignación de visitas previstas en lanzadera a excursión; visitas y OD conservados. No optimiza energía ni fuerza un umbral.",
        "limites":["Los aumentos uniformes de 8/10/12 % son sensibilidades, no elasticidades observadas.",
            "En la propuesta dirigida el porcentaje anual es ponderado por visitas en excursión y días; no es la media simple de los porcentajes locales.",
            "La propuesta dirigida concentra el traspaso en puntas y conserva las cuotas y treinta identidades previas; no es una predicción de elección modal.",
            "El inventario certificado corresponde a nueve perfiles y los recorridos conocidos. No se recalcula el p85 de 57 matrices ni se valida toda la operación anual.",
            "Los vehículos de excursión son servicios adicionales fuera de las treinta lanzaderas; su disponibilidad, expediciones y consumo no se presumen resueltos.",
            "TITSA conserva su traslado a lanzadera y no recibe el porcentaje. La341 es interior; ni regresos ni embarques interiores añaden visitas.",
            "Giros, otros destinos interiores, personal, cocheras exteriores y alimentación TITSA conservan sus límites anteriores.",
            "No se calcula ahorro nuevo, se modifica el Excel o se actualiza el informe; las ejecuciones anteriores permanecen intactas."],
        "entorno":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__}}
    return Etapa(joined),meta


def generar_excursiones_2028(root,destino,**kwargs):
    root,destino=Path(root).resolve(),Path(destino).resolve();permitido=(root/SALIDAS).resolve();data=(root/BASE).resolve().parents[3]
    if destino==permitido or any(destino.is_relative_to(p) for p in [root,data]) and not destino.is_relative_to(permitido):
        raise ValueError("Elegir una ejecución nueva e independiente de los datos previos.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):raise FileExistsError("La ejecución anterior se conserva.")
    etapa,meta=preparar_excursiones_2028(root,**kwargs);destino.mkdir(parents=True,exist_ok=True)
    for n,t in etapa.tablas.items():t.to_csv(destino/(n+".csv"),sep=";",index=False,encoding="utf-8-sig",float_format="%.17g")
    from movilidad_teide.operacion.figuras_excursiones import dibujar_excursiones
    dibujar_excursiones(etapa.tablas,root,destino)
    paquete=Path(__file__).parents[1]
    names=["flujos/excursiones_2028.py","flujos/horarios_550.py","demanda/excursiones_2028.py",
        "demanda/escenarios_2028.py","demanda/perfiles_operacion_2028.py",
        "operacion/reloj_integrado.py","operacion/refinar_reservas.py","operacion/horarios_compartidos.py",
        "operacion/cuotas_por_intervalos.py","operacion/inventario_comun.py","operacion/reasignacion_dirigida.py",
        "operacion/circulacion_compartida.py","operacion/red_compartida.py","operacion/figura_reloj.py","operacion/figuras_excursiones.py"]
    meta["codigo_sha256"]={"movilidad_teide/"+n:sha256_archivo(paquete/n) for n in names}
    meta["codigo_sha256"]["scripts/contrastar_excursiones_2028.py"]=sha256_archivo(paquete.parents[1]/"scripts/contrastar_excursiones_2028.py")
    meta["resultados_sha256"]={p.name:sha256_archivo(p) for p in sorted(destino.glob("*.csv"))}
    meta["figuras_sha256"]={p.name:sha256_archivo(p) for p in sorted(destino.iterdir()) if p.suffix in [".png",".svg",".pdf"]}
    (destino/"metadatos.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
    return etapa,meta
