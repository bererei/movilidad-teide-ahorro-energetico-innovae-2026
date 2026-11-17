"""Cierro un reloj fijo con inventario por bases mediante flujo de coste mínimo."""
import heapq
from collections import Counter
import numpy as np
from .circulacion_compartida import materializar,emparejamiento_maximo


def cadenas_con_bases(viajes,red,capacidades,*,inicio=420.,fin=1200.,regulacion=10.):
    """Mínimo exacto de cadenas de este reloj y red, incluidas sus bases.

    Cada viaje exige una entrada y una salida. Los enlaces directos cuestan0;
    pasar por una plaza de base cuesta1 y consume una guagua de esa base.
    El flujo conserva el mismo número de inicios y finales en cada base.
    No busca entre todos los horarios ni cambia el inventario.
    """
    t=viajes.sort_values(['salida_min','id_salida'],kind='stable').reset_index(drop=True)
    if t.empty or t.id_salida.duplicated().any() or set(capacidades)!=set(red.bases):raise ValueError('Viajes o bases inválidos.')
    if any(isinstance(v,bool) or int(v)!=v or v<0 for v in capacidades.values()):raise ValueError('Inventario no entero.')
    n=len(t);bases=list(red.bases);m=len(bases);S=2*n+2*m;T=S+1;graph=[[] for _ in range(T+1)]
    def edge(a,b,cap,cost=0):
        f=[b,len(graph[b]),cap,cost,cap];r=[a,len(graph[a]),0,-cost,0]
        graph[a].append(f);graph[b].append(r);return f
    source_edges=[];sink_edges=[]
    for i in range(n):source_edges.append(edge(S,n+i,1));sink_edges.append(edge(i,T,1))
    index={p:k for k,p in enumerate(red.nodos)};travel=np.array([[red.conectar(a,b)['minutos'] for b in red.nodos] for a in red.nodos])
    origins=np.array([index[p] for p in t.origen]);dests=np.array([index[p] for p in t.destino])
    transfer=travel[dests[:,None],origins[None,:]]
    needs=t.llegada_min.to_numpy()[:,None]+regulacion+transfer+(transfer>1e-10)*regulacion
    links={};starts={};ends={}
    for i,j in zip(*np.where(needs<=t.salida_min.to_numpy()[None,:]+1e-8)):
        if i!=j:links[int(i),int(j)]=edge(n+int(i),int(j),1)
    for k,b in enumerate(bases):
        bin_=2*n+k;bout=2*n+m+k;edge(bin_,bout,int(capacidades[b]),1)
        for i,row in enumerate(t.itertuples()):
            a=red.conectar(b,row.origen)['minutos'];z=red.conectar(row.destino,b)['minutos']
            if row.salida_min-a-(regulacion if a>1e-10 else 0)>=inicio-1e-8:starts[k,i]=edge(bout,i,1)
            if row.llegada_min+z+(regulacion if z>1e-10 else 0)<=fin+1e-8:ends[i,k]=edge(n+i,bin_,1)
    # La máxima cantidad de enlaces directos tiene coste0. La reutilizo como
    # flujo inicial óptimo y solo aumento las cadenas pendientes (<=N).
    adjacency=[[] for _ in range(n)]
    for i,j in links:adjacency[i].append(j)
    match,_=emparejamiento_maximo(adjacency,n)
    def enviar(e):e[2]-=1;graph[e[0]][e[1]][2]+=1
    flow=0
    for i,j in enumerate(match):
        if j>=0:
            enviar(source_edges[i]);enviar(links[i,j]);enviar(sink_edges[j]);flow+=1
    potential=[0]*len(graph);cost=0
    while flow<n:
        dist=[float('inf')]*len(graph);prev=[None]*len(graph);dist[S]=0;heap=[(0,S)]
        while heap:
            dd,a=heapq.heappop(heap)
            if dd!=dist[a]:continue
            for k,e in enumerate(graph[a]):
                b,_,cap,c,_=e
                if cap<=0:continue
                nd=dd+c+potential[a]-potential[b]
                if nd<dist[b]:dist[b]=nd;prev[b]=(a,k);heapq.heappush(heap,(nd,b))
        if prev[T] is None:return None
        for k,d in enumerate(dist):
            if d<float('inf'):potential[k]+=d
        node=T
        while node!=S:
            a,k=prev[node];e=graph[a][k];e[2]-=1;graph[node][e[1]][2]+=1;cost+=e[3];node=a
        flow+=1
    def used(e):return e[4]-e[2]
    successor={i:j for (i,j),e in links.items() if used(e)}
    starts_used=sorted((i,bases[k]) for (k,i),e in starts.items() if used(e));ends_used={i:bases[k] for (i,k),e in ends.items() if used(e)}
    chains=[];aa=[];bb=[]
    for i,base in starts_used:
        chain=[i]
        while chain[-1] in successor:
            j=successor[chain[-1]]
            if j in chain:raise ValueError('Ciclo de viajes imposible en una jornada.')
            chain.append(j)
        chains.append(chain);aa.append(base);bb.append(ends_used[chain[-1]])
    if sorted(i for c in chains for i in c)!=list(range(n)) or Counter(aa)!=Counter(bb) or len(chains)!=cost:raise ValueError('El flujo pierde viajes, bases o guaguas.')
    return t,chains,aa,bb


def cerrar_reloj_con_bases(candidatos,red,valores,capacidades,identidades,*,inicio=420.,fin=1200.,max_programadas=27):
    """Materializo el límite elegido dentro de las treinta originales.

    El valor predeterminado conserva los contrastes de tres sustitutas;
    la alternativa de dos permite como máximo28, sin añadir vehículos.
    """
    if isinstance(max_programadas,(bool,np.bool_)) or int(max_programadas)!=max_programadas or not 1<=max_programadas<=30:
        raise ValueError('Límite de guaguas programadas inválido.')
    if sum(capacidades.values())!=30 or any(len(identidades[b])!=capacidades[b] for b in capacidades) or len({i for ids in identidades.values() for i in ids})!=30:
        raise ValueError('Conservar treinta identidades y sus bases.')
    for key,reloj,u,b in candidatos:
        if key[0]>max_programadas:continue
        trips,res=reloj.tablas(u,b);answer=cadenas_con_bases(trips,red,capacidades,inicio=inicio,fin=fin,regulacion=valores['regulacion_min'])
        if answer is None:continue
        t,chains,aa,bb=answer
        if len(chains)>max_programadas:continue
        moves=materializar(t,chains,aa,red,regulacion=valores['regulacion_min'],bases_finales=bb)
        available={base:list(ids) for base,ids in identidades.items()};mapping={f'TF{k+1:02d}':available[base].pop(0) for k,base in enumerate(aa)}
        for old,actual in mapping.items():
            mask=moves.unidad_fisica_id.eq(old)&moves.familia.eq('Vacío');moves.loc[mask,'id_salida']=moves.loc[mask,'id_salida'].str.replace(old+'_',actual+'_',n=1,regex=False)
        moves['unidad_fisica_id']=moves.unidad_fisica_id.map(mapping)
        return {'viajes':t,'reservas':res,'movimientos':moves,'programadas':len(chains),'forma':key[2],'fraccion_regreso':key[3],'criterio_encadenamiento':'Flujo de coste mínimo con bases en el reloj fijo'}
    return None
