import { GoogleGenerativeAI } from '@google/generative-ai';

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

${relacionadasContext ? `NORMAS RELACIONADAS SUGERIDAS (por categoría temática similar):\n${relacionadasContext}` : ''}

${keywordsContext ? `PALABRAS CLAVE MÁS FRECUENTES EN LOS RESULTADOS: ${keywordsContext}` : ''}

Tu tarea es generar un ANÁLISIS DE CONEXIONES detallado en español (máximo 5 párrafos) que explique:

1. ¿Por qué estas normas relacionadas tienen vínculo con "${query}"? Explicá la conexión temática, jurídica o administrativa.

2. ¿Qué revelan las palabras clave? Analizá los patrones lingüísticos o temáticos.

3. ¿Qué significa la distribución temporal? Si hay concentración en ciertos años, explicá posibles razones.

4. ¿Qué relación hay entre los tipos de norma? Si predominan ordenanzas vs. decretos vs. resoluciones, explicá qué implica.

5. Conclusión integradora: Un párrafo final que conecte todos los puntos.

Escribí en prosa fluida, profesional pero accesible. Usá negritas (**texto**) para destacar conceptos clave. No menciones que sos una IA.`;

    } else {
      prompt = `Eres un analista jurídico especializado en legislación municipal argentina. Tu tarea es analizar normas del Digesto Municipal de Alta Gracia, Córdoba, Argentina.

El usuario buscó: "${query}"

${statsContext ? `ESTADÍSTICAS DE LA BÚSQUEDA:${statsContext}` : ''}

${normasContext ? `NORMAS ENCONTRADAS:\n${normasContext}` : 'No se proporcionaron normas específicas.'}

Genera un RESUMEN EJECUTIVO en español (máximo 4 párrafos cortos) que incluya:
1. Panorama general: Qué revelan estos resultados sobre el tema "${query}" en la normativa de Alta Gracia
2. Patrones detectados: Tendencias temporales, tipos de norma predominantes, o concentración en categorías
3. Aspectos relevantes: Hallazgos importantes o conexiones interesantes entre las normas
4. Contexto: Breve contexto de por qué este tema es relevante para la gestión municipal

Usa un tono profesional pero accesible. Escribe en prosa fluida. Usá negritas (**texto**) para destacar conceptos. No menciones que eres una IA.`;
    }

    // Inicializar SDK oficial de Google Generative AI
    // Al usar la última versión del SDK (^0.21.0), este objeto procesa
    // automáticamente de forma correcta las nuevas API Keys de tipo 'AQ...'
    const genAI = new GoogleGenerativeAI(geminiKey);
    const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });

    const result = await model.generateContent({
      contents: [{ role: 'user', parts: [{ text: prompt }] }],
      generationConfig: {
        temperature: 0.7,
        maxOutputTokens: modo === 'conexiones' ? 1200 : 800,
        topP: 0.9
      }
    });

    const response = await result.response;
    const resumen = response.text() || 'No se pudo generar el texto.';
    
    res.status(200).json({ resumen, modelo: 'gemini-1.5-flash (SDK)' });

  } catch (error) {
    console.error("Error en resumen IA:", error);
    res.status(500).json({ error: error.message });
  }
}
