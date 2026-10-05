# PS99 Tracker

Live site: https://petsim99tracker.netlify.app/

A static site on Netlify. All the data work runs on GitHub Actions (free for public repos) and is
saved to two data branches that the page reads straight from GitHub:

| Job | When | Saves to | Used for |
|---|---|---|---|
| `history.py` (`.github/workflows/history.yml`) | every hour | `data-history` branch | points per hour, gains, rank change and the chart, instantly for every visitor |
| `scan.py` (`.github/workflows/scan.yml`) | every hour, about 3 minutes per run (about 5 when every team changed; teams whose points didn't change are reused). The changed teams are read by 17 machines at once, 1,530 requests a minute together (90 each), which BIG Games agreed to; `SHARDS` and `TOTAL_RATE` at the top of the workflow set this | `data-ranks` branch (`ranks.json`, `players/`, `teams/`) | exact "Better than X%" player ranks with no waiting, and the player search (which top-2,000 league and clan each player is in) |

Data never goes on `main`. Every commit to `main` is a Netlify production deploy, and on the
Free plan each one costs 15 of the 300 monthly credits (about 20 deploys a month). So only commit
to `main` when the site itself changes, and batch changes into one commit.

Both data branches are a single commit that is force-pushed on every run, so the repository
doesn't grow. The page shows how old the data is and leaves a gap in the chart where a snapshot
is missing.

### What starts the jobs

GitHub's own scheduler skipped most runs, so Netlify starts them instead:
`netlify/functions/trigger-data-jobs.mjs` is a Netlify scheduled function that runs every hour
on the hour and asks GitHub to run the history job and the scan. It only makes two small API calls, so it costs about a credit a month. GitHub's schedules stay on as a
backup that only does the work when Netlify missed (history: no snapshot in the last 45 minutes;
scan: none finished in the last 50 minutes), so snapshots stay on the hour and nothing runs twice.

The function needs a Netlify environment variable `GH_DISPATCH_TOKEN`: a fine-grained GitHub
token with access to this repository only and the permission "Actions: Read and write". When the
token expires, create a new one, update the variable and redeploy. Netlify's function log shows
"started" or the error for every run.

## Setup (one time)

1. Create a PUBLIC GitHub repository (public repos get free Actions minutes) and upload every
   file, including the hidden `.github` folder.
2. In the repo go to Settings > Actions > General > Workflow permissions, choose
   "Read and write permissions", and save.
3. In the Actions tab, run "Save PS99 history" and "Scan PS99 leaderboards" once by hand.
4. In Netlify choose Add new site > Import an existing project > GitHub, pick the repo, leave the
   build command empty. Keep branch deploys off so the data branches never build.
5. Before the first deploy, add the `GH_DISPATCH_TOKEN` environment variable (see above), then
   deploy. From then on the jobs run on their own.

If the repository or its owner changes, update `RAW` in `index.html`. If the site address
changes, update it in `index.html` (canonical and share tags), `robots.txt` and `sitemap.xml`.

## Without GitHub

Run `python3 scan.py` on your computer (about 45 minutes), then put the `ranks.json` it creates
next to `index.html` and redeploy. You can also open the site, wait for its own scan to finish,
and use the "Download ranks.json" button in the "For the site owner" box. The page uses
`ranks.json` from the `data-ranks` branch first, and the copy next to `index.html` otherwise.
