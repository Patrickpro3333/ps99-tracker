#!/usr/bin/env python3
"""
Builds the list of every clan battle on clan-battles.html from BIG Games' public API:
dates, prizes by placement (the battle settings in the game data) and the top 3 clans.

Usage:  python3 battles.py
        python3 battles.py --clans clans.json   (keeps the clan pages it read in clans.json and reuses them next time)
Run it after each clan battle ends, then commit clan-battles.html. It takes about 35 minutes, because some
2,800 clans' own pages are read at 90 a minute (the API allows under 100 per IP). Only the part between
the <!-- battles --> and <!-- /battles --> markers is replaced; the rest of the page is edited by hand.

Winners come from each clan's own record (Battles[battle].Place). The clans read are the top 2,000 of the latest
battle plus the 1,000 with the most diamonds: old winners have often left the top 2,000, but most are still rich
(Goop, which won 8 battles in 2024, is found only that way). A deleted clan stays missing.
"""
import argparse, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timezone

API = os.environ.get("PS99_API", "https://ps99.biggamesapi.io")
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clan-battles.html")
ap = argparse.ArgumentParser()
ap.add_argument("--clans", default="", help="file to save the clan pages in, and to reuse them from when it exists")
a = ap.parse_args()
next_at = 0.0


def get(path):
    # Same spacing as scan.py: 90 requests a minute, by start time.
    global next_at
    for attempt in range(8):
        now = time.monotonic()
        if now < next_at:
            time.sleep(next_at - now)
        next_at = max(now, next_at) + 60 / 90
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "ps99-tracker-battles/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.load(r)
            return j.get("data") if j.get("status") == "ok" else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(int(e.headers.get("Retry-After") or 30) + 1 if e.code == 429 else 5 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    return None


def read_clans():
    # {clan name: {battle id: [place, points]}} for battles whose prizes were handed out (the final placement).
    if a.clans and os.path.exists(a.clans):
        with open(a.clans) as f:
            return json.load(f)
    names = []
    for sort, page in (("Points", 1), ("Points", 2), ("DepositedDiamonds", 1)):
        d = get(f"/api/clans?page={page}&pageSize=1000&sort={sort}&sortOrder=desc")
        if d is None:
            sys.exit(f"Could not read the clan list ({sort}, page {page}), so nothing was written.")
        names += [x["Name"] for x in d]
    names = list(dict.fromkeys(names))
    clans = {}
    for i, n in enumerate(names, 1):
        d = get("/api/clan/" + urllib.parse.quote(n, safe=""))
        if d:
            clans[d.get("Name") or n] = {k: [b.get("Place"), b.get("Points")] for k, b in (d.get("Battles") or {}).items()
                                         if b.get("ProcessedAwards") and b.get("Place")}
        if i % 100 == 0:
            print(f"{i}/{len(names)} clans read", flush=True)
    if len(clans) < len(names) * 0.95:
        sys.exit(f"Only {len(clans)} of {len(names)} clan pages could be read, so nothing was written.")
    if a.clans:
        with open(a.clans, "w") as f:
            json.dump(clans, f)
    return clans


def name(bid, c):
    # Older battles have a real title; newer ones only their id (and the latest a splash title).
    t = c.get("Title") or ""
    if " " in t:
        return t
    if c.get("SplashTitle"):
        return c["SplashTitle"].rstrip("!")
    return re.sub(r"([a-z])([A-Z0-9])", r"\1 \2", bid)


def item(d, kind=""):
    d = d.get("_data") or {}
    s = ("Shiny " if d.get("sh") else "") + {1: "Golden ", 2: "Rainbow "}.get(d.get("pt"), "") + d.get("id", "?") + kind
    return f"{d['_am']} × {s}" if d.get("_am") else s


def band(b, w):
    return f"#{b:,}" if b == w else f"#{b:,}-{w:,}"


def prizes(c):
    rows = []
    pr = c.get("PlacementRewards") or []
    # The two prizes that are not pets or gifts are a booth and a hoverboard: in every battle the booth goes to the
    # wider band (top 50) and the hoverboard to the narrower one (top 10, later top 30). The Ghost and Reaper battles,
    # where the two have different names, show it: only "Booth | Ghost Cat" and "Hoverboard | Ghost" exist.
    pet = lambda p: bool(re.match(r"(Huge|Titanic|Gargantuan) ", p["Item"]["_data"].get("id", "")))
    cos = sorted((p for p in pr if not pet(p) and "Gift" not in p["Item"]["_data"].get("id", "")), key=lambda p: p["Worst"] - p["Best"])
    kinds = {id(p): k for p, k in zip(cos, [" hoverboard", " booth"])} if len(cos) == 2 else {}
    # Pets first, from the winner down; then the booth, hoverboard and gifts, narrowest band first.
    for p in sorted(pr, key=lambda p: (0, p["Best"], p["Worst"] - p["Best"], p.get("BestContributor", 0)) if pet(p) else (1, p["Worst"] - p["Best"])):
        who = band(p["Best"], p["Worst"])
        if p.get("BestContributor"):
            b, w = p["BestContributor"], p["WorstContributor"]
            who += f" (top {w} contributors)" if b == 1 else f" (contributors {b}-{w})"
        rows.append((who, item(p["Item"], kinds.get(id(p), ""))))
    for medal in ("Gold", "Silver", "Bronze", "Good"):
        got = Counter(item(x) for x in (c.get("Rewards") or {}).get(medal) or [])
        if got:
            rows.append((f"{medal} medal", ", ".join(f"{n} × {k}" if n > 1 else k for k, n in got.items())))
    return rows


def day(t, year=True):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%-d %b %Y" if year else "%-d %b")


def dates(c):
    s, f = c["StartTime"], c["FinishTime"]
    same = day(s)[-4:] == day(f)[-4:]
    return f"{day(s, not same)} to {day(f)}", round((f - s) / 86400)


def link(n):
    return f'<a href="/?clan={urllib.parse.quote(n, safe="")}">{html.escape(n)}</a>'


def build(battles, clans, now):
    started = sorted((b for b in battles if b["configData"].get("StartTime", now + 1) <= now),
                     key=lambda b: b["configData"]["StartTime"], reverse=True)
    per = {}
    for clan, rec in clans.items():
        for bid, (place, pts) in rec.items():
            per.setdefault(bid, []).append((place, pts, clan))
    # A clan's Place is only as fresh as its record (a clan that stopped playing can keep an early, better place),
    # so a top 3 place counts only when no clan placed level or behind it has more points.
    top = {bid: sorted(e for e in t if e[0] <= 3 and not any(o[1] > e[1] and o[0] >= e[0] for o in t)) for bid, t in per.items()}
    wins = Counter(t[0][2] for t in top.values() if t and t[0][0] == 1)
    lost = sum(1 for t in top.values() if not t or t[0][0] != 1)
    out = [f'<p class="date">Updated {day(now)}. {len(started)} battles since {day(started[-1]["configData"]["StartTime"])[-8:]}.</p>']
    if wins:
        out.append('<h2 id="wins">Most clan battle wins</h2><ol class="wins">')
        out += [f"<li>{link(c)} <span>{n} {'wins' if n > 1 else 'win'}</span></li>" for c, n in wins.most_common(10)]
        out.append("</ol>")
        if lost:
            out.append(f"<p>{lost} {'battles are' if lost > 1 else 'battle is'} not counted, because the winning clan could not be found any more.</p>")
    out.append('<h2 id="all">Every battle</h2><div class="tw"><table><thead><tr><th>Battle</th><th>Dates</th><th>Winner</th></tr></thead><tbody>')
    for b in started:
        c, bid = b["configData"], b["configName"]
        w = top.get(bid, [])
        win = ("Running now" if c["FinishTime"] > now else link(w[0][2]) if w and w[0][0] == 1 else "Not found" if bid in per
               else "League event" if "League" in name(bid, c) else "Not recorded")
        out.append(f'<tr><td><a href="#{bid}">{html.escape(name(bid, c))}</a></td><td>{dates(c)[0]}</td><td>{win}</td></tr>')
    out.append("</tbody></table></div>")
    for b in started:
        c, bid = b["configData"], b["configName"]
        when, days = dates(c)
        out.append(f'<section class="bt" id="{bid}"><h3>{html.escape(name(bid, c))}</h3><p class="when">{when} · {days} days</p>')
        if c.get("SplashDesc"):
            out.append(f"<p>In-game task: {html.escape(c['SplashDesc'])}</p>")
        w = top.get(bid, [])
        if c["FinishTime"] > now:
            out.append('<p>Running now. The <a href="/">live leaderboard</a> has the current standings.</p>')
        elif bid in per:
            out.append('<ol class="podium">' + "".join(f'<li value="{p}">{link(n)} <span>{pts:,} points</span></li>' for p, pts, n in w) + "</ol>")
            if len(w) < 3:
                out.append('<p class="when">A place missing here belongs to a clan that could not be found any more.</p>')
        elif "League" in name(bid, c):
            out.append("<p>A league event, so there are no clan placements.</p>")
        else:
            out.append("<p>The game data has no clan placements for this battle.</p>")
        rows = prizes(c)
        if rows:
            out.append(f'<table class="pz"><thead><tr><th>{"Placement" if c.get("PlacementRewards") else "Medal"}</th><th>Prize</th></tr></thead><tbody>'
                       + "".join(f"<tr><td>{html.escape(r)}</td><td>{html.escape(p)}</td></tr>" for r, p in rows) + "</tbody></table>")
        out.append("</section>")
    return "\n".join(out)


# Self-check of the prize names on a shape the API uses.
assert prizes({"PlacementRewards": [
    {"Best": 1, "Worst": 1, "BestContributor": 1, "WorstContributor": 100, "Item": {"_data": {"id": "Gargantuan Wolf"}}},
    {"Best": 2, "Worst": 3, "Item": {"_data": {"id": "Titanic Goat", "pt": 2}}},
    {"Best": 1, "Worst": 50, "Item": {"_data": {"id": "Ender"}}}, {"Best": 1, "Worst": 30, "Item": {"_data": {"id": "Ender"}}},
    {"Best": 1, "Worst": 500, "Item": {"_data": {"id": "Clan Gift 2", "_am": 2}}}]}) == [
    ("#1 (top 100 contributors)", "Gargantuan Wolf"), ("#2-3", "Rainbow Titanic Goat"), ("#1-30", "Ender hoverboard"),
    ("#1-50", "Ender booth"), ("#1-500", "2 × Clan Gift 2")]

if __name__ == "__main__":
    battles = get("/api/collection/GuildBattles")
    if not battles:
        sys.exit("Could not read the battle list, so nothing was written.")
    body = build(battles, read_clans(), int(time.time()))
    with open(PAGE) as f:
        page = f.read()
    new, n = re.subn(r"(<!-- battles -->).*(<!-- /battles -->)", lambda m: f"{m[1]}\n{body}\n{m[2]}", page, flags=re.S)
    if n != 1:
        sys.exit("clan-battles.html has no <!-- battles --> markers.")
    with open(PAGE, "w") as f:
        f.write(new)
    print("clan-battles.html updated")
