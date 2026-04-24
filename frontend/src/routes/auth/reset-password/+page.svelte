<script lang="ts">
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { initSuperTokens, submitNewPassword } from '$lib/auth/supertokens';

  type Status = 'form' | 'no_token' | 'invalid' | 'success';

  let status = $state<Status>('form');
  let password = $state('');
  let confirmPassword = $state('');
  let showPassword = $state(false);
  let showConfirmPassword = $state(false);
  let submitting = $state(false);
  let clientError = $state('');

  onMount(() => {
    initSuperTokens();
    const params = new URLSearchParams(location.search);
    // The web-js SDK reads the token itself when we call submitNewPassword,
    // but we validate up-front so a landing without a token shows the right
    // UX instead of an opaque "invalid token" error after the user types a
    // new password.
    if (!params.has('token')) {
      status = 'no_token';
    }
  });

  async function handleSubmit(e?: Event) {
    e?.preventDefault();
    clientError = '';

    if (!password) {
      clientError = 'Please enter a new password.';
      return;
    }
    if (password !== confirmPassword) {
      clientError = 'Passwords do not match.';
      return;
    }

    submitting = true;
    try {
      const res = await submitNewPassword(password);
      if (res.kind === 'ok') {
        status = 'success';
        toast.success('Password updated. You can sign in now.');
        setTimeout(() => { window.location.href = '/login'; }, 1500);
      } else if (res.kind === 'invalid_token') {
        status = 'invalid';
      } else if (res.kind === 'field_error') {
        clientError = res.message;
      } else {
        toast.error("Couldn't update your password. Please try again.");
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

    {#if status === 'form'}
      <h1 class="text-xl font-semibold text-center text-gray-900 dark:text-gray-100">
        Set a new password
      </h1>
      <p class="mt-2 text-center text-sm text-gray-500 dark:text-gray-400">
        Choose a password you haven't used on this account before.
      </p>

      {#if clientError}
        <div class="mt-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm">
          {clientError}
        </div>
      {/if}

      <form onsubmit={handleSubmit} class="mt-6 space-y-4">
        <div>
          <label for="password" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            New password
          </label>
          <div class="relative">
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              bind:value={password}
              placeholder="Enter a new password"
              required
              class="w-full px-3 py-2 pr-10 border border-gray-300 dark:border-gray-600 rounded-lg
                     bg-white dark:bg-gray-700 text-gray-900 dark:text-white
                     focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
            />
            <button
              type="button"
              tabindex="-1"
              onclick={() => (showPassword = !showPassword)}
              class="absolute inset-y-0 right-0 pr-3 flex items-center
                     text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              title={showPassword ? 'Hide password' : 'Show password'}
            >
              {#if showPassword}
                <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                  <line x1="1" y1="1" x2="23" y2="23" />
                </svg>
              {:else}
                <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              {/if}
            </button>
          </div>
        </div>

        <div>
          <label for="confirm-password" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Confirm new password
          </label>
          <div class="relative">
            <input
              id="confirm-password"
              type={showConfirmPassword ? 'text' : 'password'}
              bind:value={confirmPassword}
              placeholder="Re-enter the new password"
              required
              class="w-full px-3 py-2 pr-10 border border-gray-300 dark:border-gray-600 rounded-lg
                     bg-white dark:bg-gray-700 text-gray-900 dark:text-white
                     focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
            />
            <button
              type="button"
              tabindex="-1"
              onclick={() => (showConfirmPassword = !showConfirmPassword)}
              class="absolute inset-y-0 right-0 pr-3 flex items-center
                     text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              aria-label={showConfirmPassword ? 'Hide password' : 'Show password'}
              title={showConfirmPassword ? 'Hide password' : 'Show password'}
            >
              {#if showConfirmPassword}
                <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                  <line x1="1" y1="1" x2="23" y2="23" />
                </svg>
              {:else}
                <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              {/if}
            </button>
          </div>
        </div>

        <button
          type="submit"
          disabled={submitting}
          class="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium
                 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? 'Updating…' : 'Update password'}
        </button>
      </form>
    {:else if status === 'success'}
      <div class="text-center">
        <div class="text-green-600 dark:text-green-400 text-xl font-semibold">Password updated</div>
        <p class="mt-2 text-sm text-gray-600 dark:text-gray-400">Redirecting you to sign in…</p>
      </div>
    {:else}
      <!-- invalid or no_token -->
      <div class="text-center">
        <div class="text-red-600 dark:text-red-400 text-xl font-semibold">
          {status === 'no_token' ? 'Missing reset link' : 'Link expired or invalid'}
        </div>
        <p class="mt-3 text-sm text-gray-600 dark:text-gray-400">
          Reset links expire after 2 hours. Request a new one below.
        </p>
        <a
          href="/auth/forgot-password"
          class="mt-5 inline-block px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700
                 text-white text-sm font-medium transition"
        >
          Send a new link
        </a>
        <p class="mt-3 text-xs text-gray-500">
          Or <a href="/login" class="text-blue-600 hover:underline">sign in</a> if you remember your password.
        </p>
      </div>
    {/if}
  </div>
</div>
