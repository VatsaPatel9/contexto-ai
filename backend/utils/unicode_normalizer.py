"""
Unicode normalization utility for detecting and neutralizing text obfuscation.

Provides NFKC normalization, confusable mapping, zero-width stripping,
leetspeak decoding, and detection/decoding of base64, hex, and rot13 payloads.
"""

from __future__ import annotations

import base64
import codecs
import math
import re
import string
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Confusable character map (60+ entries)
# ---------------------------------------------------------------------------

CONFUSABLE_MAP: dict[str, str] = {
    # Cyrillic → Latin
    "\u0410": "A",   # А
    "\u0430": "a",   # а
    "\u0412": "B",   # В
    "\u0435": "e",   # е
    "\u0415": "E",   # Е
    "\u041a": "K",   # К
    "\u043a": "k",   # к
    "\u041c": "M",   # М
    "\u043c": "m",   # м (looks like m in some fonts)
    "\u041d": "H",   # Н
    "\u043e": "o",   # о
    "\u041e": "O",   # О
    "\u0440": "p",   # р
    "\u0420": "P",   # Р
    "\u0441": "c",   # с
    "\u0421": "C",   # С
    "\u0443": "y",   # у
    "\u0423": "Y",   # У
    "\u0445": "x",   # х
    "\u0425": "X",   # Х
    "\u0456": "i",   # і (Ukrainian)
    "\u0406": "I",   # І (Ukrainian)
    "\u0458": "j",   # ј (Serbian)
    "\u0455": "s",   # ѕ (Macedonian)
    "\u0405": "S",   # Ѕ (Macedonian)
    "\u0442": "t",   # т (lowercase looks like m in italic, but maps to t)
    "\u0422": "T",   # Т
    "\u0432": "v",   # в (mapped to v visually in some contexts)
    # Greek → Latin
    "\u0391": "A",   # Α (Alpha)
    "\u03b1": "a",   # α (alpha) — close enough in many fonts
    "\u0392": "B",   # Β (Beta)
    "\u03b2": "b",   # β (beta)
    "\u0395": "E",   # Ε (Epsilon)
    "\u03b5": "e",   # ε (epsilon)
    "\u0397": "H",   # Η (Eta)
    "\u03b7": "h",   # η (eta) — tail differs but visually close
    "\u0399": "I",   # Ι (Iota)
    "\u03b9": "i",   # ι (iota)
    "\u039a": "K",   # Κ (Kappa)
    "\u03ba": "k",   # κ (kappa)
    "\u039c": "M",   # Μ (Mu)
    "\u03bc": "m",   # μ (mu) — close
    "\u039d": "N",   # Ν (Nu)
    "\u03bd": "n",   # ν (nu)
    "\u039f": "O",   # Ο (Omicron)
    "\u03bf": "o",   # ο (omicron)
    "\u03a1": "P",   # Ρ (Rho)
    "\u03c1": "p",   # ρ (rho)
    "\u03a4": "T",   # Τ (Tau)
    "\u03c4": "t",   # τ (tau)
    "\u03a5": "Y",   # Υ (Upsilon)
    "\u03c5": "u",   # υ (upsilon)
    "\u03a7": "X",   # Χ (Chi)
    "\u03c7": "x",   # χ (chi)
    "\u03b6": "z",   # ζ (zeta) — loose match
    "\u0396": "Z",   # Ζ (Zeta)
    # Fullwidth ASCII → ASCII (U+FF01 to U+FF5E map to U+0021 to U+007E)
    # We handle a-z and A-Z explicitly for the most common attack vector
    **{chr(0xFF01 + i): chr(0x21 + i) for i in range(94)},
    # Dashes and hyphens
    "\u2010": "-",   # hyphen
    "\u2011": "-",   # non-breaking hyphen
    "\u2012": "-",   # figure dash
    "\u2013": "-",   # en dash
    "\u2014": "-",   # em dash
    "\u2015": "-",   # horizontal bar
    "\u2212": "-",   # minus sign
    # Spaces and separators
    "\u00a0": " ",   # non-breaking space
    "\u2000": " ",   # en quad
    "\u2001": " ",   # em quad
    "\u2002": " ",   # en space
    "\u2003": " ",   # em space
    "\u2004": " ",   # three-per-em space
    "\u2005": " ",   # four-per-em space
    "\u2006": " ",   # six-per-em space
    "\u2007": " ",   # figure space
    "\u2008": " ",   # punctuation space
    "\u2009": " ",   # thin space
    "\u200a": " ",   # hair space
    "\u205f": " ",   # medium mathematical space
    "\u3000": " ",   # ideographic space
}


# ---------------------------------------------------------------------------
# Zero-width characters to strip
# ---------------------------------------------------------------------------

ZERO_WIDTH_CHARS: set[str] = {
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\ufeff",  # byte order mark / zero-width no-break space
    "\u00ad",  # soft hyphen
    "\u200e",  # left-to-right mark
    "\u200f",  # right-to-left mark
    "\u2060",  # word joiner
    "\u2061",  # function application
    "\u2062",  # invisible times
    "\u2063",  # invisible separator
    "\u2064",  # invisible plus
    "\u180e",  # Mongolian vowel separator
    "\ufff9",  # interlinear annotation anchor
    "\ufffa",  # interlinear annotation separator
    "\ufffb",  # interlinear annotation terminator
}


# ---------------------------------------------------------------------------
# Leetspeak map
# ---------------------------------------------------------------------------

_LEET_MAP: dict[str, str] = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "@": "a",
    "$": "s",
}


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------

@dataclass
class EncodingDetection:
    """Describes a detected encoded substring."""
    encoding_type: str          # "base64" | "hex" | "rot13"
    encoded_text: str           # the encoded substring
    decoded_text: str           # the decoded result
    start: int                  # start index in original text
    end: int                    # end index in original text
    confidence: float           # 0.0 – 1.0


def _shannon_entropy(text: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not text:
        return 0.0
    freq: dict[str, int] = {}
    for ch in text:
        freq[ch] = freq.get(ch, 0) + 1
    length = len(text)
    return -sum((c / length) * math.log2(c / length) for c in freq.values())


def _is_base64_candidate(text: str) -> bool:
    """Check if text looks like base64."""
    b64_chars = set(string.ascii_letters + string.digits + "+/=")
    if len(text) < 8:
        return False
    if not all(ch in b64_chars for ch in text):
        return False
    # Base64 length is typically a multiple of 4
    if len(text) % 4 not in (0, 2, 3):
        return False
    # Check entropy: base64 text tends to have high entropy
    if _shannon_entropy(text) < 3.0:
        return False
    return True


def _try_base64_decode(text: str) -> Optional[str]:
    """Try to decode base64, return decoded string or None."""
    try:
        # Pad if needed
        padded = text + "=" * (4 - len(text) % 4) if len(text) % 4 != 0 else text
        decoded_bytes = base64.b64decode(padded, validate=True)
        decoded = decoded_bytes.decode("utf-8", errors="strict")
        # Verify result is printable text
        if all(ch in string.printable for ch in decoded):
            return decoded
    except Exception:
        pass
    return None


def _try_hex_decode(text: str) -> Optional[str]:
    """Try to decode hex string, return decoded string or None."""
    try:
        cleaned = text.replace(" ", "").replace("0x", "").replace("\\x", "")
        if len(cleaned) < 4 or len(cleaned) % 2 != 0:
            return None
        if not all(ch in string.hexdigits for ch in cleaned):
            return None
        decoded_bytes = bytes.fromhex(cleaned)
        decoded = decoded_bytes.decode("utf-8", errors="strict")
        if all(ch in string.printable for ch in decoded):
            return decoded
    except Exception:
        pass
    return None


def _rot13_decode(text: str) -> str:
    """Apply ROT13 decoding."""
    return codecs.decode(text, "rot_13")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """
    Full normalization pipeline:
    1. NFKC unicode normalization
    2. Strip zero-width characters
    3. Map confusable characters to ASCII
    4. Collapse whitespace
    """
    if not text:
        return text

    # Step 1: NFKC normalization
    result = unicodedata.normalize("NFKC", text)

    # Step 2: strip zero-width characters
    result = "".join(ch for ch in result if ch not in ZERO_WIDTH_CHARS)

    # Step 3: map confusables
    chars = []
    for ch in result:
        chars.append(CONFUSABLE_MAP.get(ch, ch))
    result = "".join(chars)

    # Step 4: collapse whitespace (multiple spaces → single, strip invisible separators)
    result = re.sub(r"[ \t]+", " ", result)
    result = result.strip()

    return result


def decode_leetspeak(text: str) -> str:
    """
    Decode leetspeak (1337speak) substitutions.

    Mapping: 0->o, 1->i, 3->e, 4->a, 5->s, 7->t, 8->b, @->a, $->s
    """
    chars = []
    for ch in text:
        chars.append(_LEET_MAP.get(ch, ch))
    return "".join(chars)


def detect_encoding(text: str) -> list[EncodingDetection]:
    """
    Scan text for base64, hex-encoded, and rot13-encoded substrings.

    Returns a list of EncodingDetection objects describing found payloads.
    """
    detections: list[EncodingDetection] = []

    # Look for base64 candidates (contiguous alphanumeric+/= blocks of 8+ chars)
    b64_pattern = re.compile(r"[A-Za-z0-9+/]{8,}={0,2}")
    for m in b64_pattern.finditer(text):
        candidate = m.group(0)
        if _is_base64_candidate(candidate):
            decoded = _try_base64_decode(candidate)
            if decoded and len(decoded) >= 4:
                detections.append(EncodingDetection(
                    encoding_type="base64",
                    encoded_text=candidate,
                    decoded_text=decoded,
                    start=m.start(),
                    end=m.end(),
                    confidence=min(0.5 + _shannon_entropy(candidate) / 10, 0.95),
                ))

    # Look for hex-encoded strings (0x prefix or \x prefix or long hex blocks)
    hex_patterns = [
        re.compile(r"(?:0x[0-9a-fA-F]{2}\s*){4,}"),          # 0x41 0x42 ...
        re.compile(r"(?:\\x[0-9a-fA-F]{2}){4,}"),              # \x41\x42 ...
        re.compile(r"\b[0-9a-fA-F]{8,}\b"),                    # contiguous hex
    ]
    for pat in hex_patterns:
        for m in pat.finditer(text):
            candidate = m.group(0)
            decoded = _try_hex_decode(candidate)
            if decoded and len(decoded) >= 3:
                detections.append(EncodingDetection(
                    encoding_type="hex",
                    encoded_text=candidate,
                    decoded_text=decoded,
                    start=m.start(),
                    end=m.end(),
                    confidence=0.8,
                ))

    # Look for rot13 candidates: we check if rot13-decoding any word produces
    # a known suspicious keyword
    _suspicious_decoded = {
        "ignore", "instructions", "system", "prompt", "override",
        "forget", "disregard", "pretend", "bypass", "sudo",
        "jailbreak", "developer", "debug", "unrestricted",
    }
    words = re.findall(r"[a-zA-Z]{4,}", text)
    for word in words:
        decoded_word = _rot13_decode(word).lower()
        if decoded_word in _suspicious_decoded:
            # Find position in original text
            idx = text.find(word)
            if idx >= 0:
                detections.append(EncodingDetection(
                    encoding_type="rot13",
                    encoded_text=word,
                    decoded_text=decoded_word,
                    start=idx,
                    end=idx + len(word),
                    confidence=0.7,
                ))

    return detections


def decode_all(text: str) -> str:
    """
    Detect and decode all encoded substrings in-place.

    Replaces each encoded substring with its decoded version.
    """
    detections = detect_encoding(text)
    if not detections:
        return text

    # Sort by start position descending so replacements don't shift indices
    detections.sort(key=lambda d: d.start, reverse=True)

    result = text
    for det in detections:
        result = result[:det.start] + det.decoded_text + result[det.end:]

    return result
