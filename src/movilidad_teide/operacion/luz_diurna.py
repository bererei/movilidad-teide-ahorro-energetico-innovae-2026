"""Leo la referencia solar oficial; no la convierto en luz real de la carretera."""
from datetime import date
import re
import subprocess
import pandas as pd

URL_IGN="https://astronomia.ign.es/o/main-theme/images/webAstro/paginas/documentos/pdf/salidapuestasol/pdf2028/Santa-2028.pdf"
FUENTE_IGN="data/bronze/documentacion/luz_diurna/Santa-2028.pdf"


def leer_tabla_ign(pdf):
    """Extraigo las366 fechas conservando la hora oficial canaria de la tabla."""
    texto=subprocess.check_output(["pdftotext","-layout",str(pdf),"-"],text=True)
    if "SANTA CRUZ DE TENERIFE" not in texto or "PARA 2028" not in texto or "Hora oficial en las islas Canarias" not in texto:
        raise ValueError("Referencia solar distinta de Santa Cruz2028 en hora oficial canaria.")
    lines=[line for line in texto.splitlines() if re.match(r"^\s*\d{1,2}\s",line)]
    first=next(line for line in lines if int(line.split()[0])==1)
    tokens=list(re.finditer(r"\d+",first))
    if len(tokens)!=25:raise ValueError("Formato de tabla solar no reconocido.")
    spans=[(tokens[1+2*m].start(),tokens[2+2*m].end()) for m in range(12)]
    out=[]
    for line in lines:
        dia=int(line.split()[0])
        for mes,(a,b) in enumerate(spans,1):
            parts=line[a:b].split()
            if not parts:continue
            if len(parts)!=2:raise ValueError("Celda solar no interpretable.")
            horas=[int(p)//100*60+int(p)%100 for p in parts]
            if any(not 0<=int(p)%100<60 for p in parts) or not 0<horas[0]<horas[1]<1440:raise ValueError("Hora solar no válida.")
            out.append({"fecha":date(2028,mes,dia).isoformat(),"mes":mes,"orto_min":horas[0],"ocaso_min":horas[1],
                "referencia":"IGN/OAN, Santa Cruz de Tenerife; horizonte ideal, no terreno del Teide","zona_horaria":"Atlantic/Canary; hora oficial ya aplicada en la fuente"})
    tabla=pd.DataFrame(out)
    if len(tabla)!=366 or tabla.fecha.duplicated().any():raise ValueError("Faltan fechas o hay duplicaciones solares.")
    return tabla.sort_values("fecha").reset_index(drop=True)
