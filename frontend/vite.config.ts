import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// In dev, pointing the SDK at a different origin than the frontend
// makes session cookies third-party — Safari and Chrome Incognito
// drop them, so /api/me returns 401 and the UI thinks the user is
// unauthenticated. Forwarding /api and /auth through Vite at the
// same origin makes cookies first-party in every browser.
const API_TARGET = 'http://localhost:8000';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/auth': { target: API_TARGET, changeOrigin: true },
    },
  },
});
