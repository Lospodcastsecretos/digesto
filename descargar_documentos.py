import os
import json
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SITE_URL = "https://digestoaltagracia.com.ar"
API_KEY = "$2y$10$VXghLWoHpSnWbrhXk.p0y.BRuUHI3RZ7pAT1QC4F8T3.7693PWVCy"
OUTPUT_DIR = "output"
DOWNLOADS_DIR = os.path.join(OUTPUT_DIR, "descargas")
MAP_FILE = os.path.join(OUTPUT_DIR, "mapeo_drive.json")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Cabeceras de autorizacion requeridas por el Digesto
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "x-requested-with": "XMLHttpRequest",
    "api-key": API_KEY,
    "referer": f"{SITE_URL}/"
}

# 1. Cargar la base de datos de normas
json_files = [f for f in os.listdir(OUTPUT_DIR) if f.startswith("digesto_completo_enriquecido") or (f.startswith("digesto_completo_") and f.endswith(".json"))]
if not json_files:
    print("Error: No se encontro ningun archivo 'digesto_completo_*.json'")
    sys.exit(1)

json_files.sort(reverse=True)
latest_json = os.path.join(OUTPUT_DIR, json_files[0])
print(f"Cargando normas desde: {latest_json}")

with open(latest_json, "r", encoding="utf-8") as f:
    normas = json.load(f)

normas_con_archivo = [n for n in normas if n.get("archivo_pdf")]
print(f"Total normas registradas: {len(normas)}")
print(f"Normas con archivos registrados: {len(normas_con_archivo)}")

# Cargar mapeo existente
mapeo = {}
if os.path.exists(MAP_FILE):
    try:
        with open(MAP_FILE, "r", encoding="utf-8") as f:
            mapeo = json.load(f)
        print(f"Mapeo cargado con {len(mapeo)} registros.")
    except Exception as e:
        print(f"Error cargando mapeo previo: {e}")

# Filtrar las que faltan resolver
pendientes = [n["archivo_pdf"] for n in normas_con_archivo if n["archivo_pdf"] not in mapeo]
print(f"Archivos pendientes de resolver ID de Drive: {len(pendientes)}")

# 2. Resolucion multihilo de los IDs de Drive
def resolver_drive_id(filename):
    url = f"{SITE_URL}/api/documentos/{filename}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return filename, data[0].get("id")
        return filename, "sin_archivo_fisico"
    except Exception as e:
        return filename, f"error: {str(e)}"

if pendientes:
    print(f"\nIniciando resolucion paralela de IDs de Drive (30 hilos)...")
    resueltos_count = 0
    
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(resolver_drive_id, file): file for file in pendientes}
        
        for future in as_completed(futures):
            try:
                filename, drive_id = future.result()
                mapeo[filename] = drive_id
                resueltos_count += 1
                
                if resueltos_count % 100 == 0 or resueltos_count == len(pendientes):
                    print(f" -> Procesados: {resueltos_count}/{len(pendientes)}")
                    with open(MAP_FILE, "w", encoding="utf-8") as f:
                        json.dump(mapeo, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Error procesando resolucion: {e}")

# Guardar mapeo final
with open(MAP_FILE, "w", encoding="utf-8") as f:
    json.dump(mapeo, f, indent=2, ensure_ascii=False)

# 3. Descarga paralela a traves del endpoint universal /download (usando api-key)
drive_downloads = {k: v for k, v in mapeo.items() if v and not v.startswith("sin_archivo_fisico") and not v.startswith("error")}
print(f"\nTotal de archivos fisicos reales en Google Drive: {len(drive_downloads)}")

# Limpiar archivos corruptos de ejecuciones anteriores (archivos HTML o vacios)
print("\nLimpiando archivos corruptos de descargas anteriores...")
eliminados_count = 0
for file in list(drive_downloads.keys()):
    dest_path = os.path.join(DOWNLOADS_DIR, file)
    if os.path.exists(dest_path):
        try:
            # Si pesa menos de 30KB o tiene estructura html, es corrupto
            is_corrupt = False
            if os.path.getsize(dest_path) < 20000:
                is_corrupt = True
            else:
                with open(dest_path, "r", encoding="utf-8", errors="ignore") as test_f:
                    head = test_f.read(100)
                    if "<!doctype html>" in head.lower() or "<html" in head.lower() or "error" in head.lower():
                        is_corrupt = True
            if is_corrupt:
                os.remove(dest_path)
                eliminados_count += 1
        except Exception:
            pass
print(f"  -> Eliminados {eliminados_count} archivos corruptos.")

# Filtrar descargas pendientes
descargas_pendientes = {}
for file, drive_id in drive_downloads.items():
    dest_path = os.path.join(DOWNLOADS_DIR, file)
    if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
        descargas_pendientes[file] = drive_id

print(f"Archivos pendientes de descargar fisicamente: {len(descargas_pendientes)}")

def descargar_archivo(file, drive_id):
    dest_path = os.path.join(DOWNLOADS_DIR, file)
    # Usamos EXCLUSIVAMENTE 'download' porque 'export' da HTTP 500 para documentos de Office en su servidor
    url = f"{SITE_URL}/download/{drive_id}"
    
    try:
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=40, stream=True)
        if resp.status_code == 200:
            # Validar que el servidor no haya retornado una pagina HTML de error
            content_type = resp.headers.get("Content-Type", "")
            if "html" in content_type:
                return file, "Error: El servidor devolvio una pagina HTML en lugar del archivo binario"
            
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
            return file, True
        else:
            return file, f"HTTP Error {resp.status_code}"
    except Exception as e:
        return file, str(e)

# Descargar usando 10 hilos en paralelo (para cuidar la tasa de peticiones al Digesto)
descargados_ok = 0
fallidos = 0

if descargas_pendientes:
    print(f"\nIniciando descargas concurrentes desde el Digesto de Alta Gracia (10 hilos)...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(descargar_archivo, file, d_id): file for file, d_id in descargas_pendientes.items()}
        
        for future in as_completed(futures):
            file = futures[future]
            try:
                file_name, status = future.result()
                if status is True:
                    descargados_ok += 1
                    if descargados_ok % 20 == 0 or descargados_ok == len(descargas_pendientes):
                        print(f" -> Descargados: {descargados_ok}/{len(descargas_pendientes)}")
                else:
                    fallidos += 1
                    print(f" -> Error en {file_name}: {status}")
            except Exception as e:
                fallidos += 1
                print(f" -> Excepcion en {file}: {e}")

print(f"\nProceso finalizado:")
print(f"  - Archivos descargados exitosamente en esta sesion: {descargados_ok}")
print(f"  - Descargas fallidas: {fallidos}")
print(f"  - Todos los documentos se encuentran en la carpeta: {DOWNLOADS_DIR}")
