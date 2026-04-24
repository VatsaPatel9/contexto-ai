<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { theme, mobile, showSidebar } from '$lib/stores';
  import { authStore, refreshAuthState } from '$lib/stores/auth';
  import { initSuperTokens } from '$lib/auth/supertokens';
  import { Toaster } from 'svelte-sonner';
  import Sidebar from '$lib/components/layout/Sidebar.svelte';

  let { children } = $props();
  let ready = $state(false);

  onMount(() => {
    // Initialize SuperTokens SDK
    initSuperTokens();

    // Check current session (fire-and-forget async)
    refreshAuthState().then(() => { ready = true; });

    const checkMobile = () => {
      mobile.set(window.innerWidth < 768);
      if (window.innerWidth < 768) {
        showSidebar.set(false);
      }
    };
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  });

  // Public pages that don't require auth
  const publicPaths = ['/', '/login'];

  $effect(() => {
    if (!ready) return;
    const auth = $authStore;
    const currentPath = $page.url.pathname;
    const isPublicPage = publicPaths.includes(currentPath);

    // Unauthenticated users on protected pages → login
    if (auth.initialized && !auth.authenticated && !isPublicPage) {
      goto('/login');
    }
    // Authenticated users on login page → chat
    if (auth.initialized && auth.authenticated && currentPath === '/login') {
      goto('/chat');
    }
  });

  // Apply theme exactly like Open WebUI
  function applyTheme(t: string) {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const metaThemeColor = document.querySelector('meta[name="theme-color"]');

    // Determine effective theme class
    let themeClass: 'dark' | 'light';
    if (t === 'system') {
      themeClass = prefersDark ? 'dark' : 'light';
    } else if (t === 'oled-dark' || t === 'dark') {
      themeClass = 'dark';
    } else {
      themeClass = 'light';
    }

    // Remove all theme classes, add the right one
    document.documentElement.classList.remove('dark', 'light');
    document.documentElement.classList.add(themeClass);

    // Set gray color vars for dark mode (matches Open WebUI exactly)
    if (themeClass === 'dark' && t === 'oled-dark') {
      document.documentElement.style.setProperty('--color-gray-800', '#101010');
      document.documentElement.style.setProperty('--color-gray-850', '#050505');
      document.documentElement.style.setProperty('--color-gray-900', '#000000');
      document.documentElement.style.setProperty('--color-gray-950', '#000000');
      metaThemeColor?.setAttribute('content', '#000000');
    } else if (themeClass === 'dark') {
      document.documentElement.style.setProperty('--color-gray-800', '#333');
      document.documentElement.style.setProperty('--color-gray-850', '#262626');
      document.documentElement.style.setProperty('--color-gray-900', '#171717');
      document.documentElement.style.setProperty('--color-gray-950', '#0d0d0d');
      metaThemeColor?.setAttribute('content', '#171717');
    } else {
      // Light mode — remove custom properties
      document.documentElement.style.removeProperty('--color-gray-800');
      document.documentElement.style.removeProperty('--color-gray-850');
      document.documentElement.style.removeProperty('--color-gray-900');
      document.documentElement.style.removeProperty('--color-gray-950');
      metaThemeColor?.setAttribute('content', '#ffffff');
    }

    localStorage.setItem('theme', t);
  }

  $effect(() => {
    if (!ready) return;
    applyTheme($theme);
  });
</script>

<script lang="ts" module>
  // Paths that should render the app chrome-free (no sidebar, no
  // navbar, etc.) even for authenticated users. Keeps signup and
  // the email-verification flow looking like a real auth page.
  const CHROMELESS_PREFIXES = ['/login', '/auth/'];
</script>

{#if ready}
  <Toaster richColors position="top-right" />

  {@const pathname = $page.url.pathname}
  {@const chromeless = CHROMELESS_PREFIXES.some((p) =>
    p.endsWith('/') ? pathname.startsWith(p) : pathname === p
  )}

  {#if $authStore.authenticated && !chromeless}
    <div class="app relative text-gray-700 dark:text-gray-100 bg-white dark:bg-gray-900
                h-screen max-h-[100dvh] overflow-auto flex flex-row">
      <Sidebar />
      <div class="w-full flex-1 flex flex-col overflow-hidden">
        {@render children()}
      </div>
    </div>
  {:else}
    {@render children()}
  {/if}
{:else}
  <div class="flex items-center justify-center h-screen bg-white dark:bg-gray-900">
    <p class="text-gray-400 text-sm">Loading...</p>
  </div>
{/if}
