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

  await Promise.all(
    [...allIds].map(async (id) => {
      if (get(userNameCache)[id]) return;
      try {
        const profile = await getUserProfile(id);
        userNameCache.update((c) => ({
          ...c,
          [id]: { displayName: profile.display_name, email: profile.email },
        }));
      } catch {
        // Ignore — row will fall back to "Loading…"
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
