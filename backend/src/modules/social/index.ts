import { Router, type Request, type Response } from 'express'
import { z } from 'zod'
import { PLATFORMS, type PlatformCredentials, type PlatformId } from './types'
import { fetchPlatform } from './connectors'
import { buildReport, diagnose } from './analytics'
import { getCreds, getDefaultCreds, listCreds, putCreds } from './store'

export const socialRouter: Router = Router()

const credsSchema = z.object({
  platform: z.enum(['youtube', 'instagram', 'linkedin', 'telegram', 'whatsapp']),
  account: z.string().min(1),
  apiKey: z.string().optional(),
  accessToken: z.string().optional(),
  extra: z.string().optional(),
})

/**
 * List supported platforms and which ones have credentials configured.
 */
socialRouter.get('/social/platforms', async (_req: Request, res: Response) => {
  const configured = new Set(listCreds().map((c) => c.platform))
  res.json({
    platforms: PLATFORMS.map((p) => ({ ...p, configured: configured.has(p.id) })),
  })
})

/**
 * Save credentials for a platform (in-memory for this session).
 */
socialRouter.post('/social/connections', async (req: Request, res: Response) => {
  const parsed = credsSchema.parse(req.body)
  putCreds(parsed)
  res.json({ ok: true, platform: parsed.platform })
})

/**
 * Fetch a fresh snapshot for one platform and run weak-spot diagnosis.
 */
socialRouter.get('/social/snapshot/:platform', async (req: Request, res: Response) => {
  const platform = req.params.platform as PlatformId
  const queryCreds: PlatformCredentials | null = req.query.account
    ? {
        platform,
        account: String(req.query.account),
        apiKey: req.query.apiKey ? String(req.query.apiKey) : undefined,
        accessToken: req.query.accessToken ? String(req.query.accessToken) : undefined,
        extra: req.query.extra ? String(req.query.extra) : undefined,
      }
    : null

  const creds: PlatformCredentials =
    queryCreds || getCreds(platform) || getDefaultCreds(platform) || ({ platform, account: platform } as PlatformCredentials)

  const snapshot = await fetchPlatform(creds)
  res.json({ snapshot, diagnosis: diagnose(snapshot) })
})

/**
 * Pull every configured (or default-demo) platform, run the full analytics
 * engine and return the auto-generated cross-platform report.
 */
socialRouter.get('/social/report', async (_req: Request, res: Response) => {
  const configured = listCreds()
  const ids = new Set(configured.map((c) => c.platform))
  const all: PlatformCredentials[] = [
    ...configured,
    ...(['youtube', 'instagram', 'linkedin', 'telegram', 'whatsapp'] as PlatformId[])
      .filter((id) => !ids.has(id))
      .map((id) => getDefaultCreds(id) || ({ platform: id, account: id } as PlatformCredentials)),
  ]

  const snapshots = await Promise.all(all.map((c) => fetchPlatform(c)))
  const report = buildReport(snapshots)
  res.json({ report, snapshots })
})
