// The PS99 Tracker Worker. Cloudflare serves the site's files itself (free and unlimited); this code
// only runs for the three API proxies and the 15-minute timer (see wrangler.jsonc).
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

// Temporary check for the hourly trigger: is the secret set, and does GitHub accept it? Never shows the token.
async function jobsCheck(env) {
  const t = env.GH_DISPATCH_TOKEN, out = { secretSet: !!t, kind: !t ? null : t.startsWith('github_pat_') ? 'fine-grained' : t.startsWith('ghp_') ? 'classic' : 'other', spaces: !!t && t !== t.trim() }
  if (t) {
    const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/scan.yml`, {
      headers: { Authorization: `Bearer ${t.trim()}`, Accept: 'application/vnd.github+json', 'User-Agent': 'ps99-tracker-trigger' },
    })
    out.github = r.status
    // Write test: "enable" the scan workflow, which is already enabled, so nothing changes (204 = allowed).
    const w = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/scan.yml/enable`, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${t.trim()}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'ps99-tracker-trigger' },
    })
    out.write = w.status
    if (!w.ok) out.writeError = (await w.text()).slice(0, 160)
  }
  out.lastTimerRun = env.STATUS ? JSON.parse((await env.STATUS.get('last')) || 'null') : 'no store'
  return new Response(JSON.stringify(out), { headers: { 'content-type': 'application/json', 'cache-control': 'no-store', 'x-robots-tag': 'noindex' } })
}

export default {
  fetch(request, env) {
    const name = new URL(request.url).pathname.split('/')[1]
    if (name === '__jobs') return jobsCheck(env)
    if (name === 'ps99api' || name === 'rbx' || name === 'rbxt') return proxy({ request }, name)
    return env.ASSETS.fetch(request)
  },
  scheduled(event, env, ctx) {
    ctx.waitUntil(timerRun(event, env))
  },
}
