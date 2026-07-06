import os
import sys
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DOWNLOADS_DIR = r"output\descargas"
MAP_FIREBASE_FILE = r"output\mapeo_firebase.json"
DATA_FILE = r"buscador\datos.json"

# Nombre del bucket por defecto
BUCKET_NAME = "digestoag-cb08c.appspot.com"

if not os.path.exists(DOWNLOADS_DIR):
    print(f"Error: La carpeta {DOWNLOADS_DIR} no existe.")
    sys.exit(1)

# Obtener archivos locales
archivos = [f for f in os.listdir(DOWNLOADS_DIR) if os.path.isfile(os.path.join(DOWNLOADS_DIR, f))]
print(f"Se encontraron {len(archivos)} archivos locales para subir a Firebase Storage ({BUCKET_NAME}).")

mapeo_fb = {}
if os.path.exists(MAP_FIREBASE_FILE):
    try:
        with open(MAP_FIREBASE_FILE, "r", encoding="utf-8") as f:
            mapeo_fb = json.load(f)
        print(f"Mapeo previo cargado con {len(mapeo_fb)} archivos.")
    except Exception as e:
        print(f"Error cargando mapeo: {e}")

# Filtrar pendientes
pendientes = [f for f in archivos if f not in mapeo_fb]
print(f"Archivos pendientes de subir: {len(pendientes)}")

# Subida directa mediante la API REST pública
def subir_archivo_rest(filename, current_bucket):
    filepath = os.path.join(DOWNLOADS_DIR, filename)
    try:
        content_type = "application/octet-stream"
        if filename.lower().endswith(".pdf"):
            content_type = "application/pdf"
        elif filename.lower().endswith(".docx"):
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif filename.lower().endswith(".doc"):
            content_type = "application/msword"

        # Intentar con el bucket indicado
        url = f"https://firebasestorage.googleapis.com/v0/b/{current_bucket}/o?name=documentos/{filename}"
        
        with open(filepath, "rb") as f:
            headers = {"Content-Type": content_type}
            response = requests.post(url, headers=headers, data=f, timeout=60)
            
        if response.status_code == 200:
            res_data = response.json()
            download_token = res_data.get("downloadTokens", "")
            public_url = f"https://firebasestorage.googleapis.com/v0/b/{current_bucket}/o/documentos%2F{filename}?alt=media&token={download_token}"
            return filename, public_url, current_bucket
        elif response.status_code == 404 and current_bucket == "digestoag-cb08c.appspot.com":
            # Si el bucket por defecto no existe, intentar con el alternativo
            alt_bucket = "digestoag-cb08c.firebasestorage.app"
            url_alt = f"https://firebasestorage.googleapis.com/v0/b/{alt_bucket}/o?name=documentos/{filename}"
            with open(filepath, "rb") as f:
                headers = {"Content-Type": content_type}
                response_alt = requests.post(url_alt, headers=headers, data=f, timeout=60)
            if response_alt.status_code == 200:
                res_data = response_alt.json()
                download_token = res_data.get("downloadTokens", "")
                public_url = f"https://firebasestorage.googleapis.com/v0/b/{alt_bucket}/o/documentos%2F{filename}?alt=media&token={download_token}"
                return filename, public_url, alt_bucket
            else:
                return filename, f"error: HTTP {response_alt.status_code} - {response_alt.text}", current_bucket
        else:
            return filename, f"error: HTTP {response.status_code} - {response.text}", current_bucket
    except Exception as e:
        return filename, f"error: {str(e)}", current_bucket

subidos_ok = 0
fallidos = 0
active_bucket = BUCKET_NAME

if pendientes:
    print(f"\nIniciando subida REST masiva a Firebase Storage (15 hilos)...")
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(subir_archivo_rest, f, active_bucket): f for f in pendientes}
        
        for future in as_completed(futures):
            filename = futures[future]
            try:
                fname, result, bucket_used = future.result()
                if not result.startswith("error"):
                    mapeo_fb[fname] = result
                    active_bucket = bucket_used # Actualizar para los siguientes
                    subidos_ok += 1
                    if subidos_ok % 100 == 0 or subidos_ok == len(pendientes):
                        print(f" -> Subidos: {subidos_ok}/{len(pendientes)}")
                        with open(MAP_FIREBASE_FILE, "w", encoding="utf-8") as f_map:
                            json.dump(mapeo_fb, f_map, indent=2, ensure_ascii=False)
                else:
                    fallidos += 1
                    print(f" -> Error en {fname}: {result}")
            except Exception as e:
                fallidos += 1
                print(f" -> Excepcion en {filename}: {e}")

# Guardar mapeo final
with open(MAP_FIREBASE_FILE, "w", encoding="utf-8") as f_map:
    json.dump(mapeo_fb, f_map, indent=2, ensure_ascii=False)

print(f"\nSubida finalizada. Exitosos: {subidos_ok}, Fallidos: {fallidos}")

# Actualizar buscador/datos.json
if os.path.exists(DATA_FILE):
    print(f"\nActualizando base de datos del buscador: {DATA_FILE}...")
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f_data:
            normas = json.load(f_data)
        
        actualizadas = 0
        for n in normas:
            archivo = n.get("archivo_pdf")
            if archivo and archivo in mapeo_fb:
                n["url_firebase"] = mapeo_fb[archivo]
                actualizadas += 1
                
        with open(DATA_FILE, "w", encoding="utf-8") as f_data:
            json.dump(normas, f_data, indent=2, ensure_ascii=False)
        print(f"¡Base de datos actualizada! Se asociaron {actualizadas} URLs de Firebase.")
    except Exception as e:
        print(f"Error actualizando la base de datos: {e}")
