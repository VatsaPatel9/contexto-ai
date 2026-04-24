<script lang="ts">
  import { page } from '$app/stores';
  import ChatWindow from '$lib/components/chat/ChatWindow.svelte';
</script>

<ChatWindow chatId={$page.params.id} />
