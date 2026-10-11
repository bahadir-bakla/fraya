// Example Cloudflare Worker: a standalone mock service with a single endpoint.
// POST /ping  body: { "kod": "A1" }  ->  returns a record from the table in this file.
// This file only shows the pattern; you will write the statement-debt services yourself.

const RECORDS = {
  A1: { kod: "A1", ad: "Örnek kayıt", tutar: 1250.5, tarih: "15.11.2026" },
  B2: { kod: "B2", ad: "İkinci kayıt", tutar: 0, tarih: "01.12.2026" },
};

const CORS = { "Access-Control-Allow-Origin": "*" };

function json(body, status = 200) {
  return Response.json(body, { status: status, headers: CORS });
}

async function readBody(request) {
  try { return await request.json(); } catch { return null; }
}

// The panel's "Test API Request" button sends variables without filling them in, e.g. "{{kod}}".
function isTemplateVariable(value) {
  return typeof value === "string" && (value.startsWith("{{") || value.startsWith("%7B%7B"));
}

async function ping(request) {
  const body = (await readBody(request)) || {};
  if (isTemplateVariable(body.kod)) return json(RECORDS.A1);
  const record = RECORDS[String(body.kod || "").trim()];
  if (!record) return json({ hata: "kayıt bulunamadı" }, 404);
  return json(record);
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: {
        ...CORS,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
      } });
    }
    if (request.method === "GET" && url.pathname === "/health") return json({ durum: "ok" });
    if (request.method === "POST" && url.pathname === "/ping") return ping(request);
    return json({ hata: "bulunamadı", yollar: ["GET /health", "POST /ping"] }, 404);
  },
};
