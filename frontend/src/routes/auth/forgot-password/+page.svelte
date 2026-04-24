<script lang="ts">
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { initSuperTokens, sendPasswordResetEmail } from '$lib/auth/supertokens';

  type Status = 'idle' | 'sent';

  let email = $state('');
  let status = $state<Status>('idle');
  let submitting = $state(false);
  let resendCooldown = $state(0);

  onMount(() => {
    initSuperTokens();
  });

  function startCooldown(seconds: number) {
    resendCooldown = seconds;
    const tick = () => {
      resendCooldown -= 1;
      if (resendCooldown > 0) setTimeout(tick, 1000);
    };
    setTimeout(tick, 1000);
  }

  async function handleSubmit(e?: Event) {
    e?.preventDefault();
    if (submitting || resendCooldown > 0) return;
    if (!email.trim()) return;

    submitting = true;
    try {
      const res = await sendPasswordResetEmail(email.trim().toLowerCase());
      if (res.kind === 'ok') {
        // Always land here regardless of whether the email is
        // registered — SuperTokens returns OK for unknown emails too,
        // so we never leak enumeration signal.
        status = 'sent';
        startCooldown(30);
      } else if (res.kind === 'rate_limited') {
        toast.error(res.message);
      } else if (res.kind === 'field_error') {
        toast.error(res.message);
      } else {
        toast.error("Couldn't send reset email. Please try again.");
      }
    } finally {
      submitting = false;
    }
  }
</script>

<div class="min-h-[100dvh] flex items-center justify-center p-6 bg-gray-50 dark:bg-gray-900">
  <div class="w-full max-w-md bg-white dark:bg-gray-800 rounded-2xl shadow-lg p-8">
    <div class="flex justify-center mb-3">
      <img src="/mascot-login.png" alt="Contexto" width="72" height="72" />
    </div>

    {#if status === 'idle'}
      <h1 class="text-xl font-semibold text-center text-gray-900 dark:text-gray-100">
        Reset your password
      </h1>
      <p class="mt-2 text-center text-sm text-gray-500 dark:text-gray-400">
        Enter the email for your account and we'll send you a link to set a new password.
      </p>

      <form onsubmit={handleSubmit} class="mt-6 space-y-4">
        <div>
          <label for="email" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Email
          </label>
          <input
            id="email"
            type="email"
            bind:value={email}
            placeholder="you@example.com"
            required
            class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg
                   bg-white dark:bg-gray-700 text-gray-900 dark:text-white
                   focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
          />
        </div>

        <button
          type="submit"
          disabled={submitting || !email.trim()}
          class="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium
                 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? 'Sending…' : 'Send reset link'}
        </button>
      </form>

      <p class="mt-6 text-center text-sm text-gray-500 dark:text-gray-400">
        Remembered it?
        <a href="/login" class="text-blue-600 dark:text-blue-400 hover:underline font-medium">
          Sign in
        </a>
      </p>
    {:else}
      <h1 class="text-xl font-semibold text-center text-gray-900 dark:text-gray-100">
        Check your inbox
      </h1>
      <p class="mt-2 text-center text-sm text-gray-600 dark:text-gray-400">
        If an account exists for <span class="font-medium text-gray-900 dark:text-gray-100">{email}</span>,
        we've sent a link to reset your password.
      </p>
      <p class="mt-2 text-center text-xs text-gray-500 dark:text-gray-500">
        The link expires in 2 hours. Can't find it? Check spam or promotions.
      </p>

      <button
        onclick={handleSubmit}
        disabled={submitting || resendCooldown > 0}
        class="mt-5 w-full px-4 py-2 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600
               text-gray-700 dark:text-gray-200 text-sm font-medium
               disabled:opacity-60 disabled:cursor-not-allowed transition"
      >
        {#if submitting}
          Sending…
        {:else if resendCooldown > 0}
          Resend in {resendCooldown}s
        {:else}
          Resend email
        {/if}
      </button>

      <p class="mt-4 text-center text-xs text-gray-500">
        Wrong email?
        <button
          type="button"
          class="text-blue-600 hover:underline"
          onclick={() => { status = 'idle'; email = ''; }}
        >
          Use a different one
        </button>
      </p>
    {/if}
  </div>
</div>
