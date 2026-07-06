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
  const stopWords = new Set(['que', 'es', 'el', 'la', 'los', 'las', 'un', 'una', 'de', 'del', 'para', 'por', 'sobre', 'como', 'con', 'en', 'y', 'o', 'a', 'al', 'su', 'sus', 'te', 'tu', 'mi', 'se', 'lo', 'le']);
  const words = message.toLowerCase().replace(/[^a-záéíóúñü\s0-9]/g, '').split(/\s+/);
  
  // Mantener palabras de >= 3 letras que no sean stop words
  const relevantWords = words.filter(w => w.length >= 3 && !stopWords.has(w));
  
  // Agregar wildcard '*' a cada palabra y unirlas con OR para máxima flexibilidad en FTS5
  const keywords = relevantWords.map(w => `"${w}"*`).join(' OR ');

  let contextText = "No se encontraron normas específicas relacionadas con la pregunta actual.";

  // 2. Buscar en Turso si hay keywords (RAG)
  if (keywords.length > 0) {
    try {
      // Buscar en FTS5 las 4 normas mas relevantes (incluyendo texto completo)
      const searchSql = `
        SELECT id, numero, titulo, resumen, tipo_nombre, fecha, texto_completo
        FROM normas 
        WHERE id IN (SELECT id FROM normas_fts WHERE normas_fts MATCH ?) 
        ORDER BY rank LIMIT 4
      `;
      const normasRows = await tursoQuery(searchSql, [keywords]);
      
      if (normasRows.length > 0) {
        contextText = normasRows.map(n => {
          const textoDetalle = (n.texto_completo || n.resumen || "").substring(0, 2000);
          return `Norma: ${n.tipo_nombre} ${n.numero}\nFecha: ${n.fecha}\nTítulo: ${n.titulo}\nTexto de la Norma:\n${textoDetalle}...`;
        }).join("\n\n---\n\n");
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

  const systemPrompt = `Eres Burocracio, un asistente jurídico virtual amigable, claro y resolutivo para el Digesto Municipal (un buscador de leyes y ordenanzas locales). Tu objetivo es ayudar a los ciudadanos y funcionarios a entender normativas basándote en la base de datos oficial.

REGLAS DE COMPORTAMIENTO:
1. Sé amable, directo y evita lenguaje excesivamente técnico si no es necesario.
2. Si la base de datos te provee contexto (normas encontradas), basa tu respuesta ESTRICTAMENTE en esa información. Cita el número de norma (ej. "Según la Ordenanza 1234...").
3. Si la base de datos NO provee información sobre la pregunta, indica amablemente que no tienes información exacta sobre ese tema en el digesto actual, pero ofrece ayuda con otros temas. No inventes leyes.
4. Usa formato Markdown (negritas para destacar cosas importantes, viñetas para listas) para que sea fácil de leer.
5. Mantén tus respuestas relativamente cortas (máximo 2-3 párrafos cortos). No te presentes con tu nombre a menos que el usuario te pregunte quién eres.

CONTEXTO DE NORMAS ENCONTRADAS PARA LA PREGUNTA ACTUAL:
${contextText}

HISTORIAL DE LA CONVERSACIÓN RECIENTE:
${promptHistory}

PREGUNTA ACTUAL DEL CIUDADANO:
${message}

Tu respuesta (como asistente jurídico del municipio):`;

  // 4. Llamar a Motores Multi-IA (DeepSeek / Groq)
  const groqKey = process.env.GROQ_API_KEY || "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";
  const deepseekKey = process.env.DEEPSEEK_API_KEY || "sk-854124346ef84affbb67479c276b2554";
  
  let reply = 'Hubo un error al procesar tu consulta.';

  try {
    // Intento 1: DeepSeek (Más inteligente para razonamiento legal)
    const dsResp = await fetch("https://api.deepseek.com/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${deepseekKey}` },
      body: JSON.stringify({
        model: "deepseek-chat",
        messages: [
          { role: "system", content: systemPrompt },
          { role: "user", content: message }
        ],
        temperature: 0.2,
        max_tokens: 1500
      })
    });

    if (dsResp.ok) {
      const data = await dsResp.json();
      reply = data.choices[0].message.content;
    } else {
      console.warn("Fallo DeepSeek, intentando con Groq...");
      throw new Error("DeepSeek falló");
    }
  } catch (errDeepSeek) {
    try {
      // Intento 2: Fallback a Groq (Llama 3 ultrarrápido)
      const groqResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${groqKey}` },
        body: JSON.stringify({
          model: "llama3-8b-8192",
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: message }
          ],
          temperature: 0.2,
          max_tokens: 1500
        })
      });

      if (!groqResp.ok) {
        throw new Error("Ambos proveedores (DeepSeek y Groq) fallaron.");
      }
      
      const data = await groqResp.json();
      reply = data.choices[0].message.content;
    } catch (errGroq) {
      console.error("Error en API de Chat Multi-IA:", errGroq);
      res.status(500).json({ error: "Error interno: " + errGroq.message });
      return;
    }
  }

  res.status(200).json({ reply });
}
