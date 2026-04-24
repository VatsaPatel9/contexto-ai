<script lang="ts">
  import { tick } from 'svelte';
  import { goto } from '$app/navigation';
  import { toast } from 'svelte-sonner';

  import {
    session,
    currentChatId,
    conversations,
    pdfViewerRequest,
    closePdfViewer,
    type ChatMessage,
    type Conversation
  } from '$lib/stores';
  import PdfViewer from '$lib/components/pdf/PdfViewer.svelte';
  import {
    sendChatMessage,
    getMessages,
    getConversation,
    type ApiMessage
  } from '$lib/apis/contexto';
  import { generateId, generateTitle, scrollToBottom } from '$lib/utils';
  import { parseCitationsFence, parseSuggestionsFence } from '$lib/utils/citations';

  import Navbar from '$lib/components/layout/Navbar.svelte';
  import Messages from '$lib/components/chat/Messages.svelte';
  import MessageInput from '$lib/components/chat/MessageInput.svelte';
  import Placeholder from '$lib/components/chat/Placeholder.svelte';

  let { chatId = undefined }: { chatId?: string } = $props();

  let messages = $state<ChatMessage[]>([]);
  let chatTitle = $state('New Chat');
  let loading = $state(false);
  let inputValue = $state('');
  let messagesContainer: HTMLDivElement;

  // Resizable split between chat and PDF viewer. Value is the viewer
  // column's share of the row, as a percentage (25–75%).
  let viewerPct = $state(50);
  let splitContainer: HTMLDivElement;
  let isResizing = $state(false);

  function startResize(e: MouseEvent) {
    e.preventDefault();
    isResizing = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', onResize);
    window.addEventListener('mouseup', endResize);
  }

  function onResize(e: MouseEvent) {
    if (!splitContainer || !isResizing) return;
    const rect = splitContainer.getBoundingClientRect();
    const xFromRight = rect.right - e.clientX;
    const pct = (xFromRight / rect.width) * 100;
    viewerPct = Math.max(25, Math.min(75, pct));
  }

  function endResize() {
    isResizing = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    window.removeEventListener('mousemove', onResize);
    window.removeEventListener('mouseup', endResize);
  }

  // Track which chat is currently loaded in memory so we know when a
  // chatId change means "user switched threads" (reload + close viewer)
  // vs "our own stream just assigned this chatId" (skip reload).
  let loadedChatId: string | null = null;

  $effect(() => {
    const id = chatId;
    if (!id) {
      closePdfViewer();
      currentChatId.set(null);
      messages = [];
      chatTitle = 'New Chat';
      loadedChatId = null;
      return;
    }
    currentChatId.set(id);

    // Same chat as what's already loaded — nothing to do.
    if (id === loadedChatId) return;

    // Mid-stream of a brand-new chat: hydrateIfNew just set chatId on
    // the window, but the stream is still running. Don't wipe the
    // streamed content; just remember we're on this id now.
    if (loading && messages.length > 0) {
      loadedChatId = id;
      return;
    }

    // User navigated to a different thread (sidebar click, back/forward,
    // direct URL). Close any stale PDF viewer and reload.
    closePdfViewer();
    messages = [];
    chatTitle = 'Loading...';
    loadConversation(id).then(() => {
      loadedChatId = id;
    });
  });

  async function loadConversation(convId: string) {
    try {
      const conv = await getConversation(convId);
      chatTitle = conv.name || 'Chat';
      const { data } = await getMessages(convId);
      messages = data.map(apiMessageToChat);
      await tick();
      if (messagesContainer) scrollToBottom(messagesContainer, false);
    } catch (err) {
      toast.error('Failed to load conversation');
      console.error(err);
    }
  }

  // Enrich LLM-emitted citations (which only know doc_title/page/section)
  // with doc_id from the server's retriever metadata so badges are
  // clickable and can open the PDF viewer.
  function enrichWithDocIds(
    llmCitations: ChatMessage['retrieverResources'],
    serverResources: ChatMessage['retrieverResources']
  ): ChatMessage['retrieverResources'] {
    if (!llmCitations || !serverResources) return llmCitations ?? serverResources ?? null;
    const byTitle = new Map<string, any>();
    for (const r of serverResources) {
      if (!byTitle.has(r.doc_title)) byTitle.set(r.doc_title, r);
    }
    return llmCitations.map((c) => {
      const m = byTitle.get(c.doc_title);
      return m ? { ...c, doc_id: c.doc_id ?? m.doc_id } : c;
    });
  }

  function apiMessageToChat(msg: ApiMessage): ChatMessage {
    // Stored assistant text may contain a `citations` fence and/or a
    // `suggestions` fence. Strip both for display; surface them as
    // structured fields on the message instead.
    const c = parseCitationsFence(msg.content);
    const s = parseSuggestionsFence(c.display);
    const enriched = c.citations
      ? enrichWithDocIds(c.citations, msg.retriever_resources)
      : msg.retriever_resources;
    return {
      id: msg.id,
      role: msg.role,
      content: s.display,
      timestamp: msg.created_at * 1000,
      messageType: msg.message_type,
      done: true,
      retrieverResources: enriched,
      suggestions: s.suggestions ?? null
    };
  }

  async function handleSubmit(text: string) {
    if (loading) return;

    const courseId = session.getCourseId();

    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: text,
      timestamp: Date.now()
    };

    const assistantMsg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      done: false
    };

    messages = [...messages, userMsg, assistantMsg];
    loading = true;

    await tick();
    if (messagesContainer) scrollToBottom(messagesContainer);

    try {
      const stream = await sendChatMessage(text, chatId ?? null, courseId);

      for await (const event of stream) {
        if (event.event === 'message' || event.event === 'agent_message') {
          // Accumulate into _raw; derive visible `content` by stripping
          // both the `citations` and `suggestions` fences. While a
          // fence is open but not yet closed, everything after it stays
          // hidden — user never sees raw JSON.
          assistantMsg._raw = (assistantMsg._raw ?? '') + (event.answer ?? '');
          const c = parseCitationsFence(assistantMsg._raw);
          const s = parseSuggestionsFence(c.display);
          assistantMsg.content = s.display;
          if (c.citations) assistantMsg.retrieverResources = c.citations;
          if (s.suggestions) assistantMsg.suggestions = s.suggestions;
          if (event.message_id && assistantMsg.id !== event.message_id) {
            assistantMsg.id = event.message_id;
          }
          messages = [...messages.slice(0, -1), { ...assistantMsg }];
          await tick();
          if (messagesContainer) scrollToBottom(messagesContainer);
        }

        // Hoist the new-conversation hydration so message_end AND error paths
        // both add the thread to the sidebar. The backend now saves the user
        // prompt + assistant reply even on refusal/block paths, so the sidebar
        // should reflect that work regardless of how the turn ended.
        const hydrateIfNew = (newId?: string) => {
          if (!newId || chatId) return;
          chatId = newId;
          chatTitle = generateTitle(text);
          currentChatId.set(chatId);
          const newConv: Conversation = {
            id: chatId,
            name: chatTitle,
            courseId,
            createdAt: Date.now(),
            updatedAt: Date.now()
          };
          conversations.update((list) => [newConv, ...list]);
          // Update the URL silently — don't use goto(), which re-runs the
          // SvelteKit route and would remount ChatWindow mid-stream.
          if (typeof window !== 'undefined') {
            window.history.replaceState(null, '', `/c/${chatId}`);
          }
        };

        if (event.event === 'message_end') {
          hydrateIfNew(event.conversation_id);
          // Bump this conversation to the top of the sidebar since it
          // just got new activity. hydrateIfNew already prepends for
          // newly-created chats; this handles the existing-chat case.
          if (event.conversation_id) {
            conversations.update((list) => {
              const idx = list.findIndex((c) => c.id === event.conversation_id);
              if (idx <= 0) return list;
              const next = [...list];
              const [moved] = next.splice(idx, 1);
              moved.updatedAt = Date.now();
              next.unshift(moved);
              return next;
            });
          }
          const serverResources = event.metadata?.retriever_resources ?? null;
          if (assistantMsg.retrieverResources) {
            // LLM emitted a fence — enrich its citations with doc_id
            // from the server's retriever metadata so badges are clickable.
            assistantMsg.retrieverResources = enrichWithDocIds(
              assistantMsg.retrieverResources,
              serverResources
            );
          } else if (serverResources) {
            // LLM forgot the fence — fall back entirely to server metadata.
            assistantMsg.retrieverResources = serverResources;
          }
          messages = [...messages.slice(0, -1), { ...assistantMsg }];
        }

        if (event.event === 'error') {
          hydrateIfNew(event.conversation_id);
          assistantMsg.error = event.message ?? 'An error occurred';
          messages = [...messages.slice(0, -1), { ...assistantMsg }];
          toast.error(event.message ?? 'An error occurred');
        }
      }

      assistantMsg.done = true;
      messages = [...messages.slice(0, -1), { ...assistantMsg }];
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to send message';
      assistantMsg.error = errorMsg;
      assistantMsg.done = true;
      messages = [...messages.slice(0, -1), { ...assistantMsg }];
      toast.error(errorMsg);
    } finally {
      loading = false;
    }
  }

  function handleStop() {
    loading = false;
  }

  function handleSuggestionClick(text: string) {
    handleSubmit(text);
  }
</script>

<div bind:this={splitContainer} class="h-full max-h-[100dvh] flex">
  <!-- Chat column (narrows when the PDF panel is open) -->
  <div class="h-full flex-1 min-w-0 flex flex-col">
    <Navbar title={chatTitle} />

    <!-- Messages area -->
    <div
      bind:this={messagesContainer}
      class="flex-1 overflow-y-auto scrollbar-hidden"
    >
      {#if messages.length === 0}
        <Placeholder onSuggestionClick={handleSuggestionClick} />
      {:else}
        <Messages {messages} onAskSuggestion={handleSubmit} />
      {/if}
    </div>

    <!-- Input pinned to bottom -->
    <MessageInput
      bind:value={inputValue}
      onsubmit={handleSubmit}
      {loading}
      onstop={handleStop}
    />
  </div>

  <!-- Right-side PDF viewer panel (resizable) -->
  {#if $pdfViewerRequest}
    <!-- Drag gutter -->
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize viewer"
      class="hidden md:flex shrink-0 w-1.5 cursor-col-resize items-stretch bg-gray-200 dark:bg-gray-800 hover:bg-blue-400 dark:hover:bg-blue-500 transition
             {isResizing ? 'bg-blue-500' : ''}"
      onmousedown={startResize}
      ondblclick={() => (viewerPct = 50)}
      title="Drag to resize · double-click to reset"
    ></div>
    <div class="h-full hidden md:block shrink-0" style="flex-basis: {viewerPct}%">
      <PdfViewer
        docId={$pdfViewerRequest.docId}
        title={$pdfViewerRequest.title}
        page={$pdfViewerRequest.page ?? 1}
        highlight={$pdfViewerRequest.highlight ?? ''}
        onclose={closePdfViewer}
      />
    </div>
  {/if}
</div>
