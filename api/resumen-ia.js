export default async function handler(req, res) {
  // Habilitar CORS
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  const geminiKey = process.env.GEMINI_API_KEY;
  if (!geminiKey) {
    res.status(500).json({ error: "Falta la variable de entorno GEMINI_API_KEY." });
    return;
  }

  try {
    let body;
    if (req.method === 'POST') {
      body = req.body;
    } else {
      // GET fallback
      body = {
        query: req.query.query || '',
        normas: []
      };
    }

    const { query, normas, estadisticas } = body;

    if (!query) {
      res.status(400).json({ error: "Se requiere un término de búsqueda." });
      return;
    }

    // Construir contexto de normas para el prompt
    let normasContext = '';
    if (normas && normas.length > 0) {
      normasContext = normas.slice(0, 12).map((n, i) =>
        `${i + 1}. ${n.tipo_nombre || 'Norma'} N° ${n.numero || 'S/N'} (${n.fecha || 'sin fecha'}, ${n.vigente ? 'Vigente' : 'No vigente'}): ${(n.titulo || n.resumen || '').substring(0, 200)}`
      ).join('\n');
    }

    // Construir contexto de estadísticas
    let statsContext = '';
    if (estadisticas) {
      if (estadisticas.frecuencia) {
        statsContext += `\nTotal de normas encontradas: ${estadisticas.frecuencia.total}`;
        if (estadisticas.frecuencia.por_tipo) {
          statsContext += `\nDistribución por tipo: ${estadisticas.frecuencia.por_tipo.map(t => `${t.tipo}: ${t.cantidad}`).join(', ')}`;
        }
      }
      if (estadisticas.timeline && estadisticas.timeline.length > 0) {
        statsContext += `\nDistribución temporal: ${estadisticas.timeline.map(t => `${t.anio}: ${t.cantidad}`).join(', ')}`;
      }
    }

    // Prompt estructurado para Gemini
    const prompt = `Eres un analista jurídico especializado en legislación municipal argentina. Tu tarea es analizar normas del Digesto Municipal de Alta Gracia, Córdoba, Argentina.

El usuario buscó: "${query}"

${statsContext ? `ESTADÍSTICAS DE LA BÚSQUEDA:${statsContext}` : ''}

${normasContext ? `NORMAS ENCONTRADAS:\n${normasContext}` : 'No se proporcionaron normas específicas.'}

Genera un RESUMEN EJECUTIVO en español (máximo 4 párrafos cortos) que incluya:
1. **Panorama general**: Qué revelan estos resultados sobre el tema "${query}" en la normativa de Alta Gracia
2. **Patrones detectados**: Tendencias temporales, tipos de norma predominantes, o concentración en categorías
3. **Aspectos relevantes**: Hallazgos importantes o conexiones interesantes entre las normas
4. **Contexto**: Breve contexto de por qué este tema es relevante para la gestión municipal

Usa un tono profesional pero accesible. No uses listas con viñetas, escribe en prosa fluida. No menciones que eres una IA.`;

    // Llamar a la API REST de Gemini
    const geminiUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${geminiKey}`;

    const geminiResponse = await fetch(geminiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{
          parts: [{ text: prompt }]
        }],
        generationConfig: {
          temperature: 0.7,
          maxOutputTokens: 800,
          topP: 0.9
        }
      })
    });

    if (!geminiResponse.ok) {
      const errText = await geminiResponse.text();
      throw new Error(`Error en Gemini API: ${geminiResponse.status} - ${errText}`);
    }

    const geminiData = await geminiResponse.json();

    // Extraer texto de la respuesta de Gemini
    let resumen = 'No se pudo generar el resumen.';
    if (geminiData.candidates && geminiData.candidates[0] && geminiData.candidates[0].content) {
      const parts = geminiData.candidates[0].content.parts;
      if (parts && parts[0]) {
        resumen = parts[0].text;
      }
    }

    res.status(200).json({ resumen });

  } catch (error) {
    console.error("Error en resumen IA:", error);
    res.status(500).json({ error: error.message });
  }
}
