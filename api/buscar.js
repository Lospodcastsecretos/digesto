import { createClient } from '@libsql/client';

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

  // Obtener variables de entorno
  const url = process.env.TURSO_URL || "https://digesto-lospodcastsecretos.aws-us-west-2.turso.io";
  const authToken = process.env.TURSO_TOKEN || "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODMyODgxMjQsImlkIjoiMDE5ZjM0NDAtN2UwMS03OTljLWFlOTItODBiMDJmNmVhMjdlIiwia2lkIjoiZ0JFblIyNVR6dEEwaHVWWXljOS03cnRzYThUaGRnbmFEd1ZHSXJrR3FPYyIsInJpZCI6ImE1MGUwMDBmLTQ4ZTgtNDg1ZS04MmM0LTEzNGIxYTA4MmJhYSJ9.ev1b_OISV20t8e9brtO7O4oU9bGnrPYum1LTbBiVng-gaPC2YiUsHzFe-ok2aXmVePtRNYtAmKpb0ntWL6xSCA";

  // Inicializar cliente estable de Turso compatible con Vercel Serverless
  const client = createClient({
    url: url,
    authToken: authToken,
  });

  // Capturar parámetros
  const { query, tipo, categoria, anio, vigencia, page } = req.query;

  const itemsPerPage = 15;
  const currentPage = parseInt(page) || 1;
  const offset = (currentPage - 1) * itemsPerPage;

  try {
    let sql = "SELECT * FROM normas WHERE 1=1";
    const params = [];

    if (query) {
      sql += " AND (numero LIKE ? OR titulo LIKE ? OR resumen LIKE ?)";
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
