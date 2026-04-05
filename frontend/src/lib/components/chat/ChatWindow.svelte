<script lang="ts">
  import { tick } from 'svelte';
  import { goto } from '$app/navigation';
  import { toast } from 'svelte-sonner';

  import {
    session,
    currentChatId,
    conversations,
    type ChatMessage,
    type Conversation
  } from '$lib/stores';
  import {
    sendChatMessage,
    getMessages,
    getConversation,
    type ApiMessage
  } from '$lib/apis/contexto';
  import { generateId, generateTitle, scrollToBottom } from '$lib/utils';

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

  // React to chatId changes (handles both initial mount AND navigation between chats)
  $effect(() => {
    const id = chatId;
    if (id) {
      currentChatId.set(id);
      messages = [];
      chatTitle = 'Loading...';
      loading = false;
      loadConversation(id);
    } else {
      currentChatId.set(null);
      messages = [];
      chatTitle = 'New Chat';
    }
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

  function apiMessageToChat(msg: ApiMessage): ChatMessage {
    return {
      id: msg.id,
      role: msg.role,
      content: msg.content,
      timestamp: msg.created_at * 1000,
      messageType: msg.message_type,
      done: true,
      retrieverResources: msg.retriever_resources
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
          assistantMsg.content += event.answer ?? '';
          if (event.message_id && assistantMsg.id !== event.message_id) {
            assistantMsg.id = event.message_id;
          }
          messages = [...messages.slice(0, -1), { ...assistantMsg }];
          await tick();
          if (messagesContainer) scrollToBottom(messagesContainer);
        }

        if (event.event === 'message_end') {
          if (event.conversation_id && !chatId) {
            chatId = event.conversation_id;
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
            goto(`/c/${chatId}`, { replaceState: true });
          }
          if (event.metadata?.retriever_resources) {
            assistantMsg.retrieverResources = event.metadata.retriever_resources;
          }
        }

        if (event.event === 'error') {
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

<div class="h-full max-h-[100dvh] flex flex-col">
  <Navbar title={chatTitle} />

  <!-- Messages area -->
  <div
    bind:this={messagesContainer}
    class="flex-1 overflow-y-auto scrollbar-hidden"
  >
    {#if messages.length === 0}
      <Placeholder onSuggestionClick={handleSuggestionClick} />
    {:else}
      <Messages {messages} />
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
