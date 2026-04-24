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

  // Horizontal padding applied to the pages column (tailwind px-2 = 0.5rem
  // each side = 16px total). Used to derive available CSS width per page.
  const COLUMN_PADDING = 16;
  const MIN_PAGE_WIDTH = 200;
  const MAX_PAGE_WIDTH = 1400;

  let containerEl: HTMLDivElement;
  let pageEls: HTMLDivElement[] = $state([]);
  let aspectRatios: number[] = $state([]); // height / width per page
  let pageWidth = $state(720); // CSS width — tracked from ResizeObserver
  let errorText = $state<string | null>(null);
  let loading = $state(true);
  let currentPage = $state(page);

  let pdfjs: any = null;
  let pdfDoc: any = null;
  // Two observers: one with a large rootMargin to lazy-render pages just
  // before they scroll into view, and a second with zero rootMargin to
  // track which page is actually visible for the "Page N of M" header.
  let renderObserver: IntersectionObserver | null = null;
  let activeObserver: IntersectionObserver | null = null;
  let visibility = new Map<number, number>();
  let resizeObserver: ResizeObserver | null = null;
  let rendered = new Set<number>();
  let inflight = new Set<number>();
  let resizeTimer: ReturnType<typeof setTimeout> | null = null;

  let dims = $derived(
    aspectRatios.map((ar) => ({
      w: pageWidth,
      h: ar * pageWidth,
    }))
  );

  async function loadPdfjs() {
    if (pdfjs) return pdfjs;
    const mod = await import('pdfjs-dist');
    // Vite's `?worker` suffix bundles the target as a Web Worker — avoids
    // MIME/cache issues with serving the raw .mjs through nginx.
    const { default: PdfWorker } = await import(
      'pdfjs-dist/build/pdf.worker.min.mjs?worker'
    );
    mod.GlobalWorkerOptions.workerPort = new PdfWorker();
    pdfjs = mod;
    return mod;
  }

  function measureWidth() {
    if (!containerEl) return pageWidth;
    const w = containerEl.clientWidth - COLUMN_PADDING;
    return Math.max(MIN_PAGE_WIDTH, Math.min(MAX_PAGE_WIDTH, w));
  }

  async function setupDocument() {
    loading = true;
    errorText = null;
    try {
      const lib = await loadPdfjs();
      const { download_url } = await getDocumentSignedUrl(docId);
      pdfDoc = await lib.getDocument({ url: download_url }).promise;

      // Prefetch aspect ratios only — page widths are derived from the
      // measured container width, so placeholders can lay out before any
      // canvas rasterizes.
      const ars: number[] = [];
      for (let i = 1; i <= pdfDoc.numPages; i++) {
        const p = await pdfDoc.getPage(i);
        const vp = p.getViewport({ scale: 1 });
        ars.push(vp.height / vp.width);
      }
      aspectRatios = ars;
      pageWidth = measureWidth();
      loading = false;

      await tick();
      setupObservers();
      setupResizeObserver();
      scrollToTarget();
      // Seed the header with the target page so the UI doesn't flash
      // "Page 1 of N" before the active-observer callback fires.
      currentPage = Math.max(1, Math.min(page, aspectRatios.length));
    } catch (e: any) {
      errorText = e?.message || 'Failed to open document';
      loading = false;
    }
  }

  function setupObservers() {
    if (!containerEl) return;
    try { renderObserver?.disconnect(); } catch {}
    try { activeObserver?.disconnect(); } catch {}
    visibility.clear();

    // Lazy render: fire when a page is near the viewport.
    renderObserver = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          const idx = Number((e.target as HTMLElement).dataset.pageIdx);
          if (!Number.isFinite(idx)) continue;
          if (!rendered.has(idx + 1) && !inflight.has(idx + 1)) {
            renderPage(idx + 1);
          }
        }
      },
      { root: containerEl, rootMargin: '200px 0px', threshold: 0 }
    );

    // Current-page tracking: strict viewport, track each page's visible
    // ratio and pick the max. Uses a fine-grained threshold set so the
    // ratio updates on scroll.
    activeObserver = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const idx = Number((e.target as HTMLElement).dataset.pageIdx);
          if (!Number.isFinite(idx)) continue;
          visibility.set(idx + 1, e.intersectionRatio);
        }
        let bestPage = currentPage;
        let bestRatio = -1;
        for (const [p, r] of visibility) {
          if (r > bestRatio) {
            bestRatio = r;
            bestPage = p;
          }
        }
        if (bestRatio > 0) currentPage = bestPage;
      },
      { root: containerEl, rootMargin: '0px', threshold: [0, 0.1, 0.25, 0.5, 0.75, 1.0] }
    );

    for (const el of pageEls) {
      if (!el) continue;
      renderObserver.observe(el);
      activeObserver.observe(el);
    }
  }

  function setupResizeObserver() {
    if (!containerEl) return;
    try { resizeObserver?.disconnect(); } catch {}
    resizeObserver = new ResizeObserver(() => {
      const w = measureWidth();
      // Debounce: ignore sub-4px noise and rapid drags.
      if (Math.abs(w - pageWidth) < 4) return;
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        pageWidth = w;
        handleWidthChange();
      }, 80);
    });
    resizeObserver.observe(containerEl);
  }

  // Called after pageWidth changes: clear rasterized state so visible pages
  // re-render at the new CSS size (and therefore new canvas resolution).
  function handleWidthChange() {
    rendered = new Set();
    inflight = new Set();
    for (const el of pageEls) {
      if (!el) continue;
      const c = el.querySelector('canvas') as HTMLCanvasElement | null;
      const tl = el.querySelector('.text-layer') as HTMLDivElement | null;
      if (c) { c.width = 0; c.height = 0; }
      if (tl) tl.innerHTML = '';
    }
    // Reconnect observers so the render-observer fires for currently-
    // visible pages and active-observer resets its ratio map.
    setupObservers();
  }

  async function renderPage(n: number) {
    if (!pdfDoc || rendered.has(n) || inflight.has(n)) return;
    inflight.add(n);
    try {
      const pdfPage = await pdfDoc.getPage(n);
      const rawVp = pdfPage.getViewport({ scale: 1 });
      const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1;
      // Scale native PDF coords up to (CSS width × DPR) so the canvas
      // matches the current display size with HiDPI-crisp pixels.
      const renderScale = (pageWidth * dpr) / rawVp.width;
      const vp = pdfPage.getViewport({ scale: renderScale });

      const wrap = pageEls[n - 1];
      if (!wrap) return;
      const canvas = wrap.querySelector('canvas') as HTMLCanvasElement | null;
      const textLayer = wrap.querySelector('.text-layer') as HTMLDivElement | null;
      if (!canvas) return;

      canvas.width = vp.width;
      canvas.height = vp.height;
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
          // Text layer CSS space = pageWidth × (pageWidth * aspect).
          // Use a CSS-scale viewport (scale = pageWidth / rawVp.width).
          const cssScale = pageWidth / rawVp.width;
          const cssVp = pdfPage.getViewport({ scale: cssScale });
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
              span.style.background = 'rgba(250, 204, 21, 0.45)';
            }
            textLayer.appendChild(span);
          }
        } catch {
          // text layer is best-effort
        }
      }

      rendered.add(n);
    } finally {
      inflight.delete(n);
    }
  }

  function scrollToTarget() {
    if (!containerEl) return;
    const idx = Math.max(0, Math.min(page - 1, aspectRatios.length - 1));
    const el = pageEls[idx];
    if (el) el.scrollIntoView({ block: 'start', behavior: 'auto' });
  }

  onMount(setupDocument);

  // User clicked a different citation while the viewer is already open.
  $effect(() => {
    void docId;
    if (!pdfjs) return;
    rendered = new Set();
    inflight = new Set();
    visibility = new Map();
    aspectRatios = [];
    pageEls = [];
    try { renderObserver?.disconnect(); } catch {}
    try { activeObserver?.disconnect(); } catch {}
    try { resizeObserver?.disconnect(); } catch {}
    try { pdfDoc?.destroy(); } catch {}
    setupDocument();
  });

  onDestroy(() => {
    if (resizeTimer) clearTimeout(resizeTimer);
    try { renderObserver?.disconnect(); } catch {}
    try { activeObserver?.disconnect(); } catch {}
    try { resizeObserver?.disconnect(); } catch {}
    try { pdfDoc?.destroy(); } catch {}
  });
</script>

<div class="h-full flex flex-col bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800">
  <!-- Header -->
  <div class="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-800 shrink-0">
    <div class="min-w-0 pr-3">
      <div class="text-sm font-medium truncate text-gray-900 dark:text-gray-100">{title}</div>
      {#if aspectRatios.length}
        <div class="text-[11px] text-gray-500 dark:text-gray-400">Page {currentPage} of {aspectRatios.length}</div>
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
  :global(.text-layer span) {
    line-height: 1;
  }
</style>
