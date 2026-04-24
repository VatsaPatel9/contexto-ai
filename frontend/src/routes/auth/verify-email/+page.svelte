<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { toast } from 'svelte-sonner';
  import {
    initSuperTokens,
    verifyEmailFromToken,
    sendEmailVerification,
  } from '$lib/auth/supertokens';

  type Status = 'verifying' | 'success' | 'invalid' | 'error';
  let status = $state<Status>('verifying');
  let resending = $state(false);

  onMount(async () => {
    initSuperTokens();

    const hasToken = new URLSearchParams(location.search).has('token');
    if (!hasToken) {
      // No token in URL — user landed here after signup to see
      // "please check your email" instructions.
      status = 'error';
      return;
    }

    const result = await verifyEmailFromToken();
    if (result === 'OK') {
      status = 'success';
      // Hard navigation — the backend has just set fresh session
      // cookies as part of the auto-login override. Reloading the
      // app picks them up; client-side goto() wouldn't.
      setTimeout(() => {
        window.location.href = '/';
      }, 1200);
    } else if (result === 'INVALID_TOKEN') {
      status = 'invalid';
    } else {
      status = 'error';
    }
  });

  async function handleResend() {
    resending = true;
    try {
      const res = await sendEmailVerification();
      if (res.kind === 'ok') {
        toast.success('Verification email sent. Check your inbox.');
      } else if (res.kind === 'already_verified') {
        toast.success('Your email is already verified.');
        window.location.href = '/';
      } else if (res.kind === 'rate_limited') {
        toast.error(res.message);
      } else {
        toast.error('Could not send verification email. Try signing in again.');
      }
    } finally {
      resending = false;
    }
  }
</script>

<div class="min-h-[100dvh] flex items-center justify-center p-6 bg-white dark:bg-gray-900">
  <div class="w-full max-w-md text-center">
    {#if status === 'verifying'}
      <div class="size-8 mx-auto rounded-full border-2 border-gray-400 border-t-transparent animate-spin"></div>
      <p class="mt-4 text-sm text-gray-600 dark:text-gray-400">Verifying your email…</p>
    {:else if status === 'success'}
      <div class="text-green-600 dark:text-green-400 text-lg font-medium">✓ Email verified</div>
      <p class="mt-2 text-sm text-gray-600 dark:text-gray-400">Redirecting you to the app…</p>
    {:else if status === 'invalid'}
      <div class="text-red-600 dark:text-red-400 text-lg font-medium">Link expired or invalid</div>
      <p class="mt-2 text-sm text-gray-600 dark:text-gray-400">
        Verification links expire after a day. Send yourself a fresh one below.
      </p>
      <button
        onclick={handleResend}
        disabled={resending}
        class="mt-4 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm
               disabled:opacity-60 disabled:cursor-not-allowed transition"
      >
        {resending ? 'Sending…' : 'Send me a new link'}
      </button>
      <p class="mt-3 text-xs text-gray-500">
        If that doesn't work, <a href="/login" class="text-blue-600 hover:underline">sign in</a> again and request a new link from your profile.
      </p>
    {:else}
      <div class="text-lg font-medium text-gray-900 dark:text-gray-100">Check your inbox</div>
      <p class="mt-2 text-sm text-gray-600 dark:text-gray-400">
        We sent a verification link to the email you signed up with. Click it to activate your account.
      </p>
      <button
        onclick={handleResend}
        disabled={resending}
        class="mt-4 px-4 py-2 rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700
               text-gray-700 dark:text-gray-200 text-sm
               disabled:opacity-60 disabled:cursor-not-allowed transition"
      >
        {resending ? 'Sending…' : 'Resend verification email'}
      </button>
    {/if}
  </div>
</div>
