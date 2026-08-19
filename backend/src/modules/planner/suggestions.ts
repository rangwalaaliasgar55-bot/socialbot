import type { PlatformId, PlatformSnapshot } from '../social/types'
import type { PlatformCredentials } from '../social/types'
import { fetchPlatform } from '../social/connectors'
import { getDefaultCreds, getCreds } from '../social/store'

/**
 * Turns analytics into action: recommends the best day/time to post and drafts
 * copy from offline templates. No external API required.
 */

const BEST_HOUR: Record<PlatformId, number> = {
  youtube: 15,
  instagram: 12,
  linkedin: 9,
  telegram: 18,
  whatsapp: 11,
}

const BEST_DAY: Record<PlatformId, string> = {
  youtube: 'Saturday',
  instagram: 'Wednesday',
  linkedin: 'Tuesday',
  telegram: 'Friday',
  whatsapp: 'Monday',
}

const HOOKS = [
  'Here’s a quick win most people miss:',
  'We tested this so you don’t have to:',
  'Stop doing this — do this instead:',
  'The unpopular opinion that grew our account:',
  '3 things we learned this week:',
]

const BODY = [
  'Share one specific result and the exact step that produced it.',
  'Ask your audience a question they can answer in one line.',
  'Show the before/after — people save contrast posts.',
  'Post the behind-the-scenes; it builds trust faster than polish.',
]

const CTA = [
  'What would you add?',
  'Reply with your biggest blocker.',
  'Save this for later.',
  'Follow for the next part.',
]

export interface Suggestion {
  platform: PlatformId
  bestDay: string
  bestHour: number
  draft: string
}

function pick<T>(arr: T[], seed: number): T {
  return arr[Math.abs(seed) % arr.length]
}

/**
 * Recommend a posting time + draft for one platform, informed by its live (or
 * sample) snapshot so the draft addresses the account's weakest area.
 */
export async function suggestForPlatform(platform: PlatformId): Promise<Suggestion> {
  const creds: PlatformCredentials =
    getCreds(platform) || getDefaultCreds(platform) || ({ platform, account: platform } as PlatformCredentials)
  const snapshot: PlatformSnapshot = await fetchPlatform(creds)

  // Bias the hook toward the weakest finding so the copy attacks the gap.
  const rate = snapshot.totals.avgEngagementRate
  const seed = Math.round(snapshot.totals.followersGained + rate * 7)
  const hook = rate < 1 ? HOOKS[0] : rate < 2.5 ? HOOKS[1] : pick(HOOKS, seed)
  const body = pick(BODY, seed + 3)
  const cta = pick(CTA, seed + 5)

  const draft = `${hook}\n\n${body}\n\n${cta}`

  return {
    platform,
    bestDay: BEST_DAY[platform],
    bestHour: BEST_HOUR[platform],
    draft,
  }
}

export async function suggestAll(platforms: PlatformId[]): Promise<Suggestion[]> {
  return Promise.all(platforms.map(suggestForPlatform))
}
