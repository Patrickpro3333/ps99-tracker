// Starts the GitHub Actions that save the site's data. GitHub's own scheduler skipped most runs,
// so Netlify's scheduler presses the button instead: history every 15 minutes, the ranks scan every 3 hours.
// The jobs skip themselves if they ran recently, so GitHub's schedule can stay on as a backup.
// Needs GH_DISPATCH_TOKEN: a fine-grained GitHub token for this repository only, with Actions: read and write.
export const config = { schedule: '*/15 * * * *' }

const REPO = 'Patrickpro3333/ps99-tracker'

async function start(workflow) {
  try {
    const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${process.env.GH_DISPATCH_TOKEN}`,
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

export default async () => {
  if (!process.env.GH_DISPATCH_TOKEN) {
    console.log('GH_DISPATCH_TOKEN is not set, so nothing was started.')
    return
  }
  const now = new Date()
  const jobs = ['history.yml']
  if (now.getUTCHours() % 3 === 0 && now.getUTCMinutes() < 15) jobs.push('scan.yml')
  console.log((await Promise.all(jobs.map(start))).join('; '))
}
