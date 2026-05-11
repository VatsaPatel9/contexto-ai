/**
 * Shared admin-area state.
 *
 * Both /admin (overview tabs) and /admin/courses/[course_id] (focused
 * course management) read user lists and the display_name/email cache
 * from here, so we only fetch once per session.
 */

import { writable, get } from 'svelte/store';

import { getUserProfile, listUsers } from '$lib/apis/admin';

export type UserNameEntry = { displayName: string | null; email: string | null };

export const usersByRole = writable<Record<string, string[]>>({});
export const userNameCache = writable<Record<string, UserNameEntry>>({});
export const adminUsersLoaded = writable<boolean>(false);

export async function loadAdminUsers(force = false): Promise<void> {
  if (!force && get(adminUsersLoaded)) return;

  const res = await listUsers();
  const byRole = res.users_by_role ?? {};
  usersByRole.set(byRole);

  const allIds = new Set<string>();
  for (const list of Object.values(byRole)) {
    for (const id of list) allIds.add(id);
  }

  // Fetch profiles with a small concurrency cap. Promise.all on every
  // user fans out N parallel GETs which torch the backend's DB pool
  // (one connection per /profile call) and starves /api/me, /auth/signin
  // — eventually every user-facing request 524s until the storm clears.
  // 4-at-a-time keeps the cache warm without DoSing ourselves.
  const queue = [...allIds].filter((id) => !get(userNameCache)[id]);
  const CONCURRENCY = 4;
  await Promise.all(
    Array.from({ length: CONCURRENCY }, async () => {
      while (queue.length) {
        const id = queue.shift();
        if (!id) return;
        try {
          const profile = await getUserProfile(id);
          userNameCache.update((c) => ({
            ...c,
            [id]: { displayName: profile.display_name, email: profile.email },
          }));
        } catch {
          // Ignore — row will fall back to "Loading…"
        }
      }
    }),
  );

  adminUsersLoaded.set(true);
}

export function allKnownUserIds(): string[] {
  const byRole = get(usersByRole);
  const ids = new Set<string>();
  for (const list of Object.values(byRole)) {
    for (const id of list) ids.add(id);
  }
  return [...ids];
}
