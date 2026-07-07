import requests

import os
# Cargar .env manualmente si existe
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                parts = line.strip().split("=", 1)
                if len(parts) == 2:
                    os.environ[parts[0].strip()] = parts[1].strip().replace('"', '').replace("'", "")


TURSO_URL = os.environ.get('TURSO_URL')
TURSO_TOKEN = os.environ.get('TURSO_TOKEN')

headers = {
    "Authorization": f"Bearer {TURSO_TOKEN}",
    "Content-Type": "application/json"
}

statements = [
    "DROP TRIGGER IF EXISTS normas_au",
    "DROP TRIGGER IF EXISTS normas_ad",
    """
    CREATE TRIGGER normas_au AFTER UPDATE ON normas BEGIN
        DELETE FROM normas_fts WHERE id = old.id;
        INSERT INTO normas_fts(id, numero, titulo, resumen, texto_completo)
        VALUES (new.id, new.numero, new.titulo, new.resumen, new.texto_completo);
    END
    """,
    """
    CREATE TRIGGER normas_ad AFTER DELETE ON normas BEGIN
        DELETE FROM normas_fts WHERE id = old.id;
    END
    """
]

requests_payload = [{"type": "execute", "stmt": {"sql": stmt, "args": []}} for stmt in statements]
requests_payload.append({"type": "close"})

payload = {
    "requests": requests_payload
}

r = requests.post(f"{TURSO_URL}/v2/pipeline", headers=headers, json=payload)
print("FIX TRIGGERS RESPONSE:", r.text)