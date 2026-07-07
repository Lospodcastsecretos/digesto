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
    
    res_val = result["response"]["result"]
    cols = [c["name"] for c in res_val["cols"]]
    rows = []
    for r_val in res_val["rows"]:
        row_vals = [val["value"] if val else None for val in r_val]
        rows.append(dict(zip(cols, row_vals)))
    return rows

print("1. Creando / Asegurando índices en la tabla 'normas'...")
try:
    # 1. Crear índice de número y tipo
    run_query("CREATE INDEX IF NOT EXISTS idx_normas_num_tipo ON normas(numero, tipo_nombre)")
    # 2. Crear índice parcial de texto_completo nulo
    run_query("CREATE INDEX IF NOT EXISTS idx_normas_texto_null ON normas(numero, tipo_nombre) WHERE texto_completo IS NULL")
    print("Índices creados con éxito (o ya existentes).")
except Exception as e:
    print(f"Error al asegurar índices: {e}")
    sys.exit(1)

print("\n2. Generando informe de índices en Turso Cloud...")
try:
    indexes = run_query("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND tbl_name IN ('normas', 'normas_fts')")
    
    print("-" * 80)
    print(f"{'ÍNDICE':<25} | {'TABLA':<12} | {'DEFINICIÓN':<40}")
    print("-" * 80)
    for idx in indexes:
        name = idx.get("name") or "Desconocido"
        tbl = idx.get("tbl_name") or "Desconocido"
        definition = idx.get("sql") or "Implícito (automático)"
        print(f"{name:<25} | {tbl:<12} | {definition:<40}")
    print("-" * 80)
except Exception as e:
    print(f"Error al obtener el informe: {e}")
