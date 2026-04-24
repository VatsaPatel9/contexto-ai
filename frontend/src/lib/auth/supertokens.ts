/**
 * SuperTokens Web JS initialization for the AI Tutor chat-ui.
 *
 * Uses supertokens-web-js (framework-agnostic) since the frontend is SvelteKit.
 * Session tokens are managed via httpOnly cookies — the SDK automatically
 * attaches them to every fetch() call via its interceptor.
 */

import SuperTokens from 'supertokens-web-js';
import Session from 'supertokens-web-js/recipe/session';
import EmailPassword from 'supertokens-web-js/recipe/emailpassword';

const API_DOMAIN = import.meta.env.VITE_API_BASE_URL;

let initialized = false;

export function initSuperTokens() {
  if (initialized) return;

  SuperTokens.init({
    appInfo: {
      appName: 'Contexto',
      apiDomain: API_DOMAIN,
      apiBasePath: '/auth',
    },
    recipeList: [
      Session.init(),
      EmailPassword.init(),
    ],
  });

  initialized = true;
}

// ── Auth helpers ──────────────────────────────────────────────────────

export async function signUp(email: string, password: string, displayName?: string) {
  const formFields = [
    { id: 'email', value: email },
    { id: 'password', value: password },
  ];
  if (displayName) {
    formFields.push({ id: 'display_name', value: displayName });
  }

  const response = await EmailPassword.signUp({ formFields });

  if (response.status === 'FIELD_ERROR') {
    const errors = response.formFields.map((f) => `${f.id}: ${f.error}`).join(', ');
    throw new Error(errors);
  }

  if (response.status !== 'OK') {
    throw new Error(`Sign up failed: ${response.status}`);
  }

  return response.user;
}

export async function signIn(email: string, password: string) {
  const response = await EmailPassword.signIn({
    formFields: [
      { id: 'email', value: email },
      { id: 'password', value: password },
    ],
  });

  if (response.status === 'FIELD_ERROR') {
    const errors = response.formFields.map((f) => `${f.id}: ${f.error}`).join(', ');
    throw new Error(errors);
  }

  if (response.status === 'WRONG_CREDENTIALS_ERROR') {
    throw new Error('Invalid email or password');
  }

  if (response.status !== 'OK') {
    throw new Error(`Sign in failed: ${response.status}`);
  }

  return response.user;
}

export async function signOut() {
  await Session.signOut();
}

export async function isSessionActive(): Promise<boolean> {
  return await Session.doesSessionExist();
}

export async function getUserId(): Promise<string | null> {
  if (!(await Session.doesSessionExist())) return null;
  return (await Session.getUserId()) ?? null;
}

export async function getAccessTokenPayload(): Promise<Record<string, unknown> | null> {
  if (!(await Session.doesSessionExist())) return null;
  return await Session.getAccessTokenPayloadSecurely();
}

export async function getUserRoles(): Promise<string[]> {
  const payload = await getAccessTokenPayload();
  if (!payload) return [];
  const roleClaim = payload['st-role'] as { v?: string[] } | undefined;
  return roleClaim?.v ?? [];
}
