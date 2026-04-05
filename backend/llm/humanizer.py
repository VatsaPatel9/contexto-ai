"""Post-processing pass that removes common AI writing patterns from tutor responses."""

from __future__ import annotations

from backend.llm.client import LLMClient

HUMANIZER_SYSTEM_PROMPT = (
    "You are a rewriting assistant. Your ONLY job is to rewrite the provided "
    "text so it sounds like a natural, experienced human tutor wrote it.\n\n"
    "Remove these common AI writing patterns:\n"
    "- Sycophantic openers ('Great question!', 'That's a fantastic observation!')\n"
    "- Em dashes used as a stylistic crutch\n"
    "- Inflated or grandiose language ('delve', 'crucial', 'vital', 'landscape', "
    "'tapestry', 'paramount', 'pivotal')\n"
    "- Filler hedging phrases ('It's important to note that', 'It's worth "
    "mentioning that')\n"
    "- Unnecessary 'Rule of Three' lists when one or two items suffice\n"
    "- Overly enthusiastic exclamation marks\n"
    "- Formulaic transitions ('Furthermore', 'Moreover', 'Additionally')\n"
    "- Robotic sign-offs ('I hope this helps!', 'Let me know if you have any "
    "other questions!')\n\n"
    "KEEP intact:\n"
    "- All educational/technical content and accuracy\n"
    "- Citation markers in [Source: ...] format\n"
    "- Socratic questions and pedagogical scaffolding\n"
    "- Growth-mindset language\n"
    "- Markdown formatting (headers, bold, code blocks)\n\n"
    "Output ONLY the rewritten text. No preamble, no explanation."
)


async def humanize_response(llm: LLMClient, text: str) -> str:
    """Rewrite *text* through the humanizer LLM pass.

    Returns the humanized version, or the original text if the LLM
    call fails or returns empty.
    """
    if not text or not text.strip():
        return text

    messages = [
        {"role": "system", "content": HUMANIZER_SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    result = await llm.chat(messages)
    # Fall back to original if the humanizer produced nothing useful
    if not result or result.startswith("["):
        return text
    return result
