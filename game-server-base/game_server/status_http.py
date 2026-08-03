"""Status + log-capture HTTP server for Ingress / browser use (no SSH needed)."""

from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .version import app_version

LOG = logging.getLogger("game_server.status_http")

# Home Assistant Ingress proxy source address (Supervisor).
INGRESS_PEER = "172.30.32.2"


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="20" />
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
    .actions a, .actions button {{
      display: inline-block;
      margin: 0.25rem 0.5rem 0.25rem 0;
      padding: 0.45rem 0.75rem;
      border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
      background: transparent;
      color: var(--accent);
      text-decoration: none;
      font: inherit;
      cursor: pointer;
    }}
    ul {{ padding-left: 1.1rem; color: var(--muted); }}
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
    <p class="sub">Dedicated server supervisor · app {app_version} · Steam build {build}</p>
    <div class="grid">
      <div class="stat"><div class="label">App version</div><div class="value accent">{app_version}</div></div>
      <div class="stat"><div class="label">Server</div><div class="value {running_class}">{running}</div></div>
      <div class="stat"><div class="label">Players</div><div class="value">{players}</div></div>
      <div class="stat"><div class="label">Player gating</div><div class="value">{player_gating}</div></div>
      <div class="stat"><div class="label">Uptime</div><div class="value">{uptime}</div></div>
      <div class="stat"><div class="label">Restarts</div><div class="value">{restarts}</div></div>
      <div class="stat"><div class="label">Crashes</div><div class="value">{crashes}</div></div>
      <div class="stat"><div class="label">Steam build</div><div class="value accent">{build}</div></div>
      <div class="stat"><div class="label">Update pending</div><div class="value">{update_pending}</div></div>
    </div>
    <p class="sub warn">{gating_note}</p>

    <h2>Log pattern hits</h2>
    <p class="sub">
      <span class="tag active">active</span> can trigger updates/player state.
      <span class="tag dry_run">dry_run</span> only highlights candidates.
      <span class="tag stale">stale</span> means a pattern used to hit but has not recently.
      JSON: <a href="api/logs/patterns">api/logs/patterns</a>
    </p>
    <table>
      <thead>
        <tr><th>Mode</th><th>Category</th><th>Hits</th><th>Pattern</th><th>Last line</th></tr>
      </thead>
      <tbody>
        {pattern_rows}
      </tbody>
    </table>

    <h2>Highlighted lines</h2>
    <pre>{highlights}</pre>

    <h2>Log tools</h2>
    <div class="actions">
      <a href="api/logs/capture" onclick="return postCapture(event)">Capture logs now</a>
      <a href="api/logs/suggest">Suggest patterns</a>
      <a href="api/logs/raw?lines=400">Raw log tail</a>
      <a href="api/logs/captures">List captures</a>
      <a href="api/status">Status JSON</a>
    </div>
    <p class="sub">Captures land under <code>/data/supervisor/captures</code> and are downloadable as tar.gz.</p>
    <ul>{captures}</ul>

    <h2>Recent output</h2>
    <pre>{recent}</pre>
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
    ) -> None:
        self.host = host
        self.port = port
        self.status_provider = status_provider
        self.game_name = game_name
        self.log_toolbox = log_toolbox
        self.capture_callback = capture_callback
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        provider = self.status_provider
        game_name = self.game_name
        toolbox = self.log_toolbox
        capture_cb = self.capture_callback

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
                    if toolbox is None:
                        self._json(501, {"error": "log toolbox unavailable"})
                        return
                    self._json(
                        200,
                        {
                            "source": str(toolbox.pick_log_file() or ""),
                            "lines": toolbox.tail_file(lines=lines),
                        },
                    )
                    return

                if path == "/api/logs/suggest":
                    if toolbox is None:
                        self._json(501, {"error": "log toolbox unavailable"})
                        return
                    self._json(200, toolbox.suggest())
                    return

                if path == "/api/logs/capture":
                    # GET convenience for simple Ingress links
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
                    monitor = status.get("monitor") or {}
                    patterns = status.get("log_patterns") or {}
                    recent = (
                        "\n".join((monitor.get("recent_lines") or [])[-40:])
                        or "(no log lines yet)"
                    )
                    highlights = _format_highlights(monitor.get("highlighted_lines") or [])
                    captures = status.get("log_captures") or []
                    capture_items = []
                    for item in captures[:8]:
                        href = str(item.get("download_path") or "").lstrip("/")
                        capture_items.append(
                            f'<li><a href="{href}">{item.get("id")}</a>'
                            f' · {item.get("reason")}</li>'
                        )
                    players_known = monitor.get("players_known")
                    player_value = (
                        str(monitor.get("player_count"))
                        if players_known
                        else "unknown"
                    )
                    gating = status.get("player_gating") or "unknown"
                    if gating == "inactive_no_active_patterns":
                        gating_note = (
                            "Alpha mode: no active player/version regexes. "
                            "Steam build updates still run; dry-run candidates only highlight logs. "
                            "Promote proven patterns into the game plugin log_patterns section."
                        )
                    else:
                        gating_note = (
                            "Active player patterns are enabled; empty-server update gating is in effect."
                        )
                    html = HTML_PAGE.format(
                        game=game_name,
                        base_href=_html_escape(self._ingress_base()),
                        app_version=_html_escape(
                            str(status.get("app_version") or app_version())
                        ),
                        running="running" if status.get("running") else "stopped",
                        running_class="good" if status.get("running") else "bad",
                        players=player_value,
                        player_gating=gating.replace("_", " "),
                        gating_note=_html_escape(gating_note),
                        uptime=_fmt_seconds(status.get("supervisor_uptime_seconds", 0)),
                        restarts=status.get("restart_count", 0),
                        crashes=status.get("crash_count", 0),
                        build=status.get("local_build_id") or "unknown",
                        update_pending="yes" if status.get("update_pending") else "no",
                        pattern_rows=_format_pattern_rows(patterns.get("patterns") or []),
                        highlights=_html_escape(highlights),
                        recent=_html_escape(recent),
                        captures="\n".join(capture_items) or "<li>No captures yet</li>",
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


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_pattern_rows(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return "<tr><td colspan='5'>(no patterns configured)</td></tr>"
    # Show hits first, then the rest, capped for readability.
    ordered = sorted(
        patterns,
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
            f"<td>{_html_escape(last)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _format_highlights(items: list[dict[str, Any]]) -> str:
    if not items:
        return "(no pattern hits yet — play a session and watch dry_run candidates light up)"
    lines = []
    for item in items[-30:]:
        matches = item.get("matches") or []
        tags = ", ".join(
            f"{m.get('mode')}:{m.get('category')}" for m in matches[:6]
        )
        lines.append(f"[{tags}] {item.get('line')}")
    return "\n".join(lines)
