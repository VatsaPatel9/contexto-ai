<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { toast } from 'svelte-sonner';

  import { authStore } from '$lib/stores/auth';
  import {
    listMyExams,
    formatLocalDeadline,
    formatTimeRemaining,
    type StudentExamRow,
  } from '$lib/apis/exams';

  let loading = $state(true);
  let exams = $state<StudentExamRow[]>([]);

  // Three buckets visible to the user; the rest go in "Other".
  let available = $derived(exams.filter((e) => e.display_state === 'available'));
  let inProgress = $derived(exams.filter((e) => e.display_state === 'in_progress'));
  let submitted = $derived(exams.filter((e) => e.display_state === 'submitted'));
  let missed = $derived(exams.filter((e) => e.display_state === 'missed' || e.display_state === 'past_deadline'));

  onMount(async () => {
    if (!$authStore.authenticated) {
      goto('/auth');
      return;
    }
    await load();
    loading = false;
  });

  async function load() {
    try {
      exams = await listMyExams();
    } catch (e: any) {
      toast.error(e.message || 'Failed to load exams');
    }
  }

  function open(exam: StudentExamRow) {
    // Submitted + retake granted: route to the pre-start page so the
    // user picks "view result" vs "take retake" rather than auto-jumping.
    if (exam.display_state === 'submitted' && exam.can_retake) goto(`/exams/${exam.id}`);
    else if (exam.display_state === 'submitted') goto(`/exams/${exam.id}/result`);
    else if (exam.display_state === 'in_progress') goto(`/exams/${exam.id}/attempt`);
    else goto(`/exams/${exam.id}`);
  }

  function badge(state: StudentExamRow['display_state']): string {
    switch (state) {
      case 'available':    return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
      case 'in_progress':  return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400';
      case 'submitted':    return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300';
      case 'missed':
      case 'past_deadline':return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
      default:             return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300';
    }
  }
</script>

<div class="flex flex-col h-full">
  <div class="flex-1 overflow-y-auto">
    <div class="max-w-4xl mx-auto w-full px-4 pt-6 pb-8 space-y-6">

      <header class="space-y-1">
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Exams</h1>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Exams from courses you're enrolled in. Deadlines are shown in your local time.
        </p>
      </header>

      {#if loading}
        <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 px-4 py-10 text-center text-gray-400 text-sm">
          Loading…
        </div>
      {:else if exams.length === 0}
        <div class="rounded-2xl border border-dashed border-gray-200 dark:border-gray-700 px-4 py-10 text-center text-gray-400 text-sm">
          No exams in your courses yet.
        </div>
      {:else}
        {@render section('In progress', inProgress)}
        {@render section('Available', available)}
        {@render section('Completed', submitted)}
        {@render section('Missed', missed)}
      {/if}
    </div>
  </div>
</div>

{#snippet section(label: string, rows: StudentExamRow[])}
  {#if rows.length}
    <div>
      <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-2">
        {label} · {rows.length}
      </div>
      <div class="space-y-2">
        {#each rows as ex (ex.id)}
          <button onclick={() => open(ex)}
                  class="w-full text-left rounded-2xl border border-gray-100 dark:border-gray-800
                         bg-white dark:bg-gray-850 p-4 transition
                         hover:border-gray-200 dark:hover:border-gray-700 hover:shadow-sm">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                  <h3 class="text-sm font-semibold text-gray-900 dark:text-white truncate">{ex.title}</h3>
                  <span class="px-2 py-0.5 rounded-full text-[10px] font-medium {badge(ex.display_state)}">
                    {ex.display_state.replace('_', ' ')}
                  </span>
                </div>
                {#if ex.course_name}
                  <p class="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">{ex.course_name}</p>
                {/if}
                <div class="flex items-center gap-3 mt-2 text-[11px] text-gray-500 dark:text-gray-400 flex-wrap">
                  <span>Deadline: {formatLocalDeadline(ex.deadline_at)}</span>
                  <span>·</span>
                  <span>{ex.time_limit_minutes ? `${ex.time_limit_minutes} min` : 'Untimed'}</span>
                  <span>·</span>
                  <span>{ex.question_count} question{ex.question_count === 1 ? '' : 's'}</span>
                </div>
              </div>
              <div class="text-right shrink-0">
                {#if ex.display_state === 'submitted' && ex.score_pct !== null}
                  <div class="text-lg font-bold text-gray-900 dark:text-white">
                    {Math.round(ex.score_pct)}%
                  </div>
                  <div class="text-[10px] text-gray-400">score</div>
                  {#if ex.can_retake}
                    <div class="text-[10px] text-blue-600 dark:text-blue-400 mt-0.5 font-medium">
                      retake granted
                    </div>
                  {/if}
                {:else if ex.display_state === 'in_progress' && ex.time_remaining_seconds !== null}
                  <div class="text-sm font-mono text-blue-600 dark:text-blue-400">
                    {formatTimeRemaining(ex.time_remaining_seconds)}
                  </div>
                  <div class="text-[10px] text-gray-400">remaining</div>
                {/if}
              </div>
            </div>
          </button>
        {/each}
      </div>
    </div>
  {/if}
{/snippet}
