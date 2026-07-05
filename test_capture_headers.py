import time
import json
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    requests_log = []
    def interceptar_request(request):
        if "/api/" in request.url:
            requests_log.append({
                "url": request.url,
                "method": request.method,
                "headers": request.headers
            })
            
    page.on("request", interceptar_request)
    
    print("Navegando a la norma 8593...")
    page.goto(f"{SITE_URL}/#/detalles/8593", wait_until="networkidle")
    time.sleep(5)
    
    print("\nPeticiones de API detectadas y sus cabeceras:")
    for req in requests_log:
        print(f"\n[{req['method']}] {req['url']}")
        print(json.dumps(req['headers'], indent=2))
        print("-" * 50)
        
    browser.close()
