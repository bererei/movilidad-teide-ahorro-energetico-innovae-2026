"""vehiculos: catalogo copert. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from movilidad_teide.vehiculos.flota_tipos import ErrorFlota


def leer_claves_copert(path, *, hoja=None):
    """Leer claves exactas de una exportación; no certificar completitud ni factores.

    Se admiten Input Structure (hoja STOCK) y exportaciones de Stock Configuration
    con los cuatro encabezados oficiales. El alcance se documenta por separado:
    una selección del proyecto no es el catálogo completo de la instalación.
    Include se conserva por separado y nunca filtra las categorías exportadas.
    """
    from openpyxl import load_workbook
    import csv
    columnas=['Category','Fuel','Segment','Euro Standard']
    path=Path(path)
    if path.suffix.lower()=='.xlsx':
        with path.open('rb') as f:
            book=load_workbook(f,read_only=True,data_only=True)
            try:
                nombre=hoja or ('STOCK' if 'STOCK' in book.sheetnames else book.sheetnames[0] if len(book.sheetnames)==1 else None)
                if nombre is None or nombre not in book.sheetnames:
                    raise ErrorFlota('Indicar una hoja inequívoca para leer las categorías.')
                filas=list(book[nombre].values)
            finally:
                book.close()
    elif path.suffix.lower()=='.csv':
        if hoja is not None: raise ErrorFlota('Una exportación CSV no tiene hojas.')
        with path.open(encoding='utf-8-sig',newline='') as f:
            muestra=f.read(8192);f.seek(0)
            try: dialecto=csv.Sniffer().sniff(muestra,delimiters=';,\t')
            except csv.Error as error: raise ErrorFlota('Separador CSV no reconocido.') from error
            filas=list(csv.reader(f,dialecto))
    else:
        raise ErrorFlota('Utilizar una exportación XLSX o CSV de COPERT.')
    if not filas or any(list(filas[0]).count(c)!=1 for c in columnas):
        raise ErrorFlota('Faltan o se repiten encabezados oficiales de la clave COPERT.')
    indices=[list(filas[0]).index(c) for c in columnas]
    if list(filas[0]).count('Include')>1:
        raise ErrorFlota('La columna Include no puede estar repetida.')
    indice_include=list(filas[0]).index('Include') if 'Include' in filas[0] else None
    claves=[];incluidos=[]
    for fila in filas[1:]:
        if all(v is None or v=='' for v in fila): continue
        valores=[fila[i] if i<len(fila) else None for i in indices]
        if any(not isinstance(v,str) or not v.strip() for v in valores):
            raise ErrorFlota('La clave debe tener cuatro etiquetas de texto presentes; no se completan vacíos.')
        # Se conservan incluso los espacios de las etiquetas: no corregir claves por similitud.
        claves.append(valores)
        if indice_include is not None:
            incluido=fila[indice_include] if indice_include<len(fila) else None
            if isinstance(incluido,bool): incluidos.append(incluido)
            elif isinstance(incluido,str) and incluido.casefold() in ['true','false']:
                incluidos.append(incluido.casefold()=='true')
            else: raise ErrorFlota('Include debe ser un booleano explícito; no se infiere desde vacíos o números.')
    tabla=pd.DataFrame(claves,columns=columnas)
    if indice_include is not None:tabla['incluido_en_exportacion']=incluidos
    if tabla.empty or tabla.duplicated(columnas).any():
        raise ErrorFlota('La exportación debe contener claves únicas y no estar vacía.')
    return tabla

def revisar_claves_copert(seleccion, catalogo, *, alcance):
    """Distinguir clave presente, ausente e incompleta sin adoptar un vehículo."""
    campos=['categoria_copert_candidata','familia_combustible_candidata','segmento_candidato','euro_candidato']
    columnas=['Category','Fuel','Segment','Euro Standard']
    if alcance not in ['seleccion_proyecto','catalogo_instalacion']:
        raise ErrorFlota('Identificar el alcance de la exportación COPERT.')
    if not {'id_vehiculo',*campos}<=set(seleccion) or not set(columnas)<=set(catalogo):
        raise ErrorFlota('Faltan campos de selección o de categorías.')
    if seleccion.id_vehiculo.isna().any() or seleccion.id_vehiculo.duplicated().any():
        raise ErrorFlota('Cada vehículo propuesto necesita una identidad única.')
    if catalogo.empty or catalogo[columnas].duplicated().any():
        raise ErrorFlota('La exportación debe contener claves únicas, no un catálogo vacío.')
    if any(not isinstance(v,str) or not v.strip() for v in catalogo[columnas].to_numpy().ravel()):
        raise ErrorFlota('El catálogo no admite etiquetas ausentes.')
    claves=set(catalogo[columnas].itertuples(index=False,name=None))
    filas=[]
    for ficha in seleccion.to_dict('records'):
        clave=tuple(ficha[c] for c in campos)
        faltan=[c for c,v in zip(columnas,clave) if not isinstance(v,str) or not v.strip()]
        presente=tuple(clave) in claves if not faltan else None
        if faltan: estado='Clave incompleta: necesita propuesta o ficha técnica'
        elif presente: estado='Clave presente en exportación; representatividad y factor se verifican por separado'
        elif alcance=='seleccion_proyecto': estado='No consta en esta selección; no demuestra ausencia del catálogo'
        else: estado='Clave no encontrada en el catálogo exportado; revisar sin sustituir por similitud'
        filas.append(dict(id_vehiculo=ficha['id_vehiculo'],**dict(zip(columnas,clave)),
            campos_ausentes='; '.join(faltan),clave_completa=not faltan,presente_en_exportacion=presente,
            alcance_exportacion=alcance,estado=estado,vehiculo_adoptado=False))
    return pd.DataFrame(filas)

def contrastar_familias_catalogo(familias, catalogo):
    """Revisar disponibilidad de familias, sin elegir tamaño/Euro ni actividad.

    La búsqueda se restringe a Passenger Cars: una familia de guagua híbrida no
    cubre turismos híbridos. OTH conserva energía desconocida; no se redistribuye.
    Las coincidencias son familias disponibles, no claves completas ni factores.
    """
    columnas=['Category','Fuel','Segment','Euro Standard']
    if not {'id_vehiculo','codigo_energia','familia_combustible_candidata','cuota_stock_base','vehiculos_stock_referencia'}<=set(familias):
        raise ErrorFlota('Faltan campos de familias y su stock de referencia.')
    if familias.codigo_energia.isna().any() or familias.codigo_energia.duplicated().any():
        raise ErrorFlota('Conservar una fila inequívoca por energía.')
    if not set(columnas)<=set(catalogo) or catalogo.empty or catalogo[columnas].duplicated().any():
        raise ErrorFlota('Se necesitan claves COPERT únicas y completas.')
    if any(not isinstance(v,str) or not v.strip() for v in catalogo[columnas].to_numpy().ravel()):
        raise ErrorFlota('Las claves del catálogo no admiten etiquetas ausentes.')
    turismos=catalogo.loc[catalogo.Category.eq('Passenger Cars')]
    if turismos.empty:
        raise ErrorFlota('La exportación no incluye turismos; no afirmar ausencia de sus familias.')
    filas=[]
    for f in familias.to_dict('records'):
        codigo=f['codigo_energia'];combustible=f['familia_combustible_candidata']
        if codigo=='OTH':
            candidatas=turismos.iloc[:0]
            estado='Energía residual sin identificar; no asignar combustible desde el catálogo'
            n_claves=None
        elif codigo=='ELC_DIE_HYB':
            # Buscar una familia diésel híbrida no enchufable, sin usar Buses o PHEV como sustitutos.
            texto=(turismos.Fuel+' '+turismos.Segment).str.casefold()
            mascara=texto.str.contains('diesel',regex=False)&texto.str.contains('hybrid',regex=False)
            mascara &= ~texto.str.contains('phev|plug',regex=True)
            candidatas=turismos.loc[mascara]
            n_claves=len(candidatas)
            estado=('Revisar familia nativa diésel híbrida; no equivale a PHEV' if n_claves else
                    'Sin correspondencia directa de turismo diésel híbrido no enchufable en el catálogo aportado')
        else:
            if not isinstance(combustible,str) or not combustible:
                raise ErrorFlota('La familia necesita un combustible explícito antes del contraste.')
            candidatas=turismos.loc[turismos.Fuel.eq(combustible)]
            n_claves=len(candidatas)
            estado=('Familia presente; tamaño/Euro y pesos de actividad todavía pendientes' if n_claves else
                    'Familia no encontrada en Passenger Cars del catálogo aportado')
        filas.append(dict(id_vehiculo=f['id_vehiculo'],codigo_energia=codigo,
            vehiculos_stock_referencia=f['vehiculos_stock_referencia'],cuota_stock_base=f['cuota_stock_base'],
            claves_familia_disponibles=n_claves,
            familia_con_correspondencia=bool(len(candidatas)),
            segmentos_disponibles=' | '.join(candidatas.Segment.drop_duplicates()),
            normas_disponibles=' | '.join(candidatas['Euro Standard'].drop_duplicates()),
            estado_correspondencia=estado,peso_actividad_adoptado=False))
    resultado=pd.DataFrame(filas)
    resultado['claves_familia_disponibles']=resultado.claves_familia_disponibles.astype('Int64')
    return resultado

def resumir_segmentos_catalogo(catalogo, categoria):
    """Resumir combustibles/segmentos conservando exactamente sus normas nativas."""
    columnas=['Category','Fuel','Segment','Euro Standard']
    if not set(columnas)<=set(catalogo) or catalogo.empty or catalogo[columnas].duplicated().any():
        raise ErrorFlota('Se necesitan claves únicas del catálogo.')
    base=catalogo.loc[catalogo.Category.eq(categoria)]
    if base.empty:raise ErrorFlota('La categoría solicitada no consta en la exportación.')
    filas=[]
    for (fuel,segmento),g in base.groupby(['Fuel','Segment'],sort=False):
        filas.append(dict(Category=categoria,Fuel=fuel,Segment=segmento,n_claves=len(g),
            normas_disponibles=' | '.join(g['Euro Standard']),vehiculo_elegido=False))
    return pd.DataFrame(filas)

def proponer_claves_desde_microdatos(cruce, catalogo):
    """Precisar combustible/Euro documentados y listar tamaños todavía alternativos.

    El soporte es número de registros del perfil, repetido para mostrar cada
    alternativa. No debe sumarse entre segmentos ni utilizarse como stock CLI.
    """
    claves=['Category','Fuel','Segment','Euro Standard']
    requeridas={'ambito_geografico','grupo_servicio','categoria_turismo_compatible','familia_copert','euro_copert','norma_para_factor_compatible','vehiculos'}
    if not requeridas <= set(cruce) or not set(claves) <= set(catalogo):
        raise ErrorFlota('Faltan agregados DGT o las cuatro etiquetas exactas del catálogo COPERT.')
    if catalogo[claves].isna().any().any() or catalogo.duplicated(claves).any():
        raise ErrorFlota('Las claves del catálogo deben ser completas y únicas.')
    n=pd.to_numeric(cruce.vehiculos,errors='coerce')
    if not np.isfinite(n).all() or n.le(0).any() or n.mod(1).ne(0).any():
        raise ErrorFlota('Los soportes deben ser conteos enteros positivos, no pesos o estimaciones.')
    t=cruce.loc[cruce.ambito_geografico.eq('Tenerife identificado') & cruce.categoria_turismo_compatible
        & cruce.familia_copert.ne('') & cruce.norma_para_factor_compatible]
    perfiles=t.groupby(['familia_copert','euro_copert'],as_index=False).vehiculos.sum()
    opciones=catalogo.loc[catalogo.Category.eq('Passenger Cars'),claves].copy()
    planes=perfiles.merge(opciones,left_on=['familia_copert','euro_copert'],right_on=['Fuel','Euro Standard'],how='left',validate='one_to_many')
    planes=planes.rename(columns={'vehiculos':'registros_soporte_del_perfil_no_sumar_entre_segmentos'})
    planes['clave_disponible']=planes[claves].notna().all(axis=1)
    planes['segmento_elegido']=False;planes['factor_ejecutado']=False
    planes['peso_actividad_elegido']=np.nan
    planes['estado']='Alternativas exactas de tamaño; no mezcla elegida ni peso de actividad'
    return planes.sort_values(['registros_soporte_del_perfil_no_sumar_entre_segmentos','Fuel','Euro Standard','Segment'],ascending=[False,True,True,True],na_position='last').reset_index(drop=True)
