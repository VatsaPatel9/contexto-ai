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
import STGeneralError from 'supertokens-web-js/utils/error';

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
      EmailPassword.init({
        // Same single-tenant pin as EmailVerification (see comment on
        // that recipe). A stale or hand-mangled reset link that carries
        // a non-'public' tenantId would otherwise route to a missing
        // tenant path on the core and fail with an opaque error.
        override: {
          functions: (orig) => ({
            ...orig,
            getTenantIdFromURL: () => 'public',
          }),
        },
      }),
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
  // Our backend rate-limit override returns a GeneralErrorResponse. The
  // web-js querier intercepts status=GENERAL_ERROR responses and throws
  // STGeneralError with the server's message — the response never
  // reaches us as an OK-shaped object. Catch it here to surface the
  // rate-limit message to the user.
  try {
    const res = await EmailVerification.sendVerificationEmail();
    if (res.status === 'OK') return { kind: 'ok' };
    if (res.status === 'EMAIL_ALREADY_VERIFIED_ERROR') return { kind: 'already_verified' };
    return { kind: 'error' };
  } catch (err) {
    if (err instanceof STGeneralError) {
      return { kind: 'rate_limited', message: err.message || 'Too many requests.' };
    }
    return { kind: 'error' };
  }
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

// ── Password reset ────────────────────────────────────────────────────

export type SendResetResult =
  | { kind: 'ok' }
  | { kind: 'rate_limited'; message: string }
  | { kind: 'field_error'; message: string }
  | { kind: 'error' };

/**
 * Fire a password-reset email to the given address.
 *
 * The backend always responds OK for unknown emails (enumeration
 * defense) so the UI cannot distinguish "sent" from "no such
 * account" — always show the same "if an account exists…" message.
 */
export async function sendPasswordResetEmail(email: string): Promise<SendResetResult> {
  // The backend's rate-limit override returns GeneralErrorResponse. The
  // web-js querier intercepts that and throws STGeneralError — it never
  // arrives as a response object. Catch it so the user sees the
  // rate-limit message instead of a generic "couldn't send".
  try {
    const res = await EmailPassword.sendPasswordResetEmail({
      formFields: [{ id: 'email', value: email }],
    });
    if (res.status === 'OK') return { kind: 'ok' };
    if (res.status === 'FIELD_ERROR') {
      return {
        kind: 'field_error',
        message: res.formFields.map((f) => f.error).join(', ') || 'Invalid email',
      };
    }
    return { kind: 'error' };
  } catch (err) {
    if (err instanceof STGeneralError) {
      return { kind: 'rate_limited', message: err.message || 'Too many requests.' };
    }
    return { kind: 'error' };
  }
}

export type SubmitNewPasswordResult =
  | { kind: 'ok' }
  | { kind: 'invalid_token' }
  | { kind: 'field_error'; message: string }
  | { kind: 'error' };

/**
 * Submit a new password using the token in the current URL's `?token=…`.
 * The web-js SDK reads the token from the URL automatically.
 */
export async function submitNewPassword(newPassword: string): Promise<SubmitNewPasswordResult> {
  try {
    const res = await EmailPassword.submitNewPassword({
      formFields: [{ id: 'password', value: newPassword }],
    });
    if (res.status === 'OK') return { kind: 'ok' };
    if (res.status === 'RESET_PASSWORD_INVALID_TOKEN_ERROR') return { kind: 'invalid_token' };
    if (res.status === 'FIELD_ERROR') {
      return {
        kind: 'field_error',
        message:
          res.formFields.map((f) => f.error).join(', ') || 'Password does not meet requirements',
      };
    }
    return { kind: 'error' };
  } catch (err) {
    if (err instanceof STGeneralError) {
      return { kind: 'field_error', message: err.message };
    }
    return { kind: 'error' };
  }
}

// ── Auth helpers ──────────────────────────────────────────────────────

export async function signUp(
  email: string,
  password: string,
  displayName: string | undefined,
  termsVersion: string,
) {
  const formFields = [
    { id: 'email', value: email },
    { id: 'password', value: password },
    // The server rejects signup unless these match the current version.
    // The values flow into supertokens_config.sign_up_post which double-
    // checks them before any user is created.
    { id: 'terms_accepted', value: 'true' },
    { id: 'terms_version', value: termsVersion },
  ];
  if (displayName) {
    formFields.push({ id: 'display_name', value: displayName });
  }

  const response = (await EmailPassword.signUp({ formFields })) as {
    status: string;
    user?: unknown;
    formFields?: Array<{ id: string; error: string }>;
    reason?: string;
  };

  if (response.status === 'FIELD_ERROR') {
    const errors = (response.formFields ?? [])
      .map((f) => `${f.id}: ${f.error}`)
      .join(', ');
    throw new Error(errors || 'Invalid form fields');
  }

  if (response.status === 'SIGN_UP_NOT_ALLOWED') {
    // SuperTokens surfaces our backend "you must accept terms" /
    // "domain not allowed" rejections through this status. The reason
    // string is the human-readable message we returned from the override.
    throw new Error(response.reason || 'Sign up not allowed');
  }

  if (response.status !== 'OK') {
    throw new Error(`Sign up failed: ${response.status}`);
  }

  return response.user as ReturnType<typeof EmailPassword.signUp> extends Promise<infer R>
    ? R extends { user: infer U }
      ? U
      : never
    : never;
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
