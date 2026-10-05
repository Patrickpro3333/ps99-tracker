// Starts the GitHub Actions that save the site's data. GitHub's own scheduler skipped most runs,
// so this Cloudflare Worker presses the button every hour instead: history and the ranks scan.
// The jobs skip themselves if they ran recently, so GitHub's schedule can stay on as a backup.
// Cloudflare Pages has no timer, so this is a separate Worker (see README, "What starts the jobs").
// Needs the secret GH_DISPATCH_TOKEN: a fine-grained GitHub token for this repository only, with Actions: read and write.
const REPO = 'Patrickpro3333/ps99-tracker'

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

export default {
  async scheduled(event, env) {
    if (!env.GH_DISPATCH_TOKEN) {
      console.log('GH_DISPATCH_TOKEN is not set, so nothing was started.')
      return
    }
    const jobs = ['history.yml', 'scan.yml']
    console.log((await Promise.all(jobs.map(w => start(env, w)))).join('; '))
  },
  fetch: () => new Response('This worker only starts the PS99 Tracker data jobs every hour.', { status: 404 }),
}
