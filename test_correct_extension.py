import requests
import json
from urllib.parse import unquote

SITE_URL = "https://digestoaltagracia.com.ar"

# 1. Encontrar un documento con extensión PDF
pdf_doc_id = None
pdf_doc_name = None

try:
    with open("output/digesto_completo_20260705_000141.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        for doc in data:
            archivo = doc.get("archivo_pdf") or ""
            if archivo.lower().endswith(".pdf"):
                pdf_doc_id = doc.get("id")
                pdf_doc_name = archivo
                break
except Exception as e:
    print(f"Error cargando JSON: {e}")

print(f"Documento PDF encontrado para pruebas: ID={pdf_doc_id}, Nombre={pdf_doc_name}")

# Iniciar sesion
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://digestoaltagracia.com.ar/",
})

resp_init = session.get(SITE_URL, timeout=10)
xsrf_cookie = session.cookies.get("XSRF-TOKEN")
if xsrf_cookie:
    session.headers["X-XSRF-TOKEN"] = unquote(xsrf_cookie)

# Probar export / doc para el docx (ID 14346)
print("\n--- Probando endpoints para DOCX (ID 14346) ---")
for endpoint in ["export", "doc"]:
    url = f"{SITE_URL}/{endpoint}/14346"
    print(f"Probando: {url}")
    resp = session.get(url, allow_redirects=False, timeout=10)
    print(f"HTTP Status: {resp.status_code}")
    print(f"Location Header: {resp.headers.get('Location')}")
    if resp.status_code == 200:
        print(f"Cuerpo (50 primeros bytes): {resp.content[:50]}")

# Probar download para el PDF (si encontramos uno)
if pdf_doc_id:
    print(f"\n--- Probando endpoint para PDF (ID {pdf_doc_id}) ---")
    url = f"{SITE_URL}/download/{pdf_doc_id}"
    print(f"Probando: {url}")
    resp = session.get(url, allow_redirects=False, timeout=10)
    print(f"HTTP Status: {resp.status_code}")
    print(f"Location Header: {resp.headers.get('Location')}")
    if resp.status_code == 200:
        print(f"Cuerpo (50 primeros bytes): {resp.content[:50]}")
