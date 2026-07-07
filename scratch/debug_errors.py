import requests
import json

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

# Probemos buscar y actualizar la Ordenanza 6848 (ID 6238 o similar)
# que falló en el lote.
payload_find = {
    "requests": [
        {"type": "execute", "stmt": {"sql": "SELECT id, tipo_nombre, numero FROM normas WHERE numero = '6848'", "args": []}},
        {"type": "close"}
    ]
}

# Busquemos
r_find = requests.post(f"{TURSO_URL}/v2/pipeline", headers=headers, json=payload_find)
print("FIND RESPONSE:", r_find.text)

# Intentemos un update
payload_up = {
    "requests": [
        {"type": "execute", "stmt": {
            "sql": "UPDATE normas SET texto_completo = ? WHERE id = (SELECT id FROM normas WHERE numero = '6848' LIMIT 1)",
            "args": [{"type": "text", "value": "Texto Prueba 6848"}]
        }},
        {"type": "close"}
    ]
}
r_up = requests.post(f"{TURSO_URL}/v2/pipeline", headers=headers, json=payload_up)
print("UPDATE RESPONSE:", r_up.text)