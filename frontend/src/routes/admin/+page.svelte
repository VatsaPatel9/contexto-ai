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
    listCourses,
    createCourse,
    deleteCourse,
    listCourseMembers,
    enrollMember,
    unenrollMember,
    type UserProfile,
    type Violation,
    type Course,
    type CourseMember,
  } from '$lib/apis/admin';
  import { session } from '$lib/stores';
  import { listDocuments, deleteDocument, type UploadedDocument } from '$lib/apis/documents';

  // ── State ───────────────────────────────────────────────────────────

  type Tab = 'users' | 'courses' | 'violations';
  let activeTab = $state<Tab>('users');

  // Courses
  let courses = $state<Course[]>([]);
  let coursesLoaded = $state(false);
  let selectedCourse = $state<Course | null>(null);
  let courseMembers = $state<CourseMember[]>([]);
  let membersLoading = $state(false);

  let newCourseId = $state('');
  let newCourseName = $state('');
  let newCourseDesc = $state('');
  let creatingCourse = $state(false);

  let memberIdentifier = $state('');
  let memberStudyId = $state('');
  let enrolling = $state(false);
  let showEnrollDropdown = $state(false);

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

  /** Get a human-readable label for a user ID — full display name or full email, never the ID. */
  function userLabel(userId: string): string {
    const cached = userNameCache[userId];
    if (cached?.displayName) return cached.displayName;
    if (cached?.email) return cached.email;
    return 'Loading…';
  }

  /** Secondary label (email when display name is the primary), or empty. */
  function userSubLabel(userId: string): string {
    const cached = userNameCache[userId];
    if (cached?.displayName && cached?.email) return cached.email;
    return '';
  }

  /** Get initials for avatar. */
  function userInitials(userId: string): string {
    const cached = userNameCache[userId];
    if (cached?.displayName) return cached.displayName.slice(0, 2).toUpperCase();
    if (cached?.email) return cached.email.slice(0, 2).toUpperCase();
    return '??';
  }

  // Search dropdown
  let searchQuery = $state('');
  let showDropdown = $state(false);
  let searchResults = $derived(() => {
    const currentUserId = $authStore.userId;
    // Exclude the currently logged-in admin from their own user picker —
    // self-management belongs on the profile page, not here.
    const all = allUserIds().filter((id) => id !== currentUserId);
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
    confirmMessage = `Ban ${userLabel(userId)}? They will be unable to send messages.`;
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
    confirmMessage = `Promote ${userLabel(userId)} to admin?`;
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
    confirmMessage = `Remove admin role from ${userLabel(userId)}?`;
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

  // ── Courses ─────────────────────────────────────────────────────────

  async function loadCourses() {
    try {
      courses = await listCourses();
      coursesLoaded = true;
    } catch (e: any) {
      toast.error(e.message || 'Failed to load courses');
    }
  }

  async function selectCourse(course: Course) {
    selectedCourse = course;
    courseMembers = [];
    membersLoading = true;
    try {
      courseMembers = await listCourseMembers(course.course_id);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      membersLoading = false;
    }
  }

  async function handleCreateCourse() {
    const id = newCourseId.trim();
    const name = newCourseName.trim();
    if (!id || !name) {
      toast.error('Course ID and name are required');
      return;
    }
    creatingCourse = true;
    try {
      const created = await createCourse({
        course_id: id,
        name,
        description: newCourseDesc.trim() || undefined,
      });
      toast.success(`Course "${created.name}" created`);
      newCourseId = '';
      newCourseName = '';
      newCourseDesc = '';
      await loadCourses();
      const fresh = courses.find((c) => c.course_id === created.course_id);
      if (fresh) selectCourse(fresh);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      creatingCourse = false;
    }
  }

  async function handleDeleteCourse(course: Course) {
    confirmMessage = `Delete course "${course.name}"? Documents and enrollments will be removed.`;
    confirmAction = async () => {
      try {
        await deleteCourse(course.course_id);
        toast.success('Course deleted');
        if (selectedCourse?.course_id === course.course_id) {
          selectedCourse = null;
          courseMembers = [];
        }
        await loadCourses();
      } catch (e: any) {
        toast.error(e.message);
      }
    };
    showConfirm = true;
  }

  async function handleEnrollMember(identifier?: string, label?: string) {
    if (!selectedCourse) return;
    const id = (identifier ?? memberIdentifier).trim();
    if (!id) {
      toast.error('Pick a user from the list or type an email');
      return;
    }
    enrolling = true;
    try {
      const enrolled = await enrollMember(selectedCourse.course_id, id, memberStudyId.trim() || undefined);
      const shown = label || enrolled.display_name || enrolled.email || id;
      toast.success(`Enrolled ${shown}`);
      memberIdentifier = '';
      memberStudyId = '';
      courseMembers = await listCourseMembers(selectedCourse.course_id);
      await loadCourses();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      enrolling = false;
    }
  }

  // Candidate users for the enroll picker: every known user except the
  // caller and anyone already enrolled in the selected course, filtered by
  // the search box. Uses the existing usersByRole + userNameCache —
  // no extra API call needed.
  let enrollCandidates = $derived(() => {
    const enrolledIds = new Set(courseMembers.map((m) => m.user_id));
    const callerId = $authStore.userId;
    const q = memberIdentifier.trim().toLowerCase();
    return allUserIds()
      .filter((id) => id !== callerId && !enrolledIds.has(id))
      .filter((id) => {
        if (!q) return true;
        if (id.toLowerCase().includes(q)) return true;
        const cached = userNameCache[id];
        if (cached?.displayName?.toLowerCase().includes(q)) return true;
        if (cached?.email?.toLowerCase().includes(q)) return true;
        return false;
      });
  });

  async function handleUnenrollMember(member: CourseMember) {
    if (!selectedCourse) return;
    const label = member.display_name || member.email || 'this user';
    confirmMessage = `Remove ${label} from "${selectedCourse.name}"?`;
    confirmAction = async () => {
      try {
        await unenrollMember(selectedCourse!.course_id, member.user_id);
        toast.success('Member removed');
        courseMembers = await listCourseMembers(selectedCourse!.course_id);
        await loadCourses();
      } catch (e: any) {
        toast.error(e.message);
      }
    };
    showConfirm = true;
  }

  $effect(() => {
    if (activeTab === 'courses' && !coursesLoaded) {
      loadCourses();
    }
  });
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
<div class="flex h-full">
  <!-- Left sidebar -->
  <aside class="w-56 shrink-0 border-r border-gray-100 dark:border-gray-800 flex flex-col bg-white dark:bg-gray-900">
    <div class="px-4 py-4 border-b border-gray-100 dark:border-gray-800">
      <h1 class="text-base font-semibold text-gray-900 dark:text-white">Admin Panel</h1>
    </div>
    <nav class="flex-1 px-2 py-3 space-y-0.5">
      <button onclick={() => goto('/chat')}
              class="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium
                     text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition">
        <svg xmlns="http://www.w3.org/2000/svg" class="size-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6" />
        </svg>
        Chat
      </button>
      <div class="h-px bg-gray-100 dark:bg-gray-800 my-2 mx-2"></div>
      <button onclick={() => activeTab = 'users'}
              class="w-full flex items-center justify-between gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition
                     {activeTab === 'users'
                       ? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
                       : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'}">
        <span class="flex items-center gap-2.5">
          <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
          </svg>
          Users
        </span>
        <span class="text-[10px] {activeTab === 'users' ? 'opacity-70' : 'text-gray-400'}">{allUserIds().length}</span>
      </button>
      <button onclick={() => activeTab = 'courses'}
              class="w-full flex items-center justify-between gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition
                     {activeTab === 'courses'
                       ? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
                       : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'}">
        <span class="flex items-center gap-2.5">
          <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
          </svg>
          Courses
        </span>
        {#if coursesLoaded}
          <span class="text-[10px] {activeTab === 'courses' ? 'opacity-70' : 'text-gray-400'}">{courses.length}</span>
        {/if}
      </button>
      <button onclick={() => activeTab = 'violations'}
              class="w-full flex items-center justify-between gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition
                     {activeTab === 'violations'
                       ? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
                       : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'}">
        <span class="flex items-center gap-2.5">
          <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          Violations
        </span>
        {#if violations.length > 0}
          <span class="px-1.5 py-0.5 text-[10px] rounded-full bg-red-500 text-white">{violations.length}</span>
        {/if}
      </button>
    </nav>
  </aside>

  <!-- Main content -->
  <div class="flex-1 overflow-y-auto">
    <div class="max-w-5xl mx-auto w-full">
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
                placeholder="Search users by name or email..."
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
                          {#if userSubLabel(userId)}
                            <span class="text-[10px] text-gray-400 truncate">{userSubLabel(userId)}</span>
                          {/if}
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

        <!-- ═══ USER DETAIL — TILE GRID ═══ -->
        {#if detailLoading}
          <div class="px-4 py-12 text-center text-gray-400 text-sm">Loading user details...</div>
        {:else if selectedProfile}
          <div class="px-4 pt-4 pb-8 space-y-4">

            <!-- Header card -->
            <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 px-5 py-4">
              <div class="flex items-start gap-4">
                <div class="shrink-0 size-12 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                            flex items-center justify-center text-white text-base font-bold uppercase">
                  {userInitials(selectedProfile.user_id)}
                </div>
                <div class="flex-1 min-w-0">
                  <h2 class="text-lg font-semibold text-gray-900 dark:text-white truncate">
                    {selectedProfile.display_name || selectedProfile.email || 'Loading…'}
                  </h2>
                  {#if selectedProfile.display_name && selectedProfile.email}
                    <p class="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">{selectedProfile.email}</p>
                  {/if}
                  <div class="flex items-center gap-1.5 mt-2 flex-wrap">
                    {#each selectedProfile.roles as role}
                      <span class="px-2 py-0.5 rounded-full text-[10px] font-medium {getRoleBadgeColor(role)}">
                        {role.replace('_', ' ')}
                      </span>
                    {/each}
                  </div>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                  {#if isSuperAdmin}
                    {#if !selectedProfile.roles.includes('admin')}
                      <button onclick={() => handlePromoteToAdmin(selectedProfile!.user_id)}
                              class="text-xs px-3 py-1.5 rounded-lg bg-amber-50 text-amber-700 hover:bg-amber-100
                                     dark:bg-amber-900/20 dark:text-amber-400 dark:hover:bg-amber-900/40 transition font-medium">
                        Promote
                      </button>
                    {:else if !selectedProfile.roles.includes('super_admin')}
                      <button onclick={() => handleDemoteFromAdmin(selectedProfile!.user_id)}
                              class="text-xs px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200
                                     dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600 transition font-medium">
                        Demote
                      </button>
                    {/if}
                  {/if}
                  <button onclick={() => selectedProfile = null}
                          class="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5"
                          aria-label="Close user detail">
                    <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                  </button>
                </div>
              </div>
            </div>

            <!-- 2-column tile grid -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">

              <!-- Document Upload tile -->
              <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
                <div class="flex items-center justify-between mb-4">
                  <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">Document Upload</div>
                  <button onclick={handleToggleUpload}
                          class="relative inline-flex h-5 w-9 items-center rounded-full transition-colors
                                 {uploadEnabled ? 'bg-blue-600' : 'bg-gray-300 dark:bg-gray-600'}"
                          aria-label={uploadEnabled ? 'Revoke upload permission' : 'Grant upload permission'}>
                    <span class="inline-block size-3.5 transform rounded-full bg-white shadow transition-transform
                                 {uploadEnabled ? 'translate-x-5' : 'translate-x-0.5'}"></span>
                  </button>
                </div>
                <div class="flex items-baseline gap-2 mb-3">
                  <div class="text-2xl font-bold text-gray-900 dark:text-white">{selectedProfile.uploads.count}</div>
                  <div class="text-xs text-gray-400">/ {selectedProfile.uploads.limit ?? '∞'} documents</div>
                </div>
                {#if uploadEnabled && selectedProfile.uploads.limit}
                  <div class="h-1.5 rounded-full bg-gray-100 dark:bg-gray-700 overflow-hidden mb-3">
                    <div class="h-full rounded-full transition-all
                                {selectedProfile.uploads.count / selectedProfile.uploads.limit > 0.9 ? 'bg-red-500' : 'bg-blue-500'}"
                         style="width: {Math.min(100, (selectedProfile.uploads.count / selectedProfile.uploads.limit) * 100)}%"></div>
                  </div>
                {/if}
                {#if uploadEnabled}
                  <div class="flex gap-2">
                    <input type="text" bind:value={editUploadLimit} placeholder="Limit (number or unlimited)"
                           class="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                                  bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                                  focus:ring-1 focus:ring-blue-500 transition" />
                    <button onclick={handleSaveUploadLimit}
                            class="px-3 py-2 text-sm rounded-lg bg-gray-900 text-white hover:bg-gray-800
                                   dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100 transition font-medium">
                      Save
                    </button>
                  </div>
                {:else}
                  <p class="text-xs text-gray-400">Toggle on to grant document upload permission.</p>
                {/if}
              </div>

              <!-- Token Usage tile -->
              <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
                <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-4">Token Usage</div>
                <div class="grid grid-cols-3 gap-2 mb-3">
                  <div class="rounded-lg bg-gray-50 dark:bg-gray-800 p-2.5 text-center">
                    <div class="text-base font-semibold text-gray-900 dark:text-white">{formatTokens(selectedProfile.tokens.in)}</div>
                    <div class="text-[9px] text-gray-400 uppercase mt-0.5">In</div>
                  </div>
                  <div class="rounded-lg bg-gray-50 dark:bg-gray-800 p-2.5 text-center">
                    <div class="text-base font-semibold text-gray-900 dark:text-white">{formatTokens(selectedProfile.tokens.out)}</div>
                    <div class="text-[9px] text-gray-400 uppercase mt-0.5">Out</div>
                  </div>
                  <div class="rounded-lg bg-gray-50 dark:bg-gray-800 p-2.5 text-center">
                    <div class="text-base font-semibold text-gray-900 dark:text-white">{formatTokens(selectedProfile.tokens.total)}</div>
                    <div class="text-[9px] text-gray-400 uppercase mt-0.5">Total</div>
                  </div>
                </div>
                {#if selectedProfile.tokens.limit}
                  <div class="mb-3">
                    <div class="h-1.5 rounded-full bg-gray-100 dark:bg-gray-700 overflow-hidden">
                      <div class="h-full rounded-full transition-all {selectedProfile.tokens.total / selectedProfile.tokens.limit > 0.9 ? 'bg-red-500' : 'bg-blue-500'}"
                           style="width: {Math.min(100, (selectedProfile.tokens.total / selectedProfile.tokens.limit) * 100)}%"></div>
                    </div>
                    <div class="text-[10px] text-gray-400 mt-1 text-right">
                      {formatTokens(selectedProfile.tokens.total)} / {formatTokens(selectedProfile.tokens.limit)}
                    </div>
                  </div>
                {/if}
                <div class="flex gap-2">
                  <input type="text" bind:value={editTokenLimit} placeholder="Limit (number or none)"
                         class="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                                bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                                focus:ring-1 focus:ring-blue-500 transition" />
                  <button onclick={handleSaveTokenLimit}
                          class="px-3 py-2 text-sm rounded-lg bg-gray-900 text-white hover:bg-gray-800
                                 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100 transition font-medium">
                    Save
                  </button>
                </div>
              </div>

              <!-- Violations tile -->
              <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
                <div class="flex items-center justify-between mb-4">
                  <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">Violations</div>
                  <span class="px-2 py-0.5 rounded-full text-[10px] font-medium {getFlagColor(selectedProfile.flags.level)}">
                    {selectedProfile.flags.level}
                  </span>
                </div>
                <div class="grid grid-cols-2 gap-2 mb-3">
                  <div class="rounded-lg bg-gray-50 dark:bg-gray-800 p-2.5 text-center">
                    <div class="text-base font-semibold text-gray-900 dark:text-white">{selectedProfile.flags.offense_count_mild}</div>
                    <div class="text-[9px] text-gray-400 uppercase mt-0.5">Mild</div>
                  </div>
                  <div class="rounded-lg bg-gray-50 dark:bg-gray-800 p-2.5 text-center">
                    <div class="text-base font-semibold text-gray-900 dark:text-white">{selectedProfile.flags.offense_count_severe}</div>
                    <div class="text-[9px] text-gray-400 uppercase mt-0.5">Severe</div>
                  </div>
                </div>
                {#if selectedProfile.flags.notes}
                  <pre class="text-[11px] text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800
                              rounded-lg p-2.5 overflow-x-auto max-h-24 whitespace-pre-wrap mb-3">{selectedProfile.flags.notes}</pre>
                {/if}
                {#if selectedProfile.flags.level !== 'suspended'}
                  <button onclick={() => handleBan(selectedProfile!.user_id)}
                          class="w-full text-xs px-3 py-2 rounded-lg bg-red-50 text-red-700 hover:bg-red-100
                                 dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/40 transition font-medium">
                    Ban User
                  </button>
                {:else}
                  <button onclick={() => handleUnban(selectedProfile!.user_id)}
                          class="w-full text-xs px-3 py-2 rounded-lg bg-green-50 text-green-700 hover:bg-green-100
                                 dark:bg-green-900/20 dark:text-green-400 dark:hover:bg-green-900/40 transition font-medium">
                    Unban User
                  </button>
                {/if}
              </div>

              <!-- Documents tile -->
              <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
                <div class="flex items-center justify-between mb-4">
                  <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">
                    Documents · {userDocuments.filter(d => !d.deleted_at).length}
                  </div>
                  {#if userDocsLoading}
                    <div class="size-3.5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                  {/if}
                </div>
                {#if userDocuments.length === 0 && !userDocsLoading}
                  <p class="text-xs text-gray-400 py-6 text-center">No documents uploaded</p>
                {:else}
                  <div class="space-y-1.5 max-h-72 overflow-y-auto">
                    {#each userDocuments as doc (doc.id)}
                      <div class="flex items-center gap-2.5 px-2.5 py-2 rounded-lg group
                                  {doc.deleted_at
                                    ? 'bg-red-50/50 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30'
                                    : 'bg-gray-50 dark:bg-gray-800 border border-gray-100 dark:border-gray-700'}">
                        <span class="text-base shrink-0">{getFileIcon(doc.title)}</span>
                        <div class="flex-1 min-w-0">
                          <p class="text-xs text-gray-800 dark:text-gray-200 truncate font-medium
                                    {doc.deleted_at ? 'line-through opacity-60' : ''}">{doc.title}</p>
                          <div class="flex items-center gap-1.5 mt-0.5">
                            <span class="px-1 py-0 rounded text-[8px] font-medium {getStatusBadge(doc.status)}">{doc.status}</span>
                            <span class="text-[9px] text-gray-400">{doc.chunk_count} chunks</span>
                            <span class="text-[9px] text-gray-400">{doc.visibility === 'private' ? '🔒' : '🌐'}</span>
                            {#if doc.deleted_at}
                              <span class="text-[9px] text-red-400">deleted</span>
                            {/if}
                          </div>
                        </div>
                        {#if !doc.deleted_at}
                          <button onclick={() => handleDeleteUserDocument(doc.id, doc.title)}
                                  class="shrink-0 p-1 rounded-lg opacity-0 group-hover:opacity-100
                                         hover:bg-red-50 dark:hover:bg-red-900/20
                                         text-gray-400 hover:text-red-500 transition"
                                  aria-label="Delete document">
                            <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                              <polyline points="3 6 5 6 21 6" />
                              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                            </svg>
                          </button>
                        {/if}
                      </div>
                    {/each}
                  </div>
                {/if}
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

      {:else if activeTab === 'courses'}

        <!-- ═══ COURSES TAB ═══ -->
        <div class="px-4 pt-4 pb-8 space-y-6">

          <!-- Create course (compact) -->
          <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
            <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-3">New Course</div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
              <input type="text" bind:value={newCourseId} placeholder="course_id (e.g. bio7-control)"
                     class="px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                            bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                            focus:ring-1 focus:ring-blue-500 transition" />
              <input type="text" bind:value={newCourseName} placeholder="Display name (e.g. Biology 7 — Control)"
                     class="px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                            bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                            focus:ring-1 focus:ring-blue-500 transition" />
            </div>
            <div class="flex gap-2 mt-2">
              <input type="text" bind:value={newCourseDesc} placeholder="Description (optional)"
                     class="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                            bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                            focus:ring-1 focus:ring-blue-500 transition" />
              <button onclick={handleCreateCourse} disabled={creatingCourse}
                      class="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition font-medium disabled:opacity-50 whitespace-nowrap">
                {creatingCourse ? 'Creating...' : 'Create Course'}
              </button>
            </div>
          </div>

          <!-- Course tile grid -->
          <div>
            <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-3">Your Courses</div>
            {#if !coursesLoaded}
              <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 px-4 py-10 text-center text-gray-400 text-sm">Loading…</div>
            {:else if courses.length === 0}
              <div class="rounded-2xl border border-dashed border-gray-200 dark:border-gray-700 px-4 py-10 text-center text-gray-400 text-sm">
                No courses yet — create one above.
              </div>
            {:else}
              <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {#each courses as c (c.course_id)}
                  <button onclick={() => selectCourse(c)}
                          class="text-left rounded-2xl border bg-white dark:bg-gray-850 p-4 transition
                                 {selectedCourse?.course_id === c.course_id
                                   ? 'border-blue-500 ring-1 ring-blue-500/30 dark:border-blue-400'
                                   : 'border-gray-100 dark:border-gray-800 hover:border-gray-200 dark:hover:border-gray-700'}">
                    <div class="flex items-start justify-between gap-2">
                      <div class="min-w-0">
                        <div class="text-sm font-semibold text-gray-900 dark:text-white truncate">{c.name}</div>
                        <div class="text-[10px] font-mono text-gray-400 mt-0.5 truncate">{c.course_id}</div>
                      </div>
                      <div onclick={(e) => { e.stopPropagation(); handleDeleteCourse(c); }}
                           role="button" tabindex="0"
                           onkeydown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); handleDeleteCourse(c); } }}
                           class="shrink-0 p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition cursor-pointer"
                           title="Delete course">
                        <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                      </div>
                    </div>
                    {#if c.description}
                      <p class="text-xs text-gray-500 dark:text-gray-400 mt-2 line-clamp-2">{c.description}</p>
                    {/if}
                    <div class="flex items-center gap-2 mt-3">
                      <span class="px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
                        {c.member_count} member{c.member_count === 1 ? '' : 's'}
                      </span>
                    </div>
                  </button>
                {/each}
              </div>
            {/if}
          </div>

          <!-- Selected course: 2-column member panel -->
          {#if selectedCourse}
            <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 overflow-hidden">

              <div class="px-5 py-4 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between">
                <div>
                  <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">Members</div>
                  <div class="text-sm font-semibold text-gray-900 dark:text-white mt-0.5">{selectedCourse.name}</div>
                </div>
                <button onclick={() => { selectedCourse = null; courseMembers = []; }}
                        aria-label="Close member panel"
                        class="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5">
                  <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </button>
              </div>

              <div class="grid grid-cols-1 lg:grid-cols-2 gap-px bg-gray-100 dark:bg-gray-800">

                <!-- Add-member column -->
                <div class="bg-white dark:bg-gray-850 px-5 py-4">
                  <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-3">Add member</div>

                  <div class="relative mb-2">
                    <div class="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700
                                bg-white dark:bg-gray-850 focus-within:ring-1 focus-within:ring-blue-500 transition cursor-pointer"
                         onclick={() => (showEnrollDropdown = true)}>
                      <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-gray-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
                      </svg>
                      <input type="text" bind:value={memberIdentifier}
                             onfocus={() => (showEnrollDropdown = true)}
                             oninput={() => (showEnrollDropdown = true)}
                             onclick={(e) => e.stopPropagation()}
                             placeholder="Search by name or email"
                             class="flex-1 text-sm bg-transparent outline-none text-gray-900 dark:text-white placeholder:text-gray-400" />
                      {#if memberIdentifier}
                        <button onclick={(e) => { e.stopPropagation(); memberIdentifier = ''; }}
                                aria-label="Clear search"
                                class="p-0.5 rounded hover:bg-black/5 dark:hover:bg-white/5">
                          <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                          </svg>
                        </button>
                      {/if}
                      <svg xmlns="http://www.w3.org/2000/svg"
                           class="size-4 text-gray-400 shrink-0 transition-transform {showEnrollDropdown ? 'rotate-180' : ''}"
                           viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="6 9 12 15 18 9" />
                      </svg>
                    </div>

                    {#if showEnrollDropdown}
                      <div class="fixed inset-0 z-30" onclick={() => (showEnrollDropdown = false)}></div>
                      <div class="absolute left-0 right-0 mt-1 z-40 max-h-72 overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850 shadow-lg">
                        {#if enrollCandidates().length === 0}
                          <p class="px-3 py-6 text-xs text-center text-gray-400">
                            {memberIdentifier.trim() ? 'No matching users.' : 'No users available to enroll.'}
                          </p>
                        {:else}
                          {#each enrollCandidates() as candId (candId)}
                            {@const cached = userNameCache[candId]}
                            {@const label = cached?.displayName || cached?.email || 'Loading…'}
                            {@const initials = (cached?.displayName || cached?.email || '??').slice(0, 2).toUpperCase()}
                            <div class="flex items-center gap-2.5 px-3 py-2 border-b last:border-b-0 border-gray-100 dark:border-gray-800
                                        hover:bg-gray-50 dark:hover:bg-gray-800 transition">
                              <div class="shrink-0 size-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                                          flex items-center justify-center text-white text-[10px] font-bold uppercase">
                                {initials}
                              </div>
                              <div class="flex-1 min-w-0">
                                <div class="text-sm text-gray-800 dark:text-gray-200 truncate font-medium">{label}</div>
                                <div class="flex items-center gap-1.5 mt-0.5 flex-wrap">
                                  {#if cached?.email && cached?.displayName}
                                    <span class="text-[10px] text-gray-400 truncate">{cached.email}</span>
                                  {/if}
                                  {#each getUserRoleDisplay(candId) as role}
                                    <span class="px-1 py-0 rounded text-[8px] font-medium {getRoleBadgeColor(role)}">
                                      {role.replace('_', ' ')}
                                    </span>
                                  {/each}
                                </div>
                              </div>
                              <button onclick={() => handleEnrollMember(cached?.email || cached?.displayName || candId, label)}
                                      disabled={enrolling}
                                      class="shrink-0 text-[11px] px-2.5 py-1 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100
                                             dark:bg-blue-900/20 dark:text-blue-400 dark:hover:bg-blue-900/40 transition font-medium
                                             disabled:opacity-50">
                                Add
                              </button>
                            </div>
                          {/each}
                        {/if}
                      </div>
                    {/if}
                  </div>

                  <div class="flex gap-2">
                    <input type="text" bind:value={memberStudyId} placeholder="Study ID (optional)"
                           class="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                                  bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                                  focus:ring-1 focus:ring-blue-500 transition" />
                    {#if memberIdentifier.trim() && enrollCandidates().length === 0}
                      <button onclick={() => handleEnrollMember()} disabled={enrolling}
                              class="px-3 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition font-medium disabled:opacity-50 whitespace-nowrap">
                        {enrolling ? 'Adding...' : 'Add typed'}
                      </button>
                    {/if}
                  </div>
                  <p class="text-[10px] text-gray-400 mt-2">Click a user from the list above to enroll. Study ID applies to the next add.</p>
                </div>

                <!-- Members list column -->
                <div class="bg-white dark:bg-gray-850 px-5 py-4">
                  <div class="flex items-center justify-between mb-3">
                    <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">
                      Enrolled · {courseMembers.length}
                    </div>
                    {#if membersLoading}
                      <div class="size-3.5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                    {/if}
                  </div>
                  {#if courseMembers.length === 0 && !membersLoading}
                    <p class="text-xs text-gray-400 py-6 text-center">No members yet.</p>
                  {:else}
                    <div class="space-y-1.5 max-h-96 overflow-y-auto">
                      {#each courseMembers as m (m.user_id)}
                        <div class="flex items-center gap-2.5 px-2.5 py-2 rounded-lg bg-gray-50 dark:bg-gray-800 group">
                          <div class="shrink-0 size-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                                      flex items-center justify-center text-white text-[10px] font-bold uppercase">
                            {(m.display_name || m.email || '??').slice(0, 2).toUpperCase()}
                          </div>
                          <div class="flex-1 min-w-0">
                            <div class="text-sm text-gray-900 dark:text-white truncate font-medium">
                              {m.display_name || m.email || 'Loading…'}
                            </div>
                            <div class="flex items-center gap-1.5 mt-0.5">
                              {#if m.email && m.display_name}
                                <span class="text-[10px] text-gray-400 truncate">{m.email}</span>
                              {/if}
                              {#if m.study_id}
                                <span class="px-1.5 py-0 rounded text-[9px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                                  {m.study_id}
                                </span>
                              {/if}
                            </div>
                          </div>
                          <button onclick={() => handleUnenrollMember(m)}
                                  class="shrink-0 text-[11px] px-2.5 py-1 rounded-lg bg-red-50 text-red-700 hover:bg-red-100
                                         dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/40 transition font-medium
                                         opacity-0 group-hover:opacity-100">
                            Remove
                          </button>
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>
              </div>
            </div>
          {/if}
        </div>

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
