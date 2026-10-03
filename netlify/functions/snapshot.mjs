// Every 15 minutes: save each top-2,000 league's and clan's points and rank to Netlify Blobs.
// 40 list requests per run (4 at a time per kind), well under the API's 100 per minute,
// and the whole run has to finish inside Netlify's 30 second limit for scheduled functions.
import { getStore } from '@netlify/blobs'
import { API, STORE, KEEP, BUCKETS, PAGES, KINDS, bucket, bucketKey } from '../lib/history.mjs'

export const config = { schedule: '*/15 * * * *' }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function pool(items, n, fn) {
  const out = new Array(items.length)
  let next = 0
  await Promise.all(Array.from({ length: n }, async () => {
    while (next < items.length) {
      const i = next++
      out[i] = await fn(items[i], i)
    }
  }))
  return out
}

async function page(kind, p) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const r = await fetch(API + KINDS[kind].path + p, {
        headers: { 'User-Agent': 'ps99-tracker-history/1.0' },
        signal: AbortSignal.timeout(8000),
      })
      if (r.status === 429) return null // rate limited: skip this page, never hammer the API
      if (r.ok) {
        const rows = KINDS[kind].rows((await r.json()).data)
        if (Array.isArray(rows)) return rows
      }
    } catch (e) {}
    await sleep(800)
  }
  return null
}

async function snapKind(store, kind, t) {
  const pages = await pool(Array.from({ length: PAGES }, (_, i) => i + 1), 4, (p) => page(kind, p))
  const now = new Map()
  let failed = 0
  pages.forEach((rows, pi) => {
    if (!rows) return failed++
    rows.forEach((x, i) => {
      const name = String(x.Name || '').toLowerCase()
      // Names aren't unique; keep the higher one, like the API's own name lookup does.
      // Rank comes from the page position, so a failed page never shifts other ranks.
      if (name && !now.has(name) && typeof x.Points === 'number') now.set(name, [t, x.Points, pi * 100 + i + 1])
    })
  })
  if (!now.size) return { t: 0, n: 0, failed }

  const byBucket = Array.from({ length: BUCKETS }, () => [])
  for (const [name, entry] of now) byBucket[bucket(name)].push([name, entry])
  const cut = t - KEEP
  await pool(byBucket, 16, async (items, i) => {
    const key = bucketKey(kind, i)
    const old = (await store.get(key, { type: 'json' })) || {}
    const next = {}
    for (const name in old) {
      const h = old[name].filter((e) => e[0] >= cut)
      if (h.length) next[name] = h
    }
    for (const [name, entry] of items) {
      const h = next[name] || (next[name] = [])
      // A retried run must not add a second point for the same moment.
      if (h.length && entry[0] - h[h.length - 1][0] < 60) h[h.length - 1] = entry
      else h.push(entry)
    }
    await store.setJSON(key, next)
  })
  return { t, n: now.size, failed }
}

export default async () => {
  const started = Date.now()
  const t = Math.floor(started / 1000)
  const store = getStore({ name: STORE, consistency: 'strong' })
  const [league, clan] = await Promise.all([snapKind(store, 'league', t), snapKind(store, 'clan', t)])
  const meta = (await store.get('meta', { type: 'json' })) || {}
  if (league.t) meta.league = { t, n: league.n, failedPages: league.failed }
  if (clan.t) meta.clan = { t, n: clan.n, failedPages: clan.failed }
  meta.lastRun = { t, ms: Date.now() - started, league, clan }
  await store.setJSON('meta', meta)
  console.log(`snapshot ${new Date(started).toISOString()}: ${league.n} leagues (${league.failed} pages failed), ${clan.n} clans (${clan.failed} pages failed), ${Date.now() - started} ms`)
}
