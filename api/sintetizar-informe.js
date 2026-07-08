// Variables globales del Circuit Breaker (en memoria de Vercel)
let dsFailures = 0;
let dsTrippedUntil = 0; // Timestamp en ms

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  const deepseekKey = process.env.DEEPSEEK_API_KEY;
  const groqKey = process.env.GROQ_API_KEY;

  if ((!deepseekKey && !groqKey)) {
    res.status(500).json({ error: "Faltan variables de entorno esenciales para IA." });
    return;
  }

  let body = req.body;
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch(e) {}
  }
  const { extractos, query } = body || {};

  if (!extractos || !Array.isArray(extractos)) {
    res.status(400).json({ error: "Se requiere la lista de extractos para sintetizar." });
    return;
  }

  // Filtrar solo las normas que aplican al tema
  const normasAplicables = extractos.filter(e => e.aplica === true);

  if (normasAplicables.length === 0) {
    res.status(200).json({ 
      informe: `# Informe Temático: ${query}\n\nNo se encontraron normas vigentes o aplicables que traten específicamente sobre este tema en el Digesto.`
    });
    return;
  }

  // Formatear los extractos para el contexto del LLM
  const contextText = normasAplicables.map(n => 
    `- Norma ID: ${n.id} (Vigente: ${n.vigente ? "Sí" : "No"})
  * Aplicación/Beneficiario: ${n.beneficiario || "General"}
  * Requisitos y condiciones: ${n.condiciones || "Sin condiciones explícitas."}`
  ).join("\n");

  const promptSintesis = `Eres un consultor jurídico experto de la Municipalidad de Alta Gracia, Córdoba.
Tu tarea es redactar un INFORME TEMÁTICO EJECUTIVO en formato Markdown sobre el tema: "${query}".

Basándote únicamente en la lista de normas analizadas que se presenta a continuación, estructurá un reporte profesional para el Intendente y el Concejo Deliberante:

${contextText}

ESTRUCTURA OBLIGATORIA DEL INFORME (Usa esta jerarquía Markdown):
# Informe Temático: ${query}

## 1. Resumen Ejecutivo
(Síntesis global de los hallazgos. Máximo 150 palabras, analizando tendencias y concentración de las normas).

## 2. Detalle de Normativas Aplicables
(Enumera y clasifica las normas de forma organizada. Destaca el número de ordenanza, quiénes son los beneficiarios o a quiénes aplica, y las condiciones de acceso. Usa viñetas estructuradas y negritas).

## 3. Conclusiones y Estado de Vigencia
(Analiza el balance general de las normas, cuántas siguen vigentes y recomendaciones legales rápidas).

REGLAS DE ESTILO:
- Mantén un tono formal y técnico pero de lectura ágil.
- Destaca con negritas los números de Ordenanza (ej. **Ordenanza N° 1234**) y beneficiarios clave.
- Ve directo al grano sin introducciones del tipo "Aquí tienes tu informe...".`;


  let informeSintesis = '';
  let activeModel = 'DeepSeek (Principal)';
  const isDsTripped = Date.now() < dsTrippedUntil;

  try {
    if (isDsTripped) throw new Error();
    const dsResp = await fetch("https://api.deepseek.com/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${deepseekKey}` },
      body: JSON.stringify({
        model: "deepseek-chat",
        messages: [{ role: "user", content: promptSintesis }],
        temperature: 0.3,
        max_tokens: 3000
      })
    });
    if (dsResp.ok) {
      const data = await dsResp.json();
      informeSintesis = data.choices[0].message.content;
      dsFailures = 0;
    } else {
      throw new Error();
    }
  } catch {
    if (!isDsTripped) {
      dsFailures++;
      if (dsFailures >= 3) dsTrippedUntil = Date.now() + 5 * 60 * 1000;
    }
    activeModel = 'Groq (Respaldo)';
    const groqResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${groqKey}` },
      body: JSON.stringify({
            model: "llama-3.1-8b-instant",
            messages: [{ role: "user", content: promptSintesis }],
            temperature: 0.3,
            max_tokens: 3000
      })
    });
    if (!groqResp.ok) throw new Error("Ambas IAs fallaron al sintetizar el informe.");
    const data = await groqResp.json();
    informeSintesis = data.choices[0].message.content;
  }

  res.status(200).json({ informe: informeSintesis, modelo: activeModel });
}
