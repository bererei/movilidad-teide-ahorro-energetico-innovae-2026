"""Fichas de lectura y trazabilidad del informe, vinculadas al recorrido vigente."""
from pathlib import Path
import ast
import json
import pandas as pd

from .formato import tex
from .diccionario import _definiciones


FICHAS = [
    dict(id='demanda', titulo='Demanda, aforos y proyección',
         lecturas=[('actividad_corredor_norte', '3. Proyección de personas por colectivo, corredor y sentido'),
                   ('integracion_aforos_teide', '4. Reparto condicionado con las ocupaciones del estudio')],
         codigo=['demanda/actividad.py', 'fuentes/aforos.py'],
         funciones=['proyectar_personas_desde_referencia', 'estimar_reparto_personas_aforos'],
         entradas=['data/silver/actividad/corredor_norte/proyeccion_personas_2028.csv',
                   'data/silver/aforos_teide/reparto_personas_aforos_conjunto.csv'],
         salidas=['proyeccion_fuente.csv', 'cobertura_colectivos.csv'],
         explicacion='Esta ficha permite revisar la proyección común a 2028 y el reparto modal condicionado. El cuaderno reconstruye la proyección; los aforos y las matrices conservados aportan la referencia y sus límites.'),
    dict(id='titsa', titulo='Pasajeros publicados de TITSA',
         lecturas=[('asignacion_demanda_teide', '5. Pasajeros TITSA como evidencia de contraste'),
                   ('descarga_datos_tenerife', '2. Captura mensual de pasajeros TITSA y sus metadatos')],
         codigo=['demanda/titsa.py', 'fuentes/tenerife.py'],
         funciones=['leer_demanda_publica_titsa', 'clasificar_pasajeros_titsa'],
         entradas=['data/silver/demanda/asignacion/pasajeros_titsa_resumen.csv',
                   'data/bronze/transporte_publico/pasajeros_titsa/2025/20261022T171917Z_f6db4cae/metadatos.json'],
         salidas=[], explicacion='La captura, su cobertura y la interpretación de pasajeros se comprueban como evidencia del transporte existente; no añaden otra demanda ni otra energía a las visitas ya representadas.'),
    dict(id='recorridos', titulo='Orígenes, recorridos y perfiles',
         lecturas=[('recorridos_operativos_teide', '3. Directos y alimentadores por origen y sentido'),
                   ('asignacion_demanda_teide', '4. Cobertura de perfiles propios, aproximaciones y ausencias')],
         codigo=['cartografia/extraccion.py', 'cartografia/perfiles.py', 'demanda/representacion.py'],
         funciones=['extract_configured_itinerary', 'sample_elevation_profile', 'integrar_representacion_estudio'],
         entradas=['config/itinerarios.json', 'data/silver/demanda/asignacion/recorridos_referencia_calculo.csv'],
         salidas=['origenes_itinerarios.csv', 'red_recorridos.csv', 'pendientes_recorridos.csv', 'puntos_servicio_interior.csv'],
         explicacion='La representación territorial relaciona orígenes, geometrías y perfiles conservados. Los cuadernos muestran su cobertura y sus límites; la reconstrucción energética utiliza esas entradas verificadas sin volver a adquirir cartografía.'),
    dict(id='comunes', titulo='Servicios colectivos existentes',
         lecturas=[('consumo_energetico_copert', '7. Condiciones y límites del resultado')],
         codigo=['energia/componentes_pendientes.py', 'informe/escenarios.py'],
         funciones=['estimar_guaguas_comunes'],
         entradas=['data/silver/energia_turismos/20261030_balance_con_comunes/guaguas_comunes_detalle.csv'],
         salidas=['energia_por_componente.csv', 'componentes_representados.csv'],
         explicacion='El consumo conjunto de TITSA y excursiones procede de la estimación conservada. Su función productora y el detalle por colectivo y sentido permiten consultar esta estimación. La reproducción vigente conserva ese bloque y comprueba su conciliación; no mide combustible por línea ni lo vuelve a sumar.'),
    dict(id='operacion', titulo='Reservas, flota y consumo de lanzaderas',
         lecturas=[('consumo_energetico_copert', '5. Comprobación de las observaciones y del p85'),
                   ('consumo_energetico_copert', 'Reconstrucción de los cálculos y comparación')],
         codigo=['flujos/modulacion.py', 'flujos/inventario.py', 'operacion/inventario.py', 'energia/valoracion_operacion.py'],
         funciones=['calcular_modulacion', 'calcular_inventario', 'asignar_inventario', 'valorar_movimientos'],
         entradas=['data/silver/energia_turismos/20261101_flota_30_tres_sustitutas/movimientos_con_identidad_fisica.parquet'],
         salidas=['energia_lanzaderas_servicio.csv', 'expediciones_casos.csv', 'reservas_casos.csv', 'comprobacion_operacion.csv'],
         explicacion='La reconstrucción adapta expediciones a las cadenas de visita y asigna viajes a las treinta guaguas físicas. Comprueba plazas por tramo, identidad de vehículos y devolución del inventario a cada base, y calcula el consumo de viajes comerciales y recorridos en vacío. El diseño p85 se comprueba aparte de los nueve perfiles anuales y no se anualiza.'),
    dict(id='turismos', titulo='Parque, consumo y pendiente de turismos',
         lecturas=[('flota_vehiculos_teide', '3. Perfiles utilizados para ponderar el consumo'),
                   ('consumo_energetico_copert', '6. Actividad conservada por origen y colectivo'),
                   ('consumo_energetico_copert', 'Reconstrucción de los cálculos y comparación')],
         codigo=['flujos/pendiente.py', 'energia/pendiente.py', 'energia/fisica_turismos.py', 'energia/mezcla.py'],
         funciones=['calcular_pendiente', 'energia_pendiente_por_recorrido', 'aplicar_correcciones_a_actividad'],
         entradas=['data/silver/vehiculos/flota_teide/micro_cruce_turismos_2025.csv',
                   'data/silver/vehiculos/ponderacion/pesos_curvas.csv',
                   'data/silver/vehiculos/ponderacion/sustituciones.csv',
                   'data/silver/energia/turismos/visita_interior/recorridos_interiores.csv',
                   'data/silver/energia/referencias_unitarias/pendiente_turismos/correccion_por_origen_y_rama.csv'],
         salidas=['energia_por_componente.csv', 'contribucion_pendiente.csv', 'cobertura_colectivos.csv'],
         explicacion='El cuaderno de flota explica la composición y cobertura DGT; pesos_curvas.csv identifica las curvas COPERT ponderadas y sustituciones.csv los consumos estimados para registros incompletos, sin completar sus atributos originales. La reconstrucción obtiene masas y correcciones por recorrido, curva y rama sin/con. Los pesos y el consumo base de las demás tecnologías se mantienen; su cambio por pendiente sigue sin estimar. A y B conservan todos los colectivos.'),
    dict(id='balance', titulo='Balance central y sensibilidad',
         lecturas=[('consumo_energetico_copert', '2. Resultado central de ambos escenarios'),
                   ('consumo_energetico_copert', '3. Sensibilidad externa FTA'),
                   ('consumo_energetico_copert', 'Reconstrucción de los cálculos y comparación')],
         codigo=['flujos/estudio.py', 'flujos/seleccion.py', 'energia/seleccion.py', 'informe/cierre.py'],
         funciones=['reproducir_estudio', 'calcular_seleccion', 'armonizar_resultados', 'balance_perturbado'],
         entradas=['data/silver/energia_turismos/20261101_hot_central_fta_sensibilidad/resultado_central.csv',
                   'data/silver/energia_turismos/20261101_hot_central_fta_sensibilidad/balance_vigente.csv'],
         salidas=['resultado_central.csv', 'sensibilidad_fta.csv', 'puente_ahorro.csv', 'umbrales_central.csv', 'sensibilidad_conjunta_cierre.csv', 'umbrales_demanda_cierre.csv'],
         explicacion='La reproducción compara las cuatro etapas reconstruidas con sus referencias antes de continuar. Conserva las 120 combinaciones, selecciona el resultado central según el Excel y presenta por separado el contraste FTA de consumo de lanzaderas. Las pruebas conjuntas muestran el porcentaje aplicado a cada bloque y el ahorro A/B sin reemplazar el central; los umbrales de demanda no simulan otra oferta. La igualdad de tablas no acredita calibración del consumo o aprobación de la explotación.'),
    dict(id='documento', titulo='Preparación de este informe',
         lecturas=[('consumo_energetico_copert', 'Preparación del informe')],
         codigo=['informe/generacion.py', 'informe/guia.py'],
         funciones=['generar_recursos', 'compilar_pdf'],
         entradas=['docs/informe_energetico/main.tex', 'config/parametros_modelo.xlsx'],
         salidas=['guia_calculos.csv', 'trazabilidad_metodo.csv', 'diccionario_anexos.csv'],
         explicacion='La entrada scripts/generar_informe.py prepara los recursos desde las salidas verificadas y compila una copia. El informe mantiene un único maestro LaTeX. Los archivos de revisión conservan versión, fuentes y huellas; los anexos no son otro punto de edición de hipótesis.'),
]


def comprobar_fichas(root):
    """Compruebo archivos, funciones y títulos reales antes de exportar la guía."""
    root = Path(root)
    for ficha in FICHAS:
        funciones = set()
        for ruta in ficha['codigo']:
            p = root / 'src/movilidad_teide' / ruta
            funciones.update(n.name for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        if not set(ficha['funciones']) <= funciones:
            raise ValueError(f'Función ausente en la ficha {ficha["id"]}: {set(ficha["funciones"])-funciones}')
        for nombre, apartado in ficha['lecturas']:
            nb = json.loads((root / 'notebooks' / f'{nombre}.ipynb').read_text())
            titulos = {line.lstrip('# ').strip() for celda in nb['cells'] if celda['cell_type'] == 'markdown'
                       for line in ''.join(celda['source']).splitlines() if line.startswith('#')}
            if apartado not in titulos:
                raise ValueError(f'Apartado ausente: {nombre}: {apartado}')
        for ruta in ficha['entradas']:
            if not (root / ruta).is_file():
                raise FileNotFoundError(ruta)


def actualizar_guia(root, destino):
    comprobar_fichas(root)
    destino = Path(destino)
    for ficha in FICHAS:
        for anexo in ficha['salidas']:
            if anexo in {'guia_calculos.csv', 'diccionario_anexos.csv'}:
                continue  # Los genero a continuación en esta misma etapa.
            if not (destino / 'anexos' / anexo).is_file():
                raise FileNotFoundError(f'Anexo ausente en {ficha["id"]}: {anexo}')
    _tablas_referencia(root, destino)
    filas, bloques = [], []
    for f in FICHAS:
        cuadernos = list(dict.fromkeys('notebooks/' + n + '.ipynb' for n, _ in f['lecturas']))
        codigo = ['src/movilidad_teide/' + c for c in f['codigo']]
        if f['id'] == 'documento': codigo.insert(0, 'scripts/generar_informe.py')
        filas.append(dict(ficha_calculo=f['id'], etapa=f['titulo'], cuadernos_ejecucion='; '.join(cuadernos),
                          apartados_cuaderno='; '.join(a for _, a in f['lecturas']), codigo_calculo='; '.join(codigo),
                          entrada_calculo='; '.join(f['entradas']), salida_revision='; '.join(f['salidas']) or 'Evidencia de contraste; sin energía adicional'))
        bloques += [r'\Needspace{75mm}\begin{samepage}', r'\subsection{' + tex(f['titulo']) + r'}\label{calc:' + f['id'] + '}', tex(f['explicacion'])]
        for nombre, apartado in f['lecturas']:
            bloques.append(r'\Fuente{Lectura: \Archivo{' + tex(nombre + '.ipynb') + '}, «' + tex(apartado) + '».}')
        bloques.append(r'\Fuente{Código: ' + ', '.join(r'\Ruta{' + c + '}' for c in f['codigo']) + '.}')
        bloques.append(r'\Fuente{Funciones: ' + ', '.join(r'\Archivo{' + tex(n) + '}' for n in f['funciones']) + '.}')
        bloques += [r'\Fuente{Entrada o referencia: \Ruta{' + e + '}.}' for e in f['entradas']]
        if f['salidas']:
            bloques.append(r'\Fuente{Anexos: ' + '; '.join(r'\Ruta{' + n + '}' for n in f['salidas']) + '.}')
        bloques.append(r'\end{samepage}\par')
    pd.DataFrame(filas).to_csv(destino / 'anexos/guia_calculos.csv', sep=';', index=False, encoding='utf-8-sig')
    (destino / 'tablas/guia_calculos.tex').write_text('\n'.join(bloques) + '\n')
    p = destino / 'anexos/trazabilidad_metodo.csv'
    traza = pd.read_csv(p, sep=';')
    cambios = {
        'Consumo de vehículos': 'src/movilidad_teide/vehiculos/copert_factores.py; src/movilidad_teide/energia/balance.py; data/silver/copert/',
        'Pendiente de turismos': 'src/movilidad_teide/flujos/pendiente.py; src/movilidad_teide/energia/pendiente.py; data/silver/energia/referencias_unitarias/pendiente_turismos/',
        'Preparación del informe': 'scripts/generar_informe.py; src/movilidad_teide/informe/generacion.py; src/movilidad_teide/informe/guia.py',
    }
    for etapa, ruta in cambios.items(): traza.loc[traza.etapa.eq(etapa), 'entrada_en_repositorio'] = ruta
    traza.to_csv(p, sep=';', index=False, encoding='utf-8-sig')
    definiciones = _definiciones()
    diccionario = []
    for archivo in sorted((destino / 'anexos').glob('*.csv')):
        if archivo.stem == 'diccionario_anexos': continue
        for campo in pd.read_csv(archivo, sep=';', nrows=0).columns:
            unidad, significado = definiciones[campo]
            diccionario.append(dict(archivo=archivo.name, campo=campo, unidad_o_lectura=unidad, aclaracion=significado))
    pd.DataFrame(diccionario).to_csv(destino / 'anexos/diccionario_anexos.csv', sep=';', index=False, encoding='utf-8-sig')


def _tablas_referencia(root, destino):
    """Presento las referencias elegidas sin modificar las tablas de cálculo."""
    from .formato import numero
    from movilidad_teide.configuracion.lectura import leer_parametros
    root, destino = Path(root), Path(destino)
    folder = root / 'data/silver/vehiculos/ponderacion'
    cobertura = pd.read_csv(folder / 'cobertura_identificacion.csv', sep=';')
    factores = pd.read_csv(folder / 'factores.csv', sep=';')
    v = {p['id']: p['valor_utilizado'] for p in leer_parametros(root)['parametros']}
    servicios = [('Particular sin especificar (B00)', 'Particular'), ('Alquiler sin conductor (A01)', 'Alquiler')]
    def tabla(nombre, caption, columnas, filas, nota):
        body = [r'\begin{table}[H]\caption{' + caption + r'}\label{tab:' + nombre + r'}', r'\centering{\fontsize{10}{13}\selectfont\begin{tabularx}{\linewidth}{@{}' + columnas + r'@{}}']
        for i, fila in enumerate(filas):
            if i == 0: body.append(r'\rowcolor{azul}' + ' & '.join(r'\Blanco{' + tex(x) + '}' for x in fila) + r'\\')
            else: body.append((r'\rowcolor{fondo_azul}' if i % 2 else '') + ' & '.join(tex(x) for x in fila) + r'\\')
        body += [r'\bottomrule\end{tabularx}}\Fuente{' + nota + r'}\end{table}']
        (destino / 'tablas' / (nombre + '.tex')).write_text('\n'.join(body) + '\n')
    composicion = pd.read_csv(root / 'data/silver/vehiculos/flota_teide/perfil_combustible_euro_por_servicio_2025.csv', sep=';', keep_default_na=False)
    grupos = [('Petrol','Gasolina'),('Diesel','Diésel'),('Petrol Hybrid','Híbrido de gasolina'),('Petrol PHEV','Híbrido enchufable de gasolina'),('Diesel PHEV','Híbrido enchufable diésel'),('Battery electric','Eléctrico de batería'),('LPG Bifuel','Bifuel gasolina/GLP'),('CNG Bifuel','Bifuel gasolina/GNC'),('','Tecnología sin correspondencia revisada')]
    filas = [('Familia técnica de consumo', 'Particular', 'Alquiler')]
    for familia, nombre in grupos:
        filas.append((nombre, *[numero(composicion.loc[composicion.grupo_servicio.eq(key)&composicion.familia_copert.eq(familia),'vehiculos'].sum(),0) for key,_ in servicios]))
    filas.append(('Total de registros', *[numero(composicion.loc[composicion.grupo_servicio.eq(key),'vehiculos'].sum(),0) for key,_ in servicios]))
    tabla('composicion_parques', 'Composición por familia técnica de los parques DGT 2025 (vehículos registrados)', 'Xrr', filas,
          'Fuente: perfil\\_combustible\\_euro\\_por\\_servicio\\_2025.csv. Agrupación por familia COPERT, conservando los registros sin correspondencia revisada. Son parques registrados de referencia, no cantidades de coches visitantes. El archivo completo conserva las normas Euro y el estado de identificación.')
    filas = [('Servicio', 'Registros', 'Tamaño y norma identificados', 'Proporción')]
    for key, nombre in servicios:
        r = cobertura.loc[cobertura.grupo_servicio.eq(key)].iloc[0]
        filas.append((nombre, numero(r.vehiculos_stock, 0), numero(r.vehiculos_con_tamano_y_norma_identificados, 0), numero(100*r.fraccion_identificada) + ' %'))
    tabla('parque_copert', 'Identificación de tamaño y norma en los parques de referencia DGT 2025', 'Xrrr', filas,
          r'Fuente: cobertura\_identificacion.csv. La proporción mide identificación conjunta de tamaño y norma, no cobertura de factores ni de energía. Los demás registros permanecen en la mezcla mediante los criterios documentados de comparables y sustitución; no se les asigna consumo cero.')
    filas = [('Clase de vía / entorno COPERT', 'km/h', 'Particular', 'Alquiler')]
    for road, mode, label in [('local','urban_off_peak','Local / urbano fuera de punta'),('convencional','rural','Convencional / rural'),('rapida','highway','Rápida / autopista')]:
        speed = v['velocidad_turismo_'+road];values=[]
        for key, _ in servicios:
            r = factores.loc[factores.grupo_servicio.eq(key)&factores.modo.eq(mode)&factores.velocidad_kmh.eq(speed)].iloc[0]
            assert abs(r.aporte_conjunto_condicionado_min_mj_km-r.aporte_conjunto_condicionado_max_mj_km)<1e-12
            values.append(numero(r.aporte_conjunto_condicionado_min_mj_km,4))
        filas.append((label,numero(speed,0),*values))
    tabla('factores_turismos', 'Factores Hot ponderados antes del ajuste de pendiente (MJ/km)', 'Xrrr', filas,
          'Fuente: factores.csv de la referencia ponderada y velocidades del caso Central. Los factores incluyen el consumo estimado por sustitución. Son referencias de modelización; las velocidades no son mediciones ni límites legales. La corrección de pendiente se aplica después por grupo y segmento (sección~\\ref{sec:consumo}).')
    patrones=pd.read_csv(root/'data/silver/energia/turismos/visita_interior/recorridos_interiores.csv',sep=';')
    filas=[('Entrada al Parque','Zona próxima representada','Ida y regreso (km)')]
    for entrada, nombre in [('Boca Tauce','Parador / Cañada Blanca / Roques'),('El Portillo','Acceso al Teleférico')]:
        r=patrones.loc[patrones.patron_id.eq('zona_proxima')&patrones.terminal_calculo.eq(entrada)].iloc[0]
        filas.append((entrada,nombre,numero(r.longitud_interior_ida_vuelta_km)))
    tabla('visita_proxima', 'Recorrido interior de referencia de los coches', 'XXr', filas,
          r'Fuente: recorridos\_interiores.csv, patrón zona\_proxima. Distancias de carretera de ida y regreso a la misma entrada, sin sumar patrones alternativos. No son destinos o frecuencias observados ni recorridos del eje completo.')
