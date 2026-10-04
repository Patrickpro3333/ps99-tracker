#!/usr/bin/env python3
"""
PS99 Tracker full scanner.

Scans every league and clan in the top lists and writes ranks.json.
Put ranks.json next to index.html on your site and every visitor gets exact
"Better than X%" numbers instantly, with no waiting for the in-page scan.

Usage:   python3 scan.py
Options: --leagues 2000 --clans 2000 --rate 90 --out ranks.json
Needs only Python 3 (standard library). The API allows under 100 requests per
minute per IP, so requests are spaced to 90 per minute. With --teams and --prev,
a team whose total points haven't changed since the last scan is not asked for
again (its members can't have earned anything), except every 6-12 hours to pick
up roster changes. While the league war is paused that skips all 2,000 leagues,
and a scan takes about 20 minutes instead of about 45.
"""
import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request, zlib

API = os.environ.get("PS99_API", "https://ps99.biggamesapi.io")
ap = argparse.ArgumentParser()
ap.add_argument("--leagues", type=int, default=2000)
ap.add_argument("--clans", type=int, default=2000)
ap.add_argument("--rate", type=float, default=90, help="max requests per minute (the API allows under 100)")
ap.add_argument("--out", default="ranks.json")
ap.add_argument("--players", default="", help="also write a player index (which top team each player is in) to this folder")
ap.add_argument("--prev", default="", help="folder holding the previous data-ranks branch, to carry on each player's points history")
ap.add_argument("--teams", default="", help="write each team's contributions to this folder, so the next scan can skip unchanged teams")
a = ap.parse_args()
gap = 60.0 / a.rate
REFRESH = 12 * 3600  # an unchanged team is still asked for again after 6-12 hours (spread by name), for roster changes
PLAYER_SHARDS = 256  # index.html reads players/<kind>/<user ID % 256>.json
HISTORY_KEEP = 25 * 3600 + 1200  # each player's points at every scan for 24 hours, plus one spare so a 24h gain has a start
RANK_CHUNK = 500  # players/rank/<kind>/<n>.json holds places n*500+1 .. (n+1)*500, for "players ahead and behind"
players = {"League": {}, "Clan": {}}


next_at = 0.0


def get(path):
    # Requests are spaced by when they start, so the wait overlaps the request itself: about 90 a minute,
    # where waiting after each answer gave about 60.
    global next_at
    for attempt in range(8):
        now = time.monotonic()
        if now < next_at:
            time.sleep(next_at - now)
        next_at = max(now, next_at) + gap
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "ps99-tracker-scan/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.load(r)
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


def top(path, key, n, size=100):
    # (name, [total points, members]) for the top n teams. Clans can be read 1,000 at a time; leagues 100.
    names, page = [], 1
    while len(names) < n:
        d = get(f"{path}&pageSize={size}&page={page}")
        if d is None:
            # A failed page is not the end of the list. Writing a cut-short scan would replace good data
            # and delete the history of every player it missed, so nothing is written and the last scan stays.
            sys.exit(f"Could not read page {page} of {path}, so nothing was written.")
        rows = d if isinstance(d, list) else d.get(key)
        if not rows:
            break
        names += [(x["Name"], [x.get("Points"), x.get("Members")] if x.get("Points") is not None else None) for x in rows]
        page += 1
    # The API caches each page at a slightly different moment, so a team near a page edge can show on two
    # pages. Scanning it twice would count its players twice, so only its first place is kept.
    seen = set()
    names = [x for x in names if not (x[0].lower() in seen or seen.add(x[0].lower()))]
    return names[:n]


stopped = False


def index(kind, team, rows, members):
    # Which team each player is in, for the site's player search. A current member wins over a player
    # who only has old points left in a team; otherwise the bigger contribution wins.
    idx, current, t = players[kind], {m for m in members if m}, int(time.time())
    pts = {uid: p for uid, p in rows}
    for uid in current | set(pts):
        new = [team, pts.get(uid, 0), 1 if uid in current else 0, t]
        old = idx.get(uid)
        if old is None or (new[2], new[1]) > (old[2], old[1]):
            idx[uid] = new


def scan(kind, teams, detail, pick, members, cache):
    # cache: the previous scan's {lowercase name: {name, p ([points of the rows saved, members]), ft (fetched at),
    # rows, mem}}. A team whose list total and member count match is reused, unless it was fetched 6-12 hours
    # ago. The saved total is the sum of the rows actually saved (the list and the team's own page can be a
    # minute apart), so a team whose rows don't add up to its list total is simply asked for again.
    global stopped
    pts, i, asked, now, fresh = [], 0, 0, int(time.time()), {}
    try:
        for i, (name, lp) in enumerate(teams, 1):
            key, c = name.lower(), cache.get(name.lower())
            limit = REFRESH // 2 + zlib.crc32(key.encode()) % (REFRESH // 2)
            if not (c and lp is not None and c.get("p") == lp and now - c.get("ft", 0) < limit):
                d = get(detail + urllib.parse.quote(name, safe=""))
                asked += 1
                if not d:
                    continue
                rows = [[x["UserID"], round(x.get("Points") or 0)] for x in pick(d) if x.get("UserID")]
                c = {"name": d.get("Name") or name, "p": [sum(pt for _, pt in rows), lp[1]] if lp else None, "ft": now, "rows": rows,
                     "mem": [m for m in members(d) if m]}
            fresh[key] = c
            pts += [p for _, p in c["rows"]]
            if a.players:
                index(kind, c["name"], c["rows"], c["mem"])
            if i % 100 == 0 or i == len(teams):
                print(f"{kind}: {i}/{len(teams)} done, {asked} asked for, {len(pts)} players", flush=True)
    except KeyboardInterrupt:
        print("Stopped early, saving what was scanned so far.")
        stopped, i = True, max(0, i - 1)
    pts.sort()
    return {"names": i, "points": pts, "asked": asked}, fresh


def load_teams(kind):
    # The previous scan's teams; a clan war's teams only count during that same war.
    try:
        with open(os.path.join(a.prev, "teams", kind.lower() + ".json")) as f:
            t = json.load(f)
    except (OSError, ValueError):
        return {}
    return (t.get("teams") or {}) if kind == "League" or t.get("battle") == battle else {}


def write_teams(kind, teams):
    os.makedirs(a.teams, exist_ok=True)
    with open(os.path.join(a.teams, kind.lower() + ".json"), "w") as f:
        json.dump({"battle": battle if kind == "Clan" else None, "teams": teams}, f, separators=(",", ":"))


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
                h = e[3] if len(e) > 3 and isinstance(e[3], list) else ([[then, e[1]]] if then else [])
                hist[kind][uid] = (str(e[0]).lower(), h)  # the team, so a player who moved team starts fresh
    return hist


def write_players(folder):
    old = load_history(a.prev)
    counts = {}
    for kind, idx in players.items():
        shards, ranked = [{} for _ in range(PLAYER_SHARDS)], []
        for uid, (team, pts, cur, t) in idx.items():
            prev_team, prev = old[kind].get(str(uid), ("", []))
            h = [p for p in prev if t - HISTORY_KEEP <= p[0] < t - 60] if prev_team == str(team).lower() else []
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


out, battle, teams = {"updated": 0}, None, {}
battle = (get("/api/activeClanBattle") or {}).get("configName")
if not battle:
    # Without the war's name every clan's points come back empty and every clan player's history would be
    # wiped, so nothing is written and the last good scan stays.
    sys.exit("Could not read the current clan war, so nothing was written.")
try:
    print("Reading the top leagues...", flush=True)
    out["League"], teams["League"] = scan("League", top("/v1/leagues?sort=Points&sortOrder=desc", "leagues", a.leagues),
                                          "/v1/leagues/", lambda d: d.get("PointContributions") or [], league_members,
                                          load_teams("League") if a.prev and a.teams else {})
    if not stopped:
        print("Reading the top clans for", battle, flush=True)
        out["Clan"], teams["Clan"] = scan("Clan", top("/api/clans?sort=Points&sortOrder=desc", None, a.clans, 1000),
                                          "/api/clan/", lambda d: clan_points(d, battle), clan_members,
                                          load_teams("Clan") if a.prev and a.teams else {})
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
if a.teams and not stopped:
    for k, v in teams.items():
        write_teams(k, v)
    print("Wrote the team cache to", a.teams, "-", ", ".join(f"{k}: {out[k]['asked']} of {len(v)} asked for" for k, v in teams.items()))
