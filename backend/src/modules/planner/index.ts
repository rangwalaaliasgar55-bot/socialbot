import { Router, type Request, type Response } from 'express'
import { z } from 'zod'
import type { PlatformId } from '../social/types'
import { PLATFORMS } from '../social/types'
import { addPost, cancelPost, listActivity, listPosts, logActivity, updatePost } from './store'
import { suggestAll } from './suggestions'
import { publish } from './publisher'

export const plannerRouter: Router = Router()

const draftSchema = z.object({
  platform: z.enum(['youtube', 'instagram', 'linkedin', 'telegram', 'whatsapp']),
  account: z.string().min(1),
  text: z.string().min(1),
  media: z.string().optional(),
  scheduledFor: z.string().min(1),
  recurrence: z.enum(['none', 'daily', 'weekly']).default('none'),
})

/**
 * List scheduled posts (optionally filter by status).
 */
plannerRouter.get('/planner/posts', async (req: Request, res: Response) => {
  const status = typeof req.query.status === 'string' ? req.query.status : undefined
  const posts = listPosts().filter((p) => (status ? p.status === status : true))
  res.json({ posts })
})

/**
 * Create a scheduled post.
 */
plannerRouter.post('/planner/posts', async (req: Request, res: Response) => {
  const parsed = draftSchema.parse(req.body)
  const draft = addPost(parsed)
  logActivity({ kind: 'system', platform: parsed.platform, message: `Scheduled post for ${parsed.account}` })
  res.json({ ok: true, post: draft })
})

/**
 * Publish a post immediately (bypass the scheduler).
 */
plannerRouter.post('/planner/posts/:id/publish', async (req: Request, res: Response) => {
  const post = listPosts().find((p) => p.id === String(req.params.id))
  if (!post) {
    res.status(404).json({ ok: false, error: 'Not found' })
    return
  }
  const result = await publish(post)
  logActivity({ kind: 'publish', platform: post.platform, message: `Manual publish → ${post.account}: ${result.detail}` })
  updatePost(post.id, {
    status: result.ok ? 'done' : 'scheduled',
    lastRunAt: new Date().toISOString(),
    lastResult: result.detail,
    live: result.live,
    mediaUrl: result.mediaUrl,
  })
  res.json({ ok: result.ok, result })
})

/**
 * Cancel a scheduled post.
 */
plannerRouter.delete('/planner/posts/:id', async (req: Request, res: Response) => {
  const ok = cancelPost(String(req.params.id))
  res.json({ ok })
})

/**
 * Actionable suggestions: best time + drafted copy per platform.
 */
plannerRouter.get('/planner/suggestions', async (_req: Request, res: Response) => {
  const ids = PLATFORMS.map((p) => p.id) as PlatformId[]
  const suggestions = await suggestAll(ids)
  res.json({ suggestions })
})

/**
 * Activity log (publish events, suggestions, system).
 */
plannerRouter.get('/planner/activity', async (_req: Request, res: Response) => {
  res.json({ activity: listActivity() })
})

// ---------------------------------------------------------------------------
// Lightweight in-process scheduler: every 60s it "publishes" (logs) any post
// whose scheduled time has passed and reschedules recurrences. This keeps the
// app self-contained without external queue infrastructure.
// ---------------------------------------------------------------------------
let timer: NodeJS.Timeout | null = null

function nextRun(recurrence: 'none' | 'daily' | 'weekly', from: Date): Date {
  if (recurrence === 'daily') from.setDate(from.getDate() + 1)
  else if (recurrence === 'weekly') from.setDate(from.getDate() + 7)
  return from
}

export function startScheduler(): void {
  if (timer) return
  timer = setInterval(() => {
    const now = Date.now()
    for (const p of listPosts()) {
      if (p.status !== 'scheduled') continue
      if (new Date(p.scheduledFor).getTime() <= now) {
        void (async () => {
          const result = await publish(p)
          logActivity({
            kind: 'publish',
            platform: p.platform,
            message: `${result.live ? 'Live' : 'Logged'} → ${p.account}: ${p.text.slice(0, 60)}${
              p.text.length > 60 ? '…' : ''
            } (${result.detail})`,
          })
          if (p.recurrence === 'none') {
            updatePost(p.id, {
              status: result.ok ? 'done' : 'scheduled',
              lastRunAt: new Date().toISOString(),
              lastResult: result.detail,
              live: result.live,
              mediaUrl: result.mediaUrl,
            })
          } else {
            updatePost(p.id, {
              lastRunAt: new Date().toISOString(),
              lastResult: result.detail,
              live: result.live,
              mediaUrl: result.mediaUrl,
              scheduledFor: nextRun(p.recurrence, new Date(p.scheduledFor)).toISOString(),
            })
          }
        })()
      }
    }
  }, 30_000)
}

export function stopScheduler(): void {
  if (timer) clearInterval(timer)
  timer = null
}
