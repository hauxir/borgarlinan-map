#!/usr/bin/env python3
"""
Turn the per-segment Strætó-corridor factors (traffic_factors.json) into a small
GEOGRAPHIC congestion field, so the car can be timed in traffic with no runtime
API key: the car is routed free-flow by OTP, and the UI inflates each stretch of
its route by the field cell it passes through. Reuses data we already collected —
no new TomTom calls.

The field is a coarse grid (~200 m cells). Each cell holds, per time bucket, the
length-weighted mean factor of every bus-route segment that falls in it. Bus
corridors cover the arterials where car congestion actually happens (Miklabraut,
Sæbraut, Reykjanesbraut, Kringlumýrarbraut…); cells with no data default to 1.0
(free-flow) in the UI, which is right for minor streets.

    python3 build_traffic_field.py --gtfs /tmp/straeto \
        --factors traffic_factors.json --out traffic_field.json

Output: {cell:[latCell,lonCell], buckets:[...], g:{ "iLat_iLon":[f_bucket0,...] }}
"""
import argparse, csv, json, os
from collections import defaultdict

LAT_CELL = 0.0018                      # ~200 m
LON_CELL = 0.0041                      # ~200 m at 64°N
BUCKETS = ["wk_am", "wk_mid", "wk_pm", "wk_eve", "sat", "sun"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gtfs", default="/tmp/straeto")
    ap.add_argument("--factors", default="traffic_factors.json")
    ap.add_argument("--out", default="traffic_field.json")
    args = ap.parse_args()

    with open(args.factors) as f:
        seg_factors = json.load(f)        # shape_id -> bucket -> [[d0,d1,c],...]

    # shape_id -> sorted [(dist, lat, lon)] so we can place a segment geographically
    pts = defaultdict(list)
    with open(os.path.join(args.gtfs, "shapes.txt"), newline="") as f:
        for r in csv.DictReader(f):
            if r["shape_id"] in seg_factors:
                pts[r["shape_id"]].append((float(r["shape_dist_traveled"]),
                                           float(r["shape_pt_lat"]), float(r["shape_pt_lon"])))
    for sid in pts:
        pts[sid].sort()

    def loc_at(shape_pts, dist):
        """lat,lon at a distance along the shape (nearest point — cells are coarse)."""
        lo, hi = 0, len(shape_pts) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if shape_pts[mid][0] < dist:
                lo = mid + 1
            else:
                hi = mid
        return shape_pts[lo][1], shape_pts[lo][2]

    # cell -> bucket -> [weighted factor sum, weight]
    cells = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for sid, buckets in seg_factors.items():
        sp = pts.get(sid)
        if not sp:
            continue
        for bucket, segs in buckets.items():
            for d0, d1, c in segs:
                w = d1 - d0
                if w <= 0:
                    continue
                lat, lon = loc_at(sp, (d0 + d1) / 2)
                key = f"{round(lat / LAT_CELL)}_{round(lon / LON_CELL)}"
                acc = cells[key][bucket]
                acc[0] += w * c
                acc[1] += w

    g = {}
    for key, buckets in cells.items():
        row = []
        for b in BUCKETS:
            acc = buckets.get(b)
            row.append(round(acc[0] / acc[1], 2) if acc and acc[1] > 0 else 1.0)
        g[key] = row

    out = {"cell": [LAT_CELL, LON_CELL], "buckets": BUCKETS, "g": g}
    with open(args.out, "w") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=True)
    print(f"{len(g)} cells -> {args.out} ({os.path.getsize(args.out)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
