"""vehiculos: parque. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from itertools import product
import json
from pathlib import Path
import numpy as np
import pandas as pd
from movilidad_teide.vehiculos.flota_tipos import ErrorFlota


def _nombre_es(ficha):
    textos = [v['value'] for v in ficha['name']['text'] if v['lang'] == 'es']
    if len(textos) != 1:
        raise ErrorFlota('Cada código debe conservar una etiqueta española inequívoca.')
    return textos[0]

def seleccionar_istac(documento, seleccion):
    """Decodificar el cubo según sus índices, preservando vacíos y estados de observación.

    La última dimensión varía más deprisa. Las etiquetas se leen de metadatos;
    su orden puede ser diferente del orden de almacenamiento de los datos.
    """
    if isinstance(documento, (str, Path)):
        documento = json.loads(Path(documento).read_text())
    dimensiones = documento['data']['dimensions']['dimension']
    nombres = [d['dimensionId'] for d in dimensiones]
    if len(set(nombres)) != len(nombres) or set(seleccion) - set(nombres):
        raise ErrorFlota('Dimensión repetida o filtro no reconocido.')
    metadatos = {d['id']: d for d in documento['metadata']['dimensions']['dimension']}
    forma, indices, codigos, etiquetas = [], [], [], {}
    for dim in dimensiones:
        nombre = dim['dimensionId']
        representaciones = dim['representations']
        reps = sorted(representaciones['representation'], key=lambda r: r['index'])
        n = representaciones['total']
        codes = [r['code'] for r in reps]
        if [r['index'] for r in reps] != list(range(n)) or len(set(codes)) != n:
            raise ErrorFlota('Los índices deben ser únicos y cubrir toda la dimensión.')
        valores = metadatos[nombre]['dimensionValues']['value']
        if len({v['id'] for v in valores}) != len(valores):
            raise ErrorFlota('Etiquetas repetidas en los metadatos.')
        etiquetas[nombre] = {v['id']: _nombre_es(v) for v in valores}
        if set(codes) - etiquetas[nombre].keys():
            raise ErrorFlota('Faltan etiquetas para interpretar los códigos.')
        filtro = seleccion.get(nombre, codes)
        elegidos = list(filtro) if isinstance(filtro, (list, tuple)) else [str(filtro)]
        if not elegidos or len(set(elegidos)) != len(elegidos) or set(elegidos) - set(codes):
            raise ErrorFlota(f'Selección ausente, duplicada o desconocida en {nombre}.')
        forma.append(n)
        indices.append([codes.index(c) for c in elegidos])
        codigos.append(elegidos)
    n = int(np.prod(forma))
    tokens = [v.strip() for v in documento['data']['observations'].split('|')]
    if len(tokens) != n:
        raise ErrorFlota('El número de observaciones no corresponde a las dimensiones.')
    try:
        datos = np.array([float(v) if v else np.nan for v in tokens])
    except ValueError as error:
        raise ErrorFlota('Observación no numérica distinta de un vacío explícito.') from error
    if np.isinf(datos).any() or (datos[np.isfinite(datos)] < 0).any():
        raise ErrorFlota('El parque no puede contener infinitos o cantidades negativas.')
    if not np.equal(datos[np.isfinite(datos)] % 1, 0).all():
        raise ErrorFlota('Se esperan vehículos enteros, no cuotas ni energía.')
    estados = [''] * n
    for atributo in documento['data'].get('attributes', {}).get('attribute', []):
        if atributo['id'] == 'ESTADO_OBSERVACION':
            estados = [v.strip() for v in atributo['value'].split('|')]
            if len(estados) != n:
                raise ErrorFlota('Los estados no conservan la correspondencia con las observaciones.')
    # Recortar el cubo por sus coordenadas, sin sumar totales y subtotales.
    ix = np.ix_(*indices)
    tabla = pd.DataFrame(product(*codigos), columns=nombres)
    tabla['vehiculos'] = datos.reshape(forma)[ix].ravel()
    tabla['estado_observacion'] = np.array(estados, dtype=object).reshape(forma)[ix].ravel()
    for nombre in nombres:
        tabla[nombre + '_nombre'] = tabla[nombre].map(etiquetas[nombre])
    tabla['dataset_id'] = documento['id']
    tabla['version_fuente'] = documento['metadata']['version']
    return tabla

def composicion_validada(tabla, variable, *, subtotales=()):
    """Calcular cuotas de stock y exigir conservación frente al total oficial.

    La tabla debe contener un solo ámbito/tipo y una fila por año y clase.
    Los subtotales deben identificarse explícitamente: ALT no es otra energía.
    """
    if tabla.duplicated(['TIME_PERIOD', variable]).any():
        raise ErrorFlota('Hay más de un ámbito o se están mezclando dimensiones.')
    if tabla.vehiculos.isna().any() or not np.isfinite(tabla.vehiculos).all():
        raise ErrorFlota('Una composición completa no admite observaciones ausentes.')
    if (tabla.vehiculos < 0).any():
        raise ErrorFlota('Una composición no admite cantidades negativas.')
    filas = []
    for anio, grupo in tabla.groupby('TIME_PERIOD', sort=True):
        total = grupo.loc[grupo[variable].eq('_T'), 'vehiculos']
        if len(total) != 1 or total.iloc[0] <= 0:
            raise ErrorFlota('Se requiere un total oficial único y positivo por año.')
        partes = grupo.loc[~grupo[variable].isin(('_T', *subtotales))]
        if partes.empty or not np.isclose(partes.vehiculos.sum(), total.iloc[0], rtol=0, atol=1e-8):
            raise ErrorFlota('Las clases no suman el total; revisar ausencias o subtotales duplicados.')
        for f in partes.itertuples(index=False, name=None):
            fila = dict(zip(partes.columns, f))
            filas.append({'anio': int(anio), 'codigo': fila[variable], 'categoria': fila[variable + '_nombre'],
                          'vehiculos': int(fila['vehiculos']), 'total_ambito': int(total.iloc[0]),
                          'cuota': fila['vehiculos'] / total.iloc[0],
                          'estado_observacion': fila['estado_observacion']})
    return pd.DataFrame(filas)

def proponer_cuotas_energia(composicion, anio_base, anio_objetivo, anio_inicio):
    """Dos referencias no adoptadas: cuotas constantes y prolongación lineal reciente.

    Se extrapolan cuotas, no demanda de viajes ni flota del Teide. No se recortan
    ni renormalizan valores imposibles para ocultar un fallo de extrapolación.
    """
    if not anio_inicio < anio_base < anio_objetivo:
        raise ErrorFlota('Los años deben cumplir inicio < base < objetivo.')
    grupos = []
    for anio in [anio_inicio, anio_base]:
        tabla = composicion.loc[composicion.anio.eq(anio)].copy()
        if tabla.empty or tabla.codigo.duplicated().any() or tabla.cuota.isna().any():
            raise ErrorFlota('Se necesitan composiciones completas y únicas para ambos años.')
        if not np.isfinite(tabla.cuota).all() or not tabla.cuota.between(0, 1).all() or not np.isclose(tabla.cuota.sum(), 1, rtol=0, atol=1e-10):
            raise ErrorFlota('Las cuotas de origen deben estar entre 0 y 1 y sumar 1.')
        grupos.append(tabla.set_index('codigo'))
    inicial, base = grupos
    if set(inicial.index) != set(base.index):
        raise ErrorFlota('No se crean categorías ni ceros para suplir años no comparables.')
    inicial = inicial.reindex(base.index)
    cambio = (base.cuota - inicial.cuota) / (anio_base - anio_inicio)
    propuestas = []
    for metodo, cuota in [(f'Composición de {anio_base} constante', base.cuota),
                          (f'Continuación lineal de cuotas {anio_inicio}–{anio_base}', base.cuota + cambio * (anio_objetivo - anio_base))]:
        if not np.isfinite(cuota).all() or not cuota.between(0, 1).all() or not np.isclose(cuota.sum(), 1, rtol=0, atol=1e-10):
            raise ErrorFlota('La extrapolación sale del dominio; no se recorta ni normaliza automáticamente.')
        for codigo in base.index:
            propuestas.append({'metodo': metodo, 'anio_objetivo': anio_objetivo, 'codigo': codigo,
                'categoria': base.loc[codigo, 'categoria'], 'cuota_base': base.loc[codigo, 'cuota'],
                'cambio_anual_pp': 100 * cambio.loc[codigo], 'cuota_propuesta': cuota.loc[codigo],
                'estado': 'Propuesta técnica para revisión, no adoptada',
                'ambito': 'Parque fiscal de Tenerife, no flota visitante del Teide',
                'evolucion_comun_prevista': 'Coherente en sin y con actuación; captación por grupo aún pendiente',
                'aplicada_al_balance': False})
    return pd.DataFrame(propuestas)

def proponer_familias_turismos(composicion, propuestas, anio_base, anio_objetivo):
    """Reducir a familias por energía sin inventar Euro, tamaño ni actividad.

    Las cuotas son referencias de stock. Cada energía aparece una sola vez;
    las alternativas futuras se guardan en columnas distintas, sin sumarlas.
    """
    familias = {
        'PET_X_HYB': ('Petrol', 'Combustible líquido; obtener factores por segmento y tecnología'),
        'DIE_X_HYB': ('Diesel', 'Combustible líquido; obtener factores por segmento y tecnología'),
        'ELC_PET_HYB': ('Petrol Hybrid', 'HEV: no sustituir por un turismo de gasolina convencional'),
        'ELC': ('Battery electric', 'Electricidad y frontera de carga; no consumo energético cero'),
        'ELC_PET_PI': ('Petrol PHEV', 'Conservar modos eléctrico y térmico sin duplicar vehículos'),
        'BIFUEL_PET_LPG': ('LPG Bifuel', 'Conservar actividad por combustible sin duplicar vehículos'),
        'ELC_DIE_PI': ('Diesel PHEV', 'Conservar modos eléctrico y térmico sin duplicar vehículos'),
        'ELC_DIE_HYB': (None, 'Familia de turismo híbrido diésel por verificar; no sustituir por Diesel ni Buses'),
        'OTH': (None, 'Tecnología sin identificar; conservar el residual sin factor ficticio'),
    }
    columnas = {'anio','codigo','categoria','vehiculos','total_ambito','cuota'}
    if not columnas <= set(composicion) or not {'codigo','metodo','anio_objetivo','cuota_propuesta'} <= set(propuestas):
        raise ErrorFlota('Faltan composiciones o propuestas para preparar familias.')
    base = composicion.loc[composicion.anio.eq(anio_base)].copy()
    if base.codigo.duplicated().any() or set(base.codigo) != set(familias):
        raise ErrorFlota('Conservar exactamente las nueve energías elementales, sin ALT ni categorías omitidas.')
    numeros = base[['vehiculos','total_ambito','cuota']].to_numpy(dtype=float)
    if (not np.isfinite(numeros).all() or (numeros < 0).any()
            or (base.vehiculos % 1).ne(0).any() or base.total_ambito.nunique()!=1
            or base.total_ambito.iloc[0]<=0 or base.vehiculos.sum()!=base.total_ambito.iloc[0]
            or not np.allclose(base.cuota,base.vehiculos/base.total_ambito,rtol=0,atol=1e-12)):
        raise ErrorFlota('Las cantidades y cuotas del stock deben conservar el total oficial.')
    futuro = propuestas.loc[propuestas.anio_objetivo.eq(anio_objetivo)].copy()
    if futuro.duplicated(['metodo','codigo']).any() or futuro.metodo.nunique()!=2:
        raise ErrorFlota('Conservar por separado las dos referencias futuras completas.')
    metodos = [f'Composición de {anio_base} constante',
               f'Continuación lineal de cuotas {anio_base-(anio_objetivo-anio_base)}–{anio_base}']
    if set(futuro.metodo)!=set(metodos):
        raise ErrorFlota('Los métodos futuros no corresponden al periodo del modelo.')
    base = base.sort_values('cuota',ascending=False).reset_index(drop=True)
    base = base.rename(columns={'codigo':'codigo_energia','categoria':'vehiculo_propuesto',
        'vehiculos':'vehiculos_stock_referencia','cuota':'cuota_stock_base'})
    for metodo,col in zip(metodos,['cuota_stock_objetivo_constante','cuota_stock_objetivo_tendencia']):
        t = futuro.loc[futuro.metodo.eq(metodo)]
        if (set(t.codigo)!=set(familias) or t.cuota_propuesta.isna().any()
                or not np.isfinite(t.cuota_propuesta).all() or not t.cuota_propuesta.between(0,1).all()
                or not np.isclose(t.cuota_propuesta.sum(),1,rtol=0,atol=1e-10)):
            raise ErrorFlota('La referencia futura omite categorías o no conserva una composición válida.')
        base[col] = base.codigo_energia.map(t.set_index('codigo').cuota_propuesta)
    base['id_vehiculo'] = 'turismo_' + base.codigo_energia.str.lower()
    base['grupo_servicio'] = 'Turismos; particulares/alquiler sin reparto adoptado'
    base['categoria_copert_candidata'] = 'Passenger Cars'
    base['familia_combustible_candidata'] = base.codigo_energia.map(lambda c:familias[c][0])
    base['tratamiento'] = base.codigo_energia.map(lambda c:familias[c][1])
    base['segmento_candidato'] = base.codigo_energia.map(lambda c:
        'Small (A–B), Medium (C), Large (D–F): alternativas por contrastar, sin pesos'
        if familias[c][0] is not None else None)
    base['campos_pendientes_cli'] = 'Verificar clave exacta, segmento y Euro si aplica; definir velocidad/vía, frío/clima, actividad y acumulado compatibles'
    base['euro_candidato'] = None
    base['masa_t_candidata'] = np.nan
    base['peso_actividad_elegido'] = np.nan
    base['anio_base'] = anio_base; base['anio_objetivo'] = anio_objetivo
    base['fuente'] = 'F055 — ISTAC/DGT, parque fiscal de Tenerife; F061 — COPERT/JRC'
    base['estado'] = 'Propuesta de familia; tamaño/Euro/pesos por actividad y clave CLI pendientes'
    base['clave_completa_cli_verificada'] = False
    base['aplicada_al_balance'] = False
    return base

def proponer_guaguas(evidencia, vehiculo_piloto):
    """Separar control probado, requisitos documentados y categorías por proponer."""
    from movilidad_teide.vehiculos.copert_cli_tipos import VEHICLE
    if (evidencia.get('expediente')!='T-SU 70.20/9.2026'
            or not evidencia.get('registros') or tuple(vehiculo_piloto)!=VEHICLE):
        raise ErrorFlota('Falta la evidencia documental o la categoría acreditada del piloto.')
    fichas = [
        ('control_piloto','Control técnico del piloto','Buses',vehiculo_piloto[1],vehiculo_piloto[2],vehiculo_piloto[3],
         'F037/F039 — proyecto, exportaciones y reproducción CLI',
         'Clave del caso probado; no representa por sí sola las guaguas operativas ni la nueva flota',True),
        ('nuevas_acceso','Nuevas guaguas de acceso','Buses','Diésel; solución ECO pendiente',
         'Interurbano rígido clase II, dos ejes, 12,5–13,28 m; segmento COPERT exacto pendiente',None,
         'F062 — TITSA, pliego técnico T-SU 70.20/9.2026, pp.2–4',
         'Revisar compatibilidad de Coaches/Urban Buses y posible hibridación según ficha; el pliego no fija masa, tecnología ECO ni Euro VI D/E',False),
        ('titsa_actual','Guaguas actuales de TITSA','Buses',None,None,None,
         'H032 — oferta constante; ficha de vehículos por servicio pendiente',
         'Proponer categoría según vehículo real; horarios constantes no identifican masa/combustible/Euro',False),
        ('excursiones','Guaguas de excursiones privadas','Buses',None,'Coaches: familia candidata, masa pendiente',None,
         'Catálogo de cadenas de movilidad; propuesta técnica, sin inventario de flota',
         'Usar familia de autocar como propuesta; no identificar todas las guaguas del aforo como excursiones',False),
        ('interior','Servicio interior del Parque','Buses',None,None,None,
         'Visor/H041 y F062 — ámbito posible del renting, sin asignación operativa acreditada',
         'Definir vehículo, tecnología y ciclo propios; no adoptar por defecto la guagua piloto ni las 30 unidades',False),
    ]
    filas=[]
    for ident,nombre,categoria,fuel,segmento,euro,fuente,tratamiento,probado in fichas:
        filas.append(dict(id_vehiculo=ident,grupo_servicio=nombre,vehiculo_propuesto=nombre,
            categoria_copert_candidata=categoria,familia_combustible_candidata=fuel,
            segmento_candidato=segmento,euro_candidato=euro,masa_t_candidata=np.nan,
            campos_pendientes_cli=('Caso congelado; cualquier cambio requiere otra configuración' if probado else 'Verificar combustible/ECO, segmento/masa y Euro; definir velocidad/vía/carga/pendiente, frío y actividad'),
            peso_actividad_elegido=np.nan,cuota_stock_base=np.nan,
            cuota_stock_objetivo_constante=np.nan,cuota_stock_objetivo_tendencia=np.nan,
            fuente=fuente,tratamiento=tratamiento,
            estado='Control técnico acreditado; sin adopción operativa' if probado else 'Propuesta o requisito documental; categoría completa pendiente',
            clave_completa_cli_verificada=probado,aplicada_al_balance=False))
    return pd.DataFrame(filas)

def acotar_cruce_marginal(energia, distintivo, anio, *, ambito):
    """Acotar intersecciones de dos tablas del mismo universo sin inventar su cruce.

    Para cantidades A, B y total N, max(0,A+B-N) <= cruce <= min(A,B).
    Son límites algebraicos de cada celda por separado, no estimaciones,
    intervalos estadísticos ni una matriz cuyos extremos puedan sumarse.
    El llamante debe acreditar el mismo territorio, tipo y año en ambas fuentes.
    """
    if not isinstance(ambito, str) or not ambito.strip():
        raise ErrorFlota('Explicitar el universo común de ambas tablas.')
    grupos = []
    for tabla in [energia, distintivo]:
        if not {'anio','codigo','categoria','vehiculos','total_ambito'} <= set(tabla):
            raise ErrorFlota('Faltan los campos de las composiciones marginales.')
        base = tabla.loc[tabla.anio.eq(anio)].copy()
        if base.empty or base.codigo.isna().any() or base.codigo.duplicated().any():
            raise ErrorFlota('Cada marginal necesita clases únicas y completas del año elegido.')
        if base.codigo.isin(['_T','ALT']).any():
            raise ErrorFlota('Excluir totales y subtotales antes de acotar el cruce.')
        datos = base[['vehiculos','total_ambito']].to_numpy(dtype=float)
        if (not np.isfinite(datos).all() or (datos < 0).any() or (datos % 1 != 0).any()
                or base.total_ambito.nunique()!=1 or base.total_ambito.iloc[0]<=0
                or base.vehiculos.sum()!=base.total_ambito.iloc[0]):
            raise ErrorFlota('Cada marginal debe conservar un total positivo de vehículos enteros.')
        grupos.append(base)
    a,b = grupos
    total = int(a.total_ambito.iloc[0])
    if total != int(b.total_ambito.iloc[0]):
        raise ErrorFlota('Las marginales no comparten el total; no se fuerza la conciliación.')
    filas=[]
    for combustible in a.itertuples(index=False):
        for etiqueta in b.itertuples(index=False):
            inferior=max(0,int(combustible.vehiculos+etiqueta.vehiculos-total))
            superior=min(int(combustible.vehiculos),int(etiqueta.vehiculos))
            filas.append(dict(anio=anio,ambito=ambito,codigo_energia=combustible.codigo,
                energia=combustible.categoria,codigo_distintivo=etiqueta.codigo,
                distintivo=etiqueta.categoria,total_ambito=total,
                vehiculos_energia=int(combustible.vehiculos),vehiculos_distintivo=int(etiqueta.vehiculos),
                vehiculos_min=inferior,vehiculos_max=superior,
                cuota_parque_min=inferior/total,cuota_parque_max=superior/total,
                cuota_dentro_energia_min=inferior/combustible.vehiculos if combustible.vehiculos else np.nan,
                cuota_dentro_energia_max=superior/combustible.vehiculos if combustible.vehiculos else np.nan,
                cruce_observado=False,aplicado_al_balance=False,
                interpretacion='Límite por celda usando solo marginales; sin restricciones tecnológicas ni Euro asignado. No sumar extremos.'))
    return pd.DataFrame(filas)
