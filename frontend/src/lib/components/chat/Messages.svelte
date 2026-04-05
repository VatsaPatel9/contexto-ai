<script lang="ts">
  import type { ChatMessage } from '$lib/stores';
  import UserMessage from './Messages/UserMessage.svelte';
  import ResponseMessage from './Messages/ResponseMessage.svelte';

  let { messages }: { messages: ChatMessage[] } = $props();
</script>

<div class="h-full flex">
  <div class="w-full pt-2">
    <div class="max-w-3xl mx-auto w-full px-5 md:px-6">
      {#each messages as message (message.id)}
        <div class="w-full" style="scroll-margin-top: 3rem;">
          {#if message.role === 'user'}
            <UserMessage {message} />
          {:else}
            <ResponseMessage {message} />
          {/if}
        </div>
      {/each}
    </div>
    <!-- Bottom padding to keep content above the input -->
    <div class="pb-18"></div>
    <div class="pb-6"></div>
  </div>
</div>
