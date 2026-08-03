"""Launch and supervise the game server process with crash restarts."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

from .config import SupervisorConfig, format_bool
from .plugin import GamePlugin

LOG = logging.getLogger("game_server.process")


class ProcessManager:
    def __init__(
        self,
        plugin: GamePlugin,
        config: SupervisorConfig,
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        self.plugin = plugin
        self.config = config
        self.on_line = on_line
        self.proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self.restart_count = 0
        self.crash_count = 0
        self.intentional_stop = False
        self.last_exit_code: int | None = None
        self.last_started_at: float | None = None
        self.last_stopped_at: float | None = None
        self._crash_times: deque[float] = deque(maxlen=100)
        self._reader: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def build_command(self) -> list[str]:
        cmd = list(self.plugin.executable)
        # Expand JAVA_OPTS style tokens before the jar if present
        java_opts = str(self.config.game_options.get("java_opts") or os.environ.get("JAVA_OPTS") or "")
        if java_opts and cmd and cmd[0] == "java":
            opts = [part for part in java_opts.split() if part]
            cmd = [cmd[0], *opts, *cmd[1:]]

        options = dict(self.config.game_options)
        # Allow plugin defaults for data/logs dirs via options override
        if "data_dir" not in options:
            options["data_dir"] = self.plugin.data_dir
        if "logs_dir" not in options:
            options["logs_dir"] = self.plugin.logs_dir

        for option_key, flag in self.plugin.arg_map.items():
            if option_key not in options:
                continue
            value = options[option_key]
            if value is None or value == "":
                continue
            if isinstance(value, bool) or (
                isinstance(value, str)
                and value.lower() in {"true", "false", "1", "0", "yes", "no"}
            ):
                rendered = format_bool(value, self.plugin.bool_style)
            else:
                rendered = str(value)
            if flag.endswith("="):
                cmd.append(f"{flag}{rendered}")
            else:
                cmd.extend([flag, rendered])
        return cmd

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self.intentional_stop = False
            workdir = Path(
                self.config.game_options.get("working_dir")
                or self.config.install_dir
                or self.plugin.working_dir
            )
            workdir.mkdir(parents=True, exist_ok=True)
            Path(self.plugin.data_dir).mkdir(parents=True, exist_ok=True)
            Path(self.plugin.logs_dir).mkdir(parents=True, exist_ok=True)

            cmd = self.build_command()
            env = os.environ.copy()
            env.update(self.plugin.env)
            LOG.info("Starting server: %s (cwd=%s)", " ".join(cmd), workdir)
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(workdir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self.last_started_at = time.time()
            self.restart_count += 1
            self._reader = threading.Thread(
                target=self._read_output, name="game-stdout", daemon=True
            )
            self._reader.start()

    def _read_output(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            text = line.rstrip("\n")
            LOG.info("[game] %s", text)
            if self.on_line:
                try:
                    self.on_line(text)
                except Exception:  # noqa: BLE001
                    LOG.exception("on_line callback failed")

    def stop(self, timeout: float = 30.0) -> None:
        with self._lock:
            self.intentional_stop = True
            proc = self.proc
        if proc is None:
            return
        if proc.poll() is None:
            LOG.info("Stopping server pid=%s", proc.pid)
            try:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                LOG.warning("Server did not exit after SIGTERM; killing")
                proc.kill()
                proc.wait(timeout=10)
            except ProcessLookupError:
                pass
        self.last_exit_code = proc.returncode
        self.last_stopped_at = time.time()
        with self._lock:
            self.proc = None

    def wait(self, timeout: float | None = None) -> int | None:
        proc = self.proc
        if proc is None:
            return self.last_exit_code
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        self.last_exit_code = code
        self.last_stopped_at = time.time()
        if not self.intentional_stop and code not in (0, None):
            self.crash_count += 1
            self._crash_times.append(time.time())
            LOG.error("Server exited unexpectedly with code %s", code)
        with self._lock:
            if self.proc is proc:
                self.proc = None
        return code

    def crashes_in_last_hour(self) -> int:
        cutoff = time.time() - 3600
        return sum(1 for ts in self._crash_times if ts >= cutoff)

    def can_restart_after_crash(self) -> bool:
        if not self.config.restart_on_crash:
            return False
        return self.crashes_in_last_hour() < self.config.max_crash_restarts_per_hour

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "restart_count": self.restart_count,
            "crash_count": self.crash_count,
            "crashes_last_hour": self.crashes_in_last_hour(),
            "last_exit_code": self.last_exit_code,
            "last_started_at": self.last_started_at,
            "last_stopped_at": self.last_stopped_at,
            "command": self.build_command(),
        }
