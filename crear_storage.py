import os
import sys
import json
import firebase_admin
from firebase_admin import credentials
from google.cloud import storage as gcs

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CRED_FILE = "credenciales.json"

if not os.path.exists(CRED_FILE):
    print("Error: No se encontro el archivo 'credenciales.json'.")
    sys.exit(1)

# Leer proyecto
with open(CRED_FILE, "r", encoding="utf-8") as f:
    cred_data = json.load(f)
project_id = cred_data.get("project_id")

print(f"Iniciando configuración de Firebase Storage para el proyecto: {project_id}")

# Autenticar con GCS nativo
client = gcs.Client.from_service_account_json(CRED_FILE)

# 1. Definir nombres posibles del bucket
bucket_names = [
    f"{project_id}.appspot.com",
    f"{project_id}.firebasestorage.app",
    f"digestoag-cb08c.appspot.com",
    f"digestoag-cb08c.firebasestorage.app"
]

bucket_activo = None

# Buscar si ya existe alguno de los buckets
print("Comprobando existencia de los buckets de almacenamiento...")
for name in bucket_names:
    try:
        bucket = client.get_bucket(name)
        print(f" -> ¡Bucket existente detectado!: {name}")
        bucket_activo = bucket
        break
    except Exception:
        pass

# 2. Si no existe, crear el bucket por defecto
if not bucket_activo:
    default_name = f"{project_id}.appspot.com"
    print(f"\nNo se detectó ningún bucket activo. Creando nuevo bucket público: {default_name}...")
    try:
        # Crear bucket en ubicacion multiregion de US para plan gratuito
        bucket_activo = client.create_bucket(default_name, location="US")
        print(f" -> ¡Bucket creado con éxito en Google Cloud!")
    except Exception as e:
        print(f" -> Error al crear el bucket por defecto: {e}")
        
        # Intentar crear con la extension moderna
        alt_name = f"{project_id}.firebasestorage.app"
        print(f"Intentando crear bucket alternativo: {alt_name}...")
        try:
            bucket_activo = client.create_bucket(alt_name, location="US")
            print(f" -> ¡Bucket alternativo creado con éxito!")
        except Exception as e_alt:
            print(f" -> Error crítico: No se pudo crear ningún bucket de almacenamiento. ({e_alt})")
            print("Por favor, active Cloud Storage manualmente en la consola web de Firebase.")
            sys.exit(1)

# 3. Configurar politicas de lectura pública en el bucket
print("\nConfigurando políticas del bucket para descarga pública y anónima...")
try:
    # Obtener la politica de accesos del bucket
    policy = bucket_activo.get_iam_policy(requested_policy_version=3)
    
    # Agregar permiso de lectura publica a cualquier usuario de internet
    policy.bindings.append({
        "role": "roles/storage.objectViewer",
        "members": {"allUsers"}
    })
    
    bucket_activo.set_iam_policy(policy)
    print(" -> ¡Políticas de lectura pública configuradas exitosamente!")
    
    # Escribir el bucket activo en un archivo de configuracion local
    with open("output/bucket_activo.txt", "w", encoding="utf-8") as f_b:
        f_b.write(bucket_activo.name)
        
except Exception as e:
    print(f" -> Advertencia al configurar IAM políticas (es probable que use control de accesos uniforme): {e}")
    print("El cargador configurará los accesos individuales a nivel de archivo (make_public=True).")
    with open("output/bucket_activo.txt", "w", encoding="utf-8") as f_b:
        f_b.write(bucket_activo.name)

print("\n¡Configuración de Storage completada!")
