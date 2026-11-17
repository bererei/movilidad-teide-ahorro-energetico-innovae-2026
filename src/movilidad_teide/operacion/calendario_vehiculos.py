"""Enlazo días ya construidos sin inventar reposiciones entre fechas."""
from collections import Counter
import pandas as pd


def materializar_calendario(calendario,resumen,movimientos,disponibilidad,inventario,*,max_programadas):
    """Asigno las mismas treinta identidades desde su posición real del día anterior.

    Los modelos de guagua, plazas y tiempos son comunes en este estudio.
    Solo renombro la unidad que ejecuta cada cadena; sus recorridos y horas
    permanecen iguales. Un calendario incompleto no se convierte en oferta.
    """
    original=inventario.set_index('unidad_fisica_id').base_red.to_dict()
    if len(inventario)!=30 or len(original)!=30:
        raise ValueError('Conservar treinta identidades físicas únicas.')
    stock=Counter(original.values());salidas=[];estados=[];jornadas=[]
    for (metodo,margen),r in resumen[resumen.ambito.eq('Calendario')].groupby(['metodo_calendario','margen_min'],sort=True):
        c=calendario[calendario.metodo_calendario.eq(metodo)].sort_values('fecha')
        if c.fecha.duplicated().any():raise ValueError('Una fecha se representa dos veces.')
        if not r.cierre.all():continue
        perfil=r.set_index('id_perfil')
        if not set(c.id_perfil).issubset(perfil.index):raise ValueError('Falta el horario de una fecha.')
        posicion=dict(original);plantillas={}
        for row in c.itertuples():
            idp=row.id_perfil
            if idp not in plantillas:
                a=disponibilidad[disponibilidad.id_perfil.eq(idp)&disponibilidad.margen_min.eq(margen)]
                m=movimientos[movimientos.id_perfil.eq(idp)&movimientos.margen_min.eq(margen)]
                if len(a)!=30 or set(a.unidad_fisica_id)!=set(original):raise ValueError('Inventario diario incompleto.')
                if not m.unidad_fisica_id.isin(original).all():raise ValueError('Aparece una unidad fuera del inventario.')
                if any(original[z.unidad_fisica_id]!=z.base_inicial for z in a.itertuples()):raise ValueError('Cambia una base inicial de la plantilla.')
                plantillas[idp]=(a,m)
            a,m=plantillas[idp];mapping={}
            for base in sorted(stock):
                plant=sorted(u for u,b in original.items() if b==base)
                actual=sorted(u for u,b in posicion.items() if b==base)
                if len(plant)!=len(actual):raise ValueError('El día anterior no conserva el stock por bases.')
                # Mantengo primero todas las identidades que siguen en su base;
                # después asigno las intercambiadas, incluidas las no programadas.
                for unit in plant:
                    if unit in actual:mapping[unit]=unit
                libres=[u for u in actual if u not in mapping.values()]
                for unit,real in zip([u for u in plant if u not in mapping],libres):mapping[unit]=real
            if len(set(mapping.values()))!=30:raise ValueError('Una guagua recibe dos identidades de plantilla.')
            diario=m.copy();diario['unidad_fisica_id_plantilla']=diario.unidad_fisica_id
            diario['unidad_fisica_id']=diario.unidad_fisica_id_plantilla.map(mapping)
            for fuente,real in mapping.items():
                mask=diario.unidad_fisica_id_plantilla.eq(fuente)&diario.familia.eq('Vacío')
                diario.loc[mask,'id_salida']=diario.loc[mask,'id_salida'].str.replace(fuente+'_',real+'_',n=1,regex=False)
            usadas=diario.unidad_fisica_id.nunique()
            if usadas>max_programadas:raise ValueError('El calendario supera la flota programable.')
            siguiente={}
            for z in a.itertuples():
                real=mapping[z.unidad_fisica_id];mm=diario[diario.unidad_fisica_id.eq(real)].sort_values('salida_min')
                if posicion[real]!=z.base_inicial:raise ValueError('Una guagua cambia de base entre días sin recorrido.')
                if not mm.empty and (mm.iloc[0].origen!=posicion[real] or mm.iloc[-1].destino!=z.base_final):
                    raise ValueError('La posición entre días no concuerda con los movimientos.')
                if mm.empty and z.base_final!=posicion[real]:raise ValueError('Una reserva cambia de base sin movimiento.')
                if bool(z.programada)!=bool(len(mm)):raise ValueError('Una reserva se presenta como servicio ordinario.')
                siguiente[real]=z.base_final
                estados.append({'fecha':row.fecha,'metodo_calendario':metodo,'margen_min':margen,'id_perfil':idp,
                    'unidad_fisica_id':real,'unidad_fisica_id_plantilla':z.unidad_fisica_id,'programada':bool(z.programada),
                    'base_inicial':posicion[real],'base_final':z.base_final})
            if Counter(siguiente.values())!=stock:raise ValueError('El calendario pierde el equilibrio por bases.')
            posicion=siguiente
            salidas.append(diario.assign(fecha=row.fecha))
            jornadas.append({'fecha':row.fecha,'metodo_calendario':metodo,'margen_min':margen,'id_perfil':idp,
                'programadas':usadas,'sin_programar':30-usadas,'movimientos':len(diario),
                'demanda_lanzadera_personas_dia':perfil.loc[idp,'demanda_lanzadera_personas_dia'],
                'fin_bases_permitido_min':perfil.loc[idp,'fin_bases_permitido_min']})
    return {'movimientos_calendario':pd.concat(salidas,ignore_index=True) if salidas else pd.DataFrame(),
            'disponibilidad_calendario':pd.DataFrame(estados),'jornadas_calendario':pd.DataFrame(jornadas)}
