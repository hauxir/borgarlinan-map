#!/usr/bin/env node
// Single server: serves the web UI (index.html) and reverse-proxies the routing
// API to OTP, so everything lives on one origin (no CORS, one thing to deploy).
//
//   PORT                port to listen on                    (default 3000)
//   OTP_BACKEND         OTP for /otp/*  — proposed Borgarlína (default hosted)
//   OTP_TODAY_BACKEND   OTP for /otp-today/*  — current Strætó (default hosted)
//
// The routing engine is OTP; this process does not run it. Point the backends at
// the hosted instances (default) or local ones (e.g. http://localhost:8081).
//
// Two committed lookup tables back the "Umferð" feature (no API key at runtime):
//   GET /traffic-factors   -> Strætó route×direction per-stop-gap congestion factors
//   GET /traffic-field     -> geographic congestion grid the car route is inflated by

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const PORT = process.env.PORT || 3000;
const INDEX = path.join(__dirname, 'index.html');
const BACKEND = new URL(process.env.OTP_BACKEND || 'https://otp.borgarlinan.kosmi.dev');
const TODAY_BACKEND = new URL(process.env.OTP_TODAY_BACKEND || 'https://otp-today.borgarlinan.kosmi.dev');
const ROUTE_FACTORS_FILE = path.join(__dirname, 'traffic_route_factors.json');
const FIELD_FILE = path.join(__dirname, 'traffic_field.json');

// Serve a committed traffic table verbatim (empty object if missing).
function serveFile(res, file) {
  fs.readFile(file, (err, data) => {
    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' });
    res.end(err ? '{}' : data);
  });
}

// Pipe an incoming request to an OTP backend at `upstreamPath` (no CORS, one origin).
function proxy(backend, upstreamPath, req, res) {
  const lib = backend.protocol === 'https:' ? https : http;
  const upstream = lib.request({
    protocol: backend.protocol,
    hostname: backend.hostname,
    port: backend.port || (backend.protocol === 'https:' ? 443 : 80),
    method: req.method,
    path: upstreamPath,
    headers: { ...req.headers, host: backend.host },
  }, up => { res.writeHead(up.statusCode, up.headers); up.pipe(res); });
  upstream.on('error', e => { res.writeHead(502); res.end('Bad gateway: ' + e.message); });
  req.pipe(upstream);
}

http.createServer((req, res) => {
  const pathname = req.url.split('?')[0];

  // --- reverse proxy ---------------------------------------------------------
  // /otp-today/* -> current Strætó OTP (rewrite the prefix back to /otp/*)
  if (pathname.startsWith('/otp-today/')) {
    proxy(TODAY_BACKEND, req.url.replace('/otp-today', '/otp'), req, res);
    return;
  }
  // /otp/* -> proposed Borgarlína OTP
  if (pathname.startsWith('/otp/')) {
    proxy(BACKEND, req.url, req, res);
    return;
  }

  // --- traffic feature: two committed tables, no runtime API key -------------
  if (pathname === '/traffic-factors') { serveFile(res, ROUTE_FACTORS_FILE); return; }  // Strætó
  if (pathname === '/traffic-field')   { serveFile(res, FIELD_FILE); return; }          // car

  if (pathname === '/favicon.ico') { res.writeHead(204); res.end(); return; }

  // --- single-page UI: every other path returns index.html ------------------
  fs.readFile(INDEX, (err, data) => {
    if (err) { res.writeHead(500); res.end('index.html missing'); return; }
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    res.end(data);
  });
}).listen(PORT, () =>
  console.log(`Borgarlínan map on http://localhost:${PORT}  →  /otp: ${BACKEND.origin}  /otp-today: ${TODAY_BACKEND.origin}`));
