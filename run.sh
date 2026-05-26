#!/usr/bin/env bash
# Local dev runner (no Docker): downloads inputs on first run, builds the graph,
# then serves UI + routing API on one port — the same shape as the Docker image.
#
#   PORT         public port (UI + /otp proxy)   default 8080
#   OTP_PORT     internal OTP port               default 8081
#   OTP_BACKEND  if set, skip local OTP and proxy to this URL instead
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8080}"
OTP_PORT="${OTP_PORT:-8081}"
OTP_VERSION="${OTP_VERSION:-2.6.0}"
OSM_URL="${OSM_URL:-https://download.geofabrik.de/europe/iceland-latest.osm.pbf}"

if [ -n "${OTP_BACKEND:-}" ]; then
  echo "Using external OTP: $OTP_BACKEND → serving on :$PORT"
  exec env PORT="$PORT" node server.js
fi

mkdir -p otp/graph
[ -f otp/otp-shaded.jar ] || curl -fSL -o otp/otp-shaded.jar \
  "https://repo1.maven.org/maven2/org/opentripplanner/otp/${OTP_VERSION}/otp-${OTP_VERSION}-shaded.jar"
[ -f otp/iceland-latest.osm.pbf ] || curl -fSL -o otp/iceland-latest.osm.pbf "$OSM_URL"
[ -f gtfs.zip ] || python3 build_gtfs.py

if [ ! -f otp/graph/graph.obj ]; then
  echo "Building OTP graph (first run, ~1 min)…"
  cp gtfs.zip otp/graph/gtfs.zip
  cp otp/iceland-latest.osm.pbf otp/graph/
  ( cd otp && java -Xmx6g -jar otp-shaded.jar --build --save graph/ )
fi

echo "Starting OTP on internal :$OTP_PORT …"
( cd otp && java -Xmx6g -jar otp-shaded.jar --load graph/ --port "$OTP_PORT" ) &
OTP_PID=$!
trap "kill $OTP_PID 2>/dev/null" EXIT

echo "Waiting for OTP to load…"
until curl -sf "http://localhost:$OTP_PORT/otp/routers/default" >/dev/null 2>&1; do sleep 2; done

echo "→ Open http://localhost:$PORT"
exec env PORT="$PORT" OTP_BACKEND="http://localhost:$OTP_PORT" node server.js
