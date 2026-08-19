import { useNavigate } from 'react-router-dom'
import { BarChart3, Cable, CalendarClock, FileText } from 'lucide-react'

const Index = () => {
  const navigate = useNavigate()
  return (
    <div className="mx-auto max-w-3xl space-y-8 p-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold">Social Analytics Automation</h1>
        <p className="text-muted-foreground">
          See where your socials are lacking and get an automatic plan to improve performance — across YouTube, Instagram,
          LinkedIn, Telegram and WhatsApp.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-3">
        <LaunchCard
          icon={<Cable className="h-5 w-5" />}
          title="Connect platforms"
          desc="Add API keys to pull live data, or explore with sample data."
          onClick={() => navigate('/connections')}
        />
        <LaunchCard
          icon={<BarChart3 className="h-5 w-5" />}
          title="Dashboard"
          desc="Follower growth and per-platform health at a glance."
          onClick={() => navigate('/dashboard')}
        />
        <LaunchCard
          icon={<CalendarClock className="h-5 w-5" />}
          title="Planner"
          desc="Draft, schedule, and get best-time + copy suggestions."
          onClick={() => navigate('/planner')}
        />
        <LaunchCard
          icon={<FileText className="h-5 w-5" />}
          title="Auto-report"
          desc="Where you're weak and what to do about it."
          onClick={() => navigate('/report')}
        />
      </div>
    </div>
  )
}

function LaunchCard({
  icon,
  title,
  desc,
  onClick,
}: {
  icon: React.ReactNode
  title: string
  desc: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col items-start gap-2 rounded-xl border border-border bg-card p-4 text-left hover:border-primary"
    >
      <span className="text-primary">{icon}</span>
      <span className="font-medium">{title}</span>
      <span className="text-xs text-muted-foreground">{desc}</span>
    </button>
  )
}

export default Index
