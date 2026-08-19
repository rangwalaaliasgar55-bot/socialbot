import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ArrowUpRight, TrendingDown, TrendingUp } from 'lucide-react'
import { getReport, platformLabel, PLATFORM_COLORS, type Diagnosis, type GrowthTrend } from '@/lib/social'
import { ScoreRing, StatCard } from '@/components/social/ui'

export default function Dashboard() {
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({ queryKey: ['report'], queryFn: getReport })

  if (isLoading) {
    return <div className="p-8 text-muted-foreground">Analyzing your socials…</div>
  }
  if (!data) return <div className="p-8">No data.</div>

  const { report, snapshots } = data

  // Build a combined follower-growth series keyed by date.
  const byDate = new Map<string, Record<string, number | null>>()
  snapshots.forEach((s) => {
    s.series.forEach((p) => {
      const row = byDate.get(p.date) || {}
      row[s.platform] = p.followers
      byDate.set(p.date, row)
    })
  })
  const chartData = [...byDate.entries()].map(([date, row]) => ({ date: date.slice(5), ...row }))

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Social Analytics</h1>
          <p className="text-sm text-muted-foreground">Growth & follower performance across your platforms</p>
        </div>
        <button
          onClick={() => navigate('/report')}
          className="inline-flex items-center gap-1 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          View auto-report <ArrowUpRight className="h-4 w-4" />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Overall health" value={`${report.overallScore}/100`} hint="Across all platforms" />
        <StatCard label="Platforms" value={report.platformCount} />
        <StatCard label="Period" value={`${report.periodDays}d`} hint="Trailing window" />
        <StatCard
          label="Net followers"
          value={report.trends.reduce((s, t) => s + (t.followers == null ? 0 : t.gained), 0).toLocaleString()}
          hint="Gained in window"
        />
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <div className="mb-3 text-sm font-medium">Follower growth (last {report.periodDays} days)</div>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
              <YAxis tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
              <Tooltip contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 8 }} />
              {snapshots
                .filter((s) => s.totals.followers != null)
                .map((s) => (
                  <Line
                    key={s.platform}
                    type="monotone"
                    dataKey={s.platform}
                    name={platformLabel(s.platform)}
                    stroke={PLATFORM_COLORS[s.platform]}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Per-platform health</h2>
          <button onClick={() => navigate('/connections')} className="text-sm text-primary hover:underline">
            Manage connections
          </button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {report.diagnoses.map((d) => (
            <PlatformHealthCard key={d.platform} trend={report.trends.find((t) => t.platform === d.platform)!} diagnosis={d} />
          ))}
        </div>
      </div>
    </div>
  )
}

function PlatformHealthCard({ trend, diagnosis }: { trend: GrowthTrend; diagnosis: Diagnosis }) {
  const weak = diagnosis.findings.filter((f) => f.severity !== 'good')
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-full" style={{ background: PLATFORM_COLORS[diagnosis.platform] }} />
          <span className="font-medium">{diagnosis.account}</span>
        </div>
        <ScoreRing score={diagnosis.score} />
      </div>
      <div className="mt-2 flex items-center gap-1 text-sm">
        {trend.trend === 'up' && <TrendingUp className="h-4 w-4 text-success" />}
        {trend.trend === 'down' && <TrendingDown className="h-4 w-4 text-destructive" />}
        <span className="text-muted-foreground">
          {trend.followers == null
            ? 'engagement-only'
            : `${trend.gained >= 0 ? '+' : ''}${trend.gained.toLocaleString()} followers`}
        </span>
      </div>
      {weak.length > 0 ? (
        <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
          {weak.slice(0, 2).map((f, i) => (
            <li key={i}>• {f.title}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-xs text-success">All checks healthy.</p>
      )}
    </div>
  )
}
