"""Selección explícita de archivos y condiciones, sin modificar las fuentes."""
from pathlib import Path
import csv
from .nucleo import dump,copiar_nucleo
from .reserva import leer_politica,catalogo_completo
import json

def csvout(path,rows):
    if not rows:return
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter=';');w.writeheader();w.writerows(rows)

def evaluar_seleccion(root,politica=None):
    """Exigir una decisión por archivo y distinguir selección de permiso de difusión."""
    root=Path(root).resolve();politica=politica or leer_politica(root)
    inventory=catalogo_completo(json.loads((root/'manifiestos/archivos.json').read_text()))
    def rows(name):
        with (root/'manifiestos'/name).open(encoding='utf-8-sig',newline='') as f:
            return list(csv.DictReader(f,delimiter=';'))
    selected=rows('seleccion_entrega_publica.csv')
    bypath={r['ruta']:r for r in selected}
    expected=set(inventory)|{'manifiestos/archivos.json'}
    if len(bypath)!=len(selected) or set(bypath)!=expected:
        raise ValueError('La selección debe cubrir exactamente el inventario vigente y su manifiesto, sin duplicados.')
    conditions=rows('condiciones_entrega_publica.csv');bycase={r['condicion']:r for r in conditions}
    if len(bycase)!=len(conditions):raise ValueError('Condición de entrega repetida.')
    pending=[];omitted=[]
    for n,row in sorted(bypath.items()):
        decision=row.get('decision_final_8_2','')
        if decision!='incluir':
            raise ValueError('Decisión final pendiente o archivo de desarrollo dentro del núcleo vigente: '+n)
        if politica.excluye(n):omitted.append(n);continue
        case=row.get('caso_externo','')
        if case:
            if case not in bycase:raise ValueError('Caso externo sin condición documentada: '+case)
            condition=bycase[case]
            if condition['estado'] not in {'cumplida','verificada','no_aplica'}:
                pending.append(dict(ruta=n,caso=case,estado=condition['estado'],comprobacion=condition['comprobacion_para_cierre']))
    return dict(archivos_seleccionados=len(expected)-len(omitted),documentos_segun_gitignore=len(omitted),
                condiciones_pendientes=pending,casos_pendientes=sorted({r['caso'] for r in pending}),
                apta_para_difusion=not pending,control_documental='.gitignore')

def preparar(root,destination,extra=(),*,gitignore_publico=None,ensayo_local=False):
    if extra:raise ValueError('La entrega no admite añadidos implícitos fuera del manifiesto y del selector.')
    root=Path(root).resolve();destination=Path(destination).resolve()
    if destination==root or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError('El destino debe quedar fuera del árbol de origen.')
    if destination.exists() and any(destination.iterdir()):raise FileExistsError('Conservar el destino anterior y elegir uno vacío.')
    politica=leer_politica(root,gitignore_publico);control=evaluar_seleccion(root,politica)
    if not control['apta_para_difusion'] and not ensayo_local:
        raise ValueError('Difusión pendiente de condiciones: '+', '.join(control['casos_pendientes'])+'. Para comprobar una copia local completa, usar --ensayo-local; no concede derechos de difusión.')
    tree=copiar_nucleo(root,destination/'arbol_publicacion',politica=politica)
    dump(destination/'CONTROL_SELECCION.json',dict(control,ensayo_local=bool(ensayo_local),publicacion_realizada=False))
    return tree
