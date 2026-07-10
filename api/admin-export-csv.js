import { verifyAdminAuth } from './_lib/adminAuth.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }
  
  if (req.method !== 'GET') {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  if (!verifyAdminAuth(req)) {
    res.status(401).json({ error: "No autorizado. Token inválido." });
    return;
  }

  const tursoUrl = (process.env.TURSO_URL || "").replace("libsql://", "https://") + "/v2/pipeline";
  const tursoToken = process.env.TURSO_TOKEN;

  async function query(sql) {
    const response = await fetch(tursoUrl, {
      method: "POST",
      headers: { "Authorization": `Bearer ${tursoToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        requests: [
          { type: "execute", stmt: { sql } },
          { type: "close" }
        ]
      })
    });
    
    if (!response.ok) return [];
    
    const data = await response.json();
    const result = data.results[0];
    if (result.type === 'error') return [];
    
    const cols = result.response.result.cols.map(c => c.name);
    return result.response.result.rows.map(row => {
      const obj = {};
      cols.forEach((col, i) => { obj[col] = row[i] ? row[i].value : null; });
      return obj;
    });
  }

  try {
    const logs = await query("SELECT timestamp, tipo_consulta, query_text, cache_hit, duracion_ms FROM consultas_log ORDER BY timestamp DESC");
    
    // Generar CSV
    // Prependemos el BOM de UTF-8 (\uFEFF) para que Excel reconozca tildes y caracteres especiales en español
    let csvContent = "\uFEFF";
    
    // Encabezados
    csvContent += "Fecha y Hora (UTC),Tipo de Consulta,Pregunta del Usuario,Cache Hit (Ahorro),Latencia (Segundos)\n";
    
    logs.forEach(log => {
      const fecha = log.timestamp || "";
      const tipo = log.tipo_consulta === 'chat' ? 'Chatbot (Burocracio)' : 'Informe Temático';
      
      // Limpiar texto para evitar romper el formato CSV (escapar comillas dobles y remover saltos de línea)
      const pregunta = `"${(log.query_text || "").replace(/"/g, '""').replace(/\n/g, ' ')}"`;
      
      const hit = log.cache_hit === 1 ? 'Sí' : 'No';
      const latencia = log.duracion_ms ? (log.duracion_ms / 1000).toFixed(2) : "0.00";
      
      csvContent += `${fecha},${tipo},${pregunta},${hit},${latencia}\n`;
    });
    
    res.setHeader('Content-Type', 'text/csv; charset=utf-8');
    res.setHeader('Content-Disposition', 'attachment; filename=consultas_digesto.csv');
    res.status(200).send(csvContent);
    
  } catch (err) {
    console.error("Error exportando CSV:", err);
    res.status(500).json({ error: "Error interno al generar el CSV" });
  }
}
