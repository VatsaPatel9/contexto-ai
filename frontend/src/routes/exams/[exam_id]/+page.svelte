<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { toast } from 'svelte-sonner';

  import { authStore } from '$lib/stores/auth';
  import {
    getStudentExamSummary,
    startAttempt,
    formatLocalDeadline,
    type StudentExamSummary,
  } from '$lib/apis/exams';

  let examId = $derived(($page.params as Record<string, string>).exam_id);

  let summary = $state<StudentExamSummary | null>(null);
  let loading = $state(true);
  let starting = $state(false);

  let showConfirm = $state(false);

  onMount(async () => {
    if (!$authStore.authenticated) { goto('/auth'); return; }
    try {
      summary = await getStudentExamSummary(examId);
    } catch (e: any) {
      toast.error(e.message || 'Failed to load exam');
      goto('/exams');
      return;
    }
    // Active attempt → jump to taking page.
    if (summary.display_state === 'in_progress') {
      goto(`/exams/${examId}/attempt`);
      return;
    }
    // Submitted with no retake granted → straight to result. With a
    // retake, stay here so the user can choose: take retake or view
    // their previous score.
    if (summary.display_state === 'submitted' && !summary.can_retake) {
      goto(`/exams/${examId}/result`);
      return;
    }
    loading = false;
  });

  async function start() {
    if (!summary) return;
    starting = true;
    try {
      await startAttempt(summary.id);
      goto(`/exams/${summary.id}/attempt`);
    } catch (e: any) {
      toast.error(e.message);
      starting = false;
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->

<div class="flex flex-col h-full">
  <div class="flex-1 overflow-y-auto">
    <div class="max-w-2xl mx-auto w-full px-4 pt-6 pb-8 space-y-4">

      <button onclick={() => goto('/exams')}
              class="inline-flex items-center gap-1.5 text-xs font-medium
                     text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition">
        <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6" />
        </svg>
        All exams
      </button>

      {#if loading || !summary}
        <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 px-4 py-10 text-center text-gray-400 text-sm">
          Loading…
        </div>
      {:else}
        <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-6 space-y-4">
          <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{summary.title}</h1>
          {#if summary.description}
            <p class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-line">{summary.description}</p>
          {/if}

          <dl class="grid grid-cols-2 gap-4 pt-2 border-t border-gray-100 dark:border-gray-800">
            <div>
              <dt class="text-[11px] uppercase tracking-wider text-gray-400">Questions</dt>
              <dd class="text-sm font-medium text-gray-900 dark:text-white mt-1">{summary.question_count}</dd>
            </div>
            <div>
              <dt class="text-[11px] uppercase tracking-wider text-gray-400">Time limit</dt>
              <dd class="text-sm font-medium text-gray-900 dark:text-white mt-1">
                {summary.time_limit_minutes ? `${summary.time_limit_minutes} minutes` : 'Untimed'}
              </dd>
            </div>
            <div class="col-span-2">
              <dt class="text-[11px] uppercase tracking-wider text-gray-400">Deadline</dt>
              <dd class="text-sm font-medium text-gray-900 dark:text-white mt-1">
                {formatLocalDeadline(summary.deadline_at)}
              </dd>
            </div>
          </dl>

          {#if summary.display_state === 'available'}
            <div class="pt-2">
              <button onclick={() => showConfirm = true} disabled={starting}
                      class="w-full px-4 py-3 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition
                             font-semibold disabled:opacity-50">
                {starting ? 'Starting…' : 'Start exam'}
              </button>
              <p class="text-[11px] text-gray-500 dark:text-gray-400 mt-2">
                Once you start, the timer begins and you must submit before
                {summary.time_limit_minutes
                  ? `the lesser of your ${summary.time_limit_minutes}-minute limit or the deadline above`
                  : 'the deadline above'}.
                You only get one submission.
              </p>
            </div>
          {:else if summary.display_state === 'submitted' && summary.can_retake}
            <div class="rounded-lg bg-blue-50 dark:bg-blue-900/20 px-3 py-2 text-xs text-blue-800 dark:text-blue-300 mb-3">
              An admin has granted you a retake. Starting a new attempt will replace your previous score.
            </div>
            <div class="pt-2 grid grid-cols-2 gap-2">
              <button onclick={() => goto(`/exams/${examId}/result`)}
                      class="px-4 py-3 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                             text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition
                             font-medium">
                View previous result
              </button>
              <button onclick={() => showConfirm = true} disabled={starting}
                      class="px-4 py-3 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition
                             font-semibold disabled:opacity-50">
                {starting ? 'Starting…' : 'Take retake'}
              </button>
            </div>
          {:else if summary.display_state === 'missed'}
            <div class="rounded-lg bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
              The deadline has passed. This exam can no longer be taken.
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </div>
</div>

<!-- Confirm before starting -->
{#if showConfirm && summary}
  <div class="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4"
       onclick={() => showConfirm = false}>
    <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-xl max-w-sm w-full p-6"
         onclick={(e) => e.stopPropagation()}>
      <h2 class="text-base font-semibold text-gray-900 dark:text-white mb-2">Start now?</h2>
      <p class="text-sm text-gray-700 dark:text-gray-300 mb-5">
        {#if summary.time_limit_minutes}
          The {summary.time_limit_minutes}-minute timer begins immediately. You can only submit once.
        {:else}
          You can take as long as you like up to the deadline, but you can only submit once.
        {/if}
      </p>
      <div class="flex gap-2 justify-end">
        <button onclick={() => showConfirm = false}
                class="px-3.5 py-1.5 text-sm rounded-full border border-gray-200 dark:border-gray-700
                       text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition">
          Cancel
        </button>
        <button onclick={async () => { showConfirm = false; await start(); }}
                class="px-3.5 py-1.5 text-sm rounded-full bg-blue-600 text-white hover:bg-blue-700 transition">
          Start
        </button>
      </div>
    </div>
  </div>
{/if}
