<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { getDocumentSignedUrl } from '$lib/apis/documents';

  let {
    docId,
    title,
    page = 1,
    highlight = '',
    onclose,
  }: {
    docId: string;
    title: string;
    page?: number;
    highlight?: string;
    onclose?: () => void;
  } = $props();

  // Fixed CSS width for each page; canvas is rendered at a higher internal
  // resolution so text stays crisp on Hi-DPI screens.
  const PAGE_CSS_WIDTH = 720;
  const RENDER_SCALE = 1.6;

  let containerEl: HTMLDivElement;
  let pageEls: HTMLDivElement[] = $state([]);
  let dims = $state<{ w: number; h: number }[]>([]); // per-page CSS dimensions
  let errorText = $state<string | null>(null);
  let loading = $state(true);
  let currentPage = $state(page);

  let pdfjs: any = null;
  let pdfDoc: any = null;
  let observer: IntersectionObserver | null = null;
  let rendered = new Set<number>();
  let inflight = new Set<number>();

  async function loadPdfjs() {
    if (pdfjs) return pdfjs;
    const mod = await import('pdfjs-dist');
    // Vite's `?worker` suffix compiles the target as a Web Worker. Passing
    // the constructed Worker to pdfjs via `workerPort` bypasses the
    // .mjs MIME dance entirely — Vite serves the worker as a regular
    // bundled JS file.
    const { default: PdfWorker } = await import(
      'pdfjs-dist/build/pdf.worker.min.mjs?worker'
    );
    mod.GlobalWorkerOptions.workerPort = new PdfWorker();
    pdfjs = mod;
    return mod;
  }

  async function setupDocument() {
    loading = true;
    errorText = null;
    try {
      const lib = await loadPdfjs();
      const { download_url } = await getDocumentSignedUrl(docId);
      pdfDoc = await lib.getDocument({ url: download_url }).promise;

      // Prefetch every page's dimensions so we can lay out placeholders
      // at the correct aspect ratio before any canvas renders. Makes the
      // initial scroll stable.
      const out: { w: number; h: number }[] = [];
      for (let i = 1; i <= pdfDoc.numPages; i++) {
        const p = await pdfDoc.getPage(i);
        const vp = p.getViewport({ scale: 1 });
        const w = PAGE_CSS_WIDTH;
        const h = (vp.height / vp.width) * PAGE_CSS_WIDTH;
        out.push({ w, h });
      }
      dims = out;
      loading = false;

      await tick();
      setupObserver();
      scrollToTarget();
    } catch (e: any) {
      errorText = e?.message || 'Failed to open document';
      loading = false;
    }
  }

  function setupObserver() {
    if (!containerEl) return;
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const idx = Number((entry.target as HTMLElement).dataset.pageIdx);
          if (!Number.isFinite(idx)) continue;
          if (entry.isIntersecting) {
            if (!rendered.has(idx + 1) && !inflight.has(idx + 1)) {
              renderPage(idx + 1);
            }
            // Track which page is currently centred for the header display.
            if (entry.intersectionRatio > 0.3) {
              currentPage = idx + 1;
            }
          }
        }
      },
      { root: containerEl, rootMargin: '200px 0px', threshold: [0, 0.3, 0.6] }
    );
    for (const el of pageEls) {
      if (el) observer.observe(el);
    }
  }

  async function renderPage(n: number) {
    if (!pdfDoc || rendered.has(n) || inflight.has(n)) return;
    inflight.add(n);
    try {
      const pdfPage = await pdfDoc.getPage(n);
      const vp = pdfPage.getViewport({ scale: RENDER_SCALE });
      const wrap = pageEls[n - 1];
      if (!wrap) return;
      const canvas = wrap.querySelector('canvas') as HTMLCanvasElement | null;
      const textLayer = wrap.querySelector('.text-layer') as HTMLDivElement | null;
      if (!canvas) return;

      canvas.width = vp.width;
      canvas.height = vp.height;
      // CSS size stays at PAGE_CSS_WIDTH × aspect; internal resolution is
      // vp.width × vp.height (higher). Browser scales the canvas down →
      // sharp rendering on HiDPI.
      canvas.style.width = '100%';
      canvas.style.height = '100%';

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      await pdfPage.render({ canvasContext: ctx, viewport: vp }).promise;

      if (textLayer) {
        textLayer.innerHTML = '';
        try {
          const tc = await pdfPage.getTextContent();
          const needle = highlight.trim().toLowerCase();
          // Text layer is positioned in CSS pixels matching the CSS size.
          // Scale the transform matrix down from render-scale coords to CSS.
          const cssVp = pdfPage.getViewport({ scale: dims[n - 1].w / (vp.width / RENDER_SCALE) });
          for (const item of tc.items as any[]) {
            const str: string = item.str ?? '';
            if (!str.trim()) continue;
            const tx = pdfjs.Util.transform(cssVp.transform, item.transform);
            const fs = Math.hypot(tx[2], tx[3]);
            const span = document.createElement('span');
            span.textContent = str;
            span.style.position = 'absolute';
            span.style.left = `${tx[4]}px`;
            span.style.top = `${tx[5] - fs}px`;
            span.style.fontSize = `${fs}px`;
            span.style.whiteSpace = 'pre';
            span.style.color = 'transparent';
            span.style.pointerEvents = 'none';
            if (needle && str.toLowerCase().includes(needle)) {
              span.style.background = 'rgba(250, 204, 21, 0.45)'; // amber-400/45
            }
            textLayer.appendChild(span);
          }
        } catch {
          // Text-layer failure is non-fatal — canvas still shows.
        }
      }

      rendered.add(n);
    } finally {
      inflight.delete(n);
    }
  }

  function scrollToTarget() {
    if (!containerEl) return;
    const idx = Math.max(0, Math.min(page - 1, dims.length - 1));
    const el = pageEls[idx];
    if (el) el.scrollIntoView({ block: 'start', behavior: 'auto' });
  }

  onMount(setupDocument);

  // If the parent passes a new docId (user clicks a different citation),
  // tear down and reload.
  $effect(() => {
    void docId;
    // Only react after initial mount
    if (!pdfjs) return;
    rendered = new Set();
    inflight = new Set();
    dims = [];
    pageEls = [];
    try { observer?.disconnect(); } catch {}
    try { pdfDoc?.destroy(); } catch {}
    setupDocument();
  });

  onDestroy(() => {
    try { observer?.disconnect(); } catch {}
    try { pdfDoc?.destroy(); } catch {}
  });
</script>

<div class="h-full flex flex-col bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800">
  <!-- Header -->
  <div class="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-800 shrink-0">
    <div class="min-w-0 pr-3">
      <div class="text-sm font-medium truncate text-gray-900 dark:text-gray-100">{title}</div>
      {#if dims.length}
        <div class="text-[11px] text-gray-500 dark:text-gray-400">Page {currentPage} of {dims.length}</div>
      {/if}
    </div>
    <button
      onclick={() => onclose?.()}
      class="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
      title="Close"
      aria-label="Close viewer"
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
      </svg>
    </button>
  </div>

  <!-- Scrollable pages -->
  <div
    bind:this={containerEl}
    class="flex-1 overflow-y-auto bg-gray-100 dark:bg-gray-950 py-4 px-2"
  >
    {#if errorText}
      <div class="text-sm text-red-500 max-w-sm text-center mx-auto mt-10">{errorText}</div>
    {:else if loading}
      <div class="flex items-center gap-2 text-sm text-gray-500 justify-center mt-10">
        <div class="size-4 rounded-full border-2 border-gray-400 border-t-transparent animate-spin"></div>
        Loading PDF…
      </div>
    {:else}
      <div class="flex flex-col items-center gap-3">
        {#each dims as d, i}
          <div
            bind:this={pageEls[i]}
            data-page-idx={i}
            class="relative bg-white shadow-md"
            style="width: {d.w}px; height: {d.h}px;"
          >
            <canvas></canvas>
            <div class="text-layer absolute inset-0 origin-top-left pointer-events-none"></div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>

<style>
  /* The text layer sits on top of the canvas at the same CSS size; spans
     inside are absolutely positioned to match the PDF text coordinates. */
  :global(.text-layer span) {
    line-height: 1;
  }
</style>
