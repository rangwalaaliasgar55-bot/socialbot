import { useQuery } from '@tanstack/react-query'
import { Download, Sparkles } from 'lucide-react'
import { getReport, platformLabel, PLATFORM_COLORS, type AutoReport } from '@/lib/social'
import { SeverityBadge } from '@/components/social/ui'

export default function Report() {
  const { data, isLoading } = useQuery({ queryKey: ['report'], queryFn: getReport })

  if (isLoading) return <div className="p-8 text-muted-foreground">Generating your report…</div>
  if (!data) return <div className="p-8">No data.</div>

  const { report } = data

  const exportMd = () => {
    const md = buildMarkdown(report)
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `social-report-${report.generatedAt.slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Auto-generated report</h1>
          <p className="text-sm text-muted-foreground">
            Where you're lacking and what to improve — generated {new Date(report.generatedAt).toLocaleString()}
          </p>
        </div>
        <button
          onClick={exportMd}
          className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:bg-accent"
        >
          <Download className="h-4 w-4" /> Export
        </button>
      </div>

      <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-primary">
          <Sparkles className="h-4 w-4" /> Summary
        </div>
        <p className="mt-1 text-sm">{report.summary}</p>
      </div>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Where you're lacking (diagnosis)</h2>
        <div className="space-y-3">
          {report.diagnoses.map((d) => (
            <div key={d.platform} className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full" style={{ background: PLATFORM_COLORS[d.platform] }} />
                  <span className="font-medium">{d.account}</span>
                </div>
                <span className="text-sm text-muted-foreground">Score {d.score}/100</span>
              </div>
              <ul className="mt-3 space-y-2">
                {d.findings.map((f, i) => (
                  <li key={i} className="flex gap-3">
                    <SeverityBadge severity={f.severity} />
                    <div className="text-sm">
                      <span className="font-medium">{f.title}.</span>{' '}
                      <span className="text-muted-foreground">{f.detail}</span>
                      <div className="text-foreground/80">→ {f.suggestion}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Prioritized action plan</h2>
        <ol className="space-y-2">
          {report.actionPlan.map((b, i) => (
            <li key={i} className="rounded-lg border border-border bg-card p-3">
              <div className="text-sm font-medium">{b.heading}</div>
              <div className="mt-0.5 text-sm text-muted-foreground">{b.body}</div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}

function buildMarkdown(r: AutoReport): string {
  const lines: string[] = []
  lines.push(`# Social Performance Report`)
  lines.push(`Generated: ${new Date(r.generatedAt).toLocaleString()}`)
  lines.push(`Period: ${r.periodDays} days · Platforms: ${r.platformCount} · Overall health: ${r.overallScore}/100`)
  lines.push('')
  lines.push(`## Summary`)
  lines.push(r.summary)
  lines.push('')
  lines.push(`## Where you're lacking`)
  r.diagnoses.forEach((d) => {
    lines.push(`### ${platformLabel(d.platform)} — ${d.account} (score ${d.score}/100)`)
    d.findings.forEach((f) => lines.push(`- [${f.severity}] ${f.title}. ${f.detail} → ${f.suggestion}`))
    lines.push('')
  })
  lines.push(`## Action plan`)
  r.actionPlan.forEach((b, i) => lines.push(`${i + 1}. **${b.heading}** — ${b.body}`))
  return lines.join('\n')
}
