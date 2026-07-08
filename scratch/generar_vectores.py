import os
import sys
import json
import requests
import time

# Intentar cargar .env localmente
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

if not TURSO_URL or not TURSO_TOKEN or not OPENAI_API_KEY:
    print("❌ Faltan credenciales. Asegúrate de definir TURSO_URL, TURSO_TOKEN y OPENAI_API_KEY en tu entorno.")
    sys.exit(1)

clean_url = TURSO_URL.replace("libsql://", "https://").replace("http://", "https://")
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
        elif isinstance(arg, dict):
            formatted_args.append(arg)
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
            r = requests.post(pipeline_url, headers=headers, json=payload, timeout=120)
            r.raise_for_status()
            data = r.json()
            
            if data["results"][0]["type"] == "error":
                error_msg = data["results"][0]["error"]["message"]
                if "duplicate column name" in error_msg.lower():
                    raise ValueError(error_msg) # Usamos ValueError para salir del bucle de red
                raise Exception(f"Turso Error: {error_msg}")
                
            result = data["results"][0]["response"]["result"]
            if "cols" not in result:
                return []
                
            cols = [c["name"] for c in result["cols"]]
            rows = []
            for r in result.get("rows", []):
                obj = {}
                for i, col in enumerate(cols):
                    obj[col] = r[i].get("value") if isinstance(r[i], dict) else None
                rows.append(obj)
            return rows
        except ValueError as ve:
            raise Exception(str(ve)) # Re-lanzar para que lo atrape el main
        except Exception as e:
            if "duplicate column name" in str(e).lower():
                raise e
            print(f"   ⚠️ Reintentando consulta a Turso ({e})...")
            time.sleep(5)
            
    raise Exception("❌ No se pudo conectar con Turso tras varios intentos.")

def get_openai_embeddings_batch(texts):
    if not texts:
        return []
    
    # Limitar cada texto a 8000 caracteres
    safe_texts = [t[:8000] for t in texts]
    
    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "input": safe_texts,
                    "model": "text-embedding-3-small"
                },
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                return [item["embedding"] for item in data["data"]]
            else:
                print(f"Error OpenAI Batch: {resp.text}")
                return None
        except Exception as e:
            print(f"   ⚠️ Microcorte de red en OpenAI ({e}). Reintentando en 3 segundos...")
            time.sleep(3)
    return None

import struct
import base64

def pack_vector(vector):
    # vector es una lista de floats. Empaquetar como float32 little-endian
    packed = struct.pack(f"<{len(vector)}f", *vector)
    return base64.b64encode(packed).decode("utf-8")

def turso_batch_update(updates):
    # updates es una lista de diccionarios: {"id": id, "blob_b64": blob_b64}
    requests_list = []
    for up in updates:
        requests_list.append({
            "type": "execute",
            "stmt": {
                "sql": "UPDATE normas SET embedding = ? WHERE id = ?",
                "args": [
                    {"type": "blob", "base64": up["blob_b64"]},
                    {"type": "integer", "value": str(up["id"])}
                ]
            }
        })
    requests_list.append({"type": "close"})
    
    payload = {"requests": requests_list}
    
    for attempt in range(3):
        try:
            r = requests.post(pipeline_url, headers=headers, json=payload, timeout=60)
            r.raise_for_status()
            data = r.json()
            for i, res in enumerate(data.get("results", [])):
                if res["type"] == "error":
                    raise Exception(f"Error en instrucción index {i}: {res['error']['message']}")
            return True
        except Exception as e:
            print(f"   ⚠️ Error en batch Turso ({e}). Reintentando en 3 segundos...")
            time.sleep(3)
    return False

def main():
    print("🚀 Iniciando migración a Búsqueda Semántica Vectorial (Optimizada por Lotes)...")
    
    # 1. Asegurar que la columna 'embedding' existe
    print("1️⃣ Preparando estructura de base de datos en Turso...")
    try:
        turso_query("ALTER TABLE normas ADD COLUMN embedding F32_BLOB(1536)")
        print("   ✅ Columna vectorial creada con éxito.")
    except Exception as e:
        if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
            print("   ℹ️ La columna 'embedding' ya existe.")
        else:
            raise e
            
    total_procesadas_global = 0
    
    while True:
        # 2. Buscar normas que NO tienen embedding (limitadas a 500 por vez para no saturar la red)
        print("\n2️⃣ Buscando siguiente bloque de ordenanzas sin vector semántico...")
        normas = turso_query("SELECT id, numero, titulo, resumen, texto_completo FROM normas WHERE embedding IS NULL LIMIT 500")
        
        if not normas:
            print("   ✅ No quedan más normas por vectorizar. ¡El Digesto está 100% vectorizado!")
            break
            
        total_normas = len(normas)
        print(f"   ⚠️ Encontradas {total_normas} normas en este bloque.")
        
        # 3. Procesar en lotes de 50
        print("3️⃣ Vectorizando y actualizando base de datos en lotes...")
        batch_size = 50
        procesadas = 0
        
        for i in range(0, total_normas, batch_size):
            chunk = normas[i:i+batch_size]
            print(f"\n📦 Procesando lote {i//batch_size + 1} (Normas {i+1} a {min(i+batch_size, total_normas)} de {total_normas})...")
            
            texts = []
            for n in chunk:
                titulo = n["titulo"] or ""
                resumen = n["resumen"] or ""
                texts.append(f"Título: {titulo}\n\nResumen: {resumen}")
                
            print(f"   🤖 Generando {len(chunk)} embeddings en OpenAI...")
            vectors = get_openai_embeddings_batch(texts)
            
            if not vectors or len(vectors) != len(chunk):
                print("   ❌ Falló la generación de vectores para este lote. Saltando...")
                continue
                
            print(f"   💾 Guardando {len(chunk)} vectores en Turso (individualmente para evitar saturación de pipeline)...")
            errores_lote = 0
            for idx, n in enumerate(chunk):
                vector_str = json.dumps(vectors[idx])
                try:
                    turso_query("UPDATE normas SET embedding = vector(?) WHERE id = ?", [vector_str, int(n["id"])])
                    procesadas += 1
                except Exception as e:
                    print(f"   ❌ Error actualizando ID {n['id']} en Turso: {e}")
                    errores_lote += 1
                    
            if errores_lote == 0:
                print(f"   ✅ Lote completado con éxito.")
            else:
                print(f"   ⚠️ Lote completado con {errores_lote} errores.")
                
            # Pausa sutil
            time.sleep(0.5)
            
        total_procesadas_global += procesadas
        
    print(f"\n🎉 ¡Proceso finalizado! {total_procesadas_global} embeddings guardados en total.")

if __name__ == "__main__":
    main()
