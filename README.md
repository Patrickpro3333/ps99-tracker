# PS99 Tracker with an automatic global scan

Live site: https://petsim99tracker.netlify.app/

GitHub scans the top leagues and clans every 3 hours and saves the result as `ranks.json`.
Netlify redeploys the site with the new file. Every visitor then sees exact
"Better than X%" numbers instantly, with no waiting for the in-page scan.

## Setup (about 10 minutes, one time)

1. Create a free GitHub account and a new PUBLIC repository (public repos get free Actions minutes).
2. Upload every file from this folder, including the hidden `.github` folder
   (drag the whole folder into the repository's "Upload files" page).
3. In the repo go to Settings > Actions > General > Workflow permissions,
   choose "Read and write permissions", and save.
4. Go to the Actions tab, open "Scan PS99 leaderboards", and press "Run workflow".
   The first run takes about 45 minutes. After that it runs by itself every 3 hours.
5. In Netlify choose Add new site > Import an existing project > GitHub, pick the repo,
   leave the build command empty, and deploy. Each new `ranks.json` redeploys the site.

If your site address changes, update the address in `index.html` (canonical and share tags),
`robots.txt`, and `sitemap.xml`.

## Server history (Netlify Functions + Blobs)

Points per hour, gains, rank change and the chart work the moment someone opens a team, because
the site keeps its own 24 hour history:

- `netlify/functions/snapshot.mjs` runs every 15 minutes. It reads the top 2,000 leagues and clans
  (40 requests) and saves each team's points and rank to Netlify Blobs, keeping 24 hours.
- `netlify/functions/history.mjs` serves one team's history at
  `/api/history?kind=league&name=UN00` (or `kind=clan`). `/api/history?status` shows when the
  snapshot job last ran.
- The page merges that with the snapshots it takes itself every minute while open, and falls back
  to its own data if the function is down.

Nothing needs setting up in Netlify: `netlify.toml` and `package.json` in this repo are enough.
Scheduled functions only run on the published site. To run one right away, open the site in
Netlify > Functions > snapshot > Run now.

## Without GitHub

Run `python3 scan.py` on your computer (about 45 minutes), then put the `ranks.json` it
creates next to `index.html` and redeploy. You can also open the site, wait for its own scan
to finish, and use the "Download ranks.json" button in the "For the site owner" box.
