<script lang="ts">
  import { toast } from 'svelte-sonner';
  import { authStore } from '$lib/stores/auth';
  import { session } from '$lib/stores';
  import { uploadDocument, type UploadedDocument } from '$lib/apis/documents';

  let {
    value = $bindable(''),
    onsubmit,
    loading = false,
    onstop
  }: {
    value?: string;
    onsubmit?: (text: string) => void;
    loading?: boolean;
    onstop?: () => void;
  } = $props();

  let textarea: HTMLTextAreaElement;
  let fileInput: HTMLInputElement;
  let showMenu = $state(false);

  // Attached files (pending upload or already uploaded)
  type AttachedFile = {
    file: File;
    name: string;
    status: 'pending' | 'uploading' | 'done' | 'error';
    result?: UploadedDocument;
    error?: string;
  };
  let attachedFiles = $state<AttachedFile[]>([]);

  // Check if user has upload permission
  let canUpload = $derived(
    $authStore.roles.includes('user_uploader') ||
    $authStore.roles.includes('admin') ||
    $authStore.roles.includes('super_admin')
  );

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    const text = value.trim();
    if (!text || loading) return;
    onsubmit?.(text);
    value = '';
    attachedFiles = [];
    if (textarea) textarea.style.height = 'auto';
  }

  function autoResize() {
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 384) + 'px';
  }

  $effect(() => {
    void value;
    autoResize();
  });

  // File handling
  function triggerFileUpload() {
    showMenu = false;
    fileInput?.click();
  }

  async function handleFilesSelected() {
    if (!fileInput?.files?.length) return;

    const files = Array.from(fileInput.files);
    fileInput.value = '';

    for (const file of files) {
      const attached: AttachedFile = { file, name: file.name, status: 'pending' };
      attachedFiles = [...attachedFiles, attached];
      await uploadFile(attached);
    }
  }

  async function uploadFile(attached: AttachedFile) {
    // Update status to uploading (replace object for Svelte reactivity)
    attachedFiles = attachedFiles.map((f) =>
      f === attached ? { ...f, status: 'uploading' as const } : f
    );

    try {
      const courseId = session.getCourseId();
      const result = await uploadDocument(courseId, attached.file);
      attachedFiles = attachedFiles.map((f) =>
        f.name === attached.name && f.file === attached.file
          ? { ...f, status: 'done' as const, result }
          : f
      );
      toast.success(`"${attached.name}" uploaded (${result.chunk_count} chunks)`);
    } catch (e: any) {
      attachedFiles = attachedFiles.map((f) =>
        f.name === attached.name && f.file === attached.file
          ? { ...f, status: 'error' as const, error: e.message }
          : f
      );
      toast.error(`Failed to upload "${attached.name}"`);
    }
  }

  function removeFile(index: number) {
    attachedFiles = attachedFiles.filter((_, i) => i !== index);
  }

  function getFileIcon(name: string): string {
    const ext = name.split('.').pop()?.toLowerCase();
    if (ext === 'pdf') return '📄';
    if (['doc', 'docx'].includes(ext ?? '')) return '📝';
    if (['txt', 'md'].includes(ext ?? '')) return '📃';
    if (['csv', 'xlsx', 'xls'].includes(ext ?? '')) return '📊';
    return '📎';
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->

<!-- Hidden file input -->
<input
  bind:this={fileInput}
  type="file"
  hidden
  multiple
  accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.xls"
  onchange={handleFilesSelected}
/>

<div class="w-full max-w-3xl mx-auto px-2 md:px-3 mb-4">
  <div
    class="flex-1 flex flex-col relative w-full rounded-3xl border
           border-gray-100/30 dark:border-gray-850/30
           hover:border-gray-200 focus-within:border-gray-100
           hover:dark:border-gray-800 focus-within:dark:border-gray-800
           transition shadow-lg px-1
           bg-white dark:bg-gray-500/5 backdrop-blur-sm dark:text-gray-100"
  >
    <!-- Attached files preview -->
    {#if attachedFiles.length > 0}
      <div class="mx-2 mt-2.5 pb-1.5 flex items-center flex-wrap gap-2">
        {#each attachedFiles as attached, idx}
          <div class="relative group flex items-center gap-2 px-3 py-1.5 rounded-xl
                      bg-gray-50 dark:bg-gray-800 border border-gray-100 dark:border-gray-700
                      text-xs max-w-[200px]">
            <span class="text-sm">{getFileIcon(attached.name)}</span>
            <span class="truncate text-gray-700 dark:text-gray-300">{attached.name}</span>

            {#if attached.status === 'uploading'}
              <div class="shrink-0 size-3.5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
            {:else if attached.status === 'error'}
              <span class="shrink-0 text-red-500 text-[10px]" title={attached.error}>!</span>
            {:else if attached.status === 'done'}
              <svg xmlns="http://www.w3.org/2000/svg" class="shrink-0 size-3.5 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            {/if}

            <!-- Remove button -->
            <button
              onclick={() => removeFile(idx)}
              class="absolute -top-1.5 -right-1.5 bg-white dark:bg-gray-700 text-gray-500
                     border border-gray-200 dark:border-gray-600 rounded-full size-4
                     flex items-center justify-center
                     invisible group-hover:visible transition text-[10px]"
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="size-3" viewBox="0 0 20 20" fill="currentColor">
                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
              </svg>
            </button>
          </div>
        {/each}
      </div>
    {/if}

    <!-- Textarea -->
    <textarea
      bind:this={textarea}
      bind:value
      onkeydown={handleKeydown}
      oninput={autoResize}
      placeholder="Send a message..."
      rows="1"
      class="scrollbar-hidden bg-transparent dark:text-gray-100 outline-hidden w-full
             resize-none h-fit max-h-96 overflow-auto
             {attachedFiles.length > 0 ? 'pt-1.5' : 'pt-2.5'} pb-1 px-3 text-[15px]
             placeholder-gray-400 dark:placeholder-gray-500"
    ></textarea>

    <!-- Bottom row: actions -->
    <div class="flex justify-between mt-0.5 mb-2.5 mx-0.5 max-w-full" dir="ltr">
      <div class="ml-1 self-end flex items-center">
        <!-- + button (upload menu) — only shown if user has permission -->
        {#if canUpload}
          <div class="relative">
            <button
              onclick={() => showMenu = !showMenu}
              class="bg-transparent hover:bg-gray-100 text-gray-700 dark:text-white
                     dark:hover:bg-gray-800 rounded-full size-8
                     flex justify-center items-center outline-hidden focus:outline-hidden transition"
              title="Attach files"
            >
              <!-- Plus icon (matches Open WebUI's PlusAlt) -->
              <svg xmlns="http://www.w3.org/2000/svg" class="size-5.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </button>

            <!-- Upload menu dropdown -->
            {#if showMenu}
              <div class="fixed inset-0 z-40" onclick={() => showMenu = false}></div>
              <div class="absolute bottom-full left-0 mb-2 z-50
                          w-56 rounded-2xl px-1 py-1
                          border border-gray-100 dark:border-gray-800
                          bg-white dark:bg-gray-850 dark:text-white
                          shadow-lg">
                <!-- Upload Files -->
                <button
                  class="flex w-full gap-2.5 items-center px-3 py-2 text-sm
                         select-none cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50
                         rounded-xl transition"
                  onclick={triggerFileUpload}
                >
                  <!-- Paperclip icon -->
                  <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-gray-500 dark:text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                  </svg>
                  <span class="line-clamp-1">Upload Documents</span>
                </button>
              </div>
            {/if}
          </div>
        {/if}
      </div>

      <div class="mr-1 self-end flex items-center">
        {#if loading}
          <button
            onclick={() => onstop?.()}
            class="p-2 rounded-full bg-gray-900 dark:bg-white text-white dark:text-gray-900
                   hover:opacity-80 transition"
            title="Stop generating"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
          </button>
        {:else}
          <button
            onclick={submit}
            disabled={!value.trim()}
            class="p-2 rounded-full bg-gray-900 dark:bg-white text-white dark:text-gray-900
                   hover:opacity-80 transition
                   disabled:opacity-20 disabled:cursor-not-allowed"
            title="Send message"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        {/if}
      </div>
    </div>
  </div>
</div>
