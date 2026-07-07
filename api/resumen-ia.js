export default async function handler(req, res) {
  // Habilitar CORS
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, x-goog-api-key');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  const geminiKey = process.env.GEMINI_API_KEY;
  const url = process.env.TURSO_URL;
  const authToken = process.env.TURSO_TOKEN;

  if (!geminiKey || !url || !authToken) {
    res.status(500).json({ error: "Faltan variables de entorno esenciales (GEMINI_API_KEY, TURSO_URL o TURSO_TOKEN)." });
    return;
  }

  const cleanUrl = url.replace("libsql://", "https://").replace("http://", "https://");
  const pipelineUrl = `${cleanUrl}/v2/pipeline`;

  const formatArgs = (args) => args.map(arg => {
    if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
    return { type: 'text', value: arg.toString() };
  });

  async function tursoQuery(sql, params = []) {
    const payload = {
      requests: [
        { type: "execute", stmt: { sql, args: formatArgs(params) } },
        { type: "close" }
      ]
    };
    const r = await fetch(pipelineUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${authToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });
    if (!r.ok) {
      const errTxt = await r.text();
      throw new Error(`Turso Error: ${errTxt}`);
    }
    const data = await r.json();
    const result = data.results[0];
    if (result.type === "error") {
      throw new Error(result.error.message);
    }
    
    const resVal = result.response.result;
    const cols = resVal.cols.map(c => c.name);
    return resVal.rows.map(rVal => {
      const row = {};
      rVal.forEach((val, idx) => {
        row[cols[idx]] = val ? val.value : null;
      });
      return row;
    });
  }

  try {
    let body;
    if (req.method === 'POST') {
      body = req.body;
    } else {
      body = {
        query: req.query.query || '',
        modo: req.query.modo || '',
        normaId: req.query.normaId || null,
        normas: []
      };
    }

    const { query, normas, estadisticas, modo, relacionadas, keywords, normaId } = body;

    // CASO NUEVO: Resumir norma individual con caché persistente
    if (normaId) {
      const rows = await tursoQuery(
        "SELECT id, numero, titulo, resumen, tipo_nombre, texto_completo, resumen_ia FROM normas WHERE id = ?",
        [normaId]
      );
      if (rows.length === 0) {
        res.status(404).json({ error: "No se encontró la norma solicitada." });
        return;
      }
      
      const norma = rows[0];
      
      // Si el resumen de IA ya existe en Turso, lo devolvemos al instante
      if (norma.resumen_ia && norma.resumen_ia.trim().length > 10) {
        res.status(200).json({ resumen: norma.resumen_ia, cached: true, modelo: 'Caché Turso Cloud' });
        return;
      }
      
      // Si no existe, generarlo con IA
      const textToSummarize = norma.texto_completo || norma.resumen || norma.titulo || "Sin texto disponible.";
      const promptNorma = `Eres un analista jurídico experto en normativas municipales de Alta Gracia.
Genera un resumen ejecutivo extremadamente breve, claro y conciso (máximo de 1 a 2 párrafos cortos, un total de 100 palabras) de la siguiente norma municipal:
Norma: ${norma.tipo_nombre} N° ${norma.numero}
Título/Resumen Original: ${norma.titulo}

Texto Completo o Fragmento de la Norma:
${textToSummarize.substring(0, 15000)}

Escribe tu resumen enfocándote en el impacto práctico de la norma. No agregues introducciones formales, saludos ni firmas. Ve directo al grano en formato de resumen jurídico útil para el ciudadano.`;

      const groqKey = process.env.GROQ_API_KEY || "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";
      const deepseekKey = process.env.DEEPSEEK_API_KEY || "sk-854124346ef84affbb67479c276b2554";
      let resumenGenerado = '';
      let activeModel = '';

      try {
        // Intentar con DeepSeek
        const dsResp = await fetch("https://api.deepseek.com/chat/completions", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Authorization": `Bearer ${deepseekKey}` },
          body: JSON.stringify({
            model: "deepseek-chat",
            messages: [{ role: "user", content: promptNorma }],
            temperature: 0.2,
            max_tokens: 800
          })
        });
        if (dsResp.ok) {
          const data = await dsResp.json();
          resumenGenerado = data.choices[0].message.content;
          activeModel = 'DeepSeek (Principal)';
        } else {
          throw new Error("DeepSeek falló");
        }
      } catch (err) {
        // Fallback a Groq
        const groqResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Authorization": `Bearer ${groqKey}` },
          body: JSON.stringify({
            model: "llama3-8b-8192",
            messages: [{ role: "user", content: promptNorma }],
            temperature: 0.2,
            max_tokens: 800
          })
        });
        if (!groqResp.ok) throw new Error("Ambos motores fallaron al intentar resumir.");
        const data = await groqResp.json();
        resumenGenerado = data.choices[0].message.content;
        activeModel = 'Groq (Respaldo)';
      }

      // Guardar el resumen generado en la columna resumen_ia de Turso
      await tursoQuery(
        "UPDATE normas SET resumen_ia = ? WHERE id = ?",
        [resumenGenerado, normaId]
      );

      res.status(200).json({ resumen: resumenGenerado, cached: false, modelo: activeModel });
      return;
    }

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
