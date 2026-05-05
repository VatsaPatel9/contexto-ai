<script lang="ts">
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import {
    initSuperTokens,
    verifyEmailFromToken,
    sendEmailVerification,
  } from '$lib/auth/supertokens';

  type Status =
    | 'verifying' // landed with a ?token=… link, waiting on API
    | 'success' // token verified, redirecting
    | 'invalid'; // token bad/expired, or no token in URL

  let status = $state<Status>('verifying');
  let resending = $state(false);
  let resendCooldown = $state(0);

  onMount(async () => {
    initSuperTokens();
    const params = new URLSearchParams(location.search);

    // No token → user reached this page some other way. Send them to
    // the dedicated "check your inbox" prompt instead of leaving them
    // on a verifying spinner that never resolves.
    if (!params.has('token')) {
      window.location.replace('/auth/check-email');
      return;
    }

    const result = await verifyEmailFromToken();
    if (result === 'OK') {
      status = 'success';
      // Hard navigation — the backend has set fresh session cookies
      // as part of auto-login. A client-side goto() wouldn't pick
      // them up.
      setTimeout(() => {
        window.location.href = '/';
      }, 1200);
    } else {
      status = 'invalid';
    }
  });

  function startCooldown(seconds: number) {
    resendCooldown = seconds;
    const tick = () => {
      resendCooldown -= 1;
      if (resendCooldown > 0) setTimeout(tick, 1000);
    };
    setTimeout(tick, 1000);
  }

  async function handleResend() {
    if (resending || resendCooldown > 0) return;
    resending = true;
    try {
      const res = await sendEmailVerification();
      if (res.kind === 'ok') {
        toast.success('Verification email sent. Check your inbox.');
        startCooldown(30);
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

<div class="min-h-[100dvh] flex items-center justify-center p-6 bg-gray-50 dark:bg-gray-900">
  <div class="w-full max-w-md bg-white dark:bg-gray-800 rounded-2xl shadow-lg p-8 text-center">
    <div class="flex justify-center mb-3">
      <img src="/mascot-login.png" alt="Contexto" width="72" height="72" />
    </div>

    {#if status === 'verifying'}
      <div class="size-8 mx-auto rounded-full border-2 border-gray-400 border-t-transparent animate-spin my-4"></div>
      <p class="text-sm text-gray-600 dark:text-gray-400">Verifying your email…</p>
    {:else if status === 'success'}
      <div class="text-green-600 dark:text-green-400 text-xl font-semibold">Email verified</div>
      <p class="mt-2 text-sm text-gray-600 dark:text-gray-400">Taking you to the app…</p>
    {:else}
      <div class="text-red-600 dark:text-red-400 text-xl font-semibold">Link expired or invalid</div>
      <p class="mt-3 text-sm text-gray-600 dark:text-gray-400">
        Verification links expire after 2 hours. We can send you a fresh one.
      </p>
      <button
        onclick={handleResend}
        disabled={resending || resendCooldown > 0}
        class="mt-5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium
               disabled:opacity-60 disabled:cursor-not-allowed transition"
      >
        {#if resending}
          Sending…
        {:else if resendCooldown > 0}
          Resend in {resendCooldown}s
        {:else}
          Send a new link
        {/if}
      </button>
      <p class="mt-3 text-xs text-gray-500">
        Or <a href="/login" class="text-blue-600 hover:underline">sign in</a> with a different account.
      </p>
    {/if}
  </div>
</div>
