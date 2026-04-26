<script lang="ts">
  /**
   * Reusable upload + list + status panel.
   *
   * Drops into the course-detail page and the super_admin baseline page.
   * Polls the document list every few seconds while any document is in
   * the ``processing`` state, then idles once everything has settled.
   */

  import { onDestroy } from 'svelte';
  import { toast } from 'svelte-sonner';
  import {
    deleteDocument,
    listDocuments,
    uploadDocument,
    type UploadedDocument,
  } from '$lib/apis/documents';

  let {
    courseId,
    title = 'Materials',
    description = '',
  }: {
    courseId: string;
    title?: string;
    description?: string;
  } = $props();

  let docs = $state<UploadedDocument[]>([]);
  let loading = $state(true);
  let uploading = $state(false);
  let fileInput: HTMLInputElement;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;

  // Confirm dialog (small, inline)
  let confirmTitle = $state('');
  let confirmAction = $state<(() => Promise<void>) | null>(null);

  let activeDocs = $derived(docs.filter((d) => !d.deleted_at));
  let processingCount = $derived(activeDocs.filter((d) => d.status === 'processing').length);

  async function load() {
    try {
      const res = await listDocuments(courseId);
      docs = res.data;
      schedulePoll();
    } catch (e: any) {
      toast.error(e.message || 'Failed to load documents');
    } finally {
      loading = false;
    }
  }

  function schedulePoll() {
    if (pollTimer) clearTimeout(pollTimer);
    // Only re-poll while at least one doc is still being chunked + embedded.
    if (processingCount > 0) {
      pollTimer = setTimeout(() => {
        load();
      }, 3000);
    }
  }

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    uploading = true;
    try {
      for (const file of Array.from(files)) {
        try {
          await uploadDocument(courseId, file);
          toast.success(`Uploaded ${file.name}`);
        } catch (e: any) {
          toast.error(`${file.name}: ${e.message}`);
        }
      }
      await load();
    } finally {
      uploading = false;
      if (fileInput) fileInput.value = '';
    }
  }

  function askDelete(doc: UploadedDocument) {
    confirmTitle = doc.title;
    confirmAction = async () => {
      try {
        await deleteDocument(courseId, doc.id);
        toast.success('Document deleted');
        await load();
      } catch (e: any) {
        toast.error(e.message);
      }
    };
  }

  function getFileIcon(name: string): string {
    const ext = name.split('.').pop()?.toLowerCase();
    if (ext === 'pdf') return '📄';
    if (['doc', 'docx'].includes(ext ?? '')) return '📝';
    if (['txt', 'md'].includes(ext ?? '')) return '📃';
    if (['csv', 'xlsx', 'xls'].includes(ext ?? '')) return '📊';
    return '📎';
  }

  function statusBadge(status: string): string {
    switch (status) {
      case 'ready': return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
      case 'processing': return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400';
      case 'error': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
      default: return 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400';
    }
  }

  // Kick off the initial fetch + poll loop.
  $effect(() => {
    void courseId;
    loading = true;
    load();
  });

  onDestroy(() => {
    if (pollTimer) clearTimeout(pollTimer);
  });
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->

{#if confirmAction}
  <div class="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4"
       onclick={() => (confirmAction = null)}>
    <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-xl max-w-sm w-full p-6"
         onclick={(e) => e.stopPropagation()}>
      <p class="text-sm text-gray-700 dark:text-gray-300 mb-5">
        Delete &ldquo;{confirmTitle}&rdquo;? It will be removed from retrieval immediately and
        permanently deleted after 30 days.
      </p>
      <div class="flex gap-2 justify-end">
        <button onclick={() => (confirmAction = null)}
                class="px-3.5 py-1.5 text-sm rounded-full border border-gray-200 dark:border-gray-700
                       text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition">
          Cancel
        </button>
        <button onclick={async () => { const a = confirmAction; confirmAction = null; await a?.(); }}
                class="px-3.5 py-1.5 text-sm rounded-full bg-red-600 text-white hover:bg-red-700 transition">
          Delete
        </button>
      </div>
    </div>
  </div>
{/if}

<div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
  <div class="flex items-start justify-between gap-3 mb-4">
    <div class="min-w-0">
      <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">{title}</div>
      {#if description}
        <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
      {/if}
    </div>
    <div class="flex items-center gap-2">
      {#if processingCount > 0}
        <span class="inline-flex items-center gap-1.5 text-[11px] text-blue-600 dark:text-blue-400">
          <span class="size-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></span>
          {processingCount} processing
        </span>
      {/if}
      <input
        bind:this={fileInput}
        type="file"
        multiple
        accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.xls,.ppt,.pptx"
        onchange={(e) => handleFiles((e.currentTarget as HTMLInputElement).files)}
        class="hidden"
      />
      <button
        onclick={() => fileInput?.click()}
        disabled={uploading}
        class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
               bg-blue-600 text-white hover:bg-blue-700 transition font-medium
               disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {#if uploading}
          <span class="size-3 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
          Uploading…
        {:else}
          <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          Upload
        {/if}
      </button>
    </div>
  </div>

  {#if loading}
    <p class="text-xs text-gray-400 py-8 text-center">Loading materials…</p>
  {:else if docs.length === 0}
    <div class="rounded-xl border border-dashed border-gray-200 dark:border-gray-700 px-4 py-8 text-center">
      <p class="text-sm text-gray-400 mb-1">No materials yet.</p>
      <p class="text-xs text-gray-400">Upload PDFs, Word, text, or spreadsheet files to get started.</p>
    </div>
  {:else}
    <div class="space-y-1.5">
      {#each docs as doc (doc.id)}
        <div class="flex items-center gap-3 px-3 py-2.5 rounded-lg group
                    {doc.deleted_at
                      ? 'bg-red-50/50 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30'
                      : 'bg-gray-50 dark:bg-gray-800 border border-gray-100 dark:border-gray-700'}">
          <span class="text-base shrink-0 relative">
            {getFileIcon(doc.title)}
            {#if doc.status === 'processing'}
              <span class="absolute -bottom-1 -right-1 size-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin bg-white dark:bg-gray-900"></span>
            {/if}
          </span>
          <div class="flex-1 min-w-0">
            <p class="text-sm text-gray-800 dark:text-gray-200 truncate font-medium
                      {doc.deleted_at ? 'line-through opacity-60' : ''}">{doc.title}</p>
            <div class="flex items-center gap-1.5 mt-0.5 flex-wrap">
              <span class="px-1.5 py-0 rounded text-[9px] font-medium {statusBadge(doc.status)}">
                {doc.status}
              </span>
              {#if doc.status === 'ready'}
                <span class="text-[10px] text-gray-400">{doc.chunk_count} chunks</span>
              {/if}
              {#if doc.deleted_at}
                <span class="text-[10px] text-red-400">deleted</span>
              {/if}
            </div>
          </div>
          {#if !doc.deleted_at}
            <button onclick={() => askDelete(doc)}
                    aria-label="Delete document"
                    class="shrink-0 p-1.5 rounded-lg opacity-0 group-hover:opacity-100
                           hover:bg-red-50 dark:hover:bg-red-900/20
                           text-gray-400 hover:text-red-500 transition">
              <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
