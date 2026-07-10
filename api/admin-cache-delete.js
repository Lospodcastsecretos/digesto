import { verifyAdminAuth } from './_lib/adminAuth.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }
  
  if (req.method !== 'POST') {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  if (!verifyAdminAuth(req)) {
    res.status(401).json({ error: "No autorizado. Token inválido." });
    return;
  }

  let body = req.body;
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch(e) {}
  }

  const { rowid } = body || {};
  if (!rowid) {
    res.status(400).json({ error: "Falta el parámetro rowid." });
    return;
  }

  const tursoUrl = (process.env.TURSO_CACHE_URL || process.env.TURSO_URL || "").replace("libsql://", "https://") + "/v2/pipeline";
  const tursoToken = process.env.TURSO_CACHE_TOKEN || process.env.TURSO_TOKEN;

  async function query(sql, args) {
    const formattedArgs = args.map(arg => {
      if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
      return { type: 'text', value: arg.toString() };
    });

    const response = await fetch(tursoUrl, {
      method: "POST",
      headers: { "Authorization": `Bearer ${tursoToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        requests: [
          { type: "execute", stmt: { sql, args: formattedArgs } },
          { type: "close" }
        ]
      })
    });
    
    if (!response.ok) return null;
    
    const data = await response.json();
    const result = data.results[0];
    if (result.type === 'error') throw new Error(result.error.message);
    
    return result;
  }

  try {
    await query("DELETE FROM semantic_cache WHERE rowid = ?", [rowid]);
    res.status(200).json({ success: true, message: "Registro eliminado exitosamente." });
  } catch (err) {
    console.error("Error eliminando registro del cache:", err);
    res.status(500).json({ error: "Error eliminando el registro de la base de datos." });
  }
}
