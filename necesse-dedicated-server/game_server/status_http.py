"""Lightweight status HTTP server for uptime / crash / update visibility."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

LOG = logging.getLogger("game_server.status_http")


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="15" />
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
    main {{ max-width: 820px; margin: 0 auto; }}
    h1 {{
      font-family: "IBM Plex Serif", Georgia, serif;
      font-weight: 600;
      font-size: clamp(1.8rem, 4vw, 2.6rem);
      margin: 0 0 0.35rem;
      letter-spacing: -0.02em;
    }}
    .sub {{ color: var(--muted); margin-bottom: 1.75rem; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1rem;
    }}
    .stat {{
      background: color-mix(in srgb, var(--panel) 88%, black);
      border: 1px solid color-mix(in srgb, var(--muted) 25%, transparent);
      padding: 1rem 1.1rem;
    }}
    .stat .label {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 0.35rem; }}
    .stat .value {{ font-size: 1.45rem; font-weight: 600; }}
    .good {{ color: var(--good); }}
    .bad {{ color: var(--bad); }}
    .accent {{ color: var(--accent); }}
    pre {{
      margin-top: 1.5rem;
      background: rgba(0,0,0,0.28);
      padding: 1rem;
      overflow: auto;
      font-size: 0.8rem;
      line-height: 1.4;
      border: 1px solid rgba(155,181,166,0.2);
    }}
    a {{ color: var(--accent); }}
  </style>
</head>
<body>
  <main>
    <h1>{game}</h1>
    <p class="sub">Dedicated server supervisor status</p>
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
    <p class="sub" style="margin-top:1.25rem">JSON: <a href="/api/status">/api/status</a> · Health: <a href="/healthz">/healthz</a></p>
    <pre>{recent}</pre>
  </main>
</body>
</html>
"""


class StatusServer:
    def __init__(
        self,
        host: str,
        port: int,
        status_provider: Callable[[], dict[str, Any]],
        game_name: str = "Game",
    ) -> None:
        self.host = host
        self.port = port
        self.status_provider = status_provider
        self.game_name = game_name
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        provider = self.status_provider
        game_name = self.game_name

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
                LOG.debug("%s - %s", self.address_string(), fmt % args)

            def _send(self, code: int, body: bytes, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                status = provider()
                if path in ("/healthz", "/health"):
                    ok = bool(status.get("running")) or bool(status.get("starting"))
                    payload = b"ok\n" if ok else b"starting\n"
                    self._send(200 if ok else 503, payload, "text/plain; charset=utf-8")
                    return
                if path in ("/api/status", "/status.json"):
                    body = json.dumps(status, indent=2, default=str).encode("utf-8")
                    self._send(200, body, "application/json; charset=utf-8")
                    return
                if path in ("/", "/index.html", "/ingress"):
                    monitor = status.get("monitor") or {}
                    recent = "\n".join((monitor.get("recent_lines") or [])[-30:]) or "(no log lines yet)"
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
                    ).encode("utf-8")
                    self._send(200, html, "text/html; charset=utf-8")
                    return
                self._send(404, b"not found\n", "text/plain; charset=utf-8")

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="status-http", daemon=True)
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
