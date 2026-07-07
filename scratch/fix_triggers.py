import requests

TURSO_URL = "https://digesto-lospodcastsecretos.aws-us-west-2.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODMyODgxMjQsImlkIjoiMDE5ZjM0NDAtN2UwMS03OTljLWFlOTItODBiMDJmNmVhMjdlIiwia2lkIjoiZ0JFblIyNVR6dEEwaHVWWXljOS03cnRzYThUaGRnbmFEd1ZHSXJrR3FPYyIsInJpZCI6ImE1MGUwMDBmLTQ4ZTgtNDg1ZS04MmM0LTEzNGIxYTA4MmJhYSJ9.ev1b_OISV20t8e9brtO7O4oU9bGnrPYum1LTbBiVng-gaPC2YiUsHzFe-ok2aXmVePtRNYtAmKpb0ntWL6xSCA"

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
