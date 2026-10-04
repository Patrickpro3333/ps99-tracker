#!/usr/bin/env python3
"""
PS99 Tracker history snapshot.

Reads the top 2,000 leagues and clans (40 list requests) and adds one snapshot of each
team's points and rank to the history kept in --dir (25 hours, so a 24-hour gain always has a start):

  h/league/<bucket>.json and h/clan/<bucket>.json   {"<lowercase name>": [[unixSeconds, points, rank], ...]}
  h/meta.json                                        when each kind was last saved

GitHub Actions runs this every hour (.github/workflows/history.yml, started by Netlify) and saves
the folder to the data-history branch, which index.html reads. Needs only Python 3.
"""
import argparse, json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

API = os.environ.get("PS99_API", "https://ps99.biggamesapi.io")
KEEP = 25 * 3600 + 1200  # hourly snapshots: 24 hours plus one spare (and 20 minutes for a late run)
BUCKETS = 128
PAGES = 20  # 20 pages of 100 = top 2,000
KINDS = {
    "league": ("/v1/leagues?pageSize=100&sort=Points&sortOrder=desc&page=", lambda d: (d or {}).get("leagues")),
    "clan": ("/api/clans?pageSize=100&sort=Points&sortOrder=desc&page=", lambda d: d),
}


def bucket(name):
    # FNV-1a over code points. index.html uses the same function to find a team's file.
    h = 0x811C9DC5
    for ch in name:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h % BUCKETS


def page(kind, p):
    path, rows = KINDS[kind]
    for _ in range(3):
        try:
            req = urllib.request.Request(API + path + str(p), headers={"User-Agent": "ps99-tracker-history/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                out = rows(json.load(r).get("data"))
            if isinstance(out, list):
                return out
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return None  # rate limited: skip this page rather than retry
        except Exception:
            pass
        time.sleep(1)
    return None


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))


def output(saved):
    # Tells the workflow whether there is a new snapshot to publish (only under GitHub Actions).
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"saved={'true' if saved else 'false'}\n")


ap = argparse.ArgumentParser()
ap.add_argument("--dir", default="hist")
a = ap.parse_args()

t = int(time.time())
meta_path = os.path.join(a.dir, "h", "meta.json")
meta = load(meta_path) or {}
# Netlify starts this job every hour on the hour. GitHub's own schedule (:37) is only a backup, so it
# runs only when Netlify missed an hour (no snapshot in 45 minutes, so the :37 backup can keep an hourly
# rhythm on its own); a Netlify run only skips a repeat within 10 minutes.
since = t - (meta.get("lastRun") or {}).get("t", 0)
if since < (2700 if os.environ.get("GITHUB_EVENT_NAME") == "schedule" else 600):
    print(f"The last snapshot was {since} seconds ago, so this run is skipped.")
    output(False)
    sys.exit(0)
saved = 0
for kind in KINDS:
    with ThreadPoolExecutor(4) as ex:  # 4 at a time, 20 pages per kind: far below 100 per minute
        pages = list(ex.map(lambda p: page(kind, p), range(1, PAGES + 1)))
    now, failed = {}, 0
    for pi, rows in enumerate(pages):
        if rows is None:
            failed += 1
            continue
        for i, x in enumerate(rows):
            name, pts = str(x.get("Name") or "").lower(), x.get("Points")
            # A team can show on two pages (the API caches pages at slightly different moments); keep the
            # higher place, like index.html does. The rank counts the teams kept, as index.html does, plus
            # 100 for each failed page before it, so a failed page never moves the teams after it up.
            if name and name not in now and isinstance(pts, (int, float)):
                now[name] = [t, pts, len(now) + 1 + 100 * failed]
    print(f"{kind}: {len(now)} teams, {failed} pages failed", flush=True)
    if not now:
        continue
    saved += len(now)
    by_bucket = [[] for _ in range(BUCKETS)]
    for name, entry in now.items():
        by_bucket[bucket(name)].append((name, entry))
    cut = t - KEEP
    # Snapshots saved before ranks were counted like index.html counts them (page positions) can't be compared
    # with new ones, so their rank is dropped once; the page then shows "Collecting" until a day has passed.
    compact = (meta.get(kind) or {}).get("rank") == "compact"
    # When any team's points last changed, for the page's "league war looks paused" notice. Worked out from
    # the whole kept history each time; if nothing moved in it at all, "moved" is its oldest snapshot and
    # "still" says so (paused for at least that long).
    moved, oldest = 0, t
    for b in range(BUCKETS):
        path = os.path.join(a.dir, "h", kind, f"{b}.json")
        old = load(path) or {}
        nxt = {}
        for name, h in old.items():
            h = [e if compact else e[:2] + [None] for e in h if e[0] >= cut]
            if h:
                nxt[name] = h
        for name, entry in by_bucket[b]:
            h = nxt.setdefault(name, [])
            if kind == "clan" and h and entry[1] < h[-1][1] * 0.5:
                h.clear()  # a new clan war restarted this clan's points; never mix two wars
            if h and entry[0] - h[-1][0] < 60:
                h[-1] = entry  # a re-run must not add a second point for the same moment
            else:
                h.append(entry)
        for h in nxt.values():
            oldest = min(oldest, h[0][0])
            for i in range(len(h) - 1, 0, -1):
                if h[i][1] != h[i - 1][1]:
                    moved = max(moved, h[i][0])
                    break
        save(path, nxt)
    meta[kind] = {"t": t, "n": len(now), "failedPages": failed, "rank": "compact",
                  "moved": moved or oldest, "still": not moved}

if not saved:
    sys.exit("No data from the API, so the history was left unchanged.")
meta["lastRun"] = {"t": t, "seconds": round(time.time() - t, 1)}
save(meta_path, meta)
output(True)
print("Saved snapshot", t)
