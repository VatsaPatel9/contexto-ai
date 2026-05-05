<script lang="ts">
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import {
    initSuperTokens,
    sendEmailVerification,
    isEmailVerified,
  } from '$lib/auth/supertokens';

  type Status =
    | 'sent' // landed here straight from signup — start the cooldown
    | 'idle'; // landed here some other way — Resend available immediately

  let status = $state<Status>('sent');
  let resending = $state(false);
  let resendCooldown = $state(0);

  onMount(async () => {
    initSuperTokens();
    // If they're already verified (e.g. came back to this page after
    // clicking the link in another tab), bounce them into the app.
    const verified = await isEmailVerified().catch(() => false);
    if (verified) {
      window.location.href = '/';
      return;
    }
    const params = new URLSearchParams(location.search);
    if (params.get('sent') === '1') {
      status = 'sent';
      startCooldown(30);
    } else {
      status = 'idle';
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
        status = 'sent';
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

    <h1 class="text-xl font-semibold text-gray-900 dark:text-gray-100">Check your inbox</h1>
    <p class="mt-2 text-sm text-gray-600 dark:text-gray-400">
      We sent a verification link to your email. Click it to activate your account and sign in automatically.
    </p>
    <p class="mt-2 text-xs text-gray-500 dark:text-gray-500">
      The link expires in 2 hours. Can't find it? Check spam or promotions.
    </p>
    <button
      onclick={handleResend}
      disabled={resending || resendCooldown > 0}
      class="mt-5 px-4 py-2 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600
             text-gray-700 dark:text-gray-200 text-sm font-medium
             disabled:opacity-60 disabled:cursor-not-allowed transition"
    >
      {#if resending}
        Sending…
      {:else if resendCooldown > 0}
        Resend in {resendCooldown}s
      {:else}
        Resend email
      {/if}
    </button>
    <p class="mt-4 text-xs text-gray-500">
      Wrong email? <a href="/login" class="text-blue-600 hover:underline">Sign in with a different account</a>.
    </p>
  </div>
</div>
