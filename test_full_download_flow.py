import requests
import json
from urllib.parse import unquote

SITE_URL = "https://digestoaltagracia.com.ar"
FILE_NAME = "86-8593.pdf"

# Iniciar sesion
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://digestoaltagracia.com.ar/",
})

print("Estableciendo sesion...")
resp_init = session.get(SITE_URL, timeout=10)
xsrf_cookie = session.cookies.get("XSRF-TOKEN")
if xsrf_cookie:
    session.headers["X-XSRF-TOKEN"] = unquote(xsrf_cookie)
    # Agregar header requerido por Vue/Laravel
    session.headers["X-Requested-With"] = "XMLHttpRequest"

# Paso 1: Consultar la API de mapeo de archivo a Drive ID
mapping_url = f"{SITE_URL}/api/documentos/{FILE_NAME}"
print(f"\nConsultando mapeo para: {FILE_NAME}")
print(f"URL: {mapping_url}")

resp_map = session.get(mapping_url, timeout=15)
print(f"HTTP Status: {resp_map.status_code}")

try:
    map_data = resp_map.json()
    print("Respuesta del mapeo:")
    print(json.dumps(map_data, indent=2))
    
    if isinstance(map_data, list) and len(map_data) > 0:
        drive_id = map_data[0].get("id")
        print(f"\n-> ¡ID de Google Drive obtenido exitosamente!: {drive_id}")
        
        # Paso 2: Intentar descargar desde la URL de exportacion de Digesto
        export_url = f"{SITE_URL}/export/{drive_id}"
        print(f"\nIntentando descargar desde endpoint del Digesto: {export_url}")
        resp_export = session.get(export_url, allow_redirects=False, timeout=15)
        print(f"HTTP Status: {resp_export.status_code}")
        print(f"Headers: {dict(resp_export.headers)}")
        if resp_export.status_code in (301, 302):
            print(f"Redirige a: {resp_export.headers.get('Location')}")
            
        # Paso 3: Descarga directa de Google Drive
        drive_direct_url = f"https://docs.google.com/uc?export=download&id={drive_id}"
        print(f"\nIntentando descargar directamente de Google Drive: {drive_direct_url}")
        resp_drive = requests.get(drive_direct_url, allow_redirects=True, timeout=20, stream=True)
        print(f"HTTP Status en Drive: {resp_drive.status_code}")
        print(f"Content-Type: {resp_drive.headers.get('Content-Type')}")
        print(f"Content-Length: {resp_drive.headers.get('Content-Length')} bytes")
        
except Exception as e:
    print(f"Error procesando: {e}")
    print(f"Cuerpo crudo: {resp_map.text[:500]}")
