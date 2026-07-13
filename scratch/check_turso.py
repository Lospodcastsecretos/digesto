import os
import requests

if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key, val.strip('"\''))

TURSO_URL = os.environ.get("TURSO_URL").replace("libsql://", "https://").replace("http://", "https://")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN")
pipeline_url = f"{TURSO_URL}/v2/pipeline"
headers = {"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"}

def turso_query(sql, args=[]):
    payload = {"requests": [{"type": "execute", "stmt": {"sql": sql, "args": args}}, {"type": "close"}]}
    try:
        r = requests.post(pipeline_url, headers=headers, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"HTTP Error {r.status_code}: {r.text}")
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"Network/HTTP Exception: {e}")
        raise e

print("Verificando si la tabla 'semantic_cache' ya existe en Turso...")
try:
    res = turso_query("SELECT name FROM sqlite_master WHERE type='table' AND name='semantic_cache'")
    rows = res["results"][0]["response"]["result"]["rows"]
    if len(rows) > 0:
        print("INFO: La tabla 'semantic_cache' ya existe en la base de datos.")
    else:
        print("INFO: La tabla 'semantic_cache' NO existe en la base de datos.")
except Exception as e:
    print(f"ERROR al consultar la existencia de la tabla: {e}")

print("Intentando liberar bloqueos enviando un ROLLBACK explícito...")
try:
    res = turso_query("ROLLBACK")
    print(f"Respuesta de ROLLBACK: {res}")
except Exception as e:
    print(f"ROLLBACK rechazado (esperable si no hay transaccion activa localmente): {e}")

print("Intentando escribir en Turso (UPDATE dummy)...")
try:
    res = turso_query("UPDATE normas SET titulo = titulo WHERE id = (SELECT id FROM normas LIMIT 1)")
    if res["results"][0]["type"] == "error":
        print(f"ERROR: Fallo el UPDATE dummy: {res['results'][0]['error']['message']}")
    else:
        print(f"OK: Turso responde a UPDATEs. La base de datos NO esta bloqueada.")
except Exception as e:
    print(f"ERROR: Fallo el UPDATE dummy por Timeout: {e}")
    print("CONCLUSION: La tabla 'normas' esta bloqueada por una transaccion colgada (Database Locked).")
