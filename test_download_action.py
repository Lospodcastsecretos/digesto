import time
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    # Navegamos directamente al detalle del documento 14346
    print("Navegando al detalle...")
    page.goto(f"{SITE_URL}/#/detalles/14346", wait_until="networkidle")
    time.sleep(3)
    
    # Capturar el HTML del contenedor de detalles para ver que botones hay
    print("Analizando elementos de la pagina de detalles...")
    
    # Intentar buscar todos los enlaces de la pagina
    links = page.query_selector_all("a")
    print(f"\nEnlaces encontrados ({len(links)}):")
    for link in links:
        text = link.inner_text().strip()
        href = link.get_attribute("href") or ""
        if href:
            print(f"  - Texto: '{text}' | Href: '{href}'")
            
    # Intentar buscar botones
    buttons = page.query_selector_all("button, .v-btn")
    print(f"\nBotones encontrados ({len(buttons)}):")
    for btn in buttons:
        text = btn.inner_text().strip()
        print(f"  - Boton: '{text}'")
        
    # Obtener el HTML completo de la app para ver si hay iframes u otros elementos ocultos
    app_html = page.locator("#app").inner_html()
    print("\nEstructura HTML simplificada del contenedor de detalles:")
    # Imprimir lineas que contengan enlaces o palabras clave como archivo, descargar, pdf, docx, drive
    for line in app_html.split("\n"):
        if any(kw in line.lower() for kw in ["pdf", "docx", "drive", "descargar", "archivo", "href"]):
            print(line.strip()[:150])

    browser.close()
