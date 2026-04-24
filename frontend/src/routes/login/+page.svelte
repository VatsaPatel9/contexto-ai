<script lang="ts">
  import { goto } from '$app/navigation';
  import { login, register } from '$lib/stores/auth';
  import { isEmailVerified } from '$lib/auth/supertokens';

  let mode: 'login' | 'register' = $state('login');
  let displayName = $state('');
  let email = $state('');
  let password = $state('');
  let confirmPassword = $state('');
  let error = $state('');
  let loading = $state(false);
  let showPassword = $state(false);
  let showConfirmPassword = $state(false);

  async function handleSubmit() {
    error = '';

    if (mode === 'register' && !displayName.trim()) {
      error = 'Display name is required';
      return;
    }

    if (!email || !password) {
      error = 'Email and password are required';
      return;
    }

    if (mode === 'register' && password !== confirmPassword) {
      error = 'Passwords do not match';
      return;
    }

    loading = true;
    try {
      if (mode === 'login') {
        await login(email, password);
      } else {
        // Backend's sign_up_post override fires the verification email
        // automatically as part of this call — the frontend doesn't
        // need to kick it off.
        await register(email, password, displayName.trim());
      }

      // If the email is verified, land in the app. If not, the backend
      // will 403 every request — route to /auth/verify-email instead
      // so the user sees a real "check your inbox" page, not a broken
      // chat UI.
      const verified = await isEmailVerified();
      if (verified) {
        goto('/');
      } else {
        // ?sent=1 tells the verify-email page "email already went out,
        // show the inbox-check state and rate-limit the Resend button".
        goto('/auth/verify-email?sent=1');
      }
    } catch (e: any) {
      error = e.message || 'Authentication failed';
    } finally {
      loading = false;
    }
  }
</script>

<div class="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900 px-4">
  <div class="w-full max-w-md bg-white dark:bg-gray-800 rounded-2xl shadow-lg p-8">
    <div class="flex justify-center mb-3">
      <img src="/mascot-login.png" alt="Contexto" width="80" height="80" />
    </div>
    <h1 class="text-2xl font-bold text-center text-gray-900 dark:text-white mb-0.5">
      Contexto
    </h1>
    <p class="text-center text-xs text-gray-400 dark:text-gray-500 mb-4">AI Tutor</p>
    <p class="text-center text-gray-500 dark:text-gray-400 mb-6">
      {mode === 'login' ? 'Sign in to your account' : 'Create a new account'}
    </p>

    {#if error}
      <div class="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm">
        {error}
      </div>
    {/if}

    <form onsubmit={handleSubmit} class="space-y-4">
      {#if mode === 'register'}
        <div>
          <label for="display-name" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Display Name
          </label>
          <input
            id="display-name"
            type="text"
            bind:value={displayName}
            placeholder="Your name"
            maxlength="100"
            class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg
                   bg-white dark:bg-gray-700 text-gray-900 dark:text-white
                   focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
          />
        </div>
      {/if}

      <div>
        <label for="email" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Email <span class="text-[10px] text-gray-400 font-normal">(@psu.edu only)</span>
        </label>
        <input
          id="email"
          type="email"
          bind:value={email}
          placeholder="you@example.com"
          class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg
                 bg-white dark:bg-gray-700 text-gray-900 dark:text-white
                 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
        />
      </div>

      <div>
        <label for="password" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Password
        </label>
        <div class="relative">
          <input
            id="password"
            type={showPassword ? 'text' : 'password'}
            bind:value={password}
            placeholder="Enter your password"
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
              <!-- eye-off -->
              <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                <line x1="1" y1="1" x2="23" y2="23" />
              </svg>
            {:else}
              <!-- eye -->
              <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            {/if}
          </button>
        </div>
      </div>

      {#if mode === 'register'}
        <div>
          <label for="confirm-password" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Confirm Password
          </label>
          <div class="relative">
            <input
              id="confirm-password"
              type={showConfirmPassword ? 'text' : 'password'}
              bind:value={confirmPassword}
              placeholder="Confirm your password"
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
      {/if}

      <button
        type="submit"
        disabled={loading}
        class="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium
               rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {#if loading}
          Processing...
        {:else}
          {mode === 'login' ? 'Sign In' : 'Sign Up'}
        {/if}
      </button>
    </form>

    <div class="mt-6 text-center text-sm text-gray-500 dark:text-gray-400">
      {#if mode === 'login'}
        Don't have an account?
        <button
          class="text-blue-600 dark:text-blue-400 hover:underline font-medium"
          onclick={() => { mode = 'register'; error = ''; }}
        >
          Sign up
        </button>
      {:else}
        Already have an account?
        <button
          class="text-blue-600 dark:text-blue-400 hover:underline font-medium"
          onclick={() => { mode = 'login'; error = ''; }}
        >
          Sign in
        </button>
      {/if}
    </div>
  </div>
</div>
