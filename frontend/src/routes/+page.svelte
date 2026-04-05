<script lang="ts">
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';

  // If already logged in, go straight to chat
  $effect(() => {
    if ($authStore.initialized && $authStore.authenticated) {
      goto('/chat');
    }
  });
</script>

<!-- Public homepage navbar -->
<nav class="fixed top-0 left-0 right-0 z-50 bg-white/80 dark:bg-gray-900/80 backdrop-blur-xl border-b border-gray-100 dark:border-gray-800">
  <div class="max-w-6xl mx-auto flex items-center justify-between px-6 py-3">
    <div class="flex items-center gap-2.5">
      <img src="/mascot-nav.png" alt="Contexto" class="size-8 rounded-full" />
      <span class="text-lg font-bold text-gray-900 dark:text-white">Contexto</span>
    </div>
    <button
      onclick={() => goto('/login')}
      class="px-5 py-2 text-sm font-medium rounded-full
             bg-gray-900 dark:bg-white text-white dark:text-gray-900
             hover:opacity-90 transition"
    >
      Sign In
    </button>
  </div>
</nav>

<!-- Hero -->
<div class="min-h-screen bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100">
  <div class="max-w-4xl mx-auto px-6 pt-32 pb-20 text-center">
    <div class="flex justify-center mb-6">
      <img src="/mascot-hero.png" alt="Contexto" class="size-24 rounded-2xl shadow-lg" />
    </div>
    <h1 class="text-4xl sm:text-5xl font-bold tracking-tight text-gray-900 dark:text-white mb-4">
      Meet Contexto
    </h1>
    <p class="text-lg sm:text-xl text-gray-500 dark:text-gray-400 max-w-2xl mx-auto mb-8 leading-relaxed">
      Your AI study buddy for STEM courses. Contexto helps you understand concepts,
      work through problems, and learn at your own pace — without just giving you the answers.
    </p>
    <button
      onclick={() => goto('/login')}
      class="px-8 py-3 text-base font-medium rounded-full
             bg-blue-600 text-white hover:bg-blue-700 transition shadow-lg shadow-blue-600/25"
    >
      Get Started
    </button>
    <p class="text-xs text-gray-400 dark:text-gray-500 mt-3">Free for all PSU students</p>
  </div>

  <!-- How it works -->
  <div class="max-w-5xl mx-auto px-6 pb-20">
    <h2 class="text-2xl font-bold text-center text-gray-900 dark:text-white mb-10">How It Works</h2>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
      <div class="bg-gray-50 dark:bg-gray-800 rounded-2xl p-6 text-center">
        <div class="text-3xl mb-3">💬</div>
        <h3 class="font-semibold text-gray-900 dark:text-white mb-2">Ask a Question</h3>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Type any question about your course material — homework, concepts, or exam prep.
        </p>
      </div>
      <div class="bg-gray-50 dark:bg-gray-800 rounded-2xl p-6 text-center">
        <div class="text-3xl mb-3">🧠</div>
        <h3 class="font-semibold text-gray-900 dark:text-white mb-2">Learn by Doing</h3>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Contexto guides you with hints and questions instead of giving direct answers,
          helping you truly understand the material.
        </p>
      </div>
      <div class="bg-gray-50 dark:bg-gray-800 rounded-2xl p-6 text-center">
        <div class="text-3xl mb-3">📚</div>
        <h3 class="font-semibold text-gray-900 dark:text-white mb-2">Your Course Content</h3>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Answers are grounded in your actual course materials uploaded by your instructor —
          not random internet sources.
        </p>
      </div>
    </div>
  </div>

  <!-- Features -->
  <div class="max-w-5xl mx-auto px-6 pb-20">
    <h2 class="text-2xl font-bold text-center text-gray-900 dark:text-white mb-10">Built for Students</h2>
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
      <div class="flex items-start gap-4 bg-gray-50 dark:bg-gray-800 rounded-2xl p-5">
        <div class="text-2xl shrink-0">🔒</div>
        <div>
          <h3 class="font-semibold text-gray-900 dark:text-white text-sm mb-1">Private & Safe</h3>
          <p class="text-xs text-gray-500 dark:text-gray-400">
            Your conversations are private. Personal information is automatically detected and protected.
          </p>
        </div>
      </div>
      <div class="flex items-start gap-4 bg-gray-50 dark:bg-gray-800 rounded-2xl p-5">
        <div class="text-2xl shrink-0">📝</div>
        <div>
          <h3 class="font-semibold text-gray-900 dark:text-white text-sm mb-1">Homework Help</h3>
          <p class="text-xs text-gray-500 dark:text-gray-400">
            Show your work first, and Contexto will guide you through the rest. It encourages you
            to try before it helps.
          </p>
        </div>
      </div>
      <div class="flex items-start gap-4 bg-gray-50 dark:bg-gray-800 rounded-2xl p-5">
        <div class="text-2xl shrink-0">🌙</div>
        <div>
          <h3 class="font-semibold text-gray-900 dark:text-white text-sm mb-1">Study Anytime</h3>
          <p class="text-xs text-gray-500 dark:text-gray-400">
            Available 24/7 with dark mode for late-night study sessions. Works on your phone, tablet, or laptop.
          </p>
        </div>
      </div>
      <div class="flex items-start gap-4 bg-gray-50 dark:bg-gray-800 rounded-2xl p-5">
        <div class="text-2xl shrink-0">📖</div>
        <div>
          <h3 class="font-semibold text-gray-900 dark:text-white text-sm mb-1">Source Citations</h3>
          <p class="text-xs text-gray-500 dark:text-gray-400">
            Every answer shows which course materials it came from, so you can verify and study further.
          </p>
        </div>
      </div>
    </div>
  </div>

  <!-- CTA -->
  <div class="max-w-4xl mx-auto px-6 pb-20 text-center">
    <div class="bg-gradient-to-br from-blue-50 to-purple-50 dark:from-blue-900/20 dark:to-purple-900/20
                rounded-3xl p-10 border border-blue-100 dark:border-blue-800/30">
      <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-3">Ready to study smarter?</h2>
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Sign in with your PSU email and start chatting with Contexto in seconds.
      </p>
      <button
        onclick={() => goto('/login')}
        class="px-8 py-3 text-base font-medium rounded-full
               bg-blue-600 text-white hover:bg-blue-700 transition shadow-lg shadow-blue-600/25"
      >
        Sign In with PSU Email
      </button>
    </div>
  </div>

  <!-- Footer -->
  <footer class="border-t border-gray-100 dark:border-gray-800 py-6">
    <div class="max-w-6xl mx-auto px-6 flex items-center justify-between text-xs text-gray-400 dark:text-gray-500">
      <div class="flex items-center gap-2">
        <img src="/mascot-nav.png" alt="Contexto" class="size-4 rounded-full" />
        <span>Contexto AI Tutor</span>
      </div>
      <a href="https://vatsapatel.com/" target="_blank" rel="noopener noreferrer"
         class="hover:text-gray-600 dark:hover:text-gray-300 transition">&lt;/&gt; Built by Vatsa Patel</a>
    </div>
  </footer>
</div>
