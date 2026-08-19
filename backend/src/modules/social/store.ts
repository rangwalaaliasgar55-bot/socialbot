import type { PlatformCredentials, PlatformId } from './types'

/**
 * In-memory credential + snapshot cache.
 *
 * Credentials are passed per-request by the frontend (the user pastes them into
 * the Connections screen). We also read optional defaults from environment
 * variables so a deploy can be pre-wired without re-entering keys.
 *
 * Nothing sensitive is logged. This is intentionally simple — it can be swapped
 * for an encrypted store later without changing the connector/analytics code.
 */

interface CacheEntry {
  creds: PlatformCredentials
  snapshotAt: number
}

const cache = new Map<PlatformId, CacheEntry>()

function envCreds(platform: PlatformId): PlatformCredentials | null {
  const key = process.env[`${platform.toUpperCase()}_API_KEY`]
  const token = process.env[`${platform.toUpperCase()}_ACCESS_TOKEN`]
  const extra = process.env[`${platform.toUpperCase()}_EXTRA`]
  const account = process.env[`${platform.toUpperCase()}_ACCOUNT`]
  if (!key && !token) return null
  return { platform, account: account || platform, apiKey: key, accessToken: token, extra }
}

export function getDefaultCreds(platform: PlatformId): PlatformCredentials | null {
  return envCreds(platform)
}

export function putCreds(creds: PlatformCredentials): void {
  cache.set(creds.platform, { creds, snapshotAt: Date.now() })
}

export function getCreds(platform: PlatformId): PlatformCredentials | null {
  return cache.get(platform)?.creds ?? envCreds(platform)
}

export function listCreds(): PlatformCredentials[] {
  const fromCache = [...cache.values()].map((c) => c.creds)
  const ids = new Set(fromCache.map((c) => c.platform))
  const fromEnv = (['youtube', 'instagram', 'linkedin', 'telegram', 'whatsapp'] as PlatformId[])
    .map(envCreds)
    .filter((c): c is PlatformCredentials => !!c && !ids.has(c.platform))
  return [...fromCache, ...fromEnv]
}
