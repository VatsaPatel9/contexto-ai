<script lang="ts">
  import { goto } from '$app/navigation';
</script>

<svelte:head>
  <title>Terms of Service · Contexto</title>
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
      <a href="/privacy" class="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition">
        Privacy Policy →
      </a>
    </div>

    <h1 class="text-3xl font-bold mb-1">Terms of Service</h1>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-8">Last updated: April 26, 2026</p>

    <div class="prose prose-sm dark:prose-invert max-w-none space-y-6 leading-relaxed text-[15px]">

      <section>
        <h2 class="text-lg font-semibold mt-0">1. Acceptance of Terms</h2>
        <p>
          These Terms of Service (the &ldquo;Terms&rdquo;) govern your access to and use of
          Contexto (the &ldquo;Service&rdquo;), an AI-assisted educational tutoring platform
          owned and operated by Vatsa Patel as an individual (&ldquo;Owner,&rdquo; &ldquo;we,&rdquo; &ldquo;us&rdquo;).
          By accessing or using the Service, you agree to be bound by these Terms. If
          you do not agree, do not use the Service.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">2. The Service</h2>
        <p>
          Contexto provides a chat-based interface that uses third-party large language
          models (&ldquo;LLMs&rdquo;) and retrieval-augmented generation over instructor-uploaded
          course materials to assist learners with their studies. The Service is
          provided to schools, instructors, and their students for educational purposes
          only.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">3. Eligibility &amp; Use by Minors</h2>
        <p>
          The Service is intended for use within educational institutions. If you are
          under 18, you may use the Service only under the supervision of, and with
          consent from, a parent, guardian, or your educational institution. If you are
          under 13, you may use the Service only through an educational institution
          that has obtained appropriate parental consent and complies with applicable
          children's privacy laws (including, where applicable, the U.S. Children's
          Online Privacy Protection Act). We rely on educational institutions to
          obtain and maintain such consents.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">4. Accounts</h2>
        <p>
          You are responsible for maintaining the confidentiality of your account
          credentials and for all activity that occurs under your account. You agree to
          notify us promptly of any unauthorized use. We may suspend or terminate
          accounts that violate these Terms.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">5. Your Content</h2>
        <p>
          &ldquo;Your Content&rdquo; means anything you submit to the Service, including documents
          you upload, questions you ask, and any other input. You retain all rights you
          previously held in Your Content. By submitting Your Content, you grant the
          Owner a worldwide, non-exclusive, royalty-free license to host, store,
          transmit, process, and display Your Content solely to operate, maintain, and
          improve the Service.
        </p>
        <p>
          <strong>You are solely responsible for Your Content.</strong> You represent and warrant
          that (a) you own or have all necessary rights to submit Your Content; (b) Your
          Content does not infringe, misappropriate, or violate any third-party right,
          including intellectual property, privacy, or publicity rights; and (c) Your
          Content does not contain unlawful, harmful, or otherwise objectionable
          material. The Owner does not pre-screen Your Content and assumes no
          responsibility for any user-submitted material.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">6. AI-Generated Output</h2>
        <p>
          The Service generates responses using third-party LLMs. AI-generated output
          is produced algorithmically and may contain errors, inaccuracies, biases,
          omissions, or content that is misleading, inappropriate, or unsuitable for
          your purpose.
        </p>
        <p>
          <strong>AI output is provided for educational reference only.</strong> It does not
          constitute medical, legal, financial, psychological, or any other form of
          professional advice. You should not rely on AI output without independent
          verification by a qualified human source. The Owner makes no representation
          or warranty regarding the accuracy, completeness, fitness for purpose, or
          appropriateness of any AI output, and is not responsible for decisions made
          or actions taken in reliance on it.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">7. Acceptable Use</h2>
        <p>You agree not to, and not to permit any third party to:</p>
        <ul class="list-disc pl-6 space-y-1">
          <li>use the Service for any unlawful, harmful, deceptive, or fraudulent purpose;</li>
          <li>upload or generate content that is defamatory, obscene, pornographic, hateful, harassing, or otherwise objectionable;</li>
          <li>upload personally identifiable information about any third party without that person's consent and the appropriate legal basis;</li>
          <li>attempt to circumvent rate limits, access controls, or other security measures;</li>
          <li>reverse engineer, decompile, or attempt to extract the source code of the Service or the underlying models;</li>
          <li>use the Service to develop competing products or to train other AI models;</li>
          <li>use automated means to access the Service in a manner that places undue load on our infrastructure;</li>
          <li>impersonate any person or misrepresent your affiliation;</li>
          <li>interfere with the operation of the Service or attempt to access accounts or content that are not yours.</li>
        </ul>
      </section>

      <section>
        <h2 class="text-lg font-semibold">8. Third-Party Services</h2>
        <p>
          The Service relies on third-party providers, including model and embedding
          providers, authentication providers, and cloud storage providers, to deliver
          its functionality. Your use of the Service is also subject to those
          providers' own terms and privacy practices. We do not control and are not
          responsible for those third parties.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">9. Intellectual Property</h2>
        <p>
          All right, title, and interest in and to the Service (excluding Your
          Content) — including software, design, and trademarks — are and shall remain
          the exclusive property of the Owner and any licensors. These Terms grant you
          no rights to the Service except as expressly stated.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">10. Service &ldquo;AS IS&rdquo;; Disclaimer of Warranties</h2>
        <p class="uppercase text-[13px] tracking-wide">
          The Service is provided &ldquo;as is&rdquo; and &ldquo;as available,&rdquo; with all faults and
          without warranty of any kind. To the maximum extent permitted by applicable
          law, the Owner disclaims all warranties, express or implied, including but
          not limited to the implied warranties of merchantability, fitness for a
          particular purpose, non-infringement, and any warranty arising from course
          of dealing or usage of trade. We do not warrant that the Service will be
          uninterrupted, secure, error-free, accurate, reliable, or that any
          AI-generated output will meet your requirements.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">11. Limitation of Liability</h2>
        <p class="uppercase text-[13px] tracking-wide">
          To the maximum extent permitted by applicable law, in no event shall Vatsa
          Patel, individually, or any of his licensors, contractors, or service
          providers, be liable to you or any third party for any indirect, incidental,
          special, consequential, exemplary, or punitive damages, or any damages for
          loss of profits, revenues, data, goodwill, or other intangible losses,
          arising out of or in connection with your access to or use of, or inability
          to access or use, the Service; any content obtained from the Service
          (including AI-generated output); any content uploaded by you or any other
          user; or any unauthorized access, use, or alteration of your transmissions
          or content, regardless of the legal theory and whether or not the Owner
          has been advised of the possibility of such damages.
        </p>
        <p class="uppercase text-[13px] tracking-wide">
          The Owner's total aggregate liability arising out of or relating to these
          terms or the Service, whether in contract, tort, or otherwise, shall not
          exceed one hundred U.S. dollars ($100).
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">12. Indemnification</h2>
        <p>
          You agree to defend, indemnify, and hold harmless Vatsa Patel and his
          contractors, agents, and service providers, from and against any and all
          claims, demands, actions, liabilities, damages, losses, costs, and expenses
          (including reasonable attorneys' fees) arising out of or relating to: (a)
          your use of, or access to, the Service; (b) Your Content; (c) your
          violation of these Terms; (d) your violation of any law or any third-party
          right, including any intellectual-property or privacy right; or (e) any
          claim that Your Content or your use of the Service caused damage to a third
          party.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">13. Termination</h2>
        <p>
          We may suspend or terminate your access to the Service at any time, with or
          without notice, for any reason, including violation of these Terms. Upon
          termination, your right to use the Service will cease immediately. Sections
          intended to survive termination — including Sections 5, 6, 9, 10, 11, 12,
          14, and 15 — will continue in effect.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">14. Governing Law &amp; Disputes</h2>
        <p>
          These Terms are governed by the laws of the Commonwealth of Pennsylvania,
          USA, without regard to its conflict-of-laws principles. Any dispute arising
          out of or relating to these Terms or the Service shall be brought
          exclusively in the state or federal courts located in Pennsylvania, and you
          consent to personal jurisdiction in those courts.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">15. Changes to These Terms</h2>
        <p>
          We may modify these Terms at any time. Material changes will be indicated by
          updating the &ldquo;Last updated&rdquo; date above and, where appropriate, by notice
          within the Service. Your continued use after changes take effect constitutes
          acceptance of the modified Terms.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold">16. Contact</h2>
        <p>
          Questions about these Terms can be sent to
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
