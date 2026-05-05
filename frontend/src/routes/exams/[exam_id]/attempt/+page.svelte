<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { toast } from 'svelte-sonner';

  import { authStore } from '$lib/stores/auth';
  import {
    getMyAttempt,
    autosaveResponse,
    submitAttempt,
    formatTimeRemaining,
    type AttemptDetail,
    type AttemptQuestion,
  } from '$lib/apis/exams';

  let examId = $derived(($page.params as Record<string, string>).exam_id);

  let attempt = $state<AttemptDetail | null>(null);
  let loading = $state(true);
  let submitting = $state(false);
  let confirmSubmit = $state(false);

  // Per-question selection. Tracked separately so we can debounce autosave
  // without forcing a server round-trip on every checkbox flip.
  let selections = $state<Record<string, string[]>>({});
  let savingFor = $state<Record<string, boolean>>({});
  let saveTimers = new Map<string, ReturnType<typeof setTimeout>>();

  // Live timer
  let timeRemaining = $state(0);
  let tickInterval: ReturnType<typeof setInterval> | null = null;
  let initialFetchAt = 0;

  onMount(async () => {
    if (!$authStore.authenticated) { goto('/auth'); return; }
    await load();
    loading = false;

    // Local clock keeps the timer ticking without spamming the API.
    tickInterval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - initialFetchAt) / 1000);
      const remaining = Math.max(0, (attempt?.time_remaining_seconds ?? 0) - elapsed);
      timeRemaining = remaining;
      if (remaining === 0 && attempt && !attempt.submitted_at && !submitting) {
        // Time's up: try to submit so the score is finalised. If it
        // fails (network, race), the backend's lazy-close will catch it
        // when the user revisits.
        autoSubmitOnTimeout();
      }
    }, 1000);
  });

  onDestroy(() => {
    if (tickInterval) clearInterval(tickInterval);
    for (const t of saveTimers.values()) clearTimeout(t);
    saveTimers.clear();
  });

  async function load() {
    try {
      const a = await getMyAttempt(examId);
      attempt = a;
      initialFetchAt = Date.now();
      timeRemaining = a.time_remaining_seconds;
      // Hydrate selections from server
      selections = {};
      for (const q of a.questions) selections[q.id] = [...q.selected_option_ids];
    } catch (e: any) {
      toast.error(e.message || 'Failed to load attempt');
      goto(`/exams/${examId}`);
    }
  }

  function toggleOption(q: AttemptQuestion, optionId: string) {
    const current = selections[q.id] ?? [];
    let next: string[];
    if (q.type === 'true_false') {
      // Single-select: replace.
      next = [optionId];
    } else {
      // MCQ multi-select: toggle membership.
      next = current.includes(optionId)
        ? current.filter((id) => id !== optionId)
        : [...current, optionId];
    }
    selections[q.id] = next;
    scheduleSave(q.id, next);
  }

  function scheduleSave(qid: string, next: string[]) {
    // Debounce per question: 400ms after the last change.
    const existing = saveTimers.get(qid);
    if (existing) clearTimeout(existing);
    const t = setTimeout(() => persistSave(qid, next), 400);
    saveTimers.set(qid, t);
  }

  async function persistSave(qid: string, next: string[]) {
    savingFor[qid] = true;
    try {
      await autosaveResponse(examId, qid, next);
    } catch (e: any) {
      // 410 = time expired; route to result and stop fighting.
      if (`${e.message}`.includes('410')) {
        toast.error('Time expired — submitting your answers.');
        goto(`/exams/${examId}/result`);
        return;
      }
      toast.error(`Save failed: ${e.message}`);
    } finally {
      savingFor[qid] = false;
    }
  }

  // Force-flush any pending debounced saves. Both the manual-submit
  // and the timer-expired paths must call this — without it, the last
  // 0–400ms of selection changes get dropped on submit and the student
  // is graded against an out-of-date answer.
  async function flushPendingSaves() {
    for (const [qid, t] of saveTimers) {
      clearTimeout(t);
      await persistSave(qid, selections[qid] ?? []);
    }
    saveTimers.clear();
  }

  async function flushSavesAndSubmit() {
    confirmSubmit = false;
    submitting = true;
    try {
      await flushPendingSaves();
      await submitAttempt(examId);
      toast.success('Submitted');
      goto(`/exams/${examId}/result`);
    } catch (e: any) {
      toast.error(e.message || 'Submit failed');
      submitting = false;
    }
  }

  async function autoSubmitOnTimeout() {
    submitting = true;
    try {
      // Flush first, then submit. If the network is down we still
      // navigate to /result; backend lazy-close will finalise on next
      // access regardless.
      await flushPendingSaves();
      await submitAttempt(examId);
    } catch {
      // Best-effort — lazy-close handles the rest.
    }
    goto(`/exams/${examId}/result`);
  }

  function answeredCount(): number {
    if (!attempt) return 0;
    return attempt.questions.filter((q) => (selections[q.id] ?? []).length > 0).length;
  }

  function timerColor(): string {
    if (timeRemaining > 300) return 'text-gray-700 dark:text-gray-200';
    if (timeRemaining > 60)  return 'text-amber-600 dark:text-amber-400';
    return 'text-red-600 dark:text-red-400';
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->

<div class="flex flex-col h-full">
  <!-- Sticky header: timer + submit -->
  {#if attempt}
    <div class="sticky top-0 z-30 bg-white/95 dark:bg-gray-900/95 backdrop-blur border-b border-gray-100 dark:border-gray-800">
      <div class="max-w-3xl mx-auto w-full px-4 py-3 flex items-center justify-between gap-3">
        <div class="min-w-0">
          <h1 class="text-sm font-semibold text-gray-900 dark:text-white truncate">{attempt.title}</h1>
          <p class="text-[11px] text-gray-500 dark:text-gray-400">
            {answeredCount()}/{attempt.questions.length} answered
          </p>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          {#if attempt.time_remaining_seconds > 0 || timeRemaining > 0 || attempt.due_at}
            <div class="text-right">
              <div class="text-base font-mono font-semibold {timerColor()}">
                {formatTimeRemaining(timeRemaining)}
              </div>
              <div class="text-[10px] uppercase tracking-wider text-gray-400">remaining</div>
            </div>
          {/if}
          <button onclick={() => confirmSubmit = true} disabled={submitting}
                  class="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition
                         font-semibold disabled:opacity-50 whitespace-nowrap">
            {submitting ? 'Submitting…' : 'Submit'}
          </button>
        </div>
      </div>
    </div>
  {/if}

  <div class="flex-1 overflow-y-auto">
    <div class="max-w-3xl mx-auto w-full px-4 pt-4 pb-12 space-y-4">

      {#if loading}
        <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 px-4 py-10 text-center text-gray-400 text-sm">
          Loading…
        </div>
      {:else if attempt}
        {#each attempt.questions as q, idx (q.id)}
          {@const selected = selections[q.id] ?? []}
          <article class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
            <header class="flex items-center justify-between gap-3 mb-3">
              <div class="flex items-center gap-2">
                <span class="text-[11px] font-mono text-gray-400">Q{idx + 1}</span>
                <span class="px-1.5 py-0 rounded text-[9px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                  {q.type === 'mcq' ? 'Multiple choice' : 'True / False'}
                </span>
                {#if q.type === 'mcq'}
                  <span class="text-[10px] text-gray-400">Select all that apply</span>
                {/if}
              </div>
              {#if savingFor[q.id]}
                <span class="text-[10px] text-gray-400">Saving…</span>
              {:else if selected.length > 0}
                <span class="text-[10px] text-green-600 dark:text-green-400">Saved</span>
              {/if}
            </header>

            <p class="text-sm text-gray-900 dark:text-white whitespace-pre-line mb-3">{q.text}</p>

            <div class="space-y-2">
              {#each q.options as opt (opt.id)}
                {@const checked = selected.includes(opt.id)}
                <button onclick={() => toggleOption(q, opt.id)}
                        type="button"
                        class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border transition text-left
                               {checked
                                 ? 'border-blue-300 bg-blue-50 dark:border-blue-700 dark:bg-blue-900/20'
                                 : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'}">
                  <span class="shrink-0 size-5 rounded-{q.type === 'mcq' ? 'md' : 'full'} border-2 flex items-center justify-center
                               {checked
                                 ? 'border-blue-600 bg-blue-600 text-white'
                                 : 'border-gray-300 dark:border-gray-600'}">
                    {#if checked}
                      <svg xmlns="http://www.w3.org/2000/svg" class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    {/if}
                  </span>
                  <span class="text-sm text-gray-800 dark:text-gray-200">{opt.text}</span>
                </button>
              {/each}
            </div>
          </article>
        {/each}

        <div class="rounded-2xl border border-blue-200 dark:border-blue-900/40 bg-blue-50/30 dark:bg-blue-900/10 px-4 py-3 text-xs text-blue-800 dark:text-blue-300">
          Answers save automatically as you go. When you're ready, click <strong>Submit</strong> at the top of the page —
          you can only submit once.
        </div>
      {/if}
    </div>
  </div>
</div>

<!-- Confirm submit -->
{#if confirmSubmit && attempt}
  <div class="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4"
       onclick={() => confirmSubmit = false}>
    <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-xl max-w-sm w-full p-6"
         onclick={(e) => e.stopPropagation()}>
      <h2 class="text-base font-semibold text-gray-900 dark:text-white mb-2">Submit your answers?</h2>
      <p class="text-sm text-gray-700 dark:text-gray-300 mb-1">
        You have answered <strong>{answeredCount()}</strong> of <strong>{attempt.questions.length}</strong>.
      </p>
      <p class="text-xs text-gray-500 dark:text-gray-400 mb-5">
        Once submitted, you can't change your answers. Correct answers and explanations
        unlock for everyone after the deadline.
      </p>
      <div class="flex gap-2 justify-end">
        <button onclick={() => confirmSubmit = false}
                class="px-3.5 py-1.5 text-sm rounded-full border border-gray-200 dark:border-gray-700
                       text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition">
          Keep editing
        </button>
        <button onclick={flushSavesAndSubmit}
                class="px-3.5 py-1.5 text-sm rounded-full bg-blue-600 text-white hover:bg-blue-700 transition">
          Submit
        </button>
      </div>
    </div>
  </div>
{/if}
