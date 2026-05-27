#!/usr/bin/env python3
"""
Precompute per-segment, time-of-day traffic factors for the *current* Strætó
network, so the comparison stops giving the car and today's buses a free pass at
rush hour. (Borgarlína is on dedicated lanes -> unaffected, by design.)

For each capital-region route shape we ask the TomTom Routing API to drive along
the shape (the shape points become waypoints) for a handful of representative
departure times, with `computeTravelTimeFor=all`. TomTom returns, per leg, both
the free-flow time (`noTrafficTravelTimeInSeconds`) and the typical/historic
time for that time-of-day (`historicTrafficTravelTimeInSeconds`). The ratio is a
congestion factor c >= 1 attached to that stretch of road, in that direction, at
that time of day. The same traffic hits a car and a bus on the same street, so
these factors later drive *both* the car estimate and the Strætó GTFS running
times (see apply_traffic.py).

Output: traffic_factors.json
  { shape_id: { bucket: [[dist_from_m, dist_to_m, factor], ...] } }
Distances are GTFS shape_dist_traveled, so apply_traffic.py can map each
stop-to-stop segment (which carries shape_dist_traveled) onto these factors.

The result is committed so the Docker build is reproducible and needs no API key.
Re-run only when the network or our bucketing changes:
    TOMTOM_API_KEY=... python3 build_traffic_factors.py
"""
import argparse, csv, json, os, sys, time, urllib.request, urllib.error
from collections import defaultdict

GTFS_URL = "https://opendata.straeto.is/data/gtfs/gtfs.zip"
# Capital-region bounding box (Hafnarfjörður/Vellir up to Mosfellsbær).
LAT0, LAT1, LON0, LON1 = 63.95, 64.25, -22.10, -21.55
MAX_WAYPOINTS = 80          # TomTom hard limit is 150; keep URL length sane.

# Representative departure instants. Iceland is UTC year-round and has no DST,
# so wall-clock == UTC. 2026-06-02 = Tue, 06 = Sat, 07 = Sun.
BUCKETS = {
    "wk_am":  "2026-06-02T08:00:00Z",   # weekday morning peak (inbound heavy)
    "wk_mid": "2026-06-02T13:00:00Z",   # weekday midday
    "wk_pm":  "2026-06-02T17:00:00Z",   # weekday afternoon peak (outbound heavy)
    "wk_eve": "2026-06-02T21:00:00Z",   # weekday evening
    "sat":    "2026-06-06T13:00:00Z",   # Saturday daytime
    "sun":    "2026-06-07T13:00:00Z",   # Sunday daytime
}
# Night (~22:00-06:00) is free-flow -> factor 1.0, no call needed; the rewriter
# maps those hours to a synthetic "night" bucket handled as c=1.


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_capital_shapes(gtfs_dir):
    """Distinct shape_ids whose trips begin inside the capital bbox, with their
    ordered (lat, lon, dist) points."""
    stops = {}
    for r in read_csv(os.path.join(gtfs_dir, "stops.txt")):
        try:
            stops[r["stop_id"]] = (float(r["stop_lat"]), float(r["stop_lon"]))
        except ValueError:
            pass

    def in_capital(stop_id):
        p = stops.get(stop_id)
        return p and LAT0 <= p[0] <= LAT1 and LON0 <= p[1] <= LON1

    trip_shape = {}
    for r in read_csv(os.path.join(gtfs_dir, "trips.txt")):
        trip_shape[r["trip_id"]] = r["shape_id"]

    # A trip is "capital" only if BOTH its terminals sit in the bbox; that drops
    # intercity routes (50 to Borgarnes, the P-routes) whose first stop happens
    # to be in town but which then run out onto rural highway.
    ends = {}   # trip_id -> {min_seq: stop_id, max_seq: stop_id}
    for r in read_csv(os.path.join(gtfs_dir, "stop_times.txt")):
        t = r["trip_id"]
        seq = int(r["stop_sequence"])
        e = ends.setdefault(t, [seq, r["stop_id"], seq, r["stop_id"]])  # [lo,loId,hi,hiId]
        if seq < e[0]:
            e[0], e[1] = seq, r["stop_id"]
        if seq > e[2]:
            e[2], e[3] = seq, r["stop_id"]

    cap_shapes = set()
    for t, sid in trip_shape.items():
        e = ends.get(t)
        if e and in_capital(e[1]) and in_capital(e[3]):
            cap_shapes.add(sid)

    pts = defaultdict(list)
    for r in read_csv(os.path.join(gtfs_dir, "shapes.txt")):
        sid = r["shape_id"]
        if sid in cap_shapes:
            pts[sid].append((int(r["shape_pt_sequence"]),
                             float(r["shape_pt_lat"]),
                             float(r["shape_pt_lon"]),
                             float(r["shape_dist_traveled"])))
    for sid in pts:
        pts[sid].sort()
    return {sid: [(la, lo, d) for _, la, lo, d in p] for sid, p in pts.items() if len(p) >= 2}


def downsample(points, max_wp):
    """Evenly-spaced-by-distance subset, always keeping first and last point."""
    if len(points) <= max_wp:
        return points
    total = points[-1][2] - points[0][2]
    if total <= 0:
        return [points[0], points[-1]]
    step = total / (max_wp - 1)
    out = [points[0]]
    next_d = points[0][2] + step
    for p in points[1:-1]:
        if p[2] >= next_d:
            out.append(p)
            next_d = p[2] + step
    out.append(points[-1])
    return out


def tomtom(locations, depart_at, key, tries=4):
    locs = ":".join(f"{la:.6f},{lo:.6f}" for la, lo, _ in locations)
    url = (f"https://api.tomtom.com/routing/1/calculateRoute/{locs}/json"
           f"?key={key}&traffic=true&computeTravelTimeFor=all"
           f"&departAt={depart_at}&travelMode=car&routeType=fastest")
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:    # rate limited -> back off
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def factors_for_shape(points, depart_at, key):
    """List of [dist_from, dist_to, factor] over the shape for one departure."""
    wps = downsample(points, MAX_WAYPOINTS)
    data = tomtom(wps, depart_at, key)
    legs = data["routes"][0]["legs"]
    out = []
    for i, leg in enumerate(legs):
        s = leg["summary"]
        nf = s.get("noTrafficTravelTimeInSeconds")
        hist = s.get("historicTrafficTravelTimeInSeconds")
        d0, d1 = wps[i][2], wps[i + 1][2]
        c = (hist / nf) if (nf and hist) else 1.0
        out.append([round(d0, 1), round(d1, 1), round(max(c, 1.0), 3)])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gtfs", default=os.environ.get("STRAETO_GTFS_DIR", "/tmp/straeto"),
                    help="dir with unzipped current Strætó GTFS (stops/trips/shapes/stop_times)")
    ap.add_argument("--out", default="traffic_factors.json")
    ap.add_argument("--key", default=os.environ.get("TOMTOM_API_KEY"))
    ap.add_argument("--limit", type=int, default=0, help="only N shapes (testing)")
    ap.add_argument("--sleep", type=float, default=0.15, help="pause between calls")
    args = ap.parse_args()
    if not args.key:
        sys.exit("Set TOMTOM_API_KEY (or pass --key).")

    shapes = load_capital_shapes(args.gtfs)
    ids = sorted(shapes)
    if args.limit:
        ids = ids[:args.limit]
    total = len(ids) * len(BUCKETS)
    print(f"{len(ids)} shapes × {len(BUCKETS)} buckets = {total} TomTom calls", flush=True)

    # Resume across runs: keep whatever is already in --out.
    result = {}
    if os.path.exists(args.out):
        with open(args.out) as f:
            result = json.load(f)

    done = 0
    for sid in ids:
        result.setdefault(sid, {})
        for bucket, when in BUCKETS.items():
            done += 1
            if bucket in result[sid]:
                continue
            try:
                result[sid][bucket] = factors_for_shape(shapes[sid], when, args.key)
            except Exception as e:
                print(f"  [{done}/{total}] shape {sid} {bucket}: FAILED {e}", flush=True)
                continue
            if done % 25 == 0 or done == total:
                with open(args.out, "w") as f:        # checkpoint
                    json.dump(result, f)
                print(f"  [{done}/{total}] …", flush=True)
            time.sleep(args.sleep)

    with open(args.out, "w") as f:
        json.dump(result, f)

    # Summary: peak factor distribution.
    peaks = []
    for sid in ids:
        segs = result.get(sid, {}).get("wk_am", [])
        if segs:
            tot = sum(d1 - d0 for d0, d1, _ in segs)
            if tot:
                peaks.append(sum((d1 - d0) * c for d0, d1, c in segs) / tot)
    if peaks:
        peaks.sort()
        print(f"\nweekday-AM mean factor per shape: min {peaks[0]:.2f} / "
              f"median {peaks[len(peaks)//2]:.2f} / max {peaks[-1]:.2f}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
