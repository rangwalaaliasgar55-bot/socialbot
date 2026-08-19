import type { PlatformId } from '../social/types'

export type Recurrence = 'none' | 'daily' | 'weekly'

export interface PostDraft {
  id: string
  platform: PlatformId
  account: string
  text: string
  media?: string
  /** ISO datetime the post is scheduled for. */
  scheduledFor: string
  recurrence: Recurrence
  /** Last time the scheduler "published" (logged) this draft. */
  lastRunAt?: string
  status: 'scheduled' | 'done' | 'cancelled'
  createdAt: string
  /** Outcome of the last publish attempt. */
  lastResult?: string
  /** Whether the last publish went to the live API. */
  live?: boolean
  /** Media URL/reference attached to the post (e.g. generated image). */
  mediaUrl?: string
}

export interface ActivityEntry {
  id: string
  at: string
  kind: 'publish' | 'suggestion' | 'system'
  platform: PlatformId | 'all'
  message: string
}
