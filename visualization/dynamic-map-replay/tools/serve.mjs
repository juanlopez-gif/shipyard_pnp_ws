import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";

const root = resolve(new URL("..", import.meta.url).pathname);
const port = Number(process.env.PORT || 8767);

const types = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml"
};

function fileForUrl(url) {
  const requested = normalize(decodeURIComponent(new URL(url, `http://localhost:${port}`).pathname));
  const relative = requested === "/" ? "index.html" : requested.replace(/^\/+/, "");
  const file = resolve(join(root, relative));
  return file.startsWith(root) ? file : null;
}

createServer((request, response) => {
  const file = fileForUrl(request.url || "/");
  if (!file || !existsSync(file) || !statSync(file).isFile()) {
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    response.end("Not found\n");
    return;
  }

  response.writeHead(200, { "content-type": types[extname(file)] || "application/octet-stream" });
  createReadStream(file).pipe(response);
}).listen(port, "127.0.0.1", () => {
  console.log(`Shipyard PnP Cell Flow: http://127.0.0.1:${port}/`);
});
