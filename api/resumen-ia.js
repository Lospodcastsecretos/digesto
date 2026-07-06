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

      prompt = `Eres un analista jurídico experto en la legislación de Alta Gracia, Córdoba.
El usuario buscó: "${query}"

DATOS:
${statsContext}
${normasContext ? `NORMAS:\n${normasContext}` : ''}
${relacionadasContext ? `RELACIONADAS:\n${relacionadasContext}` : ''}
${keywordsContext ? `PALABRAS CLAVE: ${keywordsContext}` : ''}

Tu tarea es generar un INFORME DE CONEXIONES extremadamente conciso, directo y al grano (máximo 3 párrafos o bloques cortos de viñetas):
- Explica sintéticamente en 1 o 2 oraciones breves por qué se conectan las normas sugeridas con "${query}".
- Explica en 1 o 2 oraciones breves la tendencia de las palabras clave y años.
- Conclusión integradora de 1 o 2 líneas.

REGLAS CRÍTICAS:
- Sé extremadamente escueto. Ve directo a los datos sin rodeos, introducciones o saludos.
- Usa oraciones cortas y de lectura rápida.
- Usá negritas para destacar. No menciones que sos una IA.`;

    } else {
      prompt = `Eres un analista jurídico. El usuario buscó: "${query}"
${statsContext ? `ESTADÍSTICAS:\n${statsContext}` : ''}
${normasContext ? `NORMAS:\n${normasContext}` : ''}

Genera un resumen muy breve en 2 párrafos cortos sobre el tema.`;
    }

    const groqKey = process.env.GROQ_API_KEY || "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";
    const deepseekKey = process.env.DEEPSEEK_API_KEY || "sk-854124346ef84affbb67479c276b2554";
    let resumen = 'No se pudo generar el resumen.';

    try {
      // Intento 1: DeepSeek
      const dsResp = await fetch("https://api.deepseek.com/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${deepseekKey}` },
        body: JSON.stringify({
          model: "deepseek-chat",
          messages: [{ role: "user", content: prompt }],
          temperature: 0.3,
          max_tokens: 3000
        })
      });

      if (dsResp.ok) {
        const data = await dsResp.json();
        resumen = data.choices[0].message.content;
        res.status(200).json({ resumen, modelo: 'DeepSeek (Principal)' });
        return;
      } else {
        throw new Error("Fallo DeepSeek");
      }
    } catch (errDeepSeek) {
      try {
        // Intento 2: Groq
        const groqResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Authorization": `Bearer ${groqKey}` },
          body: JSON.stringify({
            model: "llama3-8b-8192",
            messages: [{ role: "user", content: prompt }],
            temperature: 0.3,
            max_tokens: 3000
          })
        });

        if (!groqResp.ok) throw new Error("Fallo Groq");
        
        const data = await groqResp.json();
        resumen = data.choices[0].message.content;
        res.status(200).json({ resumen, modelo: 'Groq (Respaldo)' });
        return;
      } catch (errGroq) {
        throw new Error(`Ambos fallaron. Groq: ${errGroq.message}`);
      }
    }

  } catch (error) {
    console.error("Error en resumen IA:", error);
    res.status(500).json({ error: error.message });
  }
}
