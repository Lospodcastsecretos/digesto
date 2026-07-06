import { createClient } from '@libsql/client/web';

export default async function handler(req, res) {
  // Habilitar CORS
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS,PATCH,DELETE,POST,PUT');
  res.setHeader(
    'Access-Control-Allow-Headers',
    'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version'
  );

  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  // Leer tokens desde las variables de entorno de Vercel
  const url = process.env.TURSO_URL;
  const authToken = process.env.TURSO_TOKEN;

  if (!url || !authToken) {
    res.status(500).json({ error: "Faltan las variables de entorno de conexión a Turso (TURSO_URL o TURSO_TOKEN)." });
    return;
  }

  // Inicializar cliente optimizado para Vercel Edge Serverless
  const client = createClient({
    url: url,
    authToken: authToken,
  });

  const { query, tipo, categoria, anio, vigencia, page } = req.query;

  const itemsPerPage = 15;
  const currentPage = parseInt(page) || 1;
  const offset = (currentPage - 1) * itemsPerPage;

  try {
    let sql = "SELECT * FROM normas WHERE 1=1";
    const params = [];

    if (query) {
      sql += " AND (lower(numero) LIKE ? OR lower(titulo) LIKE ? OR lower(resumen) LIKE ?)";
      const likeQuery = `%${query.toLowerCase()}%`;
      params.push(likeQuery, likeQuery, likeQuery);
    }

    if (tipo && tipo !== 'todos') {
      sql += " AND tipo_nombre = ?";
      params.push(tipo);
    }

    if (categoria && categoria !== 'todas') {
      sql += " AND categoria_nombre = ?";
      params.push(categoria);
    }

    if (anio && anio !== 'todos') {
      sql += " AND fecha = ?";
      params.push(`Año ${anio}`);
    }

    if (vigencia && vigencia !== 'todos') {
      const isVigente = vigencia === 'si' ? 1 : 0;
      sql += " AND vigente = ?";
      params.push(isVigente);
    }

    // Obtener total
    let countSql = sql.replace("SELECT *", "SELECT COUNT(*) as total");
    const countResult = await client.execute({ sql: countSql, args: params });
    const totalItems = countResult.rows[0].total;

    // Ejecutar paginacion
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?";
    params.push(itemsPerPage, offset);

    const result = await client.execute({ sql: sql, args: params });
    
    const normas = result.rows.map(row => ({
      id: row.id,
      numero: row.numero,
      titulo: row.titulo,
      resumen: row.resumen,
      tipo_nombre: row.tipo_nombre,
      categoria_nombre: row.categoria_nombre,
      vigente: row.vigente === 1,
      fecha: row.fecha,
      archivo_pdf: row.archivo_pdf,
      url_detalle: row.url_detalle
    }));

    res.status(200).json({
      normas: normas,
      total: totalItems,
      page: currentPage,
      totalPages: Math.ceil(totalItems / itemsPerPage)
    });

  } catch (error) {
    console.error("Error en la consulta de Turso:", error);
    res.status(500).json({ error: error.message });
  }
}
