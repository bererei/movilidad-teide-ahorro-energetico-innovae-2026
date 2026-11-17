"""Promoción verificable del cierre vigente a Gold, sin reemplazar antecedentes."""
from pathlib import Path
import hashlib,json,shutil


def _ruta(root,name):
    p=Path(name)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError('Ruta no portable: '+str(name))
    q=root/p
    if q.is_symlink() or not q.resolve().is_relative_to(root.resolve()):
        raise ValueError('Archivo externo o enlazado: '+str(name))
    return q


def _sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for part in iter(lambda:f.read(1048576),b''):h.update(part)
    return h.hexdigest()


def seleccionar_gold(root):
    """La misma selección de datos finales se aplica en desarrollo y publicación."""
    root=Path(root).resolve()
    index=json.loads((root/'config/referencia_ordenacion_2028.json').read_text())
    if index.get('arquitectura'):
        selected={str(p.relative_to(root)):str(p.relative_to(root)) for p in sorted((root/'data/gold').rglob('*')) if p.is_file() and p.name!='.gitkeep'}
        if len(selected)!=55:raise ValueError('El cierre Gold requiere los 55 productos vigentes.')
        return selected
    meta=json.loads((root/'docs/informe_energetico/metadatos.json').read_text())
    selected={}
    for name in index['productos_de_comparacion']:
        source=index.get('productos_actualizados',{}).get(name,str(Path(index['captura'])/name))
        selected['data/gold/referencia_anual/'+name]=source
    folder=root/'docs/informe_energetico/anexos_vigentes'
    if not folder.is_dir():raise FileNotFoundError('Faltan los anexos vigentes.')
    for p in sorted(folder.rglob('*')):
        if p.is_file():selected['data/gold/anexos/'+str(p.relative_to(folder))]=str(p.relative_to(root))
    version=meta['version_informe']
    archive=f'ANEXOS_ENERGETICOS_2028_v{version}.zip'
    selected['data/gold/'+archive]='docs/informe_energetico/'+archive
    for dest,source in selected.items():
        _ruta(root,dest)
        if not _ruta(root,source).is_file():raise FileNotFoundError('Falta el resultado vigente: '+source)
    return selected


def comprobar_gold(root,selected=None):
    root=Path(root).resolve();selected=selected if selected is not None else seleccionar_gold(root)
    rows=[]
    for dest,source in selected.items():
        target,original=_ruta(root,dest),_ruta(root,source)
        index=json.loads((root/'config/referencia_ordenacion_2028.json').read_text())
        if index.get('arquitectura') and _sha(target)!=index['gold_sha256'].get(dest):
            raise ValueError('Gold difiere del cierre aprobado: '+dest)
        if not target.is_file() or _sha(target)!=_sha(original):
            raise ValueError('Gold ausente o distinto de la referencia vigente: '+dest)
        rows.append({'gold':dest,'origen_vigente':source,'bytes':target.stat().st_size,'sha256':_sha(target)})
    return rows


def promover_gold(root,candidata=None,verificar=False):
    root=Path(root).resolve();selected=seleccionar_gold(root);plans=[]
    # Validar todo antes de crear un solo archivo en Gold.
    for dest,source in selected.items():
        original=_ruta(root,source);target=_ruta(root,dest);digest=_sha(original)
        if target.exists() and (not target.is_file() or _sha(target)!=digest):
            raise FileExistsError('Gold contiene otra referencia: '+dest+'. Conservar esa versión y preparar un destino nuevo; no se sobrescribe.')
        plans.append((dest,source,digest))
    if candidata is not None:
        candidate=Path(candidata).resolve()
        manifest=json.loads((candidate/'manifiestos/archivos.json').read_text())
        expected={row['ruta']:row['sha256'] for row in manifest['archivos'] if row['ruta'].startswith('data/gold/')}
        if set(expected)!=set(selected):raise ValueError('La candidata contiene una selección Gold diferente.')
        for dest,source,digest in plans:
            if expected[dest]!=digest or _sha(_ruta(candidate,dest))!=digest:
                raise ValueError('La candidata está desalineada con la referencia vigente: '+dest)
    created=0
    if not verificar:
        for dest,source,digest in plans:
            target=_ruta(root,dest)
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True)
                # El modo exclusivo evita reemplazar un archivo aparecido tras la comprobación.
                with _ruta(root,source).open('rb') as src,target.open('xb') as out:shutil.copyfileobj(src,out)
                created+=1
            if _sha(target)!=digest:raise ValueError('Copia distinta: '+dest)
    rows=comprobar_gold(root,selected)
    return {'archivos':rows,'archivos_verificados':len(rows),'archivos_creados':created,
            'candidata_comparada':candidata is not None,'identidad_bytes':True,
            'fuentes_y_antecedentes_reemplazados':False}
