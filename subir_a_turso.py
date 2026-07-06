import os
import sys
import json
import asyncio
import libsql_client

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DATA_FILE = r"output\digesto_completo_enriquecido.json"
TURSO_URL = "https://digesto-lospodcastsecretos.aws-us-west-2.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODMyODgxMjQsImlkIjoiMDE5ZjM0NDAtN2UwMS03OTljLWFlOTItODBiMDJmNmVhMjdlIiwia2lkIjoiZ0JFblIyNVR6dEEwaHVWWXljOS03cnRzYThUaGRnbmFEd1ZHSXJrR3FPYyIsInJpZCI6ImE1MGUwMDBmLTQ4ZTgtNDg1ZS04MmM0LTEzNGIxYTA4MmJhYSJ9.ev1b_OISV20t8e9brtO7O4oU9bGnrPYum1LTbBiVng-gaPC2YiUsHzFe-ok2aXmVePtRNYtAmKpb0ntWL6xSCA"

if not os.path.exists(DATA_FILE):
    print("Error: No se encontro el archivo JSON enriquecido de normas.")
    sys.exit(1)

with open(DATA_FILE, "r", encoding="utf-8") as f:
    normas = json.load(f)

print(f"Cargadas {len(normas)} normas para subir a Turso.")

async def main():
    print(f"Conectando a Turso en: {TURSO_URL}...")
    async with libsql_client.create_client(url=TURSO_URL, auth_token=TURSO_TOKEN) as client:
        # 1. Crear la tabla de normas si no existe
        print("Creando la tabla 'normas'...")
        await client.execute("""
            CREATE TABLE IF NOT EXISTS normas (
                id INTEGER PRIMARY KEY,
                numero TEXT,
                titulo TEXT,
                resumen TEXT,
                tipo_nombre TEXT,
                categoria_nombre TEXT,
                vigente INTEGER,
                fecha TEXT,
                archivo_pdf TEXT,
                url_detalle TEXT
            )
        """)
        
        # Limpiar registros
        print("Limpiando registros existentes...")
        await client.execute("DELETE FROM normas")
        
        # 2. Subir en lotes de 200 normas controlando colisiones de ID
        lote_size = 200
        total_subido = 0
        ids_insertados = set()
        
        # Llevar un contador auxiliar para cuando colisionen los IDs
        max_id_local = max(n.get("id") or 0 for n in normas) + 1000
        
        print("\nSubiendo datos masivamente a Turso en lotes...")
        for i in range(0, len(normas), lote_size):
            lote = normas[i:i+lote_size]
            statements = []
            
            for idx, n in enumerate(lote):
                norma_id = n.get("id")
                
                # Controlar colision de ID unico
                if not norma_id or norma_id in ids_insertados:
                    norma_id = max_id_local
                    max_id_local += 1
                
                ids_insertados.add(norma_id)
                es_vigente = 1 if n.get("vigente") is True or str(n.get("vigente")).lower() == 'vigente' else 0
                
                sql = "INSERT INTO normas (id, numero, titulo, resumen, tipo_nombre, categoria_nombre, vigente, fecha, archivo_pdf, url_detalle) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                params = (
                    norma_id,
                    n.get("numero"),
                    n.get("titulo"),
                    n.get("resumen"),
                    n.get("tipo_nombre", "Ordenanza"),
                    n.get("categoria_nombre", "General"),
                    es_vigente,
                    n.get("fecha"),
                    n.get("archivo_pdf"),
                    n.get("url_detalle")
                )
                statements.append(libsql_client.Statement(sql, params))
            
            # Ejecutar lote
            await client.batch(statements)
            total_subido += len(lote)
            print(f" -> Lote completado. Subidas: {total_subido}/{len(normas)} normas.")
            
    print("\n¡Felicidades! Se ha subido la base de datos completa a tu Turso Cloud Database.")

if __name__ == "__main__":
    asyncio.run(main())
