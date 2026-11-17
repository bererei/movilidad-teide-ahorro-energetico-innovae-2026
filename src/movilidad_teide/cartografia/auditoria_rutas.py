"""cartografia: auditoria rutas. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import substring
from shapely.strtree import STRtree
from movilidad_teide.cartografia.geografia_tipos import GeographicDataError
from movilidad_teide.cartografia.geometrias import combine_ordered_parts
from movilidad_teide.cartografia.geometrias import ensure_metric_crs
from movilidad_teide.trazabilidad import file_sha256
from movilidad_teide.cartografia.geometrias import route_validation_table
from movilidad_teide.cartografia.itinerarios_tipos import ItineraryExtractionError


def audit_service_trace_geometry(line, lineage, audit, tolerance_m):
    """Cotejar una traza inalterada con sus autocruces revisados, sin simplificarla.

    Los ejes sin esta auditoría siguen requiriendo línea simple. Una traza con
    solapamientos lineales, otra huella o cruces no identificados no se admite.
    """
    component_ok = (len(lineage) == 1 and lineage.component_geometry_sha256.iloc[0] == audit["expected_component_sha256"])
    parts = [LineString([a, b]) for a, b in zip(line.coords[:-1], line.coords[1:])]
    tree = STRtree(parts)
    crossings, non_point = [], False
    for i, part in enumerate(parts):
        for j in tree.query(part, predicate="intersects"):
            if j <= i + 1:
                continue
            intersection = part.intersection(parts[j])
            if not isinstance(intersection, Point):
                non_point = True
            else:
                crossings.append([float(intersection.x), float(intersection.y)])
    expected = [Point(xy) for xy in audit["expected_crossings"]]
    matched = set()
    for xy in crossings:
        matches = [i for i, point in enumerate(expected) if i not in matched and point.distance(Point(xy)) <= tolerance_m]
        if matches:
            matched.add(matches[0])
    passed = bool(component_ok and not non_point and len(crossings) == len(expected) == len(matched))
    return passed, {"component_sha256_matches": bool(component_ok), "crossings": crossings,
                    "non_point_intersection": non_point, "reason": audit["reason"]}


def audit_osm_car_sequence(axis_parts, source_frames):
    """Rechazar sentidos/accesos incompatibles en una secuencia ya elegida.

    No busca caminos ni acredita circulación actual, giros o condiciones locales.
    Las condiciones temporales requieren revisión explícita, nunca se ignoran.
    """
    from movilidad_teide.cartografia.fuentes_rutas import select_exact_records
    rows = []
    for sequence, part in enumerate(axis_parts, start=1):
        record = select_exact_records(source_frames[part["source_id"]], part["feature_filters"]).iloc[0]
        # Pandas representa las etiquetas ausentes como NaN; no son un valor OSM desconocido.
        def tag(key):
            value = record.get(key)
            return None if pd.isna(value) else value
        oneway = tag("oneway") or ("yes" if tag("junction") in {"roundabout", "circular"} else "no")
        reverse = part["reverse"]
        if oneway not in {"yes", "1", "true", "-1", "no", "0", "false"}:
            raise ItineraryExtractionError("Sentido OSM desconocido; requiere revisión.")
        if (oneway in {"yes", "1", "true"} and reverse) or (oneway == "-1" and not reverse):
            raise ItineraryExtractionError("La secuencia contradice un sentido único OSM.")
        access = next((tag(k) for k in ("motorcar", "motor_vehicle", "vehicle", "access") if tag(k)), None)
        if access not in {None, "yes", "permissive", "designated", "destination"}:
            raise ItineraryExtractionError("El acceso OSM necesita revisión para coches.")
        conditions = json.loads(tag("conditional_tags_json") or "{}")
        if any(k.split(":")[0] in {"oneway", "access", "vehicle", "motor_vehicle", "motorcar"} for k in conditions):
            raise ItineraryExtractionError("Hay condiciones temporales OSM que requieren revisión.")
        if record["highway"] not in {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "service", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}:
            raise ItineraryExtractionError("La vía OSM no es una carretera admisible en esta propuesta.")
        rows.append({"sequence": sequence, "source_id": part["source_id"], "osm_way_id": record["osm_way_id"],
                     "name": record.get("name"), "road_ref": record.get("road_ref"), "reverse": reverse,
                     "oneway": oneway, "access": access, "compatible_with_recorded_tags": True})
    return pd.DataFrame(rows)

def partition_itinerary_at_anchor(route, point, tolerance_m, *, osm_grade_context=None):
    """Partir una ruta sin añadir conectores ni perder longitud.

    La primera y segunda parte mantienen el sentido del recorrido original.
    Los autocruces solo se admiten con una auditoría OSM completa repetida sobre
    esta geometría exacta y un anclaje que identifique una sola posición de ruta.
    La separación lateral queda fuera de la circulación calculada.
    """
    if (not isinstance(route, LineString) or route.is_empty or not route.is_valid
            or not isinstance(point, Point) or point.is_empty or not np.isfinite(tolerance_m) or tolerance_m <= 0):
        raise ItineraryExtractionError("La partición requiere una ruta válida, un punto y tolerancia positiva.")
    if not route.is_simple:
        try:
            ctx=osm_grade_context
            numeric=ctx['config']['parameters']['length_tolerance_m']
            valid,_=audit_osm_grade_separated_crossings(route,ctx['lineage'],ctx['itinerary'],
                ctx['config'],ctx['project_root'],numeric)
        except (KeyError,TypeError,AttributeError):
            valid=False
        if not valid:
            raise ItineraryExtractionError('La ruta con autocruces requiere auditoría OSM completa de la geometría exacta.')
        # Un punto situado sobre el propio cruce tiene dos posiciones y no puede ser cabecera.
        positions=[];offset=0.
        for a,b in zip(route.coords[:-1],route.coords[1:]):
            edge=LineString([a,b])
            if edge.distance(point)<=tolerance_m:positions.append(offset+edge.project(point))
            offset+=edge.length
        if positions and max(positions)-min(positions)>tolerance_m:
            raise ItineraryExtractionError('El anclaje es ambiguo entre varias posiciones de la ruta.')
    if point.distance(route) > tolerance_m:
        raise ItineraryExtractionError("La cabecera está fuera del eje; no se añade un conector.")
    distance = route.project(point)
    if distance <= tolerance_m or route.length-distance <= tolerance_m:
        raise ItineraryExtractionError("La cabecera debe ser interior al recorrido.")
    first, second = substring(route, 0, distance), substring(route, distance, route.length)
    if abs(first.length + second.length - route.length) > tolerance_m or first.coords[-1] != second.coords[0]:
        raise ItineraryExtractionError("La partición no conserva continuidad y longitud.")
    return first, second

def audit_osm_node_connectivity(lineage, source_frames, target_crs, tolerance_m):
    """Comprobar nodos compartidos, incluidos los recortes de vías en un enlace.

    Una coincidencia de coordenadas sin el mismo nodo OSM no acredita conexión.
    No elige caminos ni añade enlaces; conserva la secuencia explícita recibida.
    """
    from movilidad_teide.cartografia.fuentes_rutas import select_exact_records
    frames = {sid:frame.to_crs(target_crs) for sid,frame in source_frames.items()
              if 'osm_way_id' in frame}
    endpoints=[]
    for _,part in lineage.iterrows():
        record=select_exact_records(frames[part.source_id],json.loads(part.feature_filters_json)).iloc[0]
        if not isinstance(record.geometry,LineString) or not isinstance(part.geometry,LineString):
            raise ItineraryExtractionError('La comprobación OSM requiere componentes lineales individuales.')
        nodes=json.loads(record.source_node_ids_json);coordinates=np.asarray(record.geometry.coords)
        if len(nodes)!=len(coordinates):
            raise ItineraryExtractionError('No coincide el número de nodos y vértices de la vía OSM.')
        selected=[]
        for point in [part.geometry.coords[0],part.geometry.coords[-1]]:
            hits=np.flatnonzero(np.linalg.norm(coordinates-np.asarray(point),axis=1)<=tolerance_m)
            identifiers={nodes[int(i)] for i in hits}
            if len(identifiers)!=1:
                raise ItineraryExtractionError('El extremo recortado no identifica un único nodo OSM original.')
            selected.append(next(iter(identifiers)))
        endpoints.append((record.osm_way_id,*selected))
    rows=[]
    for i,(previous,following) in enumerate(zip(endpoints[:-1],endpoints[1:]),start=1):
        if previous[2]!=following[1]:
            raise ItineraryExtractionError('Las vías coinciden geométricamente pero no comparten nodo OSM.')
        rows.append({'sequence':i,'from_way':previous[0],'to_way':following[0],'via_node':previous[2],
                     'shared_original_node':True})
    return pd.DataFrame(rows,columns=['sequence','from_way','to_way','via_node','shared_original_node'])

def audit_osm_grade_separated_crossings(line, lineage, itinerary, config, project_root, tolerance_m):
    """Comprobar todos los autocruces declarados de una secuencia OSM.

    Cada cruce exige huella del trazado, dos componentes identificados, niveles
    distintos documentados y evidencia de puente o túnel. Un extremo común solo
    se admite si está declarado, une partes consecutivas y queda fuera del cruce.
    No convierte el cruce en conexión ni modifica geometría o cotas.
    """
    import xml.etree.ElementTree as ET
    audit = itinerary['osm_grade_separation_audit']
    expected = audit.get('expected_crossings', [])
    observed = {'reason':audit.get('reason'), 'crossings':[], 'route_sha256_matches':False}
    if (not isinstance(audit.get('reason'),str) or not audit['reason'].strip()
            or itinerary['definition_mode']!='official_axis_sequence' or not expected
            or audit.get('expected_route_sha256')!=sha256(line.wkb).hexdigest()):
        return False, observed
    observed['route_sha256_matches'] = True
    # Contar todos los autocruces geométricos; ninguno puede quedar sin explicar.
    edges = [LineString([a,b]) for a,b in zip(line.coords[:-1],line.coords[1:])]
    tree = STRtree(edges); crossings=[]
    for i,edge in enumerate(edges):
        for j in tree.query(edge,predicate='intersects'):
            if j<=i+1:continue
            point=edge.intersection(edges[j])
            if not isinstance(point,Point):return False,observed
            crossings.append(point)
    if len(crossings)!=len(expected):return False,observed
    matched=set(); originals={}
    for entry in expected:
        try:
            xy=entry['point_m']
            if len(xy)!=2 or not np.isfinite(xy).all():return False,observed
            candidates=[i for i,p in enumerate(crossings) if i not in matched and p.distance(Point(xy))<=tolerance_m]
            if len(candidates)!=1:return False,observed
            crossing=crossings[candidates[0]]; pair=[]
            for name in ['lower','upper']:
                sid,wid=entry[name+'_source_id'],str(entry[name+'_osm_way_id'])
                source=config['sources'][sid]
                if source['format']!='osm_xml':return False,observed
                parts=[i for i,p in enumerate(itinerary['axis_parts']) if p['source_id']==sid and str(p['feature_filters'].get('osm_way_id'))==wid]
                if len(parts)!=1 or lineage.iloc[parts[0]].geometry.distance(crossing)>tolerance_m:return False,observed
                if sid not in originals:
                    path=Path(project_root)/source['path']
                    if file_sha256(path)!=source['expected_sha256']:return False,observed
                    originals[sid]=ET.parse(path).getroot()
                ways=originals[sid].findall(f"way[@id='{wid}']")
                if len(ways)!=1:return False,observed
                way=ways[0];tags={t.get('k'):t.get('v') for t in way.findall('tag')}
                if way.get('version')!=str(entry[name+'_osm_version']):return False,observed
                layer=int(tags.get('layer','0'))
                pair.append({'source_id':sid,'osm_way_id':wid,'version':way.get('version'),
                    'layer':layer,'layer_tag':tags.get('layer'),'bridge':tags.get('bridge'),
                    'maxheight':tags.get('maxheight'),'nodes':set(n.get('ref') for n in way.findall('nd')),
                    'node_order':[n.get('ref') for n in way.findall('nd')],
                    'part_index':parts[0],'tunnel':tags.get('tunnel')})
            lower,upper=pair
            if (lower['layer']!=entry['lower_layer'] or upper['layer']!=entry['upper_layer']
                    or upper['layer']<=lower['layer']
                    or not (upper['bridge'] in {'yes','viaduct'} or lower['tunnel']=='yes')):
                return False,observed
            # Algunas rampas cruzan sobre su túnel y se unen más adelante: exigir el extremo exacto.
            shared = lower['nodes'] & upper['nodes']
            declared_endpoint = entry.get('shared_endpoint_node_id')
            if declared_endpoint is not None:
                if shared!={str(declared_endpoint)}:
                    return False,observed
                earlier,later=sorted(pair,key=lambda part:part['part_index'])
                if later['part_index']!=earlier['part_index']+1:
                    return False,observed
                end_ids=[]
                for record,is_start in [(earlier,False),(later,True)]:
                    spec=itinerary['axis_parts'][record['part_index']]
                    if 'clip_start_anchor_id' in spec or 'clip_end_anchor_id' in spec:
                        return False,observed
                    order=record['node_order'][::-1] if spec.get('reverse',False) else record['node_order']
                    end_ids.append(order[0 if is_start else -1])
                join_a=Point(lineage.iloc[earlier['part_index']].geometry.coords[-1])
                join_b=Point(lineage.iloc[later['part_index']].geometry.coords[0])
                if (end_ids!=[str(declared_endpoint)]*2 or join_a.distance(join_b)>tolerance_m
                        or min(join_a.distance(crossing),join_b.distance(crossing))<=tolerance_m):
                    return False,observed
            elif shared:
                return False,observed
            matched.add(candidates[0])
            for part in pair:
                for key in ['nodes','node_order','part_index']:
                    part.pop(key)
                if part['tunnel'] is None:
                    part.pop('tunnel')
            evidence={'point_m':[crossing.x,crossing.y],
                'lower':lower,'upper':upper,'shared_original_nodes':bool(shared)}
            if declared_endpoint is not None:
                evidence.update(shared_endpoint_node_id=str(declared_endpoint),
                    shared_original_node_at_crossing=False)
            observed['crossings'].append(evidence)
        except (KeyError,TypeError,ValueError,IndexError):
            return False,observed
    return len(matched)==len(crossings), observed

def compare_reference_and_service_chain(reference, feeder, mountain, *, toward_terminal, tolerance_m):
    """Validar extremos y medir una cadena sin alterar la referencia directa.

    Las geometrías se reciben orientadas. El transbordo puede introducir un
    desvío: su longitud se conserva aunque los dos tramos vuelvan por una vía
    compartida. Esta comparación no concatena líneas ni calcula ahorro energético.
    """
    lines = [reference, feeder, mountain]
    if (not isinstance(toward_terminal, bool) or not np.isfinite(tolerance_m)
            or tolerance_m <= 0 or any(not isinstance(g, LineString) or g.is_empty
            or not g.is_valid or not np.isfinite(g.length) or g.length <= 0 for g in lines)):
        raise ItineraryExtractionError('La comparación requiere tres líneas orientadas y tolerancia positiva.')
    first, second = (feeder, mountain) if toward_terminal else (mountain, feeder)
    pairs = [(reference.coords[0], first.coords[0]),
             (first.coords[-1], second.coords[0]),
             (second.coords[-1], reference.coords[-1])]
    if any(Point(a).distance(Point(b)) > tolerance_m for a, b in pairs):
        raise ItineraryExtractionError('La cadena no comparte origen, transbordo y destino; no se añade un conector.')
    chain_km = (feeder.length + mountain.length) / 1000
    return {'reference_km': reference.length / 1000, 'feeder_km': feeder.length / 1000,
            'mountain_km': mountain.length / 1000, 'chain_km': chain_km,
            'chain_minus_reference_km': chain_km - reference.length / 1000}
