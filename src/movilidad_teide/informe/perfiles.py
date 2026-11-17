"""Figuras de altitud de los perfiles ya utilizados; no recalcula consumo."""
from pathlib import Path
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .formato import formatear_ejes
from movilidad_teide.trazabilidad import sha256_archivo

NOMBRES={'la_orotava_aguamansa':'La Orotava','puerto_aguamansa':'Puerto de la Cruz','adeje_vilaflor':'Adeje · costa','alcala_chio':'Alcalá','laguna_esperanza':'La Laguna','columbus_vilaflor':'Arona · costa','realejos_aguamansa':'Los Realejos','vilaflor_local':'Vilaflor · entorno local','abona_vilaflor':'Abona','santa_cruz_esperanza':'Santa Cruz','arico_vilaflor':'Arico','masca_chio':'Masca','candelaria_esperanza':'Candelaria','acentejo_esperanza':'El Sauzal · Acentejo','icod_chio':'Icod','garachico_chio':'Garachico','guancha_aguamansa':'La Guancha','adeje_oeste_chio':'Adeje · oeste','gigantes_chio':'Los Gigantes','rosario_esperanza':'El Rosario','piche_esperanza':'Piche','laguna_norte_esperanza':'La Laguna · norte','tegueste_esperanza':'Tegueste · Valle Molina','ursula_aguamansa':'Santa Úrsula','victoria_aguamansa':'La Victoria','san_miguel_vilaflor':'San Miguel','tanque_chio':'El Tanque','arico_medianias_vilaflor':'Arico · medianías','fasnia_vilaflor':'Fasnia','arafo':'Arafo','guimar':'Güímar'}

def preparar_perfiles(root,destino,datos):
 root=Path(root);destino=Path(destino);sources=[];checks=[]
 plt.rcParams.update({'font.family':'Liberation Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
 def guardar(fig,name):
  formatear_ejes(fig);fig.tight_layout()
  for ext in ['pdf','png','svg']:fig.savefig(destino/'figuras'/(name+'.'+ext),dpi=180,bbox_inches='tight')
  plt.close(fig)
 def estilo(ax):ax.set(xlabel='Distancia desde el origen de ida (km)',ylabel='Altitud del terreno (m)');ax.grid(alpha=.15)
 base=root/'data/silver/geografia/perfiles_altimetricos'
 grupos=[('chio_boca_tauce','Chío → Boca Tauce'),('la_esperanza_el_portillo','La Esperanza → El Portillo'),('aguamansa_el_portillo','Aguamansa → El Portillo'),('vilaflor_boca_tauce','Vilaflor → Boca Tauce'),('interior_boca_tauce_el_portillo','Boca Tauce → El Portillo · interior')]
 fig,axes=plt.subplots(3,2,figsize=(7.2,8));axes.flat[-1].axis('off')
 for ax,(folder,title) in zip(axes.flat,grupos):
  paths=sorted((base/folder).glob('tramos_*_propuesta.parquet'));assert len(paths)==2
  for path in paths:
   q=pd.read_parquet(path).sort_values('distance_start_m');sources.append(path)
   x=np.r_[q.distance_start_m.to_numpy(),q.distance_end_m.iloc[-1]]/1000;y=np.r_[q.elevation_start_m.to_numpy(),q.elevation_end_m.iloc[-1]]
   ida='_ida_' in path.name;ax.plot(x if ida else x[-1]-x,y,color='#0C4767' if ida else '#397568',ls='-' if ida else '--',label='Ida' if ida else 'Regreso',lw=1.2)
  ax.set_title(title,fontsize=11);estilo(ax)
 axes.flat[0].legend(frameon=False,fontsize=9);guardar(fig,'perfiles_lanzaderas')
 path=root/'data/silver/energia/referencias_unitarias/pendiente_turismos/segmentos_por_via.parquet';sources.append(path)
 q=pd.read_parquet(path);q=q[q.rol.eq('alimentador')];routes=pd.read_csv(root/'data/silver/demanda/asignacion/recorridos_referencia_calculo.csv',sep=';')
 path_routes=root/'data/silver/demanda/asignacion/recorridos_referencia_calculo.csv';sources.append(path_routes)
 route=routes[routes.comparacion_calculo_id.notna()].drop_duplicates(['comparacion_calculo_id','sentido'])
 extra_path=root/datos['referencia']['indice']['energia']/'perfiles_alimentadores_nuevos.parquet'
 additional=root/datos['referencia']['indice']['excepciones']/'perfiles_alimentadores_excepciones.parquet'
 sources.extend([extra_path,additional]);extra=pd.concat([pd.read_parquet(extra_path),pd.read_parquet(additional)],ignore_index=True)
 catpath=root/'data/bronze/geografia/rutas_cabeceras/20261108_osrm/catalogo.csv';sources.append(catpath);cat=pd.read_csv(catpath,sep=';')
 selected=datos['tablas']['calendario_operativo'][['cupo','max_programadas_programa','perfil']].drop_duplicates();used=set()
 for r in selected.itertuples():
  p=root/datos['referencia']['indice']['captura']/'ofertas'/str(r.cupo)/str(r.max_programadas_programa)/r.perfil/'traslados.csv'
  sources.append(p)
  if p.stat().st_size>3:used.update(pd.read_csv(p,sep=';').origen_id)
 cat=cat[cat.origen_id.isin(used)]
 extra=extra[extra.itinerary_id.isin(cat.archivo)].drop_duplicates(['itinerary_id','sample_id'])
 assert extra.itinerary_id.nunique()==len(cat)==14
 cab={'LAGUNA':'La Esperanza','OROTAVA':'Aguamansa','CHIO':'Chío','VILAFLOR':'Vilaflor'}
 for name,heads in [('perfiles_coche_norte',['Aguamansa','La Esperanza']),('perfiles_coche_sur',['Chío','Vilaflor'])]:
  fig,axes=plt.subplots(2,1,figsize=(7.2,8.5))
  for ax,head in zip(axes,heads):
   ids=route[route.cabecera_calculo.eq(head)].comparacion_calculo_id.unique();colors=plt.colormaps['tab10']
   for i,ident in enumerate(ids):
    for r in route[route.comparacion_calculo_id.eq(ident)].itertuples():
     g=q[q.comparacion_id.eq(ident)&q.itinerary_id.eq(r.itinerario_alimentador_id)].sort_values('distance_start_m');assert len(g)>0
     np.testing.assert_allclose(g.length_m.sum()/1000,r.alimentador_km,atol=1e-8,rtol=0)
     x=np.r_[g.distance_start_m.to_numpy(),g.distance_end_m.iloc[-1]]/1000;y=np.r_[g.elevation_start_m.to_numpy(),g.elevation_end_m.iloc[-1]];x-=x[0];ida=r.sentido=='hacia_teide'
     ax.plot(x if ida else x[-1]-x,y,color=colors(i%10),lw=1,ls='-' if ida else '--',label=NOMBRES[ident] if ida else None)
     checks.append({'origen':NOMBRES[ident],'cabecera':head,'sentido':r.sentido,'km':float(g.length_m.sum()/1000)})
   # Los nombres de los archivos identifican el corredor original; el destino se lee del catálogo.
   for ident,gg in extra.groupby('itinerary_id'):
    c=cat[cat.archivo.eq(ident)];assert len(c)>0
    if cab[c.cabecera_reserva.iloc[0]]!=head:continue
    g=gg.sort_values('distance_m');ida=c.sentido.iloc[0]=='ida';x=g.distance_m.to_numpy()/1000
    np.testing.assert_allclose(x[-1],c.km_geometria.iloc[0],atol=1e-8,rtol=0)
    label=NOMBRES[c.comparacion.iloc[0]]+' · reasignación' if ida else None
    ax.plot(x if ida else x[-1]-x,g.elevation_m,color=colors((len(ids)+list(extra.itinerary_id.unique()).index(ident)//2)%10),lw=1.2,ls=':' if ida else '-.',label=label)
   ax.set_title('Coche hasta '+head,fontsize=11);estilo(ax);ax.legend(fontsize=10.5,ncol=2,frameon=False,loc='upper left',bbox_to_anchor=(0,-.24))
  fig.subplots_adjust(hspace=.8);guardar(fig,name)
 assert len(checks)==62 and len({r['origen'] for r in checks})==31
 return {'perfiles_habituales_dirigidos':62,'referencias_territoriales':31,'perfiles_alternativos':extra.itinerary_id.nunique(),'longitudes_cotejadas':True,'fuentes_sha256':{str(p.relative_to(root)):sha256_archivo(p) for p in sources},'detalle':checks}
