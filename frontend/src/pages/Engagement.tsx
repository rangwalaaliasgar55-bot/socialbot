import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, RefreshCw, Sparkles } from 'lucide-react'
import { aiDraft, getReport, platformLabel, PLATFORM_COLORS } from '@/lib/social'

export default function Engagement() {
  const { data } = useQuery({ queryKey: ['report'], queryFn: getReport })
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  if (!data) return <div className="p-8 text-muted-foreground">Loading engagement…</div>

  const { report } = data
  const declining = report.trends.filter((t) => t.trend === 'down')
  const weakFindings = report.diagnoses.flatMap((d) =>
    d.findings.filter((f) => f.severity === 'weak').map((f) => ({ platform: d.platform, account: d.account, f })),
  )

  const draftWinBack = async (platform: string) => {
    setBusy(true)
    try {
      const res = await aiDraft(platform as never, `re-engage a declining audience on ${platform}`)
      setDraft(res.text)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">Engagement & win-back</h1>
        <p className="text-sm text-muted-foreground">Spot the platforms losing momentum and fire a re-engagement post.</p>
      </div>

      {declining.length === 0 && weakFindings.length === 0 ? (
        <div className="rounded-xl border border-success/30 bg-success/5 p-4 text-sm">
          All platforms are healthy — no win-back needed right now.
        </div>
      ) : (
        <div className="space-y-3">
          {declining.map((t) => (
            <div key={t.platform} className="flex items-center justify-between rounded-xl border border-destructive/30 bg-destructive/5 p-4">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-destructive" />
                <span className="text-sm">
                  <span className="font-medium" style={{ color: PLATFORM_COLORS[t.platform] }}>
                    {platformLabel(t.platform)}
                  </span>{' '}
                  is losing followers ({t.gained} in window).
                </span>
              </div>
              <button
                onClick={() => draftWinBack(t.platform)}
                disabled={busy}
                className="inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                <Sparkles className="h-3.5 w-3.5" /> Draft win-back
              </button>
            </div>
          ))}

          {weakFindings.map((w, i) => (
            <div key={i} className="rounded-xl border border-warning/30 bg-warning/5 p-4">
              <div className="text-sm font-medium" style={{ color: PLATFORM_COLORS[w.platform] }}>
                {w.account}
              </div>
              <div className="mt-1 text-sm">
                <span className="font-medium">{w.f.title}.</span>{' '}
                <span className="text-muted-foreground">{w.f.detail}</span>
              </div>
              <div className="mt-1 text-xs text-foreground/80">→ {w.f.suggestion}</div>
            </div>
          ))}
        </div>
      )}

      {draft && (
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium">
            <RefreshCw className="h-4 w-4" /> Suggested win-back post
          </div>
          <p className="whitespace-pre-line text-sm">{draft}</p>
        </div>
      )}
    </div>
  )
}
