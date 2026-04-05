<script lang="ts">
  import type { ChatMessage } from '$lib/stores';

  let { message }: { message: ChatMessage } = $props();
</script>

<div class="flex w-full justify-end group" style="scroll-margin-top: 3rem;">
  <div class="max-w-[90%] rounded-3xl px-4 py-1.5 bg-gray-50 dark:bg-gray-850">
    <div class="text-[15px] text-gray-800 dark:text-gray-100 whitespace-pre-wrap">
      {message.content}
    </div>
  </div>
</div>
