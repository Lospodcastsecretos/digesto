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

print("Calculando avance global de vectorizacion...")
try:
    res_total = turso_query("SELECT count(*) FROM normas")
    total = res_total["results"][0]["response"]["result"]["rows"][0][0]["value"]
    
    res_vect = turso_query("SELECT count(*) FROM normas WHERE embedding IS NOT NULL")
    vect = res_vect["results"][0]["response"]["result"]["rows"][0][0]["value"]
    
    porcentaje = (vect / total) * 100 if total > 0 else 0
    print(f"PROGRESS_DATA: Total: {total}, Vectorizadas: {vect}, Porcentaje: {porcentaje:.2f}%")
except Exception as e:
    print(f"ERROR: Fallo al calcular avance: {e}")

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
