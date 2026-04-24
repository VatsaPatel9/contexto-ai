<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
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

  let canvasEl: HTMLCanvasElement;
  let textLayerEl: HTMLDivElement;
  let errorText = $state<string | null>(null);
  let loading = $state(true);
  let currentPage = $state(page);
  let totalPages = $state(0);
  let scale = $state(1.25);

  // Keep the pdfjs module and loaded document around for page navigation.
  // Dynamically imported so pdfjs-dist only ships when the viewer opens.
  let pdfjs: any = null;
  let pdfDoc: any = null;
  let renderTask: any = null;

  async function loadPdfjs() {
    if (pdfjs) return pdfjs;
    const mod = await import('pdfjs-dist');
    const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default;
    mod.GlobalWorkerOptions.workerSrc = workerUrl;
    pdfjs = mod;
    return mod;
  }

  async function fetchAndOpen() {
    loading = true;
    errorText = null;
    try {
      const lib = await loadPdfjs();
      const { download_url } = await getDocumentSignedUrl(docId);
      pdfDoc = await lib.getDocument({ url: download_url }).promise;
      totalPages = pdfDoc.numPages;
      currentPage = Math.min(Math.max(1, page), totalPages);
      await renderPage(currentPage);
    } catch (e: any) {
      errorText = e?.message || 'Failed to open document';
    } finally {
      loading = false;
    }
  }

  async function renderPage(n: number) {
    if (!pdfDoc || !canvasEl) return;
    if (renderTask) {
      try { renderTask.cancel(); } catch {}
    }
    const pdfPage = await pdfDoc.getPage(n);
    const viewport = pdfPage.getViewport({ scale });

    const ctx = canvasEl.getContext('2d');
    canvasEl.width = viewport.width;
    canvasEl.height = viewport.height;
    canvasEl.style.width = `${viewport.width}px`;
    canvasEl.style.height = `${viewport.height}px`;

    renderTask = pdfPage.render({ canvasContext: ctx, viewport });
    await renderTask.promise;

    // Best-effort text-layer + highlight. If anything here throws, we
    // still have the rendered page — silent fallback.
    if (textLayerEl) {
      textLayerEl.innerHTML = '';
      textLayerEl.style.width = `${viewport.width}px`;
      textLayerEl.style.height = `${viewport.height}px`;
      try {
        const textContent = await pdfPage.getTextContent();
        const needle = highlight.trim().toLowerCase();
        for (const item of textContent.items as any[]) {
          const str: string = item.str ?? '';
          if (!str) continue;
          const tx = pdfjs.Util.transform(viewport.transform, item.transform);
          const fontSize = Math.hypot(tx[2], tx[3]);
          const span = document.createElement('span');
          span.textContent = str;
          span.style.position = 'absolute';
          span.style.left = `${tx[4]}px`;
          span.style.top = `${tx[5] - fontSize}px`;
          span.style.fontSize = `${fontSize}px`;
          span.style.whiteSpace = 'pre';
          span.style.color = 'transparent';
          span.style.pointerEvents = 'none';
          if (needle && str.toLowerCase().includes(needle)) {
            span.style.background = 'rgba(250, 204, 21, 0.45)'; // amber-400/45%
          }
          textLayerEl.appendChild(span);
        }
      } catch {
        // ignore text-layer failures
      }
    }
  }

  async function go(delta: number) {
    const n = Math.min(Math.max(1, currentPage + delta), totalPages);
    if (n === currentPage) return;
    currentPage = n;
    await renderPage(n);
  }

  onMount(fetchAndOpen);

  // Re-render if docId or page prop changes (e.g. user clicks another citation
  // while the viewer is open).
  $effect(() => {
    void docId;
    void page;
    // Only re-fetch when docId changes; page-only changes re-render.
    if (pdfDoc && currentPage !== page) {
      currentPage = Math.min(Math.max(1, page), totalPages || page);
      renderPage(currentPage);
    }
  });

  onDestroy(() => {
    try { renderTask?.cancel(); } catch {}
    try { pdfDoc?.destroy(); } catch {}
  });
</script>

<div class="h-full flex flex-col bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800">
  <!-- Header -->
  <div class="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-800">
    <div class="min-w-0 pr-3">
      <div class="text-sm font-medium truncate text-gray-900 dark:text-gray-100">{title}</div>
      {#if totalPages}
        <div class="text-[11px] text-gray-500 dark:text-gray-400">Page {currentPage} of {totalPages}</div>
      {/if}
    </div>
    <div class="flex items-center gap-1">
      <button
        onclick={() => go(-1)}
        disabled={currentPage <= 1 || loading}
        class="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-30"
        title="Previous page"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6" />
        </svg>
      </button>
      <button
        onclick={() => go(1)}
        disabled={currentPage >= totalPages || loading}
        class="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-30"
        title="Next page"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>
      <button
        onclick={() => onclose?.()}
        class="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 ml-1"
        title="Close"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  </div>

  <!-- Body -->
  <div class="flex-1 overflow-auto bg-gray-100 dark:bg-gray-950 flex items-start justify-center p-4">
    {#if errorText}
      <div class="text-sm text-red-500 max-w-sm text-center mt-10">{errorText}</div>
    {:else if loading}
      <div class="flex items-center gap-2 text-sm text-gray-500 mt-10">
        <div class="size-4 rounded-full border-2 border-gray-400 border-t-transparent animate-spin"></div>
        Loading PDF…
      </div>
    {/if}
    <div class="relative inline-block" class:hidden={errorText || loading}>
      <canvas bind:this={canvasEl} class="shadow-md"></canvas>
      <div bind:this={textLayerEl} class="absolute top-0 left-0 origin-top-left"></div>
    </div>
  </div>
</div>
