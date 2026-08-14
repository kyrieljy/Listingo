import { trackAnalyticsEvent, type AnalyticsEventPayload } from '../../api/client'

const SESSION_KEY = 'listingo.analytics.session'

function createSessionId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function analyticsSessionId(): string {
  if (typeof window === 'undefined') return createSessionId()
  try {
    const existing = window.localStorage.getItem(SESSION_KEY)
    if (existing) return existing
    const next = createSessionId()
    window.localStorage.setItem(SESSION_KEY, next)
    return next
  } catch {
    return createSessionId()
  }
}

export function trackWorkspaceEvent(payload: AnalyticsEventPayload): void {
  void trackAnalyticsEvent({
    session_id: analyticsSessionId(),
    surface: 'workspace',
    event_type: 'click',
    ...payload,
    metadata: {
      route: typeof window !== 'undefined' ? window.location.pathname : '',
      ...(payload.metadata || {}),
    },
  }).catch(() => {})
}
