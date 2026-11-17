"""Integridad del cálculo y de la documentación distribuida por su política Git."""
from pathlib import Path
import hashlib,json,shutil
from .reserva import leer_politica,catalogo_completo,proyectar


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def dump(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')


def verificar(root):
    root=Path(root).resolve();manifest=root/'manifiestos/archivos.json'
    data=json.loads(manifest.read_text());politica=leer_politica(root)
    catalogo=catalogo_completo(data);comprobados=reservados=0;politica_editada=False
    for nombre,row in catalogo.items():
        name=Path(nombre);path=root/name
        if (name.is_absolute() or '..' in name.parts or '\\' in nombre or name.as_posix()!=nombre
                or path.is_symlink() or not path.resolve().is_relative_to(root)):
            raise ValueError('Ruta de entrega no portable o enlazada: '+str(name))
        if politica.excluye(nombre):
            reservados+=1
            continue
        if not path.is_file():
            ayuda='Recuperar la entrega documental completa antes de levantar la reserva.' if nombre in {x['ruta'] for x in data.get('documentos_no_distribuidos',[])} else 'Descargar y extraer los paquetes de la release en la raíz.'
            raise ValueError('Falta '+str(name)+'. '+ayuda)
        if nombre=='.gitignore' and sha(path)!=row['sha256']:
            base=data.get('gitignore_editable',{}).get('sha256_fuera_del_bloque')
            if not base or base!=politica.sha256_base:
                raise ValueError('Archivo modificado fuera del bloque documental: .gitignore. Conservar las demás reglas de la entrega.')
            politica_editada=True;comprobados+=1
            continue
        if path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:
            raise ValueError('Archivo modificado: '+str(name)+'. Recuperar el paquete original; no modificar el manifiesto para aceptarlo.')
        comprobados+=1
    return {'archivos_verificados':comprobados,'visitas_sin_y_con':2500000,'rutas_comunes_directas':True,
            'materializacion_de_rutas_anteriores':False,'documentacion_reservada':politica.reservada,
            'documentos_reservados':reservados,'politica_documental':politica.resumen(),
            'bloque_gitignore_editado_desde_preparacion':politica_editada}


def copiar_nucleo(root,destino,*,politica=None):
    root,destino=Path(root).resolve(),Path(destino).resolve()
    if destino==root or destino.is_relative_to(root) or root.is_relative_to(destino):raise ValueError('La copia debe quedar fuera de la raíz original.')
    if destino.exists() and any(destino.iterdir()):raise FileExistsError('Conservar el destino existente y utilizar una carpeta vacía.')
    verificar(root);politica=politica or leer_politica(root);info=proyectar(root,politica)
    destino.mkdir(parents=True,exist_ok=True)
    for row in info['archivos']:
        name=row['ruta'];p=destino/name;p.parent.mkdir(parents=True,exist_ok=True)
        if name=='.gitignore':p.write_bytes(politica.contenido)
        else:shutil.copy2(root/name,p)
    dump(destino/'manifiestos/archivos.json',info)
    verificar(destino)
    return destino
