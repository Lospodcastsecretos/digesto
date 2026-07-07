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

payload = {
    "requests": [
        {"type": "execute", "stmt": {"sql": "CREATE INDEX IF NOT EXISTS idx_normas_texto_null ON normas(numero, tipo_nombre) WHERE texto_completo IS NULL", "args": []}},
        {"type": "close"}
    ]
}

r = requests.post(f"{TURSO_URL}/v2/pipeline", headers=headers, json=payload)
print("CREATE PARTIAL INDEX RESPONSE:", r.text)