"""Productores conectados mediante los archivos de una misma ejecución registrada."""
from contextlib import contextmanager
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pandas as pd

from movilidad_teide.configuracion.registro import abrir_ejecucion, ARCHIVO
from movilidad_teide.configuracion.estudio import leer_configuracion, configuracion_resuelta
from movilidad_teide.configuracion.parametros_tipos import ErrorParametros
from movilidad_teide.configuracion.contratos_etapas import ETAPAS
from movilidad_teide.configuracion.productos import (
    bloqueo, leer_estado, preparar_intento, agregar_suceso, describir_productos,
)
from movilidad_teide.trazabilidad import sha256_archivo

_auditoria=None
_instalada=False


def _json(p,datos):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(datos,ensure_ascii=False,indent=2,default=str)+'\n')


@contextmanager
def lecturas_de_etapa(root,carpeta,destino,fuentes,productos,etapa,*,demanda_original=()):
    """Denegar referencias previas cuando existe un producto conectado que debe usarse."""
    global _auditoria,_instalada
    if _auditoria is not None:raise RuntimeError('Ya hay una auditoría de etapa activa.')
    root,carpeta,destino=map(lambda x:Path(x).resolve(),[root,carpeta,destino])
    origenes={str(root/x['ruta']):x for x in fuentes}
    permitidos={str(carpeta/x['ruta']) for x in productos}
    leidos=set()
    if not _instalada:
        def audit(event,args):
            if _auditoria is None or event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)):return
            base,run,target,inputs,allowed,step,seen,demanda_previa=_auditoria
            p=Path(os.fsdecode(args[0])).resolve()
            if p.is_relative_to(target):return
            mode=args[1] if len(args)>1 else None;flags=args[2] if len(args)>2 and isinstance(args[2],int) else 0
            escribir=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
            if p.is_relative_to(run):
                if escribir:raise PermissionError('Una etapa no puede sobrescribir otro producto de la ejecución.')
                if str(p) not in allowed:raise PermissionError('Producto de otra etapa o intento no declarado: '+str(p.relative_to(run)))
                seen.add('ejecucion:'+str(p.relative_to(run)));return
            if not p.is_relative_to(base):return
            n=str(p.relative_to(base))
            if n.startswith(('.venv/','.git/')):return
            if n.startswith(('data/','config/','src/','scripts/','manifiestos/')) or n in ['pyproject.toml','uv.lock','.python-version']:
                if escribir:raise PermissionError('La etapa no puede modificar una entrada del proyecto: '+n)
                if str(p) not in inputs:raise PermissionError('Entrada no declarada en el registro: '+n)
                if n.startswith('data/gold/') and step!='07':raise PermissionError('Gold solo se abre en la etapa de comparación.')
                if n.startswith('data/silver/copert/referencia_comparacion/') and step not in ['05','07']:raise PermissionError('Referencia COPERT ajena a esta etapa.')
                if step=='06' and n.startswith(('data/silver/energia/','data/silver/geografia/','data/silver/vehiculos/','data/silver/copert/','data/silver/operacion/')):
                    raise PermissionError('El balance debe usar productos registrados, no esta preparación anterior: '+n)
                if step=='04' and n in demanda_previa:
                    raise PermissionError('La operación debe usar la demanda de la ejecución: '+n)
                seen.add('proyecto:'+n);return
            if n.startswith(('desarrollo/','docs/','outputs/')):raise PermissionError('La etapa depende de material ajeno al cálculo: '+n)
        sys.addaudithook(audit);_instalada=True
    _auditoria=(root,carpeta,destino,origenes,permitidos,etapa,leidos,set(demanda_original))
    try:yield leidos
    finally:_auditoria=None


def _tablas_demanda(folder):
    return {p.relative_to(folder/'tablas_parquet').with_suffix('').as_posix():pd.read_parquet(p)
            for p in sorted((folder/'tablas_parquet').rglob('*.parquet'))}


def _tablas_geografia(folder):
    from .preparacion_geografia import leer_tabla
    import geopandas as gpd
    tablas={}
    for p in sorted((folder/'tablas').rglob('*.parquet')):
        tabla=leer_tabla(p)
        if 'geometry' in tabla:
            # El comparador devuelve un DataFrame con geometría y CRS en attrs.
            # El productor necesita conservar el tipo GeoDataFrame al reescribir.
            tabla=gpd.GeoDataFrame(tabla,geometry='geometry',crs=tabla.attrs['crs'])
        tablas[p.relative_to(folder/'tablas').with_suffix('').as_posix()]=tabla
    return tablas


def _copiar_fuentes(root,out,fuentes,prefijos):
    rows=[]
    for x in fuentes:
        n=x['ruta']
        if not any(n==pre or n.startswith(pre.rstrip('/')+'/') for pre in prefijos):continue
        p=out/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,p)
        rows.append(dict(origen=n,producto=p.relative_to(out).as_posix(),sha256=x['sha256']))
    if not rows:raise ErrorParametros('No hay entradas selladas para la selección solicitada.')
    return rows


def _operacion(root,ref,demanda,geografia,out,fuentes):
    from .ordenacion_vigente import ContextoOrdenacion,_auditar_oferta,_leer
    from .compartida_2028 import BASE,PARADAS
    from .cierre_anual import INVENTARIO,SOLAR
    from movilidad_teide.operacion.red_compartida import RedOperativa
    from movilidad_teide.demanda.cabeceras_alternativas import leer_catalogo
    class ContextoConectado(ContextoOrdenacion):
        def __init__(self):
            self.root=root;self.referencia=ref;self.cfg=ref['valores'];self.v=ref['valores_modelo']
            self.captura=root/ref['indice']['captura'];self.inv=_leer(root/INVENTARIO)
            self.red=RedOperativa(_leer(root/BASE/'movimientos_diagnosticos.csv'),_leer(root/BASE/'pares_diagnosticos.csv'),_leer(root/PARADAS))
            self.sun=_leer(root/SOLAR).groupby('mes').ocaso_min.min().to_dict();self.catalogo=leer_catalogo(root)
            self.origins=demanda['territorio/origenes_por_modo_2025']
            self.hh=demanda['calendario/demanda_horaria_calendario'].query("metodo_calendario=='Estacional'").copy()
            self.cal=_leer(self.captura/'calendario.csv');self.weights=self.cal.target.value_counts().to_dict()
            self.modales={};self.auditorias=[];self.visitas_coche_sin_anio=0.
            if len(self.cal)!=366 or len(self.weights)!=36:raise ErrorParametros('Calendario de programación incompleto.')
            for ident,peso in self.weights.items():
                self.visitas_coche_sin_anio+=float(self.modal(self.cfg['cupo_ordinario'],ident,0.)['por_origen_dia'].visitas_coche.sum())*peso
    ctx=ContextoConectado()
    geo=_tablas_geografia(geografia)
    # Los recorridos adoptados y la red programada deben expresar las mismas distancias.
    puntos={'chio_boca_tauce':'CHIO','aguamansa_el_portillo':'OROTAVA','la_esperanza_el_portillo':'LAGUNA','vilaflor_boca_tauce':'VILAFLOR'}
    controles=[]
    for nombre,t in geo.items():
        if not nombre.startswith('operativos/') or '/tramos_' not in nombre:continue
        corredor=nombre.split('/')[1]
        if corredor not in puntos:continue
        point=puntos[corredor];head='cabecera:'+point
        arcos=[(a,b,km) for (a,b),(_,km) in ctx.red.arcos.items() if a==head or b==head]
        direccion='ida' if '_ida_' in nombre else 'vuelta'
        wanted=[km for a,b,km in arcos if (a==head)==(direccion=='ida')]
        if len(wanted)!=1 or abs(float(t.length_m.sum()/1000)-wanted[0])>1e-8:raise ErrorParametros('Recorrido geográfico y servicio no concilian: '+nombre)
        controles.append(dict(recorrido=nombre,km_geografia=float(t.length_m.sum()/1000),km_servicio=wanted[0]))
    if len(controles)!=8:raise ErrorParametros('No se han comprobado los ocho recorridos dirigidos de acceso.')
    pd.DataFrame(controles).to_csv(out/'distancias_comprobadas.csv',sep=';',index=False)
    actividad=[]
    def valorar(r,folder,incremento,familia):
        _,pt,_=ctx.comprobar_modal(r,folder,incremento)
        mm=_auditar_oferta(ctx,r,folder,pt)
        actividad.append(dict(familia=familia,perfil=r.perfil,cupo=r.cupo,max_programadas=r.max_programadas,
            programadas=r.programadas,incremento_excursiones=incremento,visitas_lanzadera_dia=float(pt.demanda_lanzadera_dia.sum()),
            movimientos=len(mm),vehiculo_km_comerciales=float(mm.loc[mm.componente.eq('comercial'),'km'].sum()),
            vehiculo_km_vacio=float(mm.loc[mm.componente.ne('comercial'),'km'].sum())))
    op=_leer(ctx.captura/'resultados_operacion.csv')
    for r in op[op.cierre].itertuples():valorar(r,ctx.captura/'ofertas'/str(r.cupo)/str(r.max_programadas)/r.perfil,0.,'principal')
    acts=_leer(ctx.captura/'sensibilidad_excursiones/actividad_por_programa.csv')
    for r in acts.itertuples():
        folder=ctx.captura/'sensibilidad_excursiones'/str(round(r.incremento_excursiones*100))/('conservada' if r.oferta=='Oferta conservada' else 'ajustada')/r.perfil
        valorar(r,folder,r.incremento_excursiones,'sensibilidad_excursiones')
    pd.DataFrame(actividad).to_csv(out/'actividad_programas.csv',sep=';',index=False,float_format='%.17g')
    pd.DataFrame(ctx.auditorias).to_csv(out/'auditoria_programas.csv',sep=';',index=False)
    prefixes=[BASE,PARADAS,INVENTARIO,SOLAR,ref['indice']['captura'],
        'data/bronze/geografia/rutas_cabeceras/20261108_osrm',
        'data/silver/operacion/referencias_actividad/actividad_para_factor_posicionamiento.csv']
    copias=_copiar_fuentes(root,out/'insumos',fuentes,prefixes)
    _json(out/'indice_insumos_fijados.json',copias)
    return dict(programas_comprobados=len(ctx.auditorias),programacion_fijada=True,energia_calculada=False,distancias_dirigidas_comprobadas=len(controles))


def _balance(root,ref,dependencias,out):
    from .preparacion_geografia import leer_tabla
    from movilidad_teide.energia.preparacion_coeficientes import (
        preparar_turismos,preparar_autobuses,preparar_excursiones,
        preparar_alimentacion_titsa,preparar_unidades_reasignadas,
    )
    from .balance_desde_perfiles import completar_raiz_calculo,calcular_balance
    demanda=_tablas_demanda(dependencias['01']);geo=dependencias['02']
    prep=SimpleNamespace(root=root,cat=json.loads((geo/'catalogo_resuelto.json').read_text()),tables=_tablas_geografia(geo))
    habituales=leer_tabla(geo/'clasificacion/segmentos_habituales.parquet')
    reasignados=leer_tabla(geo/'clasificacion/segmentos_osrm.parquet')
    calc=out/'calculo';calc.mkdir();shutil.copytree(root/'config',calc/'config')
    opciones=dict(factores=dependencias['05'],flota=dependencias['03']/'seleccion/data/silver/vehiculos/flota_teide',operacion=dependencias['04']/'insumos')
    base=preparar_turismos(root,calc,prep,habituales,demanda,ref['base'],**opciones)
    preparar_autobuses(root,calc,prep,ref['base'],factores=opciones['factores'],operacion=opciones['operacion'])
    preparar_excursiones(calc,base,ref['base'])
    preparar_alimentacion_titsa(root,calc,demanda,ref['base'],operacion=opciones['operacion'])
    preparar_unidades_reasignadas(root,calc,prep,reasignados,base,ref['base'])
    completar_raiz_calculo(root,calc,demanda,operacion=opciones['operacion'])
    ctx=calcular_balance(calc,out/'balance')
    cal=pd.read_csv(out/'balance/recomendada_calendario.csv',sep=';',float_precision='round_trip')
    if len(cal)!=366 or abs(cal.visitas_sin_dia.sum()-ref['valores']['visitas_anio'])>1e-8:raise ErrorParametros('El balance no conserva calendario y visitas.')
    metadata=dict(contrato_sha256=sha256_archivo(root/'manifiestos/preparacion_balance.json'),
        visitas_sin_y_con=ref['valores']['visitas_anio'],restricciones=ref['valores'],programas_comprobados=len(ctx.auditorias),
        procedencia='Productos conectados01–05; sin recalcular demanda/geografía ni releer sus referencias anteriores',
        factores_copert_de_la_etapa05=True,lecturas_gold_durante_calculo=False,
        salidas_sha256={p.relative_to(out).as_posix():sha256_archivo(p) for p in sorted(out.rglob('*')) if p.is_file()})
    _json(out/'metadatos.json',metadata)
    return dict(visitas_sin_y_con=ref['valores']['visitas_anio'],programas_comprobados=len(ctx.auditorias),
                productos_anuales=len(ref['indice']['productos_actualizados']),energia_calculada=True)


def _producir(root,carpeta,datos,etapa,accion,destino,dependencias,*,copert=None,intercambio=None):
    ref=datos['configuracion'];fuentes=datos['registro']['fuentes']
    if etapa=='01':
        from .preparacion_demanda import preparar
        m=preparar(root,destino,guardar_parquet=True,referencia=ref)
        return {k:m[k] for k in ['tablas_producidas','visitas_sin_y_con','energia_recalculada']}
    if etapa=='02':
        from .preparacion_geografia import preparar
        m=preparar(root,destino,demanda=_tablas_demanda(dependencias['01']),clasificar_vias=True,referencia=ref)
        return {k:m[k] for k in ['tablas_producidas','visitas_sin_y_con','clasificacion_reconstruida','demanda_de_ejecucion_recibida']}
    if etapa=='03':
        rows=_copiar_fuentes(root,destino/'seleccion',fuentes,['data/silver/vehiculos/flota_teide'])
        _json(destino/'seleccion_fijada.json',dict(criterio='Representación técnica elegida; se registra y conserva, sin atribuir nueva selección desde bruto.',archivos=rows))
        return dict(archivos_fijados=len(rows),seleccion_nueva=False)
    if etapa=='04':return _operacion(root,ref,_tablas_demanda(dependencias['01']),dependencias['02'],destino,fuentes)
    if etapa=='05':
        from movilidad_teide.vehiculos.copert_publico import compare_package,execute_package
        package=root/'data/bronze/copert/entradas_publicas';reference=root/'data/silver/copert/referencia_comparacion'
        if accion=='consultar':
            m=compare_package(package,root/'data/silver/copert/factores',reference=reference,destination=destino)
        else:
            if copert is None or intercambio is None:raise ErrorParametros('La ejecución del motor requiere --copert y --intercambio en Windows.')
            target=Path(intercambio).resolve()
            if target.exists():raise FileExistsError('El intercambio COPERT debe ser una carpeta nueva.')
            m=execute_package(package,target,Path(copert),reference=reference)
            shutil.copytree(target,destino,dirs_exist_ok=True)
            if not m['motor_copert_ejecutado_en_esta_llamada']:raise ErrorParametros('No consta ejecución nueva del motor.')
        return dict(accion=accion,motor_ejecutado_en_esta_ejecucion=accion=='ejecutar_motor',
                    factores_comparados=m['factores_comparados'],maxima_diferencia_mj_km=m['maxima_diferencia_mj_km'],
                    tolerancia_absoluta_mj_km=m['tolerancia_absoluta_mj_km'])
    if etapa=='06':return _balance(root,ref,dependencias,destino)
    if etapa=='07':
        from .preparacion_demanda import comparar as demanda
        from .preparacion_geografia import comparar as geografia
        from .preparacion_balance import comparar as balance
        a=demanda(root,dependencias['01'],destino/'demanda')
        b=geografia(root,dependencias['02'],destino/'geografia')
        otras={f'clasificacion/{n}.parquet':dependencias['02']/f'clasificacion/{n}.parquet' for n in ['tipologia_por_componente','segmentos_osrm']}
        c=balance(root,dependencias['06'],destino/'balance',productos=otras)
        result=dict(equivalente=a['equivalente'] and b['equivalente'] and c['equivalente'],demanda=a,geografia=b,balance=c,informe_y_anexos_modificados=False)
        _json(destino/'verificacion_integrada.json',result)
        return dict(equivalente=result['equivalente'],interfaces_demanda=a['interfaces_comparadas'],interfaces_geografia=b['interfaces_comparadas'],interfaces_balance=c['interfaces_comparadas'],productos_anuales=c['productos_anuales'])
    raise ErrorParametros('Etapa no reconocida.')


def ejecutar_etapa(root,registro,etapa,*,accion=None,copert=None,intercambio=None):
    """Completar una etapa con dependencias verificadas y cierre durable desde disco."""
    root=Path(root).resolve();carpeta=Path(registro)
    carpeta=carpeta if carpeta.is_absolute() else root/carpeta
    if carpeta.name==ARCHIVO:carpeta=carpeta.parent
    datos=abrir_ejecucion(root,carpeta);carpeta=carpeta.resolve()
    if etapa not in ETAPAS:raise ErrorParametros('Elige una etapa de01 a07.')
    accion=accion or ETAPAS[etapa]['acciones'][0]
    sello=sha256_archivo(carpeta/ARCHIVO)
    with bloqueo(carpeta):
        # Volver a comprobar el estado dentro del bloqueo, antes de reservar el intento.
        datos=abrir_ejecucion(root,carpeta)
        destino,event,estado=preparar_intento(carpeta,sello,etapa,accion)
        deps={k:carpeta/estado['etapas'][k]['carpeta'] for k in ETAPAS[etapa]['dependencias']}
        productos=[p for k in deps for p in estado['etapas'][k]['productos']]
        from .operacion_2028 import FUENTES
        demanda_previa=[FUENTES['origenes'],datos['configuracion']['indice']['demanda_horaria']]
        lecturas=set()
        try:
            with lecturas_de_etapa(root,carpeta,destino,datos['registro']['fuentes'],productos,etapa,demanda_original=demanda_previa) as lecturas:
                resultado=_producir(root,carpeta,datos,etapa,accion,destino,deps,copert=copert,intercambio=intercambio)
            if configuracion_resuelta(leer_configuracion(root))!=datos['configuracion']:raise ErrorParametros('La configuración cambió durante la etapa.')
            from movilidad_teide.configuracion.registro import _comprobar_archivos
            _comprobar_archivos(root,datos['registro']['fuentes'])
            _json(destino/'lecturas_de_etapa.json',dict(etapa=etapa,dependencias=event['dependencias'],lecturas=sorted(lecturas),resultado=resultado))
            salidas=describir_productos(carpeta,destino,etapa)
            cierre={**event,'estado':'completada','productos':salidas,'resultado':resultado,'lecturas':sorted(lecturas)}
            agregar_suceso(carpeta,sello,cierre)
            leer_estado(carpeta,sello)
            return dict(etapa=etapa,accion=accion,estado='completada',productos=len(salidas),resultado=resultado)
        except BaseException as error:
            agregar_suceso(carpeta,sello,{**event,'estado':'fallida','productos':[],'error':type(error).__name__+': '+str(error),'lecturas_antes_del_fallo':sorted(lecturas)})
            raise
