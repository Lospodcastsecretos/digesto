export default async function handler(req, res) {
  // Habilitar CORS
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }
  if (req.method !== 'POST') { res.status(405).json({ error: "Method not allowed" }); return; }

  const url = process.env.TURSO_URL;
  const authToken = process.env.TURSO_TOKEN;
  const geminiKey = process.env.GEMINI_API_KEY;

  if (!url || !authToken || !geminiKey) {
    res.status(500).json({ error: "Faltan variables de entorno." });
    return;
  }

  const cleanUrl = url.replace("libsql://", "https://").replace("http://", "https://");
  const pipelineUrl = `${cleanUrl}/v2/pipeline`;

  const { message, history } = req.body;
  if (!message) {
    res.status(400).json({ error: "Mensaje vacío" });
    return;
  }

  const formatArgs = (args) => args.map(arg => {
    if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
    return { type: 'text', value: arg.toString() };
  });

  async function tursoQuery(sql, params = []) {
    const body = {
      requests: [
        { type: "execute", stmt: { sql, args: formatArgs(params) } },
        { type: "close" }
      ]
    };
    const resp = await fetch(pipelineUrl, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!resp.ok) return [];
    const data = await resp.json();
    const result = data.results[0];
    if (result.type === 'error') return [];

    const cols = result.response.result.cols.map(c => c.name);
    return result.response.result.rows.map(row => {
      const obj = {};
      cols.forEach((col, i) => { obj[col] = row[i] ? row[i].value : null; });
      return obj;
    });
  }

  // 1. Extraer palabras clave de la pregunta para buscar en Turso
  const stopWords = ['que', 'es', 'el', 'la', 'los', 'las', 'un', 'una', 'de', 'del', 'para', 'por', 'sobre', 'como', 'con'];
  const words = message.toLowerCase().replace(/[^a-záéíóúñü\s]/g, '').split(' ');
  const keywords = words.filter(w => w.length > 3 && !stopWords.includes(w)).join(' OR ');

  let contextText = "No se encontraron normas específicas relacionadas con la pregunta actual.";

  // 2. Buscar en Turso si hay keywords (RAG)
  if (keywords.length > 0) {
    try {
      // Buscar en FTS5 las 4 normas mas relevantes
      const searchSql = `
        SELECT id, numero, titulo, resumen, tipo_nombre, fecha
        FROM normas 
        WHERE id IN (SELECT id FROM normas_fts WHERE normas_fts MATCH ?) 
        ORDER BY rank LIMIT 4
      `;
      const normasRows = await tursoQuery(searchSql, [keywords]);
      
      if (normasRows.length > 0) {
        contextText = normasRows.map(n => 
          `Norma: ${n.tipo_nombre} ${n.numero}\nFecha: ${n.fecha}\nTítulo: ${n.titulo}\nResumen: ${n.resumen}`
        ).join("\n\n");
      }
    } catch (e) {
      console.error("Error buscando contexto RAG:", e);
    }
  }

  // 3. Preparar el Prompt para Gemini
  let promptHistory = "";
  if (history && Array.isArray(history)) {
    // Tomar solo los últimos 6 mensajes para no sobrecargar
    const recentHistory = history.slice(-6);
    promptHistory = recentHistory.map(msg => `${msg.role === 'user' ? 'Ciudadano' : 'Asistente'}: ${msg.content}`).join('\n');
  }

  const systemPrompt = `Eres un asistente jurídico virtual amigable, claro y resolutivo para el Digesto Municipal (un buscador de leyes y ordenanzas locales). Tu objetivo es ayudar a los ciudadanos y funcionarios a entender normativas basándote en la base de datos oficial.

REGLAS DE COMPORTAMIENTO:
1. Sé amable, directo y evita lenguaje excesivamente técnico si no es necesario.
2. Si la base de datos te provee contexto (normas encontradas), basa tu respuesta ESTRICTAMENTE en esa información. Cita el número de norma (ej. "Según la Ordenanza 1234...").
3. Si la base de datos NO provee información sobre la pregunta, indica amablemente que no tienes información exacta sobre ese tema en el digesto actual, pero ofrece ayuda con otros temas. No inventes leyes.
4. Usa formato Markdown (negritas para destacar cosas importantes, viñetas para listas) para que sea fácil de leer.
5. Mantén tus respuestas relativamente cortas (máximo 2-3 párrafos cortos).

CONTEXTO DE NORMAS ENCONTRADAS PARA LA PREGUNTA ACTUAL:
${contextText}

HISTORIAL DE LA CONVERSACIÓN RECIENTE:
${promptHistory}

PREGUNTA ACTUAL DEL CIUDADANO:
${message}

Tu respuesta (como asistente jurídico del municipio):`;

  // 4. Llamar a Gemini API
  try {
    const urlGemini = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${geminiKey}`;
    
    let geminiResponse = await fetch(urlGemini, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-goog-api-key': geminiKey },
      body: JSON.stringify({
        contents: [{ parts: [{ text: systemPrompt }] }],
        generationConfig: { temperature: 0.3, maxOutputTokens: 1500 }
      })
    });

    if (!geminiResponse.ok) {
      // Fallback a 3.5 flash si falla por permisos
      const fallbackUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=${geminiKey}`;
      geminiResponse = await fetch(fallbackUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-goog-api-key': geminiKey },
        body: JSON.stringify({
          contents: [{ parts: [{ text: systemPrompt }] }],
          generationConfig: { temperature: 0.3, maxOutputTokens: 1500 }
        })
      });
    }

    if (!geminiResponse.ok) {
      throw new Error("Ambos modelos fallaron: " + await geminiResponse.text());
    }

    const data = await geminiResponse.json();
    let reply = 'Hubo un error al procesar tu consulta.';
    if (data.candidates && data.candidates[0] && data.candidates[0].content) {
      reply = data.candidates[0].content.parts[0].text;
    }

    res.status(200).json({ reply });
  } catch (error) {
    console.error("Error en API de Chat:", error);
    res.status(500).json({ error: "Error al generar la respuesta del asistente." });
  }
}
