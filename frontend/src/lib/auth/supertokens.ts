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
import EmailVerification from 'supertokens-web-js/recipe/emailverification';

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
      EmailVerification.init({
        // Single-tenant app: force the web-js SDK to always use the
        // 'public' tenant regardless of what's in the URL query
        // string. Without this the SDK reads ?tenantId=... verbatim,
        // so a stale/corrupted email link routes to a non-existent
        // tenant path (e.g. /auth/<something>/user/email/verify) and
        // the Core returns "Tenant not found".
        override: {
          functions: (orig) => ({
            ...orig,
            getTenantIdFromURL: () => 'public',
          }),
        },
      }),
    ],
  });

  initialized = true;
}

// ── Email verification ────────────────────────────────────────────────

/** Whether the current session's email has been verified. */
export async function isEmailVerified(): Promise<boolean> {
  if (!(await Session.doesSessionExist())) return false;
  const res = await EmailVerification.isEmailVerified();
  return res.isVerified;
}

/** Ask the backend to (re)send a verification email to the signed-in user. */
export type SendVerificationResult =
  | { kind: 'ok' }
  | { kind: 'already_verified' }
  | { kind: 'rate_limited'; message: string }
  | { kind: 'error' };

export async function sendEmailVerification(): Promise<SendVerificationResult> {
  if (!(await Session.doesSessionExist())) return { kind: 'error' };
  // The SDK types this response as OK | EMAIL_ALREADY_VERIFIED_ERROR, but
  // the SuperTokens backend can also return a GeneralErrorResponse with a
  // status of 'GENERAL_ERROR' (e.g. our rate-limit override). Cast so we
  // can check that branch without TypeScript narrowing it away.
  const res = (await EmailVerification.sendVerificationEmail()) as unknown as {
    status: string;
    message?: string;
  };
  if (res.status === 'OK') return { kind: 'ok' };
  if (res.status === 'EMAIL_ALREADY_VERIFIED_ERROR') return { kind: 'already_verified' };
  if (res.status === 'GENERAL_ERROR') {
    return { kind: 'rate_limited', message: res.message ?? 'Too many requests.' };
  }
  return { kind: 'error' };
}

/**
 * Called from the /auth/verify-email landing page after the user clicks
 * the link in their inbox. Reads the token from the URL and submits it.
 */
export async function verifyEmailFromToken(): Promise<
  'OK' | 'INVALID_TOKEN' | 'ERROR'
> {
  try {
    const res = await EmailVerification.verifyEmail();
    if (res.status === 'OK') return 'OK';
    if (res.status === 'EMAIL_VERIFICATION_INVALID_TOKEN_ERROR') return 'INVALID_TOKEN';
    return 'ERROR';
  } catch {
    return 'ERROR';
  }
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
