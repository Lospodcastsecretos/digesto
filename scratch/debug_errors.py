import requests
import json

TURSO_URL = "https://digesto-lospodcastsecretos.aws-us-west-2.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODMyODgxMjQsImlkIjoiMDE5ZjM0NDAtN2UwMS03OTljLWFlOTItODBiMDJmNmVhMjdlIiwia2lkIjoiZ0JFblIyNVR6dEEwaHVWWXljOS03cnRzYThUaGRnbmFEd1ZHSXJrR3FPYyIsInJpZCI6ImE1MGUwMDBmLTQ4ZTgtNDg1ZS04MmM0LTEzNGIxYTA4MmJhYSJ9.ev1b_OISV20t8e9brtO7O4oU9bGnrPYum1LTbBiVng-gaPC2YiUsHzFe-ok2aXmVePtRNYtAmKpb0ntWL6xSCA"

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
