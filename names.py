#!/usr/bin/env python3
"""
Saves the Roblox name and profile picture of every player in the top teams, so the page can show them without
asking Roblox. Roblox refuses the site's own proxy (Cloudflare's addresses are shared with many other sites and
stay over Roblox's limit) and doesn't let a browser ask it directly. It does answer GitHub's machines.

Usage:  python3 names.py --prev prev --out names
--prev is the last data-ranks branch: its teams/ lists every team's players, its names/ is what was saved before.
Each run asks Roblox about the players it has no answer for yet, then about the ones checked longest ago, --max in all:
8,000 takes about 100 seconds and gets round all 60,000 players in about 2 hours. When Roblox stops answering,
what was saved before is kept. The scan's merge step saves --out next to ranks.json:
  id/<user ID % 1024>.json           {user ID: [username, display name, picture, when checked]}
  team/<league|clan>/<0-511>.json    {team name in lowercase: {user ID: [username, display name, picture]}}
  by/<0-255>.json                    {username in lowercase: user ID}, for the player search
The team and username files are picked by shard() of the name; index.html has the same sum (nmh). A picture is the
32 characters that differ between Roblox's picture addresses; pic() in index.html puts the address back together.
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--prev", default="prev", help="folder holding the previous data-ranks branch")
ap.add_argument("--out", default="names", help="folder to write the names to")
ap.add_argument("--max", type=int, default=8000, help="how many players to ask Roblox about in one run")
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
            if isinstance(e, list) and len(e) == 4:
                old[int(u)] = e
    store = {u: old[u] for u in ids if u in old}  # a player who left every top team is dropped
    todo = sorted(ids, key=lambda u: store[u][3] if u in store else 0)[:a.max]  # never asked or not answered first
    now, asked, until = int(time.time()), 0, time.monotonic() + 240  # the scan's merge step waits for this, so 4 minutes at most
    for i in range(0, len(todo), 200):  # Roblox takes 200 players a request for names, 100 for pictures
        if time.monotonic() > until:
            break
        chunk = todo[i:i + 200]
        j = ask("users", "/v1/users", 25, {"userIds": chunk, "excludeBannedUsers": False})
        who = None if j is None else {x.get("id"): x for x in j.get("data") or []}
        pics, seen = {}, set()
        for part in (chunk[:100], chunk[100:]):
            j = part and ask("thumbnails", "/v1/users/avatar-headshot?userIds=" + ",".join(map(str, part)) + "&size=150x150&format=Png&isCircular=false", 100)
            if j:
                seen.update(part)
                pics.update({x.get("targetId"): x for x in j.get("data") or []})
        if who is None and not seen:
            break
        for u in chunk:
            name, shown, pic, checked = store.get(u) or ["", "", "", 0]
            if who is not None:
                x = who.get(u) or {}  # an account Roblox no longer has comes back without a name
                name = str(x.get("name") or "")[:40]
                shown = str(x.get("displayName") or name)[:40]
            p = pics.get(u) or {}
            waiting = u not in seen or p.get("state") == "Pending"  # a picture Roblox is still drawing is asked for again next run
            if not waiting:
                pic = short(p.get("imageUrl"))
            store[u] = [name, shown, pic, checked if who is None or waiting else now]
        asked += len(chunk)
    by_id, by_name = [{} for _ in range(1024)], [{} for _ in range(256)]
    for u, e in store.items():
        by_id[u % 1024][str(u)] = e
        if e[0]:
            by_name[shard(e[0].lower(), 256)][e[0].lower()] = u
    write(os.path.join(a.out, "id"), by_id)
    write(os.path.join(a.out, "by"), by_name)
    for kind, t in teams.items():
        packs = [{} for _ in range(512)]
        for key, members in t.items():
            packs[shard(key, 512)][key] = {str(u): store[u][:3] for u in members if u in store and store[u][0]}
        write(os.path.join(a.out, "team", kind), packs)
    print(f"Asked Roblox about {asked} of {len(ids)} players. {sum(1 for e in store.values() if e[0])} have a name saved, "
          f"{sum(1 for e in store.values() if e[2])} a picture.")
