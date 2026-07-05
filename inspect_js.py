import json
import os

transcript_path = r"C:\Users\Fedeparisi\.gemini\antigravity\brain\25cb2825-fab3-4e23-89b5-2cc5da115a9f\.system_generated\logs\transcript.jsonl"

if os.path.exists(transcript_path):
    print("Buscando en el transcript.jsonl...")
    with open(transcript_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            try:
                step = json.loads(line)
                content = step.get("content", "")
                # Buscar keywords como build.js, descargar, drive en el contenido del transcript
                if any(kw in str(content).lower() for kw in ["build.js", "descarga", "drive", "google"]):
                    print(f"\n--- Coincidencia en linea {i+1} ---")
                    # Mostrar fragmentos relevantes
                    for line_c in str(content).split("\n"):
                        if any(kw in line_c.lower() for kw in ["drive", "descarg", "google", "file", "api/"]):
                            print(line_c.strip()[:180])
            except Exception as e:
                pass
else:
    print("No se encontro transcript.jsonl")
