"""Generic dry-run candidate log patterns shared by all games.

These never trigger supervisor actions. They only highlight likely lines in the
status UI so operators can promote precise regexes into each game's plugin
`log_patterns` (active) section.

Keep these cross-game and mundane — game-specific phrasing belongs in that
game's `games/game.yaml`, not here.
"""

from __future__ import annotations

# Broad-on-purpose. Active plugin patterns should be much tighter.
# Matched case-insensitively after ANSI stripping.
DEFAULT_CANDIDATE_PATTERNS: dict[str, list[str]] = {
    "ready": [
        r"\bserver started\b",
        r"\bstarted server\b",
        r"\bserver is ready\b",
        r"\bready for connections\b",
        r"\blistening on\b",
        r"\bworld loaded\b",
        r"\bready\b",
    ],
    "player_join": [
        r"\bjoined the (game|server|world)\b",
        r"\bhas joined\b",
        r"\bplayer .+ joined\b",
        r"\bjoined\b",
        r"\bconnected\b",
        r"\blogin\b",
    ],
    "player_leave": [
        r"\bleft the (game|server|world)\b",
        r"\bhas left\b",
        r"\bplayer .+ left\b",
        r"\bdisconnected\b",
        r"\bleft\b",
        r"\blogout\b",
    ],
    "player_count": [
        r"\bplayers?\s+online\b",
        r"\bonline\s+players?\s*[:=]\s*\d+",
        r"\bthere are \d+ players?\b",
        r"\b\d+\s+players?\s+online\b",
        r"players?\s*[:=]\s*\d+",
    ],
    # Announce lines only — mismatch/outdated belong in version_mismatch.
    "game_version": [
        r"\bgame version\s+(?P<version>\d+(?:\.\d+)+)\b",
        r"\bserver version\s*(?:[:=]\s*)?(?P<version>\d+(?:\.\d+)+)\b",
        r"\bversion\s*(?:[:=]\s*)(?P<version>\d+(?:\.\d+)+)\b",
    ],
    "version_mismatch": [
        r"\bwrong version\b",
        r"\bversion mismatch\b",
        r"\bclient version\b",
        r"\bincompatible version\b",
        r"\boutdated (client|server|version)\b",
        r"\bnewer version\b",
    ],
}
