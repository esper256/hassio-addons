"""Status + log-capture HTTP server for Ingress / browser use (no SSH needed)."""

from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .disk import format_bytes
from .log_bridge import strip_ansi
from .version import app_version
from .backup import EMPTY_WORLD

LOG = logging.getLogger("game_server.status_http")

# Home Assistant Ingress proxy source address (Supervisor).
INGRESS_PEER = "172.30.32.2"

# Default Ingress palette; games override via ``ui_theme`` in games/game.yaml.
DEFAULT_UI_THEME: dict[str, str] = {
    "bg": "#1a1d24",
    "panel": "#242933",
    "ink": "#e8eaed",
    "muted": "#9aa3b2",
    "accent": "#7aa2f7",
    "good": "#9ece6a",
    "bad": "#f7768e",
    "glow": "#2a3344",
    "wash": "#12151a",
    "depth": "#1a1714",
}
UI_THEME_KEYS = tuple(DEFAULT_UI_THEME.keys())


def resolve_ui_theme(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Merge game ``ui_theme`` overrides onto the base default palette."""

    theme = dict(DEFAULT_UI_THEME)
    if not overrides:
        return theme
    for key in UI_THEME_KEYS:
        value = overrides.get(key)
        if isinstance(value, str) and value.strip():
            theme[key] = value.strip()
    return theme

# Phases where the HA watchdog should leave the add-on running.
_HEALTHY_LIFECYCLES = frozenset(
    {"running", "installing", "updating", "restoring", "starting", "waiting"}
)


def healthz_ok(snapshot: dict[str, Any]) -> bool:
    """Whether /healthz should report ok for this status/health snapshot."""

    if "ok" in snapshot:
        return bool(snapshot["ok"])
    phase = str(snapshot.get("lifecycle") or "")
    if phase:
        return phase in _HEALTHY_LIFECYCLES
    # Legacy fallback before lifecycle existed.
    return bool(snapshot.get("running")) or bool(snapshot.get("starting"))


def _html_escape(text: str) -> str:
    return html.escape(str(text), quote=True)


def _as_confirm_flag(value: Any) -> bool:
    """True for JSON true / common truthy confirm encodings."""

    if value is True:
        return True
    if isinstance(value, (int, float)) and value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return False


def _read_http_body(handler: BaseHTTPRequestHandler, *, max_bytes: int = 1_000_000) -> bytes:
    """Read a request body even when Ingress omits Content-Length (chunked)."""

    length_header = handler.headers.get("Content-Length")
    if length_header is not None and str(length_header).strip() != "":
        try:
            length = int(length_header)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return b""
        return handler.rfile.read(min(length, max_bytes))

    encoding = (handler.headers.get("Transfer-Encoding") or "").lower()
    if "chunked" not in encoding:
        return b""

    chunks: list[bytes] = []
    total = 0
    while True:
        size_line = handler.rfile.readline()
        if not size_line:
            break
        size_token = size_line.strip().split(b";", 1)[0]
        try:
            size = int(size_token, 16)
        except ValueError:
            break
        if size == 0:
            # Consume optional trailers through the blank line.
            while True:
                trailer = handler.rfile.readline()
                if trailer in (b"", b"\r\n", b"\n"):
                    break
            break
        if total + size > max_bytes:
            raise ValueError("request body too large")
        chunk = handler.rfile.read(size)
        chunks.append(chunk)
        total += len(chunk)
        handler.rfile.read(2)  # trailing CRLF after each chunk
    return b"".join(chunks)


def _parse_json_object(raw: bytes) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON body") from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object")
    return payload


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <base href="{base_href}" />
  <title>{game} server status</title>
  <style>
    :root {{
      --bg: {theme_bg};
      --panel: {theme_panel};
      --ink: {theme_ink};
      --muted: {theme_muted};
      --accent: {theme_accent};
      --good: {theme_good};
      --bad: {theme_bad};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, {theme_glow} 0%, transparent 40%),
        linear-gradient(160deg, {theme_wash}, var(--bg) 55%, {theme_depth});
      color: var(--ink);
      min-height: 100vh;
      padding: 2rem;
    }}
    main {{ max-width: 920px; margin: 0 auto; }}
    h1 {{
      font-family: "IBM Plex Serif", Georgia, serif;
      font-weight: 600;
      font-size: clamp(1.8rem, 4vw, 2.6rem);
      margin: 0 0 0.35rem;
      letter-spacing: -0.02em;
    }}
    h2 {{ margin: 1.75rem 0 0.6rem; font-size: 1.15rem; }}
    .sub {{ color: var(--muted); margin-bottom: 1.25rem; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 1rem;
    }}
    .stat {{
      background: color-mix(in srgb, var(--panel) 88%, black);
      border: 1px solid color-mix(in srgb, var(--muted) 25%, transparent);
      padding: 1rem 1.1rem;
    }}
    .stat .label {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 0.35rem; }}
    .stat .value {{ font-size: 1.35rem; font-weight: 600; }}
    .stat .hint {{ color: var(--muted); font-size: 0.78rem; margin-top: 0.35rem; }}
    .stat .hint:empty {{ display: none; margin: 0; }}
    .good {{ color: var(--good); }}
    .bad {{ color: var(--bad); }}
    .accent {{ color: var(--accent); }}
    pre {{
      background: rgba(0,0,0,0.28);
      padding: 1rem;
      overflow: auto;
      font-size: 0.78rem;
      line-height: 1.4;
      border: 1px solid color-mix(in srgb, var(--muted) 20%, transparent);
      max-height: 320px;
    }}
    a {{ color: var(--accent); }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      align-items: center;
      margin: 0.5rem 0 0.75rem;
    }}
    .actions a, .actions button,
    .capture-row > a, .capture-row > button,
    label.file-btn {{
      display: inline-block;
      padding: 0.45rem 0.75rem;
      border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
      background: transparent;
      color: var(--accent);
      text-decoration: none;
      font: inherit;
      cursor: pointer;
    }}
    .actions a:hover, .actions button:hover,
    .capture-row > a:hover, .capture-row > button:hover,
    label.file-btn:hover {{
      background: color-mix(in srgb, var(--accent) 12%, transparent);
    }}
    .actions a:disabled, .actions button:disabled,
    .capture-row > a:disabled, .capture-row > button:disabled {{
      opacity: 0.5;
      cursor: not-allowed;
    }}
    .capture-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      align-items: center;
      margin: 0.5rem 0 0.65rem;
    }}
    .capture-row > label:not(.file-btn),
    .capture-row > .row-label {{
      color: var(--muted);
      font-size: 0.9rem;
      min-width: 7.5rem;
    }}
    /* Hide native file control; label.file-btn is the visible picker. */
    .file-input {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      border: 0;
    }}
    .file-name {{
      color: var(--muted);
      font-size: 0.88rem;
      max-width: min(100%, 18rem);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .sub:empty {{ display: none; margin: 0; }}
    select {{
      background: rgba(0,0,0,0.28);
      color: var(--ink);
      border: 1px solid color-mix(in srgb, var(--muted) 35%, transparent);
      padding: 0.45rem 0.6rem;
      font: inherit;
      min-width: min(100%, 28rem);
    }}
    details.api, details.log-watch {{
      margin-top: 1rem;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    details.api summary, details.log-watch summary {{
      cursor: pointer;
      color: var(--accent);
    }}
    details.log-watch {{
      margin-top: 1.75rem;
      font-size: 1rem;
      color: var(--ink);
    }}
    details.log-watch > summary {{
      font-size: 1.15rem;
      font-weight: 600;
      list-style: disclosure-closed;
    }}
    details.log-watch[open] > summary {{
      margin-bottom: 0.6rem;
    }}
    details.api ul {{ padding-left: 1.1rem; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
      margin-top: 0.5rem;
    }}
    th, td {{
      text-align: left;
      padding: 0.4rem 0.45rem;
      border-bottom: 1px solid color-mix(in srgb, var(--muted) 18%, transparent);
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .tag {{
      display: inline-block;
      padding: 0.1rem 0.35rem;
      border: 1px solid color-mix(in srgb, var(--muted) 35%, transparent);
      margin-right: 0.25rem;
      font-size: 0.72rem;
    }}
    .tag.active {{ border-color: var(--good); color: var(--good); }}
    .tag.dry_run {{ border-color: var(--accent); color: var(--accent); }}
    .tag.stale {{ border-color: var(--bad); color: var(--bad); }}
    code {{ color: var(--ink); }}
    .hidden {{ display: none !important; }}
    .recent-matches {{
      font-size: 0.75rem;
      line-height: 1.35;
      max-height: 9.5rem;
      overflow: auto;
      max-width: 42rem;
    }}
    .recent-matches div {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: var(--muted);
    }}
    .pattern-cell {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.72rem;
      color: var(--muted);
      max-width: 18rem;
      word-break: break-all;
    }}
  </style>
</head>
<body>
  <main>
    <h1>{game}</h1>
    <p class="sub" id="subtitle">{subtitle}</p>
    <div class="grid" id="status-grid">
      <div class="stat"><div class="label">Server</div><div class="value {running_class}" id="v-running">{running}</div></div>
      <div class="stat {players_card_class}" id="card-players">
        <div class="label" id="l-players">{players_label}</div>
        <div class="value" id="v-players">{players}</div>
        <div class="hint" id="h-players">{players_hint}</div>
      </div>
      <div class="stat">
        <div class="label">Uptime</div>
        <div class="value" id="v-uptime">{uptime}</div>
        <div class="hint" id="h-uptime">{uptime_hint}</div>
      </div>
      <div class="stat">
        <div class="label">Game server crashes</div>
        <div class="value" id="v-crashes">{crashes}</div>
        <div class="hint" id="h-crashes">{crashes_hint}</div>
      </div>
      <div class="stat">
        <div class="label">Game version</div>
        <div class="value" id="v-game-version">{game_version}</div>
        <div class="hint" id="h-game-version-build">{game_version_build}</div>
        <div class="hint" id="h-game-version-installed">{game_version_installed}</div>
      </div>
      <div class="stat">
        <div class="label">Update pending</div>
        <div class="value" id="v-update">{update_pending}</div>
        <div class="hint" id="h-update">{update_check_hint}</div>
      </div>
      <div class="stat">
        <div class="label">World save</div>
        <div class="value" id="v-world">{world_save}</div>
        <div class="hint" id="h-world">{world_save_hint}</div>
      </div>
      <div class="stat">
        <div class="label">Backups</div>
        <div class="value" id="v-backups">{backups}</div>
        <div class="hint" id="h-backups-oldest">{backups_oldest}</div>
        <div class="hint" id="h-backups-newest">{backups_newest}</div>
      </div>
      <div class="stat">
        <div class="label">Free disk</div>
        <div class="value {disk_class}" id="v-disk">{disk}</div>
        <div class="hint" id="h-disk">{disk_hint}</div>
      </div>
    </div>
    <div class="actions" id="update-actions">
      <button type="button" id="btn-force-update" onclick="return forceUpdate(event)">
        Update game server now
      </button>
    </div>

    <h2>World backups</h2>
    <p class="sub">
      Restore replaces the live world only after you confirm, and only after a
      successful pre-restore safety backup when any world data exists. Choose
      <strong>NEW WORLD</strong> in the list for an empty world, or upload a save
      below. Archives are deleted only by their family rules: retention profile
      (scheduled), keep newest (pre-update), or age window (pre-restore).
    </p>
    <div class="capture-row">
      <label for="backup-select">Saved backup</label>
      <select id="backup-select">{backup_options}</select>
      <button type="button" id="btn-restore" onclick="return restoreBackup(event)">
        Restore selected backup
      </button>
    </div>
    <div class="capture-row {world_upload_class}" id="world-upload-row">
      <span class="row-label">Upload save</span>
      <input type="file" id="world-upload" class="file-input" accept="{world_upload_accept}"
             onchange="onWorldUploadChosen()" />
      <label class="file-btn" for="world-upload">Choose file</label>
      <span class="file-name" id="world-upload-name">No file chosen</span>
      <button type="button" id="btn-world-upload" onclick="return uploadWorld(event)">
        Restore from upload
      </button>
    </div>
    <p class="sub" id="world-upload-hint">{world_upload_hint}</p>

    <details class="log-watch {log_watch_class}" id="log-watch"{log_watch_open}>
      <summary>Game server log watching pattern hits</summary>
      <p class="sub">
        <span class="tag active">active</span> can trigger updates/player state.
        <span class="tag dry_run">dry_run</span> only highlights candidates (many broad guesses; over-match is OK).
        Promote a precise hit into the game plugin <code>log_patterns</code> to make it
        <span class="tag active">active</span>.
        <span class="tag stale">stale</span> means a pattern used to hit but has not recently.
      </p>
      <table>
        <thead>
          <tr><th>Mode</th><th>Category</th><th>Pattern</th><th>Hits</th><th>Recent matches (newest first)</th></tr>
        </thead>
        <tbody id="pattern-rows">
          {pattern_rows}
        </tbody>
      </table>
      <h2>Highlighted lines</h2>
      <pre id="highlights">{highlights}</pre>
    </details>

    <h2>Log tools</h2>
    <p class="sub">Human actions for diagnosing the live server. Prefer these over the JSON API links.</p>
    <div class="actions">
      <a href="api/logs/capture" onclick="return postCapture(event)">Capture logs now</a>
      <a href="api/logs/raw?lines=400&amp;format=text">View recent game output</a>
    </div>
    <div class="capture-row">
      <label for="capture-select">Saved captures</label>
      <select id="capture-select">{capture_options}</select>
      <a id="capture-download" href="#" onclick="return downloadCapture(event)">Download</a>
    </div>

    <details class="api">
      <summary>JSON API (automation / pattern tuning)</summary>
      <ul>
        <li><a href="api/status">Status JSON</a></li>
        <li><a href="api/ui">Formatted UI JSON (soft refresh)</a></li>
        <li>POST <code>api/update</code> — schedule Steam update now (disconnects players)</li>
        <li><a href="api/backups">Backups list JSON</a></li>
        <li><a href="api/world/download">Download active world save</a></li>
        <li>POST <code>api/world/upload?confirm=1</code> — raw world file body (mode from active world kind)</li>
        <li>POST <code>api/backups/restore</code> — <code>{{"archive":"…","confirm":true}}</code> or <code>{{"empty":true,"confirm":true}}</code></li>
        <li><a href="api/logs/patterns">Pattern hit report</a></li>
        <li><a href="api/logs/suggest">Suggest patterns from recent logs</a></li>
        <li><a href="api/logs/captures">Captures list JSON</a></li>
        <li><a href="api/logs/raw?lines=400">Recent game output JSON</a></li>
      </ul>
    </details>
  </main>
  <script>
    async function postCapture(ev) {{
      ev.preventDefault();
      const res = await fetch('api/logs/capture', {{ method: 'POST' }});
      const data = await res.json();
      if (data.download_path) {{
        window.location = data.download_path.replace(/^\\//, '');
      }} else {{
        alert(JSON.stringify(data, null, 2));
      }}
      return false;
    }}
    async function restoreBackup(ev) {{
      ev.preventDefault();
      const select = document.getElementById('backup-select');
      if (!select || !select.value) {{
        alert('No backup selected');
        return false;
      }}
      const name = select.value;
      const emptyWorld = name === '{empty_world_token}';
      const ok = window.confirm(
        emptyWorld
          ? (
            'Start a new empty world?\\n\\n' +
            'The game server will stop. If any world data exists, it is saved first ' +
            'as a pre-restore safety copy. Only after that backup succeeds are world ' +
            'files cleared so the game can create a fresh world on restart.\\n\\n' +
            'Anyone playing will be disconnected.'
          )
          : (
            'Restore this backup over the live world?\\n\\n' +
            name + '\\n\\n' +
            'The game server will stop. If any world data exists, it is saved first ' +
            'as a pre-restore safety copy. Only after that backup succeeds does the ' +
            'selected archive replace the world; then the server restarts.\\n\\n' +
            'Anyone playing will be disconnected.'
          )
      );
      if (!ok) return false;
      const btn = document.getElementById('btn-restore');
      if (btn) btn.disabled = true;
      try {{
        // Query-string mirrors the JSON body: some Ingress paths drop/omit the
        // POST body (missing Content-Length), which used to look like a failed confirm.
        const qs = emptyWorld
          ? 'empty=1&confirm=1'
          : ('archive=' + encodeURIComponent(name) + '&confirm=1');
        const body = emptyWorld
          ? {{ empty: true, confirm: true }}
          : {{ archive: name, confirm: true }};
        const res = await fetch('api/backups/restore?' + qs, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(body),
        }});
        const data = await res.json();
        if (data.ok) {{
          softRefresh();
        }} else {{
          alert(data.error || (emptyWorld ? 'Could not schedule empty-world reset.' : 'Could not schedule restore.'));
        }}
      }} catch (e) {{
        alert(emptyWorld ? 'Could not schedule empty-world reset.' : 'Could not schedule restore.');
      }} finally {{
        if (btn) btn.disabled = false;
      }}
      return false;
    }}
    function onWorldUploadChosen() {{
      const input = document.getElementById('world-upload');
      const name = document.getElementById('world-upload-name');
      if (!name) return;
      if (input && input.files && input.files[0]) {{
        name.textContent = input.files[0].name;
      }} else {{
        name.textContent = 'No file chosen';
      }}
    }}
    async function uploadWorld(ev) {{
      ev.preventDefault();
      const input = document.getElementById('world-upload');
      if (!input || !input.files || !input.files[0]) {{
        alert('Choose a world save file to upload');
        return false;
      }}
      const file = input.files[0];
      const ok = window.confirm(
        'Restore the live world from this upload?\\n\\n' +
        file.name + ' (' + file.size + ' bytes)\\n\\n' +
        'The game server will stop. If any world data exists, it is saved first ' +
        'as a pre-restore safety copy. How your file is applied depends on how this ' +
        'game stores its world (single file vs folder), not on the upload name alone.\\n\\n' +
        'Anyone playing will be disconnected.'
      );
      if (!ok) return false;
      const btn = document.getElementById('btn-world-upload');
      if (btn) btn.disabled = true;
      try {{
        const res = await fetch(
          'api/world/upload?confirm=1&filename=' + encodeURIComponent(file.name),
          {{
            method: 'POST',
            headers: {{
              'Content-Type': file.type || 'application/octet-stream',
            }},
            body: file,
          }}
        );
        const data = await res.json();
        if (data.ok) {{
          softRefresh();
        }} else {{
          alert(data.error || 'Could not schedule world upload.');
        }}
      }} catch (e) {{
        alert('Could not schedule world upload.');
      }} finally {{
        if (btn) btn.disabled = false;
      }}
      return false;
    }}
    async function forceUpdate(ev) {{
      ev.preventDefault();
      const ok = window.confirm(
        'Update the game server from Steam now?\\n\\n' +
        'The server will stop, update, and restart. Anyone playing will be disconnected.'
      );
      if (!ok) return false;
      const btn = document.getElementById('btn-force-update');
      if (btn) btn.disabled = true;
      try {{
        const res = await fetch('api/update', {{ method: 'POST' }});
        const data = await res.json();
        if (data.ok) {{
          alert(data.message || 'Update scheduled.');
          softRefresh();
        }} else {{
          alert(data.error || 'Could not schedule update.');
        }}
      }} catch (e) {{
        alert('Could not schedule update.');
      }} finally {{
        if (btn) btn.disabled = false;
      }}
      return false;
    }}
    function downloadCapture(ev) {{
      ev.preventDefault();
      const select = document.getElementById('capture-select');
      if (!select || !select.value) {{
        alert('No capture selected');
        return false;
      }}
      window.location = select.value;
      return false;
    }}
    function setText(id, value) {{
      const el = document.getElementById(id);
      if (el) el.textContent = value == null ? '' : String(value);
    }}
    function setHtml(id, value) {{
      const el = document.getElementById(id);
      if (el) el.innerHTML = value == null ? '' : String(value);
    }}
    async function softRefresh() {{
      try {{
        const res = await fetch('api/ui', {{ headers: {{ 'Accept': 'application/json' }} }});
        if (!res.ok) return;
        const u = await res.json();
        setText('subtitle', u.subtitle);
        const running = document.getElementById('v-running');
        if (running) {{
          running.textContent = u.running;
          running.className = 'value ' + (u.running_class || '');
        }}
        setText('l-players', u.players_label);
        setText('v-players', u.players);
        setText('h-players', u.players_hint);
        const playersCard = document.getElementById('card-players');
        if (playersCard) {{
          playersCard.classList.toggle('hidden', !!u.players_card_hidden);
        }}
        setText('v-uptime', u.uptime);
        setText('h-uptime', u.uptime_hint);
        setText('v-crashes', u.crashes);
        setText('h-crashes', u.crashes_hint);
        setText('v-game-version', u.game_version);
        setText('h-game-version-build', u.game_version_build);
        setText('h-game-version-installed', u.game_version_installed);
        setText('v-update', u.update_pending);
        setText('h-update', u.update_check_hint);
        setText('v-backups', u.backups);
        setText('h-backups-oldest', u.backups_oldest);
        setText('h-backups-newest', u.backups_newest);
        const logWatch = document.getElementById('log-watch');
        if (logWatch) {{
          logWatch.classList.toggle('hidden', !!u.log_watch_hidden);
        }}
        setText('v-world', u.world_save);
        setHtml('h-world', u.world_save_hint);
        setText('world-upload-hint', u.world_upload_hint);
        const uploadRow = document.getElementById('world-upload-row');
        if (uploadRow) {{
          uploadRow.classList.toggle('hidden', !!u.world_upload_hidden);
        }}
        const uploadInput = document.getElementById('world-upload');
        if (uploadInput && u.world_upload_accept) {{
          uploadInput.accept = u.world_upload_accept;
        }}
        const disk = document.getElementById('v-disk');
        if (disk) {{
          disk.textContent = u.disk;
          disk.className = 'value ' + (u.disk_class || '');
        }}
        setText('h-disk', u.disk_hint);
        setHtml('pattern-rows', u.pattern_rows);
        setText('highlights', u.highlights);
        const sel = document.getElementById('capture-select');
        if (sel && u.capture_options) {{
          const prev = sel.value;
          sel.innerHTML = u.capture_options;
          if (prev) sel.value = prev;
        }}
        const bsel = document.getElementById('backup-select');
        if (bsel && u.backup_options) {{
          const prev = bsel.value;
          bsel.innerHTML = u.backup_options;
          if (prev) bsel.value = prev;
        }}
      }} catch (e) {{}}
    }}
    setInterval(softRefresh, 20000);
  </script>
</body>
</html>
"""


class StatusServer:
    def __init__(
        self,
        host: str,
        port: int,
        status_provider: Callable[[], dict[str, Any]],
        *,
        health_provider: Callable[[], dict[str, Any]] | None = None,
        game_name: str = "Game",
        ui_theme: dict[str, str] | None = None,
        log_toolbox=None,
        capture_callback: Callable[[str], dict[str, Any]] | None = None,
        update_callback: Callable[[], dict[str, Any]] | None = None,
        restore_callback: Callable[[str], dict[str, Any]] | None = None,
        upload_callback: Callable[[Path], dict[str, Any]] | None = None,
        upload_staging_dir: str | Path | None = None,
        backups_provider: Callable[[], list[dict[str, Any]]] | None = None,
        world_download_callback: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.status_provider = status_provider
        self.health_provider = health_provider
        self.game_name = game_name
        self.ui_theme = resolve_ui_theme(ui_theme)
        self.log_toolbox = log_toolbox
        self.capture_callback = capture_callback
        self.update_callback = update_callback
        self.restore_callback = restore_callback
        self.upload_callback = upload_callback
        self.upload_staging_dir = Path(upload_staging_dir) if upload_staging_dir else None
        self.backups_provider = backups_provider
        self.world_download_callback = world_download_callback
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        provider = self.status_provider
        health = self.health_provider
        game_name = self.game_name
        ui_theme = self.ui_theme
        toolbox = self.log_toolbox
        capture_cb = self.capture_callback
        update_cb = self.update_callback
        restore_cb = self.restore_callback
        upload_cb = self.upload_callback
        upload_dir = self.upload_staging_dir
        backups_cb = self.backups_provider
        world_dl_cb = self.world_download_callback

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
                LOG.debug("%s - %s", self.address_string(), fmt % args)

            def _peer_allowed(self) -> bool:
                # Under Home Assistant, Ingress + watchdog come from Supervisor.
                # Outside HA (Portainer/Docker), allow all peers.
                if not os.environ.get("SUPERVISOR_TOKEN"):
                    return True
                peer = self.client_address[0]
                return peer == INGRESS_PEER

            def _ingress_base(self) -> str:
                raw = (self.headers.get("X-Ingress-Path") or "").strip()
                if not raw:
                    return "/"
                if not raw.startswith("/"):
                    raw = "/" + raw
                return raw.rstrip("/") + "/"

            def _send(
                self,
                code: int,
                body: bytes,
                content_type: str,
                headers: dict[str, str] | None = None,
            ) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                if headers:
                    for key, value in headers.items():
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, payload: Any) -> None:
                body = json.dumps(payload, indent=2, default=str).encode("utf-8")
                self._send(code, body, "application/json; charset=utf-8")

            def _send_file(
                self,
                path: Path,
                *,
                filename: str,
                content_type: str,
            ) -> None:
                data_path = Path(path)
                size = data_path.stat().st_size
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or "download"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{safe_name}"',
                )
                self.end_headers()
                with data_path.open("rb") as fh:
                    shutil.copyfileobj(fh, self.wfile, length=1024 * 1024)

            def do_POST(self) -> None:  # noqa: N802
                if not self._peer_allowed():
                    self._send(403, b"forbidden\n", "text/plain; charset=utf-8")
                    return
                path = urlparse(self.path).path
                if path == "/api/logs/capture":
                    if capture_cb is None:
                        self._json(501, {"error": "log capture unavailable"})
                        return
                    self._json(200, capture_cb("manual"))
                    return
                if path == "/api/update":
                    if update_cb is None:
                        self._json(501, {"ok": False, "error": "manual update unavailable"})
                        return
                    result = update_cb()
                    self._json(200 if result.get("ok") else 409, result)
                    return
                if path == "/api/world/upload":
                    if upload_cb is None or upload_dir is None:
                        self._json(
                            501, {"ok": False, "error": "world upload unavailable"}
                        )
                        return
                    parsed = urlparse(self.path)
                    query = parse_qs(parsed.query)
                    if not _as_confirm_flag((query.get("confirm") or [""])[0]):
                        self._json(
                            400,
                            {
                                "ok": False,
                                "error": (
                                    "Could not confirm the upload request. "
                                    "Try again from OPEN WEB UI."
                                ),
                            },
                        )
                        return
                    length_header = self.headers.get("Content-Length")
                    if length_header is None or str(length_header).strip() == "":
                        self._json(
                            411,
                            {
                                "ok": False,
                                "error": (
                                    "Content-Length required for world upload "
                                    "(Ingress must forward the file body)"
                                ),
                            },
                        )
                        return
                    try:
                        length = int(length_header)
                    except (TypeError, ValueError):
                        length = -1
                    if length <= 0:
                        self._json(
                            400, {"ok": False, "error": "empty world upload"}
                        )
                        return
                    # Hard cap: 8 GiB. Disk free is still checked by backup manager.
                    max_upload = 8 * 1024 * 1024 * 1024
                    if length > max_upload:
                        self._json(
                            413,
                            {
                                "ok": False,
                                "error": f"upload too large (max {max_upload} bytes)",
                            },
                        )
                        return
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                    filename = (query.get("filename") or ["world-upload.bin"])[0]
                    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)
                    safe = safe.strip("._") or "world-upload.bin"
                    staged = upload_dir / f"upload-pending-{stamp}-{safe}"
                    tmp = staged.with_suffix(staged.suffix + ".partial")
                    remaining = length
                    try:
                        with tmp.open("wb") as out:
                            while remaining > 0:
                                chunk = self.rfile.read(min(1024 * 1024, remaining))
                                if not chunk:
                                    break
                                out.write(chunk)
                                remaining -= len(chunk)
                        if remaining != 0:
                            tmp.unlink(missing_ok=True)
                            self._json(
                                400,
                                {
                                    "ok": False,
                                    "error": "upload ended before Content-Length bytes",
                                },
                            )
                            return
                        tmp.replace(staged)
                    except OSError as exc:
                        tmp.unlink(missing_ok=True)
                        staged.unlink(missing_ok=True)
                        self._json(
                            500, {"ok": False, "error": f"failed to stage upload: {exc}"}
                        )
                        return
                    try:
                        result = upload_cb(staged)
                    except Exception as exc:  # noqa: BLE001
                        staged.unlink(missing_ok=True)
                        self._json(
                            500, {"ok": False, "error": f"upload schedule failed: {exc}"}
                        )
                        return
                    if not result.get("ok"):
                        staged.unlink(missing_ok=True)
                    self._json(200 if result.get("ok") else 409, result)
                    return
                if path == "/api/backups/restore":
                    if restore_cb is None:
                        self._json(
                            501, {"ok": False, "error": "restore unavailable"}
                        )
                        return
                    parsed = urlparse(self.path)
                    query = parse_qs(parsed.query)
                    try:
                        payload = _parse_json_object(_read_http_body(self))
                    except ValueError as exc:
                        self._json(400, {"ok": False, "error": str(exc)})
                        return
                    # Prefer JSON body; fall back to query string when Ingress
                    # delivers an empty body (common when Content-Length is lost).
                    if "archive" not in payload and "name" not in payload:
                        archive_q = (query.get("archive") or [""])[0]
                        if archive_q:
                            payload["archive"] = archive_q
                    if "empty" not in payload and (query.get("empty") or [""])[0]:
                        payload["empty"] = (query.get("empty") or [""])[0]
                    if "confirm" not in payload and (query.get("confirm") or [""])[0]:
                        payload["confirm"] = (query.get("confirm") or [""])[0]

                    archive = str(
                        payload.get("archive") or payload.get("name") or ""
                    ).strip()
                    empty_raw = payload.get("empty")
                    empty = bool(empty_raw) and str(empty_raw).strip().lower() not in {
                        "0",
                        "false",
                        "no",
                        "off",
                        "",
                    }
                    if not _as_confirm_flag(payload.get("confirm")):
                        self._json(
                            400,
                            {
                                "ok": False,
                                "error": (
                                    "Could not confirm the restore request. "
                                    "Try again from OPEN WEB UI."
                                ),
                            },
                        )
                        return
                    if empty and archive:
                        self._json(
                            400,
                            {
                                "ok": False,
                                "error": "pass either empty:true or an archive name, not both",
                            },
                        )
                        return
                    if empty:
                        result = restore_cb(EMPTY_WORLD)
                        self._json(200 if result.get("ok") else 409, result)
                        return
                    if not archive:
                        self._json(
                            400,
                            {
                                "ok": False,
                                "error": "missing archive name (or set empty:true)",
                            },
                        )
                        return
                    result = restore_cb(archive)
                    self._json(200 if result.get("ok") else 409, result)
                    return
                self._json(404, {"error": "not found"})

            def do_GET(self) -> None:  # noqa: N802
                if not self._peer_allowed():
                    self._send(403, b"forbidden\n", "text/plain; charset=utf-8")
                    return
                parsed = urlparse(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)

                if path in ("/healthz", "/health"):
                    # Cheap path: avoid full status() disk/manifest scans.
                    snapshot = health() if health is not None else provider()
                    ok = healthz_ok(snapshot)
                    payload = b"ok\n" if ok else b"degraded\n"
                    self._send(200 if ok else 503, payload, "text/plain; charset=utf-8")
                    return

                status = provider()

                if path in ("/api/status", "/status.json"):
                    self._json(200, status)
                    return

                if path == "/api/ui":
                    self._json(200, _ui_view(status, game_name, ui_theme=ui_theme))
                    return

                if path == "/api/backups":
                    if backups_cb is not None:
                        archives = backups_cb()
                    else:
                        archives = (status.get("backups") or {}).get("restorable") or []
                    self._json(200, {"archives": archives})
                    return

                if path == "/api/world/download":
                    if world_dl_cb is None:
                        self._json(
                            501, {"error": "world save download unavailable"}
                        )
                        return
                    info = world_dl_cb()
                    if not info:
                        self._json(
                            404, {"error": "world save not available for download"}
                        )
                        return
                    file_path = Path(str(info["path"]))
                    cleanup = info.get("cleanup_path")
                    try:
                        self._send_file(
                            file_path,
                            filename=str(info.get("filename") or file_path.name),
                            content_type=str(
                                info.get("content_type") or "application/octet-stream"
                            ),
                        )
                    finally:
                        if cleanup:
                            Path(str(cleanup)).unlink(missing_ok=True)
                    return

                if path == "/api/logs":
                    monitor = status.get("monitor") or {}
                    self._json(
                        200,
                        {
                            "recent_lines": monitor.get("recent_lines") or [],
                            "highlighted_lines": monitor.get("highlighted_lines") or [],
                            "captures": status.get("log_captures") or [],
                            "log_patterns": status.get("log_patterns") or {},
                        },
                    )
                    return

                if path == "/api/logs/patterns":
                    self._json(200, status.get("log_patterns") or {})
                    return

                if path == "/api/logs/raw":
                    lines = int((query.get("lines") or ["400"])[0])
                    as_text = (query.get("format") or ["json"])[0].lower() == "text"
                    if toolbox is None:
                        if as_text:
                            self._send(
                                501,
                                b"log toolbox unavailable\n",
                                "text/plain; charset=utf-8",
                            )
                        else:
                            self._json(501, {"error": "log toolbox unavailable"})
                        return
                    payload = toolbox.raw_tail(lines=lines)
                    if as_text:
                        lines_out = list(payload.get("lines") or [])
                        label = (
                            payload.get("source_label")
                            or payload.get("source")
                            or "unknown"
                        )
                        header = f"# {label}\n"
                        if not lines_out and payload.get("empty_hint"):
                            body = header + "\n" + str(payload["empty_hint"]) + "\n"
                        else:
                            text = "\n".join(lines_out)
                            body = header + "\n" + text + ("\n" if text else "")
                        self._send(
                            200,
                            body.encode("utf-8"),
                            "text/plain; charset=utf-8",
                        )
                    else:
                        self._json(200, payload)
                    return

                if path == "/api/logs/suggest":
                    if toolbox is None:
                        self._json(501, {"error": "log toolbox unavailable"})
                        return
                    self._json(200, toolbox.suggest())
                    return

                if path == "/api/logs/capture":
                    # GET must not mutate state (CSRF / link-prefetch hazard).
                    self._json(
                        405,
                        {
                            "error": "Use POST /api/logs/capture to create a capture",
                        },
                    )
                    return

                if path == "/api/logs/captures":
                    if toolbox is None:
                        self._json(501, {"error": "log toolbox unavailable"})
                        return
                    self._json(200, {"captures": toolbox.list_captures()})
                    return

                if path.startswith("/api/logs/captures/") and path.endswith("/download"):
                    if toolbox is None:
                        self._json(501, {"error": "log toolbox unavailable"})
                        return
                    capture_id = path[len("/api/logs/captures/") : -len("/download")]
                    archive = toolbox.capture_archive_path(capture_id)
                    if archive is None:
                        self._json(404, {"error": "capture not found"})
                        return
                    data = archive.read_bytes()
                    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", capture_id) or "capture"
                    self._send(
                        200,
                        data,
                        "application/gzip",
                        headers={
                            "Content-Disposition": (
                                f'attachment; filename="{safe_name}.tar.gz"'
                            )
                        },
                    )
                    return

                if path in ("/", "/index.html", "/ingress"):
                    view = _ui_view(status, game_name, ui_theme=ui_theme)
                    html = render_status_html(
                        view, base_href=self._ingress_base()
                    ).encode("utf-8")
                    self._send(200, html, "text/html; charset=utf-8")
                    return

                self._send(404, b"not found\n", "text/plain; charset=utf-8")

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="status-http", daemon=True
        )
        self._thread.start()
        LOG.info("Status HTTP listening on %s:%s", self.host, self.port)

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None


def _fmt_seconds(value: Any) -> str:
    try:
        total = int(value)
    except (TypeError, ValueError):
        return "0s"
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _fmt_ago(timestamp: Any, *, now: float | None = None) -> str:
    """Human relative time like '12m ago' / '3d ago' from a unix timestamp."""

    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return "unknown"
    if ts <= 0:
        return "unknown"
    age = max(0, int((now if now is not None else time.time()) - ts))
    if age < 45:
        return "just now"
    if age < 3600:
        minutes = max(1, age // 60)
        return f"{minutes}m ago"
    if age < 86400:
        hours = max(1, age // 3600)
        return f"{hours}h ago"
    if age < 86400 * 14:
        days = max(1, age // 86400)
        return f"{days}d ago"
    if age < 86400 * 60:
        weeks = max(1, age // (86400 * 7))
        return f"{weeks}w ago"
    months = max(1, age // (86400 * 30))
    return f"{months}mo ago"


def _format_subtitle(status: dict[str, Any]) -> str:
    version = str(status.get("app_version") or app_version())
    steamcmd_ver = str(status.get("steamcmd_version") or "").strip()
    subtitle = f"Dedicated server supervisor v{version}"
    if steamcmd_ver:
        subtitle += f" · SteamCMD {steamcmd_ver}"
    return subtitle


def _format_game_version(status: dict[str, Any]) -> tuple[str, str, str]:
    """Return (human version, steam build hint, installed-ago hint)."""

    monitor = status.get("monitor") or {}
    version = str(
        status.get("game_version") or monitor.get("game_version") or ""
    ).strip()
    if not version:
        version = "unknown"
    build = str(status.get("local_build_id") or "").strip()
    build_hint = f"Steam build {build}" if build else ""
    install_ts = status.get("install_last_updated_at")
    applied_ts = status.get("last_update_applied_at")
    if install_ts:
        installed_hint = f"Installed {_fmt_ago(install_ts)}"
    elif applied_ts:
        installed_hint = f"Installed {_fmt_ago(applied_ts)}"
    else:
        installed_hint = ""
    return version, build_hint, installed_hint


def _format_uptime(status: dict[str, Any]) -> tuple[str, str]:
    if status.get("running"):
        value = _fmt_seconds(status.get("game_uptime_seconds", 0))
    else:
        value = "—"
    reason = str(status.get("last_start_reason") or "boot")
    if reason == "crash":
        hint = "Since crash restart"
    elif reason in ("update", "update_failed"):
        hint = "Since server update"
    elif reason in ("restore", "restore_failed"):
        hint = "Since world restore"
    else:
        hint = "Since first start"
    return value, hint


def _format_crashes_hint(status: dict[str, Any]) -> str:
    supervisor = _fmt_seconds(status.get("supervisor_uptime_seconds", 0))
    return f"Supervisor uptime: {supervisor}"


def _format_backups(status: dict[str, Any]) -> tuple[str, str, str]:
    """Return (count, oldest hint, newest hint)."""

    info = status.get("backups") or {}
    try:
        count = int(info.get("archive_count") if info.get("archive_count") is not None else 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        # Fall back to archive name list if summary fields are absent.
        archives = info.get("archives") or []
        count = len(archives) if isinstance(archives, list) else 0
    if count <= 0:
        return "0", "No backups yet", ""
    oldest_at = info.get("oldest_backup_at")
    newest_at = info.get("newest_backup_at")
    oldest = (
        f"Oldest: {_fmt_ago(oldest_at)}"
        if oldest_at
        else "Oldest: unknown"
    )
    newest = (
        f"Newest: {_fmt_ago(newest_at)}"
        if newest_at
        else "Newest: unknown"
    )
    return str(count), oldest, newest


def _format_update_check_hint(status: dict[str, Any]) -> str:
    checked_at = status.get("last_update_check_at")
    interval = int(status.get("auto_update_interval_minutes") or 0)
    check_hour = status.get("auto_update_check_hour")
    error = status.get("last_update_error")
    if checked_at:
        hint = f"Checked {_fmt_ago(checked_at)}"
        if status.get("update_pending") and status.get("update_reason"):
            hint += f" · {status.get('update_reason')}"
        elif error and not status.get("update_pending"):
            # Keep this short; full error remains in status JSON.
            hint += " · last check had an error"
        return hint
    if interval <= 0:
        return "Steam checks disabled"
    if check_hour is not None:
        try:
            hour = max(0, min(23, int(check_hour)))
        except (TypeError, ValueError):
            hour = 5
        return f"Next Steam check around {hour:02d}:00 local"
    return "Not checked yet"


def _format_disk(status: dict[str, Any]) -> tuple[str, str, str]:
    """Return (value, css class, hint) for free disk under the backup volume."""

    info = status.get("disk") or {}
    free = info.get("free_mb")
    ok = bool(info.get("ok"))
    try:
        free_mb = float(free) if free is not None else None
    except (TypeError, ValueError):
        free_mb = None
    if free_mb is None:
        return "Unknown", "", ""
    if free_mb >= 1024:
        value = f"{free_mb / 1024:.1f} GiB"
    else:
        value = f"{free_mb:.0f} MiB"
    # Min free threshold is enforced for backups/updates; omit from the hero card.
    return value, ("good" if ok else "bad"), ""


def _format_backup_options(status: dict[str, Any]) -> str:
    info = status.get("backups") or {}
    archives = info.get("restorable") or []
    options: list[str] = []
    if isinstance(archives, list):
        for item in archives:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            kind = str(item.get("kind") or "backup")
            mtime = item.get("mtime")
            age = _fmt_ago(mtime) if mtime else "unknown age"
            label = f"{name} ({kind}, {age})"
            options.append(
                f'<option value="{_html_escape(name)}">{_html_escape(label)}</option>'
            )
    if not options:
        options.append('<option value="">No backups yet</option>')
    options.append(
        f'<option value="{_html_escape(EMPTY_WORLD)}">NEW WORLD</option>'
    )
    return "\n".join(options)


def _format_world_save(status: dict[str, Any]) -> tuple[str, str]:
    """Return (size value, hint HTML). Hint may be a download link."""

    info = status.get("world_save") or {}
    raw_bytes = info.get("bytes")
    try:
        size = int(raw_bytes or 0)
    except (TypeError, ValueError):
        size = 0
    label = str(info.get("label") or "").strip()
    scope = str(info.get("scope") or "")
    if size <= 0 and scope == "missing":
        if label:
            return "—", _html_escape(f"Waiting for {label}")
        return "—", "No world save found yet"
    value = format_bytes(size)
    if scope == "named_path" and label:
        hint_text = label
    elif scope == "backup_sources":
        hint_text = label or "World data directory"
    elif label:
        hint_text = label
    else:
        hint_text = "World data"
    if bool(info.get("downloadable")) and size > 0:
        return (
            value,
            f'<a href="api/world/download">{_html_escape(hint_text)}</a>',
        )
    return value, _html_escape(hint_text)


def _format_world_upload(status: dict[str, Any]) -> tuple[str, str, str]:
    """Return (hint, accept attribute, row css class) for upload restore UI."""

    info = status.get("world_save") or {}
    uploadable = bool(info.get("uploadable"))
    hint = str(info.get("hint") or "").strip()
    accept = str(info.get("accept") or "").strip()
    if not uploadable:
        return (
            hint
            or "World upload is unavailable until the game plugin declares a named save path.",
            "",
            "hidden",
        )
    return hint, accept or ".zip,application/zip", ""


def _format_running(status: dict[str, Any]) -> tuple[str, str]:
    """Hero server label from lifecycle (falls back to running bool)."""

    phase = str(status.get("lifecycle") or "").strip()
    # Restore/update stop the game first; surface that while it is still up.
    if phase == "restoring":
        if status.get("running"):
            return "stopping for restore", "accent"
        return "restoring world", "accent"
    if phase == "updating":
        if status.get("running"):
            return "stopping for update", "accent"
        return "updating", "accent"
    labels = {
        "running": ("running", "good"),
        "installing": ("installing", "accent"),
        "waiting": ("waiting", "accent"),
        "starting": ("starting", "accent"),
        "stopping": ("stopping", "accent"),
        "failed": ("failed", "bad"),
        "stopped": ("stopped", "bad"),
    }
    if phase in labels:
        return labels[phase]
    if status.get("running"):
        return "running", "good"
    return "stopped", "bad"


def _ui_view(
    status: dict[str, Any],
    game_name: str,
    *,
    ui_theme: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Formatted strings for the status page and soft-refresh JSON."""

    monitor = status.get("monitor") or {}
    log_patterns = status.get("log_patterns") or {}
    patterns = log_patterns.get("patterns") or []
    has_active = any((item.get("mode") or "") == "active" for item in patterns)
    active_categories = _active_pattern_categories(patterns)
    highlights = _format_highlights(
        monitor.get("highlighted_lines") or [],
        active_categories=active_categories,
    )
    players_known = bool(monitor.get("players_known"))
    tracking_mode = str(status.get("player_tracking_mode") or "count").strip().lower()
    presence_mode = tracking_mode == "presence"
    if presence_mode:
        players_label = "Players"
        if players_known:
            present = monitor.get("players_present")
            if present is None:
                count = monitor.get("player_count")
                present = None if count is None else int(count) > 0
            players = "Players Active" if present else "Idle"
            players_hint = "From join / leave / empty-server patterns"
        else:
            players = "—"
            players_hint = "Unknown until presence patterns hit"
    else:
        players_label = "Number of players"
        players = str(monitor.get("player_count")) if players_known else "—"
        players_hint = (
            "From active join/leave patterns"
            if players_known
            else "Unknown until player patterns are promoted"
        )
    debug_mode = bool(status.get("debug_mode"))
    # Count mode: show the numeric card when an active player_count pattern exists
    # (or debug). Presence mode: show Idle/Players Active when any player-tracking
    # category is active (join/leave/empty/count).
    has_active_player_count = "player_count" in active_categories
    has_active_presence = bool(
        active_categories
        & {"player_join", "player_leave", "players_empty", "player_count"}
    )
    if presence_mode:
        players_card_hidden = (not debug_mode) and (not has_active_presence)
    else:
        players_card_hidden = (not debug_mode) and (not has_active_player_count)
    log_watch_hidden = not debug_mode
    uptime, uptime_hint = _format_uptime(status)
    game_version, game_version_build, game_version_installed = _format_game_version(
        status
    )
    backups, backups_oldest, backups_newest = _format_backups(status)
    world_save, world_save_hint = _format_world_save(status)
    world_upload_hint, world_upload_accept, world_upload_class = _format_world_upload(
        status
    )
    disk, disk_class, disk_hint = _format_disk(status)
    running_label, running_class = _format_running(status)
    theme = resolve_ui_theme(ui_theme)
    view: dict[str, Any] = {
        "game": game_name,
        "subtitle": _format_subtitle(status),
        "running": running_label,
        "running_class": running_class,
        "players_label": players_label,
        "players": players,
        "players_hint": players_hint,
        "players_card_class": "hidden" if players_card_hidden else "",
        "players_card_hidden": players_card_hidden,
        "uptime": uptime,
        "uptime_hint": uptime_hint,
        "game_version": game_version,
        "game_version_build": game_version_build,
        "game_version_installed": game_version_installed,
        "update_pending": "yes" if status.get("update_pending") else "no",
        "update_check_hint": _format_update_check_hint(status),
        "backups": backups,
        "backups_oldest": backups_oldest,
        "backups_newest": backups_newest,
        "crashes": int(status.get("crash_count") or 0),
        "crashes_hint": _format_crashes_hint(status),
        "world_save": world_save,
        "world_save_hint": world_save_hint,
        "world_upload_hint": world_upload_hint,
        "world_upload_accept": world_upload_accept,
        "world_upload_class": world_upload_class,
        "world_upload_hidden": world_upload_class == "hidden",
        "disk": disk,
        "disk_class": disk_class,
        "disk_hint": disk_hint,
        # Collapse once any active pattern exists (setup complete enough).
        "log_watch_open": "" if has_active else " open",
        "log_watch_class": "hidden" if log_watch_hidden else "",
        "log_watch_hidden": log_watch_hidden,
        "pattern_rows": _format_pattern_rows(patterns),
        "highlights": highlights,
        "capture_options": _format_capture_options(status.get("log_captures") or []),
        "backup_options": _format_backup_options(status),
        "empty_world_token": EMPTY_WORLD,
    }
    for key in UI_THEME_KEYS:
        view[f"theme_{key}"] = theme[key]
    return view


_STATUS_HTML_KEYS = (
    "game",
    "subtitle",
    "running",
    "running_class",
    "players_label",
    "players",
    "players_hint",
    "players_card_class",
    "uptime",
    "uptime_hint",
    "game_version",
    "game_version_build",
    "game_version_installed",
    "update_pending",
    "update_check_hint",
    "backups",
    "backups_oldest",
    "backups_newest",
    "crashes",
    "crashes_hint",
    "world_save",
    "world_save_hint",
    "world_upload_hint",
    "world_upload_accept",
    "world_upload_class",
    "disk",
    "disk_class",
    "disk_hint",
    "log_watch_open",
    "log_watch_class",
    "pattern_rows",
    "highlights",
    "capture_options",
    "backup_options",
    "empty_world_token",
) + tuple(f"theme_{key}" for key in UI_THEME_KEYS)


def render_status_html(view: dict[str, Any], *, base_href: str = "/") -> str:
    """Render the Ingress status page from a ``_ui_view`` dict.

    Kept as a pure function so unit tests exercise the same ``str.format``
    path the HTTP handler uses (catches unescaped ``{...}`` in the template).
    """

    theme = resolve_ui_theme(
        {key: str(view.get(f"theme_{key}") or "") for key in UI_THEME_KEYS}
    )
    return HTML_PAGE.format(
        base_href=_html_escape(base_href),
        game=_html_escape(view["game"]),
        subtitle=_html_escape(view["subtitle"]),
        running=_html_escape(view["running"]),
        running_class=_html_escape(view["running_class"]),
        players_label=_html_escape(view.get("players_label") or "Number of players"),
        players=_html_escape(view["players"]),
        players_hint=_html_escape(view["players_hint"]),
        players_card_class=_html_escape(view.get("players_card_class") or ""),
        uptime=_html_escape(view["uptime"]),
        uptime_hint=_html_escape(view["uptime_hint"]),
        game_version=_html_escape(view["game_version"]),
        game_version_build=_html_escape(view["game_version_build"]),
        game_version_installed=_html_escape(view["game_version_installed"]),
        update_pending=_html_escape(view["update_pending"]),
        update_check_hint=_html_escape(view["update_check_hint"]),
        backups=_html_escape(str(view["backups"])),
        backups_oldest=_html_escape(view["backups_oldest"]),
        backups_newest=_html_escape(view["backups_newest"]),
        crashes=_html_escape(str(view["crashes"])),
        crashes_hint=_html_escape(view["crashes_hint"]),
        world_save=_html_escape(view["world_save"]),
        # Hint may include a download <a>; _format_world_save already escapes text.
        world_save_hint=view["world_save_hint"],
        world_upload_hint=_html_escape(view.get("world_upload_hint") or ""),
        world_upload_accept=_html_escape(view.get("world_upload_accept") or ""),
        world_upload_class=_html_escape(view.get("world_upload_class") or ""),
        disk=_html_escape(view["disk"]),
        disk_class=_html_escape(view["disk_class"]),
        disk_hint=_html_escape(view["disk_hint"]),
        log_watch_open=view["log_watch_open"],
        log_watch_class=_html_escape(view.get("log_watch_class") or ""),
        pattern_rows=view["pattern_rows"],
        highlights=_html_escape(view["highlights"]),
        capture_options=view["capture_options"],
        backup_options=view["backup_options"],
        empty_world_token=_html_escape(view.get("empty_world_token") or EMPTY_WORLD),
        theme_bg=_html_escape(theme["bg"]),
        theme_panel=_html_escape(theme["panel"]),
        theme_ink=_html_escape(theme["ink"]),
        theme_muted=_html_escape(theme["muted"]),
        theme_accent=_html_escape(theme["accent"]),
        theme_good=_html_escape(theme["good"]),
        theme_bad=_html_escape(theme["bad"]),
        theme_glow=_html_escape(theme["glow"]),
        theme_wash=_html_escape(theme["wash"]),
        theme_depth=_html_escape(theme["depth"]),
    )


def _active_pattern_categories(patterns: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("category") or "")
        for item in patterns
        if (item.get("mode") or "") == "active" and item.get("category")
    }


_RECENT_MATCH_LIMIT = 5


def _recent_matches_for_pattern(item: dict[str, Any]) -> list[str]:
    """Up to 5 newest matching lines for one regex (newest first)."""

    recent = item.get("recent_lines")
    lines: list[str]
    if isinstance(recent, list) and recent:
        lines = [str(x) for x in recent if str(x).strip()]
    elif item.get("last_line"):
        lines = [str(item.get("last_line"))]
    else:
        lines = []
    # Deque stores oldest→newest; present newest first.
    return list(reversed(lines[-_RECENT_MATCH_LIMIT:]))


def _format_recent_matches_cell(item: dict[str, Any]) -> str:
    """Render up to 5 newest hits for a single regex."""

    parts: list[str] = []
    seen: set[str] = set()
    for line in _recent_matches_for_pattern(item):
        text = strip_ansi(line).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        if len(text) > 160:
            text = text[:160] + "…"
        parts.append(f"<div>{_html_escape(text)}</div>")
    if not parts:
        return ""
    return f"<div class='recent-matches'>{''.join(parts)}</div>"


def _format_pattern_snippet(pattern: str, *, limit: int = 72) -> str:
    text = str(pattern or "").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return _html_escape(text)


def _format_pattern_rows(patterns: list[dict[str, Any]]) -> str:
    """One table row per regex so broad dry-run guesses stay visible.

    Do not collapse or hide dry-run peers when an active pattern exists —
    over-matching candidates are how we discover promotions.
    """

    if not patterns:
        return "<tr><td colspan='5'>(no patterns configured)</td></tr>"

    ordered = sorted(
        patterns,
        key=lambda item: (
            0 if int(item.get("hits") or 0) else 1,
            0 if (item.get("mode") or "") == "active" else 1,
            str(item.get("category") or ""),
            -int(item.get("hits") or 0),
            str(item.get("pattern") or ""),
        ),
    )
    rows = []
    for item in ordered[:120]:
        mode = item.get("mode") or "dry_run"
        stale = (
            " <span class='tag stale'>stale</span>"
            if item.get("stale") and int(item.get("hits") or 0) > 0
            else ""
        )
        recent = _format_recent_matches_cell(item)
        rows.append(
            "<tr>"
            f"<td><span class='tag {mode}'>{mode}</span>{stale}</td>"
            f"<td>{_html_escape(str(item.get('category') or ''))}</td>"
            f"<td class='pattern-cell' title='{_html_escape(str(item.get('pattern') or ''))}'>"
            f"{_format_pattern_snippet(str(item.get('pattern') or ''))}</td>"
            f"<td>{int(item.get('hits') or 0)}</td>"
            f"<td>{recent}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _format_highlights(
    items: list[dict[str, Any]],
    *,
    active_categories: set[str] | None = None,
) -> str:
    del active_categories  # kept for call-site compatibility; dry-runs stay visible
    if not items:
        return (
            "(no pattern hits yet — once the server is online, dry_run candidates "
            "should light up lines like “server started” or “player joined”)"
        )
    lines = []
    for item in items[-30:]:
        matches = list(item.get("matches") or [])
        if not matches:
            continue
        tags = ", ".join(
            f"{m.get('mode')}:{m.get('category')}" for m in matches[:8]
        )
        lines.append(f"[{tags}] {strip_ansi(str(item.get('line') or ''))}")
    if not lines:
        return "(no pattern hits to show yet)"
    return "\n".join(lines)


def _format_capture_options(captures: list[dict[str, Any]]) -> str:
    if not captures:
        return '<option value="">No captures yet</option>'
    options = []
    for item in captures[:40]:
        href = str(item.get("download_path") or "").lstrip("/")
        label = f"{item.get('id')} · {item.get('reason')}"
        options.append(
            f'<option value="{_html_escape(href)}">{_html_escape(label)}</option>'
        )
    return "\n".join(options)
