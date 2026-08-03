"""Generic dry-run candidate log patterns shared by all games.

These never trigger supervisor actions. They only highlight likely lines in the
status UI so operators can promote precise regexes into each game's plugin
`log_patterns` (active) section.
"""

from __future__ import annotations

# Broad-on-purpose. Active plugin patterns should be much tighter.
DEFAULT_CANDIDATE_PATTERNS: dict[str, list[str]] = {
    "ready": [
        r"\bserver started\b",
        r"\blistening on\b",
        r"\bworld loaded\b",
        r"\bready\b",
    ],
    "player_join": [
        r"\bconnected\b",
        r"\bjoined\b",
        r"\blogin\b",
        r"\bentering\b",
    ],
    "player_leave": [
        r"\bdisconnected\b",
        r"\bleft\b",
        r"\blogout\b",
        r"\bleaving\b",
    ],
    "player_count": [
        r"players?\s*(online|:|/)",
        r"\b\d+\s*/\s*\d+\b",
    ],
    "version_mismatch": [
        r"\bwrong version\b",
        r"\bversion mismatch\b",
        r"\boutdated\b",
        r"\bincompatible\b",
        r"\bclient version\b",
        r"\bnewer version\b",
    ],
}
