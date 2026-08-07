"""Generic dry-run candidate log patterns shared by all games.

These never trigger supervisor actions. They only highlight likely lines in the
status UI so operators can promote precise regexes into each game's plugin
`log_patterns` (active) section.

Keep these cross-game and mundane — game-specific phrasing belongs in that
game's `games/game.yaml` under `log_pattern_candidates`, not here.

Bias toward over-matching: many short, case-insensitive guesses beat one
clever regex. Active plugin patterns should be much tighter after promotion.
"""

from __future__ import annotations

# Broad-on-purpose. Matched case-insensitively after ANSI stripping.
# Prefer several vague alternatives over a single precise pattern.
DEFAULT_CANDIDATE_PATTERNS: dict[str, list[str]] = {
    "ready": [
        r"\bserver started\b",
        r"\bstarted server\b",
        r"\bserver is ready\b",
        r"\bready for connections\b",
        r"\blistening on\b",
        r"\bopening socket\b",
        r"\bhosting game\b",
        r"\bworld loaded\b",
        r"\bmap loaded\b",
        r"\bgame loaded\b",
        r"\bin\s*game\b",
        r"\bchanging state\b",
        r"\bbound to\b",
        r"\baccepting connections\b",
        r"\bonline\b",
        r"\bready\b",
        r"\bstarted\b",
        r"\blistening\b",
        r"\bhosting\b",
    ],
    "player_join": [
        r"\[join\]",
        r"\bjoined the (game|server|world)\b",
        r"\bhas joined\b",
        r"\bplayer .+ joined\b",
        r"\bjoined\b",
        r"\bconnecting\b",
        r"\bconnected\b",
        r"\blogin\b",
        r"\bentering\b",
        r"\bspawn(ed)?\b",
    ],
    "player_leave": [
        r"\[leave\]",
        r"\bleft the (game|server|world)\b",
        r"\bhas left\b",
        r"\bplayer .+ left\b",
        r"\bdisconnected\b",
        r"\bdisconnecting\b",
        r"\bleft\b",
        r"\blogout\b",
        r"\bquit\b",
        r"\bkicked\b",
    ],
    "player_count": [
        r"\bplayers?\s+online\b",
        r"\bonline\s+players?\s*[:=]\s*\d+",
        r"\bthere are \d+ players?\b",
        r"\b\d+\s+players?\s+online\b",
        r"players?\s*[:=]\s*\d+",
        r"\bplayer count\b",
        r"\bnum(ber)? of players?\b",
        r"\bclients?\s*[:=]\s*\d+",
    ],
    "players_empty": [
        r"\bno (clients|players) connected\b",
        r"\bserver (is )?empty\b",
        r"\b0 players?\s+online\b",
        r"\bnobody (online|connected)\b",
        r"\ball players? (left|disconnected)\b",
        r"\blast player\b",
    ],
    # Announce lines only — mismatch/outdated belong in version_mismatch.
    "game_version": [
        r"\bgame version\s+(?P<version>\d+(?:\.\d+)+)\b",
        r"\bserver version\s*(?:[:=]\s*)?(?P<version>\d+(?:\.\d+)+)\b",
        r"\bversion\s*(?:[:=]\s*)(?P<version>\d+(?:\.\d+)+)\b",
        r"\bbuild\s+(?P<version>\d+)\b",
        r"\b(?P<version>\d+\.\d+\.\d+(?:\.\d+)?)\b",
    ],
    "version_mismatch": [
        r"\bwrong version\b",
        r"\bversion mismatch\b",
        r"\bclient version\b",
        r"\bincompatible version\b",
        r"\boutdated (client|server|version)\b",
        r"\bnewer version\b",
        r"\bmod mismatch\b",
        r"\bmap version\b",
        r"\bdesync\b",
    ],
}
