"""
Offensive word list organized by category and severity, with regex patterns
for common obfuscations, plus an academic allowlist for STEM contexts.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OffensivePattern:
    """A single offensive term with its regex pattern and metadata."""
    term: str
    pattern: re.Pattern
    category: str
    severity: str  # mild, moderate, severe


@dataclass
class AcademicTerm:
    """A term that looks offensive but is legitimate in academic context."""
    term: str
    pattern: re.Pattern
    context_hint: str  # e.g. "biology", "medicine", "mathematics"


# ---------------------------------------------------------------------------
# Helper: build a regex that tolerates common obfuscation between each letter
# ---------------------------------------------------------------------------

_LEET = {
    "a": r"[a@4àáâãäåæ]",
    "b": r"[b8ß]",
    "c": r"[c\(\[{<©]",
    "d": r"[d]",
    "e": r"[e3€èéêëæ]",
    "f": r"[fƒ]",
    "g": r"[g69]",
    "h": r"[h#]",
    "i": r"[i1!|ìíîï]",
    "j": r"[j]",
    "k": r"[k]",
    "l": r"[l1|!]",
    "m": r"[m]",
    "n": r"[nñ]",
    "o": r"[o0øòóôõö]",
    "p": r"[p]",
    "q": r"[q9]",
    "r": r"[r®]",
    "s": r"[s5$§]",
    "t": r"[t7+†]",
    "u": r"[uùúûüµ]",
    "v": r"[v]",
    "w": r"[wω]",
    "x": r"[x×]",
    "y": r"[yýÿ]",
    "z": r"[z2]",
}

# Characters commonly inserted between letters to evade filters
_SEP = r"[\s.*_\-~`'\",;:!?\/\\]*"


def _build_obfuscation_pattern(word: str) -> str:
    """Build a regex pattern string that matches a word through common obfuscations."""
    parts = []
    for ch in word.lower():
        leet = _LEET.get(ch, re.escape(ch))
        parts.append(leet)
    return _SEP.join(parts)


def _compile(word: str, word_boundary: bool = True) -> re.Pattern:
    """Compile obfuscation-aware pattern with optional word boundaries."""
    raw = _build_obfuscation_pattern(word)
    if word_boundary:
        raw = r"(?<!\w)" + raw + r"(?!\w)"
    return re.compile(raw, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Word lists by category and severity
# ---------------------------------------------------------------------------

_PROFANITY_MILD = [
    "damn", "hell", "crap", "piss", "ass", "bastard", "arse",
    "bollocks", "bugger", "bloody", "sod",
]

_PROFANITY_MODERATE = [
    "shit", "bitch", "dick", "cock", "prick", "douchebag",
    "asshole", "arsehole", "bullshit", "horseshit", "dipshit",
    "jackass", "dumbass", "badass", "fatass", "smartass",
    "goddamn", "motherfucker", "fucker", "fuckface",
    "shithead", "shitface", "dickhead", "bitchass",
    "wtf", "stfu", "gtfo",
]

_PROFANITY_SEVERE = [
    "fuck", "fucking", "fucked",
    "cunt",
]

_SLURS_MODERATE = [
    "retard", "retarded", "spaz", "spastic",
    "tranny", "shemale",
    "midget",
]

_SLURS_SEVERE = [
    "nigger", "nigga", "negro",
    "spic", "spick", "wetback", "beaner",
    "chink", "gook", "zipperhead", "slant",
    "kike", "hymie",
    "raghead", "towelhead", "sandnigger", "camel jockey",
    "fag", "faggot", "dyke",
    "coon", "darkie", "jiggaboo",
    "cracker", "honky",
    "paki",
    "wop", "dago", "guinea",
    "redskin", "injun", "squaw",
]

_THREATS_MODERATE = [
    "i will hurt you", "i will find you", "watch your back",
    "you will regret", "i will get you", "you are dead to me",
]

_THREATS_SEVERE = [
    "kill you", "kill yourself", "kys",
    "i will murder", "shoot you", "stab you",
    "bomb threat", "blow you up", "slit your throat",
    "hope you die", "go die", "drink bleach",
    "hang yourself", "end yourself",
    "i know where you live", "rape you",
    "gonna shoot up", "school shooting",
    "kill them all", "mass shooting",
]

_SEXUAL_MODERATE = [
    "blowjob", "handjob", "rimjob",
    "dildo", "vibrator",
    "boner", "erection",
    "boobs", "tits", "titties",
    "pussy", "vagina",
    "penis", "phallus",
    "cum", "cumshot", "jizz",
    "horny", "slutty",
    "wank", "jerk off", "jack off",
    "porn", "pornography", "hentai",
]

_SEXUAL_SEVERE = [
    "child porn", "cp", "kiddie porn",
    "molest", "pedophile", "pedo",
    "incest",
    "bestiality", "zoophilia",
    "snuff",
    "rape", "gang rape", "date rape",
]

_HATE_SPEECH_MODERATE = [
    "go back to your country",
    "you people are all the same",
    "white power",
    "white supremacy",
    "heil hitler",
    "master race",
    "ethnic cleansing",
    "inferior race",
    "subhuman",
]

_HATE_SPEECH_SEVERE = [
    "gas the jews", "holocaust was fake",
    "death to", "exterminate",
    "genocide", "lynch",
    "race war", "day of the rope",
    "fourteen words", "1488",
    "blood and soil",
]

# ---------------------------------------------------------------------------
# Build the master list of OffensivePattern objects
# ---------------------------------------------------------------------------


def _build_patterns(terms: list[str], category: str, severity: str) -> list[OffensivePattern]:
    results = []
    for term in terms:
        # For multi-word phrases, match them as a sequence (no word-boundary between words)
        if " " in term:
            words = term.split()
            pat_str = r"\b" + r"\s+".join(_build_obfuscation_pattern(w) for w in words) + r"\b"
            pat = re.compile(pat_str, re.IGNORECASE)
        else:
            pat = _compile(term)
        results.append(OffensivePattern(term=term, pattern=pat, category=category, severity=severity))
    return results


def get_all_offensive_patterns() -> list[OffensivePattern]:
    """Return the full list of offensive patterns."""
    patterns: list[OffensivePattern] = []
    patterns.extend(_build_patterns(_PROFANITY_MILD, "profanity", "mild"))
    patterns.extend(_build_patterns(_PROFANITY_MODERATE, "profanity", "moderate"))
    patterns.extend(_build_patterns(_PROFANITY_SEVERE, "profanity", "severe"))
    patterns.extend(_build_patterns(_SLURS_MODERATE, "slurs", "moderate"))
    patterns.extend(_build_patterns(_SLURS_SEVERE, "slurs", "severe"))
    patterns.extend(_build_patterns(_THREATS_MODERATE, "threats", "moderate"))
    patterns.extend(_build_patterns(_THREATS_SEVERE, "threats", "severe"))
    patterns.extend(_build_patterns(_SEXUAL_MODERATE, "sexual", "moderate"))
    patterns.extend(_build_patterns(_SEXUAL_SEVERE, "sexual", "severe"))
    patterns.extend(_build_patterns(_HATE_SPEECH_MODERATE, "hate_speech", "moderate"))
    patterns.extend(_build_patterns(_HATE_SPEECH_SEVERE, "hate_speech", "severe"))
    return patterns


# ---------------------------------------------------------------------------
# Academic allowlist
# ---------------------------------------------------------------------------

_ACADEMIC_TERMS = [
    ("organism", r"\borganism(s)?\b", "biology"),
    ("Dickinsonia", r"\bdickinsonia\b", "paleontology"),
    ("angina", r"\bangina\b", "medicine"),
    ("homo sapiens", r"\bhomo\s+sapiens\b", "biology"),
    ("homo erectus", r"\bhomo\s+erectus\b", "biology"),
    ("homo habilis", r"\bhomo\s+habilis\b", "biology"),
    ("homosexual", r"\bhomosexual(ity)?\b", "biology"),
    ("mastication", r"\bmasticat(e|ion|ing)\b", "biology"),
    ("tit", r"\b(blue\s+)?tit(s|mouse)?\b", "ornithology"),
    ("great tit", r"\bgreat\s+tit\b", "ornithology"),
    ("analysis", r"\banalys[ie]s?\b", "mathematics"),
    ("asymptote", r"\basymptot(e|ic)\b", "mathematics"),
    ("breast cancer", r"\bbreast\s+cancer\b", "medicine"),
    ("reproduction", r"\breproducti(on|ve)\b", "biology"),
    ("mating", r"\bmat(e|ing)\b", "biology"),
    ("sexual reproduction", r"\bsexual\s+reproduction\b", "biology"),
    ("erect", r"\berect(ed|ion|ing)?\b", "engineering"),
    ("penis", r"\bpen(is|ile)\b", "anatomy"),
    ("vagina", r"\bvagin(a|al)\b", "anatomy"),
    ("ejaculation", r"\bejacula(t(e|ion|ing))\b", "biology"),
    ("sperm", r"\bsperm(atozoa|atocyte)?\b", "biology"),
    ("ovum", r"\b(ovum|ova|oocyte)\b", "biology"),
    ("coitus", r"\bcoitus\b", "biology"),
    ("puberty", r"\bpubert(y|al)\b", "biology"),
    ("genitalia", r"\bgenital(ia|s)?\b", "anatomy"),
    ("uranus", r"\buranus\b", "astronomy"),
    ("coccyx", r"\bcoccyx\b", "anatomy"),
    ("pianist", r"\bpianist(s)?\b", "music"),
    ("cleavage", r"\bcleavage\b", "geology"),
    ("titration", r"\btitrat(e|ion|ing)\b", "chemistry"),
    ("titular", r"\btitular\b", "general"),
    ("sextant", r"\bsextant(s)?\b", "navigation"),
    ("sexagesimal", r"\bsexagesimal\b", "mathematics"),
    ("Scunthorpe", r"\bscunthorpe\b", "geography"),
    ("cumulus", r"\bcumul(us|onimbus|ative)\b", "meteorology"),
    ("cockatoo", r"\bcockatoo(s)?\b", "ornithology"),
    ("cocktail", r"\bcocktail(s)?\b", "chemistry"),
    ("assassin", r"\bassassin(s|ation|ate)?\b", "history"),
    ("Middlesex", r"\bmiddlesex\b", "geography"),
    ("Sussex", r"\bsussex\b", "geography"),
    ("Essex", r"\bessex\b", "geography"),
    ("buttress", r"\bbuttress(es|ed|ing)?\b", "architecture"),
    ("canal", r"\bcanal(s)?\b", "geography"),
    ("angina pectoris", r"\bangina\s+pectoris\b", "medicine"),
    ("penile", r"\bpenile\b", "anatomy"),
    ("rectum", r"\brect(um|al)\b", "anatomy"),
    ("anus", r"\banus\b", "anatomy"),
    ("feces", r"\bfec(es|al)\b", "biology"),
    ("excretion", r"\bexcret(e|ion|ory|ing)\b", "biology"),
]


def get_academic_allowlist() -> list[AcademicTerm]:
    """Return all academic terms that should not trigger offensive filters."""
    return [
        AcademicTerm(term=t, pattern=re.compile(p, re.IGNORECASE), context_hint=c)
        for t, p, c in _ACADEMIC_TERMS
    ]


class OffensiveWordList:
    """Facade providing easy access to patterns and allowlist."""

    def __init__(self) -> None:
        self.patterns: list[OffensivePattern] = get_all_offensive_patterns()
        self.allowlist: list[AcademicTerm] = get_academic_allowlist()

    def get_patterns_by_category(self, category: str) -> list[OffensivePattern]:
        return [p for p in self.patterns if p.category == category]

    def get_patterns_by_severity(self, severity: str) -> list[OffensivePattern]:
        return [p for p in self.patterns if p.severity == severity]

    def is_academic(self, text: str) -> list[AcademicTerm]:
        """Return academic terms found in text."""
        return [a for a in self.allowlist if a.pattern.search(text)]
