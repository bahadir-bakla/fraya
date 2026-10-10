import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root = path.dirname(fileURLToPath(import.meta.url));
const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.svg':'image/svg+xml'};
const server = http.createServer(async (req,res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
    if (!file.startsWith(root + path.sep) || !['.html','.js','.css','.json','.svg'].includes(path.extname(file))) {
      res.writeHead(404); res.end('Not found'); return;
    }
    const body = await readFile(file);
    res.writeHead(200,{'Content-Type':types[path.extname(file)],'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}); res.end(body);
  } catch {res.writeHead(404);res.end('Not found');}
});
server.on('error',error=>{console.error(`Yerel sunucu açılamadı: ${error.code}. Sunucu gerektirmeyen demo.html dosyasını tarayıcıda açabilirsiniz.`);process.exitCode=1;});
server.listen(Number(process.env.PORT || 4173),'127.0.0.1',()=>console.log(`Freya demo: http://127.0.0.1:${server.address().port}`));
