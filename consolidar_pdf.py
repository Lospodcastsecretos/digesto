import os
import re
import sys
from pypdf import PdfWriter

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DOWNLOADS_DIR = r"output\descargas"
OUTPUT_FILE = r"output\digesto_consolidado_pdf.pdf"

if not os.path.exists(DOWNLOADS_DIR):
    print(f"Error: La carpeta {DOWNLOADS_DIR} no existe.")
    sys.exit(1)

# 1. Obtener y ordenar los archivos .pdf de forma natural
pdf_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.lower().endswith(".pdf")]
if not pdf_files:
    print("No se encontraron archivos .pdf en la carpeta de descargas.")
    sys.exit(0)

# Ordenamiento natural (ej: 2.pdf antes que 10.pdf)
def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

pdf_files.sort(key=natural_sort_key)
print(f"Se encontraron {len(pdf_files)} archivos .pdf para consolidar.")

# 2. Inicializar el escritor de PDFs (PdfWriter hace las veces de merger)
writer = PdfWriter()

# 3. Iterar y fusionar
consolidados = 0
fallidos = 0

print("\nIniciando la fusion de los archivos PDF...")
for idx, filename in enumerate(pdf_files):
    filepath = os.path.join(DOWNLOADS_DIR, filename)
    try:
        # Fusionar el archivo actual
        writer.append(filepath)
        consolidados += 1
        if consolidados % 100 == 0 or idx == len(pdf_files) - 1:
            print(f" -> Fusionados: {consolidados}/{len(pdf_files)}...")
    except Exception as e:
        fallidos += 1
        print(f"  -> Error al leer o fusionar {filename}: {e}")

# 4. Escribir el archivo final consolidado
if consolidados > 0:
    print(f"\nEscribiendo el archivo PDF unificado en {OUTPUT_FILE} (Esto puede tomar un momento para un archivo de este tamaño)...")
    try:
        with open(OUTPUT_FILE, "wb") as f_out:
            writer.write(f_out)
        print(f"¡Éxito! Se consolidaron {consolidados} PDFs en: {OUTPUT_FILE}")
        if fallidos > 0:
            print(f"Nota: Se saltaron {fallidos} archivos debido a errores de lectura.")
    except Exception as e:
        print(f"Error al escribir el archivo consolidado: {e}")
else:
    print("No se pudo consolidar ningun archivo PDF.")

# Cerrar el writer
writer.close()
