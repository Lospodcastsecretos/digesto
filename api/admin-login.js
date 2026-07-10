export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }
  
  if (req.method !== 'POST') {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  const { password } = req.body || {};
  const adminPassword = process.env.ADMIN_PASSWORD;

  if (!adminPassword) {
    res.status(500).json({ error: "Panel de administración no configurado en el servidor." });
    return;
  }

  if (password === adminPassword) {
    // Retornamos el mismo password como token para usar en los próximos requests
    res.status(200).json({ success: true, token: adminPassword });
  } else {
    res.status(401).json({ success: false, error: "Contraseña incorrecta." });
  }
}
