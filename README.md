# PS99 Tracker

Live site: https://ps99-tracker.patrick9.workers.dev/

A static site on Cloudflare (one Worker, `ps99-tracker`, set up in `wrangler.jsonc`). All the data work runs on GitHub Actions (free for public repos) and is
saved to two data branches that the page reads straight from GitHub:

| Job | When | Saves to | Used for |
|---|---|---|---|
| `history.py` (`.github/workflows/history.yml`) | every hour | `data-history` branch | points per hour, gains, rank change and the chart, instantly for every visitor |
| `scan.py` (`.github/workflows/scan.yml`) | every hour, about 3 minutes per run (about 5 when every team changed; teams whose points didn't change are reused). The changed teams are read by 17 machines at once, 1,530 requests a minute together (90 each), which BIG Games agreed to; `SHARDS` and `TOTAL_RATE` at the top of the workflow set this | `data-ranks` branch (`ranks.json`, `players/`, `teams/`) | exact "Better than X%" player ranks with no waiting, and the player search (which top-2,000 league and clan each player is in) |

Data never goes on `main`: every commit to `main` is a site deploy (free on Cloudflare). Builds for
other branches must stay off (see Setup), or every hourly push to the data branches would start a
failing build.

Both data branches are a single commit that is force-pushed on every run, so the repository
doesn't grow. The page shows how old the data is and leaves a gap in the chart where a snapshot
is missing.

### What starts the jobs

GitHub's own scheduler skipped most runs, so Cloudflare starts them instead: the Worker's Cron
Trigger (`wrangler.jsonc`) runs `scheduled` in `cloudflare/worker.js` every hour on the hour, which
asks GitHub to run the history job and the scan. GitHub's
schedules stay on as a backup that only does the work when Cloudflare missed (history: no snapshot
in the last 45 minutes; scan: none finished in the last 50 minutes), so snapshots stay on the hour
and nothing runs twice.

The Worker needs a secret `GH_DISPATCH_TOKEN`: a fine-grained GitHub token with access to this
repository only and the permission "Actions: Read and write". When the token expires, create a new
one and replace the secret. The Worker's logs show "started" or the error for every run.

### Proxies

`/ps99api`, `/rbx` and `/rbxt` pass requests through to the BIG Games API and Roblox, for browsers
that can't reach them directly. Cloudflare's `_redirects` can't proxy to other sites, so the Worker
does it (`cloudflare/proxy.js`). Only these paths run code; they count toward the free 100,000
Worker requests a day, and the page falls back to other routes if they fail. Every other file is
served as a static asset, free and unlimited; `.assetsignore` keeps scripts and docs private.

## Setup (one time)

1. Create a PUBLIC GitHub repository (public repos get free Actions minutes) and upload every
   file, including the hidden `.github` folder.
2. In the repo go to Settings > Actions > General > Workflow permissions, choose
   "Read and write permissions", and save.
3. In the Actions tab, run "Save PS99 history" and "Scan PS99 leaderboards" once by hand.
4. In Cloudflare go to Workers & Pages > Create > Import a repository, pick the repo, name the
   Worker `ps99-tracker` (it must match `wrangler.jsonc`), production branch `main`, build command
   empty, deploy command `npx wrangler deploy`. In the Worker's Settings > Build, turn off builds for
   non-production branches, so the data branches never build.
5. In the Worker's Settings > Variables and Secrets add the secret `GH_DISPATCH_TOKEN` (see above).
   The hourly Cron Trigger comes from `wrangler.jsonc`. From then on the jobs run on their own.

If the repository or its owner changes, update `RAW` in `index.html`. If the site address
changes, update it in `index.html` (canonical and share tags), `robots.txt` and `sitemap.xml`.

## Without GitHub

Run `python3 scan.py` on your computer (about 45 minutes), then put the `ranks.json` it creates
next to `index.html` and redeploy. You can also open the site, wait for its own scan to finish,
and use the "Download ranks.json" button in the "For the site owner" box. The page uses
`ranks.json` from the `data-ranks` branch first, and the copy next to `index.html` otherwise.
