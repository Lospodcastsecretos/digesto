import os
import sys
import requests

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Cargar .env
if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key, val.strip('"\''))

TURSO_URL = os.environ.get("TURSO_URL")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN")

if not TURSO_URL or not TURSO_TOKEN:
    print("Error: No se encontraron TURSO_URL o TURSO_TOKEN en el archivo .env")
    sys.exit(1)

clean_url = TURSO_URL.replace("libsql://", "https://").replace("http://", "https://")
pipeline_url = f"{clean_url}/v2/pipeline"

def ejecutar_sql(sql):
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": []}},
            {"type": "close"}
        ]
    }
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        r = requests.post(pipeline_url, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        res = r.json()
        
        if res["results"][0]["type"] == "error":
            print(f"❌ Error de Turso: {res['results'][0]['error']['message']}")
            return
            
        result = res["results"][0]["response"]["result"]
        print("✅ Comando SQL ejecutado con éxito.")
        if "affected_row_count" in result:
            print(f"   Filas afectadas: {result['affected_row_count']}")
            
        # Si devuelve filas (es un SELECT), imprimirlas
        if "cols" in result and result.get("rows"):
            cols = [c["name"] for c in result["cols"]]
            print(f"\nResultados ({len(result['rows'])} filas):")
            print(" | ".join(cols))
            print("-" * 40)
            for r_val in result["rows"]:
                vals = [str(v.get("value") if isinstance(v, dict) else v) for v in r_val]
                print(" | ".join(vals))
                
    except Exception as e:
        print(f"❌ Error de red o conexión: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scratch/ejecutar_sql.py \"TU CONSULTA SQL AQUÍ\"")
        sys.exit(1)
        
    query = sys.argv[1]
    print(f"Ejecutando SQL: {query}")
    ejecutar_sql(query)
