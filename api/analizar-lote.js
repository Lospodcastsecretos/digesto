import crypto from 'crypto';

// Variables globales del Circuit Breaker (en memoria de Vercel)
let dsFailures = 0;
let dsTrippedUntil = 0; // Timestamp en ms

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  const url = process.env.TURSO_URL;
  const authToken = process.env.TURSO_TOKEN;
  const deepseekKey = process.env.DEEPSEEK_API_KEY;
  const groqKey = process.env.GROQ_API_KEY;

  if (!url || !authToken || (!deepseekKey && !groqKey)) {
    res.status(500).json({ error: "Faltan variables de entorno esenciales en Vercel." });
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
      headers: { 'Authorization': `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error(`Turso Error: ${await r.text()}`);
    const data = await r.json();
    const result = data.results[0];
    if (result.type === "error") throw new Error(result.error.message);
    const resVal = result.response.result;
    const cols = resVal.cols.map(c => c.name);
    return resVal.rows.map(rVal => {
      const row = {};
      rVal.forEach((val, idx) => { row[cols[idx]] = val ? val.value : null; });
      return row;
    });
  }

  let body = req.body;
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch(e) {}
  }
  const { ids, query } = body || {};

  if (!ids || !Array.isArray(ids) || ids.length === 0) {
    res.status(400).json({ error: "Se requiere un array de IDs a analizar." });
    return;
  }

  try {
    // 1. Traer datos de las normas del lote
    const placeholders = ids.map(() => "?").join(",");
    const rows = await tursoQuery(
      `SELECT id, numero, titulo, resumen, tipo_nombre, texto_completo, resumen_ia, resumen_ia_hash, vigente FROM normas WHERE id IN (${placeholders})`,
      ids
    );

    // 2. Asegurar que todas las normas tengan un resumen_ia listo
    const normasConResumen = [];

    for (const norma of rows) {
      const textToSummarize = norma.texto_completo || norma.resumen || norma.titulo || "Sin texto.";
      const currentHash = crypto.createHash('md5').update(textToSummarize).digest('hex');

      let resumen = norma.resumen_ia;

      if (!resumen || norma.resumen_ia_hash !== currentHash || resumen.trim().length < 10) {
        // Generar resumen con fallback
        const promptNorma = `Genera un resumen ejecutivo extremadamente breve (máximo 1 párrafo de 80 palabras) de la siguiente norma municipal:
Norma: ${norma.tipo_nombre} N° ${norma.numero} - ${norma.titulo}
Texto: ${textToSummarize.substring(0, 12000)}`;

        let resumenGenerado = '';
        try {
          const dsResp = await fetch("https://api.deepseek.com/chat/completions", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": `Bearer ${deepseekKey}` },
            body: JSON.stringify({
              model: "deepseek-chat",
              messages: [{ role: "user", content: promptNorma }],
              temperature: 0.2,
              max_tokens: 500
            })
          });
          if (dsResp.ok) {
            const data = await dsResp.json();
            resumenGenerado = data.choices[0].message.content;
          } else {
            throw new Error();
          }
        } catch {
          const groqResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": `Bearer ${groqKey}` },
            body: JSON.stringify({
              model: "llama-3.1-8b-instant",
              messages: [{ role: "user", content: promptNorma }],
              temperature: 0.2,
              max_tokens: 500
            })
          });
          if (groqResp.ok) {
            const data = await groqResp.json();
            resumenGenerado = data.choices[0].message.content;
          } else {
            resumenGenerado = norma.resumen || norma.titulo || "Sin resumen disponible.";
          }
        }

        // Guardar en base de datos para no volver a generarlo
        await tursoQuery(
          "UPDATE normas SET resumen_ia = ?, resumen_ia_hash = ? WHERE id = ?",
          [resumenGenerado, currentHash, norma.id]
        );
        resumen = resumenGenerado;
      }

      normasConResumen.push({
        id: norma.id,
        numero: norma.numero,
        tipo_nombre: norma.tipo_nombre,
        titulo: norma.titulo,
        resumen_ia: resumen,
        vigente: norma.vigente === 1
      });
    }

    // 3. Procesar las 25 en un solo llamado al LLM para extraer el JSON estructurado
    const contextText = normasConResumen.map(n => 
      `ID: ${n.id} | ${n.tipo_nombre} N° ${n.numero} (Vigente: ${n.vigente ? "Sí" : "No"}) - Resumen: ${n.resumen_ia}`
    ).join("\n\n");

    const promptBatch = `Dadas las siguientes normas municipales (cada una identificada con su ID y resumen), analiza cada una en relación al tema: "${query}".
Devuelve ÚNICAMENTE un objeto JSON estructurado con la clave "resultados", que sea un array de objetos con el siguiente esquema exacto:
{
  "resultados": [
    {
      "id": 123,
      "aplica": true/false, // true si trata específicamente sobre ${query}
      "beneficiario": "quién se beneficia o a quién aplica", // máximo 15 palabras, responde null si aplica es false
      "condiciones": "requisitos y condiciones principales", // máximo 25 palabras, responde null si aplica es false
      "vigente": true/false
    }
  ]
}

No incluyas explicaciones, introducciones ni bloques de código markdown (\`\`\`json). Solo el JSON plano y limpio.

NORMAS A EVALUAR:
${contextText}`;

    let jsonStr = '';
    const isDsTripped = Date.now() < dsTrippedUntil;

    try {
      if (isDsTripped) throw new Error();
      const dsResp = await fetch("https://api.deepseek.com/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${deepseekKey}` },
        body: JSON.stringify({
          model: "deepseek-chat",
          messages: [{ role: "user", content: promptBatch }],
          temperature: 0.1,
          max_tokens: 3500
        })
      });
      if (dsResp.ok) {
        const data = await dsResp.json();
        jsonStr = data.choices[0].message.content;
        dsFailures = 0;
      } else {
        throw new Error();
      }
    } catch {
      if (!isDsTripped) {
        dsFailures++;
        if (dsFailures >= 3) dsTrippedUntil = Date.now() + 5 * 60 * 1000;
      }
      const groqResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${groqKey}` },
        body: JSON.stringify({
          model: "llama-3.1-8b-instant",
          messages: [{ role: "user", content: promptBatch }],
          temperature: 0.1,
          max_tokens: 3500
        })
      });
      if (!groqResp.ok) throw new Error("Ambas IAs fallaron en el procesamiento por lote.");
      const data = await groqResp.json();
      jsonStr = data.choices[0].message.content;
    }

    // Limpiar posibles bloques markdown del LLM
    jsonStr = jsonStr.replace(/```json/g, "").replace(/```/g, "").trim();
    const parsed = JSON.parse(jsonStr);

    res.status(200).json({ resultados: parsed.resultados || [] });
  } catch (error) {
    console.error("Error en analizar-lote:", error);
    res.status(500).json({ error: error.message });
  }
}
