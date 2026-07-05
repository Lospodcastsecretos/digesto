import requests
from urllib.parse import unquote

SITE_URL = "https://digestoaltagracia.com.ar"
DOWNLOAD_URL = "https://digestoaltagracia.com.ar/download/14346"

# Iniciar sesion para obtener cookies
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://digestoaltagracia.com.ar/",
})

print("Estableciendo sesion...")
resp_init = session.get(SITE_URL, timeout=10)
xsrf_cookie = session.cookies.get("XSRF-TOKEN")
if xsrf_cookie:
    session.headers["X-XSRF-TOKEN"] = unquote(xsrf_cookie)
    print("X-XSRF-TOKEN seteado.")

print(f"Intentando descargar desde {DOWNLOAD_URL}...")
# Deshabilitar redirecciones para ver si apunta a Google Drive
resp = session.get(DOWNLOAD_URL, allow_redirects=False, timeout=15)

print(f"HTTP Status: {resp.status_code}")
print("Headers recibidos:")
for k, v in resp.headers.items():
    print(f"  {k}: {v}")

# Si hay redireccion (301/302)
if resp.status_code in (301, 302):
    print(f"\n¡Redirección encontrada! Location: {resp.headers.get('Location')}")
else:
    print(f"\nContenido de respuesta (primeros 500 bytes):")
    print(resp.content[:500])
