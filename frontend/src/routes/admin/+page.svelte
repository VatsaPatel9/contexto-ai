<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { toast } from 'svelte-sonner';
  import { authStore } from '$lib/stores/auth';
  import {
    listUsers,
    getUserProfile,
    setUploadLimit,
    revokeUploadLimit,
    setTokenLimit,
    listViolations,
    banUser,
    unbanUser,
    assignRole,
    removeRole,
    type UserProfile,
    type Violation,
  } from '$lib/apis/admin';
  import { session } from '$lib/stores';
  import { listDocuments, deleteDocument, type UploadedDocument } from '$lib/apis/documents';

  // ── State ───────────────────────────────────────────────────────────

  type Tab = 'users' | 'violations';
  let activeTab = $state<Tab>('users');

  // Users
  let usersByRole = $state<Record<string, string[]>>({});
  // Cache: userId -> { displayName, email } — populated as profiles are loaded
  let userNameCache = $state<Record<string, { displayName: string | null; email: string | null }>>({});

  let allUserIds = $derived(() => {
    const ids = new Set<string>();
    for (const list of Object.values(usersByRole)) {
      for (const id of list) ids.add(id);
    }
    return [...ids];
  });

  /** Get a human-readable label for a user ID. */
  function userLabel(userId: string): string {
    const cached = userNameCache[userId];
    if (cached?.displayName) return cached.displayName;
    if (cached?.email) return cached.email.split('@')[0];
    return userId.slice(0, 8) + '...';
  }

  /** Get initials for avatar. */
  function userInitials(userId: string): string {
    const cached = userNameCache[userId];
    if (cached?.displayName) return cached.displayName.slice(0, 2).toUpperCase();
    if (cached?.email) return cached.email.slice(0, 2).toUpperCase();
    return userId.slice(0, 2).toUpperCase();
  }

  // Search dropdown
  let searchQuery = $state('');
  let showDropdown = $state(false);
  let searchResults = $derived(() => {
    const all = allUserIds();
    if (!searchQuery.trim()) return all.slice(0, 8);
    const q = searchQuery.toLowerCase();
    return all.filter((id) => {
      if (id.toLowerCase().includes(q)) return true;
      const cached = userNameCache[id];
      if (cached?.displayName?.toLowerCase().includes(q)) return true;
      if (cached?.email?.toLowerCase().includes(q)) return true;
      return false;
    });
  });

  // Violations
  let violations = $state<Violation[]>([]);

  // Selected user detail (inline, not modal)
  let selectedProfile = $state<UserProfile | null>(null);
  let detailLoading = $state(false);

  // Edit fields
  let editUploadLimit = $state('');
  let editTokenLimit = $state('');

  // User documents (loaded when a user is selected)
  let userDocuments = $state<UploadedDocument[]>([]);
  let userDocsLoading = $state(false);
  let adminDocsExpanded = $state(false);
  let activeUserDocs = $derived(userDocuments.filter((d) => !d.deleted_at));
  let visibleUserDocs = $derived(adminDocsExpanded ? userDocuments : userDocuments.slice(0, 3));

  // Confirm
  let confirmAction = $state<(() => Promise<void>) | null>(null);
  let confirmMessage = $state('');
  let showConfirm = $state(false);

  let isSuperAdmin = $derived($authStore.roles.includes('super_admin'));

  // Upload permission: enabled if user has the user_uploader role OR has a non-null upload limit
  let uploadEnabled = $derived(
    selectedProfile !== null && (
      selectedProfile.roles.includes('user_uploader') ||
      selectedProfile.uploads.limit !== null
    )
  );

  // ── Data Loading ────────────────────────────────────────────────────

  onMount(async () => {
    if (!$authStore.roles.includes('super_admin') && !$authStore.roles.includes('admin')) {
      goto('/chat');
      return;
    }
    await loadData();
  });

  async function loadData() {
    try {
      const [usersRes, violationsRes] = await Promise.all([
        listUsers(),
        listViolations(),
      ]);
      usersByRole = usersRes.users_by_role ?? {};
      violations = violationsRes.violations;

      // Preload names for all users (fire-and-forget, parallel)
      const allIds = new Set<string>();
      for (const list of Object.values(usersByRole)) {
        for (const id of list) allIds.add(id);
      }
      preloadUserNames([...allIds]);
    } catch (e: any) {
      toast.error(e.message || 'Failed to load admin data');
    }
  }

  async function preloadUserNames(userIds: string[]) {
    // Load profiles in parallel (batched) to populate the name cache
    const promises = userIds
      .filter((id) => !userNameCache[id])
      .map(async (id) => {
        try {
          const profile = await getUserProfile(id);
          userNameCache[id] = { displayName: profile.display_name, email: profile.email };
          userNameCache = { ...userNameCache }; // trigger reactivity
        } catch {
          // Ignore — user will just show UUID
        }
      });
    await Promise.all(promises);
  }

  function cacheFromProfile(profile: UserProfile) {
    userNameCache[profile.user_id] = { displayName: profile.display_name, email: profile.email };
    userNameCache = { ...userNameCache };
  }

  async function selectUser(userId: string) {
    showDropdown = false;
    searchQuery = '';
    detailLoading = true;
    userDocuments = [];
    adminDocsExpanded = false;
    try {
      selectedProfile = await getUserProfile(userId);
      cacheFromProfile(selectedProfile);
      editUploadLimit = selectedProfile.uploads.limit?.toString() ?? '';
      editTokenLimit = selectedProfile.tokens.limit?.toString() ?? '';
      // Load user's documents in background
      loadUserDocuments();
    } catch (e: any) {
      toast.error(e.message);
      selectedProfile = null;
    } finally {
      detailLoading = false;
    }
  }

  async function loadUserDocuments() {
    userDocsLoading = true;
    try {
      const courseId = session.getCourseId();
      const res = await listDocuments(courseId);
      // Admin sees all docs — filter to this user
      if (selectedProfile) {
        userDocuments = res.data.filter((d) => d.uploaded_by === selectedProfile!.user_id);
      }
    } catch {
      userDocuments = [];
    }
    userDocsLoading = false;
  }

  async function handleDeleteUserDocument(docId: string, title: string) {
    confirmMessage = `Delete document "${title}"? It will be soft-deleted.`;
    confirmAction = async () => {
      try {
        const courseId = session.getCourseId();
        await deleteDocument(courseId, docId);
        toast.success(`"${title}" deleted`);
        await loadUserDocuments();
      } catch (e: any) {
        toast.error(e.message);
      }
    };
    showConfirm = true;
  }

  function getFileIcon(title: string): string {
    const ext = title.split('.').pop()?.toLowerCase();
    if (ext === 'pdf') return '📄';
    if (['doc', 'docx'].includes(ext ?? '')) return '📝';
    if (['txt', 'md'].includes(ext ?? '')) return '📃';
    if (['csv', 'xlsx', 'xls'].includes(ext ?? '')) return '📊';
    return '📎';
  }

  function getStatusBadge(status: string): string {
    switch (status) {
      case 'ready': return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
      case 'processing': return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400';
      case 'error': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
      default: return 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400';
    }
  }

  function getUserRoleDisplay(userId: string): string[] {
    const roles: string[] = [];
    for (const [role, ids] of Object.entries(usersByRole)) {
      if (ids.includes(userId)) roles.push(role);
    }
    return roles;
  }

  function getFlagColor(level: string): string {
    switch (level) {
      case 'suspended': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
      case 'restricted': return 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400';
      case 'warned': return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400';
      default: return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
    }
  }

  function getRoleBadgeColor(role: string): string {
    switch (role) {
      case 'super_admin': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
      case 'admin': return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
      case 'user_uploader': return 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400';
      default: return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400';
    }
  }

  // ── Actions ─────────────────────────────────────────────────────────

  async function handleToggleUpload() {
    if (!selectedProfile) return;
    try {
      if (uploadEnabled) {
        await revokeUploadLimit(selectedProfile.user_id);
        toast.success('Upload permission revoked');
      } else {
        await setUploadLimit(selectedProfile.user_id, 10);
        editUploadLimit = '10';
        toast.success('Upload permission granted (limit: 10)');
      }
      selectedProfile = await getUserProfile(selectedProfile.user_id);
      editUploadLimit = selectedProfile.uploads.limit?.toString() ?? '';
      await loadData();
    } catch (e: any) { toast.error(e.message); }
  }

  async function handleSaveUploadLimit() {
    if (!selectedProfile) return;
    const val = editUploadLimit.trim().toLowerCase();
    try {
      if (val === 'unlimited' || val === '') {
        // Keep permission but remove cap
        await setUploadLimit(selectedProfile.user_id, 0);
        toast.success('Upload limit set to unlimited');
      } else if (val === 'none' || val === 'revoke') {
        await revokeUploadLimit(selectedProfile.user_id);
        toast.success('Upload permission revoked');
      } else {
        const limit = parseInt(val, 10);
        if (isNaN(limit) || limit < 0) { toast.error('Enter a valid number or "unlimited"'); return; }
        await setUploadLimit(selectedProfile.user_id, limit);
        toast.success(`Upload limit set to ${limit}`);
      }
      selectedProfile = await getUserProfile(selectedProfile.user_id);
      editUploadLimit = selectedProfile.uploads.limit?.toString() ?? '';
      await loadData();
    } catch (e: any) { toast.error(e.message); }
  }

  async function handleSaveTokenLimit() {
    if (!selectedProfile) return;
    const val = editTokenLimit.trim();
    try {
      const limit = val === '' || val === 'none' ? null : parseInt(val, 10);
      if (limit !== null && (isNaN(limit) || limit < 0)) { toast.error('Invalid limit'); return; }
      await setTokenLimit(selectedProfile.user_id, limit);
      toast.success(limit === null ? 'Token limit removed' : `Token limit set to ${limit.toLocaleString()}`);
      selectedProfile = await getUserProfile(selectedProfile.user_id);
      editTokenLimit = selectedProfile.tokens.limit?.toString() ?? '';
    } catch (e: any) { toast.error(e.message); }
  }

  async function handleBan(userId: string) {
    confirmMessage = `Ban user ${userId.slice(0, 8)}...? They will be unable to send messages.`;
    confirmAction = async () => {
      try {
        await banUser(userId, 'Banned by admin');
        toast.success('User banned');
        if (selectedProfile?.user_id === userId) selectedProfile = await getUserProfile(userId);
        await loadData();
      } catch (e: any) { toast.error(e.message); }
    };
    showConfirm = true;
  }

  async function handleUnban(userId: string) {
    try {
      await unbanUser(userId);
      toast.success('User unbanned');
      if (selectedProfile?.user_id === userId) selectedProfile = await getUserProfile(userId);
      await loadData();
    } catch (e: any) { toast.error(e.message); }
  }

  async function handlePromoteToAdmin(userId: string) {
    confirmMessage = `Promote user ${userId.slice(0, 8)}... to admin?`;
    confirmAction = async () => {
      try {
        await assignRole(userId, 'admin');
        toast.success('User promoted to admin');
        await loadData();
        if (selectedProfile?.user_id === userId) selectedProfile = await getUserProfile(userId);
      } catch (e: any) { toast.error(e.message); }
    };
    showConfirm = true;
  }

  async function handleDemoteFromAdmin(userId: string) {
    confirmMessage = `Remove admin role from ${userId.slice(0, 8)}...?`;
    confirmAction = async () => {
      try {
        await removeRole(userId, 'admin');
        toast.success('Admin role removed');
        await loadData();
        if (selectedProfile?.user_id === userId) selectedProfile = await getUserProfile(userId);
      } catch (e: any) { toast.error(e.message); }
    };
    showConfirm = true;
  }

  function formatTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return n.toString();
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->

<!-- ═══ CONFIRM DIALOG ═══ -->
{#if showConfirm}
  <div class="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4"
       onclick={() => showConfirm = false}>
    <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-xl max-w-sm w-full p-6"
         onclick={(e) => e.stopPropagation()}>
      <p class="text-sm text-gray-700 dark:text-gray-300 mb-5">{confirmMessage}</p>
      <div class="flex gap-2 justify-end">
        <button onclick={() => showConfirm = false}
                class="px-3.5 py-1.5 text-sm rounded-full border border-gray-200 dark:border-gray-700
                       text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition">
          Cancel
        </button>
        <button onclick={async () => { showConfirm = false; await confirmAction?.(); }}
                class="px-3.5 py-1.5 text-sm rounded-full bg-red-600 text-white hover:bg-red-700 transition">
          Confirm
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- ═══ MAIN LAYOUT ═══ -->
<div class="flex flex-col h-full">
  <!-- Top bar -->
  <div class="sticky top-0 z-30 bg-white/80 dark:bg-gray-900/80 backdrop-blur-xl border-b border-gray-100 dark:border-gray-800">
    <div class="flex items-center justify-between px-4 py-3">
      <div class="flex items-center gap-3">
        <button onclick={() => goto('/chat')}
                class="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition">
          <svg xmlns="http://www.w3.org/2000/svg" class="size-5 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <h1 class="text-lg font-semibold text-gray-900 dark:text-white">Admin Panel</h1>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 px-4 pb-2">
      <button onclick={() => activeTab = 'users'}
              class="px-3 py-1.5 text-sm font-medium rounded-lg transition
                     {activeTab === 'users'
                       ? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
                       : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800'}">
        Users ({allUserIds().length})
      </button>
      <button onclick={() => activeTab = 'violations'}
              class="px-3 py-1.5 text-sm font-medium rounded-lg transition
                     {activeTab === 'violations'
                       ? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
                       : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800'}">
        Violations
        {#if violations.length > 0}
          <span class="ml-1 px-1.5 py-0.5 text-[10px] rounded-full bg-red-500 text-white">{violations.length}</span>
        {/if}
      </button>
    </div>
  </div>

  <!-- Content -->
  <div class="flex-1 overflow-y-auto">
    <div class="max-w-3xl mx-auto w-full">
      {#if activeTab === 'users'}

        <!-- ═══ USER SEARCH DROPDOWN ═══ -->
        <div class="px-4 pt-4 pb-2 relative z-40">
          <div class="relative">
            <div class="flex items-center gap-2 px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700
                        bg-white dark:bg-gray-800 focus-within:ring-1 focus-within:ring-blue-500 transition cursor-pointer"
                 onclick={() => showDropdown = !showDropdown}>
              <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-gray-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                type="text"
                bind:value={searchQuery}
                onfocus={() => showDropdown = true}
                oninput={() => showDropdown = true}
                onclick={(e) => e.stopPropagation()}
                placeholder="Search users by ID..."
                class="flex-1 text-sm bg-transparent outline-none text-gray-900 dark:text-white placeholder:text-gray-400"
              />
              {#if searchQuery}
                <button onclick={(e) => { e.stopPropagation(); searchQuery = ''; showDropdown = true; }}
                        class="p-0.5 rounded hover:bg-black/5 dark:hover:bg-white/5">
                  <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </button>
              {/if}
              <!-- Chevron -->
              <svg xmlns="http://www.w3.org/2000/svg"
                   class="size-4 text-gray-400 shrink-0 transition-transform {showDropdown ? 'rotate-180' : ''}"
                   viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </div>

            <!-- Dropdown results -->
            {#if showDropdown}
              <div class="fixed inset-0 z-40" onclick={() => showDropdown = false}></div>
              <div class="absolute left-0 right-0 mt-1 z-50 max-h-72 overflow-y-auto
                          bg-white dark:bg-gray-850 border border-gray-200 dark:border-gray-700
                          rounded-xl shadow-xl py-1">
                {#if searchResults().length === 0}
                  <p class="px-3 py-3 text-sm text-gray-400 text-center">No users found</p>
                {:else}
                  {#each searchResults() as userId (userId)}
                    <button
                      onclick={() => selectUser(userId)}
                      class="w-full flex items-center gap-3 px-3 py-2 text-left
                             hover:bg-gray-50 dark:hover:bg-gray-800 transition
                             {selectedProfile?.user_id === userId ? 'bg-gray-50 dark:bg-gray-800' : ''}"
                    >
                      <div class="shrink-0 size-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                                  flex items-center justify-center text-white text-[10px] font-bold uppercase">
                        {userInitials(userId)}
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="text-sm text-gray-800 dark:text-gray-200 truncate font-medium">{userLabel(userId)}</div>
                        <div class="flex items-center gap-1.5 mt-0.5 flex-wrap">
                          <span class="text-[10px] text-gray-400 font-mono truncate">{userId.slice(0, 12)}</span>
                          {#each getUserRoleDisplay(userId) as role}
                            <span class="px-1 py-0 rounded text-[8px] font-medium {getRoleBadgeColor(role)}">
                              {role.replace('_', ' ')}
                            </span>
                          {/each}
                        </div>
                      </div>
                    </button>
                  {/each}
                {/if}
              </div>
            {/if}
          </div>
        </div>

        <!-- ═══ USER DETAIL SECTION (inline) ═══ -->
        {#if detailLoading}
          <div class="px-4 py-12 text-center text-gray-400 text-sm">Loading user details...</div>
        {:else if selectedProfile}
          <div class="px-4 pt-2 pb-6">
            <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 overflow-hidden">

              <!-- User header -->
              <div class="flex items-center gap-3 px-5 py-4 border-b border-gray-100 dark:border-gray-800">
                <div class="shrink-0 size-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                            flex items-center justify-center text-white text-sm font-bold uppercase">
                  {userInitials(selectedProfile.user_id)}
                </div>
                <div class="flex-1 min-w-0">
                  <h2 class="text-base font-semibold text-gray-900 dark:text-white truncate">
                    {selectedProfile.display_name || selectedProfile.email?.split('@')[0] || selectedProfile.user_id.slice(0, 8) + '...'}
                  </h2>
                  {#if selectedProfile.email}
                    <p class="text-xs text-gray-400 dark:text-gray-500 truncate mt-0.5">{selectedProfile.email}</p>
                  {/if}
                  <div class="flex items-center gap-1.5 mt-1 flex-wrap">
                    <span class="text-[9px] text-gray-400 font-mono">{selectedProfile.user_id.slice(0, 12)}</span>
                    {#each selectedProfile.roles as role}
                      <span class="px-2 py-0.5 rounded-full text-[10px] font-medium {getRoleBadgeColor(role)}">
                        {role.replace('_', ' ')}
                      </span>
                    {/each}
                  </div>
                </div>
                <button onclick={() => selectedProfile = null}
                        class="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 shrink-0">
                  <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </button>
              </div>

              <div class="divide-y divide-gray-100 dark:divide-gray-800">

                <!-- Roles section -->
                {#if isSuperAdmin}
                  <div class="px-5 py-4">
                    <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-3">Role Management</div>
                    <div class="flex gap-2 flex-wrap">
                      {#if !selectedProfile.roles.includes('admin')}
                        <button onclick={() => handlePromoteToAdmin(selectedProfile!.user_id)}
                                class="text-xs px-3 py-1.5 rounded-lg bg-amber-50 text-amber-700 hover:bg-amber-100
                                       dark:bg-amber-900/20 dark:text-amber-400 dark:hover:bg-amber-900/40 transition font-medium">
                          Promote to Admin
                        </button>
                      {:else if !selectedProfile.roles.includes('super_admin')}
                        <button onclick={() => handleDemoteFromAdmin(selectedProfile!.user_id)}
                                class="text-xs px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200
                                       dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600 transition font-medium">
                          Remove Admin
                        </button>
                      {/if}
                    </div>
                  </div>
                {/if}

                <!-- Document Upload Permission -->
                <div class="px-5 py-4">
                  <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-3">Document Upload Permission</div>

                  <!-- Permission toggle row -->
                  <div class="flex items-center justify-between mb-4">
                    <div class="flex items-center gap-3">
                      <!-- Status indicator -->
                      {#if uploadEnabled}
                        <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium
                                     bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                          <span class="size-1.5 rounded-full bg-green-500"></span>
                          Enabled
                        </span>
                      {:else}
                        <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium
                                     bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400">
                          <span class="size-1.5 rounded-full bg-gray-400"></span>
                          Disabled
                        </span>
                      {/if}
                      <span class="text-xs text-gray-400">
                        {selectedProfile.uploads.count} document{selectedProfile.uploads.count !== 1 ? 's' : ''} uploaded
                      </span>
                    </div>

                    <!-- Toggle switch -->
                    <button
                      onclick={handleToggleUpload}
                      class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors
                             {uploadEnabled
                               ? 'bg-blue-600'
                               : 'bg-gray-300 dark:bg-gray-600'}"
                      title={uploadEnabled ? 'Revoke upload permission' : 'Grant upload permission'}
                    >
                      <span class="inline-block size-4 transform rounded-full bg-white shadow transition-transform
                                   {uploadEnabled ? 'translate-x-6' : 'translate-x-1'}"></span>
                    </button>
                  </div>

                  <!-- Limit controls (shown when enabled) -->
                  {#if uploadEnabled}
                    <div class="bg-gray-50 dark:bg-gray-800 rounded-xl p-3.5">
                      <div class="flex items-center justify-between mb-2.5">
                        <span class="text-xs text-gray-500 dark:text-gray-400">Max documents allowed</span>
                        <span class="text-xs font-mono text-gray-700 dark:text-gray-300">
                          {selectedProfile.uploads.count} / {selectedProfile.uploads.limit ?? '∞'}
                        </span>
                      </div>

                      <!-- Progress bar -->
                      {#if selectedProfile.uploads.limit}
                        <div class="h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden mb-3">
                          <div class="h-full rounded-full transition-all
                                      {selectedProfile.uploads.count / selectedProfile.uploads.limit > 0.9 ? 'bg-red-500' : 'bg-blue-500'}"
                               style="width: {Math.min(100, (selectedProfile.uploads.count / selectedProfile.uploads.limit) * 100)}%"></div>
                        </div>
                      {/if}

                      <div class="flex gap-2">
                        <input type="text" bind:value={editUploadLimit} placeholder="e.g. 10, 50, or unlimited"
                               class="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                                      bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                                      focus:ring-1 focus:ring-blue-500 transition" />
                        <button onclick={handleSaveUploadLimit}
                                class="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition font-medium">
                          Set Limit
                        </button>
                      </div>
                      <p class="text-[10px] text-gray-400 mt-1.5">Enter a number to set a limit, or "unlimited" for no cap.</p>
                    </div>
                  {/if}
                </div>

                <!-- Token Usage -->
                <div class="px-5 py-4">
                  <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-3">Token Usage</div>
                  <div class="grid grid-cols-3 gap-3 mb-3">
                    <div class="bg-gray-50 dark:bg-gray-800 rounded-xl p-3 text-center">
                      <div class="text-xl font-bold text-gray-900 dark:text-white">{formatTokens(selectedProfile.tokens.in)}</div>
                      <div class="text-[10px] text-gray-400 uppercase mt-0.5">Tokens In</div>
                    </div>
                    <div class="bg-gray-50 dark:bg-gray-800 rounded-xl p-3 text-center">
                      <div class="text-xl font-bold text-gray-900 dark:text-white">{formatTokens(selectedProfile.tokens.out)}</div>
                      <div class="text-[10px] text-gray-400 uppercase mt-0.5">Tokens Out</div>
                    </div>
                    <div class="bg-gray-50 dark:bg-gray-800 rounded-xl p-3 text-center">
                      <div class="text-xl font-bold text-gray-900 dark:text-white">{formatTokens(selectedProfile.tokens.total)}</div>
                      <div class="text-[10px] text-gray-400 uppercase mt-0.5">Total</div>
                    </div>
                  </div>
                  {#if selectedProfile.tokens.limit}
                    <div class="mb-3">
                      <div class="h-2 rounded-full bg-gray-100 dark:bg-gray-700 overflow-hidden">
                        <div class="h-full rounded-full transition-all {selectedProfile.tokens.total / selectedProfile.tokens.limit > 0.9 ? 'bg-red-500' : 'bg-blue-500'}"
                             style="width: {Math.min(100, (selectedProfile.tokens.total / selectedProfile.tokens.limit) * 100)}%"></div>
                      </div>
                      <div class="text-[10px] text-gray-400 mt-1 text-right">
                        {formatTokens(selectedProfile.tokens.total)} / {formatTokens(selectedProfile.tokens.limit)}
                      </div>
                    </div>
                  {/if}
                  <div class="flex gap-2">
                    <input type="text" bind:value={editTokenLimit} placeholder="e.g. 100000 or none"
                           class="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                                  bg-white dark:bg-gray-800 text-gray-900 dark:text-white outline-none
                                  focus:ring-1 focus:ring-blue-500 transition" />
                    <button onclick={handleSaveTokenLimit}
                            class="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition font-medium">
                      Save
                    </button>
                  </div>
                </div>

                <!-- Violations -->
                <div class="px-5 py-4">
                  <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-3">Violations</div>
                  <div class="flex items-center gap-3 mb-3">
                    <span class="px-2.5 py-1 rounded-full text-[11px] font-medium {getFlagColor(selectedProfile.flags.level)}">
                      {selectedProfile.flags.level}
                    </span>
                    <span class="text-xs text-gray-500">
                      {selectedProfile.flags.offense_count_mild} mild, {selectedProfile.flags.offense_count_severe} severe
                    </span>
                  </div>
                  {#if selectedProfile.flags.notes}
                    <pre class="text-[11px] text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800
                                rounded-xl p-3 overflow-x-auto max-h-40 whitespace-pre-wrap mb-3">{selectedProfile.flags.notes}</pre>
                  {/if}
                  <div class="flex gap-2">
                    {#if selectedProfile.flags.level !== 'suspended'}
                      <button onclick={() => handleBan(selectedProfile!.user_id)}
                              class="text-xs px-3 py-1.5 rounded-lg bg-red-50 text-red-700 hover:bg-red-100
                                     dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/40 transition font-medium">
                        Ban User
                      </button>
                    {:else}
                      <button onclick={() => handleUnban(selectedProfile!.user_id)}
                              class="text-xs px-3 py-1.5 rounded-lg bg-green-50 text-green-700 hover:bg-green-100
                                     dark:bg-green-900/20 dark:text-green-400 dark:hover:bg-green-900/40 transition font-medium">
                        Unban User
                      </button>
                    {/if}
                  </div>
                </div>

                <!-- User Documents -->
                <div class="px-5 py-4">
                  <div class="flex items-center justify-between mb-3">
                    <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">
                      Documents ({userDocuments.filter(d => !d.deleted_at).length})
                    </div>
                    {#if userDocsLoading}
                      <div class="size-3.5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                    {/if}
                  </div>

                  {#if userDocuments.length === 0 && !userDocsLoading}
                    <p class="text-xs text-gray-400 py-3 text-center">No documents uploaded by this user</p>
                  {:else}
                    <div class="space-y-1.5">
                      {#each visibleUserDocs as doc (doc.id)}
                        <div class="flex items-center gap-2.5 px-3 py-2 rounded-xl group
                                    {doc.deleted_at
                                      ? 'bg-red-50/50 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30'
                                      : 'bg-gray-50 dark:bg-gray-800 border border-gray-100 dark:border-gray-700'}">
                          <span class="text-base shrink-0">{getFileIcon(doc.title)}</span>
                          <div class="flex-1 min-w-0">
                            <p class="text-xs text-gray-800 dark:text-gray-200 truncate font-medium
                                      {doc.deleted_at ? 'line-through opacity-60' : ''}">{doc.title}</p>
                            <div class="flex items-center gap-1.5 mt-0.5">
                              <span class="px-1 py-0 rounded text-[8px] font-medium {getStatusBadge(doc.status)}">
                                {doc.status}
                              </span>
                              <span class="text-[9px] text-gray-400">{doc.chunk_count} chunks</span>
                              <span class="text-[9px] text-gray-400">
                                {doc.visibility === 'private' ? '🔒' : '🌐'}
                              </span>
                              {#if doc.deleted_at}
                                <span class="text-[9px] text-red-400">deleted</span>
                              {/if}
                            </div>
                          </div>

                          {#if !doc.deleted_at}
                            <button
                              onclick={() => handleDeleteUserDocument(doc.id, doc.title)}
                              class="shrink-0 p-1 rounded-lg opacity-0 group-hover:opacity-100
                                     hover:bg-red-50 dark:hover:bg-red-900/20
                                     text-gray-400 hover:text-red-500 transition"
                              title="Delete document"
                            >
                              <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="3 6 5 6 21 6" />
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                              </svg>
                            </button>
                          {/if}
                        </div>
                      {/each}
                    </div>

                    {#if userDocuments.length > 3}
                      <button
                        onclick={() => adminDocsExpanded = !adminDocsExpanded}
                        class="w-full mt-2 py-1.5 text-[11px] text-center text-blue-600 dark:text-blue-400
                               hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition font-medium"
                      >
                        {adminDocsExpanded ? 'Show less' : `Show all ${userDocuments.length} documents`}
                      </button>
                    {/if}
                  {/if}
                </div>
              </div>
            </div>
          </div>
        {:else}
          <!-- Empty state -->
          <div class="px-4 py-16 text-center">
            <svg xmlns="http://www.w3.org/2000/svg" class="size-12 mx-auto text-gray-200 dark:text-gray-700 mb-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
            <p class="text-sm text-gray-400">Search for a user above to view their details</p>
          </div>
        {/if}

      {:else if activeTab === 'violations'}

        <!-- ═══ VIOLATIONS TAB ═══ -->
        <div class="px-4 py-3 space-y-1.5">
          {#if violations.length === 0}
            <div class="text-center py-16">
              <svg xmlns="http://www.w3.org/2000/svg" class="size-12 mx-auto text-gray-200 dark:text-gray-700 mb-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p class="text-sm text-gray-400">No active violations</p>
            </div>
          {:else}
            {#each violations as v (v.user_id)}
              <div class="flex items-center justify-between px-3 py-3 rounded-xl
                          hover:bg-gray-50 dark:hover:bg-gray-800/50 transition cursor-pointer
                          border border-gray-100 dark:border-gray-800"
                   onclick={() => { activeTab = 'users'; selectUser(v.user_id); }}>
                <div class="flex items-center gap-3 min-w-0">
                  <div class="shrink-0 size-8 rounded-full bg-gradient-to-br from-red-500 to-orange-500
                              flex items-center justify-center text-white text-xs font-bold uppercase">
                    {userInitials(v.user_id)}
                  </div>
                  <div class="min-w-0">
                    <div class="text-sm font-medium text-gray-800 dark:text-gray-200 font-mono truncate">
                      {userLabel(v.user_id)}
                    </div>
                    <div class="flex items-center gap-2 mt-0.5">
                      <span class="px-1.5 py-0 rounded text-[9px] font-medium {getFlagColor(v.flag_level)}">
                        {v.flag_level}
                      </span>
                      <span class="text-[10px] text-gray-400">
                        {v.offense_count_mild} mild, {v.offense_count_severe} severe
                      </span>
                    </div>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  {#if v.flag_level === 'suspended'}
                    <button onclick={(e) => { e.stopPropagation(); handleUnban(v.user_id); }}
                            class="text-[11px] px-2.5 py-1 rounded-lg bg-green-50 text-green-700
                                   dark:bg-green-900/20 dark:text-green-400 hover:bg-green-100
                                   dark:hover:bg-green-900/40 transition font-medium">
                      Unban
                    </button>
                  {:else}
                    <button onclick={(e) => { e.stopPropagation(); handleBan(v.user_id); }}
                            class="text-[11px] px-2.5 py-1 rounded-lg bg-red-50 text-red-700
                                   dark:bg-red-900/20 dark:text-red-400 hover:bg-red-100
                                   dark:hover:bg-red-900/40 transition font-medium">
                      Ban
                    </button>
                  {/if}
                  <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-gray-300 dark:text-gray-600"
                       viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </div>
              </div>
            {/each}
          {/if}
        </div>
      {/if}
    </div>
  </div>
</div>
