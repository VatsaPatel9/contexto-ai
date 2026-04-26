"""Single source of truth for the current Terms / Privacy version string.

Bumping this constant invalidates every previously-accepted record (the
signup gate accepts only the current value). Frontend reads the same
value from ``GET /api/parameters`` so the UI and server agree.

Format is ISO date of the last edit to ``/terms`` and ``/privacy``.
"""

from __future__ import annotations

CURRENT_TERMS_VERSION = "2026-04-26"
