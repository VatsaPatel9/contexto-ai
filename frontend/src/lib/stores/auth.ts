/**
 * Svelte auth store backed by SuperTokens session.
 *
 * Provides reactive state for the current user's authentication status,
 * user ID, display name, email, and roles.
 */

import { writable, get } from 'svelte/store';
import {
  isSessionActive,
  getUserId,
  getUserRoles,
  signIn as stSignIn,
  signUp as stSignUp,
  signOut as stSignOut,
} from '$lib/auth/supertokens';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost';

export type AuthState = {
  initialized: boolean;
  authenticated: boolean;
  userId: string | null;
  displayName: string | null;
  email: string | null;
  roles: string[];
};

const initial: AuthState = {
  initialized: false,
  authenticated: false,
  userId: null,
  displayName: null,
  email: null,
  roles: [],
};

export const authStore = writable<AuthState>(initial);

/**
 * Fetch display_name and email from the backend /api/me endpoint.
 */
async function fetchProfile(): Promise<{ display_name: string | null; email: string | null }> {
  try {
    const res = await fetch(`${API_BASE}/api/me`, { credentials: 'include' });
    if (!res.ok) return { display_name: null, email: null };
    const data = await res.json();
    return { display_name: data.display_name ?? null, email: data.email ?? null };
  } catch {
    return { display_name: null, email: null };
  }
}

/**
 * Check the current session and update the store.
 * Call this on app mount and after login/signup.
 */
export async function refreshAuthState() {
  const active = await isSessionActive();
  if (active) {
    const userId = await getUserId();
    const roles = await getUserRoles();
    const { display_name, email } = await fetchProfile();
    authStore.set({
      initialized: true,
      authenticated: true,
      userId,
      displayName: display_name,
      email,
      roles,
    });
  } else {
    authStore.set({ initialized: true, authenticated: false, userId: null, displayName: null, email: null, roles: [] });
  }
}

export async function login(email: string, password: string) {
  await stSignIn(email, password);
  await refreshAuthState();
}

export async function register(email: string, password: string, displayName?: string) {
  await stSignUp(email, password, displayName);
  await refreshAuthState();
}

export async function logout() {
  await stSignOut();
  authStore.set({ initialized: true, authenticated: false, userId: null, displayName: null, email: null, roles: [] });

  // Clear cached conversations so the next user doesn't see stale data
  const { conversations, conversationsLoaded } = await import('$lib/stores');
  conversations.set([]);
  conversationsLoaded.set(false);
}

/**
 * Update the user's display name via the backend.
 */
export async function updateDisplayName(name: string) {
  const res = await fetch(`${API_BASE}/api/me`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: name }),
  });
  if (!res.ok) throw new Error('Failed to update display name');
  const data = await res.json();
  authStore.update((s) => ({ ...s, displayName: data.display_name }));
}

export function isAdmin(): boolean {
  const state = get(authStore);
  return state.roles.includes('super_admin') || state.roles.includes('admin');
}

export function isSuperAdmin(): boolean {
  const state = get(authStore);
  return state.roles.includes('super_admin');
}

/**
 * Get a human-readable name for display. Priority: displayName > email prefix > userId prefix.
 */
export function getDisplayLabel(state: AuthState): string {
  if (state.displayName) return state.displayName;
  if (state.email) return state.email.split('@')[0];
  if (state.userId) return state.userId.slice(0, 8) + '...';
  return 'User';
}
