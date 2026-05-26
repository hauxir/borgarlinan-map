# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Stage 1 — fetch inputs, build the GTFS feed and the OTP routing graph
# ---------------------------------------------------------------------------
FROM eclipse-temurin:21-jdk AS builder
RUN apt-get update && apt-get install -y --no-install-recommends python3 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build

ARG OTP_VERSION=2.6.0
ARG OSM_URL=https://download.geofabrik.de/europe/iceland-latest.osm.pbf
ARG STRAETO_GTFS_URL=https://opendata.straeto.is/data/gtfs/gtfs.zip

# Big, rarely-changing downloads first so they stay cached across builds.
RUN curl -fsSL -o otp.jar \
      "https://repo1.maven.org/maven2/org/opentripplanner/otp/${OTP_VERSION}/otp-${OTP_VERSION}-shaded.jar"
RUN mkdir -p graph && curl -fsSL -o graph/iceland-latest.osm.pbf "${OSM_URL}"

# Current Strætó network (real published GTFS) -> its own routing graph. Independent
# of the proposed-network inputs below, so keep it here to stay build-cached when
# only map.json / build_gtfs.py / the UI change.
RUN mkdir -p graph-today \
 && curl -fsSL -o graph-today/gtfs.zip "${STRAETO_GTFS_URL}" \
 && cp graph/iceland-latest.osm.pbf graph-today/iceland-latest.osm.pbf \
 && java -Xmx4g -jar otp.jar --build --save graph-today/

# Remix network export -> GTFS -> routing graph
COPY map.json map.json
COPY build_gtfs.py build_gtfs.py
RUN python3 build_gtfs.py && cp gtfs.zip graph/gtfs.zip
RUN java -Xmx4g -jar otp.jar --build --save graph/

# ---------------------------------------------------------------------------
# Stage 2 — lean runtime: Java (OTP) + Node (UI/proxy), one exposed port
# ---------------------------------------------------------------------------
FROM eclipse-temurin:21-jre
RUN apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY --from=builder /build/otp.jar               /app/otp.jar
COPY --from=builder /build/graph/graph.obj       /app/graph/graph.obj
COPY --from=builder /build/graph-today/graph.obj /app/graph-today/graph.obj
COPY index.html                             /app/index.html
COPY server.js                              /app/server.js
COPY entrypoint.sh                          /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PORT=8080 OTP_PORT=8081 OTP_TODAY_PORT=8082 OTP_XMX=3g
EXPOSE 8080
CMD ["/app/entrypoint.sh"]
