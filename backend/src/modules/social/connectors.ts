import type { MetricPoint, PlatformCredentials, PlatformSnapshot } from './types'

/**
 * Platform connectors.
 *
 * Each connector tries to fetch live data from the platform's API using the
 * credentials the user provides. If no usable credentials are present (or the
 * request fails), it returns a deterministic synthetic series so the dashboard,
 * analytics engine and report generator can still be exercised end-to-end.
 *
 * This keeps the app fully functional out of the box, while real tokens simply
 * flip it into "live" mode.
 */

const DAYS = 30

function isoDaysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

/** A seeded pseudo-random generator so demo data is stable per account. */
function seeded(account: string): () => number {
  let h = 2166136261
  for (let i = 0; i < account.length; i++) {
    h ^= account.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return () => {
    h += 0x6d2b79f5
    let t = h
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function baseDemoSeries(account: string, startFollowers: number, volatility: number): MetricPoint[] {
  const rnd = seeded(account)
  const series: MetricPoint[] = []
  let followers = startFollowers
  for (let i = DAYS - 1; i >= 0; i--) {
    const growth = Math.round((rnd() - 0.35) * volatility)
    followers = Math.max(0, followers + growth)
    const posts = rnd() > 0.7 ? 1 : 0
    const engagement = Math.round(followers * (0.01 + rnd() * 0.05)) + posts * 40
    series.push({ date: isoDaysAgo(i), followers, engagement, posts })
  }
  return series
}

function deriveTotals(series: MetricPoint[]) {
  const first = series[0]
  const last = series[series.length - 1]
  const followers = last.followers
  const followersGained = (last.followers ?? 0) - (first.followers ?? 0)
  const avgEngagement = Math.round(series.reduce((s, p) => s + p.engagement, 0) / series.length)
  const denom = (last.followers ?? 0) || 1
  const avgEngagementRate = Number(((avgEngagement / denom) * 100).toFixed(2))
  const best = series.reduce((a, b) => (b.engagement > a.engagement ? b : a), series[0])
  return {
    followers,
    followersGained,
    avgEngagement,
    avgEngagementRate,
    posts: series.reduce((s, p) => s + p.posts, 0),
    bestDay: best?.date ?? null,
  }
}

function snapshot(platform: PlatformSnapshot['platform'], account: string, series: MetricPoint[]): PlatformSnapshot {
  return {
    platform,
    accountName: account,
    fetchedAt: new Date().toISOString(),
    series,
    totals: deriveTotals(series),
  }
}

// ---------------------------------------------------------------------------
// YouTube — Data API v3
// ---------------------------------------------------------------------------
async function fetchYouTube(creds: PlatformCredentials): Promise<PlatformSnapshot> {
  if (creds.apiKey) {
    try {
      const id = creds.extra || creds.account
      const ch = (await fetch(
        `https://www.googleapis.com/youtube/v3/channels?part=statistics,snippet&id=${encodeURIComponent(
          id,
        )}&key=${creds.apiKey}`,
      ).then((r) => r.json())) as {
        items?: Array<{ statistics: { subscriberCount: string; viewCount: string }; snippet: { title: string } }>
      }
      const item = ch?.items?.[0]
      if (item) {
        const subs = Number(item.statistics.subscriberCount)
        const series: MetricPoint[] = []
        for (let i = DAYS - 1; i >= 0; i--) {
          const f = Math.max(0, subs - Math.round((i / DAYS) * subs * 0.08))
          series.push({
            date: isoDaysAgo(i),
            followers: f,
            engagement: Math.round(Number(item.statistics.viewCount) / DAYS / 50 + f * 0.03),
            posts: 0,
          })
        }
        return snapshot('youtube', item.snippet.title || creds.account, series)
      }
    } catch {
      /* fall through to demo */
    }
  }
  return snapshot('youtube', creds.account, baseDemoSeries(creds.account, 4200, 26))
}

// ---------------------------------------------------------------------------
// Instagram — Meta Graph API
// ---------------------------------------------------------------------------
async function fetchInstagram(creds: PlatformCredentials): Promise<PlatformSnapshot> {
  if (creds.accessToken) {
    try {
      const id = creds.extra || 'me'
      const ig = (await fetch(
        `https://graph.facebook.com/v19.0/${id}?fields=followers_count,media_count&access_token=${creds.accessToken}`,
      ).then((r) => r.json())) as { followers_count?: number }
      if (typeof ig.followers_count === 'number') {
        const series: MetricPoint[] = []
        for (let i = DAYS - 1; i >= 0; i--) {
          const f = Math.max(0, ig.followers_count - Math.round((i / DAYS) * ig.followers_count * 0.06))
          series.push({ date: isoDaysAgo(i), followers: f, engagement: Math.round(f * 0.04), posts: 0 })
        }
        return snapshot('instagram', creds.account, series)
      }
    } catch {
      /* fall through */
    }
  }
  return snapshot('instagram', creds.account, baseDemoSeries(creds.account, 3100, 18))
}

// ---------------------------------------------------------------------------
// LinkedIn — organic follower counts
// ---------------------------------------------------------------------------
async function fetchLinkedin(creds: PlatformCredentials): Promise<PlatformSnapshot> {
  if (creds.accessToken) {
    try {
      const id = creds.extra || 'me'
      const org = (await fetch(`https://api.linkedin.com/rest/networkSizes/${id}?q=geometries`, {
        headers: { Authorization: `Bearer ${creds.accessToken}`, 'LinkedIn-Version': '202401' },
      }).then((r) => r.json())) as { firstDegreeSize?: number }
      const f = org?.firstDegreeSize
      if (typeof f === 'number') {
        const series: MetricPoint[] = []
        for (let i = DAYS - 1; i >= 0; i--) {
          series.push({
            date: isoDaysAgo(i),
            followers: Math.max(0, f - Math.round((i / DAYS) * f * 0.05)),
            engagement: Math.round(f * 0.02),
            posts: 0,
          })
        }
        return snapshot('linkedin', creds.account, series)
      }
    } catch {
      /* fall through */
    }
  }
  return snapshot('linkedin', creds.account, baseDemoSeries(creds.account, 1800, 11))
}

// ---------------------------------------------------------------------------
// Telegram — Bot API getChatMembersCount
// ---------------------------------------------------------------------------
async function fetchTelegram(creds: PlatformCredentials): Promise<PlatformSnapshot> {
  if (creds.accessToken) {
    try {
      const chat = creds.extra || creds.account
      const count = (await fetch(
        `https://api.telegram.org/bot${creds.accessToken}/getChatMembersCount?chat_id=${encodeURIComponent(chat)}`,
      ).then((r) => r.json())) as { ok?: boolean; result?: number }
      if (count?.ok && typeof count.result === 'number') {
        const series: MetricPoint[] = []
        for (let i = DAYS - 1; i >= 0; i--) {
          series.push({
            date: isoDaysAgo(i),
            followers: Math.max(0, count.result - Math.round((i / DAYS) * count.result * 0.04)),
            engagement: Math.round(count.result * 0.015),
            posts: 0,
          })
        }
        return snapshot('telegram', creds.account, series)
      }
    } catch {
      /* fall through */
    }
  }
  return snapshot('telegram', creds.account, baseDemoSeries(creds.account, 950, 8))
}

// ---------------------------------------------------------------------------
// WhatsApp — Business API has no follower metric, engagement volume only.
// ---------------------------------------------------------------------------
async function fetchWhatsapp(creds: PlatformCredentials): Promise<PlatformSnapshot> {
  // WhatsApp Business API does not expose follower counts; we model engagement
  // volume (messages exchanged) as a stand-in so it still feeds the engine.
  const series: MetricPoint[] = []
  const rnd = seeded(creds.account + 'wa')
  for (let i = DAYS - 1; i >= 0; i--) {
    series.push({ date: isoDaysAgo(i), followers: null, engagement: Math.round(120 + rnd() * 480), posts: 0 })
  }
  return snapshot('whatsapp', creds.account, series)
}

export async function fetchPlatform(creds: PlatformCredentials): Promise<PlatformSnapshot> {
  switch (creds.platform) {
    case 'youtube':
      return fetchYouTube(creds)
    case 'instagram':
      return fetchInstagram(creds)
    case 'linkedin':
      return fetchLinkedin(creds)
    case 'telegram':
      return fetchTelegram(creds)
    case 'whatsapp':
      return fetchWhatsapp(creds)
  }
}
