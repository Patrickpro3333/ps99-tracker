# PS99 Tracker with an automatic global scan

GitHub scans the top leagues and clans twice a day and saves the result as `ranks.json`.
Netlify redeploys the site with the new file. Every visitor then sees exact
"Better than X%" numbers instantly, with no waiting for the in-page scan.

## Setup (about 10 minutes, one time)

1. Create a free GitHub account and a new PUBLIC repository (public repos get free Actions minutes).
2. Upload every file from this folder, including the hidden `.github` folder
   (drag the whole folder into the repository's "Upload files" page).
3. In the repo go to Settings > Actions > General > Workflow permissions,
   choose "Read and write permissions", and save.
4. Go to the Actions tab, open "Scan PS99 leaderboards", and press "Run workflow".
   The first run takes about 70 minutes. After that it runs by itself twice a day.
5. In Netlify choose Add new site > Import an existing project > GitHub, pick the repo,
   leave the build command empty, and deploy. Each new `ranks.json` redeploys the site.

If your site address changes, update the address in `index.html` (canonical and share tags),
`robots.txt`, and `sitemap.xml`.

## Without GitHub

Run `python3 scan.py` on your computer (about 35 minutes), then put the `ranks.json` it
creates next to `index.html` and redeploy. You can also open the site, wait for its own scan
to finish, and use the "Download ranks.json" button in the "For the site owner" box.
