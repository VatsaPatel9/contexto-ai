<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { toast } from 'svelte-sonner';
  import { authStore, getDisplayLabel, logout } from '$lib/stores/auth';
  import { session, conversations, conversationsLoaded } from '$lib/stores';
  import {
    deleteDocument,
    getDocumentSignedUrl,
  } from '$lib/apis/documents';

  // Same fallback as $lib/auth/supertokens.ts: empty env → same-origin,
  // which is what the nginx reverse proxy expects in production.
  const API_BASE =
    import.meta.env.VITE_API_BASE_URL ||
    (typeof window !== 'undefined' ? window.location.origin : '');

  // One row per accessible document, with the course it belongs to so
  // we can group by course in the UI. Comes from /api/me/documents,
  // which aggregates baseline + enrolled-course + own-private content
  // — replacing the old single-course listDocuments() call that only
  // showed materials from whichever course was last selected.
  type AccessibleDocument = {
    id: string;
    title: string;
    status: 'processing' | 'ready' | 'error';
    chunk_count: number;
    course_id: string;
    course_name: string;
    uploader_role: 'baseline' | 'course' | 'private';
    can_delete: boolean;
    download_url?: string | null;
  };

  type MyProfile = {
    user_id: string;
    display_name: string | null;
    email: string | null;
    uploads: { count: number; limit: number | null };
    tokens: { in: number; out: number; total: number; limit: number | null };
    flags: { level: string; offense_count_mild: number; offense_count_severe: number };
  };

  let profile = $state<MyProfile | null>(null);
  let loading = $state(true);
  let documents = $state<AccessibleDocument[]>([]);
  let docsLoading = $state(false);

  onMount(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/me`, { credentials: 'include' });
      if (res.ok) profile = await res.json();
    } catch { /* ignore */ }
    loading = false;

    await loadDocuments();
  });

  async function loadDocuments() {
    docsLoading = true;
    try {
      const res = await fetch(`${API_BASE}/api/me/documents`, { credentials: 'include' });
      if (res.ok) {
        const body = await res.json();
        documents = body.data ?? [];
      } else {
        documents = [];
      }
    } catch {
      documents = [];
    }
    docsLoading = false;
  }

  async function handleDeleteDocument(doc: AccessibleDocument) {
    if (!doc.can_delete) return;
    if (!confirm(`Delete "${doc.title}"? This cannot be undone.`)) return;
    try {
      await deleteDocument(doc.course_id, doc.id);
      documents = documents.filter((d) => d.id !== doc.id);
      toast.success(`"${doc.title}" deleted`);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function handleViewDocument(docId: string) {
    try {
      const { download_url } = await getDocumentSignedUrl(docId);
      window.open(download_url, '_blank', 'noopener,noreferrer');
    } catch (e: any) {
      toast.error(e.message || 'Unable to open document');
    }
  }

  // Fetch the object cross-origin (R2 CORS allows it) so the browser
  // triggers a real download instead of navigating to the signed URL.
  async function handleDownloadDocument(docId: string, title: string) {
    try {
      const { download_url } = await getDocumentSignedUrl(docId);
      const res = await fetch(download_url);
      if (!res.ok) throw new Error(`Download failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = title;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      toast.error(e.message || 'Download failed');
    }
  }

  function formatTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return n.toString();
  }

  function getFlagColor(level: string): string {
    switch (level) {
      case 'suspended': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
      case 'restricted': return 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400';
      case 'warned': return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400';
      default: return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
    }
  }

  function getStatusBadge(status: string): string {
    switch (status) {
      case 'ready': return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
      case 'processing': return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400';
      case 'error': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
      default: return 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400';
    }
  }

  function getFileIcon(title: string): string {
    const ext = title.split('.').pop()?.toLowerCase();
    if (ext === 'pdf') return '📄';
    if (['doc', 'docx'].includes(ext ?? '')) return '📝';
    if (['txt', 'md'].includes(ext ?? '')) return '📃';
    if (['csv', 'xlsx', 'xls'].includes(ext ?? '')) return '📊';
    return '📎';
  }

  let canUpload = $derived(
    $authStore.roles.includes('user_uploader') ||
    $authStore.roles.includes('admin') ||
    $authStore.roles.includes('super_admin')
  );

  // Backend already filters out soft-deleted; nothing extra to do.
  let activeDocuments = $derived(documents);
  let docsExpanded = $state(false);
  let visibleDocuments = $derived(docsExpanded ? activeDocuments : activeDocuments.slice(0, 3));

  // Group the visible slice by course so students can see each course's
  // materials clustered together. Baseline-tagged docs are pulled into
  // a separate group so they're easy to spot.
  let groupedDocuments = $derived.by(() => {
    const groups = new Map<string, AccessibleDocument[]>();
    for (const doc of visibleDocuments) {
      const label =
        doc.uploader_role === 'baseline'
          ? 'System library'
          : doc.uploader_role === 'private'
            ? 'My uploads'
            : doc.course_name || 'Course';
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label)!.push(doc);
    }
    return Array.from(groups.entries());
  });

  function uploaderRoleLabel(role: AccessibleDocument['uploader_role']): string {
    if (role === 'baseline') return '🌐 System';
    if (role === 'course') return '🎓 Course';
    return '🔒 Private';
  }

  // ── Delete account ───────────────────────────────────────────────
  // Confirmation pattern: user must type their own email exactly to
  // arm the destructive button. No password re-entry — the active
  // session is already proof of identity.
  let showDeleteConfirm = $state(false);
  let deleteConfirmText = $state('');
  let deleting = $state(false);
  let deleteEnabled = $derived(
    !!profile?.email && deleteConfirmText.trim().toLowerCase() === profile.email.toLowerCase()
  );

  async function handleDeleteAccount() {
    if (!deleteEnabled || deleting) return;
    deleting = true;
    try {
      const res = await fetch(`${API_BASE}/api/me`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(text || `Delete failed (${res.status})`);
      }
      // Local store cleanup so the next login sees a clean slate even
      // though the server already revoked the session cookie.
      conversations.set([]);
      conversationsLoaded.set(false);
      try { await logout(); } catch { /* session is already revoked server-side */ }
      toast.success('Account deleted');
      goto('/login');
    } catch (e: any) {
      toast.error(e.message || 'Failed to delete account');
      deleting = false;
    }
  }
</script>

<div class="flex flex-col h-full">
  <!-- Top bar -->
  <div class="sticky top-0 z-30 bg-white/80 dark:bg-gray-900/80 backdrop-blur-xl border-b border-gray-100 dark:border-gray-800">
    <div class="flex items-center gap-3 px-4 py-3">
      <button onclick={() => goto('/chat')}
              class="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition">
        <svg xmlns="http://www.w3.org/2000/svg" class="size-5 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6" />
        </svg>
      </button>
      <h1 class="text-lg font-semibold text-gray-900 dark:text-white">My Profile</h1>
    </div>
  </div>

  <!-- Content -->
  <div class="flex-1 overflow-y-auto">
    {#if loading}
      <div class="flex items-center justify-center h-48">
        <p class="text-sm text-gray-400">Loading...</p>
      </div>
    {:else if profile}
      <div class="max-w-lg mx-auto px-4 py-6 space-y-6">

        <!-- User Info -->
        <div class="flex items-center gap-4">
          <div class="size-14 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                      flex items-center justify-center text-white text-lg font-bold uppercase">
            {getDisplayLabel($authStore).slice(0, 2)}
          </div>
          <div>
            <p class="text-base font-semibold text-gray-800 dark:text-gray-200">
              {getDisplayLabel($authStore)}
            </p>
            {#if profile.email}
              <p class="text-xs text-gray-400 dark:text-gray-500">{profile.email}</p>
            {/if}
            <div class="flex gap-1.5 mt-1">
              {#each $authStore.roles as role}
                <span class="px-1.5 py-0.5 rounded text-[10px] font-medium
                  {role === 'super_admin' ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                   : role === 'admin' ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                   : 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'}">
                  {role.replace('_', ' ')}
                </span>
              {/each}
            </div>
          </div>
        </div>

        <!-- Token Usage -->
        <div class="bg-gray-50 dark:bg-gray-800 rounded-2xl p-5">
          <h2 class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Token Usage</h2>
          <div class="grid grid-cols-3 gap-3">
            <div class="text-center">
              <div class="text-2xl font-bold text-gray-900 dark:text-white">{formatTokens(profile.tokens.in)}</div>
              <div class="text-[10px] text-gray-400 uppercase mt-0.5">Input</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-gray-900 dark:text-white">{formatTokens(profile.tokens.out)}</div>
              <div class="text-[10px] text-gray-400 uppercase mt-0.5">Output</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-gray-900 dark:text-white">{formatTokens(profile.tokens.total)}</div>
              <div class="text-[10px] text-gray-400 uppercase mt-0.5">Total</div>
            </div>
          </div>
          {#if profile.tokens.limit}
            <div class="mt-4">
              <div class="h-2 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                <div class="h-full rounded-full transition-all
                  {profile.tokens.total / profile.tokens.limit > 0.9 ? 'bg-red-500' : profile.tokens.total / profile.tokens.limit > 0.7 ? 'bg-amber-500' : 'bg-blue-500'}"
                     style="width: {Math.min(100, (profile.tokens.total / profile.tokens.limit) * 100)}%">
                </div>
              </div>
              <p class="text-[11px] text-gray-400 mt-1 text-right">
                {formatTokens(profile.tokens.total)} / {formatTokens(profile.tokens.limit)} tokens used
              </p>
            </div>
          {/if}
        </div>

        <!-- My Documents — every doc the user can read, grouped by
             course. Baseline + enrolled-course content is view-only;
             only the user's own private uploads expose a Delete button. -->
        {#if canUpload || activeDocuments.length > 0}
          <div class="bg-gray-50 dark:bg-gray-800 rounded-2xl p-5">
            <h2 class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
              My Documents ({activeDocuments.length})
            </h2>

            {#if docsLoading}
              <p class="text-sm text-gray-400 py-4 text-center">Loading documents...</p>
            {:else if activeDocuments.length === 0}
              <p class="text-sm text-gray-400 py-4 text-center">No documents available yet</p>
            {:else}
              <div class="space-y-4">
                {#each groupedDocuments as [groupLabel, groupDocs] (groupLabel)}
                  <div>
                    <p class="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1.5 px-1">
                      {groupLabel}
                    </p>
                    <div class="space-y-2">
                      {#each groupDocs as doc (doc.id)}
                        <div class="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-white dark:bg-gray-850
                                    border border-gray-100 dark:border-gray-700 group">
                          <span class="text-lg shrink-0">{getFileIcon(doc.title)}</span>
                          <div class="flex-1 min-w-0">
                            <p class="text-sm text-gray-800 dark:text-gray-200 truncate font-medium">{doc.title}</p>
                            <div class="flex items-center gap-2 mt-0.5">
                              <span class="px-1.5 py-0 rounded text-[9px] font-medium {getStatusBadge(doc.status)}">
                                {doc.status}
                              </span>
                              <span class="text-[10px] text-gray-400">{doc.chunk_count} chunks</span>
                              <span class="text-[10px] text-gray-400">{uploaderRoleLabel(doc.uploader_role)}</span>
                            </div>
                          </div>
                          <div class="shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition">
                            <button
                              onclick={() => handleViewDocument(doc.id)}
                              class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800
                                     text-gray-400 hover:text-blue-600 transition"
                              title="Open in a new tab"
                              aria-label="View document"
                            >
                              <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                                <circle cx="12" cy="12" r="3" />
                              </svg>
                            </button>

                            <button
                              onclick={() => handleDownloadDocument(doc.id, doc.title)}
                              class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800
                                     text-gray-400 hover:text-blue-600 transition"
                              title="Download"
                              aria-label="Download document"
                            >
                              <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                <polyline points="7 10 12 15 17 10" />
                                <line x1="12" y1="15" x2="12" y2="3" />
                              </svg>
                            </button>

                            {#if doc.can_delete}
                              <button
                                onclick={() => handleDeleteDocument(doc)}
                                class="p-1.5 rounded-lg
                                       hover:bg-red-50 dark:hover:bg-red-900/20
                                       text-gray-400 hover:text-red-500 transition"
                                title="Delete document"
                                aria-label="Delete document"
                              >
                                <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                  <polyline points="3 6 5 6 21 6" />
                                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                                </svg>
                              </button>
                            {/if}
                          </div>
                        </div>
                      {/each}
                    </div>
                  </div>
                {/each}
              </div>

              {#if activeDocuments.length > 3}
                <button
                  onclick={() => docsExpanded = !docsExpanded}
                  class="w-full mt-3 py-1.5 text-xs text-center text-blue-600 dark:text-blue-400
                         hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition font-medium"
                >
                  {docsExpanded ? 'Show less' : `Show all ${activeDocuments.length} documents`}
                </button>
              {/if}
            {/if}
          </div>
        {/if}

        <!-- Account Status -->
        <div class="bg-gray-50 dark:bg-gray-800 rounded-2xl p-5">
          <h2 class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Account Status</h2>
          <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded-full text-xs font-medium {getFlagColor(profile.flags.level)}">
              {profile.flags.level}
            </span>
            {#if profile.flags.offense_count_mild + profile.flags.offense_count_severe > 0}
              <span class="text-xs text-gray-400">
                ({profile.flags.offense_count_mild + profile.flags.offense_count_severe} violations)
              </span>
            {/if}
          </div>
          {#if profile.flags.level === 'suspended'}
            <p class="text-sm text-red-500 mt-2">
              Your account is suspended. Please contact your instructor or advisor.
            </p>
          {:else if profile.flags.level === 'restricted'}
            <p class="text-sm text-orange-500 mt-2">
              Your account has warnings. Please follow community guidelines.
            </p>
          {:else if profile.flags.level === 'warned'}
            <p class="text-sm text-yellow-600 dark:text-yellow-400 mt-2">
              You have received a warning. Please keep conversations respectful.
            </p>
          {/if}
        </div>

        <!-- Danger Zone -->
        <div class="rounded-2xl border border-red-200 dark:border-red-900/40 bg-red-50/40 dark:bg-red-900/10 p-5">
          <h2 class="text-xs font-medium text-red-600 dark:text-red-400 uppercase tracking-wider mb-2">Danger zone</h2>
          <p class="text-sm text-gray-700 dark:text-gray-300 mb-1">Delete my account</p>
          <p class="text-xs text-gray-500 dark:text-gray-400 mb-4">
            Permanently removes your sign-in, your private uploads, your conversations, and your enrollments. This cannot be undone.
          </p>
          <button
            onclick={() => { deleteConfirmText = ''; showDeleteConfirm = true; }}
            class="text-xs px-3 py-1.5 rounded-lg bg-red-600 text-white hover:bg-red-700 transition font-medium">
            Delete account
          </button>
        </div>
      </div>
    {:else}
      <div class="flex items-center justify-center h-48">
        <p class="text-sm text-gray-400">Failed to load profile</p>
      </div>
    {/if}
  </div>
</div>

{#if showDeleteConfirm && profile}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4"
       onclick={() => { if (!deleting) showDeleteConfirm = false; }}>
    <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-xl max-w-md w-full p-6"
         onclick={(e) => e.stopPropagation()}>
      <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-2">
        Delete this account?
      </h3>
      <p class="text-sm text-gray-700 dark:text-gray-300 mb-2">
        This permanently removes your sign-in, private uploads, conversations,
        and enrollments. Course materials and baseline content stay intact.
      </p>
      <p class="text-xs text-gray-500 dark:text-gray-400 mb-3">
        Type your email to confirm:
        <span class="font-mono text-gray-700 dark:text-gray-200">{profile.email}</span>
      </p>
      <input
        type="email"
        autocomplete="off"
        bind:value={deleteConfirmText}
        disabled={deleting}
        placeholder={profile.email ?? ''}
        class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
               bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
               focus:ring-1 focus:ring-red-500 transition mb-4 disabled:opacity-50"
      />
      <div class="flex gap-2 justify-end">
        <button
          onclick={() => { if (!deleting) showDeleteConfirm = false; }}
          disabled={deleting}
          class="px-3.5 py-1.5 text-sm rounded-full border border-gray-200 dark:border-gray-700
                 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition
                 disabled:opacity-50">
          Cancel
        </button>
        <button
          onclick={handleDeleteAccount}
          disabled={!deleteEnabled || deleting}
          class="px-3.5 py-1.5 text-sm rounded-full bg-red-600 text-white hover:bg-red-700 transition
                 disabled:opacity-50 disabled:cursor-not-allowed">
          {deleting ? 'Deleting…' : 'Delete account'}
        </button>
      </div>
    </div>
  </div>
{/if}
