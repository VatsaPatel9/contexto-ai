/**
 * Admin API client for the Contexto admin dashboard.
 * All endpoints require super_admin or admin role.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL;

// ── Types ──────────────────────────────────────────────────────────────

export type UsersByRole = Record<string, string[]>;

export type UserProfile = {
  user_id: string;
  display_name: string | null;
  email: string | null;
  roles: string[];
  uploads: { count: number; limit: number | null };
  tokens: { in: number; out: number; total: number; limit: number | null };
  flags: {
    level: string;
    offense_count_mild: number;
    offense_count_severe: number;
    last_offense_at: string | null;
    restricted_until: string | null;
    notes: string | null;
  };
};

export type Violation = {
  user_id: string;
  flag_level: string;
  offense_count_mild: number;
  offense_count_severe: number;
  last_offense_at: string | null;
  restricted_until: string | null;
  notes: string | null;
};

export type Course = {
  course_id: string;
  name: string;
  description: string | null;
  created_by: string | null;
  member_count: number;
};

export type CourseMember = {
  user_id: string;
  display_name: string | null;
  email: string | null;
  study_id: string | null;
  enrolled_at: string;
};

// ── Helpers ────────────────────────────────────────────────────────────

async function adminFetch(path: string, opts: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Admin API error (${res.status}): ${text}`);
  }
  return res;
}

// ── Users ──────────────────────────────────────────────────────────────

export async function listUsers(role?: string): Promise<{ users_by_role?: UsersByRole; users?: string[] }> {
  const params = role ? `?role=${role}` : '';
  const res = await adminFetch(`/api/admin/users${params}`);
  return res.json();
}

export async function getUserRoles(userId: string): Promise<{ user_id: string; roles: string[] }> {
  const res = await adminFetch(`/api/admin/users/${userId}/roles`);
  return res.json();
}

export async function getUserProfile(userId: string): Promise<UserProfile> {
  const res = await adminFetch(`/api/admin/users/${userId}/profile`);
  return res.json();
}

// ── Roles ──────────────────────────────────────────────────────────────

export async function assignRole(userId: string, role: string) {
  const res = await adminFetch(`/api/admin/users/${userId}/role`, {
    method: 'POST',
    body: JSON.stringify({ role }),
  });
  return res.json();
}

export async function removeRole(userId: string, role: string) {
  const res = await adminFetch(`/api/admin/users/${userId}/role`, {
    method: 'DELETE',
    body: JSON.stringify({ role }),
  });
  return res.json();
}

// ── Upload Limits ──────────────────────────────────────────────────────

export async function setUploadLimit(userId: string, limit: number) {
  const res = await adminFetch(`/api/admin/users/${userId}/upload-limit`, {
    method: 'POST',
    body: JSON.stringify({ limit }),
  });
  return res.json();
}

export async function revokeUploadLimit(userId: string) {
  const res = await adminFetch(`/api/admin/users/${userId}/upload-limit`, {
    method: 'DELETE',
  });
  return res.json();
}

// ── Token Limits ───────────────────────────────────────────────────────

export async function setTokenLimit(userId: string, limit: number | null) {
  const res = await adminFetch(`/api/admin/users/${userId}/token-limit`, {
    method: 'PUT',
    body: JSON.stringify({ limit }),
  });
  return res.json();
}

// ── Violations ─────────────────────────────────────────────────────────

export async function listViolations(): Promise<{ violations: Violation[]; total: number }> {
  const res = await adminFetch('/api/admin/violations');
  return res.json();
}

export async function getUserViolations(userId: string): Promise<Violation> {
  const res = await adminFetch(`/api/admin/users/${userId}/violations`);
  return res.json();
}

// ── Ban / Unban ────────────────────────────────────────────────────────

export async function banUser(userId: string, reason: string = 'Banned by admin') {
  const res = await adminFetch(`/api/admin/users/${userId}/ban`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
  return res.json();
}

export async function unbanUser(userId: string) {
  const res = await adminFetch(`/api/admin/users/${userId}/unban`, {
    method: 'POST',
  });
  return res.json();
}

// ── Courses ────────────────────────────────────────────────────────────

export async function listCourses(): Promise<Course[]> {
  const res = await adminFetch('/api/admin/courses');
  return res.json();
}

export async function createCourse(body: {
  course_id: string;
  name: string;
  description?: string;
}): Promise<Course> {
  const res = await adminFetch('/api/admin/courses', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function deleteCourse(courseId: string) {
  const res = await adminFetch(`/api/admin/courses/${encodeURIComponent(courseId)}`, {
    method: 'DELETE',
  });
  return res.json();
}

export async function listCourseMembers(courseId: string): Promise<CourseMember[]> {
  const res = await adminFetch(`/api/admin/courses/${encodeURIComponent(courseId)}/members`);
  return res.json();
}

export async function enrollMember(
  courseId: string,
  identifier: string,
  studyId?: string,
): Promise<CourseMember> {
  const res = await adminFetch(`/api/admin/courses/${encodeURIComponent(courseId)}/members`, {
    method: 'POST',
    body: JSON.stringify({ identifier, study_id: studyId ?? null }),
  });
  return res.json();
}

export async function unenrollMember(courseId: string, userId: string) {
  const res = await adminFetch(
    `/api/admin/courses/${encodeURIComponent(courseId)}/members/${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );
  return res.json();
}
