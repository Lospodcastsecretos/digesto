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

# Cargar .env localmente
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
API_KEY = "$2y$10$VXghLWoHpSnWbrhXk.p0y.BRuUHI3RZ7pAT1QC4F8T3.7693PWVCy"

digesto_headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "x-requested-with": "XMLHttpRequest",
    "api-key": API_KEY,
    "referer": f"{SITE_URL}/"
}

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

def resolver_drive_id(filename):
    files = [f.strip() for f in filename.split(";") if f.strip()]
    if not files:
        return None
    # Priorizar .docx y .pdf
    docx_pdf_files = [f for f in files if f.lower().endswith((".docx", ".pdf"))]
    file_to_resolve = docx_pdf_files[0] if docx_pdf_files else files[0]
    
    url = f"{SITE_URL}/api/documentos/{file_to_resolve}"
    try:
        resp = requests.get(url, headers=digesto_headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0].get("id"), file_to_resolve
    except Exception as e:
        print(f"      [Drive ID] Falló resolución para {file_to_resolve}: {e}")
    return None, None

def descargar_y_convertir_docx(drive_id):
    url = f"{SITE_URL}/download/{drive_id}"
    resp = requests.get(url, headers=digesto_headers, allow_redirects=True, timeout=40, stream=True)
    if resp.status_code == 200:
        content_type = resp.headers.get("Content-Type", "")
        if "html" in content_type:
            raise Exception("El servidor devolvió HTML en lugar del archivo binario.")
        temp_docx_path = "temp_backfill.docx"
        with open(temp_docx_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)
        try:
            with open(temp_docx_path, "rb") as docx_file:
                result = mammoth.convert_to_markdown(docx_file)
                return result.value
        finally:
            if os.path.exists(temp_docx_path):
                os.remove(temp_docx_path)
    return None

def descargar_y_convertir_pdf(drive_id):
    url = f"{SITE_URL}/download/{drive_id}"
    resp = requests.get(url, headers=digesto_headers, allow_redirects=True, timeout=40, stream=True)
    if resp.status_code == 200:
        content_type = resp.headers.get("Content-Type", "")
        if "html" in content_type:
            raise Exception("El servidor devolvió HTML en lugar del archivo binario.")
        temp_pdf_path = "temp_backfill.pdf"
        with open(temp_pdf_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)
        try:
            # 1. Extracción nativa
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
            
            if len(extracted_text) > 150:
                print(f"      [PDF] Texto nativo extraído ({len(extracted_text)} caracteres).")
                return extracted_text
                
            # 2. OCR Tesseract
            print("      [PDF] Aplicando OCR (Tesseract)...")
            try:
                from pdf2image import convert_from_path
                import pytesseract
                
                images = convert_from_path(temp_pdf_path)
                ocr_text = ""
                for i, img in enumerate(images):
                    print(f"         [OCR] Página {i+1}/{len(images)}...")
                    page_text = pytesseract.image_to_string(img, lang="spa")
                    if page_text:
                        ocr_text += page_text + "\n"
                ocr_text = ocr_text.strip()
                if ocr_text:
                    print(f"      [PDF] OCR finalizado ({len(ocr_text)} caracteres).")
                    return ocr_text
            except Exception as oe:
                print(f"      [PDF] Error en OCR: {oe}")
            return extracted_text if extracted_text else None
        finally:
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
    return None

def main():
    dry_run = "--dry-run" in sys.argv
    limit = 50 # Limitar por ejecución para no sobrecargar de golpe
    for arg in sys.argv:
        if arg.startswith("--limit="):
            limit = int(arg.split("=")[1])
            
    print(f"🚀 Iniciando Backfill de Textos y OCR (Límite: {limit} normas)...")
    
    # Buscar normas sin texto completo
    sql = """
        SELECT id, numero, tipo_nombre, titulo, resumen, archivo_pdf 
        FROM normas 
        WHERE (texto_completo IS NULL OR texto_completo = '') 
          AND archivo_pdf IS NOT NULL AND archivo_pdf != ''
        LIMIT ?
    """
    pendientes = turso_query(sql, [limit])
    print(f"Normas elegidas para procesar en este lote: {len(pendientes)}")
    
    exitos = 0
    
    for idx, n in enumerate(pendientes):
        nid = n["id"]
        num = n["numero"]
        tipo = n["tipo_nombre"]
        titulo = n["titulo"]
        resumen = n["resumen"] or ""
        filename = n["archivo_pdf"]
        
        print(f"\n[{idx+1}/{len(pendientes)}] Procesando {tipo} {num} (ID: {nid})...")
        texto_completo = None
        
        try:
            drive_id, resolved_file = resolver_drive_id(filename)
            if drive_id and drive_id != "sin_archivo_fisico":
                ext = os.path.splitext(resolved_file.lower())[1]
                if ext in (".docx", ".doc"):
                    texto_completo = descargar_y_convertir_docx(drive_id)
                elif ext == ".pdf":
                    texto_completo = descargar_y_convertir_pdf(drive_id)
                else:
                    print(f"   ⚠️ Extensión no soportada: {ext}")
                    
                if texto_completo:
                    print(f"   ✅ Texto extraído con éxito ({len(texto_completo)} caracteres).")
                else:
                    print("   ⚠️ No se pudo extraer texto del archivo.")
            else:
                print("   ⚠️ No tiene archivo real en Google Drive o no pudo ser resuelto.")
        except Exception as e:
            print(f"   ❌ Error procesando archivo: {e}")
            
        # Generar embedding si tenemos resumen/titulo
        embedding = None
        if not dry_run:
            try:
                # Generar embedding
                print("   -> Regenerando vector en OpenAI...")
                text_to_embed = f"Título: {titulo}\n\nResumen: {resumen}"
                embedding = get_openai_embedding(text_to_embed)
                
                # Actualizar base de datos
                db_text = texto_completo if texto_completo else "sin_texto_disponible"
                sql_up = "UPDATE normas SET texto_completo = ? WHERE id = ?"
                turso_query(sql_up, [db_text, nid])
                
                if embedding:
                    embedding_str = json.dumps(embedding)
                    turso_query("UPDATE normas SET embedding = vector(?) WHERE id = ?", [embedding_str, nid])
                    
                print(f"   🎉 ¡{tipo} {num} actualizada e indexada con éxito!")
                exitos += 1
            except Exception as e:
                print(f"   ❌ Error al guardar en Turso: {e}")
        else:
            print(f"   [DRY RUN] Se habría guardado texto ({bool(texto_completo)}) y vector.")
            exitos += 1
            
    print(f"\n--- LOTE FINALIZADO ---")
    print(f"Procesadas con éxito: {exitos}")

if __name__ == "__main__":
    main()
