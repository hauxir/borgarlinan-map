#!/bin/sh
# One container: OTP runs internally; the Node server serves the UI and proxies
# the routing API to it. Only $PORT is exposed.
set -e
: "${PORT:=8080}"        # public port: UI + /otp proxy
: "${OTP_PORT:=8081}"    # internal OTP port (not exposed)
: "${OTP_XMX:=4g}"       # OTP heap
export PORT OTP_PORT OTP_XMX

echo "[entrypoint] starting OTP on internal :$OTP_PORT (heap $OTP_XMX)…"
java -Xmx"$OTP_XMX" -jar /app/otp.jar --load /app/graph --port "$OTP_PORT" &

echo "[entrypoint] waiting for OTP to finish loading the graph…"
node -e '
const net = require("net"), port = Number(process.env.OTP_PORT) || 8081;
(function wait(){
  const s = net.connect(port, "127.0.0.1");
  s.on("connect", () => { s.end(); process.exit(0); });
  s.on("error",  () => { s.destroy(); setTimeout(wait, 2000); });
})();'

echo "[entrypoint] OTP ready. Serving UI + API on :$PORT"
exec env PORT="$PORT" OTP_BACKEND="http://localhost:$OTP_PORT" node /app/server.js
