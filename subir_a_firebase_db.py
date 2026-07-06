import os
import sys
import json
import firebase_admin
from firebase_admin import credentials, db

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CRED_FILE = "credenciales.json"
DATA_FILE = r"output\digesto_completo_enriquecido.json"
DB_URL = "https://digestoag-cb08c-default-rtdb.firebaseio.com"

if not os.path.exists(CRED_FILE):
    print("Error: No se encontro el archivo 'credenciales.json'.")
    sys.exit(1)

if not os.path.exists(DATA_FILE):
    print(f"Error: El archivo de datos {DATA_FILE} no existe.")
    sys.exit(1)

print(f"Inicializando Firebase Realtime Database en: {DB_URL}")
cred = credentials.Certificate(CRED_FILE)
firebase_admin.initialize_app(cred, {
    'databaseURL': DB_URL
})

# Cargar las normas locales
with open(DATA_FILE, "r", encoding="utf-8") as f:
    normas = json.load(f)

print(f"Cargadas {len(normas)} normas locales listas para subir...")

# Estructurar datos
datos_db = {}
for idx, n in enumerate(normas):
    norma_id = n.get("id") or idx
    datos_db[str(norma_id)] = {
        "id": n.get("id"),
        "numero": n.get("numero"),
        "titulo": n.get("titulo"),
        "resumen": n.get("resumen"),
        "tipo_nombre": n.get("tipo_nombre", "Ordenanza"),
        "categoria_nombre": n.get("categoria_nombre", "General"),
        "vigente": n.get("vigente", True),
        "fecha": n.get("fecha"),
        "archivo_pdf": n.get("archivo_pdf"),
        "url_detalle": n.get("url_detalle")
    }

print("\nSubiendo datos a Firebase Realtime Database...")
ref = db.reference('/')
ref.child('normas').set(datos_db)

print("\n¡Felicidades! Se ha subido la base de datos completa de las 9320 normas a tu Firebase Realtime Database.")
