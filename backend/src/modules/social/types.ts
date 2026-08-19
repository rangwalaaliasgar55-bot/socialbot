/**
 * Shared data model for the social analytics engine.
 *
 * Every platform connector (YouTube, Instagram, LinkedIn, Telegram, WhatsApp)
 * returns data normalized into these shapes so the analytics engine and the
 * report generator only ever deal with one common vocabulary.
 */

export type PlatformId = 'youtube' | 'instagram' | 'linkedin' | 'telegram' | 'whatsapp'

export interface PlatformMeta {
  id: PlatformId
  label: string
  /** Whether this platform exposes organic follower/growth metrics. */
  supportsGrowth: boolean
  /** Short note shown in the UI about data access. */
  note: string
}

export const PLATFORMS: PlatformMeta[] = [
  { id: 'youtube', label: 'YouTube', supportsGrowth: true, note: 'YouTube Data API v3 (API key)' },
  { id: 'instagram', label: 'Instagram', supportsGrowth: true, note: 'Meta Graph API (Page access token)' },
  { id: 'linkedin', label: 'LinkedIn', supportsGrowth: true, note: 'LinkedIn API (access token)' },
  { id: 'telegram', label: 'Telegram', supportsGrowth: true, note: 'Bot token / channel stats' },
  { id: 'whatsapp', label: 'WhatsApp', supportsGrowth: false, note: 'Business API — engagement volume only' },
]

/**
 * A single time-series point: followers count + engagement on a given day.
 * For WhatsApp (no follower metric) followers may be null.
 */
export interface MetricPoint {
  date: string // ISO date (YYYY-MM-DD)
  followers: number | null
  engagement: number // likes + comments + shares + views (platform dependent)
  posts: number
}

/**
 * Fully normalized snapshot for one platform.
 */
export interface PlatformSnapshot {
  platform: PlatformId
  accountName: string
  fetchedAt: string
  series: MetricPoint[]
  totals: {
    followers: number | null
    followersGained: number // over the series window
    avgEngagement: number
    avgEngagementRate: number // engagement / followers (0 if no followers)
    posts: number
    bestDay: string | null
  }
}

/** Raw credentials the user supplies for a platform. */
export interface PlatformCredentials {
  platform: PlatformId
  /** Free-text identifier the user chooses (e.g. channel handle). */
  account: string
  apiKey?: string
  accessToken?: string
  /** Extra, platform-specific (e.g. channelId, pageId, chatId). */
  extra?: string
}

export interface ConnectorResult {
  snapshot: PlatformSnapshot
}
