// The PS99 Tracker Worker. Cloudflare serves the site's files, the page included, itself (free and unlimited);
// this code only runs for the three API proxies, /__jobs, /sitemap.xml and the 15-minute timer (see wrangler.jsonc).
import { proxy } from './proxy.js'

const REPO = 'Patrickpro3333/ps99-tracker'

// Starts the GitHub Actions that save the site's data. GitHub's own scheduler skipped most runs, so
// this presses the button every 15 minutes instead: history and the ranks scan. The jobs skip themselves if
// they ran recently, so GitHub's schedule can stay on as a backup.
// Needs the secret GH_DISPATCH_TOKEN: a fine-grained GitHub token for this repository only, with Actions: read and write.
async function start(env, workflow) {
  try {
    const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'ps99-tracker-trigger',
      },
      body: JSON.stringify({ ref: 'main' }),
    })
    return `${workflow}: ${r.ok ? 'started' : `failed (${r.status}) ${(await r.text()).slice(0, 200)}`}`
  } catch (e) {
    return `${workflow}: failed (${e.message})`
  }
}

async function startJobs(env) {
  if (!env.GH_DISPATCH_TOKEN) return 'GH_DISPATCH_TOKEN is not set, so nothing was started.'
  const jobs = ['history.yml', 'scan.yml']
  return (await Promise.all(jobs.map(w => start(env, w)))).join('; ')
}

// Each timer run is logged and its result kept in the STATUS store, so /__jobs can show the last one.
async function timerRun(event, env) {
  let result
  try { result = await startJobs(env) } catch (e) { result = `error: ${e.message}` }
  console.log(result)
  if (env.STATUS) await env.STATUS.put('last', JSON.stringify({ planned: new Date(event.scheduledTime).toISOString(), ran: new Date().toISOString(), cron: event.cron, result }))
}

// Check for the timer: is the secret set, and what did the last run get back from GitHub? Never shows the token.
// It no longer calls GitHub itself: the page is public, so every visit used to spend some of the token's GitHub allowance.
async function jobsCheck(env) {
  const t = env.GH_DISPATCH_TOKEN, out = { secretSet: !!t, kind: !t ? null : t.startsWith('github_pat_') ? 'fine-grained' : t.startsWith('ghp_') ? 'classic' : 'other', spaces: !!t && t !== t.trim() }
  out.lastTimerRun = env.STATUS ? JSON.parse((await env.STATUS.get('last')) || 'null') : 'no store'
  return new Response(JSON.stringify(out), { headers: { 'content-type': 'application/json', 'cache-control': 'no-store', 'x-robots-tag': 'noindex' } })
}

// The sitemap lists the home page and the pages of the top 1,000 clans and top 100 leagues (?clan=NAME), so search
// engines find them. It is made here so it stays current; crawlers read it a few times a day. If the API fails, the
// plain sitemap.xml (the home page only) is served instead.
async function sitemap(request, env) {
  try {
    const get = async p => { const r = await fetch('https://ps99.biggamesapi.io' + p, { headers: { 'User-Agent': 'ps99-tracker-sitemap' } }); if (!r.ok) throw new Error(r.status); return (await r.json()).data }
    const [clans, leagues] = await Promise.all([get('/api/clans?page=1&pageSize=1000&sort=Points&sortOrder=desc'), get('/v1/leagues?page=1&pageSize=100&sort=Points&sortOrder=desc')])
    const day = new Date().toISOString().slice(0, 10), page = q => `<url><loc>https://ps99tracker.xyz/${q}</loc><lastmod>${day}</lastmod></url>`
    // The same address the page itself uses for a team (encodeURIComponent leaves nothing XML needs escaped).
    const teams = (k, a) => (a || []).map(x => page(`?${k}=${encodeURIComponent(x.Name)}`)).join('\n')
    const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${page('')}\n${teams('clan', clans)}\n${teams('league', leagues && leagues.leagues)}\n</urlset>\n`
    return new Response(xml, { headers: { 'content-type': 'application/xml', 'cache-control': 'public, max-age=3600' } })
  } catch (e) {
    return env.ASSETS.fetch(request)
  }
}

export default {
  fetch(request, env) {
    const name = new URL(request.url).pathname.split('/')[1]
    if (name === '__jobs') return jobsCheck(env)
    if (name === 'sitemap.xml') return sitemap(request, env)
    if (name === 'ps99api' || name === 'rbx' || name === 'rbxt') return proxy({ request }, name)
    return env.ASSETS.fetch(request)
  },
  scheduled(event, env, ctx) {
    ctx.waitUntil(timerRun(event, env))
  },
}
