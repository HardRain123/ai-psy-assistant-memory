export function safetyFallbackStream({
  safetyGuidance,
  riskLevel,
  immediateActionRequired,
  error,
}: {
  safetyGuidance: Record<string, unknown>
  riskLevel: string
  immediateActionRequired: boolean
  error: string
}) {
  const events = [
    {
      type: 'safety',
      immediateActionRequired,
      riskLevel,
      guidance: safetyGuidance,
    },
    { type: 'error', error },
  ]
  const body = events
    .map((event) => `data: ${JSON.stringify(event)}\n\n`)
    .join('')
  return new Response(body, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
    },
  })
}
