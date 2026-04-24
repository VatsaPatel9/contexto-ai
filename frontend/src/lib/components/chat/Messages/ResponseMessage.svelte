<script lang="ts">
  import type { ChatMessage } from '$lib/stores';
  import { session, openPdfViewer } from '$lib/stores';
  import { copyToClipboard } from '$lib/utils';
  import { submitFeedback } from '$lib/apis/contexto';
  import { toast } from 'svelte-sonner';
  import Markdown from './Markdown.svelte';

  let {
    message,
    onAskSuggestion,
  }: {
    message: ChatMessage;
    onAskSuggestion?: (text: string) => void;
  } = $props();

  let copied = $state(false);
  let feedbackState = $derived(message.feedback ?? null) as 'like' | 'dislike' | null;
  let localFeedback = $state<'like' | 'dislike' | null>(null);
  let effectiveFeedback = $derived(localFeedback ?? feedbackState);

  // Dedupe citation badges by (doc_title, page_num). Multiple retrieved
  // chunks often come from the same page — showing the same pill seven
  // times is noise. Keep the first one (highest-scored, since the
  // server returns sources sorted by relevance).
  let uniqueCitations = $derived.by(() => {
    const list = message.retrieverResources;
    if (!list || list.length === 0) return [];
    const seen = new Set<string>();
    const out: typeof list = [];
    for (const c of list) {
      const key = `${c.doc_title}::${c.page_num ?? ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(c);
    }
    return out;
  });

  async function handleCopy() {
    const ok = await copyToClipboard(message.content);
    if (ok) {
      copied = true;
      toast.success('Copied to clipboard');
      setTimeout(() => (copied = false), 2000);
    }
  }

  async function handleFeedback(rating: 'like' | 'dislike') {
    if (effectiveFeedback === rating) return;
    try {
      await submitFeedback(message.id, rating);
      localFeedback = rating;
    } catch {
      toast.error('Failed to submit feedback');
    }
  }
</script>

<div class="flex w-full group" style="scroll-margin-top: 3rem;">
  <!-- Avatar -->
  <div class="shrink-0 mr-3 mt-1">
    <div class="size-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                flex items-center justify-center text-white text-xs font-bold object-cover">
      AI
    </div>
  </div>

  <!-- Content -->
  <div class="flex-auto w-0 pl-1 relative">
    {#if message.error}
      <div class="text-sm text-red-500 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
        {message.error}
      </div>
    {:else if !message.content && !message.done}
      <!-- Thinking spinner -->
      <div class="flex items-center gap-2 py-2">
        <div
          class="size-4 rounded-full border-2 border-gray-400 dark:border-gray-500"
          style="border-top-color: transparent; animation: spin 0.7s linear infinite;"
        ></div>
        <span class="text-sm text-gray-400 dark:text-gray-500">Thinking...</span>
      </div>
    {:else}
      <!-- Markdown content -->
      <div class="chat-assistant-message w-full">
        <Markdown content={message.content} />
      </div>

      <!-- Suggested follow-up questions (chips) — submits on click -->
      {#if message.done && message.suggestions && message.suggestions.length > 0}
        <div class="mt-4 pt-3 border-t border-gray-100 dark:border-gray-800">
          <div class="text-[11px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
            You can also ask
          </div>
          <div class="flex flex-wrap gap-2">
            {#each message.suggestions as q}
              <button
                type="button"
                onclick={() => onAskSuggestion?.(q)}
                class="text-sm px-3 py-1.5 rounded-full
                       bg-gray-50 hover:bg-blue-50 dark:bg-gray-800 dark:hover:bg-blue-900/30
                       text-gray-700 hover:text-blue-700 dark:text-gray-200 dark:hover:text-blue-300
                       border border-gray-200 dark:border-gray-700
                       hover:border-blue-300 dark:hover:border-blue-600
                       transition"
                title="Ask this question"
              >
                {q}
              </button>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Sources (above action bar) — clickable when doc_id is known -->
      {#if message.done && uniqueCitations.length > 0}
        <div class="mt-2 flex flex-wrap gap-1.5">
          {#each uniqueCitations as source}
            {@const clickable = !!source.doc_id}
            <button
              type="button"
              disabled={!clickable}
              onclick={() => clickable && openPdfViewer({
                docId: source.doc_id!,
                title: source.doc_title,
                page: source.page_num,
                highlight: source.section ?? '',
              })}
              class="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full
                     bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400
                     {clickable ? 'hover:bg-blue-100 dark:hover:bg-blue-900/40 cursor-pointer' : 'cursor-default'}
                     transition"
              title={clickable ? 'Open in document viewer' : (source.section ?? '')}
            >
              {source.doc_title}{source.page_num ? ` (p. ${source.page_num})` : ''}
            </button>
          {/each}
        </div>
      {/if}

      <!-- Action buttons -->
      {#if message.done}
        <div class="flex justify-start overflow-x-auto text-gray-600 dark:text-gray-500 mt-0.5">
          <!-- Copy -->
          <button
            onclick={handleCopy}
            class="invisible group-hover:visible p-1.5 hover:bg-black/5 dark:hover:bg-white/5
                   rounded-lg dark:hover:text-white hover:text-black transition"
            title="Copy"
          >
            {#if copied}
              <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            {:else}
              <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
            {/if}
          </button>

          <!-- Like -->
          <button
            onclick={() => handleFeedback('like')}
            class="{effectiveFeedback === 'like' ? 'visible text-green-500' : 'invisible group-hover:visible'}
                   p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg
                   dark:hover:text-white hover:text-black transition"
            title="Good response"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24"
                 fill={effectiveFeedback === 'like' ? 'currentColor' : 'none'}
                 stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" />
            </svg>
          </button>

          <!-- Dislike -->
          <button
            onclick={() => handleFeedback('dislike')}
            class="{effectiveFeedback === 'dislike' ? 'visible text-red-500' : 'invisible group-hover:visible'}
                   p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg
                   dark:hover:text-white hover:text-black transition"
            title="Bad response"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24"
                 fill={effectiveFeedback === 'dislike' ? 'currentColor' : 'none'}
                 stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17" />
            </svg>
          </button>
        </div>
      {/if}
    {/if}
  </div>
</div>
