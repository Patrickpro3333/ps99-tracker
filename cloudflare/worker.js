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
  if (!env.GH_DISPATCH_TOKEN) {
    console.log('GH_DISPATCH_TOKEN is not set, so nothing was started.')
    return
  }
  const jobs = ['history.yml', 'scan.yml']
  console.log((await Promise.all(jobs.map(w => start(env, w)))).join('; '))
}

export default {
  fetch(request, env) {
    const name = new URL(request.url).pathname.split('/')[1]
    if (name === 'ps99api' || name === 'rbx' || name === 'rbxt') return proxy({ request }, name)
    return env.ASSETS.fetch(request)
  },
  scheduled(event, env, ctx) {
    ctx.waitUntil(startJobs(env))
  },
}
