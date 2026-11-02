import http from 'node:http';
import {readFile, stat} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.PORT || 8000);
const mime = {
  '.html': 'text/html; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
};

http.createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const requested = path.resolve(root, `.${pathname}`);
    if (requested !== root && !requested.startsWith(root + path.sep)) {
      response.writeHead(403).end('Forbidden');
      return;
    }

    let target = requested;
    if ((await stat(target)).isDirectory()) target = path.join(target, 'index.html');
    const body = await readFile(target);
    response.writeHead(200, {
      'Content-Type': mime[path.extname(target).toLowerCase()] || 'application/octet-stream',
      'Cache-Control': 'no-store',
    });
    response.end(body);
  } catch {
    response.writeHead(404, {'Content-Type': 'text/plain; charset=utf-8'});
    response.end('Not found');
  }
}).listen(port, '127.0.0.1', () => {
  console.log(`복지틈새찾기: http://127.0.0.1:${port}/`);
});
