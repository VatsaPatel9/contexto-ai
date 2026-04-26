<script lang="ts">
  import { goto } from '$app/navigation';
</script>

<svelte:head>
  <title>Privacy Policy · Contexto</title>
</svelte:head>

<div class="min-h-screen bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100">
  <div class="max-w-3xl mx-auto px-6 py-10">

    <!-- Top bar -->
    <div class="flex items-center justify-between mb-8">
      <button onclick={() => goto('/')}
              class="inline-flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition">
        <svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6" />
        </svg>
        Back
      </button>
      <a href="/terms" class="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition">
        Terms of Service →
      </a>
    </div>

    <h1 class="text-3xl font-bold mb-1">Privacy Policy</h1>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-8">Last updated: April 26, 2026</p>

    <div class="prose prose-sm dark:prose-invert max-w-none space-y-6 leading-relaxed text-[15px]">

      <section>
        <h2 class="text-lg font-semibold mt-0">1. Who We Are</h2>
        <p>
          Contexto (the &ldquo;Service&rdquo;) is owned and operated by Vatsa Patel as an
          individual. This Privacy Policy explains what information we collect, how we
          use it, and the choices you have.
        </p>
        <p>
          The Service is intended for use within educational institutions, primarily
          to support tutoring and learning activities approved by an instructor or
          school. Where the Service is provided through a school, the school is the
          primary controller of student data and we act as a service provider to that
          school.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">2. Information We Collect</h2>
        <p>We collect the following categories of information:</p>
        <ul class="list-disc pl-6 space-y-1">
          <li>
            <strong>Account information.</strong> When you sign up, we collect the email
            address you provide and a hashed password. You may also provide a display
            name. Authentication is handled by SuperTokens (see Section 4).
          </li>
          <li>
            <strong>Course content.</strong> Documents uploaded by instructors, super-administrators,
            or users with upload permission, including their text, structure, and any
            metadata you choose to attach.
          </li>
          <li>
            <strong>Chat content.</strong> The messages you send and the AI responses you
            receive, together with timestamps, classification labels (e.g., &ldquo;homework&rdquo;
            vs. &ldquo;conceptual&rdquo;), citations to source documents, hint level, and like /
            dislike feedback.
          </li>
          <li>
            <strong>Usage data.</strong> Aggregate counters such as token usage, upload counts,
            and rate-limit signals; coarse logs of API requests for security and
            reliability purposes.
          </li>
          <li>
            <strong>Course membership.</strong> When an administrator enrolls a user in a
            course, we record that membership and any pseudonymous study identifier
            attached to the enrollment.
          </li>
          <li>
            <strong>Moderation signals.</strong> Detected events such as PII scrubbing,
            prompt-injection attempts, offensive-language flags, and risk escalations,
            stored to help keep the Service safe.
          </li>
        </ul>
        <p>
          We do <em>not</em> intentionally collect special categories of personal data
          (e.g., health, biometric, or precise location data). Please do not submit
          such data to the Service.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">3. How We Use Information</h2>
        <p>We use the information we collect to:</p>
        <ul class="list-disc pl-6 space-y-1">
          <li>operate, maintain, and improve the Service;</li>
          <li>generate retrieval-augmented responses scoped to the materials your course makes available;</li>
          <li>enforce account, course, and rate-limit boundaries;</li>
          <li>detect and prevent abuse, including prompt injection, harassment, and academic-integrity violations;</li>
          <li>communicate with you about your account, including verification and password reset;</li>
          <li>comply with legal obligations and respond to lawful requests.</li>
        </ul>
        <p>
          We do <em>not</em> sell your personal information. We do not use your chat
          content or uploads to advertise to you.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">4. Service Providers &amp; Third Parties</h2>
        <p>
          The Service is built on top of the following providers, each of which
          processes some of the information described above on our behalf:
        </p>
        <ul class="list-disc pl-6 space-y-1">
          <li>
            <strong>OpenAI</strong> — generates chat responses and document embeddings. Your
            messages and the relevant retrieved context are sent to OpenAI's API to
            produce a response. OpenAI's processing of API inputs is governed by their
            API terms and data-usage policy.
          </li>
          <li>
            <strong>SuperTokens</strong> — handles authentication, session management, and
            user-role data.
          </li>
          <li>
            <strong>Cloudflare R2</strong> — stores uploaded original documents.
          </li>
          <li>
            <strong>Postgres &amp; Redis</strong> (self-hosted) — store conversations, profiles,
            embeddings, rate-limit counters, and short-lived caches.
          </li>
          <li>
            <strong>Email delivery (SMTP)</strong> — used to send account verification and
            password-reset emails.
          </li>
          <li>
            <strong>Hosting providers</strong> — used to run the Service infrastructure.
          </li>
        </ul>
        <p>
          We share information with these providers only to the extent necessary to
          deliver their function. Each provider has its own privacy practices that
          apply to the data it processes.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">5. Data Retention</h2>
        <p>
          We retain your account, chat, and course data for as long as your account is
          active or as needed to provide the Service. Soft-deleted documents are
          retained for up to 30 days before permanent deletion. We may retain certain
          information for longer periods where required by law, to resolve disputes,
          to enforce our agreements, or to maintain the security and integrity of the
          Service.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">6. Children's Privacy</h2>
        <p>
          The Service is intended for use within educational settings. We do not
          knowingly collect personal information from children under 13 except through
          schools that have obtained appropriate parental consent and have agreed,
          where applicable, that the school is the parent's authorized agent under
          the U.S. Children's Online Privacy Protection Act (&ldquo;COPPA&rdquo;).
        </p>
        <p>
          When the Service is used as part of an educational program, student
          information may also be subject to the U.S. Family Educational Rights and
          Privacy Act (&ldquo;FERPA&rdquo;) and analogous state laws. In those contexts, we treat
          student records as the school's records and act as a school official with a
          legitimate educational interest. We do not disclose student data to third
          parties except as described in this Policy or as directed by the school.
        </p>
        <p>
          If you believe a child under 13 has provided us with personal information
          without appropriate consent, please contact us at
          <a href="mailto:askcontexto@gmail.com" class="text-blue-600 dark:text-blue-400 hover:underline">askcontexto@gmail.com</a>
          and we will work with the relevant school to delete the information.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">7. Your Choices &amp; Rights</h2>
        <p>
          Subject to applicable law and the school's role where relevant, you may:
        </p>
        <ul class="list-disc pl-6 space-y-1">
          <li>access or update your account information from the profile page;</li>
          <li>delete a conversation from the sidebar; deletion removes it from the active list and triggers permanent removal of associated messages;</li>
          <li>request deletion of your account by emailing us; we will honor verified requests subject to legal retention obligations and direction from your school where applicable;</li>
          <li>where required by law (e.g., GDPR, CCPA), exercise data-subject rights such as access, correction, deletion, restriction, portability, and objection by contacting us.</li>
        </ul>
      </section>

      <section>
        <h2 class="text-lg font-semibold">8. Security</h2>
        <p>
          We use commercially reasonable technical and organizational measures to
          protect your information, including encryption in transit, hashed passwords,
          httpOnly session cookies, role-based access controls, and rate limiting.
          However, no system is fully secure and we cannot guarantee absolute
          security. You are responsible for keeping your account credentials
          confidential.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">9. International Users</h2>
        <p>
          The Service is operated from the United States and processed by service
          providers located in the United States and other countries. By using the
          Service, you understand that your information may be transferred to and
          processed in countries other than your own, which may have different
          data-protection laws.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">10. Changes to This Policy</h2>
        <p>
          We may update this Privacy Policy from time to time. Material changes will
          be indicated by updating the &ldquo;Last updated&rdquo; date above and, where
          appropriate, by additional notice. Continued use of the Service after a
          change takes effect constitutes acceptance of the updated Policy.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">11. Contact</h2>
        <p>
          Privacy questions, deletion requests, and other inquiries can be sent to
          <a href="mailto:askcontexto@gmail.com" class="text-blue-600 dark:text-blue-400 hover:underline">askcontexto@gmail.com</a>.
        </p>
      </section>

    </div>

    <footer class="mt-12 pt-6 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-400 dark:text-gray-600 flex items-center justify-between flex-wrap gap-2">
      <span>© 2026 Vatsa Patel · Contexto</span>
      <div class="flex gap-3">
        <a href="/terms" class="hover:text-gray-600 dark:hover:text-gray-400 transition">Terms</a>
        <a href="/privacy" class="hover:text-gray-600 dark:hover:text-gray-400 transition">Privacy</a>
      </div>
    </footer>
  </div>
</div>
