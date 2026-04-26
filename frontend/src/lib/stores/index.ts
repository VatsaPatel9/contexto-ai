import { writable, get } from 'svelte/store';
import { v4 as uuidv4 } from 'uuid';

// ── PDF viewer panel (right-side drawer) ──────────────────────────────
export type PdfViewerRequest = {
  docId: string;
  title: string;
  page?: number;
  highlight?: string;
};
export const pdfViewerRequest = writable<PdfViewerRequest | null>(null);

export function openPdfViewer(req: PdfViewerRequest) {
  pdfViewerRequest.set(req);
}
export function closePdfViewer() {
  pdfViewerRequest.set(null);
}

// ── Types ──────────────────────────────────────────────────────────────

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  messageType?: string | null;
  done?: boolean;
  error?: string;
  feedback?: 'like' | 'dislike' | null;
  // Raw accumulated stream text (pre-fence-strip). Used only during
  // streaming so we can keep appending chunks and re-parse the
  // citations fence as it completes. Never shown to the user.
  _raw?: string;
  retrieverResources?: Array<{
    doc_title: string;
    doc_id?: string;
    page_num?: number;
    section?: string;
    score?: number;
  }> | null;
  // Clickable follow-up questions the tutor suggests when it can't
  // answer. Rendered as chips at the bottom of the assistant bubble.
  suggestions?: string[] | null;
  // Interactive comprehension check the tutor attached to the answer.
  // Resolved locally — the user picks and the component reveals the
  // correct answer + explanation. No round-trip needed.
  quiz?: import('$lib/utils/citations').Quiz | null;
  // True while the `quiz` fence is open but not yet closed in the
  // stream — UI shows a "Generating quiz…" placeholder so the pane
  // doesn't look frozen between the main body ending and the quiz
  // buttons arriving.
  quizPending?: boolean;
};

export type Conversation = {
  id: string;
  name: string;
  courseId: string;
  createdAt: number;
  updatedAt: number;
};

// ── Zustand-style persistent store helper ──────────────────────────────

function persistentStore<T>(key: string, initial: T) {
  let data = initial;
  if (typeof localStorage !== 'undefined') {
    const stored = localStorage.getItem(key);
    if (stored !== null) {
      try {
        data = JSON.parse(stored) as T;
      } catch {
        // Stored value isn't valid JSON (e.g. raw string like "system")
        // Try treating it as a plain string value
        data = stored as unknown as T;
      }
    }
  }
  const { subscribe, set, update } = writable<T>(data);

  return {
    subscribe,
    set(value: T) {
      set(value);
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(key, JSON.stringify(value));
      }
    },
    update(fn: (current: T) => T) {
      update((current) => {
        const updated = fn(current);
        if (typeof localStorage !== 'undefined') {
          localStorage.setItem(key, JSON.stringify(updated));
        }
        return updated;
      });
    }
  };
}

// ── Session Store ──────────────────────────────────────────────────────
// Manages user identity. Generates a persistent anonymous ID on first visit.
// This ID is sent as the `user` parameter to all backend API calls.

export type Session = {
  userId: string;
  courseId: string;
  createdAt: number;
};

function createSessionStore() {
  const store = persistentStore<Session>('session', {
    userId: '',
    courseId: 'BIO101',
    createdAt: 0
  });

  function ensureUserId() {
    const current = get(store);
    if (!current.userId) {
      store.set({
        userId: `student-${uuidv4().slice(0, 8)}`,
        courseId: 'BIO101',
        createdAt: Date.now()
      });
    }
  }

  // Only initialize on the client side
  if (typeof window !== 'undefined') {
    ensureUserId();
  }

  return {
    subscribe: store.subscribe,
    set: store.set,
    update: store.update,
    init() {
      ensureUserId();
    },
    getUserId(): string {
      ensureUserId();
      return get(store).userId;
    },
    getCourseId(): string {
      return get(store).courseId;
    },
    setCourseId(courseId: string) {
      store.update((s) => ({ ...s, courseId }));
    },
    reset() {
      store.set({
        userId: `student-${uuidv4().slice(0, 8)}`,
        courseId: 'BIO101',
        createdAt: Date.now()
      });
    }
  };
}

export const session = createSessionStore();

// ── Theme Store ────────────────────────────────────────────────────────

export const theme = persistentStore<string>('theme', 'system');

// ── Conversations Store ────────────────────────────────────────────────
// Conversations are fetched from the backend but cached locally for
// instant sidebar rendering. The backend is the source of truth.

export const conversations = writable<Conversation[]>([]);
export const conversationsLoaded = writable<boolean>(false);

// ── Current Chat State ─────────────────────────────────────────────────

export const currentChatId = writable<string | null>(null);

// Bumped each time the sidebar "+" button is clicked. The /chat page
// keys its <ChatWindow> on this so a click always forces a fresh
// remount — even when the user is already on /chat and goto('/chat')
// would otherwise no-op.
export const newChatNonce = writable<number>(0);

// ── UI State ───────────────────────────────────────────────────────────

export const mobile = writable<boolean>(false);
export const showSidebar = writable<boolean>(true);

// ── Admin section counts (populated by /admin page, read by Sidebar) ───

export const adminCounts = writable<{ users: number; courses: number; violations: number }>({
  users: 0,
  courses: 0,
  violations: 0,
});

// ── Parameters (from backend /api/parameters) ──────────────────────────

export type AppParameters = {
  openingStatement: string;
  suggestedQuestions: string[];
  courseName: string;
};

export const appParameters = writable<AppParameters>({
  openingStatement: '',
  suggestedQuestions: [],
  courseName: ''
});
