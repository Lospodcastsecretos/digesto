const token = 'eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODMyODgxMjQsImlkIjoiMDE5ZjM0NDAtN2UwMS03OTljLWFlOTItODBiMDJmNmVhMjdlIiwia2lkIjoiZ0JFblIyNVR6dEEwaHVWWXljOS03cnRzYThUaGRnbmFEd1ZHSXJrR3FPYyIsInJpZCI6ImE1MGUwMDBmLTQ4ZTgtNDg1ZS04MmM0LTEzNGIxYTA4MmJhYSJ9.ev1b_OISV20t8e9brtO7O4oU9bGnrPYum1LTbBiVng-gaPC2YiUsHzFe-ok2aXmVePtRNYtAmKpb0ntWL6xSCA';
const url = 'https://digesto-lospodcastsecretos.aws-us-west-2.turso.io/v2/pipeline';

const queries = [
  '"taxi"*',
  'taxi*',
  'taxi',
  '"becerra"*',
  'becerra'
];

async function run() {
  for (let q of queries) {
    const searchSql = 'SELECT id, numero, titulo FROM normas WHERE id IN (SELECT id FROM normas_fts WHERE normas_fts MATCH ?) LIMIT 4';
    
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        requests: [
          { type: 'execute', stmt: { sql: searchSql, args: [{ type: 'text', value: q }] } },
          { type: 'close' }
        ]
      })
    });
    const d = await resp.json();
    console.log("QUERY:", q);
    if(d.results[0].type === 'error') {
       console.log("ERROR:", d.results[0].error.message);
    } else {
       console.log("ROWS:", d.results[0].response.result.rows);
    }
  }
}
run();
