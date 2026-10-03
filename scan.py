#!/usr/bin/env python3
"""
PS99 Tracker full scanner.

Scans every league and clan in the top lists once and writes ranks.json.
Put ranks.json next to index.html on your site and every visitor gets exact
"Better than X%" numbers instantly, with no waiting for the in-page scan.

Usage:   python3 scan.py
Options: --leagues 2000 --clans 2000 --rate 60 --out ranks.json
Needs only Python 3 (standard library). The API allows 100 requests per minute
per IP, so the default is 60 per minute: about 35 minutes for 2,000 leagues and
2,000 clans. Run it again whenever you want fresh numbers.
"""
import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request

API = os.environ.get("PS99_API", "https://ps99.biggamesapi.io")
ap = argparse.ArgumentParser()
ap.add_argument("--leagues", type=int, default=2000)
ap.add_argument("--clans", type=int, default=2000)
ap.add_argument("--rate", type=float, default=60, help="max requests per minute")
ap.add_argument("--out", default="ranks.json")
a = ap.parse_args()
gap = 60.0 / a.rate


def get(path):
    for attempt in range(8):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "ps99-tracker-scan/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.load(r)
            time.sleep(gap)
            return j.get("data") if j.get("status") == "ok" else None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After") or 30)
                print("  rate limited, waiting", wait, "seconds", flush=True)
                time.sleep(wait + 1)
                continue
            if e.code == 404:
                return None
            time.sleep(5 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    return None


def top(path, key, n):
    names, page = [], 1
    while len(names) < n:
        d = get(f"{path}&pageSize=100&page={page}")
        rows = d if isinstance(d, list) else (d or {}).get(key)
        if not rows:
            break
        names += [x["Name"] for x in rows]
        page += 1
    return names[:n]


def scan(kind, names, detail, pick):
    pts = []
    for i, name in enumerate(names, 1):
        d = get(detail + urllib.parse.quote(name, safe=""))
        if d:
            pts += [round(x["Points"]) for x in pick(d)]
        if i % 25 == 0 or i == len(names):
            print(f"{kind}: {i}/{len(names)} scanned, {len(pts)} players", flush=True)
    pts.sort()
    return {"names": len(names), "points": pts}


out = {"updated": 0}
try:
    print("Reading the top leagues...", flush=True)
    out["League"] = scan("League", top("/v1/leagues?sort=Points&sortOrder=desc", "leagues", a.leagues),
                         "/v1/leagues/", lambda d: d.get("PointContributions") or [])
    print("Reading the top clans...", flush=True)
    out["Clan"] = scan("Clan", top("/api/clans?sort=Points&sortOrder=desc", None, a.clans),
                       "/api/clan/", lambda d: (d.get("Contribution") or {}).get("Battle") or [])
except KeyboardInterrupt:
    print("Stopped early, saving what was scanned so far.")
out["updated"] = int(time.time())
with open(a.out, "w") as f:
    json.dump(out, f, separators=(",", ":"))
print("Wrote", a.out, "- upload it next to index.html")
