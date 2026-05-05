/**
 * Exam authoring + (Phase 2) student-taking API client.
 *
 * Phase 1 only ships the admin authoring surface. Student endpoints
 * land alongside Phase 2 in the same module.
 *
 * All deadlines are stored UTC server-side. The browser converts the
 * admin's local picker value to a UTC ISO string for transit and renders
 * the response in the viewer's local zone.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL;

// ── Types ──────────────────────────────────────────────────────────────

export type QuestionType = 'mcq' | 'true_false';
export type ExamState = 'draft' | 'published' | 'closed' | 'archived';

export type ExamOption = {
  id: string;
  position: number;
  text: string;
  is_correct: boolean;
};

export type ExamQuestion = {
  id: string;
  position: number;
  type: QuestionType;
  text: string;
  explanation: string | null;
  options: ExamOption[];
};

export type ExamSummary = {
  id: string;
  course_id: string;
  title: string;
  description: string | null;
  state: ExamState;
  deadline_at: string;            // ISO 8601 UTC
  time_limit_minutes: number | null;
  question_count: number;
  created_by: string;
  created_at: string;
  published_at: string | null;
};

export type ExamDetail = ExamSummary & { questions: ExamQuestion[] };

export type OptionInput = { text: string; is_correct: boolean };
export type QuestionInput = {
  type: QuestionType;
  text: string;
  explanation?: string | null;
  options: OptionInput[];
};

// ── Helpers ────────────────────────────────────────────────────────────

async function examFetch(path: string, opts: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Exam API error (${res.status}): ${text}`);
  }
  return res;
}

// ── Admin: course-scoped ───────────────────────────────────────────────

export async function listExams(courseId: string): Promise<ExamSummary[]> {
  const res = await examFetch(
    `/api/admin/courses/${encodeURIComponent(courseId)}/exams`,
  );
  const json = await res.json();
  return json.exams as ExamSummary[];
}

export async function createExam(
  courseId: string,
  body: {
    title: string;
    description?: string;
    deadline_at: string;          // ISO UTC
    time_limit_minutes?: number | null;
  },
): Promise<ExamDetail> {
  const res = await examFetch(
    `/api/admin/courses/${encodeURIComponent(courseId)}/exams`,
    { method: 'POST', body: JSON.stringify(body) },
  );
  return res.json();
}

// ── Admin: exam-scoped ─────────────────────────────────────────────────

export async function getExam(examId: string): Promise<ExamDetail> {
  const res = await examFetch(`/api/admin/exams/${examId}`);
  return res.json();
}

export async function updateExam(
  examId: string,
  body: {
    title?: string;
    description?: string;
    deadline_at?: string;
    time_limit_minutes?: number | null;
  },
): Promise<ExamDetail> {
  const res = await examFetch(`/api/admin/exams/${examId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function publishExam(examId: string): Promise<ExamDetail> {
  const res = await examFetch(`/api/admin/exams/${examId}/publish`, {
    method: 'POST',
  });
  return res.json();
}

export async function deleteExam(examId: string) {
  const res = await examFetch(`/api/admin/exams/${examId}`, { method: 'DELETE' });
  return res.json();
}

// ── Admin: question CRUD ───────────────────────────────────────────────

export async function addQuestion(
  examId: string,
  question: QuestionInput,
): Promise<ExamQuestion> {
  const res = await examFetch(`/api/admin/exams/${examId}/questions`, {
    method: 'POST',
    body: JSON.stringify(question),
  });
  return res.json();
}

export async function addQuestionsBulk(
  examId: string,
  questions: QuestionInput[],
): Promise<ExamQuestion[]> {
  const res = await examFetch(`/api/admin/exams/${examId}/questions/bulk`, {
    method: 'POST',
    body: JSON.stringify({ questions }),
  });
  const json = await res.json();
  return json.questions as ExamQuestion[];
}

export async function updateQuestion(
  examId: string,
  questionId: string,
  patch: Partial<QuestionInput> & { position?: number },
): Promise<ExamQuestion> {
  const res = await examFetch(
    `/api/admin/exams/${examId}/questions/${questionId}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return res.json();
}

export async function deleteQuestion(examId: string, questionId: string) {
  const res = await examFetch(
    `/api/admin/exams/${examId}/questions/${questionId}`,
    { method: 'DELETE' },
  );
  return res.json();
}

export async function reorderQuestions(examId: string, questionIds: string[]) {
  const res = await examFetch(`/api/admin/exams/${examId}/questions/reorder`, {
    method: 'POST',
    body: JSON.stringify({ question_ids: questionIds }),
  });
  return res.json();
}

// ── Admin: AI question generation (Phase 3) ────────────────────────────

export type CandidateQuestion = {
  client_id: string;            // stable across edits; not persisted
  type: QuestionType;
  text: string;
  explanation: string;
  options: { text: string; is_correct: boolean }[];
  source_chunks: { doc_title: string; page_num: number; section: string }[];
};

export type GenerateResponse = {
  candidates: CandidateQuestion[];
  requested: { mcq: number; tf: number };
  dropped: number;
  chunks_used: number;
};

export async function generateQuestions(
  examId: string,
  body: { topic: string; n_mcq: number; n_tf: number },
): Promise<GenerateResponse> {
  const res = await examFetch(`/api/admin/exams/${examId}/generate`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return res.json();
}

// ── Admin: Agentic chat (Phase 5) ──────────────────────────────────────
//
// History round-trips through the client — server is stateless. Each
// turn, the client sends the existing history + the new user message;
// server returns the new fragments to append (assistant turns, any
// tool calls + tool results, final assistant text) plus any candidates
// produced by tool calls.

export type AgentHistoryMessage = {
  role: 'user' | 'assistant' | 'tool';
  content?: string | null;
  tool_calls?: Array<{
    id: string;
    type: 'function';
    function: { name: string; arguments: string };
  }>;
  tool_call_id?: string | null;
  name?: string | null;
};

export type AgentResponse = {
  assistant_message: string;
  candidates: CandidateQuestion[];
  dropped: number;
  appended_history: AgentHistoryMessage[];
};

export async function callExamAgent(
  examId: string,
  body: { user_message: string; history: AgentHistoryMessage[] },
): Promise<AgentResponse> {
  const res = await examFetch(`/api/admin/exams/${examId}/agent`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return res.json();
}

// ── Admin: Gradebook + override + retake grants (Phase 4) ──────────────

export type GradebookRow = {
  user_id: string;
  display_name: string | null;
  email: string | null;
  status: 'submitted' | 'in_progress' | 'missed' | 'not_started';
  attempt_id: string | null;
  attempt_count: number;
  submitted_at: string | null;
  score_pct: number | null;
  score_raw: number | null;
  auto_score_raw: number | null;
  total_points: number | null;
  manual_override: boolean;
  active_grants: number;
};

export type Gradebook = {
  exam_id: string;
  course_id: string;
  title: string;
  total_enrolled: number;
  rows: GradebookRow[];
};

export type AttemptDetailAdmin = {
  attempt_id: string;
  exam_id: string;
  user_id: string;
  display_name: string | null;
  email: string | null;
  started_at: string;
  submitted_at: string | null;
  due_at: string;
  score_raw: number | null;
  score_pct: number | null;
  total_points: number | null;
  auto_score_raw: number | null;
  manual_override_score: number | null;
  override_by: string | null;
  override_reason: string | null;
  override_at: string | null;
  review: {
    question_id: string;
    type: QuestionType;
    text: string;
    explanation: string | null;
    options: { id: string; text: string; is_correct: boolean }[];
    selected_option_ids: string[];
    is_correct: boolean;
    partial_score: number;
  }[];
};

export type GrantRow = {
  id: string;
  user_id: string;
  display_name: string | null;
  email: string | null;
  granted_by: string;
  granted_at: string;
  reason: string | null;
  consumed: boolean;
  consumed_at: string | null;
  consumed_by_attempt_id: string | null;
};

export async function getGradebook(examId: string): Promise<Gradebook> {
  const res = await examFetch(`/api/admin/exams/${examId}/gradebook`);
  return res.json();
}

export async function getAttemptDetail(
  examId: string,
  attemptId: string,
): Promise<AttemptDetailAdmin> {
  const res = await examFetch(`/api/admin/exams/${examId}/attempts/${attemptId}`);
  return res.json();
}

export async function overrideAttemptScore(
  examId: string,
  attemptId: string,
  body: { score_raw: number | null; reason?: string },
) {
  const res = await examFetch(
    `/api/admin/exams/${examId}/attempts/${attemptId}/score`,
    { method: 'PATCH', body: JSON.stringify(body) },
  );
  return res.json();
}

export async function listGrants(examId: string): Promise<{ grants: GrantRow[] }> {
  const res = await examFetch(`/api/admin/exams/${examId}/grants`);
  return res.json();
}

export async function grantRetake(
  examId: string,
  body: { identifier: string; reason?: string },
) {
  const res = await examFetch(`/api/admin/exams/${examId}/grants`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function revokeGrant(examId: string, grantId: string) {
  const res = await examFetch(`/api/admin/exams/${examId}/grants/${grantId}`, {
    method: 'DELETE',
  });
  return res.json();
}

// ── Helpers shared with UI ─────────────────────────────────────────────

/**
 * Take a `<input type="datetime-local">` value (interpreted in the
 * viewer's local TZ) and produce a UTC ISO string for the API.
 */
export function localInputToUtcIso(localValue: string): string {
  if (!localValue) return '';
  // The Date constructor parses "YYYY-MM-DDTHH:mm" as local time.
  return new Date(localValue).toISOString();
}

/**
 * Inverse of `localInputToUtcIso` — produce a value the
 * `<input type="datetime-local">` will accept, in viewer-local time.
 */
export function utcIsoToLocalInput(iso: string): string {
  const d = new Date(iso);
  // Pad and slice to "YYYY-MM-DDTHH:mm" (no seconds, no TZ suffix).
  const pad = (n: number) => `${n}`.padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

export function formatLocalDeadline(iso: string): string {
  // Friendly viewer-local rendering, e.g. "May 12, 2026, 5:00 PM EDT".
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

// ── Student-facing types & calls ───────────────────────────────────────

export type StudentExamRow = {
  id: string;
  course_id: string | null;
  course_name: string | null;
  title: string;
  description: string | null;
  deadline_at: string;            // ISO UTC
  time_limit_minutes: number | null;
  question_count: number;
  display_state: 'available' | 'in_progress' | 'submitted' | 'missed' | 'past_deadline';
  score_pct: number | null;
  submitted_at: string | null;
  time_remaining_seconds: number | null;
  can_retake: boolean;
};

export type StudentExamSummary = {
  id: string;
  title: string;
  description: string | null;
  deadline_at: string;
  time_limit_minutes: number | null;
  question_count: number;
  display_state: 'available' | 'in_progress' | 'submitted' | 'missed';
  has_attempt: boolean;
  can_retake: boolean;
};

export type AttemptOption = { id: string; text: string; position: number };
export type AttemptQuestion = {
  id: string;
  type: QuestionType;
  text: string;
  options: AttemptOption[];
  selected_option_ids: string[];
};

export type AttemptDetail = {
  attempt_id: string;
  exam_id: string;
  title: string;
  description: string | null;
  deadline_at: string;
  due_at: string;
  time_remaining_seconds: number;
  submitted_at: string | null;
  questions: AttemptQuestion[];
};

export type ResultReviewRow = {
  question_id: string;
  type: QuestionType;
  text: string;
  explanation: string | null;
  options: { id: string; text: string; is_correct: boolean }[];
  selected_option_ids: string[];
  is_correct: boolean;
  partial_score: number;
};

export type ResultPayload = {
  attempt_id: string;
  exam_id: string;
  title: string;
  submitted_at: string;
  deadline_at: string;
  score_pct: number;
  score_raw: number;
  total_points: number;
  review_unlocked: boolean;
  auto_score_raw: number | null;
  manual_override: boolean;
  review?: ResultReviewRow[];
};

export async function listMyExams(): Promise<StudentExamRow[]> {
  const res = await examFetch('/api/exams');
  const json = await res.json();
  return json.exams as StudentExamRow[];
}

export async function getStudentExamSummary(examId: string): Promise<StudentExamSummary> {
  const res = await examFetch(`/api/exams/${examId}`);
  return res.json();
}

export async function startAttempt(examId: string) {
  const res = await examFetch(`/api/exams/${examId}/start`, { method: 'POST' });
  return res.json() as Promise<{ attempt_id: string; started_at: string; due_at: string }>;
}

export async function getMyAttempt(examId: string): Promise<AttemptDetail> {
  const res = await examFetch(`/api/exams/${examId}/attempt`);
  return res.json();
}

export async function autosaveResponse(
  examId: string,
  questionId: string,
  selectedOptionIds: string[],
) {
  const res = await examFetch(
    `/api/exams/${examId}/attempt/responses/${questionId}`,
    { method: 'PUT', body: JSON.stringify({ selected_option_ids: selectedOptionIds }) },
  );
  return res.json();
}

export async function submitAttempt(examId: string) {
  const res = await examFetch(`/api/exams/${examId}/submit`, { method: 'POST' });
  return res.json() as Promise<{
    result: 'success';
    attempt_id: string;
    submitted_at: string;
    score_pct: number;
    score_raw: number;
    total_points: number;
  }>;
}

export async function getMyResult(examId: string): Promise<ResultPayload> {
  const res = await examFetch(`/api/exams/${examId}/result`);
  return res.json();
}

export function formatTimeRemaining(seconds: number): string {
  if (seconds <= 0) return '0:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n: number) => `${n}`.padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}
