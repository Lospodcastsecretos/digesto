import os
import sys
import re
import json
import time
import requests
import mammoth

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Intentar cargar .env localmente si existe
if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key, val.strip('"\''))

TURSO_URL = os.environ.get("TURSO_URL")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

SITE_URL = "https://digestoaltagracia.com.ar"
API_KEY = os.environ.get("SITE_API_KEY")

# Headers para interactuar con la web oficial del Digesto
digesto_headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "x-requested-with": "XMLHttpRequest",
    "api-key": API_KEY,
    "referer": f"{SITE_URL}/"
}

# Configuración de Turso Pipeline
clean_turso_url = (TURSO_URL or "").replace("libsql://", "https://").replace("http://", "https://")
pipeline_url = f"{clean_turso_url}/v2/pipeline"
turso_headers = {
    "Authorization": f"Bearer {TURSO_TOKEN}",
    "Content-Type": "application/json"
}

def turso_query(sql, args=None):
    if args is None: args = []
    formatted_args = []
    for arg in args:
        if isinstance(arg, int):
            formatted_args.append({"type": "integer", "value": str(arg)})
        elif isinstance(arg, float):
            formatted_args.append({"type": "float", "value": str(arg)})
        elif arg is None:
            formatted_args.append({"type": "null"})
        else:
            formatted_args.append({"type": "text", "value": str(arg)})
            
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": formatted_args}},
            {"type": "close"}
        ]
    }
    
    for attempt in range(3):
        try:
            r = requests.post(pipeline_url, headers=turso_headers, json=payload, timeout=60)
            r.raise_for_status()
            data = r.json()
            
            if data["results"][0]["type"] == "error":
                raise Exception(f"Turso Error: {data['results'][0]['error']['message']}")
                
            result = data["results"][0]["response"]["result"]
            if "cols" not in result:
                return []
                
            cols = [c["name"] for c in result["cols"]]
            rows = []
            for r_val in result.get("rows", []):
                obj = {}
                for i, col in enumerate(cols):
                    obj[col] = r_val[i].get("value") if isinstance(r_val[i], dict) else None
                rows.append(obj)
            return rows
        except Exception as e:
            print(f"      [Turso] Intento {attempt+1} falló ({e}). Reintentando en 5 segundos...")
            time.sleep(5)
            
    raise Exception("❌ No se pudo conectar con Turso tras 3 intentos (Timeout/Error de red).")

def get_openai_embedding(text):
    safe_text = text[:8000]
    resp = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "input": safe_text,
            "model": "text-embedding-3-small"
        },
        timeout=30
    )
    if resp.status_code == 200:
        data = resp.json()
        return data["data"][0]["embedding"]
    else:
        raise Exception(f"OpenAI Embedding Error: {resp.text}")

def extraer_relaciones_legales(texto, nid, numero_origen, tipo_origen):
    if not texto:
        return
    
    fragmento = texto[:12000]
    prompt = f"""
Analiza el siguiente texto de la norma legal municipal ({tipo_origen} N° {numero_origen}) e identifica si realiza alguna acción legal explícita sobre otras normas anteriores.
Acciones a identificar:
- Deroga (de forma total): deroga en su totalidad otra norma.
- Modifica: cambia artículos o reforma parte de otra norma.
- Deroga parcialmente: deroga artículos específicos de otra norma.
- Reglamenta: reglamenta la aplicación de otra norma.

Debes responder ÚNICAMENTE en formato JSON con la siguiente estructura:
{{
  "relaciones": [
    {{
      "tipo_relacion": "deroga" | "modifica" | "deroga_parcialmente" | "reglamenta",
      "numero_destino": "10309",
      "tipo_destino": "Ordenanza" | "Decreto" | "Resolución",
      "detalles": "Breve frase o artículo que describe la acción"
    }}
  ]
}}

Si no se mencionan derogaciones, modificaciones o reglamentaciones de otras normas, responde:
{{
  "relaciones": []
}}

Texto de la norma:
{fragmento}
"""

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "Eres un asistente legal experto en digesto y ordenanzas municipales de Argentina."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": { "type": "json_object" },
                "temperature": 0.0
            },
            timeout=30
        )
        if resp.status_code == 200:
            res_json = resp.json()
            raw_content = res_json["choices"][0]["message"]["content"]
            data = json.loads(raw_content)
            
            for rel in data.get("relaciones", []):
                tipo_rel = rel.get("tipo_relacion")
                num_dest = str(rel.get("numero_destino")).strip()
                tipo_dest = rel.get("tipo_destino")
                detalles = rel.get("detalles")
                
                if not num_dest or not tipo_rel or not tipo_dest:
                    continue
                
                dest_rows = turso_query("SELECT id FROM normas WHERE numero = ? AND tipo_nombre = ? LIMIT 1", [num_dest, tipo_dest])
                if dest_rows and dest_rows[0].get("id") is not None:
                    dest_id = dest_rows[0]["id"]
                    print(f"   🔗 Relación detectada: {tipo_origen} {numero_origen} -> {tipo_rel.upper()} -> {tipo_dest} {num_dest} (ID: {dest_id})")
                    
                    sql_rel = """
                        INSERT OR IGNORE INTO normas_relaciones (norma_origen_id, norma_destino_id, tipo_relacion, detalles)
                        VALUES (?, ?, ?, ?)
                    """
                    turso_query(sql_rel, [nid, dest_id, tipo_rel, detalles])
                    
                    if tipo_rel == 'deroga':
                        print(f"   🚫 Apagando flag de vigencia para {tipo_dest} {num_dest} debido a derogación.")
                        turso_query("UPDATE normas SET vigente = 0 WHERE id = ?", [dest_id])
    except Exception as ex:
        print(f"   ⚠️ Falló la extracción de relaciones por IA: {ex}")


def resolver_drive_id(filename):
    url = f"{SITE_URL}/api/documentos/{filename}"
    try:
        resp = requests.get(url, headers=digesto_headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0].get("id")
    except Exception as e:
        print(f"      [Drive ID] Falló resolución para {filename}: {e}")
    return None

def descargar_y_convertir_docx(drive_id):
    url = f"{SITE_URL}/download/{drive_id}"
    resp = requests.get(url, headers=digesto_headers, allow_redirects=True, timeout=40, stream=True)
    if resp.status_code == 200:
        # Validar tipo de contenido
        content_type = resp.headers.get("Content-Type", "")
        if "html" in content_type:
            raise Exception("El servidor devolvió HTML en lugar del archivo binario.")
            
        temp_docx_path = "temp_sync_file.docx"
        with open(temp_docx_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)
                    
        # Convertir a Markdown usando Mammoth
        try:
            with open(temp_docx_path, "rb") as docx_file:
                result = mammoth.convert_to_markdown(docx_file)
                markdown_text = result.value
            return markdown_text
        finally:
            if os.path.exists(temp_docx_path):
                os.remove(temp_docx_path)
    else:
        raise Exception(f"Error HTTP {resp.status_code} al descargar.")

def descargar_y_convertir_pdf(drive_id):
    url = f"{SITE_URL}/download/{drive_id}"
    resp = requests.get(url, headers=digesto_headers, allow_redirects=True, timeout=40, stream=True)
    if resp.status_code == 200:
        content_type = resp.headers.get("Content-Type", "")
        if "html" in content_type:
            raise Exception("El servidor devolvió HTML en lugar del archivo binario.")
            
        temp_pdf_path = "temp_sync_file.pdf"
        with open(temp_pdf_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)
                    
        try:
            # 1. Intentar extracción de texto nativa con pypdf
            extracted_text = ""
            try:
                import pypdf
                reader = pypdf.PdfReader(temp_pdf_path)
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        extracted_text += text + "\n"
                extracted_text = extracted_text.strip()
            except Exception as pe:
                print(f"      [PDF] Error en extracción nativa (pypdf): {pe}")
            
            # Si se logró extraer suficiente texto nativo, usarlo
            if len(extracted_text) > 150:
                print(f"      [PDF] Texto nativo extraído con éxito ({len(extracted_text)} caracteres).")
                return extracted_text
                
            # 2. Si no, aplicar OCR con Inteligencia Artificial (OpenAI Vision)
            print("      [PDF] Poco texto nativo detectado. Aplicando OCR con Inteligencia Artificial (OpenAI Vision)...")
            try:
                import io
                import base64
                from pdf2image import convert_from_path
                
                # Convertir páginas del PDF a imágenes en memoria
                images = convert_from_path(temp_pdf_path)
                ocr_text = ""
                for i, img in enumerate(images):
                    print(f"         [OpenAI Vision] Transcribiendo página {i+1} de {len(images)}...")
                    
                    # Guardar imagen en buffer en memoria como JPEG
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG')
                    base64_image = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                    
                    # Llamar a OpenAI Chat Completions con imagen
                    api_resp = requests.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENAI_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "gpt-4o-mini",
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Transcribe textualmente a texto plano en español todo el contenido de este documento municipal. Corrige automáticamente palabras cortas o borrosas por contexto y mantén el formato original en lo posible. No agregues introducciones, resúmenes ni comentarios tuyos, solo el texto transcrito."
                                        },
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:image/jpeg;base64,{base64_image}"
                                            }
                                        }
                                    ]
                                }
                            ],
                            "max_tokens": 1500
                        },
                        timeout=45
                    )
                    
                    if api_resp.status_code == 200:
                        page_text = api_resp.json()["choices"][0]["message"]["content"]
                        ocr_text += page_text + "\n"
                    else:
                        print(f"         ⚠️ Error de API OpenAI en página {i+1}: {api_resp.text}")
                
                ocr_text = ocr_text.strip()
                if ocr_text:
                    print(f"      [PDF] Transcripción por IA finalizada ({len(ocr_text)} caracteres).")
                    return ocr_text
            except Exception as oe:
                print(f"      [PDF] Error en OpenAI Vision OCR: {oe}")
            
            # Si falló todo, retornar lo que sea que hayamos sacado
            return extracted_text if extracted_text else "Error: No se pudo extraer texto del PDF escaneado (falta OCR local)."
            
        finally:
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
    else:
        raise Exception(f"Error HTTP {resp.status_code} al descargar.")

def normalizar_publicacion(p):
    """Mapear los nombres de la API del digesto a las columnas de la base de datos."""
    # Determinar tipo
    tipo = "Ordenanza"
    titulo_upper = (p.get("titulo") or "").upper()
    if "DECRETO" in titulo_upper:
        tipo = "Decreto"
    elif "RESOLUCI" in titulo_upper:
        tipo = "Resolución"
        
    # Extraer número
    numero = p.get("numero")
    if not numero:
        match = re.search(r'(?:N[°º]|\bNRO\.?|\bN|\bNMERO|\bN\b)\s*(\d+)', titulo_upper)
        if match:
            numero = match.group(1)
            
    es_vigente = 1 if p.get("vigente") is True or str(p.get("vigente")).lower() == 'vigente' else 0
    
    return {
        "id": p.get("id"),
        "numero": numero,
        "titulo": p.get("titulo"),
        "resumen": p.get("resumen") or "",
        "tipo_nombre": tipo,
        "categoria_nombre": (p.get("categoria", {}).get("nombre") or "").strip() if isinstance(p.get("categoria"), dict) else "General",
        "vigente": es_vigente,
        "fecha": p.get("fecha_sancion") or "Histórico / Sin fecha",
        "archivo_pdf": p.get("archivo_pdf"),
        "url_detalle": f"{SITE_URL}/#/detalles/{p.get('id')}" if p.get("id") else None
    }

def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("🔍 EJECUTANDO EN MODO PRUEBA (DRY RUN) - No se guardarán cambios en Turso.")

    if not TURSO_URL or not TURSO_TOKEN or not OPENAI_API_KEY:
        print("❌ Faltan variables de entorno esenciales (TURSO_URL, TURSO_TOKEN, OPENAI_API_KEY).")
        sys.exit(1)

    print("1️⃣ Consultando la API oficial del Digesto de Alta Gracia...")
    try:
        resp = requests.get(f"{SITE_URL}/api/publicaciones", headers=digesto_headers, timeout=30)
        resp.raise_for_status()
        raw_data = resp.json()
        
        # Si la API envuelve la lista en un objeto (ej: {"data": [...]})
        if isinstance(raw_data, dict):
            publicaciones = raw_data.get("data", raw_data)
            if not isinstance(publicaciones, list):
                publicaciones = raw_data.get("publicaciones", [raw_data])
        else:
            publicaciones = raw_data
            
        print(f"   -> Recibidas {len(publicaciones)} publicaciones de la API (Tipo: {type(publicaciones).__name__}).")
        if len(publicaciones) > 0:
            print("   -> Ejemplo del primer elemento:", json.dumps(publicaciones[0])[:300])
    except Exception as e:
        print(f"❌ Error al consultar la API del Digesto: {e}")
        sys.exit(1)

    print("2️⃣ Buscando normas ya existentes en Turso...")
    try:
        existentes_rows = turso_query("SELECT id, numero, tipo_nombre FROM normas")
        existentes_ids = {int(row["id"]) for row in existentes_rows if row.get("id") is not None}
        existentes_claves = {
            (str(row.get("numero")).strip(), str(row.get("tipo_nombre")).strip())
            for row in existentes_rows 
            if row.get("numero") and row.get("tipo_nombre")
        }
        print(f"   -> Encontradas {len(existentes_ids)} normas indexadas en la base de datos.")
    except Exception as e:
        print(f"❌ Error al consultar normas existentes en Turso: {e}")
        sys.exit(1)

    # Identificar las normas que faltan (evitando colisiones con claves duplicadas limpiadas)
    nuevas_publicaciones = []
    for p in publicaciones:
        if not p.get("id"):
            continue
        
        # Pre-normalizar temporalmente para comparar por número y tipo
        norma_norm = normalizar_publicacion(p)
        num_str = str(norma_norm["numero"]).strip()
        tipo_str = str(norma_norm["tipo_nombre"]).strip()
        
        id_existe = int(p.get("id")) in existentes_ids
        clave_existe = (num_str, tipo_str) in existentes_claves
        
        if not id_existe and not clave_existe:
            nuevas_publicaciones.append(p)
            
    print(f"   -> Detectadas {len(nuevas_publicaciones)} normas nuevas por sincronizar.")

    if not nuevas_publicaciones:
        print("✅ ¡La base de datos ya está al día con el sitio oficial! Nada que sincronizar.")
        sys.exit(0)

    print(f"\n3️⃣ Iniciando sincronización incremental de {len(nuevas_publicaciones)} normas...")
    
    sincronizadas = 0
    errores = 0

    for idx, p in enumerate(nuevas_publicaciones):
        norma = normalizar_publicacion(p)
        nid = norma["id"]
        num = norma["numero"]
        tipo = norma["tipo_nombre"]
        filename = norma["archivo_pdf"]
        
        print(f"\n[{idx+1}/{len(nuevas_publicaciones)}] Procesando {tipo} {num} (ID: {nid})...")
        
        texto_completo = None
        
        # Si tiene archivo físico registrado, intentar descargar y extraer texto completo
        if filename:
            print(f"   -> Buscando ID de Drive para archivo: {filename}...")
            try:
                drive_id = resolver_drive_id(filename)
                if drive_id and drive_id != "sin_archivo_fisico":
                    ext = os.path.splitext(filename.lower())[1]
                    if ext == ".docx":
                        print(f"   -> Descargando y convirtiendo archivo Word (Drive: {drive_id})...")
                        texto_completo = descargar_y_convertir_docx(drive_id)
                    elif ext == ".pdf":
                        print(f"   -> Descargando y convirtiendo archivo PDF (Drive: {drive_id})...")
                        texto_completo = descargar_y_convertir_pdf(drive_id)
                    else:
                        print(f"   ⚠️ Extensión de archivo no soportada: {ext}. Saltando conversión.")
                    
                    if texto_completo:
                        print(f"   ✅ Texto completo extraído: {len(texto_completo)} caracteres.")
                else:
                    print("   ⚠️ La norma no tiene archivo físico en Google Drive.")
            except Exception as e:
                print(f"   ❌ Error al procesar archivo físico: {e}")
                
        # Generar embedding del resumen
        print("   -> Generando embedding vectorial con OpenAI...")
        embedding = None
        try:
            text_to_embed = f"Título: {norma['titulo']}\n\nResumen: {norma['resumen']}"
            embedding = get_openai_embedding(text_to_embed)
            print("   ✅ Embedding vectorial generado con éxito.")
        except Exception as e:
            print(f"   ❌ Error al generar embedding: {e}")

        # Guardar en Turso
        if not dry_run:
            try:
                # Insertar registro principal
                sql_ins = """
                    INSERT INTO normas (id, numero, titulo, resumen, tipo_nombre, categoria_nombre, vigente, fecha, archivo_pdf, url_detalle, texto_completo)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                params_ins = [
                    nid, num, norma["titulo"], norma["resumen"], tipo,
                    norma["categoria_nombre"], norma["vigente"], norma["fecha"],
                    filename, norma["url_detalle"], texto_completo
                ]
                turso_query(sql_ins, params_ins)
                
                # Actualizar embedding si existe
                if embedding:
                    embedding_str = json.dumps(embedding)
                    turso_query("UPDATE normas SET embedding = vector(?) WHERE id = ?", [embedding_str, nid])
                    
                # Extraer y registrar relaciones legales si hay texto completo
                if texto_completo:
                    print("   -> Analizando texto para extraer relaciones legales...")
                    extraer_relaciones_legales(texto_completo, nid, num, tipo)
                    
                print(f"   🎉 ¡{tipo} {num} sincronizada e indexada con éxito!")
                sincronizadas += 1
            except Exception as e:
                print(f"   ❌ Error guardando en Turso: {e}")
                errores += 1
        else:
            print(f"   [DRY RUN] Se habría guardado {tipo} {num} (Extraído: {bool(texto_completo)}, Vector: {bool(embedding)})")
            sincronizadas += 1

    print("\n--- RESUMEN FINAL DE LA SINCRONIZACIÓN ---")
    print(f"Total procesadas: {len(nuevas_publicaciones)}")
    print(f"Sincronizadas con éxito: {sincronizadas}")
    print(f"Fallidas: {errores}")

if __name__ == "__main__":
    main()
