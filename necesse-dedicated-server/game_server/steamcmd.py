"""SteamCMD install / update helpers with retries and build-id comparison."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .plugin import GamePlugin
from .steam_gate import get_gate

LOG = logging.getLogger("game_server.steamcmd")

# SteamCMD often returns this on a cold/partial appcache; retrying (sometimes
# after clearing appinfo.vdf, or with a platform override) usually succeeds.
MISSING_CONFIG_MARKERS = (
    "missing configuration",
    "missing app configuration",
)


class SteamCMDError(RuntimeError):
    pass


def _run_streaming(
    cmd: list[str],
    *,
    timeout: float,
    prefix: str = "[steamcmd]",
    env: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Run a command, streaming stdout/stderr line-by-line into HA Logs."""

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    lines: list[str] = []

    def _reader() -> None:
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                text = raw.rstrip("\n")
                lines.append(text)
                LOG.info("%s %s", prefix, text)
        finally:
            proc.stdout.close()

    reader = threading.Thread(target=_reader, name="steamcmd-stdout", daemon=True)
    reader.start()
    try:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            raise
    finally:
        reader.join(timeout=30)
    return int(proc.returncode or 0), "\n".join(lines)


def steamcmd_bin(steamcmd_dir: str | Path) -> Path:
    path = Path(steamcmd_dir) / "steamcmd.sh"
    if not path.is_file():
        raise SteamCMDError(f"steamcmd.sh not found at {path}")
    return path


def looks_missing_configuration(output: str) -> bool:
    text = (output or "").lower()
    return any(marker in text for marker in MISSING_CONFIG_MARKERS)


def steam_home_dir() -> Path:
    raw = (os.environ.get("STEAM_HOME") or "").strip()
    if raw:
        return Path(raw)
    return Path("/data/steam-home")


def prepare_steam_env(install_dir: str | Path) -> dict[str, str]:
    """Point SteamCMD at a persistent HOME and ensure steamapps exists."""

    install_dir = Path(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / "steamapps").mkdir(parents=True, exist_ok=True)

    home = steam_home_dir()
    home.mkdir(parents=True, exist_ok=True)
    (home / "Steam").mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home)
    # Avoid SteamCMD locale warnings when the image provides en_US.UTF-8.
    env.setdefault("LANG", os.environ.get("LANG") or "en_US.UTF-8")
    env.setdefault("LC_ALL", env["LANG"])
    return env


def clear_steam_appcache(env: dict[str, str] | None = None) -> None:
    """Drop Steam appinfo cache files that commonly cause Missing configuration."""

    homes: list[Path] = []
    if env and env.get("HOME"):
        homes.append(Path(env["HOME"]))
    homes.append(steam_home_dir())
    homes.append(Path("/root"))
    homes.append(Path.home())

    seen: set[Path] = set()
    removed = 0
    for home in homes:
        for relative in (
            Path("Steam/appcache/appinfo.vdf"),
            Path(".steam/appcache/appinfo.vdf"),
            Path("Steam/appcache/packageinfo.vdf"),
        ):
            path = (home / relative).resolve()
            if path in seen:
                continue
            seen.add(path)
            if path.is_file():
                try:
                    path.unlink()
                    removed += 1
                    LOG.info("Cleared Steam appcache file %s", path)
                except OSError:
                    LOG.warning("Could not remove %s", path, exc_info=True)
    if removed == 0:
        LOG.info("No Steam appcache files to clear")


def manifest_path(install_dir: str | Path, app_id: int) -> Path | None:
    candidates = [
        Path(install_dir) / "steamapps" / f"appmanifest_{app_id}.acf",
        Path(install_dir).parent / "steamapps" / f"appmanifest_{app_id}.acf",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def read_local_build_id(install_dir: str | Path, app_id: int) -> str | None:
    path = manifest_path(install_dir, app_id)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'"buildid"\s+"(\d+)"', text)
    return match.group(1) if match else None


def fetch_remote_build_id(
    steamcmd_dir: str | Path,
    plugin: GamePlugin,
    *,
    stop_event: threading.Event | None = None,
) -> str | None:
    gate = get_gate()
    cmd = [
        str(steamcmd_bin(steamcmd_dir)),
        "+login",
        plugin.steam_login,
    ]
    if plugin.steam_login != "anonymous" and plugin.steam_password:
        cmd.append(plugin.steam_password)
    cmd.extend(
        [
            "+app_info_update",
            "1",
            "+app_info_print",
            str(plugin.steam_app_id),
            "+quit",
        ]
    )
    env = prepare_steam_env(Path(os.environ.get("INSTALL_DIR") or "/data/game"))
    try:
        with gate.session("app_info", stop_event=stop_event):
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
    except InterruptedError:
        LOG.info("Remote build id query cancelled by stop")
        return None
    except subprocess.TimeoutExpired:
        LOG.warning("Timed out querying remote build id")
        gate.note_failure("timeout", kind="app_info")
        return None

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    # Prefer the public branch buildid when present
    branch = re.escape(plugin.steam_branch)
    branch_match = re.search(
        rf'"{branch}"\s*\{{.*? "buildid"\s+"(\d+)"',
        output,
        re.DOTALL | re.IGNORECASE,
    )
    if branch_match:
        gate.note_success(kind="app_info")
        return branch_match.group(1)
    match = re.search(r'"buildid"\s+"(\d+)"', output)
    if match:
        gate.note_success(kind="app_info")
        return match.group(1)

    if looks_missing_configuration(output):
        gate.note_failure(output, kind="app_info", transient=True)
    else:
        gate.note_failure(output, kind="app_info")
    LOG.warning("Could not parse remote build id from SteamCMD output")
    return None


def server_installed(install_dir: str | Path, marker_relative: str | None = None) -> bool:
    root = Path(install_dir)
    if not root.is_dir():
        return False
    if marker_relative:
        marker = root / marker_relative
        return marker.exists()
    # Without a plugin marker, only treat a non-empty install dir as present.
    try:
        return any(root.iterdir())
    except OSError:
        return False


def _build_app_update_cmd(
    steamcmd_dir: str | Path,
    install_dir: str | Path,
    plugin: GamePlugin,
    *,
    validate: bool,
    platform: str,
) -> list[str]:
    """Build a SteamCMD argv using CLI +args (more reliable than +runscript)."""

    cmd = [
        str(steamcmd_bin(steamcmd_dir)),
        "+@ShutdownOnFailedCommand",
        "1",
        "+@NoPromptForPassword",
        "1",
    ]
    platform = (platform or "").strip().lower()
    if platform in {"windows", "linux", "macos"}:
        cmd.extend(["+@sSteamCmdForcePlatformType", platform])

    # Valve: force_install_dir must come before login.
    cmd.extend(["+force_install_dir", str(install_dir)])

    if plugin.steam_login == "anonymous":
        cmd.extend(["+login", "anonymous"])
    else:
        login = ["+login", plugin.steam_login]
        if plugin.steam_password:
            login.append(plugin.steam_password)
        cmd.extend(login)

    # Refresh app info before update; reduces cold-cache "Missing configuration".
    cmd.extend(["+app_info_update", "1"])

    update = f"{plugin.steam_app_id}"
    cmd.extend(["+app_update", update])
    if plugin.steam_branch and plugin.steam_branch != "public":
        cmd.extend(["-beta", plugin.steam_branch])
    if validate:
        cmd.append("validate")
    cmd.append("+quit")
    return cmd


def _install_strategies(
    plugin: GamePlugin, *, validate: bool
) -> list[dict[str, object]]:
    """Ordered install strategies for flaky first-start SteamCMD failures.

    Kept short: SteamGate hard-caps retries at 3, and HA start timeout is ~300s.
    """

    preferred = (plugin.steam_platform or "").strip().lower()
    primary = preferred  # "" means native depot selection
    alternate = "windows" if primary != "windows" else "linux"

    def _entry(platform: str, use_validate: bool, clear_cache: bool) -> dict[str, object]:
        label_parts = [
            f"platform={platform or 'native'}",
            f"validate={use_validate}",
        ]
        if clear_cache:
            label_parts.insert(0, "clear_cache")
        return {
            "platform": platform,
            "validate": use_validate,
            "clear_cache": clear_cache,
            "label": " ".join(label_parts),
        }

    strategies = [
        # Normal path: preferred/native platform with requested validate flag.
        _entry(primary, validate, False),
        # Cold/partial appcache is the usual cause of "Missing configuration".
        _entry(primary, validate, True),
        # Platform depot fallback (Java servers often ship a Windows depot).
        _entry(alternate, validate, True),
    ]
    if validate:
        # Last-resort variant if callers raise the retry budget.
        strategies.append(_entry(primary, False, True))
    return strategies


def install_or_update(
    steamcmd_dir: str | Path,
    install_dir: str | Path,
    plugin: GamePlugin,
    *,
    retries: int = 3,
    retry_delay_seconds: int | None = None,
    validate: bool | None = None,
    stop_event: threading.Event | None = None,
) -> str | None:
    """Run SteamCMD app_update with strategy rotation and gated retries.

    Returns new local build id. Never spins tightly against Steam: attempts are
    serialized through the process-wide SteamGate with spacing + cooldowns.
    Transient "Missing configuration" failures use short spacing so a fresh
    Home Assistant start can still finish inside the supervisor start timeout.
    """

    gate = get_gate()
    retries = gate.clamp_retries(retries)
    install_dir = Path(install_dir)
    validate = plugin.validate_on_update if validate is None else validate
    env = prepare_steam_env(install_dir)
    strategies = _install_strategies(plugin, validate=validate)

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        if stop_event is not None and stop_event.is_set():
            raise SteamCMDError("Stopped before SteamCMD install/update")

        strategy = strategies[(attempt - 1) % len(strategies)]
        platform = str(strategy["platform"] or "")
        use_validate = bool(strategy["validate"])
        clear_cache = bool(strategy["clear_cache"])

        LOG.info(
            "SteamCMD install/update attempt %s/%s for app %s (%s)",
            attempt,
            retries,
            plugin.steam_app_id,
            strategy["label"],
        )
        if clear_cache:
            clear_steam_appcache(env)

        cmd = _build_app_update_cmd(
            steamcmd_dir,
            install_dir,
            plugin,
            validate=use_validate,
            platform=platform,
        )
        combined = ""
        transient = False
        try:
            with gate.session("app_update", stop_event=stop_event):
                returncode, combined = _run_streaming(cmd, timeout=3600, env=env)
            success_markers = (
                "Success! App '%s' fully installed" % plugin.steam_app_id,
                "Success! App '%s' already up to date" % plugin.steam_app_id,
            )
            # SteamCMD sometimes returns non-zero even on success (state 0x6 etc.)
            looks_ok = any(marker in combined for marker in success_markers) or (
                returncode == 0
                and read_local_build_id(install_dir, plugin.steam_app_id)
            )
            if looks_ok or (
                returncode == 0
                and server_installed(install_dir, plugin.install_marker)
            ):
                build_id = read_local_build_id(install_dir, plugin.steam_app_id)
                LOG.info("SteamCMD succeeded (buildid=%s)", build_id or "unknown")
                gate.note_success(kind="app_update")
                return build_id

            LOG.warning(
                "SteamCMD attempt %s failed (exit %s). Tail:\n%s",
                attempt,
                returncode,
                "\n".join(combined.splitlines()[-40:]),
            )
            last_error = SteamCMDError(f"SteamCMD failed with exit {returncode}")
            transient = looks_missing_configuration(combined)
            gate.note_failure(combined, kind="app_update", transient=transient)
        except InterruptedError as exc:
            raise SteamCMDError("Stopped while waiting for Steam gate") from exc
        except subprocess.TimeoutExpired as exc:
            LOG.warning("SteamCMD timed out on attempt %s", attempt)
            last_error = exc
            gate.note_failure("timeout", kind="app_update")
        except Exception as exc:  # noqa: BLE001
            LOG.exception("SteamCMD attempt %s raised", attempt)
            last_error = exc
            gate.note_failure(str(exc), kind="app_update")

        # Rate-limit style failures: do not burn remaining retries immediately.
        if gate.looks_rate_limited(combined) or gate.cooldown_remaining() >= 600:
            LOG.error(
                "Aborting remaining SteamCMD retries due to cooldown/rate-limit "
                "(remaining=%.0fs)",
                gate.cooldown_remaining(),
            )
            break

        if attempt < retries:
            if transient:
                delay = max(
                    float(gate.policy.transient_spacing_seconds),
                    gate.cooldown_remaining(),
                )
            else:
                delay = gate.retry_delay_seconds(attempt)
                if retry_delay_seconds is not None:
                    delay = max(delay, float(retry_delay_seconds))
                delay = max(delay, gate.cooldown_remaining())
            LOG.info("Backing off %.0fs before SteamCMD retry", delay)
            # Interruptible sleep
            deadline = time.time() + delay
            while time.time() < deadline:
                if stop_event is not None and stop_event.is_set():
                    raise SteamCMDError("Stopped during SteamCMD backoff")
                time.sleep(min(5.0, deadline - time.time()))

    if server_installed(install_dir, plugin.install_marker) or server_installed(
        install_dir
    ):
        LOG.error(
            "SteamCMD failed after retries; keeping existing install. Last error: %s",
            last_error,
        )
        return read_local_build_id(install_dir, plugin.steam_app_id)

    raise SteamCMDError(
        f"SteamCMD failed to install app {plugin.steam_app_id} after {retries} attempts: {last_error}"
    )


def update_available(
    steamcmd_dir: str | Path,
    install_dir: str | Path,
    plugin: GamePlugin,
    *,
    stop_event: threading.Event | None = None,
) -> tuple[bool, str | None, str | None]:
    local = read_local_build_id(install_dir, plugin.steam_app_id)
    remote = fetch_remote_build_id(steamcmd_dir, plugin, stop_event=stop_event)
    if remote is None:
        return False, local, remote
    if local is None:
        return True, local, remote
    return local != remote, local, remote


def ensure_steamcmd(steamcmd_dir: str | Path) -> None:
    """Download SteamCMD if the directory is empty / missing steamcmd.sh."""

    steamcmd_dir = Path(steamcmd_dir)
    steamcmd_dir.mkdir(parents=True, exist_ok=True)
    marker = steamcmd_dir / "steamcmd.sh"
    if marker.is_file():
        return

    LOG.info("Downloading SteamCMD into %s", steamcmd_dir)
    import tarfile
    import urllib.request

    url = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
    archive = steamcmd_dir / "steamcmd_linux.tar.gz"
    urllib.request.urlretrieve(url, archive)  # noqa: S310 - trusted Valve CDN
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(steamcmd_dir)
    archive.unlink(missing_ok=True)
    if not marker.is_file():
        raise SteamCMDError("SteamCMD download did not produce steamcmd.sh")
    os.chmod(marker, 0o755)
