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
ap.add_argument("--players", default="", help="also write a player index (which top team each player is in) to this folder")
ap.add_argument("--prev", default="", help="folder holding the previous data-ranks branch, to carry on each player's points history")
a = ap.parse_args()
gap = 60.0 / a.rate
PLAYER_SHARDS = 256  # index.html reads players/<kind>/<user ID % 256>.json
HISTORY_KEEP = 25 * 3600 + 1200  # each player's points at every scan for 24 hours, plus one spare so a 24h gain has a start
RANK_CHUNK = 500  # players/rank/<kind>/<n>.json holds places n*500+1 .. (n+1)*500, for "players ahead and behind"
players = {"League": {}, "Clan": {}}


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
    # The API caches each page at a slightly different moment, so a team near a page edge can show on two
    # pages. Scanning it twice would count its players twice, so only its first place is kept.
    seen = set()
    names = [x for x in names if not (x.lower() in seen or seen.add(x.lower()))]
    return names[:n]


stopped = False


def index(kind, team, contributions, members):
    # Which team each player is in, for the site's player search. A current member wins over a player
    # who only has old points left in a team; otherwise the bigger contribution wins.
    idx, current, t = players[kind], {m for m in members if m}, int(time.time())
    pts = {x["UserID"]: round(x.get("Points") or 0) for x in contributions if x.get("UserID")}
    for uid in current | set(pts):
        new = [team, pts.get(uid, 0), 1 if uid in current else 0, t]
        old = idx.get(uid)
        if old is None or (new[2], new[1]) > (old[2], old[1]):
            idx[uid] = new


def scan(kind, names, detail, pick, members):
    global stopped
    pts, i = [], 0
    try:
        for i, name in enumerate(names, 1):
            d = get(detail + urllib.parse.quote(name, safe=""))
            if d:
                rows = pick(d)
                pts += [round(x["Points"]) for x in rows]
                if a.players:
                    index(kind, d.get("Name") or name, rows, members(d))
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


def league_members(d):
    owner = d.get("Owner")
    return [m.get("UserID") for m in d.get("Members") or []] + [owner.get("UserID") if isinstance(owner, dict) else owner]


def clan_members(d):
    return [m.get("UserID") for m in d.get("Members") or []] + [d.get("Owner")]


def load_history(folder):
    # Each player's points at earlier scans, from the previous data-ranks branch. Entries written before
    # the history existed ([team, points, member]) count as one point at that scan's time.
    hist = {"League": {}, "Clan": {}}
    if not folder:
        return hist
    try:
        with open(os.path.join(folder, "players", "meta.json")) as f:
            meta = json.load(f)
    except (OSError, ValueError):
        meta = {}
    then = meta.get("updated", 0)
    for kind in hist:
        if kind == "Clan" and battle and meta.get("battle") != battle:
            continue  # the previous scan was taken in another clan war; never mix two wars
        for i in range(PLAYER_SHARDS):
            try:
                with open(os.path.join(folder, "players", kind.lower(), f"{i}.json")) as f:
                    shard = json.load(f)
            except (OSError, ValueError):
                continue
            for uid, e in shard.items():
                hist[kind][uid] = e[3] if len(e) > 3 and isinstance(e[3], list) else ([[then, e[1]]] if then else [])
    return hist


def write_players(folder):
    old = load_history(a.prev)
    counts = {}
    for kind, idx in players.items():
        shards, ranked = [{} for _ in range(PLAYER_SHARDS)], []
        for uid, (team, pts, cur, t) in idx.items():
            h = [p for p in old[kind].get(str(uid), []) if t - HISTORY_KEEP <= p[0] < t - 60]
            if kind == "Clan" and h and pts < h[-1][1] * 0.5:
                h = []  # a new clan war restarted this player's points; never mix two wars
            h.append([t, pts])
            shards[int(uid) % PLAYER_SHARDS][str(uid)] = [team, pts, cur, h]  # [team, points, member 1/0, [[time, points], ...]]
            if pts > 0:
                ranked.append((pts, uid))
        os.makedirs(os.path.join(folder, kind.lower()), exist_ok=True)
        for i, shard in enumerate(shards):
            with open(os.path.join(folder, kind.lower(), f"{i}.json"), "w") as f:
                json.dump(shard, f, separators=(",", ":"))
        ranked.sort(reverse=True)
        rdir = os.path.join(folder, "rank", kind.lower())
        os.makedirs(rdir, exist_ok=True)
        for c in range(0, len(ranked), RANK_CHUNK):
            with open(os.path.join(rdir, f"{c // RANK_CHUNK}.json"), "w") as f:
                json.dump([[uid, pts] for pts, uid in ranked[c:c + RANK_CHUNK]], f, separators=(",", ":"))
        counts[kind] = len(ranked)
    with open(os.path.join(folder, "meta.json"), "w") as f:
        json.dump({"updated": out["updated"], "battle": battle, "League": len(players["League"]),
                   "Clan": len(players["Clan"]), "ranked": counts, "rankChunk": RANK_CHUNK}, f, separators=(",", ":"))


out, battle = {"updated": 0}, None
try:
    print("Reading the top leagues...", flush=True)
    out["League"] = scan("League", top("/v1/leagues?sort=Points&sortOrder=desc", "leagues", a.leagues),
                         "/v1/leagues/", lambda d: d.get("PointContributions") or [], league_members)
    if not stopped:
        battle = (get("/api/activeClanBattle") or {}).get("configName")
        print("Reading the top clans for", battle or "the current clan battle", flush=True)
        out["Clan"] = scan("Clan", top("/api/clans?sort=Points&sortOrder=desc", None, a.clans),
                           "/api/clan/", lambda d: clan_points(d, battle), clan_members)
        out["Clan"]["battle"] = battle  # the page ignores a clan scan from an earlier war
except KeyboardInterrupt:
    print("Stopped early, saving what was scanned so far.")
if not any(len((out.get(k) or {}).get("points") or []) > 50 for k in ("League", "Clan")):
    sys.exit("Scan found almost no players, so " + a.out + " was not written. The API may be down.")
out["updated"] = int(time.time())
with open(a.out, "w") as f:
    json.dump(out, f, separators=(",", ":"))
print("Wrote", a.out, "- upload it next to index.html")
if a.players:
    write_players(a.players)
    print(f"Wrote the player index to {a.players}: {len(players['League'])} league players, {len(players['Clan'])} clan players")
