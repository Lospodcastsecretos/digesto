import os
import sys
import re
import json
import requests
import mammoth

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Cargar .env
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

clean_url = (TURSO_URL or "").replace("libsql://", "https://").replace("http://", "https://")
pipeline_url = f"{clean_url}/v2/pipeline"
headers = {
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
    r = requests.post(pipeline_url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    res = r.json()
    if res["results"][0]["type"] == "error":
        raise Exception(res["results"][0]["error"]["message"])
    return res["results"][0]["response"]["result"]

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
        return resp.json()["data"][0]["embedding"]
    raise Exception(f"OpenAI Error: {resp.text}")

def extraer_texto_docx(filepath):
    with open(filepath, "rb") as docx_file:
        result = mammoth.convert_to_markdown(docx_file)
        return result.value

def extraer_texto_pdf(filepath):
    # Intentar extracción nativa
    extracted_text = ""
    try:
        import pypdf
        reader = pypdf.PdfReader(filepath)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                extracted_text += t + "\n"
        extracted_text = extracted_text.strip()
    except Exception as e:
        print(f"   ⚠️ Error en lectura nativa PDF: {e}")
        
    if len(extracted_text) > 150:
        return extracted_text
        
    # Intentar OCR
    print("   -> PDF escaneado detectado. Intentando OCR local (Tesseract)...")
    try:
        from pdf2image import convert_from_path
        import pytesseract
        images = convert_from_path(filepath)
        ocr_text = ""
        for i, img in enumerate(images):
            print(f"      [OCR] Procesando página {i+1}/{len(images)}...")
            page_text = pytesseract.image_to_string(img, lang="spa")
            if page_text:
                ocr_text += page_text + "\n"
        ocr_text = ocr_text.strip()
        if ocr_text:
            return ocr_text
    except Exception as e:
        print(f"   ❌ Error en OCR (Verifica que Tesseract/Poppler estén instalados en Windows): {e}")
        
    return extracted_text if extracted_text else None

def main():
    folder = "scratch/documentos_corregidos"
    if not os.path.exists(folder):
        os.makedirs(folder)
        print(f"📂 Se ha creado la carpeta '{folder}'.")
        print("👉 Por favor, coloca allí los archivos (.docx o .pdf) que quieras procesar.")
        print("⚠️ Importante: El nombre del archivo debe terminar con el ID de la norma (ej: 'ordenanza-8582.docx' o 'gas_obra-8582.docx').")
        sys.exit(0)
        
    archivos = [f for f in os.listdir(folder) if f.lower().endswith((".docx", ".pdf"))]
    if not archivos:
        print(f"⚠️ No se encontraron archivos (.docx o .pdf) en la carpeta '{folder}'.")
        return
        
    print(f"🚀 Procesando {len(archivos)} archivos locales corregidos...")
    
    for filename in archivos:
        filepath = os.path.join(folder, filename)
        print(f"\n📄 Archivo: {filename}")
        
        # Intentar extraer el ID del nombre del archivo (busca dígitos antes de la extensión, ej: -8582.docx)
        match = re.search(r'-(\d+)\.(docx|pdf)$', filename.lower())
        if not match:
            # Buscar cualquier número de más de 3 dígitos al final
            match = re.search(r'(\d+)\.(docx|pdf)$', filename.lower())
            
        if not match:
            print(f"   ❌ Error: No se pudo identificar el ID de la norma en el nombre '{filename}'.")
            print("   Asegúrate de que termine con '-[ID].[ext]' (ej: 'obra-8582.docx')")
            continue
            
        nid = int(match.group(1))
        ext = "." + match.group(2)
        
        # Buscar la norma en Turso para obtener sus datos
        try:
            res = turso_query("SELECT numero, tipo_nombre, titulo, resumen FROM normas WHERE id = ?", [nid])
            rows = res.get("rows", [])
            if not rows:
                print(f"   ❌ Error: No se encontró ninguna norma con el ID {nid} en la base de datos.")
                continue
            
            # SQLite devuelve los valores
            num = rows[0][0].get("value")
            tipo = rows[0][1].get("value")
            titulo = rows[0][2].get("value")
            resumen = rows[0][3].get("value") or ""
            
            print(f"   🎯 Vinculando con: {tipo} {num} (ID: {nid}) - {titulo[:40]}...")
            
            # Extraer texto
            texto_completo = None
            if ext == ".docx":
                texto_completo = extraer_texto_docx(filepath)
            elif ext == ".pdf":
                texto_completo = extraer_texto_pdf(filepath)
                
            if not texto_completo:
                print("   ❌ Error: No se pudo extraer texto del archivo.")
                continue
                
            print(f"   ✅ Texto extraído con éxito ({len(texto_completo)} caracteres).")
            
            # Generar embedding del resumen
            print("   -> Generando embedding con OpenAI...")
            text_to_embed = f"Título: {titulo}\n\nResumen: {resumen}"
            embedding = get_openai_embedding(text_to_embed)
            
            # Guardar en Turso
            print("   -> Actualizando base de datos...")
            turso_query("UPDATE normas SET texto_completo = ? WHERE id = ?", [texto_completo, nid])
            turso_query("UPDATE normas SET embedding = vector(?) WHERE id = ?", [json.dumps(embedding), nid])
            
            print(f"   🎉 ¡{tipo} {num} actualizada e indexada con éxito localmente!")
            
        except Exception as e:
            print(f"   ❌ Error procesando base de datos o API: {e}")

if __name__ == "__main__":
    main()
