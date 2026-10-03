// GET /api/history?kind=league|clan&name=<team>  -> that team's last 24h of snapshots
// GET /api/history?status                         -> when the snapshot job last ran
import { getStore } from '@netlify/blobs'
import { STORE, STEP, KINDS, bucket, bucketKey } from '../lib/history.mjs'

export const config = { path: '/api/history' }

// Snapshots change every 15 minutes, so a couple of minutes of CDN caching is safe.
const CACHE = { browser: 'public, max-age=60', cdn: 'public, durable, s-maxage=120, stale-while-revalidate=300' }
const NONE = { browser: 'no-store', cdn: 'no-store' }

const reply = (body, status, cache) => new Response(JSON.stringify(body), {
  status,
  headers: {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': cache.browser,
    'Netlify-CDN-Cache-Control': cache.cdn,
    'Netlify-Vary': 'query=kind|name|status',
  },
})

export default async (req) => {
  const q = new URL(req.url).searchParams
  const store = getStore(STORE)
  const now = Math.floor(Date.now() / 1000)
  if (q.has('status')) {
    return reply({ v: 1, now, step: STEP, meta: (await store.get('meta', { type: 'json' })) || null }, 200, NONE)
  }
  const kind = q.get('kind')
  const name = (q.get('name') || '').trim().toLowerCase()
  if (!KINDS[kind] || !name || name.length > 64) {
    return reply({ v: 1, error: 'Use ?kind=league or ?kind=clan, and &name=<team name>.' }, 400, NONE)
  }
  try {
    const [b, meta] = await Promise.all([
      store.get(bucketKey(kind, bucket(name)), { type: 'json' }),
      store.get('meta', { type: 'json' }),
    ])
    // updated: when the snapshot job last succeeded for this kind, so the page can say how old the data is.
    return reply({ v: 1, kind, name, now, step: STEP, updated: (meta && meta[kind] && meta[kind].t) || 0, h: (b && b[name]) || [] }, 200, CACHE)
  } catch (e) {
    return reply({ v: 1, error: 'History is unavailable right now.' }, 503, NONE)
  }
}
