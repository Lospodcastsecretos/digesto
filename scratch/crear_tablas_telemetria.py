import os
import sqlite3
import requests
from dotenv import load_dotenv

load_dotenv()

TURSO_URL = os.environ.get("TURSO_URL", "").replace("libsql://", "https://")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN")

if not TURSO_URL or not TURSO_TOKEN:
    print("❌ Error: Faltan las variables de entorno TURSO_URL o TURSO_TOKEN.")
    exit(1)

def ejecutar_query(sql, parametros=None):
    url = f"{TURSO_URL}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }
    
    stmt = {"sql": sql}
    if parametros:
        # Reemplazar placeholders paramétricos con argumentos posicionales simples de SQLite
        stmt["args"] = parametros
    
    data = {
        "requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"}
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Error ejecutando SQL: {sql}")
        print(f"Detalle: {e}")
        if 'response' in locals() and response.content:
             print(f"Respuesta API: {response.text}")
        return None

def crear_tablas():
    print("Creando tabla de telemetria: consultas_log...")
    sql_log = """
    CREATE TABLE IF NOT EXISTS consultas_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        tipo_consulta TEXT NOT NULL, -- 'chat' o 'informe'
        query_text TEXT NOT NULL,
        cache_hit BOOLEAN DEFAULT 0,
        duracion_ms INTEGER,
        tokens_prompt INTEGER,
        tokens_respuesta INTEGER
    );
    """
    res_log = ejecutar_query(sql_log)
    if res_log:
         print("Tabla 'consultas_log' verificada/creada exitosamente.")
    else:
         print("Fallo al crear tabla 'consultas_log'.")

    print("\nCreando indices de rendimiento...")
    sql_index1 = "CREATE INDEX IF NOT EXISTS idx_consultas_timestamp ON consultas_log(timestamp);"
    sql_index2 = "CREATE INDEX IF NOT EXISTS idx_consultas_tipo ON consultas_log(tipo_consulta);"
    ejecutar_query(sql_index1)
    ejecutar_query(sql_index2)
    print("Indices de telemetria creados.")
    
    print("\nListo. Tablas e indices de telemetria creados en Turso.")

if __name__ == "__main__":
    crear_tablas()
