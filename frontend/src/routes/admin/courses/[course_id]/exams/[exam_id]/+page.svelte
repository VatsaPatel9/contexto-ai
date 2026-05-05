<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { toast } from 'svelte-sonner';

  import { authStore } from '$lib/stores/auth';
  import {
    getExam,
    updateExam,
    publishExam,
    deleteExam,
    addQuestion,
    addQuestionsBulk,
    updateQuestion,
    deleteQuestion,
    generateQuestions,
    callExamAgent,
    getGradebook,
    getAttemptDetail,
    overrideAttemptScore,
    listGrants,
    grantRetake,
    revokeGrant,
    formatLocalDeadline,
    localInputToUtcIso,
    utcIsoToLocalInput,
    type ExamDetail,
    type ExamQuestion,
    type QuestionType,
    type CandidateQuestion,
    type AgentHistoryMessage,
    type Gradebook,
    type GradebookRow,
    type AttemptDetailAdmin,
    type GrantRow,
  } from '$lib/apis/exams';

  // Route params
  let courseId = $derived(($page.params as Record<string, string>).course_id);
  let examId = $derived(($page.params as Record<string, string>).exam_id);

  // Data
  let exam = $state<ExamDetail | null>(null);
  let loading = $state(true);
  let saving = $state(false);

  // Edit-meta drawer
  let metaOpen = $state(false);
  let editTitle = $state('');
  let editDescription = $state('');
  let editDeadline = $state('');
  let editTimeLimit = $state('60');

  // Selected question (id) for the right-side editor pane
  let selectedQuestionId = $state<string | null>(null);
  let selectedQuestion = $derived(
    exam?.questions.find((q) => q.id === selectedQuestionId) ?? null,
  );

  // Working copy of the selected question (so edits don't mutate the
  // server-shaped object until we hit Save)
  type WorkingOption = { text: string; is_correct: boolean };
  type WorkingQuestion = {
    id: string;
    type: QuestionType;
    text: string;
    explanation: string;
    options: WorkingOption[];
  };
  let working = $state<WorkingQuestion | null>(null);
  let workingDirty = $state(false);

  // Confirm dialog
  let showConfirm = $state(false);
  let confirmMessage = $state('');
  let confirmAction = $state<(() => Promise<void>) | null>(null);

  // ── Gradebook (Phase 4) ────────────────────────────────────────────
  // Top-level tab between "Questions" and "Gradebook". Gradebook only
  // makes sense once published (drafts have no attempts to grade).
  type View = 'editor' | 'gradebook';
  let activeView = $state<View>('editor');
  let gradebook = $state<Gradebook | null>(null);
  let gradebookLoading = $state(false);
  let grants = $state<GrantRow[]>([]);
  let grantsLoading = $state(false);

  // Grant retake form
  let grantIdentifier = $state('');
  let grantReason = $state('');
  let granting = $state(false);

  // Attempt drill-down drawer (right side)
  let attemptDetail = $state<AttemptDetailAdmin | null>(null);
  let attemptLoading = $state(false);
  let overrideRaw = $state('');
  let overrideReason = $state('');
  let savingOverride = $state(false);

  async function loadGradebook() {
    if (!exam) return;
    gradebookLoading = true;
    try {
      gradebook = await getGradebook(exam.id);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      gradebookLoading = false;
    }
  }

  async function loadGrants() {
    if (!exam) return;
    grantsLoading = true;
    try {
      const res = await listGrants(exam.id);
      grants = res.grants;
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      grantsLoading = false;
    }
  }

  async function openAttempt(attemptId: string) {
    if (!exam) return;
    attemptLoading = true;
    attemptDetail = null;
    try {
      attemptDetail = await getAttemptDetail(exam.id, attemptId);
      overrideRaw = attemptDetail.manual_override_score != null
        ? `${attemptDetail.manual_override_score}`
        : '';
      overrideReason = attemptDetail.override_reason ?? '';
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      attemptLoading = false;
    }
  }

  function closeAttemptDrawer() {
    attemptDetail = null;
    overrideRaw = '';
    overrideReason = '';
  }

  async function handleSaveOverride() {
    if (!exam || !attemptDetail) return;
    const trimmed = overrideRaw.trim();
    let score_raw: number | null;
    if (trimmed === '' || trimmed.toLowerCase() === 'clear') {
      score_raw = null;
    } else {
      const n = parseFloat(trimmed);
      if (!Number.isFinite(n) || n < 0) {
        toast.error('Override must be a non-negative number, or blank to clear'); return;
      }
      const total = attemptDetail.total_points ?? 0;
      if (total > 0 && n > total) {
        toast.error(`Override cannot exceed total points (${total})`); return;
      }
      score_raw = n;
    }
    savingOverride = true;
    try {
      await overrideAttemptScore(exam.id, attemptDetail.attempt_id, {
        score_raw,
        reason: overrideReason.trim() || undefined,
      });
      toast.success(score_raw === null ? 'Override cleared' : 'Override saved');
      // Refresh both the drawer detail and the row in the table.
      const refreshed = await getAttemptDetail(exam.id, attemptDetail.attempt_id);
      attemptDetail = refreshed;
      overrideRaw = refreshed.manual_override_score != null
        ? `${refreshed.manual_override_score}`
        : '';
      overrideReason = refreshed.override_reason ?? '';
      await loadGradebook();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      savingOverride = false;
    }
  }

  async function handleGrantRetake() {
    if (!exam) return;
    const id = grantIdentifier.trim();
    if (!id) { toast.error('Pick a student to grant'); return; }
    granting = true;
    try {
      const res = await grantRetake(exam.id, {
        identifier: id,
        reason: grantReason.trim() || undefined,
      });
      if (res.result === 'exists') {
        toast.success('Student already has an unused retake');
      } else {
        toast.success('Retake granted');
      }
      grantIdentifier = '';
      grantReason = '';
      await loadGrants();
      await loadGradebook();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      granting = false;
    }
  }

  function handleRevokeGrant(grant: GrantRow) {
    if (!exam) return;
    const label = grant.display_name || grant.email || grant.user_id;
    confirmMessage = `Revoke unused retake for ${label}?`;
    confirmAction = async () => {
      try {
        await revokeGrant(exam!.id, grant.id);
        toast.success('Grant revoked');
        await loadGrants();
        await loadGradebook();
      } catch (e: any) {
        toast.error(e.message);
      }
    };
    showConfirm = true;
  }

  function gradebookStatusBadge(s: string): string {
    switch (s) {
      case 'submitted':   return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
      case 'in_progress': return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400';
      case 'missed':      return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
      default:            return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400';
    }
  }

  // Lazy-load gradebook + grants when the tab opens.
  $effect(() => {
    if (activeView === 'gradebook' && exam && !gradebookLoading && gradebook?.exam_id !== exam.id) {
      loadGradebook();
      loadGrants();
    }
  });

  // ── AI generation panel (Phase 3) ──────────────────────────────────
  // Editable copies of the candidates + a "selected" set keyed by client_id.
  // The admin tweaks text/options/correct flags inline before adding.
  let aiOpen = $state(false);
  let aiTopic = $state('');
  let aiNMcq = $state('5');
  let aiNTf = $state('3');
  let aiGenerating = $state(false);
  let aiAdding = $state(false);
  let aiCandidates = $state<CandidateQuestion[]>([]);
  let aiSelected = $state<Set<string>>(new Set());
  let aiDropped = $state(0);
  let aiChunksUsed = $state<number | null>(null);

  // Input mode toggle inside the panel: "chat" lets the admin type
  // natural-language requests (agent endpoint with tool calls); "form"
  // is the original structured input. Both produce candidates into the
  // same list below — only the input UI swaps.
  type AIInputMode = 'chat' | 'form';
  let aiMode = $state<AIInputMode>('chat');

  function resetAiPanel() {
    aiCandidates = [];
    aiSelected = new Set();
    aiDropped = 0;
    aiChunksUsed = null;
    agentHistory = [];
    agentInput = '';
    agentLastAssistant = '';
  }

  // ── Agent (Phase 5) ──────────────────────────────────────────────
  // Chat-style interaction layered on top of the same candidate panel.
  // History is held client-side; the server is stateless and only sees
  // the current user turn + the prior history we send.
  let agentInput = $state('');
  let agentSending = $state(false);
  let agentHistory = $state<AgentHistoryMessage[]>([]);
  let agentLastAssistant = $state('');
  let agentTextHistory = $derived(
    agentHistory.filter(
      (m) => (m.role === 'user' || m.role === 'assistant') && m.content,
    ),
  );

  async function handleAgentSend() {
    if (!exam) return;
    const msg = agentInput.trim();
    if (!msg) return;
    agentSending = true;
    try {
      const res = await callExamAgent(exam.id, {
        user_message: msg,
        history: agentHistory,
      });
      agentHistory = [...agentHistory, ...res.appended_history];
      agentLastAssistant = res.assistant_message || '';

      if (res.candidates.length) {
        // Append new candidates to the panel (keep prior ones so the
        // admin can compare or accumulate across turns).
        const next = [...aiCandidates, ...res.candidates];
        aiCandidates = next;
        // Pre-select the newly added ones — easier to "add all" workflow.
        const justAdded = new Set(res.candidates.map((c) => c.client_id));
        aiSelected = new Set([...aiSelected, ...justAdded]);
        aiDropped += res.dropped;
        toast.success(`Added ${res.candidates.length} candidate${res.candidates.length === 1 ? '' : 's'}`);
      }
      agentInput = '';
    } catch (e: any) {
      toast.error(e.message || 'Agent failed');
    } finally {
      agentSending = false;
    }
  }

  function handleAgentKeydown(e: KeyboardEvent) {
    // Enter sends, Shift+Enter inserts a newline (matches chat conventions).
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      handleAgentSend();
    }
  }

  function toggleAiSelect(clientId: string) {
    const next = new Set(aiSelected);
    if (next.has(clientId)) next.delete(clientId);
    else next.add(clientId);
    aiSelected = next;
  }

  async function handleAiGenerate() {
    if (!exam) return;
    const topic = aiTopic.trim();
    if (!topic) { toast.error('Topic is required'); return; }
    const nMcq = parseInt(aiNMcq, 10) || 0;
    const nTf = parseInt(aiNTf, 10) || 0;
    if (nMcq + nTf <= 0) { toast.error('Ask for at least one question'); return; }
    if (nMcq + nTf > 30) { toast.error('Cap is 30 questions per call'); return; }

    aiGenerating = true;
    try {
      const result = await generateQuestions(exam.id, { topic, n_mcq: nMcq, n_tf: nTf });
      aiCandidates = result.candidates;
      aiDropped = result.dropped;
      aiChunksUsed = result.chunks_used;
      // Pre-select everything so the common case is one-click "add all".
      aiSelected = new Set(result.candidates.map((c) => c.client_id));
      if (!result.candidates.length) {
        toast.error('No usable candidates returned. Try a different topic.');
      } else if (result.dropped > 0) {
        toast.warning(`${result.candidates.length} candidates returned; ${result.dropped} dropped (bad shape).`);
      } else {
        toast.success(`${result.candidates.length} candidates ready for review.`);
      }
    } catch (e: any) {
      toast.error(e.message || 'Generation failed');
    } finally {
      aiGenerating = false;
    }
  }

  function aiCandidateToggleCorrect(c: CandidateQuestion, optIdx: number) {
    if (c.type === 'true_false') {
      // Single correct: flip exactly one.
      c.options = c.options.map((o, i) => ({ ...o, is_correct: i === optIdx }));
    } else {
      c.options[optIdx].is_correct = !c.options[optIdx].is_correct;
    }
    // Force reactivity (Svelte 5 tracks deep mutations via $state, but
    // explicitly reassigning the array also covers Svelte 4 holdouts).
    aiCandidates = [...aiCandidates];
  }

  function aiCandidateValid(c: CandidateQuestion): boolean {
    if (!c.text.trim()) return false;
    if (c.options.some((o) => !o.text.trim())) return false;
    if (c.type === 'mcq') return c.options.some((o) => o.is_correct);
    return c.options.filter((o) => o.is_correct).length === 1;
  }

  async function handleAiAddSelected() {
    if (!exam) return;
    const chosen = aiCandidates.filter((c) => aiSelected.has(c.client_id));
    if (!chosen.length) { toast.error('Select at least one candidate'); return; }
    const invalid = chosen.filter((c) => !aiCandidateValid(c));
    if (invalid.length) {
      toast.error(`${invalid.length} selected candidate(s) have invalid options. Fix or unselect.`);
      return;
    }

    aiAdding = true;
    try {
      await addQuestionsBulk(
        exam.id,
        chosen.map((c) => ({
          type: c.type,
          text: c.text.trim(),
          explanation: c.explanation.trim() || undefined,
          options: c.options.map((o) => ({
            text: o.text.trim(),
            is_correct: o.is_correct,
          })),
        })),
      );
      toast.success(`Added ${chosen.length} question${chosen.length === 1 ? '' : 's'}`);
      // Drop the just-added ones from the candidate list so admin can
      // keep tweaking the rest, or generate more.
      aiCandidates = aiCandidates.filter((c) => !aiSelected.has(c.client_id));
      aiSelected = new Set();
      await loadExam();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      aiAdding = false;
    }
  }

  // ── Loading ────────────────────────────────────────────────────────

  onMount(async () => {
    if (!$authStore.roles.includes('super_admin') && !$authStore.roles.includes('admin')) {
      goto('/chat');
      return;
    }
    await loadExam();
    loading = false;
  });

  async function loadExam() {
    try {
      exam = await getExam(examId);
      // Auto-select the first question if none selected
      if (!selectedQuestionId && exam.questions.length) {
        selectQuestion(exam.questions[0].id);
      } else if (selectedQuestionId) {
        // refresh the working copy against new server data
        const found = exam.questions.find((q) => q.id === selectedQuestionId);
        if (found) selectQuestion(found.id);
      }
    } catch (e: any) {
      toast.error(e.message || 'Failed to load exam');
    }
  }

  let isDraft = $derived(exam?.state === 'draft');
  let isPublished = $derived(exam?.state === 'published');

  // ── Question selection ────────────────────────────────────────────

  function selectQuestion(qid: string) {
    if (!exam) return;
    if (workingDirty && working && !confirm('Discard unsaved question changes?')) return;
    const q = exam.questions.find((x) => x.id === qid);
    if (!q) return;
    selectedQuestionId = qid;
    working = {
      id: q.id,
      type: q.type,
      text: q.text,
      explanation: q.explanation ?? '',
      options: q.options.map((o) => ({ text: o.text, is_correct: o.is_correct })),
    };
    workingDirty = false;
  }

  function markDirty() { workingDirty = true; }

  // ── Add question ──────────────────────────────────────────────────

  async function addBlankMcq() {
    if (!exam) return;
    saving = true;
    try {
      const q = await addQuestion(exam.id, {
        type: 'mcq',
        text: 'New question',
        options: [
          { text: 'Option A', is_correct: true },
          { text: 'Option B', is_correct: false },
          { text: 'Option C', is_correct: false },
          { text: 'Option D', is_correct: false },
        ],
      });
      await loadExam();
      selectQuestion(q.id);
      toast.success('Question added');
    } catch (e: any) { toast.error(e.message); }
    finally { saving = false; }
  }

  async function addBlankTrueFalse() {
    if (!exam) return;
    saving = true;
    try {
      const q = await addQuestion(exam.id, {
        type: 'true_false',
        text: 'New true/false statement',
        options: [
          { text: 'True', is_correct: true },
          { text: 'False', is_correct: false },
        ],
      });
      await loadExam();
      selectQuestion(q.id);
      toast.success('Question added');
    } catch (e: any) { toast.error(e.message); }
    finally { saving = false; }
  }

  // ── Save / delete the working question ────────────────────────────

  async function saveWorking() {
    if (!exam || !working) return;
    if (!working.text.trim()) { toast.error('Question text cannot be empty'); return; }
    if (working.type === 'mcq') {
      if (!working.options.some((o) => o.is_correct)) {
        toast.error('At least one MCQ option must be correct'); return;
      }
    } else {
      const correct = working.options.filter((o) => o.is_correct).length;
      if (correct !== 1) { toast.error('True/False needs exactly one correct option'); return; }
    }
    if (working.options.some((o) => !o.text.trim())) {
      toast.error('Option text cannot be empty'); return;
    }

    saving = true;
    try {
      await updateQuestion(exam.id, working.id, {
        text: working.text.trim(),
        explanation: working.explanation.trim(),
        options: working.options.map((o) => ({
          text: o.text.trim(),
          is_correct: o.is_correct,
        })),
      });
      workingDirty = false;
      await loadExam();
      toast.success('Question saved');
    } catch (e: any) { toast.error(e.message); }
    finally { saving = false; }
  }

  function handleDeleteQuestion() {
    if (!exam || !selectedQuestionId) return;
    confirmMessage = 'Delete this question? Other questions will renumber.';
    confirmAction = async () => {
      try {
        await deleteQuestion(exam!.id, selectedQuestionId!);
        const idx = exam!.questions.findIndex((q) => q.id === selectedQuestionId);
        await loadExam();
        // Pick a neighbor to select if possible
        const next = exam!.questions[idx] || exam!.questions[idx - 1];
        if (next) selectQuestion(next.id);
        else { selectedQuestionId = null; working = null; }
        toast.success('Question deleted');
      } catch (e: any) { toast.error(e.message); }
    };
    showConfirm = true;
  }

  // ── Exam meta save ───────────────────────────────────────────────

  function openMetaEditor() {
    if (!exam) return;
    editTitle = exam.title;
    editDescription = exam.description ?? '';
    editDeadline = utcIsoToLocalInput(exam.deadline_at);
    editTimeLimit = exam.time_limit_minutes != null ? `${exam.time_limit_minutes}` : '';
    metaOpen = true;
  }

  async function saveMeta() {
    if (!exam) return;
    const body: Record<string, any> = {};
    if (isDraft) {
      const t = editTitle.trim();
      if (!t) { toast.error('Title cannot be empty'); return; }
      body.title = t;
      body.description = editDescription.trim();
      const tlRaw = editTimeLimit.trim().toLowerCase();
      if (tlRaw === '' || tlRaw === 'none' || tlRaw === 'untimed') {
        body.time_limit_minutes = null;
      } else {
        const n = parseInt(tlRaw, 10);
        if (!Number.isFinite(n) || n < 1 || n > 1440) {
          toast.error('Time limit must be 1–1440 min, or blank'); return;
        }
        body.time_limit_minutes = n;
      }
    }
    if (editDeadline) {
      body.deadline_at = localInputToUtcIso(editDeadline);
      if (new Date(body.deadline_at).getTime() <= Date.now()) {
        toast.error('Deadline must be in the future'); return;
      }
    }

    saving = true;
    try {
      const updated = await updateExam(exam.id, body);
      exam = updated;
      metaOpen = false;
      toast.success('Saved');
    } catch (e: any) { toast.error(e.message); }
    finally { saving = false; }
  }

  // ── Publish + delete the exam ────────────────────────────────────

  function handlePublish() {
    if (!exam) return;
    if (!exam.questions.length) {
      toast.error('Add at least one question before publishing'); return;
    }
    confirmMessage =
      `Publish "${exam.title}"? Once published, questions and answers are locked. ` +
      `You can extend the deadline and grant retakes (later phase), but you can't ` +
      `edit questions. Cancel to keep editing.`;
    confirmAction = async () => {
      try {
        const updated = await publishExam(exam!.id);
        exam = updated;
        toast.success('Exam published');
      } catch (e: any) { toast.error(e.message); }
    };
    showConfirm = true;
  }

  function handleDeleteExam() {
    if (!exam) return;
    confirmMessage = `Delete exam "${exam.title}"? Submissions are kept; the exam disappears from listings.`;
    confirmAction = async () => {
      try {
        await deleteExam(exam!.id);
        toast.success('Exam deleted');
        goto(`/admin/courses/${encodeURIComponent(courseId)}?tab=exams`);
      } catch (e: any) { toast.error(e.message); }
    };
    showConfirm = true;
  }

  // ── Helpers ──────────────────────────────────────────────────────

  function stateBadge(s: string): string {
    switch (s) {
      case 'draft':     return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300';
      case 'published': return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
      case 'closed':    return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
      case 'archived':  return 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500';
      default:          return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300';
    }
  }

  function questionPreview(q: ExamQuestion): string {
    const stem = q.text.length > 60 ? q.text.slice(0, 60) + '…' : q.text;
    return stem;
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->

<!-- ═══ CONFIRM DIALOG ═══ -->
{#if showConfirm}
  <div class="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4"
       onclick={() => showConfirm = false}>
    <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-xl max-w-md w-full p-6"
         onclick={(e) => e.stopPropagation()}>
      <p class="text-sm text-gray-700 dark:text-gray-300 mb-5 whitespace-pre-line">{confirmMessage}</p>
      <div class="flex gap-2 justify-end">
        <button onclick={() => showConfirm = false}
                class="px-3.5 py-1.5 text-sm rounded-full border border-gray-200 dark:border-gray-700
                       text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition">
          Cancel
        </button>
        <button onclick={async () => { showConfirm = false; await confirmAction?.(); }}
                class="px-3.5 py-1.5 text-sm rounded-full bg-blue-600 text-white hover:bg-blue-700 transition">
          Confirm
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- ═══ ATTEMPT DETAIL DRAWER ═══ -->
{#if attemptDetail}
  <div class="fixed inset-0 bg-black/50 z-[55] flex items-stretch justify-end"
       onclick={() => { if (!savingOverride) closeAttemptDrawer(); }}>
    <div class="bg-white dark:bg-gray-900 w-full max-w-2xl h-full overflow-y-auto shadow-xl border-l border-gray-200 dark:border-gray-800 flex flex-col"
         onclick={(e) => e.stopPropagation()}>

      <!-- Header -->
      <div class="px-5 py-4 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between gap-3 sticky top-0 bg-white/95 dark:bg-gray-900/95 backdrop-blur z-10">
        <div class="min-w-0">
          <h2 class="text-base font-semibold text-gray-900 dark:text-white truncate">
            {attemptDetail.display_name || attemptDetail.email || attemptDetail.user_id}
          </h2>
          <p class="text-[11px] text-gray-500 dark:text-gray-400">
            {attemptDetail.submitted_at
              ? `Submitted ${new Date(attemptDetail.submitted_at).toLocaleString()}`
              : 'In progress'}
          </p>
        </div>
        <button onclick={closeAttemptDrawer}
                disabled={savingOverride}
                aria-label="Close attempt drawer"
                class="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 disabled:opacity-50">
          <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <!-- Score + override -->
      <div class="px-5 py-4 border-b border-gray-100 dark:border-gray-800">
        <div class="flex items-baseline gap-3">
          <div class="text-3xl font-bold text-gray-900 dark:text-white">
            {attemptDetail.score_pct !== null ? `${Math.round(attemptDetail.score_pct)}%` : '—'}
          </div>
          <div class="text-sm text-gray-500 dark:text-gray-400">
            {attemptDetail.score_raw?.toFixed(2) ?? '-'} / {attemptDetail.total_points ?? '-'}
          </div>
          {#if attemptDetail.manual_override_score !== null}
            <span class="px-1.5 py-0 rounded text-[10px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
              override
            </span>
          {/if}
        </div>
        {#if attemptDetail.manual_override_score !== null && attemptDetail.auto_score_raw !== null}
          <p class="text-[11px] text-gray-500 dark:text-gray-400 mt-1">
            Auto: {attemptDetail.auto_score_raw.toFixed(2)} / {attemptDetail.total_points}
            {#if attemptDetail.override_at}
              — overridden {new Date(attemptDetail.override_at).toLocaleString()}
            {/if}
          </p>
        {/if}

        <div class="mt-4 grid grid-cols-1 sm:grid-cols-[1fr_2fr_auto] gap-2">
          <input type="text" bind:value={overrideRaw}
                 placeholder="Raw score (e.g. 7) or blank to clear"
                 class="px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                        bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                        focus:ring-1 focus:ring-blue-500 transition" />
          <input type="text" bind:value={overrideReason}
                 placeholder="Reason (audit log)"
                 class="px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                        bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                        focus:ring-1 focus:ring-blue-500 transition" />
          <button onclick={handleSaveOverride} disabled={savingOverride || attemptDetail.submitted_at === null}
                  class="px-3 py-2 text-sm rounded-lg bg-purple-600 text-white hover:bg-purple-700 transition
                         font-medium disabled:opacity-50 whitespace-nowrap">
            {savingOverride ? 'Saving…' : 'Save override'}
          </button>
        </div>
        <p class="text-[11px] text-gray-400 mt-1">
          Sets the student's final score. Auto-graded score is preserved unchanged. Leave blank to clear.
        </p>
      </div>

      <!-- Per-question review -->
      <div class="flex-1 overflow-y-auto px-5 py-4 space-y-3">
        {#each attemptDetail.review as r, idx (r.question_id)}
          <article class="rounded-2xl border
                          {r.is_correct
                            ? 'border-green-200 dark:border-green-900/40 bg-green-50/30 dark:bg-green-900/10'
                            : r.partial_score > 0
                              ? 'border-amber-200 dark:border-amber-900/40 bg-amber-50/30 dark:bg-amber-900/10'
                              : 'border-red-200 dark:border-red-900/40 bg-red-50/30 dark:bg-red-900/10'}
                          p-4">
            <div class="flex items-center justify-between gap-2 mb-2">
              <span class="text-[11px] font-mono text-gray-400">Q{idx + 1}</span>
              <span class="text-xs font-medium
                           {r.is_correct
                             ? 'text-green-700 dark:text-green-400'
                             : r.partial_score > 0
                               ? 'text-amber-700 dark:text-amber-400'
                               : 'text-red-700 dark:text-red-400'}">
                {r.is_correct
                  ? 'Correct (1.00)'
                  : r.partial_score > 0
                    ? `Partial (${r.partial_score.toFixed(2)})`
                    : 'Incorrect (0.00)'}
              </span>
            </div>
            <p class="text-sm text-gray-900 dark:text-white whitespace-pre-line mb-2">{r.text}</p>
            <div class="space-y-1">
              {#each r.options as opt (opt.id)}
                {@const wasSelected = r.selected_option_ids.includes(opt.id)}
                <div class="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-xs
                            {opt.is_correct
                              ? 'border-green-300 bg-green-50 dark:border-green-700 dark:bg-green-900/20'
                              : wasSelected
                                ? 'border-red-300 bg-red-50 dark:border-red-700 dark:bg-red-900/20'
                                : 'border-gray-200 dark:border-gray-700'}">
                  <span class="text-gray-700 dark:text-gray-300 flex-1 truncate">{opt.text}</span>
                  {#if wasSelected}
                    <span class="text-[10px] text-blue-600 dark:text-blue-400 shrink-0">selected</span>
                  {/if}
                  {#if opt.is_correct}
                    <span class="text-[10px] text-green-700 dark:text-green-400 font-medium shrink-0">correct</span>
                  {/if}
                </div>
              {/each}
            </div>
          </article>
        {/each}
      </div>
    </div>
  </div>
{/if}

<!-- ═══ AI GENERATE PANEL ═══ -->
{#if aiOpen}
  <div class="fixed inset-0 bg-black/50 z-[55] flex items-stretch justify-end"
       onclick={() => { if (!aiGenerating && !aiAdding) aiOpen = false; }}>
    <div class="bg-white dark:bg-gray-900 w-full max-w-2xl h-full overflow-y-auto shadow-xl border-l border-gray-200 dark:border-gray-800 flex flex-col"
         onclick={(e) => e.stopPropagation()}>

      <!-- Header -->
      <div class="px-5 py-4 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between gap-3 sticky top-0 bg-white/95 dark:bg-gray-900/95 backdrop-blur z-10">
        <div>
          <h2 class="text-base font-semibold text-gray-900 dark:text-white inline-flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-purple-600 dark:text-purple-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polygon points="12 2 15 8 22 9 17 14 18 21 12 17 6 21 7 14 2 9 9 8 12 2" />
            </svg>
            Generate questions with AI
          </h2>
          <p class="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
            Grounded on this course's documents. Review and edit before adding.
          </p>
        </div>
        <button onclick={() => { aiOpen = false; resetAiPanel(); aiTopic = ''; }}
                disabled={aiGenerating || aiAdding}
                aria-label="Close AI panel"
                class="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 disabled:opacity-50">
          <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <!-- Mode tabs: chat (agent) vs structured form -->
      <div class="px-5 pt-3 border-b border-gray-100 dark:border-gray-800">
        <div class="flex items-center gap-1 -mb-px">
          <button onclick={() => aiMode = 'chat'}
                  class="px-3 py-2 text-xs font-medium transition border-b-2
                         {aiMode === 'chat'
                           ? 'border-purple-600 text-purple-600 dark:border-purple-400 dark:text-purple-400'
                           : 'border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'}">
            Chat
          </button>
          <button onclick={() => aiMode = 'form'}
                  class="px-3 py-2 text-xs font-medium transition border-b-2
                         {aiMode === 'form'
                           ? 'border-purple-600 text-purple-600 dark:border-purple-400 dark:text-purple-400'
                           : 'border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'}">
            Quick form
          </button>
        </div>
      </div>

      {#if aiMode === 'chat'}
        <!-- Chat with AI (agent) -->
        <div class="px-5 py-4 border-b border-gray-100 dark:border-gray-800 space-y-3">
          {#if agentTextHistory.length}
            <div class="space-y-2 max-h-64 overflow-y-auto pr-1">
              {#each agentTextHistory as m, i (i)}
                <div class="text-xs px-3 py-2 rounded-lg
                            {m.role === 'user'
                              ? 'bg-purple-50 dark:bg-purple-900/20 text-purple-900 dark:text-purple-100'
                              : 'bg-gray-50 dark:bg-gray-800 text-gray-800 dark:text-gray-200'}">
                  <span class="text-[10px] uppercase tracking-wider opacity-60 block mb-0.5">
                    {m.role === 'user' ? 'You' : 'Assistant'}
                  </span>
                  <p class="whitespace-pre-line">{m.content}</p>
                </div>
              {/each}
            </div>
          {:else}
            <p class="text-[11px] text-gray-400">
              Describe what questions you want — e.g. "Make 5 MCQs and 2 T/Fs about photosynthesis."
              The assistant drafts candidates that appear below for you to review and edit.
            </p>
          {/if}

          <div class="flex items-end gap-2">
            <textarea bind:value={agentInput}
                      onkeydown={handleAgentKeydown}
                      rows="2"
                      disabled={agentSending}
                      placeholder='e.g. "Make me 5 MCQs and 2 T/Fs about photosynthesis"'
                      class="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                             bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                             focus:ring-1 focus:ring-purple-500 transition resize-y disabled:opacity-50"></textarea>
            <button onclick={handleAgentSend} disabled={agentSending || !agentInput.trim()}
                    class="px-3 py-2 text-sm rounded-lg bg-purple-600 text-white hover:bg-purple-700 transition
                           font-medium disabled:opacity-50 self-end">
              {agentSending ? '…' : 'Send'}
            </button>
          </div>
          <p class="text-[10px] text-gray-400">
            Enter to send, Shift+Enter for a newline. Candidates appear below.
          </p>
        </div>
      {:else}
        <!-- Generation form -->
        <div class="px-5 py-4 border-b border-gray-100 dark:border-gray-800 space-y-3">
          <label class="block">
            <span class="text-[11px] text-gray-400 block mb-1">Topic / instruction</span>
            <textarea bind:value={aiTopic}
                      rows="2"
                      placeholder="e.g. Photosynthesis — focus on the light-dependent reactions"
                      class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                             bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                             focus:ring-1 focus:ring-purple-500 transition resize-y"></textarea>
          </label>
          <div class="grid grid-cols-3 gap-2">
            <label>
              <span class="text-[11px] text-gray-400 block mb-1">MCQ count</span>
              <input type="text" bind:value={aiNMcq}
                     class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                            bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                            focus:ring-1 focus:ring-purple-500 transition" />
            </label>
            <label>
              <span class="text-[11px] text-gray-400 block mb-1">T/F count</span>
              <input type="text" bind:value={aiNTf}
                     class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                            bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                            focus:ring-1 focus:ring-purple-500 transition" />
            </label>
            <button onclick={handleAiGenerate} disabled={aiGenerating}
                    class="self-end px-3 py-2 text-sm rounded-lg bg-purple-600 text-white hover:bg-purple-700
                           transition font-medium disabled:opacity-50">
              {aiGenerating ? 'Generating…' : 'Generate'}
            </button>
          </div>
          {#if aiChunksUsed !== null}
            <p class="text-[11px] text-gray-500 dark:text-gray-400">
              Grounded on {aiChunksUsed} retrieved chunk{aiChunksUsed === 1 ? '' : 's'}.
              {aiDropped > 0 ? `${aiDropped} dropped (off-spec).` : ''}
            </p>
          {/if}
        </div>
      {/if}

      <!-- Candidates list -->
      <div class="flex-1 overflow-y-auto">
        {#if aiCandidates.length === 0}
          <div class="text-center text-sm text-gray-400 py-12 px-5">
            {aiChunksUsed !== null
              ? 'No candidates produced. Try a different topic or different counts.'
              : 'Generate candidates above. They appear here for review.'}
          </div>
        {:else}
          <div class="px-5 py-4 space-y-3">
            {#each aiCandidates as cand (cand.client_id)}
              {@const checked = aiSelected.has(cand.client_id)}
              {@const valid = aiCandidateValid(cand)}
              <article class="rounded-2xl border p-4 transition
                              {checked
                                ? 'border-purple-300 dark:border-purple-700 bg-purple-50/30 dark:bg-purple-900/10'
                                : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850'}">
                <header class="flex items-start gap-2 mb-3">
                  <input type="checkbox" checked={checked}
                         onchange={() => toggleAiSelect(cand.client_id)}
                         class="mt-1 size-4 shrink-0 accent-purple-600" />
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                      <span class="px-1.5 py-0 rounded text-[9px] font-medium
                                    bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                        {cand.type === 'mcq' ? 'MCQ' : 'T/F'}
                      </span>
                      {#if !valid}
                        <span class="px-1.5 py-0 rounded text-[9px] font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
                          fix before adding
                        </span>
                      {/if}
                      {#if cand.source_chunks.length}
                        <span class="text-[10px] text-gray-400 truncate">
                          src: {cand.source_chunks.map((s) => `${s.doc_title} p.${s.page_num}`).join('; ')}
                        </span>
                      {/if}
                    </div>
                  </div>
                </header>

                <textarea bind:value={cand.text}
                          rows="2"
                          placeholder="Question stem"
                          class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                                 bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                                 focus:ring-1 focus:ring-purple-500 transition resize-y"></textarea>

                <div class="mt-2 space-y-1.5">
                  {#each cand.options as opt, i (i)}
                    <div class="flex items-center gap-2">
                      <input type={cand.type === 'true_false' ? 'radio' : 'checkbox'}
                             name="ai-correct-{cand.client_id}"
                             checked={opt.is_correct}
                             onchange={() => aiCandidateToggleCorrect(cand, i)}
                             class="size-4 shrink-0 accent-green-600" />
                      <input type="text" bind:value={opt.text}
                             class="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                                    bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                                    focus:ring-1 focus:ring-purple-500 transition" />
                    </div>
                  {/each}
                </div>

                <label class="block mt-2">
                  <span class="text-[11px] text-gray-400 block mb-1">Explanation</span>
                  <textarea bind:value={cand.explanation}
                            rows="2"
                            class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                                   bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                                   focus:ring-1 focus:ring-purple-500 transition resize-y"></textarea>
                </label>
              </article>
            {/each}
          </div>
        {/if}
      </div>

      <!-- Footer -->
      <div class="px-5 py-3 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between gap-3">
        <span class="text-[11px] text-gray-500 dark:text-gray-400">
          {aiSelected.size} of {aiCandidates.length} selected
        </span>
        <div class="flex items-center gap-2">
          <button onclick={() => { aiOpen = false; resetAiPanel(); aiTopic = ''; }}
                  disabled={aiGenerating || aiAdding}
                  class="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                         text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition
                         disabled:opacity-50">
            Close
          </button>
          <button onclick={handleAiAddSelected}
                  disabled={aiAdding || aiSelected.size === 0}
                  class="px-3 py-1.5 text-sm rounded-lg bg-purple-600 text-white hover:bg-purple-700
                         transition font-medium disabled:opacity-50">
            {aiAdding ? 'Adding…' : `Add ${aiSelected.size} to exam`}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- ═══ MAIN ═══ -->
<div class="flex flex-col h-full">
  <div class="flex-1 overflow-y-auto">
    <div class="max-w-6xl mx-auto w-full px-4 pt-4 pb-8 space-y-4">

      <!-- Breadcrumb / header -->
      <div class="flex items-start justify-between gap-3 flex-wrap">
        <div class="min-w-0">
          <button onclick={() => goto(`/admin/courses/${encodeURIComponent(courseId)}?tab=exams`)}
                  class="inline-flex items-center gap-1.5 text-xs font-medium
                         text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition">
            <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            Back to course
          </button>
          <div class="flex items-center gap-2 mt-1 flex-wrap">
            <h1 class="text-2xl font-bold text-gray-900 dark:text-white truncate">
              {exam?.title || (loading ? 'Loading…' : 'Exam')}
            </h1>
            {#if exam}
              <span class="px-2 py-0.5 rounded-full text-[10px] font-medium {stateBadge(exam.state)}">
                {exam.state}
              </span>
            {/if}
          </div>
          {#if exam}
            <div class="flex items-center gap-3 mt-1 text-[11px] text-gray-500 dark:text-gray-400 flex-wrap">
              <span>Deadline: {formatLocalDeadline(exam.deadline_at)}</span>
              <span>·</span>
              <span>{exam.time_limit_minutes ? `${exam.time_limit_minutes} min` : 'Untimed'}</span>
              <span>·</span>
              <span>{exam.questions.length} question{exam.questions.length === 1 ? '' : 's'}</span>
            </div>
            {#if exam.description}
              <p class="text-sm text-gray-600 dark:text-gray-400 mt-2 max-w-2xl">{exam.description}</p>
            {/if}
          {/if}
        </div>
        <div class="flex items-center gap-2 shrink-0">
          {#if exam}
            <button onclick={openMetaEditor}
                    class="text-xs px-3 py-1.5 rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200
                           dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 transition font-medium">
              {isDraft ? 'Edit details' : 'Extend deadline'}
            </button>
            {#if isDraft}
              <button onclick={() => { aiOpen = true; }}
                      class="text-xs px-3 py-1.5 rounded-lg bg-purple-600 text-white hover:bg-purple-700
                             transition font-medium inline-flex items-center gap-1.5">
                <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="12 2 15 8 22 9 17 14 18 21 12 17 6 21 7 14 2 9 9 8 12 2" />
                </svg>
                Generate with AI
              </button>
              <button onclick={handlePublish}
                      class="text-xs px-3 py-1.5 rounded-lg bg-green-600 text-white hover:bg-green-700
                             transition font-medium">
                Publish
              </button>
            {/if}
            <button onclick={handleDeleteExam}
                    class="text-xs px-3 py-1.5 rounded-lg bg-red-50 text-red-700 hover:bg-red-100
                           dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/40 transition font-medium">
              Delete
            </button>
          {/if}
        </div>
      </div>

      <!-- ═══ META EDITOR (modal-ish drawer) ═══ -->
      {#if metaOpen && exam}
        <div class="rounded-2xl border border-blue-200 dark:border-blue-900/40 bg-blue-50/30 dark:bg-blue-900/10 p-5 space-y-3">
          <div class="text-[11px] font-medium text-blue-600 dark:text-blue-400 uppercase tracking-wider">
            {isDraft ? 'Edit exam details' : 'Adjust deadline'}
          </div>

          {#if isDraft}
            <input type="text" bind:value={editTitle} placeholder="Exam title"
                   class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                          bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                          focus:ring-1 focus:ring-blue-500 transition" />
            <textarea bind:value={editDescription} rows="2" placeholder="Description (optional)"
                      class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                             bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                             focus:ring-1 focus:ring-blue-500 transition resize-y"></textarea>
          {/if}

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <label class="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850">
              <span class="text-[11px] text-gray-400 shrink-0">Deadline</span>
              <input type="datetime-local" bind:value={editDeadline}
                     class="flex-1 text-sm bg-transparent outline-none text-gray-900 dark:text-white" />
            </label>
            {#if isDraft}
              <label class="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850">
                <span class="text-[11px] text-gray-400 shrink-0">Time limit (min)</span>
                <input type="text" bind:value={editTimeLimit} placeholder="60 or blank"
                       class="flex-1 text-sm bg-transparent outline-none text-gray-900 dark:text-white" />
              </label>
            {/if}
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <button onclick={() => metaOpen = false} disabled={saving}
                    class="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                           text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition
                           disabled:opacity-50">
              Cancel
            </button>
            <button onclick={saveMeta} disabled={saving}
                    class="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition
                           font-medium disabled:opacity-50">
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      {/if}

      {#if loading}
        <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 px-4 py-10 text-center text-gray-400 text-sm">
          Loading exam…
        </div>
      {:else if exam}

        <!-- ═══ VIEW TABS (only after publish) ═══ -->
        {#if !isDraft}
          <div class="flex items-center gap-1 border-b border-gray-200 dark:border-gray-700">
            <button onclick={() => activeView = 'editor'}
                    class="px-4 py-2 text-sm font-medium transition border-b-2 -mb-px
                           {activeView === 'editor'
                             ? 'border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400'
                             : 'border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'}">
              Questions · {exam.questions.length}
            </button>
            <button onclick={() => activeView = 'gradebook'}
                    class="px-4 py-2 text-sm font-medium transition border-b-2 -mb-px
                           {activeView === 'gradebook'
                             ? 'border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400'
                             : 'border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'}">
              Gradebook{gradebook ? ` · ${gradebook.total_enrolled}` : ''}
            </button>
          </div>
        {/if}

      {#if activeView === 'editor' || isDraft}
        <!-- ═══ QUESTION EDITOR — two-pane ═══ -->
        <div class="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-4">

          <!-- ─── Left: question list ─── -->
          <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-3 space-y-1.5">
            <div class="flex items-center justify-between mb-2 px-1">
              <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">Questions</div>
              <span class="text-[11px] text-gray-400">{exam.questions.length}</span>
            </div>

            {#if exam.questions.length === 0}
              <p class="text-xs text-gray-400 py-6 text-center">No questions yet.</p>
            {:else}
              {#each exam.questions as q, i (q.id)}
                <button onclick={() => selectQuestion(q.id)}
                        class="w-full text-left px-2.5 py-2 rounded-lg flex items-start gap-2 transition
                               {selectedQuestionId === q.id
                                 ? 'bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800'
                                 : 'hover:bg-gray-50 dark:hover:bg-gray-800 border border-transparent'}">
                  <span class="shrink-0 text-[10px] font-mono text-gray-400 mt-0.5">{i + 1}.</span>
                  <div class="flex-1 min-w-0">
                    <p class="text-xs text-gray-800 dark:text-gray-200 truncate">{questionPreview(q)}</p>
                    <span class="inline-block mt-1 px-1.5 py-0 rounded text-[9px] font-medium
                                  bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                      {q.type === 'mcq' ? 'MCQ' : 'T/F'}
                    </span>
                  </div>
                </button>
              {/each}
            {/if}

            {#if isDraft}
              <div class="pt-2 mt-2 border-t border-gray-100 dark:border-gray-800 space-y-1.5">
                <button onclick={addBlankMcq} disabled={saving}
                        class="w-full px-3 py-2 text-xs rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100
                               dark:bg-blue-900/20 dark:text-blue-400 dark:hover:bg-blue-900/40 transition
                               font-medium disabled:opacity-50">
                  + Add MCQ
                </button>
                <button onclick={addBlankTrueFalse} disabled={saving}
                        class="w-full px-3 py-2 text-xs rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100
                               dark:bg-purple-900/20 dark:text-purple-400 dark:hover:bg-purple-900/40 transition
                               font-medium disabled:opacity-50">
                  + Add True/False
                </button>
              </div>
            {:else}
              <p class="text-[10px] text-gray-400 px-1 pt-2">
                Questions are locked after publish.
              </p>
            {/if}
          </div>

          <!-- ─── Right: editor / preview ─── -->
          <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
            {#if !selectedQuestion || !working}
              <div class="text-center py-12 text-sm text-gray-400">
                {exam.questions.length === 0
                  ? (isDraft ? 'Add a question on the left to start.' : 'No questions on this exam.')
                  : 'Pick a question from the list.'}
              </div>
            {:else}
              <div class="flex items-center justify-between mb-4">
                <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">
                  Question · {working.type === 'mcq' ? 'Multiple choice (multi-correct)' : 'True / False'}
                </div>
                {#if isDraft}
                  <button onclick={handleDeleteQuestion} disabled={saving}
                          class="text-[11px] px-2.5 py-1 rounded-lg bg-red-50 text-red-700 hover:bg-red-100
                                 dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/40 transition
                                 font-medium disabled:opacity-50">
                    Delete question
                  </button>
                {/if}
              </div>

              <textarea bind:value={working.text} oninput={markDirty}
                        readonly={!isDraft}
                        rows="3"
                        placeholder="Question stem"
                        class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                               bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                               focus:ring-1 focus:ring-blue-500 transition resize-y
                               read-only:opacity-70"></textarea>

              <div class="mt-3 space-y-2">
                {#each working.options as opt, i (i)}
                  <div class="flex items-center gap-2">
                    <input type="checkbox" bind:checked={opt.is_correct}
                           onchange={markDirty}
                           disabled={!isDraft}
                           class="size-4 shrink-0 accent-green-600 disabled:opacity-50" />
                    <input type="text" bind:value={opt.text}
                           oninput={markDirty}
                           readonly={!isDraft}
                           placeholder={working.type === 'mcq' ? `Option ${i + 1}` : (i === 0 ? 'True' : 'False')}
                           class="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                                  bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                                  focus:ring-1 focus:ring-blue-500 transition read-only:opacity-70" />
                  </div>
                {/each}
              </div>

              <label class="block mt-4">
                <span class="text-[11px] text-gray-400 block mb-1">
                  Explanation (shown to students after the deadline)
                </span>
                <textarea bind:value={working.explanation} oninput={markDirty}
                          readonly={!isDraft}
                          rows="2"
                          class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                                 bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                                 focus:ring-1 focus:ring-blue-500 transition resize-y read-only:opacity-70"></textarea>
              </label>

              {#if isDraft}
                <div class="flex justify-end gap-2 mt-4">
                  <button onclick={() => selectQuestion(working!.id)} disabled={saving || !workingDirty}
                          class="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                                 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition
                                 disabled:opacity-50">
                    Reset
                  </button>
                  <button onclick={saveWorking} disabled={saving || !workingDirty}
                          class="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition
                                 font-medium disabled:opacity-50">
                    {saving ? 'Saving…' : 'Save question'}
                  </button>
                </div>
              {/if}
            {/if}
          </div>
        </div>

        {#if isPublished}
          <div class="rounded-2xl border border-amber-200 dark:border-amber-900/40 bg-amber-50/40 dark:bg-amber-900/10 px-4 py-3 text-xs text-amber-800 dark:text-amber-300">
            This exam is published. Questions and answers are locked. You can extend the deadline and grant retakes from the Gradebook tab.
          </div>
        {/if}

      {:else if activeView === 'gradebook'}
        <!-- ═══ GRADEBOOK ═══ -->

        <!-- Grants section -->
        <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
          <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-3">
            Grant retake
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-2">
            <input type="text" bind:value={grantIdentifier}
                   placeholder="Student email or display name"
                   class="px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                          bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                          focus:ring-1 focus:ring-blue-500 transition" />
            <input type="text" bind:value={grantReason}
                   placeholder="Reason (optional, audit log)"
                   class="px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                          bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                          focus:ring-1 focus:ring-blue-500 transition" />
            <button onclick={handleGrantRetake} disabled={granting}
                    class="px-3 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition
                           font-medium disabled:opacity-50 whitespace-nowrap">
              {granting ? 'Granting…' : 'Grant'}
            </button>
          </div>
          <p class="text-[11px] text-gray-400 mt-2">
            One unconsumed grant per student. The new attempt's score replaces the previous one.
          </p>

          {#if grants.filter((g) => !g.consumed).length}
            <div class="mt-4 pt-4 border-t border-gray-100 dark:border-gray-800 space-y-1.5">
              <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-2">
                Active grants · {grants.filter((g) => !g.consumed).length}
              </div>
              {#each grants.filter((g) => !g.consumed) as g (g.id)}
                <div class="flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-800">
                  <div class="min-w-0">
                    <p class="text-sm text-gray-900 dark:text-white truncate font-medium">
                      {g.display_name || g.email || g.user_id}
                    </p>
                    <p class="text-[10px] text-gray-400">
                      {new Date(g.granted_at).toLocaleString()}{g.reason ? ` — ${g.reason}` : ''}
                    </p>
                  </div>
                  <button onclick={() => handleRevokeGrant(g)}
                          class="text-[11px] px-2.5 py-1 rounded-lg bg-red-50 text-red-700 hover:bg-red-100
                                 dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/40 transition font-medium">
                    Revoke
                  </button>
                </div>
              {/each}
            </div>
          {/if}
        </div>

        <!-- Roster table -->
        <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
          <div class="flex items-center justify-between mb-3">
            <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">
              Roster{gradebook ? ` · ${gradebook.total_enrolled}` : ''}
            </div>
            {#if gradebook}
              {@const submitted = gradebook.rows.filter((r) => r.status === 'submitted')}
              {@const avg = submitted.length
                ? submitted.reduce((s, r) => s + (r.score_pct ?? 0), 0) / submitted.length
                : null}
              <span class="text-[11px] text-gray-500 dark:text-gray-400">
                {submitted.length} submitted{avg !== null ? ` · avg ${Math.round(avg)}%` : ''}
              </span>
            {/if}
          </div>

          {#if gradebookLoading}
            <p class="text-xs text-gray-400 py-8 text-center">Loading gradebook…</p>
          {:else if !gradebook || gradebook.rows.length === 0}
            <p class="text-xs text-gray-400 py-8 text-center">No students enrolled yet.</p>
          {:else}
            <div class="space-y-1.5">
              {#each gradebook.rows as r (r.user_id)}
                <button onclick={() => r.attempt_id && openAttempt(r.attempt_id)}
                        disabled={!r.attempt_id}
                        class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition
                               {r.attempt_id ? 'hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer' : 'cursor-default opacity-70'}
                               bg-white dark:bg-gray-850 border border-gray-100 dark:border-gray-800">
                  <div class="shrink-0 size-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                              flex items-center justify-center text-white text-[11px] font-bold uppercase">
                    {(r.display_name || r.email || '??').slice(0, 2).toUpperCase()}
                  </div>
                  <div class="flex-1 min-w-0">
                    <p class="text-sm text-gray-900 dark:text-white truncate font-medium">
                      {r.display_name || r.email || r.user_id}
                    </p>
                    <div class="flex items-center gap-1.5 mt-0.5 flex-wrap">
                      <span class="px-1.5 py-0 rounded text-[9px] font-medium {gradebookStatusBadge(r.status)}">
                        {r.status.replace('_', ' ')}
                      </span>
                      {#if r.attempt_count > 1}
                        <span class="text-[10px] text-gray-400">{r.attempt_count} attempts</span>
                      {/if}
                      {#if r.active_grants > 0}
                        <span class="px-1.5 py-0 rounded text-[9px] font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                          retake granted
                        </span>
                      {/if}
                      {#if r.manual_override}
                        <span class="px-1.5 py-0 rounded text-[9px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                          override
                        </span>
                      {/if}
                    </div>
                  </div>
                  <div class="text-right shrink-0">
                    {#if r.score_pct !== null}
                      <div class="text-sm font-semibold text-gray-900 dark:text-white">
                        {Math.round(r.score_pct)}%
                      </div>
                      <div class="text-[10px] text-gray-400">
                        {r.score_raw?.toFixed(1) ?? '-'} / {r.total_points ?? '-'}
                      </div>
                    {:else}
                      <div class="text-[10px] text-gray-400">—</div>
                    {/if}
                  </div>
                </button>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
      {/if}
    </div>
  </div>
</div>
