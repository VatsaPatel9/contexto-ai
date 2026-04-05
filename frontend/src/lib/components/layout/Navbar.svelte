<script lang="ts">
  import { showSidebar, theme } from '$lib/stores';

  let { title = 'New Chat' }: { title?: string } = $props();
  let showThemeMenu = $state(false);

  function toggleSidebar() {
    showSidebar.update((v) => !v);
  }

  function setTheme(t: string) {
    theme.set(t);
    showThemeMenu = false;
  }

  const themes = [
    { id: 'system', label: 'System' },
    { id: 'light', label: 'Light' },
    { id: 'dark', label: 'Dark' },
    { id: 'oled-dark', label: 'OLED Dark' }
  ];
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->

<!-- Sticky top bar matching Open WebUI -->
<div class="sticky top-0 z-30 w-full">
  <div class="flex items-center px-4 py-2.5">
    <!-- Sidebar toggle -->
    <button
      onclick={toggleSidebar}
      class="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition"
      title="Toggle sidebar"
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="size-5 text-gray-600 dark:text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="3" y1="6" x2="21" y2="6" />
        <line x1="3" y1="12" x2="21" y2="12" />
        <line x1="3" y1="18" x2="21" y2="18" />
      </svg>
    </button>

    <!-- Title -->
    <h1 class="flex-1 text-sm font-medium truncate text-gray-700 dark:text-gray-100 mx-3">
      {title}
    </h1>

    <!-- Theme toggle -->
    <div class="relative">
      <button
        onclick={() => showThemeMenu = !showThemeMenu}
        class="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition
               text-gray-600 dark:text-gray-400"
        title="Theme"
      >
        {#if $theme === 'dark' || $theme === 'oled-dark'}
          <!-- Moon -->
          <svg xmlns="http://www.w3.org/2000/svg" class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        {:else if $theme === 'light'}
          <!-- Sun -->
          <svg xmlns="http://www.w3.org/2000/svg" class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="5" />
            <line x1="12" y1="1" x2="12" y2="3" />
            <line x1="12" y1="21" x2="12" y2="23" />
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
            <line x1="1" y1="12" x2="3" y2="12" />
            <line x1="21" y1="12" x2="23" y2="12" />
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
          </svg>
        {:else}
          <!-- Monitor (system) -->
          <svg xmlns="http://www.w3.org/2000/svg" class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="17" x2="12" y2="21" />
          </svg>
        {/if}
      </button>

      <!-- Theme dropdown -->
      {#if showThemeMenu}
        <div
          class="fixed inset-0 z-40"
          onclick={() => showThemeMenu = false}
        ></div>
        <div class="absolute right-0 mt-1 z-50 w-40 py-1 rounded-xl
                    bg-white dark:bg-gray-850 border border-gray-100 dark:border-gray-800
                    shadow-lg">
          {#each themes as t}
            <button
              onclick={() => setTheme(t.id)}
              class="w-full px-3 py-2 text-left text-sm flex items-center gap-2
                     hover:bg-gray-50 dark:hover:bg-gray-800 transition
                     {$theme === t.id ? 'text-gray-900 dark:text-white font-medium' : 'text-gray-600 dark:text-gray-400'}"
            >
              {#if t.id === 'system'}
                <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                  <line x1="8" y1="21" x2="16" y2="21" />
                  <line x1="12" y1="17" x2="12" y2="21" />
                </svg>
              {:else if t.id === 'light'}
                <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="5" />
                  <line x1="12" y1="1" x2="12" y2="3" />
                  <line x1="12" y1="21" x2="12" y2="23" />
                  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                  <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                  <line x1="1" y1="12" x2="3" y2="12" />
                  <line x1="21" y1="12" x2="23" y2="12" />
                  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                  <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                </svg>
              {:else if t.id === 'dark'}
                <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
              {:else}
                <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="4" />
                </svg>
              {/if}
              {t.label}
              {#if $theme === t.id}
                <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5 ml-auto" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              {/if}
            </button>
          {/each}
        </div>
      {/if}
    </div>
  </div>
</div>
