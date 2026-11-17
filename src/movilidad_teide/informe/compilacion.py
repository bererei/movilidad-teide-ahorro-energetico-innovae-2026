"""Compilar el maestro suministrado, sin cargar generadores históricos."""
from pathlib import Path
import json
import subprocess
from movilidad_teide.trazabilidad import sha256_archivo

def compilar_pdf(destino):
    """Compilo una copia de revisión; el PDF vigente no se sobrescribe."""
    destino = Path(destino).resolve()
    compilacion = destino / 'compilacion'
    compilacion.mkdir(exist_ok=True)
    for _ in range(3):
        result = subprocess.run(
            ['xelatex', '-interaction=nonstopmode', '-halt-on-error',
             '-output-directory', str(compilacion), 'main.tex'],
            cwd=destino, capture_output=True, text=True,
        )
        (compilacion / 'compilacion.txt').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'La compilación no terminó correctamente: {compilacion / "compilacion.txt"}')
    pdf = compilacion / 'main.pdf'
    meta_path = destino / 'metadatos.json'
    meta = json.loads(meta_path.read_text())
    meta['generacion_integrada']['compilacion_pdf_ejecutada'] = True
    meta['pdf_generado'] = {'ruta': str(pdf.relative_to(destino)), 'sha256': sha256_archivo(pdf)}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    return pdf
