<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { toast } from 'svelte-sonner';

  import { authStore } from '$lib/stores/auth';
  import {
    getMyResult,
    formatLocalDeadline,
    type ResultPayload,
  } from '$lib/apis/exams';

  let examId = $derived(($page.params as Record<string, string>).exam_id);

  let result = $state<ResultPayload | null>(null);
  let loading = $state(true);

  onMount(async () => {
    if (!$authStore.authenticated) { goto('/auth'); return; }
    try {
      result = await getMyResult(examId);
    } catch (e: any) {
      toast.error(e.message || 'Failed to load result');
      goto('/exams');
      return;
    }
    loading = false;
  });

  function scoreBand(pct: number): string {
    if (pct >= 80) return 'text-green-600 dark:text-green-400';
    if (pct >= 60) return 'text-blue-600 dark:text-blue-400';
    if (pct >= 40) return 'text-amber-600 dark:text-amber-400';
    return 'text-red-600 dark:text-red-400';
  }
</script>

<div class="flex flex-col h-full">
  <div class="flex-1 overflow-y-auto">
    <div class="max-w-3xl mx-auto w-full px-4 pt-6 pb-12 space-y-4">

      <button onclick={() => goto('/exams')}
              class="inline-flex items-center gap-1.5 text-xs font-medium
                     text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition">
        <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6" />
        </svg>
        All exams
      </button>

      {#if loading || !result}
        <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 px-4 py-10 text-center text-gray-400 text-sm">
          Loading…
        </div>
      {:else}
        <!-- Score card -->
        <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-6">
          <h1 class="text-base font-semibold text-gray-900 dark:text-white">{result.title}</h1>
          <p class="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
            Submitted {new Date(result.submitted_at).toLocaleString()}
          </p>

          <div class="flex items-baseline gap-3 mt-5">
            <div class="text-5xl font-bold {scoreBand(result.score_pct)}">
              {Math.round(result.score_pct)}%
            </div>
            <div class="text-sm text-gray-500 dark:text-gray-400">
              {result.score_raw.toFixed(2)} / {result.total_points} points
            </div>
          </div>

          {#if result.manual_override && result.auto_score_raw !== null}
            <div class="mt-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 px-3 py-2 text-xs text-blue-800 dark:text-blue-300">
              An admin adjusted your score. Auto-graded:
              <strong>{result.auto_score_raw.toFixed(2)} / {result.total_points}</strong>;
              final after review: <strong>{result.score_raw.toFixed(2)} / {result.total_points}</strong>.
            </div>
          {/if}

          {#if !result.review_unlocked}
            <div class="mt-5 rounded-lg bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
              Per-question correct answers and explanations will appear here after the
              deadline ({formatLocalDeadline(result.deadline_at)}).
            </div>
          {/if}
        </div>

        {#if result.review_unlocked && result.review}
          <div>
            <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-2">
              Review · {result.review.length} questions
            </div>
            <div class="space-y-3">
              {#each result.review as r, idx (r.question_id)}
                <article class="rounded-2xl border
                                {r.is_correct
                                  ? 'border-green-200 dark:border-green-900/40 bg-green-50/30 dark:bg-green-900/10'
                                  : r.partial_score > 0
                                    ? 'border-amber-200 dark:border-amber-900/40 bg-amber-50/30 dark:bg-amber-900/10'
                                    : 'border-red-200 dark:border-red-900/40 bg-red-50/30 dark:bg-red-900/10'}
                                p-5">
                  <header class="flex items-center justify-between gap-3 mb-3">
                    <div class="flex items-center gap-2">
                      <span class="text-[11px] font-mono text-gray-400">Q{idx + 1}</span>
                      <span class="px-1.5 py-0 rounded text-[9px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                        {r.type === 'mcq' ? 'MCQ' : 'T/F'}
                      </span>
                    </div>
                    <span class="text-xs font-medium
                                 {r.is_correct
                                   ? 'text-green-700 dark:text-green-400'
                                   : r.partial_score > 0
                                     ? 'text-amber-700 dark:text-amber-400'
                                     : 'text-red-700 dark:text-red-400'}">
                      {r.is_correct
                        ? 'Correct'
                        : r.partial_score > 0
                          ? `Partial (${(r.partial_score * 100).toFixed(0)}%)`
                          : 'Incorrect'}
                    </span>
                  </header>

                  <p class="text-sm text-gray-900 dark:text-white whitespace-pre-line mb-3">{r.text}</p>

                  <div class="space-y-1.5">
                    {#each r.options as opt (opt.id)}
                      {@const wasSelected = r.selected_option_ids.includes(opt.id)}
                      <div class="flex items-center gap-3 px-3 py-2 rounded-lg border
                                  {opt.is_correct
                                    ? 'border-green-300 bg-green-50 dark:border-green-700 dark:bg-green-900/20'
                                    : wasSelected
                                      ? 'border-red-300 bg-red-50 dark:border-red-700 dark:bg-red-900/20'
                                      : 'border-gray-200 dark:border-gray-700'}">
                        <span class="shrink-0 size-5 rounded-md border-2 flex items-center justify-center
                                     {wasSelected
                                       ? (opt.is_correct ? 'border-green-600 bg-green-600 text-white' : 'border-red-600 bg-red-600 text-white')
                                       : 'border-gray-300 dark:border-gray-600'}">
                          {#if wasSelected}
                            <svg xmlns="http://www.w3.org/2000/svg" class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                              <polyline points="20 6 9 17 4 12" />
                            </svg>
                          {/if}
                        </span>
                        <span class="text-sm text-gray-800 dark:text-gray-200 flex-1">{opt.text}</span>
                        {#if opt.is_correct}
                          <span class="text-[10px] uppercase tracking-wider text-green-700 dark:text-green-400 font-medium shrink-0">Correct</span>
                        {/if}
                      </div>
                    {/each}
                  </div>

                  {#if r.explanation}
                    <p class="text-xs text-gray-700 dark:text-gray-300 mt-3 pt-3 border-t border-gray-200 dark:border-gray-700 whitespace-pre-line">
                      <strong class="text-gray-500 dark:text-gray-400">Why:</strong> {r.explanation}
                    </p>
                  {/if}
                </article>
              {/each}
            </div>
          </div>
        {/if}
      {/if}
    </div>
  </div>
</div>
