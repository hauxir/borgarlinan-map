#!/usr/bin/env node
// Single server: serves the web UI (index.html) and reverse-proxies the routing
// API to OTP, so everything lives on one origin (no CORS, one thing to deploy).
//
//   PORT          port to listen on              (default 3000)
//   OTP_BACKEND   OTP instance to proxy /otp/*   (default the hosted one)
//
// The routing engine is OTP; this process does not run it. Point OTP_BACKEND at
// the hosted instance (default) or a local one (http://localhost:8080).

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const PORT = process.env.PORT || 3000;
const INDEX = path.join(__dirname, 'index.html');
const BACKEND = new URL(process.env.OTP_BACKEND || 'https://otp.borgarlinan.kosmi.dev');

http.createServer((req, res) => {
  const pathname = req.url.split('?')[0];

  // --- reverse proxy: anything under /otp/ goes to the OTP backend -----------
  if (pathname.startsWith('/otp/')) {
    const lib = BACKEND.protocol === 'https:' ? https : http;
    const upstream = lib.request({
      protocol: BACKEND.protocol,
      hostname: BACKEND.hostname,
      port: BACKEND.port || (BACKEND.protocol === 'https:' ? 443 : 80),
      method: req.method,
      path: req.url,
      headers: { ...req.headers, host: BACKEND.host },
    }, up => { res.writeHead(up.statusCode, up.headers); up.pipe(res); });
    upstream.on('error', e => { res.writeHead(502); res.end('Bad gateway: ' + e.message); });
    req.pipe(upstream);
    return;
  }

  if (pathname === '/favicon.ico') { res.writeHead(204); res.end(); return; }

  // --- single-page UI: every other path returns index.html ------------------
  fs.readFile(INDEX, (err, data) => {
    if (err) { res.writeHead(500); res.end('index.html missing'); return; }
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    res.end(data);
  });
}).listen(PORT, () =>
  console.log(`Borgarlínan map on http://localhost:${PORT}  →  OTP backend: ${BACKEND.origin}`));
