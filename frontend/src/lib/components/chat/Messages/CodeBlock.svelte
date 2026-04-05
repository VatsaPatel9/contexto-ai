<script lang="ts">
  import { onMount } from 'svelte';
  import { copyToClipboard } from '$lib/utils';
  import { toast } from 'svelte-sonner';

  let { lang = '', code = '' }: { lang?: string; code?: string } = $props();

  let codeEl: HTMLElement;
  let copied = $state(false);

  onMount(async () => {
    try {
      const hljs = (await import('highlight.js')).default;
      if (lang && hljs.getLanguage(lang)) {
        codeEl.innerHTML = hljs.highlight(code, { language: lang }).value;
      } else {
        codeEl.innerHTML = hljs.highlightAuto(code).value;
      }
    } catch {
      // Fallback: plain text
    }
  });

  async function handleCopy() {
    const ok = await copyToClipboard(code);
    if (ok) {
      copied = true;
      toast.success('Code copied');
      setTimeout(() => (copied = false), 2000);
    }
  }
</script>

<div class="relative rounded-lg bg-gray-900 text-gray-100 my-3 overflow-hidden">
  {#if lang}
    <div class="flex items-center justify-between px-4 py-1.5 text-xs text-gray-400 bg-gray-800">
      <span>{lang}</span>
      <button
        onclick={handleCopy}
        class="hover:text-gray-200 transition-colors"
      >
        {copied ? 'Copied!' : 'Copy'}
      </button>
    </div>
  {/if}
  <pre class="p-4 overflow-x-auto text-sm"><code bind:this={codeEl} class={lang ? `language-${lang}` : ''}>{code}</code></pre>
</div>
