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

const API_BASE = import.meta.env.VITE_API_BASE_URL;

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
 *
 * Returns ``null`` (not an empty object) when the call fails so the
 * caller can distinguish "profile is empty" from "the cookie wasn't
 * sent / server didn't recognize us." Cross-origin cookie blocking
 * (Safari, Chrome Incognito) shows up here as a non-OK response — we
 * surface that to ``refreshAuthState`` which then refuses to mark the
 * user authenticated, instead of leaving the UI in a half-authed
 * state that then claims the email isn't verified.
 */
async function fetchProfile(): Promise<{ display_name: string | null; email: string | null } | null> {
  try {
    const res = await fetch(`${API_BASE}/api/me`, { credentials: 'include' });
    if (!res.ok) return null;
    const data = await res.json();
    return { display_name: data.display_name ?? null, email: data.email ?? null };
  } catch {
    return null;
  }
}

/**
 * Check the current session and update the store.
 * Call this on app mount and after login/signup.
 */
export async function refreshAuthState() {
  const active = await isSessionActive();
  if (active) {
    const profile = await fetchProfile();
    if (!profile) {
      // Client-side session cookie exists but the server can't see it
      // (third-party cookie blocked, expired, network down). Treat as
      // unauthenticated so route gates work and the UI doesn't loop on
      // "verify your email" — re-running through /login on a same-
      // origin proxy will let the cookie become first-party and recover.
      authStore.set({
        initialized: true,
        authenticated: false,
        userId: null,
        displayName: null,
        email: null,
        roles: [],
      });
      return;
    }
    const userId = await getUserId();
    const roles = await getUserRoles();
    authStore.set({
      initialized: true,
      authenticated: true,
      userId,
      displayName: profile.display_name,
      email: profile.email,
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

export async function register(
  email: string,
  password: string,
  displayName: string | undefined,
  termsVersion: string,
) {
  await stSignUp(email, password, displayName, termsVersion);
  await refreshAuthState();
}

export async function logout() {
  await stSignOut();
  authStore.set({ initialized: true, authenticated: false, userId: null, displayName: null, email: null, roles: [] });

  // Clear cached conversations so the next user doesn't see stale data
  const { conversations, conversationsLoaded } = await import('$lib/stores');
  conversations.set([]);
  conversationsLoaded.set(false);

  // Navigate explicitly so the user never lingers on a protected URL
  // (/chat/<old-id>, /admin/...) waiting for the layout's $effect to
  // catch up. The login page is the only safe landing for an
  // unauthenticated user. Lazy-import goto so this module stays usable
  // outside a client/component context.
  try {
    const { goto } = await import('$app/navigation');
    await goto('/login');
  } catch {
    // SSR / non-client context — caller can navigate themselves.
  }
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
