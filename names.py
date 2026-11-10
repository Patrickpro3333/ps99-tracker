#!/usr/bin/env python3
"""
Saves the Roblox name and profile picture of every player in the top teams, so the page can show them without
asking Roblox. Roblox refuses the site's own proxy (Cloudflare's addresses are shared with many other sites and
stay over Roblox's limit) and doesn't let a browser ask it directly. It does answer GitHub's machines.

Usage:  python3 names.py --prev prev --out names
--prev is the last data-ranks branch: its teams/ lists every team's players, its names/ is what was saved before.
Each run asks Roblox about the players it has no answer for yet, then about the ones checked longest ago: 700 names
(everyone's name is checked again about once a day) and 6,000 pictures (every 3 hours or so). Measured from a
GitHub machine, Roblox takes about 1,000 names and 10,000 pictures a minute, so a normal run needs about a minute
and the first fill of 60,000 players about 2 hours of runs, each stopping after 8 minutes. When Roblox stops
answering, what was saved before is kept. The scan's merge step saves --out next to ranks.json:
  id/<user ID % 1024>.json           {user ID: [username, display name, picture, name checked, picture checked]}
  team/<league|clan>/<0-511>.json    {team name in lowercase: {user ID: [username, display name, picture]}}
  by/<0-255>.json                    {username in lowercase: user ID}, for the player search
The team and username files are picked by shard() of the name; index.html has the same sum (nmh). A picture is the
32 characters that differ between Roblox's picture addresses; pic() in index.html puts the address back together.
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--prev", default="prev", help="folder holding the previous data-ranks branch")
ap.add_argument("--out", default="names", help="folder to write the names to")
a = ap.parse_args()
PIC = re.compile(r"https://tr\.rbxcdn\.com/30DAY-AvatarHeadshot-([0-9A-F]{32})-Png/150/150/AvatarHeadshot/Png/noFilter")
next_at, stopped = {}, set()


def ask(host, path, per_minute, body=None):
    # None when Roblox keeps refusing or can't be reached. That host is then left alone for the rest of the run.
    if host in stopped:
        return None
    for attempt in range(4):
        wait = next_at.get(host, 0) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        next_at[host] = time.monotonic() + 60 / per_minute
        try:
            req = urllib.request.Request(f"https://{host}.roblox.com{path}", data=json.dumps(body).encode() if body else None,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            why = e
            if e.code != 429:
                break
            # Roblox says "too many requests" now and then even under its stated limit, so wait and ask again.
            next_at[host] = time.monotonic() + 10 * (attempt + 1)
        except Exception as e:
            why = e
    print(f"{host}.roblox.com stopped answering ({why}). The players left wait for the next run.", flush=True)
    stopped.add(host)
    return None


def shard(s, n):
    x = 0
    for b in s.encode():
        x = (x * 31 + b) % n
    return x


def short(url):
    # Only Roblox's own picture servers are saved, since the page shows whatever address is in the file.
    m = PIC.fullmatch(url or "")
    return m[1] if m else url if re.fullmatch(r"https://[a-z0-9]+\.rbxcdn\.com/[\w./-]+", url or "") else ""


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write(folder, shards):
    os.makedirs(folder, exist_ok=True)
    for i, s in enumerate(shards):
        with open(os.path.join(folder, f"{i}.json"), "w") as f:
            json.dump(s, f, separators=(",", ":"))


assert shard("un0", 512) == 183 and shard("", 512) == 0
assert short("https://tr.rbxcdn.com/30DAY-AvatarHeadshot-33EBC42BC550FCB5158C6AF17BE3E4C8-Png/150/150/AvatarHeadshot/Png/noFilter") == "33EBC42BC550FCB5158C6AF17BE3E4C8"
assert short("https://t1.rbxcdn.com/abc/150/150") == "https://t1.rbxcdn.com/abc/150/150" and short("https://evil.example/x.png") == "" and short(None) == ""

if __name__ == "__main__":
    teams, ids = {}, {}
    for kind in ("league", "clan"):  # in the scan's order, so the top teams' players are asked about first
        saved = (load(os.path.join(a.prev, "teams", kind + ".json")) or {}).get("teams") or {}
        teams[kind] = {key: list(dict.fromkeys(int(u) for u in (c.get("mem") or []) + [r[0] for r in c.get("rows") or []] if u))
                       for key, c in saved.items()}
        for members in teams[kind].values():
            ids.update(dict.fromkeys(members))
    if not ids:
        sys.exit("The last scan has no teams, so no names were written.")
    old = {}
    for i in range(1024):
        for u, e in (load(os.path.join(a.prev, "names", "id", f"{i}.json")) or {}).items():
            if isinstance(e, list) and len(e) == 5:
                old[int(u)] = e
    store = {u: old.get(u) or ["", "", "", 0, 0] for u in ids}  # a player who left every top team is dropped

    def queue(stamp, again):
        # Players with no answer yet, in the scan's order, then the ones checked longest ago.
        return [u for u in ids if not store[u][stamp]] + sorted((u for u in ids if store[u][stamp]), key=lambda u: store[u][stamp])[:again]

    names, pics = queue(3, 700), queue(4, 6000)
    now, asked, until = int(time.time()), [0, 0], time.monotonic() + 480  # the scan's merge step waits for this job
    while (names or pics) and time.monotonic() < until:
        if names:
            part, names = names[:100], names[100:]
            j = ask("users", "/v1/users", 10, {"userIds": part, "excludeBannedUsers": False})
            if j is None:
                names = []
            else:
                who = {x.get("id"): x for x in j.get("data") or []}
                for u in part:
                    x = who.get(u) or {}  # an account Roblox no longer has comes back without a name
                    name = str(x.get("name") or "")[:40]
                    store[u][0], store[u][1], store[u][3] = name, str(x.get("displayName") or name)[:40], now
                asked[0] += len(part)
        for _ in range(9):  # nine picture requests fit in the six seconds between two name requests
            if not pics:
                break
            part, pics = pics[:100], pics[100:]
            j = ask("thumbnails", "/v1/users/avatar-headshot?userIds=" + ",".join(map(str, part)) + "&size=150x150&format=Png&isCircular=false", 100)
            if j is None:
                pics = []
                break
            got = {x.get("targetId"): x for x in j.get("data") or []}
            for u in part:
                state = (got.get(u) or {}).get("state")
                if state in ("Completed", "Blocked"):  # anything else (still being drawn, an error) is asked for again next run
                    store[u][2], store[u][4] = short(got[u].get("imageUrl")) if state == "Completed" else "", now
            asked[1] += len(part)
    by_id, by_name = [{} for _ in range(1024)], [{} for _ in range(256)]
    for u, e in store.items():
        if e[3] or e[4]:
            by_id[u % 1024][str(u)] = e
        if e[0]:
            by_name[shard(e[0].lower(), 256)][e[0].lower()] = u
    write(os.path.join(a.out, "id"), by_id)
    write(os.path.join(a.out, "by"), by_name)
    for kind, t in teams.items():
        packs = [{} for _ in range(512)]
        for key, members in t.items():
            packs[shard(key, 512)][key] = {str(u): store[u][:3] for u in members if store[u][0] or store[u][2]}
        write(os.path.join(a.out, "team", kind), packs)
    print(f"Asked Roblox about {asked[0]} names and {asked[1]} pictures. Of {len(ids)} players, "
          f"{sum(1 for e in store.values() if e[0])} have a name saved and {sum(1 for e in store.values() if e[2])} a picture.")
