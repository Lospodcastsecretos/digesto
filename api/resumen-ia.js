export default async function handler(req, res) {
  // Habilitar CORS
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, x-goog-api-key');

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
      body = {
        query: req.query.query || '',
        modo: req.query.modo || '',
        normas: []
      };
    }

    const { query, normas, estadisticas, modo, relacionadas, keywords } = body;

    if (!query) {
      res.status(400).json({ error: "Se requiere un término de búsqueda." });
      return;
    }

    // Construir contexto de normas
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

    let prompt;

    if (modo === 'conexiones') {
      let relacionadasContext = '';
      if (relacionadas && relacionadas.length > 0) {
        relacionadasContext = relacionadas.slice(0, 10).map((r, i) =>
          `${i + 1}. ${r.tipo_nombre || 'Norma'} N° ${r.numero || 'S/N'} — Categoría: ${r.categoria_nombre || 'General'} — "${(r.titulo || '').substring(0, 150)}"`
        ).join('\n');
      }

      let keywordsContext = '';
      if (keywords && keywords.length > 0) {
        keywordsContext = keywords.slice(0, 15).map(k => `"${k.palabra}" (${k.frecuencia} apariciones)`).join(', ');
      }

      prompt = `Eres un analista jurídico experto en legislación municipal argentina del Digesto de Alta Gracia, Córdoba.

El usuario realizó una búsqueda con el término: "${query}"

DATOS DEL ANÁLISIS:
${statsContext}

${normasContext ? `NORMAS PRINCIPALES ENCONTRADAS:\n${normasContext}` : ''}

${relacionadasContext ? `NORMAS RELACIONADAS SUGERIDAS:\n${relacionadasContext}` : ''}

${keywordsContext ? `PALABRAS CLAVE MÁS FRECUENTES EN LOS RESULTADOS: ${keywordsContext}` : ''}

Tu tarea es generar un ANÁLISIS DE CONEXIONES detallado en español (máximo 5 párrafos) que explique:
1. ¿Por qué estas normas relacionadas tienen vínculo con "${query}"?
2. ¿Qué revelan las palabras clave?
3. ¿Qué significa la distribución temporal?
4. ¿Qué relación hay entre los tipos de norma?
5. Conclusión integradora: Un párrafo final.

Usá negritas para destacar conceptos. No menciones que sos una IA.`;

    } else {
      prompt = `Eres un analista jurídico especializado en legislación municipal. El usuario buscó: "${query}"

${statsContext ? `ESTADÍSTICAS:\n${statsContext}` : ''}
${normasContext ? `NORMAS:\n${normasContext}` : ''}

Genera un RESUMEN EJECUTIVO en español (máximo 4 párrafos cortos):
1. Panorama general sobre el tema en Alta Gracia
2. Patrones detectados (tipos, años)
3. Aspectos relevantes
4. Contexto municipal

Usá negritas. No menciones que eres una IA.`;
    }

    // Usar Fetch puro para evitar problemas con librerías en Vercel
    // Si la clave empieza con AQ... la enviamos tanto en query string como en header por seguridad
    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=${geminiKey}`;
    
    const geminiResponse = await fetch(url, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'x-goog-api-key': geminiKey 
      },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: {
          temperature: 0.7,
          maxOutputTokens: modo === 'conexiones' ? 2500 : 2048
        }
      })
    });

    if (!geminiResponse.ok) {
      const errText = await geminiResponse.text();
      // Si falla, intentamos usar gemini-1.5-flash como último recurso
      console.log("Fallo con 3.5-flash, error:", errText);
      const fallbackUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${geminiKey}`;
      const fallbackResponse = await fetch(fallbackUrl, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'x-goog-api-key': geminiKey 
        },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: { temperature: 0.7, maxOutputTokens: 2048 }
        })
      });

      if (!fallbackResponse.ok) {
        throw new Error(`Error en API: ${fallbackResponse.status} - ${await fallbackResponse.text()}`);
      }

      const fbData = await fallbackResponse.json();
      res.status(200).json({ resumen: fbData.candidates[0].content.parts[0].text, modelo: 'gemini-1.5-flash (Fetch Fallback)' });
      return;
    }

    const geminiData = await geminiResponse.json();

    let resumen = 'No se pudo generar el resumen.';
    if (geminiData.candidates && geminiData.candidates[0] && geminiData.candidates[0].content) {
      resumen = geminiData.candidates[0].content.parts[0].text;
    }

    res.status(200).json({ resumen, modelo: 'gemini-3.5-flash (Fetch Puro)' });

  } catch (error) {
    console.error("Error en resumen IA:", error);
    res.status(500).json({ error: error.message });
  }
}
