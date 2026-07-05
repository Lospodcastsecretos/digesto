"""
Scraper del Digesto Municipal de Alta Gracia
=============================================
Extrae ordenanzas, resoluciones, decretos y demás normativas
desde la API REST del sitio digestoaltagracia.com.ar

Estrategia:
  1. Llamada directa a la API REST (sin navegador, rápido y eficiente)
  2. Fallback con Playwright si la API falla (modo headless)

Requisitos:
  pip install requests pydantic
  pip install playwright  # Solo para fallback
  playwright install chromium  # Solo para fallback
"""

import json
import logging
import sys
import time
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import unquote

import requests
from pydantic import BaseModel, Field, ValidationError

# Fix Windows console encoding for Unicode characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("DigestoScraper")


# ==========================================
# 1. MODELOS DE DATOS (Pydantic)
# ==========================================

class Descriptor(BaseModel):
    """Descriptor temático de un documento."""
    id: Optional[int] = None
    nombre: Optional[str] = None


class Tipo(BaseModel):
    """Tipo de documento (Ordenanza, Resolución, Decreto, etc.)."""
    id: Optional[int] = None
    nombre: Optional[str] = None


class Categoria(BaseModel):
    """Categoría temática del documento."""
    id: Optional[int] = None
    nombre: Optional[str] = None


class DocumentoDigesto(BaseModel):
    """Modelo completo de un documento del Digesto."""
    id: int = Field(description="ID interno del documento")
    numero: Optional[str] = Field(default=None, description="Número de la norma")
    titulo: Optional[str] = Field(default=None, description="Título o descripción corta")
    tipo: Optional[str] = Field(default=None, description="Tipo: Ordenanza, Resolución, Decreto, etc.")
    tipo_id: Optional[int] = None
    categoria: Optional[str] = Field(default=None, description="Categoría temática")
    categoria_id: Optional[int] = None
    fecha_sancion: Optional[str] = Field(default=None, description="Fecha de sanción")
    fecha_promulgacion: Optional[str] = Field(default=None, description="Fecha de promulgación")
    vigente: Optional[bool] = Field(default=None, description="Si la norma está vigente")
    descriptores: Optional[List[str]] = Field(default_factory=list, description="Descriptores temáticos")
    resumen: Optional[str] = Field(default=None, description="Resumen del documento")
    texto: Optional[str] = Field(default=None, description="Texto completo de la norma")
    archivo_pdf: Optional[str] = Field(default=None, description="URL del archivo PDF")
    url_detalle: Optional[str] = Field(default=None, description="URL de la página de detalle")


# ==========================================
# 2. MOTOR DEL SCRAPER
# ==========================================

class DigestoScraper:
    """Scraper del Digesto Municipal de Alta Gracia."""

    # Endpoints descubiertos del análisis del build.js
    API_BASE = "https://digestoaltagracia.com.ar/api"
    ENDPOINTS = {
        "publicaciones": f"{API_BASE}/publicaciones",
        "documentos": f"{API_BASE}/documentos",
        "categorias": f"{API_BASE}/categorias",
        "tipos": f"{API_BASE}/tipos",
        "descriptores": f"{API_BASE}/descriptores",
    }
    SITE_URL = "https://digestoaltagracia.com.ar"

    # Headers que simula el frontend Vue.js
    HEADERS = {
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://digestoaltagracia.com.ar/",
        "Origin": "https://digestoaltagracia.com.ar",
    }

    def __init__(self, output_dir: str = "output"):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.datos_extraidos: List[Dict[str, Any]] = []
        self.catalogo_tipos: Dict[int, str] = {}
        self.catalogo_categorias: Dict[int, str] = {}
        self.output_dir = output_dir
        self._csrf_initialized = False
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------
    # Helpers
    # ------------------------------------------
    def _init_csrf(self):
        """Obtiene cookies de sesion y extrae el token CSRF de Laravel."""
        if self._csrf_initialized:
            return
        logger.info("Obteniendo token CSRF de Laravel...")
        try:
            resp = self.session.get(self.SITE_URL, timeout=15)
            logger.info(f"  -> Pagina principal: HTTP {resp.status_code}")
            logger.info(f"  -> Cookies obtenidas: {list(self.session.cookies.keys())}")
            self._apply_csrf_token()
            self._csrf_initialized = True
        except Exception as e:
            logger.warning(f"  -> Error al cargar pagina principal: {e}")

    def _apply_csrf_token(self):
        """Extrae XSRF-TOKEN de las cookies y lo setea como header X-XSRF-TOKEN.
        Laravel espera que el valor del cookie (URL-encoded) se envie URL-decoded
        en el header X-XSRF-TOKEN."""
        xsrf_cookie = self.session.cookies.get("XSRF-TOKEN")
        if xsrf_cookie:
            # Laravel URL-encodes el token en la cookie, hay que decodificarlo
            decoded_token = unquote(xsrf_cookie)
            self.session.headers["X-XSRF-TOKEN"] = decoded_token
            logger.info(f"  -> Token CSRF aplicado: {decoded_token[:20]}...")
        else:
            logger.warning("  -> No se encontro cookie XSRF-TOKEN")

    def _get_api(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Hace una peticion GET a la API con reintentos y CSRF token."""
        url = self.ENDPOINTS.get(endpoint, endpoint)
        for intento in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code in (401, 419):  # 419 = CSRF token mismatch
                    logger.warning(f"HTTP {resp.status_code} en {url}. Renovando sesion CSRF... (intento {intento+1}/3)")
                    # Renovar la sesion y el token CSRF
                    self._csrf_initialized = False
                    self._init_csrf()
                    time.sleep(1)
                    continue
                else:
                    logger.warning(f"HTTP {resp.status_code} en {url} (intento {intento+1}/3)")
            except requests.RequestException as e:
                logger.error(f"Error de red en {url}: {e} (intento {intento+1}/3)")
            time.sleep(2 * (intento + 1))
        return None

    def _normalizar_documento(self, raw: dict) -> Optional[Dict[str, Any]]:
        """Normaliza y valida un registro crudo de la API."""
        try:
            # Mapeo flexible de campos (la API puede usar diferentes nombres)
            tipo_id = raw.get("tipo_id") or raw.get("tipoId") or raw.get("tipo", {}).get("id") if isinstance(raw.get("tipo"), dict) else None
            cat_id = raw.get("categoria_id") or raw.get("categoriaId") or raw.get("categoria", {}).get("id") if isinstance(raw.get("categoria"), dict) else None

            tipo_nombre = None
            if isinstance(raw.get("tipo"), dict):
                tipo_nombre = raw["tipo"].get("nombre")
            elif isinstance(raw.get("tipo"), str):
                tipo_nombre = raw["tipo"]
            elif tipo_id and tipo_id in self.catalogo_tipos:
                tipo_nombre = self.catalogo_tipos[tipo_id]

            cat_nombre = None
            if isinstance(raw.get("categoria"), dict):
                cat_nombre = raw["categoria"].get("nombre")
            elif isinstance(raw.get("categoria"), str):
                cat_nombre = raw["categoria"]
            elif cat_id and cat_id in self.catalogo_categorias:
                cat_nombre = self.catalogo_categorias[cat_id]

            # Extraer descriptores
            descriptores_raw = raw.get("descriptores", [])
            descriptores = []
            if isinstance(descriptores_raw, list):
                for d in descriptores_raw:
                    if isinstance(d, dict):
                        descriptores.append(d.get("nombre", str(d)))
                    elif isinstance(d, str):
                        descriptores.append(d)

            doc_id = raw.get("id", 0)
            doc = DocumentoDigesto(
                id=doc_id,
                numero=str(raw.get("numero", "")) or None,
                titulo=raw.get("titulo") or raw.get("descripcion") or raw.get("nombre") or None,
                tipo=tipo_nombre,
                tipo_id=tipo_id if isinstance(tipo_id, int) else None,
                categoria=cat_nombre,
                categoria_id=cat_id if isinstance(cat_id, int) else None,
                fecha_sancion=raw.get("fecha_sancion") or raw.get("fechaSancion") or raw.get("fecha") or None,
                fecha_promulgacion=raw.get("fecha_promulgacion") or raw.get("fechaPromulgacion") or None,
                vigente=raw.get("vigente") if isinstance(raw.get("vigente"), bool) else None,
                descriptores=descriptores,
                resumen=raw.get("resumen") or raw.get("sintesis") or None,
                texto=raw.get("texto") or None,
                archivo_pdf=raw.get("archivo") or raw.get("pdf") or raw.get("archivo_pdf") or None,
                url_detalle=f"{self.SITE_URL}/#/detalles/{doc_id}" if doc_id else None,
            )
            return doc.model_dump()

        except ValidationError as e:
            logger.error(f"Error de validación: {e.errors()}")
            return None
        except Exception as e:
            logger.error(f"Error normalizando documento: {e}")
            return None

    # ------------------------------------------
    # Carga de catálogos auxiliares
    # ------------------------------------------
    def _cargar_catalogos(self):
        """Carga los catálogos de tipos y categorías para enriquecer los datos."""
        logger.info("Cargando catálogo de tipos de documento...")
        tipos = self._get_api("tipos")
        if tipos:
            data = tipos.get("data", tipos) if isinstance(tipos, dict) else tipos
            if isinstance(data, list):
                for t in data:
                    if isinstance(t, dict) and "id" in t:
                        self.catalogo_tipos[t["id"]] = t.get("nombre", "")
                logger.info(f"  → {len(self.catalogo_tipos)} tipos cargados")
            else:
                logger.warning(f"  → Formato inesperado de tipos: {type(data)}")
        else:
            logger.warning("  → No se pudieron cargar los tipos")

        logger.info("Cargando catálogo de categorías...")
        categorias = self._get_api("categorias")
        if categorias:
            data = categorias.get("data", categorias) if isinstance(categorias, dict) else categorias
            if isinstance(data, list):
                for c in data:
                    if isinstance(c, dict) and "id" in c:
                        self.catalogo_categorias[c["id"]] = c.get("nombre", "")
                logger.info(f"  → {len(self.catalogo_categorias)} categorías cargadas")
            else:
                logger.warning(f"  → Formato inesperado de categorías: {type(data)}")
        else:
            logger.warning("  → No se pudieron cargar las categorías")

    # ------------------------------------------
    # Estrategia 1: API REST directa
    # ------------------------------------------
    def _scrape_via_api(self) -> bool:
        """Intenta extraer todos los documentos usando la API REST."""
        logger.info("=" * 60)
        logger.info("ESTRATEGIA 1: Extracción directa por API REST")
        logger.info("=" * 60)

        # Obtener cookies de sesion y token CSRF
        self._init_csrf()

        # Cargar catálogos auxiliares
        self._cargar_catalogos()

        # Buscar TODAS las publicaciones (búsqueda vacía = todo)
        logger.info("\nExtrayendo publicaciones...")

        # Intentar primero con el endpoint de publicaciones (búsqueda)
        for endpoint in ["publicaciones", "documentos"]:
            logger.info(f"  Probando endpoint: /api/{endpoint}")

            # La búsqueda vacía o con parámetros mínimos debería devolver todo
            params_opciones = [
                {"descripcion": ""},  # Búsqueda vacía
                {"vigente": 1, "novigente": 1},  # Todo vigente y no vigente
                {},  # Sin parámetros
            ]

            for params in params_opciones:
                resultado = self._get_api(endpoint, params=params)
                if resultado:
                    # Extraer la lista de datos
                    if isinstance(resultado, dict):
                        data = resultado.get("data", [])
                        if not data and "results" in resultado:
                            data = resultado["results"]
                        if not data:
                            # Quizás el resultado es directamente la lista
                            data = resultado if isinstance(resultado, list) else []
                    elif isinstance(resultado, list):
                        data = resultado
                    else:
                        data = []

                    if data and len(data) > 0:
                        logger.info(f"  → ¡Éxito! {len(data)} registros encontrados con /api/{endpoint}")
                        logger.info(f"  → Muestra del primer registro: {json.dumps(data[0], ensure_ascii=False, indent=2)[:500]}")

                        # Normalizar cada documento
                        for raw in data:
                            doc = self._normalizar_documento(raw)
                            if doc:
                                self.datos_extraidos.append(doc)

                        logger.info(f"  → {len(self.datos_extraidos)} documentos validados exitosamente")
                        return True
                    else:
                        logger.info(f"  → Respuesta vacía con params {params}")

        logger.warning("La API REST no devolvió resultados.")
        return False

    # ------------------------------------------
    # Estrategia 2: Playwright (navegador real)
    # ------------------------------------------
    def _scrape_via_playwright(self) -> bool:
        """Usa Playwright con un navegador real para interceptar la API."""
        logger.info("=" * 60)
        logger.info("ESTRATEGIA 2: Extraccion con Playwright (navegador real)")
        logger.info("=" * 60)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright no instalado: pip install playwright && playwright install chromium")
            return False

        api_responses = []

        def interceptar_respuesta(response):
            """Captura TODAS las respuestas de la API."""
            if "/api/" in response.url:
                try:
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type:
                        body = response.json()
                        api_responses.append({
                            "url": response.url,
                            "status": response.status,
                            "data": body
                        })
                        data_preview = str(body)[:120] if body else "vacio"
                        logger.info(f"  -> [{response.status}] {response.url} => {data_preview}")
                except Exception as e:
                    logger.debug(f"  -> No parseable: {response.url} ({e})")

        with sync_playwright() as p:
            # Intentar modo headed primero (evita reCAPTCHA v3 bot detection)
            try:
                browser = p.chromium.launch(headless=False, args=["--window-size=1280,800"])
                logger.info("  -> Navegador lanzado en modo HEADED")
            except Exception:
                browser = p.chromium.launch(headless=True)
                logger.info("  -> Navegador lanzado en modo headless")

            context = browser.new_context(
                user_agent=self.HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 800}
            )

            # Stealth
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['es-AR', 'es', 'en-US', 'en']
                });
            """)

            page = context.new_page()
            page.on("response", interceptar_respuesta)

            # ---- Paso 1: Cargar la SPA ----
            logger.info("Cargando sitio web...")
            page.goto(f"{self.SITE_URL}/#/Index", wait_until="networkidle", timeout=30000)
            time.sleep(3)
            logger.info(f"  -> Titulo: {page.title()}")

            # ---- Guardar datos de catalogos interceptados (status 201) ----
            for resp in api_responses:
                if resp["status"] in (200, 201):
                    url = resp["url"]
                    data_raw = resp["data"]
                    data = data_raw.get("data", data_raw) if isinstance(data_raw, dict) else data_raw
                    if isinstance(data, list):
                        if "categorias" in url:
                            for c in data:
                                if isinstance(c, dict) and "id" in c:
                                    self.catalogo_categorias[c["id"]] = c.get("nombre", "")
                            logger.info(f"  -> {len(self.catalogo_categorias)} categorias cargadas")
                        elif "tipos" in url:
                            for t in data:
                                if isinstance(t, dict) and "id" in t:
                                    self.catalogo_tipos[t["id"]] = t.get("nombre", "")
                            logger.info(f"  -> {len(self.catalogo_tipos)} tipos cargados")

            # ---- Paso 2: Buscar usando la interaccion del Vue.js ----
            logger.info("\nEjecutando busqueda interactiva...")

            # Simular interaccion humana: tipo texto caracter a caracter
            try:
                search_input = page.wait_for_selector(
                    'input[type="text"]', timeout=5000
                )
                if search_input:
                    search_input.click()
                    time.sleep(0.5)
                    # Escribir caracter a caracter (mas humano, evita bot detection)
                    page.keyboard.type("a", delay=100)
                    time.sleep(0.3)
                    logger.info("  -> Texto 'a' escrito en busqueda")

            except Exception as e:
                logger.warning(f"  -> No se pudo escribir en busqueda: {e}")

            # Limpiar respuestas previas antes de la busqueda
            api_responses_before = len(api_responses)

            # Click BUSCAR
            try:
                buscar_btn = page.wait_for_selector(
                    'button:has-text("BUSCAR"), .v-btn:has-text("BUSCAR")',
                    timeout=5000
                )
                if buscar_btn:
                    buscar_btn.click()
                    logger.info("  -> Click en BUSCAR")
                    # Esperar a que la API responda
                    time.sleep(2)
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    time.sleep(3)

            except Exception as e:
                logger.warning(f"  -> No se encontro boton BUSCAR: {e}")

            # ---- Paso 3: Intentar acceder al Vue instance directamente ----
            logger.info("\nAccediendo a datos del Vue.js...")
            try:
                vue_data = page.evaluate("""
                    () => {
                        // Intentar acceder al Vue instance
                        const app = document.getElementById('app');
                        if (app && app.__vue__) {
                            const vm = app.__vue__;
                            // Navegar por los componentes hijos para encontrar los datos
                            function findData(component, depth) {
                                if (depth > 10) return null;
                                
                                // Buscar propiedades que contengan arrays de normas/resultados
                                const data = component.$data || {};
                                if (data.resultados && Array.isArray(data.resultados) && data.resultados.length > 0) {
                                    return { source: 'resultados', data: data.resultados };
                                }
                                if (data.normas && Array.isArray(data.normas) && data.normas.length > 0) {
                                    return { source: 'normas', data: data.normas };
                                }
                                if (data.publicaciones && Array.isArray(data.publicaciones) && data.publicaciones.length > 0) {
                                    return { source: 'publicaciones', data: data.publicaciones };
                                }
                                
                                // Buscar en hijos
                                if (component.$children) {
                                    for (const child of component.$children) {
                                        const result = findData(child, depth + 1);
                                        if (result) return result;
                                    }
                                }
                                return null;
                            }
                            
                            return findData(vm, 0);
                        }
                        return null;
                    }
                """)

                if vue_data and vue_data.get("data"):
                    docs = vue_data["data"]
                    logger.info(f"  -> {len(docs)} documentos en Vue.js ({vue_data.get('source', '?')})")
                    if len(docs) > 0:
                        logger.info(f"  -> Muestra: {json.dumps(docs[0], ensure_ascii=False, indent=2)[:300]}")
                    for raw in docs:
                        doc = self._normalizar_documento(raw)
                        if doc:
                            self.datos_extraidos.append(doc)

            except Exception as e:
                logger.warning(f"  -> Error accediendo Vue instance: {e}")

            # ---- Paso 4: Revisar localStorage ----
            if not self.datos_extraidos:
                logger.info("\nRevisando localStorage...")
                try:
                    local_data = page.evaluate("""
                        () => {
                            const raw = localStorage.getItem('data');
                            if (raw) {
                                try { return JSON.parse(raw); } catch(e) {}
                            }
                            return null;
                        }
                    """)
                    if local_data and isinstance(local_data, list) and len(local_data) > 0:
                        logger.info(f"  -> {len(local_data)} docs en localStorage")
                        for raw in local_data:
                            doc = self._normalizar_documento(raw)
                            if doc:
                                self.datos_extraidos.append(doc)
                except Exception as e:
                    logger.warning(f"  -> Error leyendo localStorage: {e}")

            # ---- Paso 5: Procesar respuestas de red interceptadas ----
            if not self.datos_extraidos:
                logger.info("\nProcesando respuestas de red interceptadas...")
                new_responses = api_responses[api_responses_before:]
                logger.info(f"  -> {len(new_responses)} nuevas respuestas despues de buscar")

                for resp in api_responses:
                    url = resp["url"]
                    status = resp.get("status", 0)
                    if status in (200, 201) and ("publicaciones" in url or "documentos" in url):
                        body = resp["data"]
                        data = body.get("data", body) if isinstance(body, dict) else body
                        if isinstance(data, list) and len(data) > 0:
                            logger.info(f"  -> {len(data)} docs desde {url} (HTTP {status})")
                            for raw in data:
                                doc = self._normalizar_documento(raw)
                                if doc:
                                    self.datos_extraidos.append(doc)

            # ---- Paso 6: DOM scraping como ultimo recurso ----
            if not self.datos_extraidos:
                logger.info("\nScrapeando tarjetas del DOM...")
                try:
                    page.wait_for_timeout(2000)
                    cards = page.query_selector_all(".v-card")
                    logger.info(f"  -> {len(cards)} tarjetas v-card")

                    for card in cards:
                        try:
                            title_el = card.query_selector("a[href*='detalles']")
                            if not title_el:
                                continue

                            title_text = title_el.inner_text().strip()
                            href = title_el.get_attribute("href") or ""

                            doc_id = 0
                            if "detalles/" in href:
                                try:
                                    doc_id = int(href.split("detalles/")[-1])
                                except ValueError:
                                    pass

                            numero = ""
                            for sep in ["Nº", "N°", "No."]:
                                if sep in title_text:
                                    numero = title_text.split(sep)[-1].strip()
                                    break

                            tipo = ""
                            for t in ["Ordenanza", "Resolucion", "Decreto"]:
                                if t.lower() in title_text.lower():
                                    tipo = t
                                    break

                            doc = DocumentoDigesto(
                                id=doc_id or abs(hash(title_text)) % 100000,
                                numero=numero or None,
                                titulo=title_text,
                                tipo=tipo or None,
                                url_detalle=f"{self.SITE_URL}/#{href}" if href else None,
                            )
                            self.datos_extraidos.append(doc.model_dump())

                        except Exception:
                            continue

                    logger.info(f"  -> {len(self.datos_extraidos)} documentos del DOM")

                except Exception as e:
                    logger.error(f"Error DOM: {e}")

            # ---- Resumen ----
            logger.info(f"\n  Total extraidos via Playwright: {len(self.datos_extraidos)}")
            browser.close()

        return len(self.datos_extraidos) > 0



    # ------------------------------------------
    # Exportación
    # ------------------------------------------
    def _exportar(self):
        """Guarda los datos en múltiples formatos."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # JSON completo
        json_path = os.path.join(self.output_dir, f"digesto_completo_{timestamp}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.datos_extraidos, f, ensure_ascii=False, indent=2)
        logger.info(f"  → JSON guardado en: {json_path}")

        # CSV (tabla plana)
        csv_path = os.path.join(self.output_dir, f"digesto_tabla_{timestamp}.csv")
        try:
            import csv
            campos = ["id", "numero", "tipo", "titulo", "categoria", "fecha_sancion",
                       "vigente", "descriptores", "resumen", "archivo_pdf", "url_detalle"]
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
                writer.writeheader()
                for doc in self.datos_extraidos:
                    row = dict(doc)
                    # Convertir lista de descriptores a string
                    if isinstance(row.get("descriptores"), list):
                        row["descriptores"] = "; ".join(row["descriptores"])
                    writer.writerow(row)
            logger.info(f"  → CSV guardado en: {csv_path}")
        except Exception as e:
            logger.error(f"Error exportando CSV: {e}")

        # Resumen por tipo
        resumen = {}
        for doc in self.datos_extraidos:
            tipo = doc.get("tipo") or "Sin tipo"
            resumen[tipo] = resumen.get(tipo, 0) + 1

        logger.info("\n" + "=" * 50)
        logger.info("RESUMEN POR TIPO DE DOCUMENTO:")
        logger.info("=" * 50)
        for tipo, cant in sorted(resumen.items(), key=lambda x: -x[1]):
            logger.info(f"  {tipo}: {cant}")

        # Resumen vigencia
        vigentes = sum(1 for d in self.datos_extraidos if d.get("vigente") is True)
        no_vigentes = sum(1 for d in self.datos_extraidos if d.get("vigente") is False)
        sin_info = len(self.datos_extraidos) - vigentes - no_vigentes
        logger.info(f"\n  Vigentes: {vigentes}")
        logger.info(f"  No vigentes: {no_vigentes}")
        logger.info(f"  Sin información: {sin_info}")

    # ------------------------------------------
    # Ejecución principal
    # ------------------------------------------
    def ejecutar(self) -> List[Dict[str, Any]]:
        """Ejecuta el scraping con la estrategia más eficiente disponible."""
        logger.info("╔══════════════════════════════════════════════════════╗")
        logger.info("║   SCRAPER DEL DIGESTO MUNICIPAL DE ALTA GRACIA     ║")
        logger.info("╚══════════════════════════════════════════════════════╝")
        logger.info(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Estrategia 1: API directa (rápida, sin navegador)
        exito = self._scrape_via_api()

        # Estrategia 2: Playwright (fallback)
        if not exito:
            logger.info("\nLa API directa falló. Activando Playwright...\n")
            exito = self._scrape_via_playwright()

        # Exportar resultados
        if self.datos_extraidos:
            logger.info(f"\n{'=' * 50}")
            logger.info("EXPORTANDO RESULTADOS...")
            self._exportar()
        else:
            logger.error("\n⚠ No se pudieron extraer datos con ninguna estrategia.")
            logger.error("Posibles causas:")
            logger.error("  - El sitio puede estar caído o bloqueando requests")
            logger.error("  - La estructura de la API puede haber cambiado")
            logger.error("  - Se requiere una VPN o estar en la red local")

        logger.info(f"\nFin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Total documentos extraídos: {len(self.datos_extraidos)}")

        return self.datos_extraidos


# ==========================================
# EJECUCIÓN
# ==========================================
if __name__ == "__main__":
    scraper = DigestoScraper(output_dir="output")
    resultados = scraper.ejecutar()
    print(f"\nProceso finalizado. Total de normas validas: {len(resultados)}")
