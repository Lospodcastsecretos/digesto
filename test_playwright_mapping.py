import time
import json
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"
FILE_NAME = "86-8593.pdf"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    # 1. Cargar el sitio para inicializar cookies y sesion legitima
    print("Iniciando navegador...")
    page.goto(f"{SITE_URL}/#/Index", wait_until="networkidle")
    time.sleep(3)
    
    # 2. Consultar la API del mapeo usando fetch() dentro del navegador
    print(f"Llamando a la API de mapeo en el navegador para: {FILE_NAME}...")
    
    # Definir el script JS por separado para evitar problemas de f-string
    js_code = """
        async (filename) => {
            try {
                const cookies = document.cookie.split(';');
                let xsrfToken = '';
                for (const cookie of cookies) {
                    const [name, value] = cookie.trim().split('=');
                    if (name === 'XSRF-TOKEN') {
                        xsrfToken = decodeURIComponent(value);
                        break;
                    }
                }
                
                const response = await fetch('/api/documentos/' + filename, {
                    method: 'GET',
                    headers: {
                        'Accept': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-XSRF-TOKEN': xsrfToken
                    },
                    credentials: 'same-origin'
                });
                
                const status = response.status;
                const data = await response.json();
                return { success: true, status: status, data: data };
            } catch (e) {
                return { success: false, error: e.message };
            }
        }
    """
    
    js_result = page.evaluate(js_code, FILE_NAME)
    
    print(f"Resultado en navegador (HTTP {js_result.get('status')}):")
    print(json.dumps(js_result, indent=2))
    
    browser.close()
