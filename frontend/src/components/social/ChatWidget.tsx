import { useEffect, useRef, useState } from 'react'
import { Bot, Send, Sparkles, X } from 'lucide-react'
import { aiChat, getAiStatus, getReport, type AiStatus } from '@/lib/social'

interface Msg {
  role: 'user' | 'ai'
  text: string
}

export function ChatWidget() {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<AiStatus | null>(null)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) getAiStatus().then(setStatus)
  }, [open])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs])

  const send = async () => {
    if (!input.trim() || busy) return
    const userMsg = input.trim()
    setMsgs((m) => [...m, { role: 'user', text: userMsg }])
    setInput('')
    setBusy(true)
    try {
      // Feed the latest report as context so the AI answers with real numbers.
      const ctx = await getReport()
        .then((d) =>
          d.report.diagnoses
            .map((x) => `${x.account}: score ${x.score}, ${x.findings.map((f) => f.title).join('; ')}`)
            .join('\n'),
        )
        .catch(() => undefined)
      const { reply } = await aiChat(userMsg, ctx)
      setMsgs((m) => [...m, { role: 'ai', text: reply }])
    } catch {
      setMsgs((m) => [...m, { role: 'ai', text: 'Sorry, something went wrong reaching the assistant.' }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-5 right-5 z-30 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg hover:opacity-90"
        aria-label="Open assistant"
      >
        {open ? <X className="h-5 w-5" /> : <Bot className="h-5 w-5" />}
      </button>

      {open && (
        <div className="fixed bottom-20 right-5 z-30 flex h-[28rem] w-[22rem] max-w-[90vw] flex-col rounded-2xl border border-border bg-card shadow-xl">
          <div className="flex items-center gap-2 border-b border-border px-4 py-3">
            <Sparkles className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold">Growth Assistant</span>
            <span className="ml-auto text-xs text-muted-foreground">
              {status?.enabled ? `AI on` : 'offline tips'}
            </span>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
            {msgs.length === 0 && (
              <p className="text-muted-foreground">
                Ask anything about your socials — “why is engagement low on Instagram?” or “what should I post this week?”
              </p>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
                <span
                  className={`inline-block max-w-[85%] rounded-2xl px-3 py-2 ${
                    m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
                  }`}
                >
                  {m.text}
                </span>
              </div>
            ))}
            <div ref={endRef} />
          </div>

          <div className="flex items-center gap-2 border-t border-border p-3">
            <input
              className="flex-1 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
              placeholder="Ask the assistant…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && send()}
            />
            <button
              onClick={send}
              disabled={busy}
              className="rounded-lg bg-primary p-2 text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </>
  )
}
