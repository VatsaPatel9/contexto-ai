<script>
  import { page } from '$app/stores';
</script>

<div style="padding: 2rem; font-family: monospace;">
  <h1>Error {$page.status}</h1>
  <pre>{$page.error?.message}</pre>
</div>
