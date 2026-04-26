<script lang="ts">
  /**
   * Reusable upload + list + status panel.
   *
   * Drops into the course-detail page and the super_admin baseline page.
   * The list is *optimistic*: when the user picks N files, N rows appear
   * instantly with per-row spinners. Each upload runs in parallel; as
   * each 200 lands, that row's placeholder is replaced with the real
   * document (with View / Download surfaced on ``ready``). No manual
   * refresh required.
   *
   * Polls the list every few seconds while at least one *server-side*
   * document remains in ``processing`` (rare — uploads are synchronous
   * end-to-end today, but the field is honored if it ever becomes
   * async).
   */

  import { onDestroy } from 'svelte';
  import { toast } from 'svelte-sonner';
  import {
    deleteDocument,
    getDocumentSignedUrl,
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

  /** Local-only flags layered on top of ``UploadedDocument``. */
  type LocalDoc = UploadedDocument & {
    pending?: boolean;     // optimistic placeholder, no server id yet
    failed?: boolean;      // upload returned an error
    error_message?: string;
  };

  let docs = $state<LocalDoc[]>([]);
  let loading = $state(true);
  let fileInput: HTMLInputElement;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;

  // Inline confirm dialog for delete
  let confirmTitle = $state('');
  let confirmAction = $state<(() => Promise<void>) | null>(null);

  let activeDocs = $derived(docs.filter((d) => !d.deleted_at));
  let inFlightCount = $derived(
    activeDocs.filter((d) => d.pending || d.status === 'processing').length,
  );

  async function load() {
    try {
      const res = await listDocuments(courseId);
      // Preserve any in-flight optimistic rows that the server hasn't
      // seen yet — they merge back in when the upload promise resolves.
      const pending = docs.filter((d) => d.pending);
      docs = [...pending, ...res.data];
      schedulePoll();
    } catch (e: any) {
      toast.error(e.message || 'Failed to load documents');
    } finally {
      loading = false;
    }
  }

  function schedulePoll() {
    if (pollTimer) clearTimeout(pollTimer);
    const stillProcessing = docs.filter(
      (d) => !d.deleted_at && !d.pending && d.status === 'processing',
    ).length;
    if (stillProcessing > 0) {
      pollTimer = setTimeout(() => {
        load();
      }, 3000);
    }
  }

  function makePlaceholder(file: File): LocalDoc {
    return {
      id: `pending-${crypto.randomUUID()}`,
      title: file.name,
      status: 'processing',
      chunk_count: 0,
      uploaded_by: '',
      visibility: 'global',
      deleted_at: null,
      download_url: null,
      pending: true,
    };
  }

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const list = Array.from(files);

    // 1) Insert N placeholders at the top — instantly visible to the user.
    const placeholders = list.map(makePlaceholder);
    docs = [...placeholders, ...docs];

    // 2) Upload in parallel; each row resolves the moment its 200 lands.
    await Promise.all(
      list.map(async (file, idx) => {
        const tempId = placeholders[idx].id;
        try {
          const result = await uploadDocument(courseId, file);
          docs = docs.map((d) =>
            d.id === tempId ? { ...result, pending: false } : d,
          );
        } catch (e: any) {
          docs = docs.map((d) =>
            d.id === tempId
              ? {
                  ...d,
                  pending: false,
                  failed: true,
                  status: 'error',
                  error_message: e.message || 'Upload failed',
                }
              : d,
          );
          toast.error(`${file.name}: ${e.message}`);
        }
      }),
    );

    if (fileInput) fileInput.value = '';
    schedulePoll();
  }

  function askDelete(doc: LocalDoc) {
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

  function dismissFailed(doc: LocalDoc) {
    docs = docs.filter((d) => d.id !== doc.id);
  }

  async function resolveUrl(doc: LocalDoc): Promise<string | null> {
    if (doc.download_url) return doc.download_url;
    try {
      const res = await getDocumentSignedUrl(doc.id);
      return res.download_url;
    } catch (e: any) {
      toast.error(e.message || 'Failed to fetch download link');
      return null;
    }
  }

  async function viewDoc(doc: LocalDoc) {
    const url = await resolveUrl(doc);
    if (url) window.open(url, '_blank', 'noopener,noreferrer');
  }

  async function downloadDoc(doc: LocalDoc) {
    const url = await resolveUrl(doc);
    if (!url) return;
    // Same-origin download is straightforward; for cross-origin (R2) we
    // pull the bytes once and build an object URL so the ``download``
    // attribute is honored regardless of the response Content-Disposition.
    try {
      const res = await fetch(url);
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = doc.title;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // Defer revoke so the browser has time to consume the URL.
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch {
      // Fallback: just open it; the browser will save manually if needed.
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }

  function getFileIcon(name: string): string {
    const ext = name.split('.').pop()?.toLowerCase();
    if (ext === 'pdf') return '📄';
    if (['doc', 'docx'].includes(ext ?? '')) return '📝';
    if (['txt', 'md'].includes(ext ?? '')) return '📃';
    if (['csv', 'xlsx', 'xls'].includes(ext ?? '')) return '📊';
    if (['ppt', 'pptx'].includes(ext ?? '')) return '🎯';
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
      {#if inFlightCount > 0}
        <span class="inline-flex items-center gap-1.5 text-[11px] text-blue-600 dark:text-blue-400">
          <span class="size-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></span>
          {inFlightCount} processing
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
        class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
               bg-blue-600 text-white hover:bg-blue-700 transition font-medium"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
        Upload
      </button>
    </div>
  </div>

  {#if loading && docs.length === 0}
    <p class="text-xs text-gray-400 py-8 text-center">Loading materials…</p>
  {:else if docs.length === 0}
    <div class="rounded-xl border border-dashed border-gray-200 dark:border-gray-700 px-4 py-8 text-center">
      <p class="text-sm text-gray-400 mb-1">No materials yet.</p>
      <p class="text-xs text-gray-400">Upload PDFs, Word, text, or spreadsheet files to get started.</p>
    </div>
  {:else}
    <!-- 4 tiles per row at lg+, 2 at sm/md, 1 on phones. Names truncate
         with a native tooltip showing the full filename on hover so the
         action buttons always fit. -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
      {#each docs as doc (doc.id)}
        {@const isReady = doc.status === 'ready' && !doc.deleted_at && !doc.pending && !doc.failed}
        {@const isInFlight = doc.pending || (doc.status === 'processing' && !doc.deleted_at)}
        <div class="flex flex-col gap-2 p-3 rounded-lg transition
                    {doc.failed
                      ? 'bg-red-50/50 dark:bg-red-900/10 border border-red-200 dark:border-red-900/40'
                      : doc.deleted_at
                        ? 'bg-red-50/50 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30'
                        : isInFlight
                          ? 'bg-blue-50/40 dark:bg-blue-900/10 border border-blue-100 dark:border-blue-900/30'
                          : 'bg-gray-50 dark:bg-gray-800 border border-gray-100 dark:border-gray-700 hover:border-gray-200 dark:hover:border-gray-700'}">

          <!-- Title row: icon + truncated name (native tooltip on hover) -->
          <div class="flex items-center gap-2 min-w-0">
            <span class="text-base shrink-0 relative">
              {getFileIcon(doc.title)}
              {#if isInFlight}
                <span class="absolute -bottom-1 -right-1 size-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin bg-white dark:bg-gray-900"></span>
              {/if}
            </span>
            <p title={doc.title}
               class="text-sm text-gray-800 dark:text-gray-200 truncate font-medium min-w-0
                      {doc.deleted_at ? 'line-through opacity-60' : ''}">
              {doc.title}
            </p>
          </div>

          <!-- Meta row: status badge + chunks/error -->
          <div class="flex items-center gap-1.5 flex-wrap min-h-[18px]">
            <span class="px-1.5 py-0 rounded text-[9px] font-medium {statusBadge(doc.status)}">
              {doc.pending ? 'uploading' : doc.status}
            </span>
            {#if isReady}
              <span class="text-[10px] text-gray-400">{doc.chunk_count} chunks</span>
            {/if}
            {#if doc.failed && doc.error_message}
              <span class="text-[10px] text-red-500 truncate" title={doc.error_message}>{doc.error_message}</span>
            {/if}
            {#if doc.deleted_at}
              <span class="text-[10px] text-red-400">deleted</span>
            {/if}
          </div>

          <!-- Actions row: pinned to bottom of tile -->
          <div class="flex items-center justify-end gap-1 mt-auto pt-1 border-t border-gray-100 dark:border-gray-700/50">
            {#if isReady}
              <button onclick={() => viewDoc(doc)}
                      title="View"
                      aria-label="View document"
                      class="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50
                             dark:hover:text-blue-400 dark:hover:bg-blue-900/20 transition">
                <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              </button>
              <button onclick={() => downloadDoc(doc)}
                      title="Download"
                      aria-label="Download document"
                      class="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50
                             dark:hover:text-blue-400 dark:hover:bg-blue-900/20 transition">
                <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
              </button>
              <button onclick={() => askDelete(doc)}
                      title="Delete"
                      aria-label="Delete document"
                      class="p-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20
                             text-gray-400 hover:text-red-500 transition">
                <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            {:else if doc.failed}
              <button onclick={() => dismissFailed(doc)}
                      title="Dismiss"
                      aria-label="Dismiss failed upload"
                      class="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition">
                <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            {:else if isInFlight}
              <span class="text-[10px] text-blue-500 dark:text-blue-400 px-1">Processing…</span>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
