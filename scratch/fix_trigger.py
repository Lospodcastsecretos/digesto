import os
import requests
import time

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
    r = requests.post(pipeline_url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

print("1. Eliminando trigger ineficiente normas_au...")
try:
    res = turso_query("DROP TRIGGER IF EXISTS normas_au")
    print("   OK: Trigger normas_au eliminado con exito.")
except Exception as e:
    print(f"   ERROR: Fallo al eliminar trigger: {e}")

print("2. Creando trigger optimizado normas_au (solo se activa al cambiar texto/titulo)...")
try:
    sql_trigger = """
    CREATE TRIGGER normas_au AFTER UPDATE OF numero, titulo, resumen, texto_completo ON normas 
    BEGIN
        DELETE FROM normas_fts WHERE id = old.id;
        INSERT INTO normas_fts(id, numero, titulo, resumen, texto_completo)
        VALUES (new.id, new.numero, new.titulo, new.resumen, new.texto_completo);
    END;
    """
    res = turso_query(sql_trigger)
    print("   OK: Trigger optimizado normas_au creado con exito.")
except Exception as e:
    print(f"   ERROR: Fallo al crear trigger: {e}")

print("3. Probando UPDATE rapido de prueba (resumen_ia, que no activa el trigger FTS)...")
try:
    res = turso_query("UPDATE normas SET resumen_ia = resumen_ia WHERE id = (SELECT id FROM normas LIMIT 1)")
    print("   OK: EXITO! El UPDATE se ejecuto de inmediato sin Timeouts.")
except Exception as e:
    print(f"   ERROR: El UPDATE de resumen_ia sigue fallando: {e}")
