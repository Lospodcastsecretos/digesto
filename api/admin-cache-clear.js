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

  const tursoUrl = (process.env.TURSO_CACHE_URL || process.env.TURSO_URL || "").replace("libsql://", "https://") + "/v2/pipeline";
  const tursoToken = process.env.TURSO_CACHE_TOKEN || process.env.TURSO_TOKEN;

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
    
    if (!response.ok) return null;
    
    const data = await response.json();
    const result = data.results[0];
    if (result.type === 'error') throw new Error(result.error.message);
    
    return result;
  }

  try {
    await query("DELETE FROM semantic_cache");
    res.status(200).json({ success: true, message: "Caché limpiado exitosamente." });
  } catch (err) {
    console.error("Error limpiando cache:", err);
    res.status(500).json({ error: "Error limpiando caché en la base de datos." });
  }
}
