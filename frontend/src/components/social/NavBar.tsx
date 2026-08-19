import { NavLink } from 'react-router-dom'
import { BarChart3, Cable, CalendarClock, FileText, Home, Users } from 'lucide-react'

const links = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/dashboard', label: 'Dashboard', icon: BarChart3, end: false },
  { to: '/planner', label: 'Planner', icon: CalendarClock, end: false },
  { to: '/engagement', label: 'Engagement', icon: Users, end: false },
  { to: '/connections', label: 'Connections', icon: Cable, end: false },
  { to: '/report', label: 'Report', icon: FileText, end: false },
]

export function NavBar() {
  return (
    <nav className="sticky top-0 z-20 border-b border-border bg-background/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-1 px-4 py-2">
        <span className="mr-3 text-sm font-semibold">SocialScope</span>
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.end}
            className={({ isActive }) =>
              `inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm ${
                isActive ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-accent'
              }`
            }
          >
            <l.icon className="h-4 w-4" />
            {l.label}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
