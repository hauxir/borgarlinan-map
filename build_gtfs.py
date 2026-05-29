#!/usr/bin/env python3
"""
Convert a Remix published-map JSON (the proposed Borgarlína network for the
Reykjavík capital region) into a GTFS feed that OpenTripPlanner can route on.

Input : map.json   (response of GET /api/maps/7ab8d517)
Output: gtfs/*.txt  +  gtfs.zip

The Remix model stores, per line:
  - patterns -> directions -> directionStops (placeId + distanceFromStart in metres)
  - windows  : time-of-day bands with {start,end (min from midnight),
               headwaySeconds, speed (km/h), type (weekday/saturday/sunday)}
We synthesise an explicit timetable: for every window we emit one trip per
headway between start and end, with stop times derived from cumulative distance
and that window's speed. No GTFS frequencies.txt -> the schedule is fully
materialised, which OTP prefers for accurate transfers.
"""
import csv, json, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAP = ROOT / "map.json"
OUT = ROOT / "gtfs"
OUT.mkdir(exist_ok=True)

# A representative service window. weekday=Mon-Fri, saturday=Sat, sunday=Sun.
FEED_START = "20260601"
FEED_END   = "20261231"
AGENCY_ID  = "straeto"
TZ         = "Atlantic/Reykjavik"

data = json.loads(MAP.read_text())
stops_by_id = {s["id"]: s for s in data["stops"]}

# ---- corrections for known bad source data --------------------------------
# The Remix snapshot carries corrupt distanceFromStart values that misorder
# stops along a corridor. A full audit of every line/direction (relocation
# cost + cross-direction consistency + stalled-distance checks) found four,
# each confirmed by the opposite direction ordering the same physical corridor
# correctly. Reseat each to its true position. Keyed by placeId; each placeId
# is referenced exactly once across the whole feed.
#
# Two are "inserted" far past their true slot, causing a long there-and-back:
#   - D outbound: Norðurbær recorded 14772.7 (past Hraunbrún + Hellisgerði);
#     belongs between Ásar and Hraunbrún -> …Ásar, Norðurbær, Hraunbrún….
#   - D inbound: Hraunvallaskóli recorded 1585.6 (past Daggarvellir);
#     belongs between Hvannavellir and Daggarvellir.
# Two are adjacent pairs whose distances are nearly equal (gap ~12 m) though
# the stops are ~190 m apart, so they sort in the wrong order — a small wiggle.
# The fix swaps the pair's two values:
#   - D outbound: Haukáhús comes before Ásvallalaug heading west (was reversed).
#   - M inbound:  Borgaskóli comes before Vættaborgir heading east (was reversed).
DISTANCE_OVERRIDES = {
    "2495e8bc-5294-4dfd-9aa2-99349ac34906": 13586.1,  # D outbound · Norðurbær
    "16ad9bd5-d282-4790-982f-daa109e79106": 1346.6,   # D inbound  · Hraunvallaskóli
    "d05f1a90-6268-4dbc-b527-f8fed18e9c6f": 18112.7,  # D outbound · Haukahús    (was 18126.6)
    "23a6f682-1863-4e3c-b69a-113b95d255ad": 18126.6,  # D outbound · Ásvallalaug (was 18112.7)
    "559f6a40-215f-4509-beda-53bc7fc1925e": 7064.7,   # M inbound  · Borgaskóli  (was 7076.4)
    "e46ef899-4fc2-4cce-8ab7-1db051afca4c": 7076.4,   # M inbound  · Vættaborgir (was 7064.7)
}

# ---- collect the places actually used by some direction -------------------
used_place_ids = set()
for line in data["lines"]:
    for pat in line["patterns"]:
        for d in pat["directions"]:
            for ds in d["directionStops"]:
                used_place_ids.add(ds["placeId"])

# ---------------------------------------------------------------- writers --
def write(name, header, rows):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)

# agency.txt
write("agency.txt",
      ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"],
      [[AGENCY_ID, data.get("agencyName") or "Straeto",
        "https://straeto.is", TZ, "is"]])

# stops.txt
stop_rows = []
for pid in sorted(used_place_ids):
    s = stops_by_id[pid]
    lng, lat = s["geometry"]["coordinates"]
    stop_rows.append([pid, s.get("name") or pid, f"{lat:.6f}", f"{lng:.6f}"])
write("stops.txt", ["stop_id", "stop_name", "stop_lat", "stop_lon"], stop_rows)

# calendar.txt  (3 service ids matching window.type)
write("calendar.txt",
      ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday",
       "saturday", "sunday", "start_date", "end_date"],
      [["weekday", 1, 1, 1, 1, 1, 0, 0, FEED_START, FEED_END],
       ["saturday", 0, 0, 0, 0, 0, 1, 0, FEED_START, FEED_END],
       ["sunday",   0, 0, 0, 0, 0, 0, 1, FEED_START, FEED_END]])

# routes.txt  — trunk letters A-G are the Borgarlína high-frequency spine.
TRUNK = set("ABCDEFG")

def hex6(c):
    """Normalise '#rgb'/'#rrggbb' to GTFS route_color form 'RRGGBB', else ''."""
    c = (c or "").lstrip("#").strip()
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    ok = len(c) == 6 and all(d in "0123456789abcdefABCDEF" for d in c)
    return c.upper() if ok else ""

def text_for(bg):
    """Black or white label colour for a background hex, by perceived luminance."""
    if not bg:
        return ""
    r, g, b = (int(bg[i:i + 2], 16) for i in (0, 2, 4))
    return "000000" if (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 else "FFFFFF"

route_rows = []
for line in data["lines"]:
    short = line["gtfsShortName"] or ""
    # 700 = Bus Service; 702 = Express (use for trunk to distinguish)
    rtype = 702 if short in TRUNK else 3
    color = hex6((line.get("lineDisplay") or {}).get("color"))  # official plan colour
    route_rows.append([line["id"], AGENCY_ID, short,
                       line["gtfsLongName"] or line["name"], rtype,
                       color, text_for(color)])
write("routes.txt",
      ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type",
       "route_color", "route_text_color"],
      route_rows)

# trips.txt + stop_times.txt
def hhmmss(sec):
    h, r = divmod(int(round(sec)), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

trip_rows, st_rows = [], []
n_trips = 0
for line in data["lines"]:
    for pat in line["patterns"]:
        for d in pat["directions"]:
            dir_id = 0 if (d.get("name") == "inbound") else 1
            def dist(ds):  # corrected cumulative distance (see DISTANCE_OVERRIDES)
                return DISTANCE_OVERRIDES.get(ds["placeId"]) or ds["distanceFromStart"]
            seq = sorted(d["directionStops"], key=dist)
            if len(seq) < 2:
                continue
            base = dist(seq[0])
            offsets = [(ds["placeId"], dist(ds) - base) for ds in seq]
            for w in line["windows"]:
                svc = w["type"]
                speed_mps = (w["speed"] * 1000.0) / 3600.0
                if speed_mps <= 0:
                    continue
                headway = w["headwaySeconds"]
                start_s, end_s = w["start"] * 60, w["end"] * 60
                t = start_s
                while t < end_s:
                    n_trips += 1
                    tid = f"{line['id']}_{d['id']}_{svc}_{t}"
                    trip_rows.append([line["id"], svc, tid, d.get("headsign") or "",
                                      dir_id])
                    for i, (pid, off) in enumerate(offsets):
                        clock = hhmmss(t + off / speed_mps)
                        st_rows.append([tid, clock, clock, pid, i])
                    t += headway

write("trips.txt",
      ["route_id", "service_id", "trip_id", "trip_headsign", "direction_id"],
      trip_rows)
write("stop_times.txt",
      ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
      st_rows)

# feed_info.txt
write("feed_info.txt",
      ["feed_publisher_name", "feed_publisher_url", "feed_lang",
       "feed_start_date", "feed_end_date"],
      [["Borgarlína what-if (Remix project cd2f0f6e)", "https://straeto.is",
        "is", FEED_START, FEED_END]])

# zip it
zip_path = ROOT / "gtfs.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for p in OUT.glob("*.txt"):
        z.write(p, p.name)

print(f"routes      : {len(route_rows)}")
print(f"stops       : {len(stop_rows)}")
print(f"trips       : {n_trips:,}")
print(f"stop_times  : {len(st_rows):,}")
print(f"wrote       : {zip_path} ({zip_path.stat().st_size/1e6:.1f} MB)")
