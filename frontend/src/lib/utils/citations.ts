/**
 * Parse an LLM response that terminates with a citations fence:
 *
 *     ```citations
 *     [{"doc_title":"...","section":"...","page_num":4}]
 *     ```
 *
 * Works incrementally during streaming:
 *   - Before the fence opens → everything is display text.
 *   - After the fence opens but before it closes → hide the fence region
 *     from display (so the user never sees raw JSON) and mark as pending.
 *   - After the fence closes → parse the JSON, strip the fence from
 *     display, and return structured citations.
 *
 * If JSON parse fails, citations is returned as undefined and the display
 * keeps the fence stripped (we don't want to show malformed JSON either).
 */
export type ParsedCitation = {
  doc_title: string;
  doc_id?: string;
  page_num?: number;
  section?: string;
  score?: number;
};

export type CitationsSplit = {
  display: string;
  citations?: ParsedCitation[];
  pending: boolean;
};

const FENCE_OPEN = '```citations';
const FENCE_CLOSE = '```';

export function parseCitationsFence(raw: string): CitationsSplit {
  const openIdx = raw.indexOf(FENCE_OPEN);
  if (openIdx < 0) return { display: raw, pending: false };

  const afterOpen = raw.slice(openIdx + FENCE_OPEN.length);
  const closeIdx = afterOpen.indexOf(FENCE_CLOSE);

  if (closeIdx < 0) {
    // Fence is open but not yet closed — still streaming.
    return { display: raw.slice(0, openIdx).trimEnd(), pending: true };
  }

  const jsonText = afterOpen.slice(0, closeIdx).trim();
  let citations: ParsedCitation[] | undefined;
  try {
    const parsed = JSON.parse(jsonText);
    if (Array.isArray(parsed)) citations = parsed as ParsedCitation[];
  } catch {
    citations = undefined;
  }

  const display =
    raw.slice(0, openIdx).trimEnd() +
    afterOpen.slice(closeIdx + FENCE_CLOSE.length);

  return { display, citations, pending: false };
}
