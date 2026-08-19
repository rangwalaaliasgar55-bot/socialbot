import type { PlatformId, PlatformSnapshot } from './types'

export type Severity = 'good' | 'watch' | 'weak'

export interface Diagnosis {
  platform: PlatformId
  account: string
  /** Overall health score 0-100. */
  score: number
  findings: Finding[]
}

export interface Finding {
  severity: Severity
  title: string
  detail: string
  /** Concrete improvement suggestion. */
  suggestion: string
}

export interface GrowthTrend {
  platform: PlatformId
  account: string
  followers: number | null
  gained: number
  /** Daily average growth (can be negative). */
  dailyAvg: number
  trend: 'up' | 'down' | 'flat'
}

function growthTrend(s: PlatformSnapshot): GrowthTrend {
  const gained = s.totals.followersGained
  const dailyAvg = Number((gained / s.series.length).toFixed(1))
  const trend: GrowthTrend['trend'] = gained > s.series.length ? 'up' : gained < -s.series.length ? 'down' : 'flat'
  return { platform: s.platform, account: s.accountName, followers: s.totals.followers, gained, dailyAvg, trend }
}

/**
 * Analyze one platform snapshot and produce weak-spot findings + a health score.
 */
export function diagnose(s: PlatformSnapshot): Diagnosis {
  const findings: Finding[] = []
  let score = 100

  const t = s.totals

  // 1. Engagement rate check
  if (t.avgEngagementRate < 1) {
    score -= 25
    findings.push({
      severity: 'weak',
      title: 'Engagement rate is low',
      detail: `Average engagement rate is ${t.avgEngagementRate}% — content isn't resonating with the audience.`,
      suggestion: 'Post more native, conversation-starting content (questions, polls) and use 1-2 hashtags that fit your niche.',
    })
  } else if (t.avgEngagementRate < 2.5) {
    score -= 10
    findings.push({
      severity: 'watch',
      title: 'Engagement rate is below average',
      detail: `Engagement rate sits at ${t.avgEngagementRate}%. Healthy accounts usually clear 2.5%.`,
      suggestion: 'Improve hooks in the first line and reply to the first 10 comments within an hour of posting.',
    })
  } else {
    findings.push({
      severity: 'good',
      title: 'Engagement looks healthy',
      detail: `Engagement rate is ${t.avgEngagementRate}%, above the 2.5% benchmark.`,
      suggestion: 'Keep the current content mix and double down on your top-performing formats.',
    })
  }

  // 2. Growth trend check (skip for WhatsApp which has no follower metric)
  if (s.platform !== 'whatsapp' && t.followers != null) {
    if (t.followersGained < 0) {
      score -= 25
      findings.push({
        severity: 'weak',
        title: 'Followers are declining',
        detail: `You lost ${Math.abs(t.followersGained)} followers over the window.`,
        suggestion: 'Audit recent posts for off-brand or overly promotional content; re-engage with a value-first series.',
      })
    } else if (t.followersGained < s.series.length * 2) {
      score -= 12
      findings.push({
        severity: 'watch',
        title: 'Growth is slow',
        detail: `Gained only ${t.followersGained} followers — below a healthy daily pace.`,
        suggestion: 'Increase posting frequency by 30% and cross-promote on your strongest platform.',
      })
    } else {
      findings.push({
        severity: 'good',
        title: 'Steady follower growth',
        detail: `Gained ${t.followersGained} followers in the window.`,
        suggestion: 'Sustain cadence and test one new content pillar per week to find the next growth lever.',
      })
    }
  }

  // 3. Posting consistency check
  if (t.posts === 0) {
    score -= 15
    findings.push({
      severity: 'weak',
      title: 'No posts in the window',
      detail: 'The account shows zero posts in the last 30 days.',
      suggestion: 'Commit to at least 3 posts per week; consistency matters more than volume for the algorithm.',
    })
  } else if (t.posts < 8) {
    score -= 8
    findings.push({
      severity: 'watch',
      title: 'Posting is infrequent',
      detail: `Only ${t.posts} posts in 30 days.`,
      suggestion: 'Aim for 2-3 posts weekly to stay in your followers’ feeds.',
    })
  }

  score = Math.max(0, Math.min(100, score))
  return { platform: s.platform, account: s.accountName, score, findings }
}

export interface ReportBlock {
  heading: string
  body: string
}

export interface AutoReport {
  generatedAt: string
  periodDays: number
  platformCount: number
  overallScore: number
  trends: GrowthTrend[]
  diagnoses: Diagnosis[]
  /** Prioritized, cross-platform action list. */
  actionPlan: ReportBlock[]
  summary: string
}

/**
 * Build the cross-platform auto-report with prioritized improvement actions.
 */
export function buildReport(snapshots: PlatformSnapshot[]): AutoReport {
  const diagnoses = snapshots.map(diagnose)
  const trends = snapshots.map(growthTrend)
  const overallScore = Math.round(diagnoses.reduce((s, d) => s + d.score, 0) / (diagnoses.length || 1))

  const weak = diagnoses.flatMap((d) => d.findings.filter((f) => f.severity === 'weak'))
  const watch = diagnoses.flatMap((d) => d.findings.filter((f) => f.severity === 'watch'))

  const actionPlan: ReportBlock[] = []
  weak.slice(0, 5).forEach((f, i) =>
    actionPlan.push({ heading: `Priority ${i + 1}: ${f.title}`, body: `${f.detail} → ${f.suggestion}` }),
  )
  watch.slice(0, 3).forEach((f) =>
    actionPlan.push({ heading: `Then: ${f.title}`, body: `${f.detail} → ${f.suggestion}` }),
  )
  if (actionPlan.length === 0) {
    actionPlan.push({
      heading: 'Maintain momentum',
      body: 'All platforms are healthy. Run a small experiment each week to keep compounding growth.',
    })
  }

  const declining = trends.filter((t) => t.trend === 'down')
  const summary =
    `Across ${snapshots.length} platform(s), overall health scores ${overallScore}/100. ` +
    (declining.length
      ? `${declining.map((d) => d.platform).join(', ')} ${declining.length > 1 ? 'are' : 'is'} losing followers. `
      : 'No platform is losing followers. ') +
    `Top priority: ${actionPlan[0]?.heading ?? 'keep consistency'}.`

  return {
    generatedAt: new Date().toISOString(),
    periodDays: snapshots[0]?.series.length ?? 0,
    platformCount: snapshots.length,
    overallScore,
    trends,
    diagnoses,
    actionPlan,
    summary,
  }
}
