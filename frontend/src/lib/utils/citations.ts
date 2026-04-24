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

const CITATIONS_FENCE_OPEN = '```citations';
const SUGGESTIONS_FENCE_OPEN = '```suggestions';
const FENCE_CLOSE = '```';

function splitFence<T>(
  raw: string,
  openTag: string,
  coerce: (parsed: unknown) => T | undefined
): { display: string; value?: T; pending: boolean } {
  const openIdx = raw.indexOf(openTag);
  if (openIdx < 0) return { display: raw, pending: false };

  const afterOpen = raw.slice(openIdx + openTag.length);
  const closeIdx = afterOpen.indexOf(FENCE_CLOSE);

  if (closeIdx < 0) {
    return { display: raw.slice(0, openIdx).trimEnd(), pending: true };
  }

  const jsonText = afterOpen.slice(0, closeIdx).trim();
  let value: T | undefined;
  try {
    value = coerce(JSON.parse(jsonText));
  } catch {
    value = undefined;
  }

  const display =
    raw.slice(0, openIdx).trimEnd() +
    afterOpen.slice(closeIdx + FENCE_CLOSE.length);

  return { display, value, pending: false };
}

export function parseCitationsFence(raw: string): CitationsSplit {
  const out = splitFence<ParsedCitation[]>(raw, CITATIONS_FENCE_OPEN, (p) =>
    Array.isArray(p) ? (p as ParsedCitation[]) : undefined
  );
  return { display: out.display, citations: out.value, pending: out.pending };
}

export type SuggestionsSplit = {
  display: string;
  suggestions?: string[];
  pending: boolean;
};

export function parseSuggestionsFence(raw: string): SuggestionsSplit {
  const out = splitFence<string[]>(raw, SUGGESTIONS_FENCE_OPEN, (p) => {
    if (!Array.isArray(p)) return undefined;
    return p.filter((x): x is string => typeof x === 'string');
  });
  return { display: out.display, suggestions: out.value, pending: out.pending };
}
