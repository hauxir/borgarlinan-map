#!/bin/sh
# One container, two routing networks: two OTP instances run internally (the
# proposed Borgarlína graph and the current Strætó graph), and the Node server
# serves the UI and reverse-proxies to both. Only $PORT is exposed.
set -e
: "${PORT:=8080}"            # public port: UI + /otp + /otp-today proxies
: "${OTP_PORT:=8081}"        # internal OTP — proposed Borgarlína network
: "${OTP_TODAY_PORT:=8082}"  # internal OTP — current Strætó network
: "${OTP_XMX:=3g}"           # OTP heap, per instance
export PORT OTP_PORT OTP_TODAY_PORT OTP_XMX

echo "[entrypoint] starting OTP (Borgarlínan) on internal :$OTP_PORT (heap $OTP_XMX)…"
java -Xmx"$OTP_XMX" -jar /app/otp.jar --load /app/graph --port "$OTP_PORT" &

echo "[entrypoint] starting OTP (Strætó í dag) on internal :$OTP_TODAY_PORT (heap $OTP_XMX)…"
java -Xmx"$OTP_XMX" -jar /app/otp.jar --load /app/graph-today --port "$OTP_TODAY_PORT" &

# Block until a TCP port accepts a connection (OTP finished loading its graph).
wait_for() {
  echo "[entrypoint] waiting for OTP on :$1 to finish loading…"
  node -e '
  const net = require("net"), port = Number(process.argv[1]);
  (function wait(){
    const s = net.connect(port, "127.0.0.1");
    s.on("connect", () => { s.end(); process.exit(0); });
    s.on("error",  () => { s.destroy(); setTimeout(wait, 2000); });
  })();' "$1"
}
wait_for "$OTP_PORT"
wait_for "$OTP_TODAY_PORT"

echo "[entrypoint] both OTP instances ready. Serving UI + API on :$PORT"
exec env PORT="$PORT" \
  OTP_BACKEND="http://localhost:$OTP_PORT" \
  OTP_TODAY_BACKEND="http://localhost:$OTP_TODAY_PORT" \
  node /app/server.js
