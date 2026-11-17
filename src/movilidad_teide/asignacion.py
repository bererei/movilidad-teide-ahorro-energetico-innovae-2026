"""Interfaz compatible; las responsabilidades se organizan en demanda."""

from movilidad_teide.demanda.asignacion import _valores, agrupar_origenes, catalogo_cadenas_movilidad, conciliar_aforos_anuales, construir_asignacion, contexto_od_por_origen, contrastar_corredores, contrastar_totales, demanda_por_corredor, demanda_por_origen, reconstruir_cabeceras, resolver_puntos_cabecera, resumir_discrepancia_repartos

from movilidad_teide.demanda.asignacion_tipos import ErrorAsignacion, PENDIENTE, SEGMENTOS, SENTIDOS

from movilidad_teide.demanda.origenes import agrupar_origenes_para_recorridos, cerrar_revision_geografica, diagnosticar_reutilizacion_trazados, resumir_revision_trazados, revisar_cabeceras_de_estudio, revisar_representatividad_geografica, seleccionar_origenes_representativos

from movilidad_teide.demanda.representacion import integrar_representacion_estudio, normalizar_recorridos_estudio, preparar_aproximaciones_geograficas

from movilidad_teide.demanda.titsa import clasificar_pasajeros_titsa, cribar_conexiones_titsa, leer_demanda_publica_titsa, referencias_velocidad_gtfs, resumir_pasajeros_titsa, ubicar_paradas_titsa

__all__ = ['ErrorAsignacion', 'PENDIENTE', 'SEGMENTOS', 'SENTIDOS', 'agrupar_origenes', 'agrupar_origenes_para_recorridos', 'catalogo_cadenas_movilidad', 'cerrar_revision_geografica', 'clasificar_pasajeros_titsa', 'conciliar_aforos_anuales', 'construir_asignacion', 'contexto_od_por_origen', 'contrastar_corredores', 'contrastar_totales', 'cribar_conexiones_titsa', 'demanda_por_corredor', 'demanda_por_origen', 'diagnosticar_reutilizacion_trazados', 'integrar_representacion_estudio', 'leer_demanda_publica_titsa', 'normalizar_recorridos_estudio', 'preparar_aproximaciones_geograficas', 'reconstruir_cabeceras', 'referencias_velocidad_gtfs', 'resolver_puntos_cabecera', 'resumir_discrepancia_repartos', 'resumir_pasajeros_titsa', 'resumir_revision_trazados', 'revisar_cabeceras_de_estudio', 'revisar_representatividad_geografica', 'seleccionar_origenes_representativos', 'ubicar_paradas_titsa']
