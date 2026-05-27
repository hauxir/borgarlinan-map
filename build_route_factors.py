#!/usr/bin/env python3
"""
Turn the per-segment TomTom factors (traffic_factors.json, keyed by shape) into a
table the browser can apply at *stop-to-stop* resolution, so a passenger boarding
mid-route is timed on the stretch they actually ride — not a whole-route average
(route 1's segments span 1.0–3.3, so the average badly misprices a partial trip).

For each route short-name + direction we pick the most-detailed shape, list its
stops with their distance along the shape, and integrate the fine segment factors
over each consecutive stop gap, per time bucket:

    { shortName: { directionId: {
        s: [[lat, lon, dist_km], ...],        # stops in order
        f: { bucket: [gapFactor_0, gapFactor_1, ...] }   # one per gap (len = #stops-1)
    } } }

The UI matches a leg's from/to to the nearest stops and length-weights the gap
factors between them. Direction is kept (peaks are directional). Served at
/traffic-factors.

    python3 build_route_factors.py --gtfs /tmp/straeto \
        --factors traffic_factors.json --out traffic_route_factors.json
"""
import argparse, csv, json, os
from collections import defaultdict


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def seg_mean(segs, d0, d1):
    """Length-weighted mean factor of the fine segments over [d0, d1]."""
    if d1 <= d0:
        return 1.0
    acc = tot = 0.0
    for a0, a1, c in segs:
        lo, hi = max(d0, a0), min(d1, a1)
        if hi > lo:
            acc += (hi - lo) * c
            tot += (hi - lo)
    return acc / tot if tot > 0 else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gtfs", default="/tmp/straeto")
    ap.add_argument("--factors", default="traffic_factors.json")
    ap.add_argument("--out", default="traffic_route_factors.json")
    args = ap.parse_args()

    with open(args.factors) as f:
        seg_factors = json.load(f)            # shape_id -> bucket -> [[d0,d1,c],...]

    route_name = {r["route_id"]: r["route_short_name"]
                  for r in read_csv(os.path.join(args.gtfs, "routes.txt"))}
    stop_ll = {}
    for r in read_csv(os.path.join(args.gtfs, "stops.txt")):
        try:
            stop_ll[r["stop_id"]] = (float(r["stop_lat"]), float(r["stop_lon"]))
        except ValueError:
            pass

    # (short_name, direction) -> set of shape_ids; and shape_id -> one representative trip
    rd_shapes = defaultdict(set)
    shape_trip = {}
    for r in read_csv(os.path.join(args.gtfs, "trips.txt")):
        sid = r.get("shape_id", "")
        if not sid or sid not in seg_factors:
            continue
        rd_shapes[(route_name.get(r["route_id"], r["route_id"]), r.get("direction_id", "0"))].add(sid)
        shape_trip.setdefault(sid, r["trip_id"])

    # stop list (id + shape_dist) per representative trip
    trip_stops = defaultdict(list)
    wanted = set(shape_trip.values())
    for r in read_csv(os.path.join(args.gtfs, "stop_times.txt")):
        if r["trip_id"] in wanted:
            sd = r.get("shape_dist_traveled", "")
            trip_stops[r["trip_id"]].append(
                (int(r["stop_sequence"]), r["stop_id"], float(sd) if sd not in ("", None) else None))

    out = {}
    for (name, direction), shapes in rd_shapes.items():
        # most-detailed shape for this route+direction = most stops on its rep trip
        best = max(shapes, key=lambda s: len(trip_stops.get(shape_trip[s], [])))
        stops = sorted(trip_stops.get(shape_trip[best], []))
        stops = [(sid, d) for _, sid, d in stops if d is not None and sid in stop_ll]
        if len(stops) < 2:
            continue
        segs_by_bucket = seg_factors[best]

        s_list = [[round(stop_ll[sid][0], 5), round(stop_ll[sid][1], 5), round(d, 3)]
                  for sid, d in stops]
        f_by_bucket = {}
        for bucket, segs in segs_by_bucket.items():
            gaps = [round(seg_mean(segs, stops[i][1], stops[i + 1][1]), 3)
                    for i in range(len(stops) - 1)]
            f_by_bucket[bucket] = gaps
        out.setdefault(name, {})[direction] = {"s": s_list, "f": f_by_bucket}

    with open(args.out, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    size = os.path.getsize(args.out)
    n_rd = sum(len(d) for d in out.values())
    print(f"{len(out)} routes / {n_rd} route-directions -> {args.out} ({size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
