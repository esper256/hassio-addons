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
from .log_bridge import STDOUT_DEDUPER, strip_ansi
from .plugin import GamePlugin

LOG = logging.getLogger("game_server.process")

_SECRET_OPTION_MARKERS = ("password", "secret", "token", "api_key")
_SECRET_FLAGS = frozenset({"-password", "--password", "-passwd", "--passwd"})


def redact_command(cmd: list[str], plugin: GamePlugin | None = None) -> list[str]:
    """Return argv with secret flag values replaced by ``***``.

    Used for status JSON and logs so a passwordless Ingress page cannot leak
    the game join password via ``process.command``.
    """

    secret_flags = set(_SECRET_FLAGS)
    if plugin is not None:
        for option_key, flag in plugin.arg_map.items():
            key = str(option_key).lower()
            if any(marker in key for marker in _SECRET_OPTION_MARKERS):
                secret_flags.add(str(flag))
                if str(flag).endswith("="):
                    secret_flags.add(str(flag))

    redacted: list[str] = []
    hide_next = False
    for part in cmd:
        text = str(part)
        if hide_next:
            redacted.append("***")
            hide_next = False
            continue
        matched_eq = False
        for flag in secret_flags:
            if flag.endswith("=") and text.startswith(flag):
                redacted.append(f"{flag}***")
                matched_eq = True
                break
        if matched_eq:
            continue
        if text in secret_flags:
            redacted.append(text)
            hide_next = True
            continue
        redacted.append(text)
    return redacted


class ProcessManager:
    def __init__(
        self,
        plugin: GamePlugin,
        config: SupervisorConfig,
        on_line: Callable[[str], None] | None = None,
        *,
        run_uid: int | None = None,
        run_gid: int | None = None,
    ) -> None:
        self.plugin = plugin
        self.config = config
        self.on_line = on_line
        self.run_uid = run_uid
        self.run_gid = run_gid
        self.proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self.start_count = 0
        self.restart_count = 0
        self.crash_count = 0
        self.intentional_stop = False
        self.last_exit_code: int | None = None
        self.last_started_at: float | None = None
        self.last_stopped_at: float | None = None
        self.last_start_reason: str | None = None
        self._crash_times: deque[float] = deque(maxlen=100)
        self._reader: threading.Thread | None = None
        self.on_line_error: str | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def build_command(self) -> list[str]:
        cmd = list(self.plugin.executable)
        java_opts = str(
            self.config.game_options.get("java_opts") or os.environ.get("JAVA_OPTS") or ""
        )
        if java_opts and cmd and cmd[0] == "java":
            opts = [part for part in java_opts.split() if part]
            cmd = [cmd[0], *opts, *cmd[1:]]

        options = dict(self.config.game_options)
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

    def _preexec(self) -> None:
        if self.run_uid is None or self.run_gid is None:
            return
        os.setgid(self.run_gid)
        os.setuid(self.run_uid)

    def start(self, reason: str = "boot") -> None:
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
            want_stdin = bool(self.plugin.stop_stdin_commands)
            if self.start_count > 0:
                self.restart_count += 1
            self.start_count += 1
            self.last_start_reason = reason
            LOG.info(
                "Starting server (%s): %s (cwd=%s, uid=%s)",
                reason,
                " ".join(redact_command(cmd, self.plugin)),
                workdir,
                self.run_uid,
            )
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(workdir),
                env=env,
                stdin=subprocess.PIPE if want_stdin else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=self._preexec if self.run_uid is not None else None,
            )
            self.last_started_at = time.time()
            self._reader = threading.Thread(
                target=self._read_output, name="game-stdout", daemon=True
            )
            self._reader.start()

    def _read_output(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            text = strip_ansi(line.rstrip("\n"))
            # Prefer process stdout over a later file-log echo of the same line.
            if STDOUT_DEDUPER.remember_if_new(text):
                LOG.info("[game] %s", text)
            if self.on_line:
                try:
                    self.on_line(text)
                except Exception as exc:  # noqa: BLE001
                    # Keep reading stdout (game logs must not stop), but do not
                    # keep invoking a broken callback forever.
                    self.on_line_error = str(exc)
                    LOG.exception(
                        "on_line callback failed; disabling further line callbacks"
                    )
                    self.on_line = None

    def stop(self, timeout: float | None = None) -> None:
        timeout = (
            float(timeout)
            if timeout is not None
            else float(
                self.config.stop_timeout_seconds or self.plugin.stop_timeout_seconds or 60
            )
        )
        with self._lock:
            self.intentional_stop = True
            proc = self.proc
        if proc is None:
            return
        if proc.poll() is None:
            LOG.info("Stopping server pid=%s gracefully", proc.pid)
            # Optional console save/exit commands before SIGTERM.
            if proc.stdin and self.plugin.stop_stdin_commands:
                try:
                    for command in self.plugin.stop_stdin_commands:
                        LOG.info("Sending stop command via stdin: %s", command)
                        proc.stdin.write(command + "\n")
                        proc.stdin.flush()
                        time.sleep(1)
                except (BrokenPipeError, OSError):
                    LOG.warning("Failed writing stop commands to stdin", exc_info=True)
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
            "start_count": self.start_count,
            "restart_count": self.restart_count,
            "last_start_reason": self.last_start_reason,
            "crash_count": self.crash_count,
            "crashes_last_hour": self.crashes_in_last_hour(),
            "last_exit_code": self.last_exit_code,
            "last_started_at": self.last_started_at,
            "last_stopped_at": self.last_stopped_at,
            "run_uid": self.run_uid,
            # Never expose raw secrets on the passwordless status surface.
            "command": redact_command(self.build_command(), self.plugin),
            "on_line_error": self.on_line_error,
        }
