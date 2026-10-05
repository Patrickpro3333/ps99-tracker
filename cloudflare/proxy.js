// Passes /ps99api, /rbx and /rbxt through to the real APIs, like Netlify's 200 rewrites did.
// Cloudflare's _redirects can't proxy to other sites, so the Pages Functions in functions/ call this.
// Every call counts toward the free 100,000 Functions requests a day; the page falls back to other
// routes when a proxy fails, so it keeps working if that ever runs out.
const HOSTS = { ps99api: 'ps99.biggamesapi.io', rbx: 'users.roblox.com', rbxt: 'thumbnails.roblox.com' }
const PASS = ['accept', 'accept-language', 'content-type', 'user-agent']

export async function proxy({ request }, name) {
  if (!['GET', 'HEAD', 'POST'].includes(request.method)) return new Response('Method not allowed', { status: 405 })
  const url = new URL(request.url), to = new URL('https://' + HOSTS[name])
  to.pathname = url.pathname.slice(name.length + 1) || '/'
  to.search = url.search
  const headers = new Headers()
  PASS.forEach(k => request.headers.has(k) && headers.set(k, request.headers.get(k)))
  try {
    const r = await fetch(to, {
      method: request.method,
      headers,
      body: request.method === 'POST' ? await request.arrayBuffer() : undefined,
    })
    const res = new Response(r.body, r)
    res.headers.delete('set-cookie')
    res.headers.set('X-Robots-Tag', 'noindex')
    return res
  } catch (e) {
    return new Response('Could not reach ' + to.host, { status: 502, headers: { 'X-Robots-Tag': 'noindex' } })
  }
}
