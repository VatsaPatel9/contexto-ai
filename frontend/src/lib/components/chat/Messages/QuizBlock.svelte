<script lang="ts">
  import type { Quiz } from '$lib/utils/citations';

  let { quiz }: { quiz: Quiz } = $props();

  // Local-only state: picking resolves the quiz in place, no network.
  let picked = $state<number | boolean | null>(null);
  let resolved = $derived(picked !== null);

  function pickMcq(i: number) {
    if (resolved) return;
    picked = i;
  }

  function pickTf(v: boolean) {
    if (resolved) return;
    picked = v;
  }

  function mcqButtonClass(i: number): string {
    if (!resolved) {
      return 'border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20';
    }
    if (quiz.kind !== 'mcq') return '';
    if (i === quiz.answer) {
      return 'border-green-400 bg-green-50 dark:border-green-500 dark:bg-green-900/30 text-green-800 dark:text-green-200';
    }
    if (i === picked) {
      return 'border-red-400 bg-red-50 dark:border-red-500 dark:bg-red-900/30 text-red-800 dark:text-red-200';
    }
    return 'border-gray-200 dark:border-gray-700 opacity-50';
  }

  function tfButtonClass(v: boolean): string {
    if (!resolved) {
      return 'border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20';
    }
    if (quiz.kind !== 'tf') return '';
    if (v === quiz.answer) {
      return 'border-green-400 bg-green-50 dark:border-green-500 dark:bg-green-900/30 text-green-800 dark:text-green-200';
    }
    if (v === picked) {
      return 'border-red-400 bg-red-50 dark:border-red-500 dark:bg-red-900/30 text-red-800 dark:text-red-200';
    }
    return 'border-gray-200 dark:border-gray-700 opacity-50';
  }

  let wasCorrect = $derived(resolved && picked === quiz.answer);
</script>

<div class="mt-4 pt-3 border-t border-gray-100 dark:border-gray-800">
  <div class="text-[11px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
    Quick check
  </div>
  <div class="text-sm text-gray-800 dark:text-gray-100 mb-3">
    {quiz.question}
  </div>

  {#if quiz.kind === 'mcq'}
    <div class="flex flex-col gap-2">
      {#each quiz.options as opt, i}
        <button
          type="button"
          onclick={() => pickMcq(i)}
          disabled={resolved}
          class="text-left text-sm px-3 py-2 rounded-lg border transition
                 {mcqButtonClass(i)}
                 {resolved ? 'cursor-default' : 'cursor-pointer'}"
        >
          <span class="font-medium mr-2">{String.fromCharCode(65 + i)}.</span>{opt}
        </button>
      {/each}
    </div>
  {:else if quiz.kind === 'tf'}
    <div class="flex gap-2">
      {#each [true, false] as v}
        <button
          type="button"
          onclick={() => pickTf(v)}
          disabled={resolved}
          class="text-sm px-4 py-2 rounded-lg border transition min-w-[100px]
                 {tfButtonClass(v)}
                 {resolved ? 'cursor-default' : 'cursor-pointer'}"
        >
          {v ? 'True' : 'False'}
        </button>
      {/each}
    </div>
  {/if}

  {#if resolved}
    <div class="mt-3 text-xs {wasCorrect
        ? 'text-green-700 dark:text-green-300'
        : 'text-gray-600 dark:text-gray-400'}">
      <span class="font-medium">{wasCorrect ? 'Correct.' : 'Not quite.'}</span>
      {#if quiz.explanation}
        <span class="ml-1">{quiz.explanation}</span>
      {/if}
    </div>
  {/if}
</div>
