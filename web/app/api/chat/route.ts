export async function POST(req: Request) {
  try {
    const { message, userId, conversationId } = await req.json()

    if (!message || !userId) {
      return Response.json(
        { error: 'message and userId are required' },
        { status: 400 }
      )
    }

    const difyApiUrl = process.env.DIFY_API_URL
    const difyApiKey = process.env.DIFY_API_KEY

    if (!difyApiUrl || !difyApiKey) {
      return Response.json(
        { error: 'Dify API is not configured' },
        { status: 500 }
      )
    }

    const res = await fetch(`${difyApiUrl}/chat-messages`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${difyApiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query: message,
        user: userId,
        conversation_id: conversationId || '',
        response_mode: 'blocking',
        inputs: {
          user_id: userId,
        },
      }),
    })

    const data = await res.json()

    if (!res.ok) {
      return Response.json(
        { error: data?.message || 'Dify request failed' },
        { status: res.status }
      )
    }

    return Response.json({
      answer: data.answer || '',
      conversationId: data.conversation_id || conversationId || '',
    })
  } catch (error) {
    return Response.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}