import os
import sys
import win32com.client as win32

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DOWNLOADS_DIR = os.path.abspath(r"output\descargas")

if not os.path.exists(DOWNLOADS_DIR):
    print(f"Error: La carpeta {DOWNLOADS_DIR} no existe.")
    sys.exit(1)

# 1. Buscar todos los archivos .doc antiguos
doc_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.lower().endswith(".doc")]
if not doc_files:
    print("No se encontraron archivos .doc para convertir.")
    sys.exit(0)

print(f"Se encontraron {len(doc_files)} archivos .doc para convertir a .docx.")

# 2. Iniciar Word de forma invisible
print("Iniciando Microsoft Word...")
word = win32.gencache.EnsureDispatch('Word.Application')
word.Visible = False

convertidos = 0
fallidos = 0

# 3. Iterar y convertir
try:
    for idx, filename in enumerate(doc_files):
        doc_path = os.path.join(DOWNLOADS_DIR, filename)
        docx_path = doc_path + "x" # ej: Ord.doc -> Ord.docx
        
        print(f"[{idx+1}/{len(doc_files)}] Convirtiendo: {filename}...")
        try:
            doc = word.Documents.Open(doc_path)
            # Formato 12 o 16 es para guardar como XML Document (.docx)
            doc.SaveAs2(docx_path, FileFormat=16)
            doc.Close()
            
            # Borrar el archivo .doc original para que no quede duplicado
            os.remove(doc_path)
            convertidos += 1
        except Exception as e:
            fallidos += 1
            print(f"  -> Error al convertir {filename}: {e}")
            
finally:
    # 4. Cerrar Word limpiamente
    print("Cerrando Microsoft Word...")
    word.Quit()

print(f"\nProceso finalizado:")
print(f"  - Archivos convertidos con éxito: {convertidos}")
print(f"  - Conversiones fallidas: {fallidos}")
