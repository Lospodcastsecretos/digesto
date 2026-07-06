import http.server
import socketserver
import json
import urllib.parse
import sys
import os
import requests

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PORT = 8000
DIRECTORY = "buscador"
TURSO_URL = "https://digesto-lospodcastsecretos.aws-us-west-2.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODMyODgxMjQsImlkIjoiMDE5ZjM0NDAtN2UwMS03OTljLWFlOTItODBiMDJmNmVhMjdlIiwia2lkIjoiZ0JFblIyNVR6dEEwaHVWWXljOS03cnRzYThUaGRnbmFEd1ZHSXJrR3FPYyIsInJpZCI6ImE1MGUwMDBmLTQ4ZTgtNDg1ZS04MmM0LTEzNGIxYTA4MmJhYSJ9.ev1b_OISV20t8e9brtO7O4oU9bGnrPYum1LTbBiVng-gaPC2YiUsHzFe-ok2aXmVePtRNYtAmKpb0ntWL6xSCA"

class MyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        if self.path.startswith('/api/buscar'):
            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)
            
            query = params.get('query', [''])[0]
            tipo = params.get('tipo', ['todos'])[0]
            categoria = params.get('categoria', ['todas'])[0]
            anio = params.get('anio', ['todos'])[0]
            vigencia = params.get('vigencia', ['todos'])[0]
            page = int(params.get('page', [1])[0])
            
            items_per_page = 15
            offset = (page - 1) * items_per_page
            
            sql = "SELECT * FROM normas WHERE 1=1"
            sql_params = []
            
            if query:
                sql += " AND (lower(numero) LIKE ? OR lower(titulo) LIKE ? OR lower(resumen) LIKE ?)"
                like_q = f"%{query.lower()}%"
                sql_params.append({"type": "text", "value": like_q})
                sql_params.append({"type": "text", "value": like_q})
                sql_params.append({"type": "text", "value": like_q})
                
            if tipo != 'todos':
                sql += " AND tipo_nombre = ?"
                sql_params.append({"type": "text", "value": tipo})
                
            if categoria != 'todas':
                sql += " AND categoria_nombre = ?"
                sql_params.append({"type": "text", "value": categoria})
                
            if anio != 'todos':
                sql += " AND fecha = ?"
                sql_params.append({"type": "text", "value": f"Año {anio}"})
                
            if vigencia != 'todos':
                is_vigente = "1" if vigencia == 'si' else "0"
                sql += " AND vigente = ?"
                sql_params.append({"type": "text", "value": is_vigente})
                
            count_sql = sql.replace("SELECT *", "SELECT COUNT(*) as total")
            
            sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
            sql_params_query = list(sql_params)
            sql_params_query.append({"type": "text", "value": str(items_per_page)})
            sql_params_query.append({"type": "text", "value": str(offset)})
            
            try:
                headers = {
                    "Authorization": f"Bearer {TURSO_TOKEN}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "requests": [
                        {"type": "execute", "stmt": {"sql": count_sql, "args": sql_params}},
                        {"type": "execute", "stmt": {"sql": sql, "args": sql_params_query}}
                    ]
                }
                
                response = requests.post(f"{TURSO_URL}/v2/pipeline", headers=headers, json=payload, timeout=15)
                
                if response.status_code == 200:
                    res_data = response.json()
                    
                    count_rows = res_data["results"][0]["response"]["result"]["rows"]
                    total_items = int(count_rows[0][0]["value"]) if count_rows else 0
                    
                    rows = res_data["results"][1]["response"]["result"]["rows"]
                    cols = [c["name"] for c in res_data["results"][1]["response"]["result"]["cols"]]
                    
                    normas = []
                    for r in rows:
                        row_vals = [val["value"] for val in r]
                        row_dict = dict(zip(cols, row_vals))
                        normas.append({
                            "id": int(row_dict.get("id", 0)),
                            "numero": row_dict.get("numero"),
                            "titulo": row_dict.get("titulo"),
                            "resumen": row_dict.get("resumen"),
                            "tipo_nombre": row_dict.get("tipo_nombre"),
                            "categoria_nombre": row_dict.get("categoria_nombre"),
                            "vigente": int(row_dict.get("vigente", 1)) == 1,
                            "fecha": row_dict.get("fecha"),
                            "archivo_pdf": row_dict.get("archivo_pdf"),
                            "url_detalle": row_dict.get("url_detalle")
                        })
                        
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.end_headers()
                    
                    result_json = {
                        "normas": normas,
                        "total": total_items,
                        "page": page,
                        "totalPages": int(total_items / items_per_page) + 1
                    }
                    self.wfile.write(json.dumps(result_json, ensure_ascii=False).encode('utf-8'))
                else:
                    self.send_error(500, f"Error de Turso: {response.text}")
            except Exception as e:
                self.send_error(500, f"Excepcion del servidor local: {str(e)}")
            return
            
        elif self.path.startswith('/descargas/'):
            # CORRECCIÓN: Los archivos locales están en 'output/descargas/' no en 'descargas/'
            filename = urllib.parse.unquote(self.path[11:])
            filepath = os.path.join("output", "descargas", filename)
            
            if os.path.exists(filepath):
                self.send_response(200)
                if filepath.lower().endswith(".pdf"):
                    self.send_header('Content-Type', 'application/pdf')
                elif filepath.lower().endswith(".docx"):
                    self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
                self.end_headers()
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, f"Archivo no encontrado localmente: {filepath}")
            return

        return super().do_GET()

handler = MyHandler
print(f"Iniciando servidor local del Digesto conectado a Turso Cloud en: http://localhost:{PORT}")
with socketserver.TCPServer(("", PORT), handler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor cerrado.")
        httpd.server_close()
