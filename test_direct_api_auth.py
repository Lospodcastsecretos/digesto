import requests
import json

SITE_URL = "https://digestoaltagracia.com.ar"
API_KEY = "$2y$10$VXghLWoHpSnWbrhXk.p0y.BRuUHI3RZ7pAT1QC4F8T3.7693PWVCy"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "x-requested-with": "XMLHttpRequest",
    "api-key": API_KEY,
    "referer": "https://digestoaltagracia.com.ar/"
}

# 1. Probar API de publicaciones
print("Probando API de publicaciones con la api-key...")
resp_pub = requests.get(f"{SITE_URL}/api/publicaciones?descripcion=a", headers=headers, timeout=10)
print(f"HTTP Status: {resp_pub.status_code}")
if resp_pub.status_code == 200:
    data = resp_pub.json()
    print(f"Éxito: {len(data.get('data', []))} registros recibidos.")
    
# 2. Probar API de mapeo de archivo a Drive ID para '86-8593.pdf'
print("\nProbando API de documentos para obtener ID de Drive...")
resp_doc = requests.get(f"{SITE_URL}/api/documentos/86-8593.pdf", headers=headers, timeout=10)
print(f"HTTP Status: {resp_doc.status_code}")
if resp_doc.status_code == 200:
    doc_data = resp_doc.json()
    print("Respuesta de la API de documentos:")
    print(json.dumps(doc_data, indent=2))
