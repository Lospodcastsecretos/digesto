import http.server
import socketserver
import os
import sys
import json
import webbrowser

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PORT = 8000
DATA_FILE = r"output\digesto_completo_enriquecido.json"
DOWNLOADS_DIR = r"output\descargas"

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # 1. Endpoint para servir el JSON de datos en /api/datos
        if self.path == '/api/datos':
            if os.path.exists(DATA_FILE):
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                with open(DATA_FILE, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "Base de datos JSON no encontrada.")
            return

        # 2. Servir los archivos fisicos de descargas (PDFs, DOCXs, DOCs) en /descargas/...
        if self.path.startswith('/descargas/'):
            filename = self.path.replace('/descargas/', '')
            # Decodificar caracteres especiales de la URL (ej: %20 -> espacio)
            filename = urllib.parse.unquote(filename) if 'urllib' in sys.modules else filename.replace('%20', ' ')
            filepath = os.path.join(DOWNLOADS_DIR, filename)
            
            if os.path.exists(filepath):
                self.send_response(200)
                # Detectar content-type
                if filename.lower().endswith('.pdf'):
                    self.send_header('Content-type', 'application/pdf')
                elif filename.lower().endswith('.docx'):
                    self.send_header('Content-type', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
                elif filename.lower().endswith('.doc'):
                    self.send_header('Content-type', 'application/msword')
                else:
                    self.send_header('Content-type', 'application/octet-stream')
                
                self.end_headers()
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, f"Archivo no encontrado en descargas: {filename}")
            return

        # 3. Servir el index.html por defecto
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            with open(r'buscador\index.html', 'rb') as f:
                self.wfile.write(f.read())
            return

        # Para cualquier otra ruta, usar el comportamiento por defecto
        super().do_GET()

# Importar urllib en caso de que sea necesario decodificar URL
import urllib.parse

print(f"Iniciando el servidor del Buscador Inteligente en http://localhost:{PORT}")
print("Puedes buscar tus ordenanzas por nro, palabras del titulo o resumen.")
print("Al hacer clic en 'Ver Documento' se abrira el archivo descargado localmente.")

# Iniciar servidor y abrir navegador
with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
    # Abrir navegador automaticamente
    webbrowser.open(f"http://localhost:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido por el usuario.")
