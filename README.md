# Borgarlínan map

Simulate the **proposed** Reykjavík capital-region bus network (Remix project
`cd2f0f6e` — the Borgarlína trunk + feeder redesign) as if it were running
today, and see door-to-door travel time between any two points using
[OpenTripPlanner](https://www.opentripplanner.org/).

Google Maps can't route on a network that doesn't exist yet, so instead we turn
the plan into a GTFS feed and route on it ourselves (transit + walking), behind
a Google-Maps-style UI (in Icelandic) where you pick origin → destination.

## Run

### Docker (single container)

The image bundles everything — it downloads OpenTripPlanner and the Iceland OSM
extract, builds the GTFS + routing graph, and serves the UI and routing API on
one port via `server.js` (zero-dependency Node front that reverse-proxies
`/otp/*` to OTP, so there's no CORS).

```bash
docker build -t borgarlinan-map .
docker run -d --network host borgarlinan-map        # serves host :8080
# bridge networking instead: docker run -d -p 8080:8080 borgarlinan-map
```

Or pull the image built by CI:

```bash
docker run -d --network host ghcr.io/hauxir/borgarlinan-map:latest
```

Inside the container OTP runs on `OTP_PORT` (8081) and the Node front serves UI +
`/otp` on `PORT` (8080). Give the host ~4 GB RAM (`OTP_XMX`, default `4g`).

### Local (no Docker)

```bash
./run.sh        # downloads inputs + builds graph on first run, then serves :8080
# or skip the local engine and proxy to a running OTP:
OTP_BACKEND=https://otp.borgarlinan.kosmi.dev ./run.sh
```

Per-request backend override in the browser: `?otp=HOST`.

## Using the UI

- **Type an address** (e.g. *Skólavörðustígur 10*) in the From/To fields and pick
  a suggestion — geocoded via OpenStreetMap [Nominatim](https://nominatim.org/),
  biased to the capital region — or **click the map** (1st click = start, 2nd =
  destination). The swap button reverses them.
- Pick day/time; results rank by **fewest transfers within ~10 min of the
  fastest** and the selected route draws on the map (trunk lines A–G in
  Borgarlína blue). Trips are shareable — the full state lives in the URL hash.

## How it works

```
map.json            # network pulled from Remix  (GET /api/maps/7ab8d517)
   │  build_gtfs.py
   ▼
gtfs.zip            # synthesised GTFS for the 20 proposed lines (A–U)
   │  + iceland-latest.osm.pbf   (walking network, Geofabrik)
   ▼  OpenTripPlanner 2.6
graph.obj           # routable graph
   ▼  server.js  (serves index.html + proxies /otp/* to OTP)
:8080               # one origin: UI + routing API
```

Model notes: all 20 proposed lines with real stops and per-direction stop order
from the Remix `directionStops`; per-line time-of-day frequency windows
(peak/off-peak/evening, Sat, Sun) materialised into an explicit timetable; run
times from each window's modelled speed (~24–27 km/h) and cumulative stop
distances (trunk lines A–G tagged GTFS route_type 702). Walking legs use real
OSM streets. Simplifications: no road-snapped shapes (routing uses stop-to-stop
times) and uniform dwell.

## Traffic ("Umferð" toggle)

The proposed Borgarlína runs on dedicated lanes, so its times are congestion-free
by design. To compare it fairly against today's options, the **Umferð** toggle (on
by default) re-times the two modes that actually sit in traffic — the **car** and
**current Strætó** — to typical rush-hour conditions, leaving Borgarlína, bike and
walk untouched.

All traffic data is precomputed once with TomTom and committed, so **running the
container needs no API key** — the key is only used to (re)generate the tables.

```
build_traffic_factors.py   # TomTom Routing API along every capital-region Strætó
   │                       # route shape -> per-segment free-flow vs typical time
   ▼
traffic_factors.json       # shape -> bucket -> [dist0,dist1,factor]   (committed)
   ├─ build_route_factors.py ─▶ traffic_route_factors.json  # Strætó: per-stop-gap factors
   └─ build_traffic_field.py ─▶ traffic_field.json          # car: ~200 m congestion grid
        served at /traffic-factors and /traffic-field; the UI inflates legs client-side
```

**Strætó** legs: the UI matches a leg's board/alight stops to the route's stop list
and length-weights only the gaps actually ridden, so boarding mid-route is priced on
that stretch — not a whole-route average (route 1's gaps span 1.06–2.26). **Car**: OTP
routes it free-flow and the UI inflates each stretch by the congestion-grid cell it
passes through (bus corridors cover the arterials where car delay happens; off-grid
cells default to 1.0). Buckets are weekday AM-peak / midday / PM-peak / evening,
Saturday, Sunday (nights free-flow); factors are strongly directional (inbound ~1.5,
outbound ~1.15 at 8am). Regenerate only when the network changes:
`TOMTOM_API_KEY=… python3 build_traffic_factors.py && python3 build_route_factors.py && python3 build_traffic_field.py`.

## Continuous build

`.github/workflows/docker.yml` builds the image on every push and publishes
`ghcr.io/hauxir/borgarlinan-map:latest` on `master`.

`map.json` is an authenticated read from `eu.remix.com` for project `cd2f0f6e` /
map `7ab8d517`, describing a proposed network, used here only for analysis.
