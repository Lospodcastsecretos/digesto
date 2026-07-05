import requests

SITE_URL = "https://digestoaltagracia.com.ar"
API_KEY = "$2y$10$VXghLWoHpSnWbrhXk.p0y.BRuUHI3RZ7pAT1QC4F8T3.7693PWVCy"
DRIVE_ID = "1Y3bzmRw1iRNQalPjJ_jflNIPTYrXFK8O"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "x-requested-with": "XMLHttpRequest",
    "api-key": API_KEY,
    "referer": f"{SITE_URL}/"
}

for endpoint in ["export", "download"]:
    url = f"{SITE_URL}/{endpoint}/{DRIVE_ID}"
    print(f"\nProbando: {url}")
    try:
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=15)
        print(f"HTTP Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")
        print(f"Content-Length: {resp.headers.get('Content-Length')}")
        print(f"Contenido (50 primeros bytes): {resp.content[:50]}")
    except Exception as e:
        print(f"Error: {e}")
