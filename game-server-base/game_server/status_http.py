"""Status + log-capture HTTP server for Ingress / browser use (no SSH needed)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .disk import format_bytes
from .log_bridge import strip_ansi
from .version import app_version

LOG = logging.getLogger("game_server.status_http")

# Home Assistant Ingress proxy source address (Supervisor).
INGRESS_PEER = "172.30.32.2"


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <base href="{base_href}" />
  <title>{game} server status</title>
  <style>
    :root {{
      --bg: #12201a;
      --panel: #1c3027;
      --ink: #e7f0ea;
      --muted: #9bb5a6;
      --accent: #d4a25a;
      --good: #6fbf8a;
      --bad: #d9786a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, #243f33 0%, transparent 40%),
        linear-gradient(160deg, #0e1814, var(--bg) 55%, #1a1710);
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
      border: 1px solid rgba(155,181,166,0.2);
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
    .actions a, .actions button {{
      display: inline-block;
      padding: 0.45rem 0.75rem;
      border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
      background: transparent;
      color: var(--accent);
      text-decoration: none;
      font: inherit;
      cursor: pointer;
    }}
    .capture-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      align-items: center;
      margin: 0.5rem 0 1rem;
    }}
    select {{
      background: rgba(0,0,0,0.28);
      color: var(--ink);
      border: 1px solid rgba(155,181,166,0.35);
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
      border-bottom: 1px solid rgba(155,181,166,0.18);
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .tag {{
      display: inline-block;
      padding: 0.1rem 0.35rem;
      border: 1px solid rgba(155,181,166,0.35);
      margin-right: 0.25rem;
      font-size: 0.72rem;
    }}
    .tag.active {{ border-color: var(--good); color: var(--good); }}
    .tag.dry_run {{ border-color: var(--accent); color: var(--accent); }}
    .tag.stale {{ border-color: var(--bad); color: var(--bad); }}
    .warn {{ color: var(--accent); }}
    code {{ color: var(--ink); }}
  </style>
</head>
<body>
  <main>
    <h1>{game}</h1>
    <p class="sub" id="subtitle">{subtitle}</p>
    <div class="grid" id="status-grid">
      <div class="stat"><div class="label">Server</div><div class="value {running_class}" id="v-running">{running}</div></div>
      <div class="stat">
        <div class="label">Number of players</div>
        <div class="value" id="v-players">{players}</div>
        <div class="hint" id="h-players">{players_hint}</div>
      </div>
      <div class="stat">
        <div class="label">Uptime</div>
        <div class="value" id="v-uptime">{uptime}</div>
        <div class="hint" id="h-uptime">{uptime_hint}</div>
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
        <div class="label">Backups</div>
        <div class="value" id="v-backups">{backups}</div>
        <div class="hint" id="h-backups-oldest">{backups_oldest}</div>
        <div class="hint" id="h-backups-newest">{backups_newest}</div>
      </div>
      <div class="stat">
        <div class="label">Game server crashes</div>
        <div class="value" id="v-crashes">{crashes}</div>
        <div class="hint" id="h-crashes">{crashes_hint}</div>
      </div>
      <div class="stat">
        <div class="label">World save</div>
        <div class="value" id="v-world">{world_save}</div>
        <div class="hint" id="h-world">{world_save_hint}</div>
      </div>
      <div class="stat">
        <div class="label">Free disk</div>
        <div class="value {disk_class}" id="v-disk">{disk}</div>
        <div class="hint" id="h-disk">{disk_hint}</div>
      </div>
    </div>
    <p class="sub warn" id="update-players-note">{update_players_note}</p>

    <h2>World backups</h2>
    <p class="sub">
      Restore replaces the live world. The current world is saved first as a
      pre-restore safety copy kept outside normal backup rotation.
    </p>
    <div class="capture-row">
      <label for="backup-select">Saved backups</label>
      <select id="backup-select">{backup_options}</select>
      <button type="button" id="btn-restore" onclick="return restoreBackup(event)">
        Restore selected backup
      </button>
    </div>

    <details class="log-watch"{log_watch_open}>
      <summary>Game server log watching pattern hits</summary>
      <p class="sub">
        <span class="tag active">active</span> can trigger updates/player state.
        <span class="tag dry_run">dry_run</span> only highlights candidates for promotion.
        <span class="tag stale">stale</span> means a pattern used to hit but has not recently.
      </p>
      <table>
        <thead>
          <tr><th>Mode</th><th>Category</th><th>Hits</th><th>Pattern</th><th>Last line</th></tr>
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
      <a href="api/logs/raw?lines=400&amp;format=text">View raw log tail</a>
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
        <li><a href="api/backups">Backups list JSON</a></li>
        <li>POST <code>api/backups/restore</code> — restore selected archive</li>
        <li><a href="api/logs/patterns">Pattern hit report</a></li>
        <li><a href="api/logs/suggest">Suggest patterns from recent logs</a></li>
        <li><a href="api/logs/captures">Captures list JSON</a></li>
        <li><a href="api/logs/raw?lines=400">Raw log tail JSON</a></li>
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
      const ok = window.confirm(
        'Restore this backup over the live world?\\n\\n' +
        name + '\\n\\n' +
        'The game server will stop. The current world is saved first as a ' +
        'pre-restore safety copy (kept outside normal backup rotation), then ' +
        'the selected backup replaces the world and the server restarts.\\n\\n' +
        'Anyone playing will be disconnected.'
      );
      if (!ok) return false;
      const btn = document.getElementById('btn-restore');
      if (btn) btn.disabled = true;
      try {{
        const res = await fetch('api/backups/restore', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ archive: name }}),
        }});
        const data = await res.json();
        if (data.ok) {{
          alert(data.message || 'Restore scheduled.');
          softRefresh();
        }} else {{
          alert(data.error || 'Could not schedule restore.');
        }}
      }} catch (e) {{
        alert('Could not schedule restore.');
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
        setText('v-players', u.players);
        setText('h-players', u.players_hint);
        setText('v-uptime', u.uptime);
        setText('h-uptime', u.uptime_hint);
        setText('v-game-version', u.game_version);
        setText('h-game-version-build', u.game_version_build);
        setText('h-game-version-installed', u.game_version_installed);
        setText('v-update', u.update_pending);
        setText('h-update', u.update_check_hint);
        setText('v-backups', u.backups);
        setText('h-backups-oldest', u.backups_oldest);
        setText('h-backups-newest', u.backups_newest);
        setText('v-crashes', u.crashes);
        setText('h-crashes', u.crashes_hint);
        setText('v-world', u.world_save);
        setText('h-world', u.world_save_hint);
        const disk = document.getElementById('v-disk');
        if (disk) {{
          disk.textContent = u.disk;
          disk.className = 'value ' + (u.disk_class || '');
        }}
        setText('h-disk', u.disk_hint);
        setText('update-players-note', u.update_players_note);
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
        game_name: str = "Game",
        log_toolbox=None,
        capture_callback: Callable[[str], dict[str, Any]] | None = None,
        restore_callback: Callable[[str], dict[str, Any]] | None = None,
        backups_provider: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.status_provider = status_provider
        self.game_name = game_name
        self.log_toolbox = log_toolbox
        self.capture_callback = capture_callback
        self.restore_callback = restore_callback
        self.backups_provider = backups_provider
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        provider = self.status_provider
        game_name = self.game_name
        toolbox = self.log_toolbox
        capture_cb = self.capture_callback
        restore_cb = self.restore_callback
        backups_cb = self.backups_provider

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
                if path == "/api/backups/restore":
                    if restore_cb is None:
                        self._json(
                            501, {"ok": False, "error": "restore unavailable"}
                        )
                        return
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    try:
                        payload = json.loads(raw.decode("utf-8") or "{}")
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        self._json(400, {"ok": False, "error": "invalid JSON body"})
                        return
                    if not isinstance(payload, dict):
                        self._json(400, {"ok": False, "error": "expected JSON object"})
                        return
                    archive = str(
                        payload.get("archive") or payload.get("name") or ""
                    ).strip()
                    if not archive:
                        self._json(
                            400, {"ok": False, "error": "missing archive name"}
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
                status = provider()

                if path in ("/healthz", "/health"):
                    ok = bool(status.get("running")) or bool(status.get("starting"))
                    payload = b"ok\n" if ok else b"degraded\n"
                    self._send(200 if ok else 503, payload, "text/plain; charset=utf-8")
                    return

                if path in ("/api/status", "/status.json"):
                    self._json(200, status)
                    return

                if path == "/api/ui":
                    self._json(200, _ui_view(status, game_name))
                    return

                if path == "/api/backups":
                    if backups_cb is not None:
                        archives = backups_cb()
                    else:
                        archives = (status.get("backups") or {}).get("restorable") or []
                    self._json(200, {"archives": archives})
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
                        text = "\n".join(payload.get("lines") or [])
                        header = f"# source: {payload.get('source') or 'unknown'}\n\n"
                        self._send(
                            200,
                            (header + text + ("\n" if text else "")).encode("utf-8"),
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
                    if capture_cb is None:
                        self._json(501, {"error": "log capture unavailable"})
                        return
                    self._json(200, capture_cb("manual"))
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
                    self._send(
                        200,
                        data,
                        "application/gzip",
                        headers={
                            "Content-Disposition": f'attachment; filename="{capture_id}.tar.gz"'
                        },
                    )
                    return

                if path in ("/", "/index.html", "/ingress"):
                    view = _ui_view(status, game_name)
                    html = HTML_PAGE.format(
                        game=_html_escape(view["game"]),
                        base_href=_html_escape(self._ingress_base()),
                        subtitle=_html_escape(view["subtitle"]),
                        running=_html_escape(view["running"]),
                        running_class=_html_escape(view["running_class"]),
                        players=_html_escape(view["players"]),
                        players_hint=_html_escape(view["players_hint"]),
                        uptime=_html_escape(view["uptime"]),
                        uptime_hint=_html_escape(view["uptime_hint"]),
                        game_version=_html_escape(view["game_version"]),
                        game_version_build=_html_escape(view["game_version_build"]),
                        game_version_installed=_html_escape(
                            view["game_version_installed"]
                        ),
                        update_pending=_html_escape(view["update_pending"]),
                        update_check_hint=_html_escape(view["update_check_hint"]),
                        backups=_html_escape(str(view["backups"])),
                        backups_oldest=_html_escape(view["backups_oldest"]),
                        backups_newest=_html_escape(view["backups_newest"]),
                        crashes=_html_escape(str(view["crashes"])),
                        crashes_hint=_html_escape(view["crashes_hint"]),
                        world_save=_html_escape(view["world_save"]),
                        world_save_hint=_html_escape(view["world_save_hint"]),
                        disk=_html_escape(view["disk"]),
                        disk_class=_html_escape(view["disk_class"]),
                        disk_hint=_html_escape(view["disk_hint"]),
                        update_players_note=_html_escape(view["update_players_note"]),
                        log_watch_open=view["log_watch_open"],
                        pattern_rows=view["pattern_rows"],
                        highlights=_html_escape(view["highlights"]),
                        capture_options=view["capture_options"],
                        backup_options=view["backup_options"],
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


def _format_install_updated(status: dict[str, Any]) -> tuple[str, str]:
    """Return (value, hint) for when game server files were last updated on disk."""

    install_ts = status.get("install_last_updated_at")
    applied_ts = status.get("last_update_applied_at")
    build = status.get("local_build_id")
    if install_ts:
        value = _fmt_ago(install_ts)
        hint = (
            f"Steam build {build} (game server files)"
            if build
            else "From Steam install stamp"
        )
        return value, hint
    if applied_ts:
        value = _fmt_ago(applied_ts)
        hint = (
            f"Supervisor last applied · build {build}"
            if build
            else "Supervisor last applied an update"
        )
        return value, hint
    if build:
        return "Unknown age", f"Steam build {build} (game server files)"
    return "Unknown", "No Steam install stamp yet"


def _format_disk(status: dict[str, Any]) -> tuple[str, str, str]:
    """Return (value, css class, hint) for free disk under the backup volume."""

    info = status.get("disk") or {}
    free = info.get("free_mb")
    minimum = info.get("min_free_disk_mb")
    ok = bool(info.get("ok"))
    try:
        free_mb = float(free) if free is not None else None
    except (TypeError, ValueError):
        free_mb = None
    try:
        min_mb = int(minimum) if minimum is not None else 0
    except (TypeError, ValueError):
        min_mb = 0
    if free_mb is None:
        return "Unknown", "", f"Min {min_mb} MiB"
    if free_mb >= 1024:
        value = f"{free_mb / 1024:.1f} GiB"
    else:
        value = f"{free_mb:.0f} MiB"
    hint = f"Min {min_mb} MiB free required"
    return value, ("good" if ok else "bad"), hint


def _format_backup_options(status: dict[str, Any]) -> str:
    info = status.get("backups") or {}
    archives = info.get("restorable") or []
    if not isinstance(archives, list) or not archives:
        return '<option value="">No backups yet</option>'
    options: list[str] = []
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
        return '<option value="">No backups yet</option>'
    return "\n".join(options)


def _format_world_save(status: dict[str, Any]) -> tuple[str, str]:
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
            return "—", f"Waiting for {label}"
        return "—", "No world save found yet"
    value = format_bytes(size)
    if scope == "named_path" and label:
        return value, label
    if scope == "heuristic" and label:
        return value, f"{label} (heuristic)"
    if scope == "backup_sources":
        return value, label or "World data directory"
    if label:
        return value, label
    return value, "World data"


def _ui_view(status: dict[str, Any], game_name: str) -> dict[str, Any]:
    """Formatted strings for the status page and soft-refresh JSON."""

    monitor = status.get("monitor") or {}
    patterns = (status.get("log_patterns") or {}).get("patterns") or []
    has_active = any((item.get("mode") or "") == "active" for item in patterns)
    active_categories = _active_pattern_categories(patterns)
    highlights = _format_highlights(
        monitor.get("highlighted_lines") or [],
        active_categories=active_categories,
    )
    players_known = monitor.get("players_known")
    players = str(monitor.get("player_count")) if players_known else "—"
    players_hint = (
        "From active join/leave patterns"
        if players_known
        else "Unknown until player patterns are promoted"
    )
    waits = status.get("waits_for_empty_server") or status.get("player_gating")
    if waits in ("no_player_tracking", "inactive_no_active_patterns"):
        update_players_note = (
            "Updates will not wait for players to leave until join/leave "
            "log patterns are promoted from dry-run highlights into the "
            "game plugin. Steam still checks for newer builds on its schedule."
        )
    else:
        update_players_note = (
            "When a newer build is available, the restart waits until nobody "
            "is online so players are not interrupted."
        )
    uptime, uptime_hint = _format_uptime(status)
    game_version, game_version_build, game_version_installed = _format_game_version(
        status
    )
    backups, backups_oldest, backups_newest = _format_backups(status)
    world_save, world_save_hint = _format_world_save(status)
    disk, disk_class, disk_hint = _format_disk(status)
    return {
        "game": game_name,
        "subtitle": _format_subtitle(status),
        "running": "running" if status.get("running") else "stopped",
        "running_class": "good" if status.get("running") else "bad",
        "players": players,
        "players_hint": players_hint,
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
        "disk": disk,
        "disk_class": disk_class,
        "disk_hint": disk_hint,
        "update_players_note": update_players_note,
        # Collapse once any active pattern exists (setup complete enough).
        "log_watch_open": "" if has_active else " open",
        "pattern_rows": _format_pattern_rows(patterns),
        "highlights": highlights,
        "capture_options": _format_capture_options(status.get("log_captures") or []),
        "backup_options": _format_backup_options(status),
    }


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _active_pattern_categories(patterns: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("category") or "")
        for item in patterns
        if (item.get("mode") or "") == "active" and item.get("category")
    }


def _format_pattern_rows(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return "<tr><td colspan='5'>(no patterns configured)</td></tr>"
    active_categories = _active_pattern_categories(patterns)
    # Hide dry-run rows once that category already has an active pattern.
    visible = [
        item
        for item in patterns
        if not (
            (item.get("mode") or "") == "dry_run"
            and str(item.get("category") or "") in active_categories
        )
    ]
    if not visible:
        return "<tr><td colspan='5'>(no patterns to show)</td></tr>"
    ordered = sorted(
        visible,
        key=lambda item: (
            0 if item.get("hits") else 1,
            0 if item.get("mode") == "active" else 1,
            str(item.get("category") or ""),
            -int(item.get("hits") or 0),
        ),
    )
    rows = []
    for item in ordered[:60]:
        mode = item.get("mode") or "dry_run"
        stale = " <span class='tag stale'>stale</span>" if item.get("stale") else ""
        last = item.get("last_line") or ""
        if len(last) > 140:
            last = last[:140] + "…"
        rows.append(
            "<tr>"
            f"<td><span class='tag {mode}'>{mode}</span>{stale}</td>"
            f"<td>{_html_escape(str(item.get('category') or ''))}</td>"
            f"<td>{int(item.get('hits') or 0)}</td>"
            f"<td><code>{_html_escape(str(item.get('pattern') or ''))}</code></td>"
            f"<td>{_html_escape(strip_ansi(last))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _format_highlights(
    items: list[dict[str, Any]],
    *,
    active_categories: set[str] | None = None,
) -> str:
    if not items:
        return (
            "(no pattern hits yet — once the server is online, dry_run candidates "
            "should light up lines like “Started server…” or “empty server”)"
        )
    active = active_categories or set()
    lines = []
    for item in items[-30:]:
        matches = []
        for match in item.get("matches") or []:
            mode = str(match.get("mode") or "")
            category = str(match.get("category") or "")
            if mode == "dry_run" and category in active:
                continue
            matches.append(match)
        if not matches:
            continue
        tags = ", ".join(
            f"{m.get('mode')}:{m.get('category')}" for m in matches[:6]
        )
        lines.append(f"[{tags}] {strip_ansi(str(item.get('line') or ''))}")
    if not lines:
        return "(no pattern hits to show after hiding superseded dry-run matches)"
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
