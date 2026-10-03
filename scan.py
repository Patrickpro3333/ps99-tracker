#!/usr/bin/env python3
"""
PS99 Tracker full scanner.

Scans every league and clan in the top lists once and writes ranks.json.
Put ranks.json next to index.html on your site and every visitor gets exact
"Better than X%" numbers instantly, with no waiting for the in-page scan.

Usage:   python3 scan.py
Options: --leagues 2000 --clans 2000 --rate 90 --out ranks.json
Needs only Python 3 (standard library). The API allows under 100 requests per
minute per IP, so the default is 90 per minute: about 45 minutes for 2,000 leagues
and 2,000 clans (one request per team plus the list pages). Run it again whenever
you want fresh numbers.
"""
import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request

API = os.environ.get("PS99_API", "https://ps99.biggamesapi.io")
ap = argparse.ArgumentParser()
ap.add_argument("--leagues", type=int, default=2000)
ap.add_argument("--clans", type=int, default=2000)
ap.add_argument("--rate", type=float, default=90, help="max requests per minute (the API allows under 100)")
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


stopped = False


def scan(kind, names, detail, pick):
    global stopped
    pts, i = [], 0
    try:
        for i, name in enumerate(names, 1):
            d = get(detail + urllib.parse.quote(name, safe=""))
            if d:
                pts += [round(x["Points"]) for x in pick(d)]
            if i % 25 == 0 or i == len(names):
                print(f"{kind}: {i}/{len(names)} scanned, {len(pts)} players", flush=True)
    except KeyboardInterrupt:
        print("Stopped early, saving what was scanned so far.")
        stopped, i = True, max(0, i - 1)
    pts.sort()
    return {"names": i, "points": pts}


def clan_points(d, battle):
    # Clan battle points live under Battles[<active battle>]; older API versions used Contribution.Battle.
    b = (d.get("Battles") or {}).get(battle) or {}
    return b.get("PointContributions") or (d.get("Contribution") or {}).get("Battle") or []


out = {"updated": 0}
try:
    print("Reading the top leagues...", flush=True)
    out["League"] = scan("League", top("/v1/leagues?sort=Points&sortOrder=desc", "leagues", a.leagues),
                         "/v1/leagues/", lambda d: d.get("PointContributions") or [])
    if not stopped:
        battle = (get("/api/activeClanBattle") or {}).get("configName")
        print("Reading the top clans for", battle or "the current clan battle", flush=True)
        out["Clan"] = scan("Clan", top("/api/clans?sort=Points&sortOrder=desc", None, a.clans),
                           "/api/clan/", lambda d: clan_points(d, battle))
        out["Clan"]["battle"] = battle  # the page ignores a clan scan from an earlier war
except KeyboardInterrupt:
    print("Stopped early, saving what was scanned so far.")
if not any(len((out.get(k) or {}).get("points") or []) > 50 for k in ("League", "Clan")):
    sys.exit("Scan found almost no players, so " + a.out + " was not written. The API may be down.")
out["updated"] = int(time.time())
with open(a.out, "w") as f:
    json.dump(out, f, separators=(",", ":"))
print("Wrote", a.out, "- upload it next to index.html")
