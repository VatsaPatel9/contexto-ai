<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import DocumentManager from '$lib/components/admin/DocumentManager.svelte';

  // Single fixed dataset all super_admin baseline uploads land in. The
  // backend tags any super_admin upload with ``uploader_role='baseline'``
  // regardless of which dataset it sits in, so retrieval surfaces these
  // documents to every chat — even for students with no course enrollment.
  const BASELINE_COURSE_ID = '_baseline_';

  onMount(() => {
    if (!$authStore.roles.includes('super_admin')) {
      goto('/admin?tab=users');
    }
  });
</script>

<svelte:head>
  <title>Baseline materials · Contexto</title>
</svelte:head>

<div class="flex flex-col h-full">
  <div class="flex-1 overflow-y-auto">
    <div class="max-w-5xl mx-auto w-full px-4 pt-4 pb-8 space-y-6">

      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Baseline materials</h1>
        <p class="text-sm text-gray-600 dark:text-gray-400 mt-1 max-w-2xl">
          Documents uploaded here are <strong>system-wide</strong>. Every learner sees them
          during chat, regardless of which course they're enrolled in (or whether
          they're enrolled at all). Use this for institutional reference materials —
          glossaries, lab safety guides, foundational reading — that should always
          be retrievable.
        </p>
      </div>

      {#if $authStore.roles.includes('super_admin')}
        <DocumentManager
          courseId={BASELINE_COURSE_ID}
          title="System library"
          description="Visible to every authenticated user in every chat."
        />
      {/if}

    </div>
  </div>
</div>
