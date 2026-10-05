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
up roster changes. While the league war is paused that skips all 2,000 leagues.

The work can be split across machines (BIG Games agreed to this for PS99 Tracker):
  python3 scan.py plan  --prev prev --plan plan.json                 (one machine)
  python3 scan.py fetch --plan plan.json --shard 0 --of 17 --total-rate 1530 --part p0.json   (machines 0..16, 90/min each)
  python3 scan.py merge --plan plan.json --parts parts --of 17 --prev prev --out ranks.json --players players --teams teams
With no step named, one machine does all three.
"""
import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request, zlib

API = os.environ.get("PS99_API", "https://ps99.biggamesapi.io")
ap = argparse.ArgumentParser()
ap.add_argument("step", nargs="?", default="all", choices=["all", "plan", "fetch", "merge"])
ap.add_argument("--plan", default="plan.json", help="plan file written by the plan step, read by fetch and merge")
ap.add_argument("--shard", type=int, default=0, help="fetch: which machine this is, from 0")
ap.add_argument("--of", type=int, default=1, help="fetch and merge: how many machines share the fetch step")
ap.add_argument("--part", default="part.json", help="fetch: where this machine writes the teams it read")
ap.add_argument("--parts", default="parts", help="merge: folder holding every machine's part file")
ap.add_argument("--leagues", type=int, default=2000)
ap.add_argument("--clans", type=int, default=2000)
ap.add_argument("--rate", type=float, default=90, help="max requests per minute for this machine (the API allows under 100)")
ap.add_argument("--total-rate", type=float, default=0, help="fetch: requests per minute for all machines together; each gets an equal share")
ap.add_argument("--out", default="ranks.json")
ap.add_argument("--players", default="", help="also write a player index (which top team each player is in) to this folder")
ap.add_argument("--prev", default="", help="folder holding the previous data-ranks branch, to carry on each player's points history")
ap.add_argument("--teams", default="", help="write each team's contributions to this folder, so the next scan can skip unchanged teams")
a = ap.parse_args()
rate = min(a.rate, a.total_rate / a.of) if a.step == "fetch" and a.total_rate else a.rate
gap = 60.0 / rate
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


KINDS = {  # list path, list key, list page size, team page
    "League": ("/v1/leagues?sort=Points&sortOrder=desc", "leagues", 100, "/v1/leagues/"),
    "Clan": ("/api/clans?sort=Points&sortOrder=desc", None, 1000, "/api/clan/"),
}


def due(c, lp, key, now):
    # A team is read again unless it was saved before with the same list total and member count, under 6-12
    # hours ago (spread by name). The saved total is the sum of the rows actually saved (the list and the
    # team's own page can be a minute apart), so a team whose rows don't add up to its list total is read again.
    limit = REFRESH // 2 + zlib.crc32(key.encode()) % (REFRESH // 2)
    return not (c and lp is not None and c.get("p") == lp and now - c.get("ft", 0) < limit)


def make_plan():
    # Step 1 (one machine): the clan war, both top lists, and which teams changed since the last scan.
    global battle
    battle = (get("/api/activeClanBattle") or {}).get("configName")
    if not battle:
        # Without the war's name every clan's points come back empty and every clan player's history would be
        # wiped, so nothing is written and the last good scan stays.
        sys.exit("Could not read the current clan war, so nothing was written.")
    now = int(time.time())
    plan = {"battle": battle, "t": now, "fetch": []}
    for kind, (path, key, size, _) in KINDS.items():
        teams = top(path, key, a.leagues if kind == "League" else a.clans, size)
        cache = load_teams(kind) if a.prev else {}
        todo = [[kind, n, lp] for n, lp in teams if due(cache.get(n.lower()), lp, n.lower(), now)]
        plan[kind], plan["fetch"] = teams, plan["fetch"] + todo
        print(f"{kind}: {len(teams)} teams, {len(todo)} changed or due to be read again", flush=True)
    return plan


def fetch(items, label=""):
    # Step 2 (one or more machines): the changed teams' own pages. Returns {kind: {lowercase name: team}}.
    got = {"League": {}, "Clan": {}}
    try:
        for i, (kind, name, lp) in enumerate(items, 1):
            d = get(KINDS[kind][3] + urllib.parse.quote(name, safe=""))
            if d:
                found = (d.get("PointContributions") or []) if kind == "League" else clan_points(d, battle)
                rows = [[x["UserID"], round(x.get("Points") or 0)] for x in found if x.get("UserID")]
                got[kind][name.lower()] = {"name": d.get("Name") or name, "ft": int(time.time()), "rows": rows,
                                           "p": [sum(pt for _, pt in rows), lp[1]] if lp else None,
                                           "mem": [m for m in (league_members(d) if kind == "League" else clan_members(d)) if m]}
            if i % 100 == 0 or i == len(items):
                print(f"{label}{i}/{len(items)} teams read", flush=True)
    except KeyboardInterrupt:
        print("Stopped early; the teams not read keep their last saved data.")
    return got


def merge(plan, got):
    # Step 3 (one machine): every team, read now or reused, into ranks.json, the player index and the team cache.
    for kind in KINDS:
        cache = load_teams(kind) if a.prev else {}
        pts, keep = [], {}
        for name, lp in plan[kind]:
            key = name.lower()
            c = got[kind].get(key) or cache.get(key)  # a team whose page could not be read keeps its last saved data
            if not c:
                continue
            keep[key] = c
            pts += [p for _, p in c["rows"]]
            if a.players:
                index(kind, c["name"], c["rows"], c["mem"])
        pts.sort()
        out[kind] = {"names": len(keep), "points": pts, "read": len(got[kind])}
        teams[kind] = keep
    out["Clan"]["battle"] = battle  # the page ignores a clan scan from an earlier war
    if not any(len(out[k]["points"]) > 50 for k in KINDS):
        sys.exit("Scan found almost no players, so " + a.out + " was not written. The API may be down.")
    out["updated"] = int(time.time())
    with open(a.out, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print("Wrote", a.out)
    if a.players:
        write_players(a.players)
        print(f"Wrote the player index to {a.players}: {len(players['League'])} league players, {len(players['Clan'])} clan players")
    if a.teams:
        for k, v in teams.items():
            write_teams(k, v)
        print("Wrote the team cache to", a.teams, "-", ", ".join(f"{k}: {out[k]['read']} read, {len(v) - out[k]['read']} reused" for k, v in teams.items()))


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
if a.step == "plan":
    plan = make_plan()
    with open(a.plan, "w") as f:
        json.dump(plan, f, separators=(",", ":"))
    print(f"Wrote {a.plan}: {len(plan['fetch'])} teams to read")
elif a.step == "fetch":
    with open(a.plan) as f:
        plan = json.load(f)
    battle, items = plan["battle"], plan["fetch"][a.shard::a.of]
    print(f"Machine {a.shard + 1} of {a.of}: {len(items)} teams to read at {rate:g} a minute", flush=True)
    got = fetch(items)
    with open(a.part, "w") as f:
        json.dump(got, f, separators=(",", ":"))
    print("Wrote", a.part)
elif a.step == "merge":
    with open(a.plan) as f:
        plan = json.load(f)
    battle, got = plan["battle"], {"League": {}, "Clan": {}}
    files = sorted(fn for fn in os.listdir(a.parts) if fn.endswith(".json"))
    if len(files) != a.of:
        # A machine's part is missing: those teams would quietly fall back to old data, so nothing is written.
        sys.exit(f"Expected {a.of} part files in {a.parts}, found {len(files)}, so nothing was written.")
    for fn in files:
        with open(os.path.join(a.parts, fn)) as f:
            part = json.load(f)
        for k in got:
            got[k].update(part.get(k) or {})
    merge(plan, got)
else:
    plan = make_plan()
    merge(plan, fetch(plan["fetch"]))
