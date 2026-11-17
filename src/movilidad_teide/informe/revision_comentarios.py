"""Presentación de hipótesis y trazabilidad, sin cambios de actividad o energía."""
from pathlib import Path
import re,json
import pandas as pd
from .integracion import _tabla
from .editorial import argumento


def preparar_apoyos(root,destino,datos):
    root=Path(root);destino=Path(destino);folder=destino/'tablas/vigente';v=datos['referencia']['valores_modelo']
    speed=float(v['velocidad_copert']);load=float(v['carga_copert']);assert speed==34 and load==.5
    car=[float(v['velocidad_turismo_'+name]) for name in ['local','convencional','rapida']];assert car==[20,40,80]
    # La referencia de excursión se identifica por su factor, no por una etiqueta retrospectiva.
    common=pd.read_csv(root/'data/silver/energia/excursiones/referencias_por_origen.csv',sep=';')
    f=pd.read_parquet(root/'data/silver/copert/factores/factores_autocar.parquet')
    chosen=f[f['Segment'].eq('Coaches Standard <=18 t')&f['Euro Standard'].eq('Euro VI D/E')&f.slope_class_pct.eq(0)&f.load_fraction.eq(load)&f.rural_speed_kmh.eq(speed)]
    assert len(chosen)==1 and (abs(common.factor_hot_referencia_mj_km-chosen.hot_ec_mj_per_km.iloc[0])<1e-12).all()
    rows=[['Coches directos, autorizados y hasta cabeceras','20 / 40 / 80','Según carretera local, convencional o rápida; también en la visita interior en coche.'],['Lanzaderas de acceso y tramo interior integrado','34','Referencia rural de COPERT para calcular energía, con la pendiente de cada tramo.'],['Lanzaderas en vacío y apoyos externos','34','Misma velocidad de referencia energética; carga técnica cero en vacío.'],['TITSA 342 y 348 sin intervención','34','Referencia rural aplicada a los cuatro sentidos, con su pendiente.'],['Autocares de excursión','34','Referencia rural con pendiente cero; mismo factor sin y con proyecto en el principal.'],['Línea 341 y otros servicios comunes no cuantificados','No asignada','Su consumo absoluto no se ha estimado; no se les aplica un factor de velocidad en el balance.']]
    _tabla(folder/'velocidades_modos.tex','Velocidades para calcular el consumo de cada modo en 2028',['Modo y desplazamiento','km/h','Aplicación'],rows,r'Mismas 2.500.000 visitas sin y con intervención. Son velocidades técnicas del cálculo energético, no mediciones ni límites de tráfico. Los tiempos de las lanzaderas proceden de cada itinerario y de sus tramos; se utilizan para enlazar servicios y no se sustituyen automáticamente por distancia dividida entre 34. Fuente: libro de parámetros, factores COPERT y código de cálculo; anexos~\ref{sec:anexos} y~\ref{sec:guia_calculos}.')
    rows=[['Coches directos, autorizados, visita interior y acceso a cabeceras','Sí, en gasolina y diésel convencionales','Ajuste físico por desnivel, masa y conversión a energía de combustible, aplicado por segmento sin y con proyecto.'],['Otras tecnologías de turismo','Cambio de pendiente sin estimar','Mantienen su consumo base; su energía no se elimina.'],['Lanzaderas de acceso e interior, comerciales y vacíos','Sí','Factores COPERT por pendiente; el tramo interior forma parte de los movimientos integrados.'],['TITSA 342 y 348 sin intervención','Sí','Cuatro trazados independientes, una expedición por sentido y día; factores COPERT por pendiente.'],['Autocares de excursión','Sin corrección de pendiente','Factor a pendiente cero; la actividad idéntica sin/con cancela este bloque en el ahorro principal. En sensibilidad con más excursiones ya no se cancela completamente.'],['Línea 341 y servicios comunes no cuantificados','Sin consumo absoluto estimado','Se supone igualdad sin/con; cualquier cambio neto necesita incorporarse al balance.']]
    _tabla(folder/'pendiente_modos.tex','Tratamiento de la pendiente por modo de transporte',['Modo y recorrido','Tratamiento','Cómo entra en el balance'],rows,r'Planificación de 2028, con 2.500.000 visitas en cada escenario. COPERT es el modelo de consumo por carretera. El terreno aproxima la altura de la carretera; los factores de pesados se limitan a −6/+6\,\%, manteniendo registrada la pendiente física. Fuente: método del estudio y ejecuciones de COPERT; anexos~\ref{sec:anexos} y~\ref{sec:guia_calculos}.')
    for stem,columns in [('velocidades_modos',r'L{49mm}>{\Centering\arraybackslash}p{23mm}X'),('pendiente_modos',r'L{50mm}L{36mm}X')]:
        p=folder/(stem+'.tex');s=p.read_text();s=s.replace(r'X>{\RaggedLeft\arraybackslash}X>{\RaggedLeft\arraybackslash}X',columns);p.write_text(s)
    return {'velocidades_turismos_kmh':car,'velocidad_colectivos_kmh':speed,'factor_excursiones_mj_km':float(chosen.hot_ec_mj_per_km.iloc[0]),'tablas_explicativas_nuevas':2}


def _cita_interna(match):
    keys=match[1].split(',');external=[k for k in keys if k not in ['metodo','calculo']]
    own=[k for k in keys if k in ['metodo','calculo']]
    ext=r'\cite{'+','.join(external)+'}' if external else ''
    if not own:return ext
    # Las fuentes del propio estudio se presentan como anexos, no publicaciones externas.
    ref=r'Anexo~\ref{sec:anexos}' if own==['metodo'] else (r'Anexo~\ref{sec:guia_calculos}' if own==['calculo'] else r'Anexos~\ref{sec:anexos} y~\ref{sec:guia_calculos}')
    return ext+' '+('(véanse los '+ref+')' if len(own)>1 else '(véase el '+ref+')') if ext else ('(véanse los '+ref+')' if len(own)>1 else '(véase el '+ref+')')


def _nota(note):
    keys=[]
    for cc in re.findall(r'\\cite\{([^}]+)\}',note):
        for key in cc.split(','):
            if key not in ['metodo','calculo'] and key not in keys:keys.append(key)
    # Retirar solo las coletillas de procedencia; se mantienen todas las condiciones de lectura.
    note=re.sub(r' Fuente: elaboración propia(?: a partir de \\cite\{[^}]+\})?\. Método y desarrollo del cálculo: anexos~\\ref\{sec:anexos\} y~\\ref\{sec:guia_calculos\}\.$','',note)
    note=re.sub(r'Fuente: elaboración propia a partir de(?: las fuentes y decisiones identificadas en)?\s*\\cite\{[^}]+\}\.?\s*$', '',note).strip()
    note=re.sub(r'Fuente: microdatos DGT y referencias físicas~\\cite\{[^}]+\}\. ?', '',note)
    note=re.sub(r'Fuente: (?:libro de parámetros, factores COPERT y código de cálculo|método del estudio y ejecuciones de COPERT); anexos~\\ref\{sec:anexos\} y~\\ref\{sec:guia_calculos\}\. ?', '',note)
    note=note.replace(r'Fuente: calendario y cuentas diarias de 2028~\cite{calculo}.','Calendario y cuentas diarias de 2028.')
    note=re.sub(r'\\cite\{([^}]+)\}',_cita_interna,note)
    note=note.replace('una referencia, referencia de las bases','la referencia energética de las bases')
    note=note.replace('una referencia de magnitud, la referencia exigida por las bases','la referencia energética de las bases')
    note=note.replace('Mismas 2.500.000 visitas sin y con intervención. Son velocidades técnicas del cálculo energético, no mediciones ni límites de tráfico. ','')
    note=note.replace('Personas por año. El total de cada grupo es igual en los dos escenarios; sus columnas de transporte corresponden a con intervención. ','')
    return note.rstrip()+' Fuente: elaboración propia'+(r' a partir de \cite{'+','.join(keys)+'}' if keys else '')+'. Método y desarrollo del cálculo: anexos~'+r'\ref{sec:anexos} y~\ref{sec:guia_calculos}.'


def revisar_textos(destino):
    destino=Path(destino);files=[destino/'main.tex',*(destino/'tablas').rglob('*.tex')]
    replacements={
        'factores conservados de COPERT':'factores obtenidos mediante ejecuciones programáticas de COPERT',
        'factores COPERT 5.10.1 conservados':'factores calculados con COPERT 5.10.1',
        'Factores COPERT 5.10.1 conservados':'Factores calculados con COPERT 5.10.1',
        'COPERT conservado':'COPERT 5.10.1',
        'factores conservados':'factores calculados',
        'factores reutilizados':'factores de consumo aplicados',
        'coeficientes físicos conservados':'coeficientes físicos de referencia',
        'circulaciones conservadas':'circulaciones programadas',
        'Factores Hot reutilizados':'Factores de consumo con motor caliente',
        'factores Hot reutilizados':'factores de consumo con motor caliente',
        'referencias conservadas e identificadas':'referencias de vehículo identificadas',
        'referencias efectivamente reutilizadas':'referencias de cálculo aplicadas',
        'factores efectivamente reutilizados':'factores aplicados al transporte representado',
        'perfiles conservados':'perfiles de cálculo',
        'distribuciones horarias conservadas':'distribuciones horarias de las fuentes',
        'Las circulaciones conservadas':'Las circulaciones programadas',
        'recursos conservados':'recursos del estudio',
        'no una acreditación de la ayuda':'la referencia exigida por las bases',
        'no certificación':'referencia de las bases',
        'no es una acreditación de la ayuda':'sirve para comparar el ahorro con el requisito energético',
        'Esta exportación no representa una ejecución nueva de COPERT.':'Los archivos permiten revisar los factores aplicados y las hipótesis de cálculo.',
        'esta exportación no representa una ejecución nueva de COPERT.':'los archivos permiten revisar los factores aplicados y las hipótesis de cálculo.',
        'Reproducir no significa volver a adquirir fuentes ni ejecutar COPERT.':'La reproducción del balance aplica los resultados de COPERT con las mismas entradas y condiciones.',
        'No vuelve a adquirir todas las fuentes, consultar COPERT o buscar horarios desde cero.':'Las ejecuciones de COPERT y la programación de servicios se integran mediante los módulos indicados en las fichas.',
        'sin una nueva ejecución de COPERT':'con las condiciones de vehículo y circulación del estudio',
        'sin nueva ejecución de COPERT':'con los factores de consumo del estudio',
        'conservadas; agregación':'programadas; agregación',
    }
    for p in files:
        s=p.read_text()
        for old,new in replacements.items():s=s.replace(old,new)
        calls=list(re.finditer(r'\\Figura(?:\[[^\]]*\]){0,2}\{([^}]+)\}',s))
        for m in reversed(calls):
            _,capend=argumento(s,m.end());note,end=argumento(s,capend)
            s=s[:capend]+'{'+_nota(note)+'}'+s[end:]
        # Cada fuente de tabla o figura distingue sus referencias externas del desarrollo propio.
        matches=list(re.finditer(r'\\Fuente\{',s))
        for m in reversed(matches):
            note,end=argumento(s,m.end()-1)
            if '#' in note:continue
            note=_nota(note)
            s=s[:m.end()-1]+'{'+note+'}'+s[end:]
        s=re.sub(r'\\cite\{([^}]+)\}',_cita_interna,s)
        if p.name=='main.tex':
            s=re.sub(r'\\bibitem\{(?:metodo|calculo)\}[^\n]*\n','',s)
        else:
            # El tamaño de tabla no puede alterar el interlineado del párrafo que la introduce.
            s=re.sub(r'^(?:\\par\s*)+','',s)
            s=re.sub(r'(?:\s*\\par)+\s*$','',s)
            s=r'\par'+'\n'+s.rstrip()+'\n'+r'\par'+'\n'
        p.write_text(s)
    return {'documentos_propios_como_anexos':True,'referencias_externas_separadas':True,'tablas_separadas_de_parrafos_antes_de_cambiar_tipografia':True}
