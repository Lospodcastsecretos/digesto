import mammoth

# Convertir el archivo Word a Markdown conservando tablas y jerarquía
with open("output/digesto_consolidado_word.docx", "rb") as docx_file:
    result = mammoth.convert_to_markdown(docx_file)
    markdown = result.value
    
    # Escribir los primeros 10000 caracteres para inspección
    print("Longitud total de Markdown generado:", len(markdown))
    print("\n--- Primeras líneas de Markdown ---")
    lines = markdown.split("\n")
    for i, line in enumerate(lines[:100]):
        if line.strip():
            print(f"[{i}] {line}")
            
    # Guardar una parte para inspección en un archivo
    with open("scratch/preview.md", "w", encoding="utf-8") as preview_file:
        preview_file.write(markdown[:100000]) # Primeros 100k caracteres
