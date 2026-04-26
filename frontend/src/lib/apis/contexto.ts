/**
 * Backend API client for Contexto AI Tutor.
 *
 * Matches the FastAPI backend.
 *
 * Authentication is handled via SuperTokens httpOnly session cookies.
 * The supertokens-web-js SDK automatically attaches session tokens to
 * every fetch() call, so no explicit Authorization header is needed.
 *
 * Endpoints:
 *   POST   /api/chat-messages          — Send message (SSE streaming)
 *   GET    /api/conversations           — List conversations
 *   GET    /api/conversations/:id       — Get conversation
 *   DELETE /api/conversations/:id       — Delete conversation
 *   GET    /api/messages                — List messages in conversation
 *   POST   /api/messages/:id/feedbacks  — Submit feedback
 *   GET    /api/parameters              — Get UI config (opening statement, suggestions)
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL;

// ── Types ──────────────────────────────────────────────────────────────

export type StreamEvent = {
  event: string;
  answer?: string;
  conversation_id?: string;
  message_id?: string;
  created_at?: number;
  metadata?: {
    retriever_resources?: RetrieverResource[];
  };
  message?: string; // error message
  code?: string;    // error code
};

export type RetrieverResource = {
  doc_title: string;
  doc_id: string;
  page_num: number;
  section: string;
  score: number;
};

export type Conversation = {
  id: string;
  name: string;
  course_id: string;
  created_at: number;
  updated_at: number;
};

export type ConversationListResponse = {
  data: Conversation[];
  has_more: boolean;
};

export type ApiMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  message_type: string | null;
  created_at: number;
  retriever_resources: RetrieverResource[] | null;
  feedback?: 'like' | 'dislike' | null;
};

export type MessageListResponse = {
  data: ApiMessage[];
  has_more: boolean;
};

export type ParametersResponse = {
  opening_statement: string;
  suggested_questions: string[];
  course_name: string;
  terms_version: string;
};

// ── Chat Messages (SSE Streaming) ──────────────────────────────────────

export async function sendChatMessage(
  query: string,
  conversationId: string | null = null,
  courseId: string = 'BIO101'
): Promise<AsyncGenerator<StreamEvent>> {
  const body: Record<string, unknown> = {
    query,
    course_id: courseId,
    response_mode: 'streaming',
    inputs: {}
  };

  if (conversationId) {
    body.conversation_id = conversationId;
  }

  const response = await fetch(`${API_BASE}/api/chat-messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API error (${response.status}): ${errorText}`);
  }

  if (!response.body) {
    throw new Error('No response body from API');
  }

  return parseSSEStream(response.body);
}

// ── Conversations ──────────────────────────────────────────────────────

export async function getConversations(
  courseId?: string,
  limit: number = 20
): Promise<ConversationListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (courseId) params.set('course_id', courseId);

  const res = await fetch(`${API_BASE}/api/conversations?${params}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Failed to fetch conversations: ${res.status}`);
  return res.json();
}

export async function getConversation(conversationId: string): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/api/conversations/${conversationId}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Failed to fetch conversation: ${res.status}`);
  return res.json();
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/conversations/${conversationId}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Failed to delete conversation: ${res.status}`);
}

// ── Messages ───────────────────────────────────────────────────────────

export async function getMessages(
  conversationId: string,
  limit: number = 100
): Promise<MessageListResponse> {
  const params = new URLSearchParams({
    conversation_id: conversationId,
    limit: String(limit)
  });

  const res = await fetch(`${API_BASE}/api/messages?${params}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Failed to fetch messages: ${res.status}`);
  return res.json();
}

// ── Feedback ───────────────────────────────────────────────────────────

export async function submitFeedback(
  messageId: string,
  rating: 'like' | 'dislike'
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/messages/${messageId}/feedbacks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ rating })
  });
  if (!res.ok) throw new Error(`Failed to submit feedback: ${res.status}`);
}

// ── Parameters ─────────────────────────────────────────────────────────

export async function getParameters(): Promise<ParametersResponse> {
  const res = await fetch(`${API_BASE}/api/parameters`);
  if (!res.ok) throw new Error(`Failed to fetch parameters: ${res.status}`);
  return res.json();
}

// ── SSE Parser ─────────────────────────────────────────────────────────

/**
 * Parse an SSE stream from the backend into structured events.
 * Returns an async generator instead of a ReadableStream for simpler consumption.
 */
export async function* parseSSEStream(
  body: ReadableStream<Uint8Array>
): AsyncGenerator<StreamEvent> {
  const reader = body.pipeThrough(new TextDecoderStream() as unknown as ReadableWritablePair<string, Uint8Array>).getReader();
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();

      if (done) break;

      buffer += value;
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith('data:')) continue;

        const jsonStr = trimmed.slice(5).trim();
        if (!jsonStr || jsonStr === '[DONE]') continue;

        try {
          const event = JSON.parse(jsonStr) as StreamEvent;
          yield event;

          if (event.event === 'message_end' || event.event === 'error') {
            return;
          }
        } catch {
          // Skip malformed JSON lines
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
