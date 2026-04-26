<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { toast } from 'svelte-sonner';
  import dayjs from 'dayjs';

  import {
    session,
    conversations,
    conversationsLoaded,
    showSidebar,
    mobile,
    currentChatId,
    newChatNonce,
    adminCounts,
    type Conversation
  } from '$lib/stores';
  import { authStore, logout, getDisplayLabel } from '$lib/stores/auth';
  import {
    getConversations,
    deleteConversation as apiDeleteConversation
  } from '$lib/apis/contexto';

  let showUserMenu = $state(false);

  // Switch sidebar contents based on the active route. On /admin we render
  // admin nav (Users / Courses / Violations) instead of the chat list, so
  // there's one sidebar — never two stacked panels.
  let isAdminRoute = $derived($page.url.pathname.startsWith('/admin'));
  let isSuperAdmin = $derived($authStore.roles.includes('super_admin'));
  // The course detail route (/admin/courses/:id) is conceptually still
  // the Courses tab, so highlight it when on any /admin/courses/* path.
  // /admin/baseline is its own thing — only super_admins ever see it.
  let activeAdminTab = $derived(
    $page.url.pathname.startsWith('/admin/baseline')
      ? 'baseline'
      : $page.url.pathname.startsWith('/admin/courses')
        ? 'courses'
        : $page.url.searchParams.get('tab') || 'users',
  );

  function gotoAdminTab(tab: 'users' | 'courses' | 'violations') {
    goto(`/admin?tab=${tab}`);
    if ($mobile) showSidebar.set(false);
  }

  function gotoBaseline() {
    goto('/admin/baseline');
    if ($mobile) showSidebar.set(false);
  }

  // Reload conversations when auth state changes (login/logout/user switch)
  $effect(() => {
    const auth = $authStore;
    if (auth.authenticated && !$conversationsLoaded) {
      loadConversations();
    }
  });

  async function loadConversations() {
    try {
      const courseId = session.getCourseId();
      const { data } = await getConversations(courseId);

      const mapped: Conversation[] = data.map((c) => ({
        id: c.id,
        name: c.name,
        courseId: c.course_id,
        createdAt: c.created_at * 1000,
        updatedAt: c.updated_at * 1000
      }));

      // Sort newest-first so first paint matches what user expects.
      // Subsequent updates keep this invariant via the move-to-top in
      // ChatWindow's send / message_end handlers.
      mapped.sort((a, b) => b.updatedAt - a.updatedAt);

      conversations.set(mapped);
      conversationsLoaded.set(true);
    } catch {
      // Backend may be down — that's fine, show empty sidebar
    }
  }

  function newChat() {
    currentChatId.set(null);
    // Bump the nonce so /chat keys its <ChatWindow> on a new value and
    // forces a remount. Without this, clicking + while already on /chat
    // would no-op (goto('/chat') doesn't navigate to the same URL),
    // leaving stale input / scroll / mid-stream state behind.
    newChatNonce.update((n) => n + 1);
    goto('/chat');
    if ($mobile) showSidebar.set(false);
  }

  function openChat(id: string) {
    goto(`/chat/${id}`);
    if ($mobile) showSidebar.set(false);
  }

  async function deleteChat(e: Event, id: string) {
    e.stopPropagation();
    try {
      await apiDeleteConversation(id);
      conversations.update((list) => list.filter((c) => c.id !== id));
      if ($currentChatId === id) {
        goto('/chat');
      }
    } catch {
      toast.error('Failed to delete conversation');
    }
  }

  function formatDate(ts: number): string {
    const d = dayjs(ts);
    const now = dayjs();
    if (d.isSame(now, 'day')) return 'Today';
    if (d.isSame(now.subtract(1, 'day'), 'day')) return 'Yesterday';
    return d.format('MMM D');
  }

  // Group conversations by date
  let groupedChats = $derived(() => {
    const groups: Record<string, Conversation[]> = {};
    for (const conv of $conversations) {
      const label = formatDate(conv.updatedAt);
      if (!groups[label]) groups[label] = [];
      groups[label].push(conv);
    }
    return groups;
  });
</script>

{#if $showSidebar}
  {#if $mobile}
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="fixed inset-0 bg-black/50 z-40"
      onclick={() => showSidebar.set(false)}
    ></div>
  {/if}

  <aside
    class="flex flex-col w-64 h-full bg-gray-50 dark:bg-gray-950 border-r border-gray-100 dark:border-gray-850
           {$mobile ? 'fixed left-0 top-0 z-50' : 'shrink-0'}"
  >
    <!-- Header -->
    <div class="flex items-center justify-between p-3 border-b border-gray-100 dark:border-gray-850">
      <div class="flex items-center gap-2">
        {#if isAdminRoute}
          <span class="text-sm font-semibold text-gray-700 dark:text-gray-200">Admin Panel</span>
        {:else}
          <img src="/mascot-nav.png" alt="Contexto" class="rounded-full" width="24" height="24" />
          <span class="text-sm font-semibold text-gray-700 dark:text-gray-200">Contexto</span>
        {/if}
      </div>
      {#if !isAdminRoute}
        <button
          onclick={newChat}
          class="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
          title="New chat"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-gray-600 dark:text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      {/if}
    </div>

    {#if isAdminRoute}
      <!-- Admin nav -->
      <nav class="flex-1 overflow-y-auto p-2 space-y-0.5">
        <button
          onclick={() => goto('/chat')}
          class="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors
                 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-900"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="size-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          Chat
        </button>
        <div class="h-px bg-gray-100 dark:bg-gray-850 my-2 mx-2"></div>
        <button
          onclick={() => gotoAdminTab('users')}
          class="w-full flex items-center justify-between gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors
                 {activeAdminTab === 'users'
                   ? 'bg-gray-200 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                   : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-900'}"
        >
          <span class="flex items-center gap-2.5">
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
            </svg>
            Users
          </span>
          <span class="text-[10px] {activeAdminTab === 'users' ? 'opacity-70' : 'text-gray-400'}">{$adminCounts.users}</span>
        </button>
        <button
          onclick={() => gotoAdminTab('courses')}
          class="w-full flex items-center justify-between gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors
                 {activeAdminTab === 'courses'
                   ? 'bg-gray-200 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                   : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-900'}"
        >
          <span class="flex items-center gap-2.5">
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
            </svg>
            Courses
          </span>
          <span class="text-[10px] {activeAdminTab === 'courses' ? 'opacity-70' : 'text-gray-400'}">{$adminCounts.courses}</span>
        </button>
        <button
          onclick={() => gotoAdminTab('violations')}
          class="w-full flex items-center justify-between gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors
                 {activeAdminTab === 'violations'
                   ? 'bg-gray-200 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                   : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-900'}"
        >
          <span class="flex items-center gap-2.5">
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            Violations
          </span>
          {#if $adminCounts.violations > 0}
            <span class="px-1.5 py-0.5 text-[10px] rounded-full bg-red-500 text-white">{$adminCounts.violations}</span>
          {/if}
        </button>

        {#if isSuperAdmin}
          <div class="h-px bg-gray-100 dark:bg-gray-850 my-2 mx-2"></div>
          <button
            onclick={gotoBaseline}
            class="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors
                   {activeAdminTab === 'baseline'
                     ? 'bg-gray-200 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                     : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-900'}"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
            </svg>
            Baseline
          </button>
        {/if}
      </nav>
    {:else}
      <!-- Chat list -->
      <div class="flex-1 overflow-y-auto p-2 space-y-3">
        {#if $conversations.length === 0}
          <p class="text-xs text-gray-400 dark:text-gray-600 text-center mt-8">
            No conversations yet
          </p>
        {:else}
          {#each Object.entries(groupedChats()) as [dateLabel, chatGroup]}
            <div>
              <p class="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-600 px-2 mb-1">
                {dateLabel}
              </p>
              {#each chatGroup as conv (conv.id)}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div
                  onclick={() => openChat(conv.id)}
                  class="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-sm transition-colors group cursor-pointer
                         {$currentChatId === conv.id
                           ? 'bg-gray-200 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                           : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-900'}"
                >
                  <span class="flex-1 truncate">{conv.name || 'Untitled'}</span>
                  <button
                    onclick={(e) => deleteChat(e, conv.id)}
                    class="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-gray-300 dark:hover:bg-gray-700 transition-all"
                    title="Delete conversation"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              {/each}
            </div>
          {/each}
        {/if}
      </div>
    {/if}

    <!-- User profile menu (bottom of sidebar, like Open WebUI) -->
    <div class="relative border-t border-gray-100 dark:border-gray-850">
      <!-- User menu dropdown (opens upward) -->
      {#if showUserMenu}
        <div
          class="fixed inset-0 z-40"
          onclick={() => showUserMenu = false}
        ></div>
        <div class="absolute bottom-full left-2 right-2 mb-1 z-50 py-1 rounded-xl
                    bg-white dark:bg-gray-850 border border-gray-100 dark:border-gray-800
                    shadow-lg">

          <!-- Role badge -->
          {#if $authStore.roles.length > 0}
            <div class="px-3 py-2 border-b border-gray-100 dark:border-gray-800">
              <div class="flex items-center gap-1.5 flex-wrap">
                {#each $authStore.roles as role}
                  <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium
                    {role === 'super_admin'
                      ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                      : role === 'admin'
                        ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                        : 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'}">
                    {role.replace('_', ' ')}
                  </span>
                {/each}
              </div>
            </div>
          {/if}

          <!-- Admin Panel (super_admin/admin only) -->
          {#if $authStore.roles.includes('super_admin') || $authStore.roles.includes('admin')}
            <button
              onclick={() => { showUserMenu = false; goto('/admin'); }}
              class="w-full px-3 py-2 text-left text-sm flex items-center gap-2.5
                     text-gray-700 dark:text-gray-300
                     hover:bg-gray-50 dark:hover:bg-gray-800 transition"
            >
              <!-- Shield icon -->
              <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
              Admin Panel
            </button>
          {/if}

          <!-- Profile -->
          <button
            onclick={() => { showUserMenu = false; goto('/profile'); }}
            class="w-full px-3 py-2 text-left text-sm flex items-center gap-2.5
                   text-gray-700 dark:text-gray-300
                   hover:bg-gray-50 dark:hover:bg-gray-800 transition"
          >
            <!-- User icon -->
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
            Profile
          </button>

          <!-- Sign Out -->
          <button
            onclick={async () => { showUserMenu = false; await logout(); }}
            class="w-full px-3 py-2 text-left text-sm flex items-center gap-2.5
                   text-gray-700 dark:text-gray-300
                   hover:bg-gray-50 dark:hover:bg-gray-800 transition"
          >
            <!-- Log out icon -->
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            Sign Out
          </button>
        </div>
      {/if}

      <!-- Profile button -->
      <button
        onclick={() => showUserMenu = !showUserMenu}
        class="w-full flex items-center gap-3 p-3 hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors"
      >
        <!-- Avatar -->
        <div class="shrink-0 size-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                    flex items-center justify-center text-white text-xs font-bold uppercase">
          {getDisplayLabel($authStore).slice(0, 2)}
        </div>
        <!-- Name / email -->
        <div class="flex-1 min-w-0 text-left">
          <p class="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">
            {getDisplayLabel($authStore)}
          </p>
          {#if $authStore.email && $authStore.displayName}
            <p class="text-[10px] text-gray-400 dark:text-gray-500 truncate">
              {$authStore.email}
            </p>
          {:else if $authStore.roles.length > 0}
            <p class="text-[10px] text-gray-400 dark:text-gray-500 truncate">
              {$authStore.roles[0].replace('_', ' ')}
            </p>
          {/if}
        </div>
        <!-- Chevron -->
        <svg xmlns="http://www.w3.org/2000/svg" class="size-4 shrink-0 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      <!-- Legal footer -->
      <div class="px-3 pb-2 pt-0 flex items-center gap-2 text-[10px] text-gray-400 dark:text-gray-600">
        <a href="/terms" class="hover:text-gray-600 dark:hover:text-gray-400 transition">Terms</a>
        <span aria-hidden="true">·</span>
        <a href="/privacy" class="hover:text-gray-600 dark:hover:text-gray-400 transition">Privacy</a>
      </div>
    </div>
  </aside>
{/if}
