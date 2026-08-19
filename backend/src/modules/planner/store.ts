import { randomUUID } from 'crypto'
import type { ActivityEntry, PostDraft, Recurrence } from './types'
import type { PlatformId } from '../social/types'

/**
 * Planner persistence.
 *
 * Posts and the activity log are kept in a JSON file under the backend so they
 * survive restarts without needing a database. This is intentionally simple and
 * dependency-free; it can be swapped for a real store later.
 */

const DATA_DIR = process.env.DATA_DIR || '/workspace/backend/.data'
const POSTS_FILE = `${DATA_DIR}/posts.json`
const ACTIVITY_FILE = `${DATA_DIR}/activity.json`

import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'fs'

function ensure() {
  if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true })
}

function read<T>(file: string, fallback: T): T {
  ensure()
  if (!existsSync(file)) return fallback
  try {
    return JSON.parse(readFileSync(file, 'utf8')) as T
  } catch {
    return fallback
  }
}

function write<T>(file: string, value: T) {
  ensure()
  writeFileSync(file, JSON.stringify(value, null, 2))
}

export function listPosts(): PostDraft[] {
  return read<PostDraft[]>(POSTS_FILE, [])
}

export function addPost(input: {
  platform: PlatformId
  account: string
  text: string
  media?: string
  scheduledFor: string
  recurrence: Recurrence
}): PostDraft {
  const posts = listPosts()
  const draft: PostDraft = {
    id: randomUUID(),
    ...input,
    status: 'scheduled',
    createdAt: new Date().toISOString(),
  }
  posts.push(draft)
  write(POSTS_FILE, posts)
  return draft
}

export function updatePost(id: string, patch: Partial<PostDraft>): PostDraft | null {
  const posts = listPosts()
  const idx = posts.findIndex((p) => p.id === id)
  if (idx === -1) return null
  posts[idx] = { ...posts[idx], ...patch }
  write(POSTS_FILE, posts)
  return posts[idx]
}

export function cancelPost(id: string): boolean {
  return !!updatePost(id, { status: 'cancelled' })
}

export function listActivity(): ActivityEntry[] {
  return read<ActivityEntry[]>(ACTIVITY_FILE, [])
}

export function logActivity(entry: Omit<ActivityEntry, 'id' | 'at'>): ActivityEntry {
  const all = listActivity()
  const e: ActivityEntry = { id: randomUUID(), at: new Date().toISOString(), ...entry }
  all.unshift(e)
  write(ACTIVITY_FILE, all.slice(0, 200))
  return e
}
