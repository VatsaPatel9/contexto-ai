<script lang="ts">
  import { onMount } from 'svelte';
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';
  import CodeBlock from './CodeBlock.svelte';

  let { content = '' }: { content: string } = $props();

  let htmlContent = $state('');
  let container: HTMLDivElement;

  // Custom renderer to handle code blocks specially
  const renderer = new marked.Renderer();

  // Override code block rendering — we insert a placeholder that we replace with Svelte components
  const codeBlocks: Array<{ lang: string; code: string }> = [];

  // @ts-ignore — marked v9 uses token-based renderer, type mismatch with @types
  renderer.code = function (token: { text: string; lang?: string }) {
    const index = codeBlocks.length;
    codeBlocks.push({ lang: token.lang ?? '', code: token.text });
    return `<div data-codeblock="${index}"></div>`;
  };

  // Configure marked
  marked.setOptions({
    renderer,
    gfm: true,
    breaks: true
  });

  // Strip all citation artifacts from the backend's response.
  // The backend injects [Source: title, Section: X, p.Y] markers into stored text.
  // The LLM sometimes also generates partial fragments like ", p.3]" on its own.
  // Citations are displayed separately as badges in ResponseMessage.
  function stripCitations(text: string): string {
    // 1. Full citations: [Source: anything]
    text = text.replace(/\s*\[Source:\s*[^\]]*\]/g, '');
    // 2. Orphan fragments: ", p.N]" or " p.N]" — the LLM breaks citations across tokens.
    //    Only eat comma/space before "p.", not sentence-ending periods.
    text = text.replace(/[,\s]+p\.\d+\]/g, '');
    // 3. If period directly precedes "p.N]" (like "networks., p.3]" already partly stripped),
    //    we may have "networks." left which is correct. But "networks, p.3]" → "networks" missing period.
    //    So also catch the bare ", p.N]" that follows a period: "., p.3]" → "."
    text = text.replace(/\.\s*,\s*p\.\d+\]/g, '.');
    // 4. Leftover hanging ", Section: ..." without closing bracket (rare)
    text = text.replace(/,\s*Section:\s*[^,\]]*(?:,\s*p\.\d+)?/g, '');
    return text;
  }

  // Fix numbered lists that are crammed on one line without line breaks.
  // e.g. "1. **Foo** - desc 2. **Bar** - desc" → separate lines
  function fixNumberedLists(text: string): string {
    // Insert newline before numbered items that follow text (not at start of line)
    return text.replace(/(?<!\n)(\s)(\d+\.\s+\*\*)/g, '\n\n$2');
  }

  // Process KaTeX math (inline $...$ and display $$...$$)
  function preprocessMath(text: string): string {
    // Display math: $$...$$
    text = text.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => {
      return `<div class="katex-display" data-math-display="${encodeURIComponent(math)}"></div>`;
    });
    // Inline math: $...$  (not preceded/followed by $)
    text = text.replace(/(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)/g, (_, math) => {
      return `<span data-math-inline="${encodeURIComponent(math)}"></span>`;
    });
    return text;
  }

  function render() {
    codeBlocks.length = 0;
    let processed = stripCitations(content);
    processed = fixNumberedLists(processed);
    processed = preprocessMath(processed);
    const raw = marked.parse(processed) as string;
    htmlContent = DOMPurify.sanitize(raw, {
      ADD_TAGS: ['div', 'span'],
      ADD_ATTR: ['data-codeblock', 'data-math-display', 'data-math-inline']
    });
  }

  $effect(() => {
    void content;
    render();
  });

  // After HTML renders, mount CodeBlock components and render KaTeX
  $effect(() => {
    void htmlContent;
    if (!container) return;

    // Mount code blocks
    container.querySelectorAll('[data-codeblock]').forEach((el) => {
      const index = parseInt(el.getAttribute('data-codeblock') ?? '0');
      const block = codeBlocks[index];
      if (!block) return;

      const wrapper = document.createElement('div');
      el.replaceWith(wrapper);

      // Create a simple highlighted code block via DOM
      const pre = document.createElement('pre');
      const code = document.createElement('code');
      code.className = block.lang ? `language-${block.lang}` : '';
      code.textContent = block.code;
      pre.appendChild(code);
      pre.className =
        'rounded-lg bg-gray-900 text-gray-100 p-4 overflow-x-auto text-sm my-3 relative';

      // Language label
      if (block.lang) {
        const label = document.createElement('div');
        label.className =
          'absolute top-0 left-0 right-0 flex items-center justify-between px-4 py-1.5 text-xs text-gray-400 bg-gray-800 rounded-t-lg';
        label.textContent = block.lang;
        pre.style.paddingTop = '2.5rem';
        pre.insertBefore(label, code);
      }

      wrapper.appendChild(pre);

      // Highlight with highlight.js if available
      import('highlight.js').then((hljs) => {
        if (block.lang && hljs.default.getLanguage(block.lang)) {
          code.innerHTML = hljs.default.highlight(block.code, { language: block.lang }).value;
        } else {
          code.innerHTML = hljs.default.highlightAuto(block.code).value;
        }
      }).catch(() => {
        // highlight.js not available, show plain text
      });
    });

    // Render KaTeX math
    const renderKatex = async () => {
      try {
        const katex = (await import('katex')).default;
        await import('katex/dist/katex.min.css');

        container.querySelectorAll('[data-math-display]').forEach((el) => {
          const math = decodeURIComponent(el.getAttribute('data-math-display') ?? '');
          try {
            el.innerHTML = katex.renderToString(math, { displayMode: true, throwOnError: false });
          } catch {
            el.textContent = math;
          }
        });

        container.querySelectorAll('[data-math-inline]').forEach((el) => {
          const math = decodeURIComponent(el.getAttribute('data-math-inline') ?? '');
          try {
            el.innerHTML = katex.renderToString(math, { displayMode: false, throwOnError: false });
          } catch {
            el.textContent = math;
          }
        });
      } catch {
        // KaTeX not available
      }
    };

    renderKatex();
  });
</script>

<div bind:this={container} class="markdown-content">
  {@html htmlContent}
</div>

<style>
  .markdown-content :global(h1) {
    font-size: 1.5em;
    font-weight: 700;
    margin: 1em 0 0.5em;
  }
  .markdown-content :global(h2) {
    font-size: 1.25em;
    font-weight: 600;
    margin: 0.8em 0 0.4em;
  }
  .markdown-content :global(h3) {
    font-size: 1.1em;
    font-weight: 600;
    margin: 0.6em 0 0.3em;
  }
  .markdown-content :global(p) {
    margin: 0.5em 0;
  }
  .markdown-content :global(ul),
  .markdown-content :global(ol) {
    padding-left: 1.5em;
    margin: 0.5em 0;
  }
  .markdown-content :global(li) {
    margin: 0.2em 0;
  }
  .markdown-content :global(code:not(pre code)) {
    background: rgba(0, 0, 0, 0.06);
    border-radius: 4px;
    padding: 0.15em 0.3em;
    font-size: 0.9em;
  }
  :global(.dark) .markdown-content :global(code:not(pre code)) {
    background: rgba(255, 255, 255, 0.1);
  }
  .markdown-content :global(blockquote) {
    border-left: 3px solid #d1d5db;
    padding-left: 1em;
    margin: 0.5em 0;
    color: #6b7280;
  }
  :global(.dark) .markdown-content :global(blockquote) {
    border-left-color: #4b5563;
    color: #9ca3af;
  }
  .markdown-content :global(table) {
    border-collapse: collapse;
    width: 100%;
    margin: 0.5em 0;
  }
  .markdown-content :global(th),
  .markdown-content :global(td) {
    border: 1px solid #d1d5db;
    padding: 0.4em 0.8em;
    text-align: left;
  }
  :global(.dark) .markdown-content :global(th),
  :global(.dark) .markdown-content :global(td) {
    border-color: #4b5563;
  }
  .markdown-content :global(th) {
    background: rgba(0, 0, 0, 0.04);
    font-weight: 600;
  }
  :global(.dark) .markdown-content :global(th) {
    background: rgba(255, 255, 255, 0.05);
  }
  .markdown-content :global(a) {
    color: #3b82f6;
    text-decoration: underline;
  }
  .markdown-content :global(a:hover) {
    color: #2563eb;
  }
  .markdown-content :global(hr) {
    border-color: #e5e7eb;
    margin: 1em 0;
  }
  :global(.dark) .markdown-content :global(hr) {
    border-color: #374151;
  }
</style>
