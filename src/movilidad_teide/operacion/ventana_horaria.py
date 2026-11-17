"""Cierro circulaciones en una ventana explícita, sin alterar sus tiempos."""
import numpy as np
from .circulacion_compartida import encadenar_viajes,materializar
from .inventario_comun import bases_posibles,asignar_bases


def cerrar_en_ventana(candidatos,red,valores,capacidades,identidades,*,inicio_min,fin_min,maximo_programado=27):
    """Conservo la flota y hago explícito hasta cuándo puede volver a sus bases."""
    if (not np.isfinite([inicio_min,fin_min]).all() or inicio_min>=fin_min
        or set(capacidades)!=set(identidades) or any(capacidades[b]!=len(identidades[b]) for b in capacidades)
        or sum(capacidades.values())!=30 or not 0<maximo_programado<=27):
        raise ValueError("Ventana o inventario incompatibles con treinta y tres de sustitución.")
    todos=[i for ids in identidades.values() for i in ids]
    if len(set(todos))!=30:raise ValueError("Identidades de flota repetidas.")
    for key,reloj,u,b in candidatos:
        if key[0]>maximo_programado:continue
        viajes,reservas=reloj.tablas(u,b)
        for criterio in ["distancia","tiempo","servicio"]:
            t,cadenas=encadenar_viajes(viajes,red,regulacion=valores["regulacion_min"],criterio=criterio)
            ss,ee=bases_posibles(t,cadenas,red,inicio=inicio_min,fin=fin_min,regulacion=valores["regulacion_min"])
            cierre,_=asignar_bases(ss,ee,red.bases,capacidades)
            if cierre is None:continue
            aa,bb=cierre
            movimientos=materializar(t,cadenas,aa,red,regulacion=valores["regulacion_min"],bases_finales=bb)
            ids={base:lista.copy() for base,lista in identidades.items()}
            equivalencias={f"TF{k+1:02d}":ids[base].pop(0) for k,base in enumerate(aa)}
            for original,real in equivalencias.items():
                mask=movimientos.unidad_fisica_id.eq(original)&movimientos.familia.eq("Vacío")
                movimientos.loc[mask,"id_salida"]=movimientos.loc[mask,"id_salida"].str.replace(original+"_",real+"_",n=1,regex=False)
            movimientos["unidad_fisica_id"]=movimientos.unidad_fisica_id.map(equivalencias)
            return {"viajes":viajes,"reservas":reservas,"movimientos":movimientos,"programadas":len(cadenas),
                "forma":key[2],"fraccion_regreso":key[3],"criterio_encadenamiento":criterio}
    return None
