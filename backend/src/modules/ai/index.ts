import { Router, type Request, type Response } from 'express'
import { z } from 'zod'
import { env } from '../../config/env'
import type { PlatformId } from '../social/types'

/**
 * AI module — OpenAI-compatible text + image generation.
 *
 * Text (draft + chat) uses Groq by default (OPENAI-compatible), falling back to
 * OPENAI_API_KEY if no Groq key is present. Image generation uses OpenAI only,
 * because Groq does not offer an image API.
 *
 * Without any key, sensible offline fallbacks keep the whole product usable.
 */

export const aiRouter: Router = Router()

interface TextProvider {
  key?: string
  baseUrl: string
  model: string
}

function textProvider(): TextProvider {
  if (env.GROQ_API_KEY) return { key: env.GROQ_API_KEY, baseUrl: env.GROQ_BASE_URL, model: env.GROQ_MODEL }
  if (env.OPENAI_API_KEY) return { key: env.OPENAI_API_KEY, baseUrl: env.OPENAI_BASE_URL, model: env.OPENAI_MODEL }
  return { baseUrl: env.GROQ_BASE_URL, model: env.GROQ_MODEL }
}

export function aiEnabled(): boolean {
  return !!(env.GROQ_API_KEY || env.OPENAI_API_KEY)
}

export function imageEnabled(): boolean {
  return !!env.OPENAI_API_KEY
}

async function chatCompletion(system: string, user: string): Promise<string> {
  const p = textProvider()
  if (!p.key) return ''
  const r = await fetch(`${p.baseUrl}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${p.key}` },
    body: JSON.stringify({
      model: p.model,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user },
      ],
    }),
  })
  if (!r.ok) throw new Error(`AI request failed: ${r.status}`)
  const data = (await r.json()) as { choices?: Array<{ message: { content: string } }> }
  return data.choices?.[0]?.message?.content ?? ''
}

// ---------------------------------------------------------------------------
// Draft post copy for a platform, optionally from a brief.
// ---------------------------------------------------------------------------
const draftSchema = z.object({
  platform: z.enum(['youtube', 'instagram', 'linkedin', 'telegram', 'whatsapp']),
  brief: z.string().optional(),
})

aiRouter.post('/ai/draft', async (req: Request, res: Response) => {
  const { platform, brief } = draftSchema.parse(req.body)
  if (!aiEnabled()) {
    res.json({ enabled: false, text: fallbackDraft(platform, brief) })
    return
  }
  const system =
    `You are a social media copywriter. Write ONE engaging post for ${platform}. ` +
    `Use a strong hook, 1-2 short paragraphs, and a clear call to action. Keep it platform-appropriate and under 280 characters when possible. Return plain text only.`
  const text = await chatCompletion(system, brief || `Topic: something our audience cares about.`)
  res.json({ enabled: true, provider: textProvider().key ? 'groq' : 'openai', text })
})

// ---------------------------------------------------------------------------
// Generate an image (OpenAI only) from a prompt.
// ---------------------------------------------------------------------------
const imageSchema = z.object({ prompt: z.string().min(3) })

aiRouter.post('/ai/image', async (req: Request, res: Response) => {
  const { prompt } = imageSchema.parse(req.body)
  if (!imageEnabled()) {
    res.json({ enabled: false, note: 'Add OPENAI_API_KEY to generate real images (Groq has no image API).', prompt })
    return
  }
  const r = await fetch(`${env.OPENAI_BASE_URL}/images/generations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${env.OPENAI_API_KEY}` },
    body: JSON.stringify({ model: env.OPENAI_IMAGE_MODEL, prompt, n: 1, size: '1024x1024' }),
  })
  if (!r.ok) {
    res.status(502).json({ enabled: true, error: `Image generation failed: ${r.status}` })
    return
  }
  const data = (await r.json()) as { data?: Array<{ url?: string; b64_json?: string }> }
  const item = data.data?.[0]
  res.json({ enabled: true, url: item?.url, b64: item?.b64_json })
})

// ---------------------------------------------------------------------------
// Audience chat — answers questions using the provided analytics context.
// ---------------------------------------------------------------------------
const chatSchema = z.object({
  message: z.string().min(1),
  context: z.string().optional(),
})

aiRouter.post('/ai/chat', async (req: Request, res: Response) => {
  const { message, context } = chatSchema.parse(req.body)
  if (!aiEnabled()) {
    res.json({
      enabled: false,
      reply:
        'AI chat is in offline mode. Add a GROQ_API_KEY (or OPENAI_API_KEY) to get data-aware answers. ' +
        'Meanwhile: post 2-3x weekly, reply to early comments, and double down on your best-performing format.',
    })
    return
  }
  const system =
    'You are a friendly social-media growth coach for a creator/brand. ' +
    'Use the provided analytics context when relevant. Give short, actionable advice. ' +
    (context ? `Analytics context:\n${context}` : '')
  const reply = await chatCompletion(system, message)
  res.json({ enabled: true, provider: textProvider().key ? 'groq' : 'openai', reply })
})

aiRouter.get('/ai/status', async (_req: Request, res: Response) => {
  res.json({
    enabled: aiEnabled(),
    provider: env.GROQ_API_KEY ? 'groq' : env.OPENAI_API_KEY ? 'openai' : 'offline',
    model: textProvider().model,
    imageEnabled: imageEnabled(),
  })
})

function fallbackDraft(platform: PlatformId, brief?: string): string {
  const topic = brief ? ` about ${brief}` : ''
  const map: Record<PlatformId, string> = {
    youtube: `New video idea${topic}: show the exact step that got us results, then ask viewers to subscribe.`,
    instagram: `Quick tip${topic}: save this post and tell us which part you'll try first.`,
    linkedin: `We learned something${topic} — here's the one takeaway worth your time. What would you add?`,
    telegram: `Update${topic}: one useful insight for the channel today. Reply with your questions.`,
    whatsapp: `Hi! Here's something useful${topic}. Reply to tell us what you think.`,
  }
  return map[platform]
}
