import type { ReactNode } from 'react'
import type { Severity } from '@/lib/social'

export function StatCard({
  label,
  value,
  hint,
}: {
  label: string
  value: ReactNode
  hint?: string
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-foreground">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}

const SEV: Record<Severity, { label: string; cls: string }> = {
  good: { label: 'Healthy', cls: 'bg-success/15 text-success' },
  watch: { label: 'Watch', cls: 'bg-warning/15 text-warning' },
  weak: { label: 'Weak', cls: 'bg-destructive/15 text-destructive' },
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEV[severity]
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}>{s.label}</span>
}

export function ScoreRing({ score }: { score: number }) {
  const color = score >= 75 ? 'var(--success)' : score >= 50 ? 'var(--warning)' : 'var(--destructive)'
  const r = 26
  const c = 2 * Math.PI * r
  const off = c * (1 - score / 100)
  return (
    <div className="relative h-16 w-16">
      <svg className="h-16 w-16 -rotate-90" viewBox="0 0 64 64">
        <circle cx="32" cy="32" r={r} fill="none" stroke="var(--muted)" strokeWidth="6" />
        <circle
          cx="32"
          cy="32"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeDasharray={c}
          strokeDashoffset={off}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-sm font-semibold">{score}</div>
    </div>
  )
}
