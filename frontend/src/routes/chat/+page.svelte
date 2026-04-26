<script lang="ts">
  import ChatWindow from '$lib/components/chat/ChatWindow.svelte';
  import { newChatNonce } from '$lib/stores';
</script>

{#key $newChatNonce}
  <ChatWindow />
{/key}
