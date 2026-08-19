import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Image as ImageIcon, Lightbulb, Send, Sparkles, Trash2, Upload } from 'lucide-react'
import {
  aiDraft,
  aiImage,
  cancelPost,
  createPost,
  getActivity,
  getAiStatus,
  getPosts,
  getSuggestions,
  platformLabel,
  PLATFORM_COLORS,
  PLATFORMS,
  publishNow,
  type PlatformId,
  type Recurrence,
  type Suggestion,
} from '@/lib/social'

export default function Planner() {
  const qc = useQueryClient()
  const { data: posts } = useQuery({ queryKey: ['posts'], queryFn: () => getPosts() })
  const { data: suggestions } = useQuery({ queryKey: ['suggestions'], queryFn: getSuggestions })
  const { data: activity } = useQuery({ queryKey: ['activity'], queryFn: getActivity })
  const { data: aiStatus } = useQuery({ queryKey: ['aiStatus'], queryFn: getAiStatus })

  const [platform, setPlatform] = useState<PlatformId>('instagram')
  const [account, setAccount] = useState('@mybrand')
  const [text, setText] = useState('')
  const [when, setWhen] = useState(() => new Date(Date.now() + 3600_000).toISOString().slice(0, 16))
  const [recurrence, setRecurrence] = useState<Recurrence>('none')
  const [brief, setBrief] = useState('')

  // Image generator state
  const [imgPrompt, setImgPrompt] = useState('')
  const [imgSrc, setImgSrc] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: createPost,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['posts'] }),
  })
  const remove = useMutation({
    mutationFn: cancelPost,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['posts'] }),
  })
  const publish = useMutation({
    mutationFn: publishNow,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['posts'] }),
  })
  const genDraft = useMutation({
    mutationFn: () => aiDraft(platform, brief || undefined),
    onSuccess: (d) => setText(d.text),
  })
  const genImage = useMutation({
    mutationFn: () => aiImage(imgPrompt || text),
    onSuccess: (d) => {
      if (d.url) setImgSrc(d.url)
      else if (d.b64) setImgSrc(`data:image/png;base64,${d.b64}`)
      else setImgSrc(null)
    },
  })

  const applySuggestion = (s: Suggestion) => {
    setPlatform(s.platform)
    setText(s.draft)
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">Content Planner</h1>
        <p className="text-sm text-muted-foreground">
          Draft with AI, generate images, schedule, and publish — turning insights into real posts.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Composer */}
        <section className="rounded-xl border border-border bg-card p-5">
          <div className="mb-3 flex items-center gap-2 font-medium">
            <CalendarClock className="h-4 w-4" /> New scheduled post
          </div>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-xs text-muted-foreground">Platform</span>
                <select
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                  value={platform}
                  onChange={(e) => setPlatform(e.target.value as PlatformId)}
                >
                  {PLATFORMS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-muted-foreground">Account</span>
                <input
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                  value={account}
                  onChange={(e) => setAccount(e.target.value)}
                />
              </label>
            </div>

            <label className="block">
              <span className="mb-1 block text-xs text-muted-foreground">Brief (optional — AI uses this)</span>
              <input
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
                placeholder="e.g. a tip about saving money"
              />
            </label>

            <div className="flex gap-2">
              <button
                onClick={() => genDraft.mutate()}
                disabled={genDraft.isPending}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-sm hover:bg-accent disabled:opacity-50"
              >
                <Sparkles className="h-4 w-4" /> {aiStatus?.enabled ? 'AI draft' : 'Draft (offline)'}
              </button>
              <button
                onClick={() => genImage.mutate()}
                disabled={genImage.isPending}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-sm hover:bg-accent disabled:opacity-50"
              >
                <ImageIcon className="h-4 w-4" /> {aiStatus?.enabled ? 'Generate image' : 'Image (offline)'}
              </button>
            </div>

            <label className="block">
              <span className="mb-1 block text-xs text-muted-foreground">Image prompt (optional)</span>
              <input
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                value={imgPrompt}
                onChange={(e) => setImgPrompt(e.target.value)}
                placeholder="Leave blank to use post text as prompt"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs text-muted-foreground">Post text</span>
              <textarea
                rows={4}
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="What do you want to say?"
              />
            </label>

            {imgSrc && (
              <div className="overflow-hidden rounded-lg border border-border">
                <img src={imgSrc} alt="generated" className="h-40 w-full object-cover" />
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-xs text-muted-foreground">Schedule for</span>
                <input
                  type="datetime-local"
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                  value={when}
                  onChange={(e) => setWhen(e.target.value)}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-muted-foreground">Recurrence</span>
                <select
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                  value={recurrence}
                  onChange={(e) => setRecurrence(e.target.value as Recurrence)}
                >
                  <option value="none">One-time</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
              </label>
            </div>
            <button
              disabled={create.isPending || !text}
              onClick={() =>
                create.mutate({
                  platform,
                  account,
                  text,
                  media: imgSrc ?? undefined,
                  scheduledFor: new Date(when).toISOString(),
                  recurrence,
                })
              }
              className="w-full rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              Schedule post
            </button>
          </div>
        </section>

        {/* Suggestions */}
        <section className="rounded-xl border border-border bg-card p-5">
          <div className="mb-3 flex items-center gap-2 font-medium">
            <Lightbulb className="h-4 w-4" /> Best-time & copy suggestions
          </div>
          <div className="space-y-2">
            {suggestions?.map((s) => (
              <div key={s.platform} className="rounded-lg border border-border p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: PLATFORM_COLORS[s.platform] }} />
                    {platformLabel(s.platform)}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {s.bestDay} · {String(s.bestHour).padStart(2, '0')}:00
                  </span>
                </div>
                <p className="mt-1 whitespace-pre-line text-xs text-muted-foreground">{s.draft}</p>
                <button
                  onClick={() => applySuggestion(s)}
                  className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <Sparkles className="h-3 w-3" /> Use this draft
                </button>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* Queue */}
      <section>
        <h2 className="mb-2 text-lg font-semibold">Scheduled queue</h2>
        <div className="overflow-hidden rounded-xl border border-border">
          {posts && posts.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Platform</th>
                  <th className="px-3 py-2">Account</th>
                  <th className="px-3 py-2">Text</th>
                  <th className="px-3 py-2">When</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {posts.map((p) => (
                  <tr key={p.id} className="border-t border-border align-top">
                    <td className="px-3 py-2">{platformLabel(p.platform)}</td>
                    <td className="px-3 py-2 text-muted-foreground">{p.account}</td>
                    <td className="max-w-xs px-3 py-2">
                      <div className="truncate">{p.text}</div>
                      {p.mediaUrl && <span className="text-xs text-info">🖼 attached</span>}
                      {p.lastResult && (
                        <div className="text-xs text-muted-foreground/70">{p.live ? 'live' : 'logged'}: {p.lastResult}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{new Date(p.scheduledFor).toLocaleString()}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${
                          p.status === 'scheduled'
                            ? 'bg-info/15 text-info'
                            : p.status === 'done'
                              ? 'bg-success/15 text-success'
                              : 'bg-muted text-muted-foreground'
                        }`}
                      >
                        {p.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex justify-end gap-2">
                        {p.status === 'scheduled' && (
                          <button
                            onClick={() => publish.mutate(p.id)}
                            title="Publish now"
                            className="text-muted-foreground hover:text-primary"
                          >
                            <Upload className="h-4 w-4" />
                          </button>
                        )}
                        {p.status === 'scheduled' && (
                          <button onClick={() => remove.mutate(p.id)} className="text-muted-foreground hover:text-destructive">
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="p-4 text-sm text-muted-foreground">No posts scheduled yet.</p>
          )}
        </div>
        {posts?.some((p) => p.status === 'scheduled') && (
          <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
            <Send className="h-3 w-3" /> Due posts also publish automatically every 30s (live if credentials are set).
          </p>
        )}
      </section>

      {/* Activity */}
      <section>
        <h2 className="mb-2 text-lg font-semibold">Activity log</h2>
        <div className="space-y-1 rounded-xl border border-border p-3 text-sm">
          {activity && activity.length > 0 ? (
            activity.map((a) => (
              <div key={a.id} className="flex gap-2 text-muted-foreground">
                <span className="text-xs text-muted-foreground/70">{new Date(a.at).toLocaleTimeString()}</span>
                <span className={a.kind === 'publish' ? 'text-success' : ''}>{a.message}</span>
              </div>
            ))
          ) : (
            <p className="text-muted-foreground">Nothing yet. Scheduled posts will be published automatically when their time arrives.</p>
          )}
        </div>
      </section>
    </div>
  )
}
