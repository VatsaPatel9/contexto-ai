<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { toast } from 'svelte-sonner';

  import { authStore } from '$lib/stores/auth';
  import {
    usersByRole as usersByRoleStore,
    userNameCache as userNameCacheStore,
    loadAdminUsers,
    allKnownUserIds,
  } from '$lib/stores/admin';
  import {
    listCourses,
    listCourseMembers,
    enrollMember,
    unenrollMember,
    deleteCourse,
    updateCourse,
    type Course,
    type CourseMember,
  } from '$lib/apis/admin';
  import {
    listExams,
    createExam,
    deleteExam,
    formatLocalDeadline,
    localInputToUtcIso,
    type ExamSummary,
  } from '$lib/apis/exams';
  import DocumentManager from '$lib/components/admin/DocumentManager.svelte';

  // Route param
  let courseId = $derived(($page.params as Record<string, string>).course_id);

  // Active tab driven by URL ?tab= so deep links work.
  type Tab = 'members' | 'exams';
  let activeTab = $derived((($page.url.searchParams.get('tab') as Tab) || 'members'));
  function setTab(t: Tab) {
    const params = new URLSearchParams($page.url.searchParams);
    params.set('tab', t);
    goto(`/admin/courses/${encodeURIComponent(courseId)}?${params.toString()}`);
  }

  // Data
  let course = $state<Course | null>(null);
  let members = $state<CourseMember[]>([]);
  let loading = $state(true);

  // Exams (lazy-loaded when the Exams tab opens for the first time)
  let exams = $state<ExamSummary[]>([]);
  let examsLoaded = $state(false);
  let creatingExam = $state(false);

  // Create-exam form
  let newExamTitle = $state('');
  let newExamDeadline = $state('');         // datetime-local string in viewer TZ
  let newExamTimeLimit = $state<string>('60'); // minutes; '' means untimed

  // Add-member state
  let memberQuery = $state('');
  let memberStudyId = $state('');
  let enrolling = $state(false);

  // Confirm dialog
  let showConfirm = $state(false);
  let confirmMessage = $state('');
  let confirmAction = $state<(() => Promise<void>) | null>(null);

  // ── Derived ────────────────────────────────────────────────────────

  let usersByRole = $derived($usersByRoleStore);
  let userNameCache = $derived($userNameCacheStore);

  // Super_admins can audit any course's materials (view + delete) but
  // shouldn't upload here — their uploads belong on /admin/baseline so
  // system-wide content stays separate from per-course datasets. Course
  // admins see the full panel only on courses they own.
  let isSuperAdmin = $derived($authStore.roles.includes('super_admin'));
  let canUploadHere = $derived(
    course !== null && !isSuperAdmin && course.created_by === $authStore.userId,
  );
  let canSeeMaterials = $derived(
    course !== null && (isSuperAdmin || canUploadHere),
  );

  // Edit affordance: only the owning admin or any super_admin can rename
  // / re-describe the course. Same authorization the PUT endpoint
  // enforces — surfacing it client-side just keeps the pencil hidden
  // for users who'd 403.
  let canEditCourse = $derived(
    course !== null && (isSuperAdmin || course.created_by === $authStore.userId),
  );

  let editingMeta = $state(false);
  let editName = $state('');
  let editDescription = $state('');
  let savingMeta = $state(false);

  function startEditMeta() {
    if (!course) return;
    editName = course.name;
    editDescription = course.description ?? '';
    editingMeta = true;
  }

  function cancelEditMeta() {
    editingMeta = false;
    savingMeta = false;
  }

  async function saveMeta() {
    if (!course) return;
    const trimmed = editName.trim();
    if (!trimmed) {
      toast.error('Name cannot be empty');
      return;
    }
    savingMeta = true;
    try {
      const updated = await updateCourse(course.course_id, {
        name: trimmed,
        description: editDescription.trim(),
      });
      course = updated;
      editingMeta = false;
      toast.success('Course updated');
    } catch (e: any) {
      toast.error(e.message || 'Failed to update course');
    } finally {
      savingMeta = false;
    }
  }

  function getUserRoleDisplay(userId: string): string[] {
    const roles: string[] = [];
    for (const [role, ids] of Object.entries(usersByRole)) {
      if (ids.includes(userId)) roles.push(role);
    }
    return roles;
  }

  function getRoleBadgeColor(role: string): string {
    switch (role) {
      case 'super_admin': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
      case 'admin': return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
      case 'user_uploader': return 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400';
      default: return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400';
    }
  }

  let candidates = $derived.by(() => {
    const enrolledIds = new Set(members.map((m) => m.user_id));
    const callerId = $authStore.userId;
    const q = memberQuery.trim().toLowerCase();
    return allKnownUserIds()
      .filter((id) => id !== callerId && !enrolledIds.has(id))
      .filter((id) => {
        if (!q) return true;
        const cached = userNameCache[id];
        if (cached?.displayName?.toLowerCase().includes(q)) return true;
        if (cached?.email?.toLowerCase().includes(q)) return true;
        return false;
      });
  });

  // ── Loading ─────────────────────────────────────────────────────────

  onMount(async () => {
    if (!$authStore.roles.includes('super_admin') && !$authStore.roles.includes('admin')) {
      goto('/chat');
      return;
    }
    await Promise.all([loadAdminUsers(), loadCourse(), loadMembers()]);
    loading = false;
  });

  async function loadCourse() {
    try {
      const all = await listCourses();
      course = all.find((c) => c.course_id === courseId) ?? null;
      if (!course) {
        toast.error('Course not found');
        goto('/admin?tab=courses');
      }
    } catch (e: any) {
      toast.error(e.message || 'Failed to load course');
    }
  }

  async function loadMembers() {
    try {
      members = await listCourseMembers(courseId);
    } catch (e: any) {
      toast.error(e.message || 'Failed to load members');
    }
  }

  // ── Actions ────────────────────────────────────────────────────────

  async function addMember(identifier: string, label?: string) {
    if (!course) return;
    const id = identifier.trim();
    if (!id) {
      toast.error('Pick a user or type an email');
      return;
    }
    enrolling = true;
    try {
      const enrolled = await enrollMember(course.course_id, id, memberStudyId.trim() || undefined);
      const shown = label || enrolled.display_name || enrolled.email || id;
      toast.success(`Enrolled ${shown}`);
      memberQuery = '';
      memberStudyId = '';
      await loadMembers();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      enrolling = false;
    }
  }

  function removeMember(member: CourseMember) {
    if (!course) return;
    const label = member.display_name || member.email || 'this user';
    confirmMessage = `Remove ${label} from "${course.name}"?`;
    confirmAction = async () => {
      try {
        await unenrollMember(course!.course_id, member.user_id);
        toast.success('Member removed');
        await loadMembers();
      } catch (e: any) {
        toast.error(e.message);
      }
    };
    showConfirm = true;
  }

  function handleDeleteCourse() {
    if (!course) return;
    confirmMessage = `Delete course "${course.name}"? Documents and enrollments will be removed.`;
    confirmAction = async () => {
      try {
        await deleteCourse(course!.course_id);
        toast.success('Course deleted');
        goto('/admin?tab=courses');
      } catch (e: any) {
        toast.error(e.message);
      }
    };
    showConfirm = true;
  }

  // ── Exams ──────────────────────────────────────────────────────────

  async function loadExams() {
    try {
      exams = await listExams(courseId);
      examsLoaded = true;
    } catch (e: any) {
      toast.error(e.message || 'Failed to load exams');
    }
  }

  async function handleCreateExam() {
    if (!course) return;
    const title = newExamTitle.trim();
    if (!title) { toast.error('Exam title is required'); return; }
    if (!newExamDeadline) { toast.error('Pick a deadline'); return; }

    const deadline_at = localInputToUtcIso(newExamDeadline);
    if (new Date(deadline_at).getTime() <= Date.now()) {
      toast.error('Deadline must be in the future'); return;
    }

    const tlRaw = newExamTimeLimit.trim().toLowerCase();
    let time_limit_minutes: number | null = null;
    if (tlRaw === '' || tlRaw === 'none' || tlRaw === 'untimed') {
      time_limit_minutes = null;
    } else {
      const n = parseInt(tlRaw, 10);
      if (!Number.isFinite(n) || n < 1 || n > 24 * 60) {
        toast.error('Time limit must be 1–1440 minutes (or blank for untimed)'); return;
      }
      time_limit_minutes = n;
    }

    creatingExam = true;
    try {
      const created = await createExam(course.course_id, {
        title,
        deadline_at,
        time_limit_minutes,
      });
      toast.success(`"${created.title}" created — add questions next`);
      newExamTitle = '';
      newExamDeadline = '';
      newExamTimeLimit = '60';
      goto(`/admin/courses/${encodeURIComponent(course.course_id)}/exams/${created.id}`);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      creatingExam = false;
    }
  }

  function openExam(examId: string) {
    goto(`/admin/courses/${encodeURIComponent(courseId)}/exams/${examId}`);
  }

  function handleDeleteExam(exam: ExamSummary) {
    confirmMessage = `Delete exam "${exam.title}"? Submissions are kept; the exam disappears from listings.`;
    confirmAction = async () => {
      try {
        await deleteExam(exam.id);
        toast.success('Exam deleted');
        await loadExams();
      } catch (e: any) {
        toast.error(e.message);
      }
    };
    showConfirm = true;
  }

  function examStateBadge(state: string): string {
    switch (state) {
      case 'draft':     return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300';
      case 'published': return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
      case 'closed':    return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
      case 'archived':  return 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500';
      default:          return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300';
    }
  }

  // Derived state badge with deadline-aware "closed" override.
  function effectiveState(exam: ExamSummary): string {
    if (exam.state === 'published' && new Date(exam.deadline_at).getTime() < Date.now()) {
      return 'closed';
    }
    return exam.state;
  }

  $effect(() => {
    if (activeTab === 'exams' && course && !examsLoaded) {
      loadExams();
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

<!-- ═══ MAIN ═══ -->
<div class="flex flex-col h-full">
  <div class="flex-1 overflow-y-auto">
    <div class="max-w-6xl mx-auto w-full px-4 pt-4 pb-8 space-y-6">

      <!-- Breadcrumb / header -->
      <div class="flex items-start justify-between gap-3 flex-wrap">
        <div class="min-w-0">
          <button onclick={() => goto('/admin?tab=courses')}
                  class="inline-flex items-center gap-1.5 text-xs font-medium
                         text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition">
            <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            All courses
          </button>
          {#if editingMeta && course}
            <div class="mt-1 max-w-2xl space-y-2">
              <input
                type="text"
                bind:value={editName}
                disabled={savingMeta}
                placeholder="Course name"
                class="w-full px-3 py-2 text-2xl font-bold border border-gray-200 dark:border-gray-700 rounded-lg
                       bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                       focus:ring-1 focus:ring-blue-500 transition disabled:opacity-50"
              />
              <textarea
                bind:value={editDescription}
                disabled={savingMeta}
                rows="3"
                placeholder="Optional description"
                class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                       bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                       focus:ring-1 focus:ring-blue-500 transition resize-y disabled:opacity-50"
              ></textarea>
              <div class="flex items-center gap-3">
                <span class="text-xs font-mono text-gray-400">{courseId}</span>
                <span class="text-xs text-gray-500">{members.length} member{members.length === 1 ? '' : 's'}</span>
              </div>
              <div class="flex gap-2">
                <button onclick={cancelEditMeta} disabled={savingMeta}
                        class="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                               text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition
                               disabled:opacity-50">
                  Cancel
                </button>
                <button onclick={saveMeta} disabled={savingMeta || !editName.trim()}
                        class="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition
                               font-medium disabled:opacity-50">
                  {savingMeta ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
          {:else}
            <div class="flex items-center gap-2 mt-1">
              <h1 class="text-2xl font-bold text-gray-900 dark:text-white truncate">
                {course?.name || (loading ? 'Loading…' : 'Unknown course')}
              </h1>
              {#if canEditCourse}
                <button onclick={startEditMeta}
                        title="Edit course"
                        aria-label="Edit course"
                        class="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50
                               dark:hover:text-blue-400 dark:hover:bg-blue-900/20 transition">
                  <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                  </svg>
                </button>
              {/if}
            </div>
            <div class="flex items-center gap-3 mt-1">
              <span class="text-xs font-mono text-gray-400">{courseId}</span>
              <span class="text-xs text-gray-500">{members.length} member{members.length === 1 ? '' : 's'}</span>
            </div>
            {#if course?.description}
              <p class="text-sm text-gray-600 dark:text-gray-400 mt-2 max-w-2xl">{course.description}</p>
            {/if}
          {/if}
        </div>
        {#if course}
          <button onclick={handleDeleteCourse}
                  class="text-xs px-3 py-1.5 rounded-lg bg-red-50 text-red-700 hover:bg-red-100
                         dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/40 transition font-medium">
            Delete course
          </button>
        {/if}
      </div>

      <!-- Course materials. Owning admin gets full panel (upload + delete);
           super_admins get a read-only-upload variant so they can audit and
           remove materials without polluting the course dataset. -->
      {#if canSeeMaterials && course}
        <DocumentManager
          courseId={course.course_id}
          title="Course materials"
          description={canUploadHere
            ? 'Documents you upload here are visible only to students enrolled in this course.'
            : 'Materials uploaded by the course admin. Upload new system-wide content via Baseline.'}
          canUpload={canUploadHere}
        />
      {/if}

      <!-- Tabs: Members | Exams -->
      <div class="flex items-center gap-1 border-b border-gray-200 dark:border-gray-700">
        <button onclick={() => setTab('members')}
                class="px-4 py-2 text-sm font-medium transition border-b-2 -mb-px
                       {activeTab === 'members'
                         ? 'border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400'
                         : 'border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'}">
          Members · {members.length}
        </button>
        <button onclick={() => setTab('exams')}
                class="px-4 py-2 text-sm font-medium transition border-b-2 -mb-px
                       {activeTab === 'exams'
                         ? 'border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400'
                         : 'border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'}">
          Exams{examsLoaded ? ` · ${exams.length}` : ''}
        </button>
      </div>

      {#if activeTab === 'members'}
      <!-- Add member -->
      <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">Add member</div>
          <span class="text-[11px] text-gray-400">{candidates.length} available</span>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-2 mb-3">
          <div class="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850 focus-within:ring-1 focus-within:ring-blue-500 transition">
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4 text-gray-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input type="text" bind:value={memberQuery}
                   placeholder="Filter by name or email"
                   class="flex-1 text-sm bg-transparent outline-none text-gray-900 dark:text-white placeholder:text-gray-400" />
            {#if memberQuery}
              <button onclick={() => memberQuery = ''}
                      aria-label="Clear filter"
                      class="p-0.5 rounded hover:bg-black/5 dark:hover:bg-white/5">
                <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            {/if}
          </div>
          <input type="text" bind:value={memberStudyId} placeholder="Study ID (optional)"
                 class="px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                        bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                        focus:ring-1 focus:ring-blue-500 transition w-full sm:w-44" />
        </div>

        <!-- Candidate list — full width, scrollable, NOT inside any clipping wrapper -->
        <div class="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/30 max-h-[28rem] overflow-y-auto">
          {#if loading}
            <p class="px-3 py-8 text-xs text-center text-gray-400">Loading users…</p>
          {:else if candidates.length === 0}
            <p class="px-3 py-8 text-xs text-center text-gray-400">
              {memberQuery.trim() ? 'No matching users.' : 'No users available to enroll.'}
            </p>
          {:else}
            {#each candidates as candId (candId)}
              {@const cached = userNameCache[candId]}
              {@const label = cached?.displayName || cached?.email || 'Loading…'}
              {@const initials = (cached?.displayName || cached?.email || '??').slice(0, 2).toUpperCase()}
              <div class="flex items-center gap-3 px-3 py-2 border-b last:border-b-0 border-gray-100 dark:border-gray-800
                          hover:bg-white dark:hover:bg-gray-800 transition">
                <div class="shrink-0 size-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                            flex items-center justify-center text-white text-[11px] font-bold uppercase">
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
                <button
                  onclick={() => addMember(cached?.email || cached?.displayName || candId, label)}
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

        {#if memberQuery.trim() && candidates.length === 0}
          <div class="flex justify-end mt-2">
            <button onclick={() => addMember(memberQuery)} disabled={enrolling}
                    class="px-3 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition font-medium disabled:opacity-50 whitespace-nowrap">
              {enrolling ? 'Adding…' : `Add "${memberQuery.trim()}"`}
            </button>
          </div>
        {/if}
      </div>

      <!-- Enrolled members -->
      <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
        <div class="flex items-center justify-between mb-4">
          <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">
            Enrolled · {members.length}
          </div>
        </div>
        {#if loading}
          <p class="text-xs text-gray-400 py-8 text-center">Loading members…</p>
        {:else if members.length === 0}
          <p class="text-xs text-gray-400 py-8 text-center">No members yet — add some from the list above.</p>
        {:else}
          <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
            {#each members as m (m.user_id)}
              <div class="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-gray-50 dark:bg-gray-800 group">
                <div class="shrink-0 size-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600
                            flex items-center justify-center text-white text-[11px] font-bold uppercase">
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
                <button onclick={() => removeMember(m)}
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

      {:else if activeTab === 'exams'}

      <!-- Create exam -->
      {#if canEditCourse}
        <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 p-5">
          <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-3">New exam</div>
          <input type="text" bind:value={newExamTitle}
                 placeholder="Exam title (e.g. Chapter 3 quiz)"
                 class="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg
                        bg-white dark:bg-gray-850 text-gray-900 dark:text-white outline-none
                        focus:ring-1 focus:ring-blue-500 transition" />
          <div class="grid grid-cols-1 sm:grid-cols-[1fr_auto_auto] gap-2 mt-2">
            <label class="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700
                          bg-white dark:bg-gray-850 focus-within:ring-1 focus-within:ring-blue-500 transition">
              <span class="text-[11px] text-gray-400 shrink-0">Deadline</span>
              <input type="datetime-local" bind:value={newExamDeadline}
                     class="flex-1 text-sm bg-transparent outline-none text-gray-900 dark:text-white" />
            </label>
            <label class="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700
                          bg-white dark:bg-gray-850 focus-within:ring-1 focus-within:ring-blue-500 transition w-full sm:w-44">
              <span class="text-[11px] text-gray-400 shrink-0">Time limit</span>
              <input type="text" bind:value={newExamTimeLimit}
                     placeholder="60 or blank"
                     class="flex-1 text-sm bg-transparent outline-none text-gray-900 dark:text-white" />
              <span class="text-[10px] text-gray-400">min</span>
            </label>
            <button onclick={handleCreateExam} disabled={creatingExam}
                    class="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition
                           font-medium disabled:opacity-50 whitespace-nowrap">
              {creatingExam ? 'Creating…' : 'Create draft'}
            </button>
          </div>
          <p class="text-[11px] text-gray-400 mt-2">
            Deadline is interpreted in your local time and stored UTC. Leave time limit blank for an untimed exam.
          </p>
        </div>
      {/if}

      <!-- Exam list -->
      <div>
        {#if !examsLoaded}
          <div class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850 px-4 py-10 text-center text-gray-400 text-sm">
            Loading exams…
          </div>
        {:else if exams.length === 0}
          <div class="rounded-2xl border border-dashed border-gray-200 dark:border-gray-700 px-4 py-10 text-center text-gray-400 text-sm">
            No exams yet — create one above.
          </div>
        {:else}
          <div class="space-y-2">
            {#each exams as ex (ex.id)}
              {@const eff = effectiveState(ex)}
              <button onclick={() => openExam(ex.id)}
                      class="w-full text-left rounded-2xl border border-gray-100 dark:border-gray-800
                             bg-white dark:bg-gray-850 p-4 transition
                             hover:border-gray-200 dark:hover:border-gray-700 hover:shadow-sm">
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                      <h3 class="text-sm font-semibold text-gray-900 dark:text-white truncate">{ex.title}</h3>
                      <span class="px-2 py-0.5 rounded-full text-[10px] font-medium {examStateBadge(eff)}">
                        {eff}
                      </span>
                    </div>
                    {#if ex.description}
                      <p class="text-xs text-gray-500 dark:text-gray-400 mt-1 line-clamp-2">{ex.description}</p>
                    {/if}
                    <div class="flex items-center gap-3 mt-2 text-[11px] text-gray-500 dark:text-gray-400 flex-wrap">
                      <span>Deadline: {formatLocalDeadline(ex.deadline_at)}</span>
                      <span>·</span>
                      <span>{ex.time_limit_minutes ? `${ex.time_limit_minutes} min` : 'Untimed'}</span>
                      <span>·</span>
                      <span>{ex.question_count} question{ex.question_count === 1 ? '' : 's'}</span>
                    </div>
                  </div>
                  <div onclick={(e) => { e.stopPropagation(); handleDeleteExam(ex); }}
                       role="button" tabindex="0"
                       onkeydown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); handleDeleteExam(ex); } }}
                       class="shrink-0 p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50
                              dark:hover:bg-red-900/20 transition cursor-pointer"
                       title="Delete exam">
                    <svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </div>
                </div>
              </button>
            {/each}
          </div>
        {/if}
      </div>

      {/if}
    </div>
  </div>
</div>
