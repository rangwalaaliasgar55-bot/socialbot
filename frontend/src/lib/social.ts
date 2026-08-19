import { apiClient } from './api-client'

export type PlatformId = 'youtube' | 'instagram' | 'linkedin' | 'telegram' | 'whatsapp'

export interface PlatformMeta {
  id: PlatformId
  label: string
  supportsGrowth: boolean
  note: string
  configured: boolean
}

export interface MetricPoint {
  date: string
  followers: number | null
  engagement: number
  posts: number
}

export interface PlatformSnapshot {
  platform: PlatformId
  accountName: string
  fetchedAt: string
  series: MetricPoint[]
  totals: {
    followers: number | null
    followersGained: number
    avgEngagement: number
    avgEngagementRate: number
    posts: number
    bestDay: string | null
  }
}

export type Severity = 'good' | 'watch' | 'weak'

export interface Finding {
  severity: Severity
  title: string
  detail: string
  suggestion: string
}

export interface Diagnosis {
  platform: PlatformId
  account: string
  score: number
  findings: Finding[]
}

export interface GrowthTrend {
  platform: PlatformId
  account: string
  followers: number | null
  gained: number
  dailyAvg: number
  trend: 'up' | 'down' | 'flat'
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
  actionPlan: ReportBlock[]
  summary: string
}

export interface PlatformCredentials {
  platform: PlatformId
  account: string
  apiKey?: string
  accessToken?: string
  extra?: string
}

const PLATFORM_LABELS: Record<PlatformId, string> = {
  youtube: 'YouTube',
  instagram: 'Instagram',
  linkedin: 'LinkedIn',
  telegram: 'Telegram',
  whatsapp: "WhatsApp",
}

export const platformLabel = (id: PlatformId) => PLATFORM_LABELS[id] ?? id

export async function getPlatforms(): Promise<PlatformMeta[]> {
  const { data } = await apiClient.get('/social/platforms')
  return data.platforms
}

export async function saveConnection(creds: PlatformCredentials): Promise<void> {
  await apiClient.post('/social/connections', creds)
}

export async function getSnapshot(
  platform: PlatformId,
  creds?: Partial<PlatformCredentials>,
): Promise<{ snapshot: PlatformSnapshot; diagnosis: Diagnosis }> {
  const params = creds?.account ? new URLSearchParams() : undefined
  if (creds?.account) params!.set('account', creds.account)
  if (creds?.apiKey) params!.set('apiKey', creds.apiKey)
  if (creds?.accessToken) params!.set('accessToken', creds.accessToken)
  if (creds?.extra) params!.set('extra', creds.extra)
  const { data } = await apiClient.get(`/social/snapshot/${platform}`, { params })
  return data
}

export async function getReport(): Promise<{ report: AutoReport; snapshots: PlatformSnapshot[] }> {
  const { data } = await apiClient.get('/social/report')
  return data
}

export const PLATFORM_COLORS: Record<PlatformId, string> = {
  youtube: '#EF4444',
  instagram: '#EC4899',
  linkedin: '#3B82F6',
  telegram: '#06B6D4',
  whatsapp: '#22C55E',
}

export const PLATFORMS: { id: PlatformId; label: string }[] = [
  { id: 'youtube', label: 'YouTube' },
  { id: 'instagram', label: 'Instagram' },
  { id: 'linkedin', label: 'LinkedIn' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'whatsapp', label: 'WhatsApp' },
]

export type Recurrence = 'none' | 'daily' | 'weekly'

export interface PostDraft {
  id: string
  platform: PlatformId
  account: string
  text: string
  media?: string
  scheduledFor: string
  recurrence: Recurrence
  status: 'scheduled' | 'done' | 'cancelled'
  createdAt: string
  lastResult?: string
  live?: boolean
  mediaUrl?: string
}

export interface Suggestion {
  platform: PlatformId
  bestDay: string
  bestHour: number
  draft: string
}

export interface ActivityEntry {
  id: string
  at: string
  kind: 'publish' | 'suggestion' | 'system'
  platform: PlatformId | 'all'
  message: string
}

export async function getPosts(status?: string): Promise<PostDraft[]> {
  const { data } = await apiClient.get('/planner/posts', { params: status ? { status } : undefined })
  return data.posts
}

export async function createPost(input: Omit<PostDraft, 'id' | 'status' | 'createdAt'>): Promise<PostDraft> {
  const { data } = await apiClient.post('/planner/posts', input)
  return data.post
}

export async function cancelPost(id: string): Promise<void> {
  await apiClient.delete(`/planner/posts/${id}`)
}

export async function getSuggestions(): Promise<Suggestion[]> {
  const { data } = await apiClient.get('/planner/suggestions')
  return data.suggestions
}

export async function getActivity(): Promise<ActivityEntry[]> {
  const { data } = await apiClient.get('/planner/activity')
  return data.activity
}

export async function publishNow(id: string): Promise<void> {
  await apiClient.post(`/planner/posts/${id}/publish`)
}

// --- AI module ---
export interface AiStatus {
  enabled: boolean
  model: string
}

export async function getAiStatus(): Promise<AiStatus> {
  const { data } = await apiClient.get('/ai/status')
  return data
}

export async function aiDraft(platform: PlatformId, brief?: string): Promise<{ enabled: boolean; text: string }> {
  const { data } = await apiClient.post('/ai/draft', { platform, brief })
  return data
}

export async function aiImage(prompt: string): Promise<{ enabled: boolean; url?: string; b64?: string; note?: string; error?: string }> {
  const { data } = await apiClient.post('/ai/image', { prompt })
  return data
}

export async function aiChat(message: string, context?: string): Promise<{ enabled: boolean; reply: string }> {
  const { data } = await apiClient.post('/ai/chat', { message, context })
  return data
}
