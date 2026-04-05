<script lang="ts">
  import { onMount } from 'svelte';
  import { appParameters } from '$lib/stores';
  import { getParameters } from '$lib/apis/contexto';

  let { onSuggestionClick }: { onSuggestionClick?: (text: string) => void } = $props();

  const fallbackSuggestions = [
    'Explain the concept of derivatives in calculus',
    "Help me understand Newton's laws of motion",
    'What is the difference between DNA and RNA?',
    'Walk me through solving a quadratic equation'
  ];

  onMount(async () => {
    try {
      const params = await getParameters();
      appParameters.set({
        openingStatement: params.opening_statement,
        suggestedQuestions: params.suggested_questions,
        courseName: params.course_name
      });
    } catch {
      // Backend unavailable
    }
  });

  let suggestions = $derived(
    $appParameters.suggestedQuestions.length > 0
      ? $appParameters.suggestedQuestions
      : fallbackSuggestions
  );

  let courseName = $derived($appParameters.courseName || 'STEM subjects');
  let openingStatement = $derived($appParameters.openingStatement);
</script>

<div class="m-auto w-full max-w-6xl px-2 md:px-20 translate-y-6 py-24 text-center">
  <!-- Title -->
  <div class="w-full text-3xl text-gray-800 dark:text-gray-100 text-center flex items-center gap-4 font-primary justify-center">
    <img src="/mascot-placeholder.png" alt="Contexto" class="rounded-full" width="56" height="56" />
    <div class="text-3xl line-clamp-1">Contexto</div>
  </div>
  <p class="text-xs text-gray-400 dark:text-gray-500 -mt-1">AI Tutor</p>

  <!-- Description -->
  {#if openingStatement}
    <div class="mt-0.5 px-2 text-sm font-normal text-gray-500 dark:text-gray-400 line-clamp-2 max-w-xl mx-auto">
      {openingStatement}
    </div>
  {:else}
    <div class="mt-0.5 px-2 text-sm font-normal text-gray-500 dark:text-gray-400">
      Ask me anything about {courseName}
    </div>
  {/if}

  <!-- Suggestions -->
  <div class="mx-auto max-w-2xl font-primary mt-8">
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
      {#each suggestions as suggestion}
        <button
          class="text-left px-4 py-3 rounded-xl border border-gray-100 dark:border-gray-850
                 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition
                 text-sm text-gray-600 dark:text-gray-400"
          onclick={() => onSuggestionClick?.(suggestion)}
        >
          {suggestion}
        </button>
      {/each}
    </div>
  </div>
</div>
