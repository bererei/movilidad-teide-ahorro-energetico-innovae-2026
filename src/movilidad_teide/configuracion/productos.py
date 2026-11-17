"""Sucesos inmutables y productos de etapas vinculados al registro inicial."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from .contratos_etapas import ETAPAS
from .parametros_tipos import ErrorParametros
from .registro import _ruta_interna
from movilidad_teide.trazabilidad import sha256_archivo

ESTADO = 'estado_ejecucion.json'


def _bytes(datos):
    return (json.dumps(datos,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')


def _atomico(path,contenido):
    temporal=path.with_name('.'+path.name+'.'+uuid4().hex+'.tmp')
    try:
        with temporal.open('xb') as f:f.write(contenido);f.flush();os.fsync(f.fileno())
        os.replace(temporal,path)
    finally:
        if temporal.exists():temporal.unlink()


@contextmanager
def bloqueo(carpeta):
    """Serializar escritores en el entorno Ubuntu/WSL del proyecto.

    El sistema libera el bloqueo al terminar el proceso, incluso si se interrumpe.
    El archivo se conserva; su existencia no significa que haya un proceso activo.
    """
    import fcntl
    p=Path(carpeta)/'bloqueo_etapas'
    if p.is_symlink():raise ErrorParametros('El bloqueo no puede ser un enlace.')
    with p.open('a+b') as f:
        try:fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise ErrorParametros('Hay otra etapa en ejecución en este registro.') from exc
        try:yield
        finally:fcntl.flock(f.fileno(),fcntl.LOCK_UN)


def leer_estado(carpeta,registro_sha256,*,verificar_productos=True):
    carpeta=Path(carpeta).resolve();head=carpeta/ESTADO;directory=carpeta/'eventos'
    etapas={k:dict(nombre=v['nombre'],estado='pendiente') for k,v in ETAPAS.items()}
    if not head.exists():
        if directory.exists() and any(directory.iterdir()):raise ErrorParametros('Hay sucesos sin índice de estado; conserva la carpeta y revisa su integridad.')
        return dict(etapas=etapas,productos=0,eventos=[],ultimo_sha256=None)
    if head.is_symlink() or directory.is_symlink():raise ErrorParametros('El estado no admite enlaces.')
    h=json.loads(head.read_text());files=sorted(directory.glob('*.json'));anterior=None;events=[];productos={}
    if h.get('version')!='1.0' or h.get('registro_sha256')!=registro_sha256 or h.get('eventos')!=len(files):
        raise ErrorParametros('El índice de etapas no corresponde al registro o faltan sucesos.')
    for numero,p in enumerate(files,1):
        digest=sha256_archivo(p)
        if p.is_symlink() or p.name!=f'{numero:06d}_{digest}.json':raise ErrorParametros('Un suceso de etapa fue alterado o renumerado.')
        e=json.loads(p.read_text());key=e.get('etapa')
        if (key not in ETAPAS or e.get('numero')!=numero or e.get('anterior_sha256')!=anterior
                or e.get('registro_sha256')!=registro_sha256 or e.get('accion') not in ETAPAS[key]['acciones']):
            raise ErrorParametros('Cadena de sucesos o acción incompatible con el registro.')
        if e.get('estado') not in ['iniciada','completada','fallida']:raise ErrorParametros('Estado de etapa desconocido.')
        deps=e.get('dependencias',{})
        if set(deps)!=set(ETAPAS[key]['dependencias']):raise ErrorParametros('Dependencias de etapa incompletas.')
        for dep,sello in deps.items():
            if etapas[dep]['estado']!='completada' or etapas[dep].get('evento_sha256')!=sello:
                raise ErrorParametros('La etapa mezcla productos de otro intento o una dependencia incompleta.')
        _ruta_interna(carpeta,e['carpeta'])
        if not e['carpeta'].startswith('resultados/'+key+'/'):raise ErrorParametros('Carpeta de producto ajena a su etapa.')
        prev=etapas[key]
        if e['estado']=='iniciada':
            if prev['estado']=='completada':raise ErrorParametros('No se reemplaza una etapa completada dentro de la misma ejecución.')
            if e.get('productos'):raise ErrorParametros('Una etapa iniciada no puede acreditar productos.')
        elif prev['estado']!='iniciada' or any(prev.get(k)!=e.get(k) for k in ['carpeta','accion','dependencias']):
            raise ErrorParametros('El cierre no corresponde al inicio de la etapa.')
        if e['estado']=='completada':
            if not e.get('productos'):raise ErrorParametros('Una etapa completada debe identificar sus archivos.')
            if len({x['ruta'] for x in e['productos']})!=len(e['productos']):raise ErrorParametros('Producto repetido.')
            for x in e['productos']:
                if not x['ruta'].startswith(e['carpeta']+'/') or x['ruta'] in productos:
                    raise ErrorParametros('Producto fuera del intento o usado por otra etapa.')
                q=_ruta_interna(carpeta,x['ruta'])
                if verificar_productos and (not q.is_file() or q.stat().st_size!=x['bytes'] or sha256_archivo(q)!=x['sha256']):
                    raise ErrorParametros('Producto registrado ausente o alterado: '+x['ruta'])
                productos[x['ruta']]=x
        elif e.get('productos'):raise ErrorParametros('No se aceptan productos de una etapa incompleta o fallida.')
        etapas[key]={**e,'nombre':ETAPAS[key]['nombre'],'evento_sha256':digest}
        anterior=digest;events.append(e)
    if h.get('ultimo_sha256')!=anterior:raise ErrorParametros('El último suceso no coincide con el estado publicado.')
    return dict(etapas=etapas,productos=len(productos),eventos=events,ultimo_sha256=anterior)


def agregar_suceso(carpeta,registro_sha256,datos):
    """Publicar un suceso sin reescribir sus antecesores; requiere bloqueo del llamador."""
    carpeta=Path(carpeta);estado=leer_estado(carpeta,registro_sha256)
    e=dict(datos,numero=len(estado['eventos'])+1,anterior_sha256=estado['ultimo_sha256'],
           registro_sha256=registro_sha256,fecha_utc=datetime.now(timezone.utc).isoformat())
    contenido=_bytes(e);sello=sha256(contenido).hexdigest();directory=carpeta/'eventos';directory.mkdir(exist_ok=True)
    p=directory/f"{e['numero']:06d}_{sello}.json"
    with p.open('xb') as f:f.write(contenido);f.flush();os.fsync(f.fileno())
    _atomico(carpeta/ESTADO,_bytes(dict(version='1.0',registro_sha256=registro_sha256,eventos=e['numero'],ultimo_sha256=sello)))
    return sello


def preparar_intento(carpeta,registro_sha256,etapa,accion):
    if etapa not in ETAPAS or accion not in ETAPAS[etapa]['acciones']:raise ErrorParametros('Etapa o acción no reconocida.')
    estado=leer_estado(carpeta,registro_sha256)
    if estado['etapas'][etapa]['estado']=='completada':raise ErrorParametros('La etapa ya está completada. Consúltala o crea otra ejecución para repetirla.')
    deps={}
    for key in ETAPAS[etapa]['dependencias']:
        if estado['etapas'][key]['estado']!='completada':raise ErrorParametros('Primero debe completarse la etapa '+key+'.')
        deps[key]=estado['etapas'][key]['evento_sha256']
    # Un proceso interrumpido puede dejar el último intento iniciado. Se registra
    # su cierre fallido antes de abrir otro; sus archivos se conservan íntegros.
    previa=estado['etapas'][etapa]
    if previa['estado']=='iniciada':
        agregar_suceso(carpeta,registro_sha256,dict(etapa=etapa,accion=previa['accion'],estado='fallida',
            carpeta=previa['carpeta'],dependencias=previa['dependencias'],productos=[],
            error='Intento interrumpido antes de registrar un cierre; se conserva sin aceptar sus productos.'))
    relativo='resultados/'+etapa+'/'+uuid4().hex
    destino=_ruta_interna(Path(carpeta),relativo);destino.mkdir(parents=True,exist_ok=False)
    e=dict(etapa=etapa,accion=accion,estado='iniciada',carpeta=relativo,dependencias=deps,productos=[])
    agregar_suceso(carpeta,registro_sha256,e)
    return destino,e,estado


def describir_productos(carpeta,destino,etapa):
    """Registrar archivos efectivos, distinguiendo controles y selecciones fijadas."""
    carpeta,destino=Path(carpeta),Path(destino);out=[]
    for p in sorted(destino.rglob('*')):
        if p.is_symlink():raise ErrorParametros('Un producto no puede ser un enlace: '+str(p))
        if not p.is_file():continue
        name=p.relative_to(destino).as_posix();papel='resultado_calculado'
        if etapa=='03' or (etapa=='04' and name.startswith('insumos/')):papel='dato_fijado_copiado'
        if etapa=='05':papel='factor_normalizado_y_comparado'
        if etapa=='07':papel='comprobacion'
        if p.suffix=='.json' or p.name.startswith(('indice_','lecturas_','contrato_')):papel='control'
        if etapa=='06' and name.startswith('calculo/'):
            papel='intermedio_de_calculo'
            if name.startswith(('calculo/config/','calculo/data/silver/operacion/','calculo/data/bronze/')):papel='dato_fijado_copiado'
        out.append(dict(ruta=p.relative_to(carpeta).as_posix(),sha256=sha256_archivo(p),bytes=p.stat().st_size,
                        papel=papel,formato=p.suffix.lstrip('.') or 'binario',unidades=ETAPAS[etapa]['unidades']))
    return out
