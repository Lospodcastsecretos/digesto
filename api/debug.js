export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  const results = {
    turso: { status: 'pending', details: '' },
    deepseek: { status: 'pending', details: '' },
    groq: { status: 'pending', details: '' },
    env: {
      TURSO_URL_present: !!process.env.TURSO_URL,
      TURSO_TOKEN_present: !!process.env.TURSO_TOKEN,
      DEEPSEEK_API_KEY_present: !!process.env.DEEPSEEK_API_KEY,
      GROQ_API_KEY_present: !!process.env.GROQ_API_KEY,
    }
  };

  // 1. Diagnóstico de Turso
  if (!process.env.TURSO_URL || !process.env.TURSO_TOKEN) {
    results.turso.status = 'error';
    results.turso.details = 'Faltan variables de entorno de Turso.';
  } else {
    try {
      const cleanUrl = process.env.TURSO_URL.replace("libsql://", "https://").replace("http://", "https://");
      const pipelineUrl = `${cleanUrl}/v2/pipeline`;
      
      const payload = {
        requests: [
          { type: "execute", stmt: { sql: "SELECT 1 as val", args: [] } },
          { type: "close" }
        ]
      };
      
      const start = Date.now();
      const r = await fetch(pipelineUrl, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${process.env.TURSO_TOKEN}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload),
        timeout: 5000
      });
      
      if (!r.ok) {
        results.turso.status = 'error';
        results.turso.details = `HTTP ${r.status_code}: ${await r.text()}`;
      } else {
        const data = await r.json();
        if (data.results[0].type === 'error') {
          results.turso.status = 'error';
          results.turso.details = data.results[0].error.message;
        } else {
          results.turso.status = 'ok';
          results.turso.details = `Conectado con éxito en ${Date.now() - start}ms`;
        }
      }
    } catch (e) {
      results.turso.status = 'error';
      results.turso.details = e.message;
    }
  }

  // 2. Diagnóstico de DeepSeek
  if (!process.env.DEEPSEEK_API_KEY) {
    results.deepseek.status = 'error';
    results.deepseek.details = 'Falta DEEPSEEK_API_KEY.';
  } else {
    try {
      const start = Date.now();
      const r = await fetch("https://api.deepseek.com/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${process.env.DEEPSEEK_API_KEY}`
        },
        body: JSON.stringify({
          model: "deepseek-chat",
          messages: [{ role: "user", content: "Hi" }],
          max_tokens: 5
        })
      });
      if (r.ok) {
        results.deepseek.status = 'ok';
        results.deepseek.details = `Respondió en ${Date.now() - start}ms`;
      } else {
        results.deepseek.status = 'error';
        results.deepseek.details = `HTTP ${r.status}: ${await r.text()}`;
      }
    } catch (e) {
      results.deepseek.status = 'error';
      results.deepseek.details = e.message;
    }
  }

  // 3. Diagnóstico de Groq
  if (!process.env.GROQ_API_KEY) {
    results.groq.status = 'error';
    results.groq.details = 'Falta GROQ_API_KEY.';
  } else {
    try {
      const start = Date.now();
      const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${process.env.GROQ_API_KEY}`
        },
        body: JSON.stringify({
          model: "llama-3.1-8b-instant",
          messages: [{ role: "user", content: "Hi" }],
          max_tokens: 5
        })
      });
      if (r.ok) {
        results.groq.status = 'ok';
        results.groq.details = `Respondió en ${Date.now() - start}ms`;
      } else {
        results.groq.status = 'error';
        results.groq.details = `HTTP ${r.status}: ${await r.text()}`;
      }
    } catch (e) {
      results.groq.status = 'error';
      results.groq.details = e.message;
    }
  }

  res.status(200).json(results);
}
