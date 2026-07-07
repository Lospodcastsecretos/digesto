import os
import requests
import sys

# Cargar .env manualmente si existe
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                parts = line.strip().split("=", 1)
                if len(parts) == 2:
                    os.environ[parts[0].strip()] = parts[1].strip().replace('"', '').replace("'", "")

TURSO_URL = os.environ.get("TURSO_URL")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN")

if not TURSO_URL or not TURSO_TOKEN:
    print("Error: Se requieren las variables de entorno TURSO_URL y TURSO_TOKEN.")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {TURSO_TOKEN}",
    "Content-Type": "application/json"
}

def run_query(sql):
    url = f"{TURSO_URL}/v2/pipeline"
    payload = {
      "requests": [
        {"type": "execute", "stmt": {"sql": sql, "args": []}},
        {"type": "close"}
      ]
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if not r.ok:
        raise Exception(f"HTTP {r.status_code}: {r.text}")
    data = r.json()
    result = data["results"][0]
    if result["type"] == "error":
        raise Exception(result["error"]["message"])
    print(f"Éxito: {sql[:50]}...")

try:
    print("Asegurando nuevos índices de categoría e invalidación...")
    run_query("CREATE INDEX IF NOT EXISTS idx_normas_categoria ON normas(categoria_nombre)")
    run_query("CREATE INDEX IF NOT EXISTS idx_normas_categoria_vigente ON normas(categoria_nombre, vigente)")
    run_query("CREATE INDEX IF NOT EXISTS idx_normas_sin_resumen_ia ON normas(id) WHERE resumen_ia IS NULL")
    print("Todos los nuevos índices están activos.")
except Exception as e:
    print(f"Error al asegurar índices: {e}")
    sys.exit(1)
