import time
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    
    # Monitorear requests salientes
    requests_log = []
    def interceptar_request(request):
        if "download" in request.url or "export" in request.url or "doc/" in request.url or "drive" in request.url:
            requests_log.append({
                "url": request.url,
                "method": request.method,
                "headers": request.headers,
            })
            print(f"\n[Request Interceptado] {request.method} -> {request.url}")
            
    page.on("request", interceptar_request)
    
    # Navegamos al detalle de la norma 8593 que tiene PDF
    print("Navegando al detalle de la norma 8593...")
    page.goto(f"{SITE_URL}/#/detalles/8593", wait_until="networkidle")
    time.sleep(3)
    
    # Intentar hacer clic en el botón de PDF o descarga
    print("Buscando el boton de descarga...")
    
    # Imprimir todos los botones visibles para elegir el correcto
    buttons = page.query_selector_all("button, a, .v-btn")
    for btn in buttons:
        text = btn.inner_text().strip()
        if text:
            print(f"  - Elemento visible: '{text}'")
            
    # Intentar hacer clic en elementos que contengan "PDF" o "Descargar"
    descarga_clickeada = False
    for btn in buttons:
        text = btn.inner_text().strip().lower()
        if "pdf" in text or "descargar" in text or "planilla" in text or "digitalizado" in text:
            print(f"Haciendo clic en: '{btn.inner_text().strip()}'")
            
            # Monitorear evento de descarga en Playwright
            with page.expect_download(timeout=10000) as download_info:
                try:
                    btn.click()
                    download = download_info.value
                    print(f"¡Descarga capturada!")
                    print(f"  - URL sugerida: {download.url}")
                    print(f"  - Archivo sugerido: {download.suggested_filename}")
                    descarga_clickeada = True
                    break
                except Exception as e:
                    print(f"  -> Error al hacer clic o esperar descarga: {e}")
                    
    if not descarga_clickeada:
        print("\nNo se pudo disparar el evento de descarga estándar. Intentando con la API desde consola...")
        # Evaluar qué pasa si ejecutamos descargarArchivo desde la consola o inspeccionamos los eventos
        # Buscaremos enlaces ocultos o enlaces dinámicos
        
    time.sleep(3)
    
    print("\nLogs de Peticiones del Navegador:")
    for req in requests_log:
        print(f"\nURL: {req['url']}")
        print(f"Headers: {req['headers']}")
        
    browser.close()
