"""Status + log-capture HTTP server for Ingress / browser use (no SSH needed)."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

LOG = logging.getLogger("game_server.status_http")


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="20" />
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
  </style>
</head>
<body>
  <main>
    <h1>{game}</h1>
    <p class="sub">Dedicated server supervisor · no SSH needed for logs</p>
    <div class="grid">
      <div class="stat"><div class="label">Server</div><div class="value {running_class}">{running}</div></div>
      <div class="stat"><div class="label">Players</div><div class="value">{players}</div></div>
      <div class="stat"><div class="label">Uptime</div><div class="value">{uptime}</div></div>
      <div class="stat"><div class="label">Restarts</div><div class="value">{restarts}</div></div>
      <div class="stat"><div class="label">Crashes</div><div class="value">{crashes}</div></div>
      <div class="stat"><div class="label">Build</div><div class="value accent">{build}</div></div>
      <div class="stat"><div class="label">Update pending</div><div class="value">{update_pending}</div></div>
      <div class="stat"><div class="label">Version mismatches</div><div class="value">{mismatches}</div></div>
    </div>

    <h2>Log tools</h2>
    <div class="actions">
      <a href="/api/logs/capture" onclick="return postCapture(event)">Capture logs now</a>
      <a href="/api/logs/suggest">Suggest patterns</a>
      <a href="/api/logs/raw?lines=400">Raw log tail</a>
      <a href="/api/logs/captures">List captures</a>
      <a href="/api/status">Status JSON</a>
    </div>
    <p class="sub">Captures land under <code>/data/supervisor/captures</code> and are downloadable as tar.gz.</p>
    <ul>{captures}</ul>

    <h2>Recent output</h2>
    <pre>{recent}</pre>
  </main>
  <script>
    async function postCapture(ev) {{
      ev.preventDefault();
      const res = await fetch('/api/logs/capture', {{ method: 'POST' }});
      const data = await res.json();
      if (data.download_path) {{
        window.location = data.download_path;
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
                path = urlparse(self.path).path
                if path == "/api/logs/capture":
                    if capture_cb is None:
                        self._json(501, {"error": "log capture unavailable"})
                        return
                    self._json(200, capture_cb("manual"))
                    return
                self._json(404, {"error": "not found"})

            def do_GET(self) -> None:  # noqa: N802
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
                            "captures": status.get("log_captures") or [],
                        },
                    )
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
                    recent = (
                        "\n".join((monitor.get("recent_lines") or [])[-40:])
                        or "(no log lines yet)"
                    )
                    captures = status.get("log_captures") or []
                    capture_items = []
                    for item in captures[:8]:
                        capture_items.append(
                            f'<li><a href="{item.get("download_path")}">{item.get("id")}</a>'
                            f' · {item.get("reason")}</li>'
                        )
                    html = HTML_PAGE.format(
                        game=game_name,
                        running="running" if status.get("running") else "stopped",
                        running_class="good" if status.get("running") else "bad",
                        players=monitor.get("player_count", 0),
                        uptime=_fmt_seconds(status.get("supervisor_uptime_seconds", 0)),
                        restarts=status.get("restart_count", 0),
                        crashes=status.get("crash_count", 0),
                        build=status.get("local_build_id") or "unknown",
                        update_pending="yes" if status.get("update_pending") else "no",
                        mismatches=monitor.get("version_mismatch_count", 0),
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
