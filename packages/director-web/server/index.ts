// Express (BFF reżysera): serwuje zbudowany frontend i proxuje /api oraz /ws do debate-api.
// Node 26 uruchamia ten plik bezpośrednio (type stripping), bez osobnego kroku budowania.
import path from "node:path";
import { fileURLToPath } from "node:url";

import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";

const API_URL = process.env.DEBATE_API_URL ?? "http://127.0.0.1:8001";
const PORT = Number(process.env.PORT ?? 3000);
const HOST = process.env.HOST ?? "127.0.0.1";
const CLIENT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../dist/client");

const apiProxy = createProxyMiddleware({
  target: API_URL,
  changeOrigin: true,
  ws: true,
  pathFilter: ["/api", "/ws"],
});

const app = express();
app.use(apiProxy);
app.use(express.static(CLIENT_DIR));
// SPA: każda inna ścieżka dostaje index.html
app.get("/{*splat}", (_req, res) => {
  res.sendFile(path.join(CLIENT_DIR, "index.html"));
});

const server = app.listen(PORT, HOST, () => {
  console.log(`director-web: http://${HOST}:${PORT} (API: ${API_URL})`);
});
server.on("upgrade", apiProxy.upgrade);
