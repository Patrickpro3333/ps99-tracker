// Shared by the snapshot (scheduled) and history (API) functions.
// History is sharded by team name into BUCKETS blobs per kind, each holding
// { "<lowercase name>": [[unixSeconds, points, rank], ...] } for the last KEEP seconds.

export const API = 'https://ps99.biggamesapi.io'
export const STORE = 'ps99-history'
export const STEP = 900 // seconds between snapshots (the schedule below)
export const KEEP = 24 * 3600 + 1200 // 24 hours, plus one spare snapshot so the 24h gain has a start point
export const BUCKETS = 32
export const PAGES = 20 // 20 pages of 100 = top 2,000

export const KINDS = {
  league: { path: '/v1/leagues?pageSize=100&sort=Points&sortOrder=desc&page=', rows: (d) => d && d.leagues },
  clan: { path: '/api/clans?pageSize=100&sort=Points&sortOrder=desc&page=', rows: (d) => d },
}

// FNV-1a, so both functions agree on which bucket a team lives in.
export function bucket(name) {
  let h = 0x811c9dc5
  for (const ch of name) {
    h ^= ch.codePointAt(0)
    h = Math.imul(h, 16777619) >>> 0
  }
  return h % BUCKETS
}

export const bucketKey = (kind, i) => `h/${kind}/${i}`
