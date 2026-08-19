import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, KeyRound, Loader2 } from 'lucide-react'
import { getPlatforms, platformLabel, PLATFORM_COLORS, saveConnection, type PlatformCredentials, type PlatformId } from '@/lib/social'
import { SeverityBadge } from '@/components/social/ui'

const FIELD_HINTS: Record<PlatformId, { apiKey?: string; accessToken?: string; extra?: string }> = {
  youtube: { apiKey: 'YouTube Data API v3 key', extra: 'Channel ID (optional)' },
  instagram: { accessToken: 'Meta Page access token', extra: 'IG user ID (optional)' },
  linkedin: { accessToken: 'LinkedIn access token', extra: 'Organization ID (optional)' },
  telegram: { accessToken: 'Bot token', extra: 'Channel username (e.g. @mychannel)' },
  whatsapp: { accessToken: 'WhatsApp Business token', extra: 'Phone number ID (optional)' },
}

export default function Connections() {
  const qc = useQueryClient()
  const { data: platforms } = useQuery({ queryKey: ['platforms'], queryFn: getPlatforms })
  const [selected, setSelected] = useState<PlatformId>('youtube')
  const [form, setForm] = useState<PlatformCredentials>({ platform: 'youtube', account: '' })

  const mutation = useMutation({
    mutationFn: saveConnection,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platforms'] })
      qc.invalidateQueries({ queryKey: ['report'] })
    },
  })

  const meta = platforms?.find((p) => p.id === selected)
  const hints = FIELD_HINTS[selected]

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">Connections</h1>
        <p className="text-sm text-muted-foreground">
          Add API credentials for each platform. Without credentials the dashboard runs on sample data so you can explore immediately.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {platforms?.map((p) => (
          <button
            key={p.id}
            onClick={() => {
              setSelected(p.id)
              setForm({ platform: p.id, account: '' })
            }}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
              selected === p.id ? 'border-primary bg-primary/10' : 'border-border'
            }`}
          >
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: PLATFORM_COLORS[p.id] }} />
            {p.label}
            {p.configured && <Check className="h-3.5 w-3.5 text-success" />}
          </button>
        ))}
      </div>

      {meta && (
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium">{platformLabel(selected)} credentials</span>
            </div>
            <SeverityBadge severity={meta.supportsGrowth ? 'good' : 'watch'} />
          </div>
          <p className="mb-4 text-xs text-muted-foreground">{meta.note}</p>

          <div className="space-y-3">
            <Field label="Account / handle">
              <input
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                placeholder="e.g. @mybrand"
                value={form.account}
                onChange={(e) => setForm({ ...form, account: e.target.value })}
              />
            </Field>
            {hints.apiKey && (
              <Field label={hints.apiKey}>
                <input
                  type="password"
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                  value={form.apiKey ?? ''}
                  onChange={(e) => setForm({ ...form, apiKey: e.target.value })}
                />
              </Field>
            )}
            {hints.accessToken && (
              <Field label={hints.accessToken}>
                <input
                  type="password"
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                  value={form.accessToken ?? ''}
                  onChange={(e) => setForm({ ...form, accessToken: e.target.value })}
                />
              </Field>
            )}
            {hints.extra && (
              <Field label={hints.extra}>
                <input
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                  value={form.extra ?? ''}
                  onChange={(e) => setForm({ ...form, extra: e.target.value })}
                />
              </Field>
            )}
          </div>

          <button
            disabled={mutation.isPending || !form.account}
            onClick={() => mutation.mutate(form)}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {mutation.isSuccess ? 'Saved' : 'Save connection'}
          </button>
        </div>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}
