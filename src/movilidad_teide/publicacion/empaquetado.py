"""Paquetes con rutas Medallion y la reserva definida exclusivamente en .gitignore."""
from pathlib import Path
import json,zipfile,shutil
from .nucleo import sha,dump,verificar
from .reserva import leer_politica,proyectar
from .seleccion import evaluar_seleccion


def empaquetar(tree,destination,*,ensayo_local=False):
    tree,destination=Path(tree).resolve(),Path(destination).resolve()
    if destination==tree or destination.is_relative_to(tree):raise ValueError('Los ZIP deben quedar fuera del árbol que empaquetan.')
    if destination.exists() and any(destination.iterdir()):raise FileExistsError('Se conservan paquetes anteriores; usar un destino vacío.')
    verificar(tree);politica=leer_politica(tree);manifest=proyectar(tree,politica)
    control=evaluar_seleccion(tree,politica) if (tree/'manifiestos/seleccion_entrega_publica.csv').is_file() else None
    if control is None and str(manifest.get('version','')).startswith('2.8'):
        raise ValueError('La entrega requiere su selector y condiciones.')
    if control and not control['apta_para_difusion'] and not ensayo_local:
        raise ValueError('No se preparan paquetes para difusión con condiciones pendientes; --ensayo-local permite únicamente su prueba local.')
    files=[row['ruta'] for row in manifest['archivos']]+['manifiestos/archivos.json']
    # El inventario del ZIP describe sus archivos, incluso si se empaqueta una raíz completa bajo reserva.
    virtual={'manifiestos/archivos.json':(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()}
    if politica.existe:virtual['.gitignore']=politica.contenido
    destination.mkdir(parents=True,exist_ok=True);packages=[]
    for name,group in [('codigo_y_documentacion.zip',None),('datos_bronze.zip','bronze'),('datos_silver.zip','silver'),('datos_gold.zip','gold')]:
        selected=[n for n in files if n.startswith('data/'+group+'/')] if group else [n for n in files if not n.startswith('data/')]
        if any(politica.excluye(n) for n in selected):raise ValueError('Se ha intentado incluir documentación reservada en un paquete.')
        p=destination/name
        with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,strict_timestamps=False) as z:
            for n in sorted(selected):
                q=tree/n
                if q.is_symlink() or not q.resolve().is_relative_to(tree):raise ValueError('Archivo externo al árbol: '+n)
                info=zipfile.ZipInfo(n,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.create_system=3;info.external_attr=0o100644<<16
                with z.open(info,'w',force_zip64=True) as target:
                    if n in virtual:target.write(virtual[n])
                    else:
                        with q.open('rb') as source:shutil.copyfileobj(source,target,1024*1024)
        with zipfile.ZipFile(p) as z:
            bad=z.testzip()
            if bad:raise ValueError('ZIP incorrecto: '+bad)
            if any(politica.excluye(n) for n in z.namelist()):raise ValueError('El ZIP contiene un documento reservado.')
        packages.append({'archivo':name,'archivos':len(selected),'bytes':p.stat().st_size,'sha256':sha(p),'capa':group or 'codigo_y_documentacion'})
        print('Paquete verificado:',name,len(selected),'archivos',p.stat().st_size,'bytes',flush=True)
    reference=tree/'manifiestos/referencia.json'
    dump(destination/'manifiesto_paquetes.json',{'estado':'Ensayo local completo con condiciones pendientes' if control and not control['apta_para_difusion'] else 'Entrega preparada localmente, no publicada','ensayo_local':bool(ensayo_local),'apta_para_difusion':control['apta_para_difusion'] if control else False,'casos_pendientes':control['casos_pendientes'] if control else [],'zip_determinista':True,'referencia':json.loads(reference.read_text()) if reference.exists() else None,
         'politica_documental':politica.resumen(),'documentos_no_distribuidos':len(manifest.get('documentos_no_distribuidos',[])),
         'extraccion':'Extraer los cuatro ZIP desde una misma raíz; verificar después con scripts/verificar_entrega.py','paquetes':packages})
    (destination/'SHA256SUMS').write_text(''.join(f"{p['sha256']}  {p['archivo']}\n" for p in packages))
    return packages
