"""Hytale-only helpers: names, config merge, downloader, device-code scrape.

Kept outside the shared ``game_server`` package so title-specific OAuth and
paths never leak into ``game-server-base``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import IO, Any, Mapping, NamedTuple
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

INSTANCE_SALT_NAME = "instance_salt"
MACHINE_ID_NAME = "machine-id"
SERVER_NAME_PREFIX = "HAOS Hytale"
OPERATOR_ACTION_FILENAME = "operator_action.json"
DOWNLOADER = Path("/opt/hytale-downloader")
CREDENTIALS_NAME = ".hytale-downloader-credentials.json"
AUTH_ENC_NAME = "auth.enc"
GAME_ZIP_NAME = "game.zip"
INSTALL_MARKER = "Assets.zip"
AUTH_LOGIN_DEVICE = "/auth login device"
AUTH_PERSIST_ENCRYPTED = "/auth persistence Encrypted"
SIGNIN_DETAIL = (
    "Open the link in a new browser tab (not this panel). "
    "Hytale emails a login code first; after you are signed in, click the link again "
    "to reach Authorize a device. You have 10 minutes. "
    "Paste this card's device code only on that page, never into an email box."
)
DOWNLOAD_SIGNIN_DETAIL = SIGNIN_DETAIL + " First download is several gigabytes."
SERVER_SIGNIN_DETAIL = (
    "This is a second, different Hytale login after download. "
    + SIGNIN_DETAIL
    + " Hosting does not lock your client."
)
TIMEOUT_RETRY_DETAIL = (
    "The last sign-in timed out after 10 minutes (Hytale's downloader stopped waiting). "
    "A new device code is below. Sign in first, then open the link to Authorize a device. "
    "Paste this code only on that page. You have 10 minutes."
)
# 0 = keep requesting a new device code until sign-in succeeds or the app is stopped.
INSTALL_TOKEN_ATTEMPTS = 0

_URL_RE = re.compile(r"https://[^\s\"'<>]+", re.IGNORECASE)
_CODE_RE = re.compile(
    r"(?:user_code|enter code|code)\s*[=:]\s*([A-Za-z0-9][A-Za-z0-9._-]{2,31})",
    re.IGNORECASE,
)
_CODE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,31}")
# Java /auth colors the device code; CSI reset is ESC[m and must not enter user_code.
_ANSI_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|].*?(?:\x1b\\|\x07))")
# Java /auth prints "authentication successful"; the official downloader does not —
# it starts the zip fetch instead. Encrypted load means the card is not needed.
_SIGNIN_DONE_RE = re.compile(
    r"authentication successful|downloading latest|successfully downloaded"
    r"|loaded encrypted credentials",
    re.IGNORECASE,
)
_TOKEN_TIMEOUT_RE = re.compile(
    r"error obtaining token:.*context deadline exceeded",
    re.IGNORECASE,
)
# Only start /auth login device when Java says tokens are missing. Blind inject
# opens a new device flow while the server is already playable (Memory tokens).
_NEED_AUTH_RE = re.compile(
    r"no server tokens configured|use /auth login"
    r"|server session token not available|cannot request auth grant",
    re.IGNORECASE,
)
_CREDS_PERSISTED_RE = re.compile(
    r"loaded encrypted credentials|credential storage changed to:\s*encrypted",
    re.IGNORECASE,
)
_MACHINE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class TeeResult(NamedTuple):
    returncode: int
    token_wait_timed_out: bool = False


def token_wait_timed_out_line(line: str) -> bool:
    return bool(_TOKEN_TIMEOUT_RE.search(line))


def signin_finished_line(line: str) -> bool:
    return bool(_SIGNIN_DONE_RE.search(_strip_ansi(line)))


def needs_server_auth_line(line: str) -> bool:
    return bool(_NEED_AUTH_RE.search(_strip_ansi(line)))


def credentials_persisted_line(line: str) -> bool:
    return bool(_CREDS_PERSISTED_RE.search(_strip_ansi(line)))


def _valid_machine_id(text: str) -> str:
    cleaned = (text or "").strip().lower().replace("-", "")
    return cleaned if _MACHINE_ID_RE.fullmatch(cleaned) else ""


def _write_machine_id_file(path: Path, machine_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(machine_id + "\n", encoding="utf-8")
    tmp.replace(path)


def ensure_machine_id(
    *,
    state_dir: str | Path | None = None,
    etc_path: str | Path | None = None,
    dbus_path: str | Path | None = None,
) -> str:
    """Persist a 32-hex machine-id so Encrypted auth.enc survives container recreate.

    Hytale encrypts auth.enc with the Linux hardware UUID. Docker/HAOS images
    often have no /etc/machine-id (or a new one each recreate). Keep ours under
    STATE_DIR and copy it to the paths Java reads.
    """

    state = Path(state_dir or _state_dir())
    persisted = state / MACHINE_ID_NAME
    etc = Path(etc_path or "/etc/machine-id")
    dbus = Path(dbus_path or "/var/lib/dbus/machine-id")

    machine_id = ""
    if persisted.is_file():
        try:
            machine_id = _valid_machine_id(persisted.read_text(encoding="utf-8"))
        except OSError:
            machine_id = ""
    if not machine_id and etc.is_file():
        try:
            machine_id = _valid_machine_id(etc.read_text(encoding="utf-8"))
        except OSError:
            machine_id = ""
    if not machine_id and dbus.is_file():
        try:
            machine_id = _valid_machine_id(dbus.read_text(encoding="utf-8"))
        except OSError:
            machine_id = ""
    if not machine_id:
        machine_id = secrets.token_hex(16)

    try:
        existing = (
            _valid_machine_id(persisted.read_text(encoding="utf-8"))
            if persisted.is_file()
            else ""
        )
    except OSError:
        existing = ""
    if existing != machine_id:
        _write_machine_id_file(persisted, machine_id)

    for dest in (etc, dbus):
        try:
            current = (
                _valid_machine_id(dest.read_text(encoding="utf-8"))
                if dest.is_file()
                else ""
            )
            if current != machine_id:
                _write_machine_id_file(dest, machine_id)
        except OSError:
            pass
    return machine_id


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def _sanitize_device_code(raw: str) -> str:
    text = _strip_ansi(raw or "").strip()
    if not text:
        return ""
    found = _CODE_TOKEN_RE.match(text)
    return found.group(0) if found else ""


def signin_log_lines(url: str, code: str) -> list[str]:
    """HA Logs copy of the Ingress card — URL on its own line so it is easy to copy."""

    lines = ["Sign-in from HA Logs: open this URL in a browser"]
    if url:
        lines.append(url)
    if code:
        lines.append(
            f"Device code (Authorize a device page only, not an email OTP): {code}"
        )
    return lines


def ensure_instance_salt(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    salt = secrets.token_hex(16)
    path.write_text(salt + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return salt


def default_server_name(
    *,
    state_dir: str | Path | None = None,
    prefix: str = SERVER_NAME_PREFIX,
) -> str:
    root = Path(state_dir or os.environ.get("STATE_DIR") or "/data/supervisor")
    salt = ensure_instance_salt(root / INSTANCE_SALT_NAME)
    digest = hashlib.sha256(f"hytale-server-name|{salt}".encode("utf-8")).hexdigest()
    digits = int(digest[:8], 16) % 10000
    return f"{prefix} {digits:04d}"


def resolve_server_name(
    *,
    options_file: str | Path | None = None,
    state_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    env = environ if environ is not None else os.environ
    from_env = str(env.get("SERVER_NAME") or "").strip()
    if from_env:
        return from_env

    path = Path(
        options_file
        or env.get("OPTIONS_FILE")
        or env.get("HASSIO_OPTIONS_FILE")
        or "/data/options.json"
    )
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            from_options = str(data.get("server_name") or "").strip()
            if from_options:
                return from_options

    return default_server_name(state_dir=state_dir)


def _state_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    return Path(env.get("STATE_DIR") or "/data/supervisor")


def _install_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    return Path(env.get("INSTALL_DIR") or "/data/game")


def _data_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    return Path(env.get("DATA_DIR") or "/data/world")


def _channel(environ: Mapping[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    options: dict[str, Any] = {}
    if environ is None:
        options = _load_options()
    raw = str(
        options.get("release_channel") or env.get("RELEASE_CHANNEL") or "release"
    ).strip().lower()
    if raw in {"pre-release", "prerelease", "preview"}:
        return "pre-release"
    return "release"


def _java_opts() -> str:
    from_env = str(os.environ.get("JAVA_OPTS") or "").strip()
    if from_env:
        return from_env
    return str(_load_options().get("java_opts") or "").strip()


def _server_authed(data_dir: Path) -> bool:
    """True when Encrypted persistence left auth.enc (cwd or Server/)."""

    return (data_dir / AUTH_ENC_NAME).is_file() or (
        data_dir / "Server" / AUTH_ENC_NAME
    ).is_file()


def operator_action_path(state_dir: str | Path | None = None) -> Path:
    return Path(state_dir or _state_dir()) / OPERATOR_ACTION_FILENAME


def write_operator_action(
    *,
    title: str,
    url: str = "",
    code: str = "",
    detail: str = "",
    steps: list[dict[str, str]] | None = None,
    state_dir: str | Path | None = None,
) -> None:
    path = Path(state_dir or _state_dir()) / OPERATOR_ACTION_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "title": title,
        "detail": detail,
        "url": url,
        "code": code,
        "steps": steps or [],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    tmp.replace(path)


def clear_operator_action(state_dir: str | Path | None = None) -> None:
    path = Path(state_dir or _state_dir()) / OPERATOR_ACTION_FILENAME
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def scrape_device_login(line: str) -> tuple[str, str]:
    """Return (url, code) found on one log line (empty strings if none)."""

    line = _strip_ansi(line)
    url = ""
    code = ""
    for match in _URL_RE.finditer(line):
        candidate = match.group(0).rstrip(").,;]")
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"}:
            continue
        lowered = candidate.lower()
        if (
            "device" not in lowered
            and "user_code" not in lowered
            and "hytale.com" not in lowered
        ):
            continue
        url = candidate
        qs = parse_qs(parsed.query)
        for key in ("user_code", "userCode"):
            if qs.get(key):
                code = _sanitize_device_code(str(qs[key][0]))
                break
    found = _CODE_RE.search(line)
    if found:
        code = _sanitize_device_code(found.group(1))
    code = _sanitize_device_code(code)
    if url:
        url = _url_with_code(url, code)
    return url, code


def _url_has_user_code(url: str) -> bool:
    if not url:
        return False
    qs = parse_qs(urlparse(url).query)
    return bool(qs.get("user_code") or qs.get("userCode"))


def _url_with_code(url: str, code: str) -> str:
    """Keep a complete verification URL; attach or replace user_code with a clean token."""

    url = _strip_ansi(url or "")
    code = _sanitize_device_code(code)
    if not url:
        return url
    parsed = urlparse(url)
    pairs: list[tuple[str, str]] = []
    existing = ""
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in {"user_code", "usercode"}:
            existing = _sanitize_device_code(value)
            continue
        pairs.append((key, value))
    final = code or existing
    if final:
        pairs.append(("user_code", final))
    return urlunparse(parsed._replace(query=urlencode(pairs)))


def coalesce_device_login(
    url: str, code: str, new_url: str, new_code: str
) -> tuple[str, str]:
    """Merge one scraped line into running (url, code). Prefer ?user_code= URLs."""

    if new_code:
        code = new_code
    if new_url:
        if _url_has_user_code(new_url) or not url or not _url_has_user_code(url):
            url = new_url
    return _url_with_code(url, code), code


def merge_server_config(
    path: Path,
    *,
    server_name: str,
    motd: str,
    password: str,
    max_players: int,
    world_name: str,
) -> None:
    """Write HA options into config.json without dropping keys the server owns."""

    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            existing = {}
    existing["ServerName"] = server_name
    existing["MOTD"] = motd
    existing["Password"] = password
    existing["MaxPlayers"] = int(max_players)
    defaults = existing.get("Defaults")
    if not isinstance(defaults, dict):
        defaults = {}
        existing["Defaults"] = defaults
    if world_name:
        defaults["World"] = world_name
    update = existing.get("Update")
    if not isinstance(update, dict):
        update = {}
        existing["Update"] = update
    update["Enabled"] = False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_options() -> dict[str, Any]:
    path = Path(os.environ.get("OPTIONS_FILE") or "/data/options.json")
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def prepare_world_config() -> None:
    options = _load_options()
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    name = resolve_server_name()
    motd = str(options.get("server_motd") or os.environ.get("SERVER_MOTD") or "").strip()
    password = str(
        options.get("server_password") or os.environ.get("SERVER_PASSWORD") or ""
    )
    slots_raw = options.get("server_slots")
    if slots_raw is None:
        slots_raw = os.environ.get("SERVER_SLOTS") or 20
    try:
        slots = int(slots_raw)
    except (TypeError, ValueError):
        slots = 20
    world = str(options.get("world_name") or os.environ.get("WORLD_NAME") or "default").strip()
    merge_server_config(
        data_dir / "config.json",
        server_name=name,
        motd=motd,
        password=password,
        max_players=slots,
        world_name=world or "default",
    )


def _extract_zip(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if n and not n.startswith("/")]
        tops = {Path(n).parts[0] for n in names if Path(n).parts}
        strip = 0
        if len(tops) == 1:
            top = next(iter(tops))
            if top not in {"Assets.zip", "Server", "start.sh", "start.bat"}:
                strip = 1
        for info in zf.infolist():
            parts = Path(info.filename).parts
            if not parts or ".." in parts:
                continue
            if strip:
                if len(parts) <= strip:
                    continue
                rel = Path(*parts[strip:])
            else:
                rel = Path(*parts)
            target = dest / rel
            if info.is_dir() or str(info.filename).endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def _downloader_cmd(*args: str) -> list[str]:
    if not DOWNLOADER.is_file():
        raise SystemExit(f"missing downloader at {DOWNLOADER}")
    return [str(DOWNLOADER), "-skip-update-check", *args]


def _patchline_args(channel: str) -> list[str]:
    # Official CLI documents -patchline for pre-release; omit it on release.
    if channel == "pre-release":
        return ["-patchline", "pre-release"]
    return []


def _tee_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    steps: list[dict[str, str]],
    title: str,
    detail: str,
    send_after_start: str | None = None,
    success_clears: bool = True,
    persist_encrypted: bool = False,
    stdin: IO[str] | None = None,
) -> TeeResult:
    """Run argv, scrape device-code lines, optional stdin inject, forward stdin.

    ``send_after_start`` is only written after a need-auth log line (Java has
    no tokens). Blind inject used to start a second device flow while players
    could already join. ``persist_encrypted`` sends ``/auth persistence
    Encrypted`` before that login and again after a successful Java sign-in.
    """

    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    seen_url = ""
    seen_code = ""
    token_wait_timed_out = False
    signin_done = False
    need_auth = False
    persist_sent = False
    stop = threading.Event()
    stdin_lock = threading.Lock()
    last_published = ""

    def publish() -> None:
        nonlocal last_published
        if not seen_url and not seen_code:
            return
        write_operator_action(
            title=title,
            url=seen_url,
            code=seen_code,
            detail=detail,
            steps=steps,
        )
        key = f"{seen_url}|{seen_code}"
        if key != last_published:
            for line in signin_log_lines(seen_url, seen_code):
                print(line, flush=True)
            last_published = key

    def write_child_stdin(text: str) -> None:
        if not proc.stdin or proc.poll() is not None:
            return
        try:
            with stdin_lock:
                proc.stdin.write(text)
                if not text.endswith("\n"):
                    proc.stdin.write("\n")
                proc.stdin.flush()
        except OSError:
            pass

    def reader() -> None:
        nonlocal seen_url, seen_code, token_wait_timed_out, signin_done
        nonlocal need_auth, persist_sent
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                if token_wait_timed_out_line(line):
                    token_wait_timed_out = True
                if needs_server_auth_line(line):
                    need_auth = True
                if credentials_persisted_line(line):
                    persist_sent = True
                url, code = scrape_device_login(line)
                if url or code:
                    seen_url, seen_code = coalesce_device_login(
                        seen_url, seen_code, url, code
                    )
                    publish()
                if signin_finished_line(line) and not signin_done:
                    # Drop the sign-in card so Ingress can show "installing"
                    # during the rest of a large download.
                    signin_done = True
                    clear_operator_action()
                    print("Sign-in finished; dropping Ingress card", flush=True)
                    if persist_encrypted:
                        write_child_stdin(AUTH_PERSIST_ENCRYPTED + "\n")
        finally:
            stop.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    def injector() -> None:
        nonlocal persist_sent
        if not send_after_start and not persist_encrypted:
            return
        login_sent = False
        while proc.poll() is None and not stop.is_set():
            if signin_done:
                return
            if persist_encrypted and need_auth and not persist_sent:
                write_child_stdin(AUTH_PERSIST_ENCRYPTED + "\n")
                persist_sent = True
            if (
                send_after_start
                and need_auth
                and not login_sent
                and not seen_url
                and not seen_code
            ):
                write_child_stdin(send_after_start)
                login_sent = True
                return
            time.sleep(0.5)

    inj = threading.Thread(target=injector, daemon=True)
    inj.start()

    def forward_stdin() -> None:
        src = stdin if stdin is not None else sys.stdin
        try:
            while not stop.is_set():
                line = src.readline()
                if line == "":
                    break
                write_child_stdin(line)
        except OSError:
            pass

    fwd = threading.Thread(target=forward_stdin, daemon=True)
    fwd.start()
    rc = proc.wait()
    stop.set()
    thread.join(timeout=5)
    if success_clears:
        clear_operator_action()
    return TeeResult(int(rc or 0), token_wait_timed_out)


def cmd_print_version() -> int:
    state = _state_dir()
    state.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(state)
    argv = _downloader_cmd(*_patchline_args(_channel()), "-print-version")
    try:
        result = subprocess.run(
            argv,
            cwd=str(state),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if result.stderr:
        sys.stderr.write(result.stderr)
    lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return result.returncode or 1
    print(lines[-1])
    return 0 if result.returncode == 0 else result.returncode


def cmd_install() -> int:
    install = _install_dir()
    state = _state_dir()
    install.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(state)
    archive = install / GAME_ZIP_NAME
    steps = [
        {"label": "Download files", "state": "active"},
        {"label": "Authenticate server", "state": "pending"},
    ]
    argv = _downloader_cmd(
        *_patchline_args(_channel()),
        "-download-path",
        str(archive),
    )
    rc = 1
    attempt = 0
    while True:
        attempt += 1
        timed_out = attempt > 1
        title = (
            "Sign in again — previous code expired"
            if timed_out
            else "Sign in to download Hytale"
        )
        detail = TIMEOUT_RETRY_DETAIL if timed_out else DOWNLOAD_SIGNIN_DETAIL
        if timed_out:
            cap = (
                f"{attempt}/{INSTALL_TOKEN_ATTEMPTS}"
                if INSTALL_TOKEN_ATTEMPTS
                else str(attempt)
            )
            print(
                "Downloader token wait timed out; requesting a new device code "
                f"({cap})",
                flush=True,
            )
        write_operator_action(title=title, detail=detail, steps=steps)
        result = _tee_process(
            argv,
            cwd=state,
            env=env,
            steps=steps,
            title=title,
            detail=detail,
            success_clears=False,
        )
        rc = result.returncode
        if rc == 0:
            break
        if not result.token_wait_timed_out:
            return rc
        if INSTALL_TOKEN_ATTEMPTS and attempt >= INSTALL_TOKEN_ATTEMPTS:
            print(
                "Hytale downloader stopped waiting for the device token after 10 minutes. "
                "Restart this app and finish Authorize a device within 10 minutes.",
                flush=True,
            )
            return rc
    if not archive.is_file():
        print(f"downloader finished but {archive} is missing", file=sys.stderr)
        return 1
    print(f"Extracting {archive} into {install}", flush=True)
    _extract_zip(archive, install)
    try:
        archive.unlink()
    except OSError:
        pass
    marker = install / INSTALL_MARKER
    if not marker.exists():
        # Some layouts put Assets.zip next to Server/ after unzip of a wrapper dir.
        nested = list(install.glob("**/Assets.zip"))
        if nested:
            nested_root = nested[0].parent
            if nested_root != install:
                for child in nested_root.iterdir():
                    dest = install / child.name
                    if dest.exists():
                        continue
                    shutil.move(str(child), str(dest))
    if not marker.exists():
        print("Assets.zip missing after extract", file=sys.stderr)
        return 1
    clear_operator_action()
    print("Hytale server files installed", flush=True)
    return 0


def cmd_run_server(java_argv: list[str]) -> int:
    ensure_machine_id()
    prepare_world_config()
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    authed = _server_authed(data_dir)
    steps = [
        {"label": "Download files", "state": "done"},
        {
            "label": "Authenticate server",
            "state": "pending" if not authed else "done",
        },
    ]
    env = os.environ.copy()
    env.setdefault("HYTALE_DISABLE_UPDATES", "1")
    env["HOME"] = str(data_dir)
    # Do not pre-write the Ingress card. publish() writes it when a device
    # URL/code appears. Do not inject /auth login device unless Java says
    # tokens are missing — otherwise a new flow starts while players can join.
    result = _tee_process(
        java_argv,
        cwd=data_dir,
        env=env,
        steps=steps,
        title="Sign in to run the Hytale server",
        detail=SERVER_SIGNIN_DETAIL,
        send_after_start=AUTH_LOGIN_DEVICE + "\n",
        success_clears=True,
        persist_encrypted=True,
    )
    return result.returncode


def build_java_command(extra: list[str]) -> list[str]:
    install = _install_dir()
    jar = install / "Server" / "HytaleServer.jar"
    assets = install / "Assets.zip"
    aot = install / "Server" / "HytaleServer.aot"
    if not jar.is_file():
        raise SystemExit(f"missing {jar}")
    cmd = ["java"]
    java_opts = _java_opts()
    if java_opts:
        cmd.extend(part for part in java_opts.split() if part)
    if aot.is_file():
        cmd.append(f"-XX:AOTCache={aot}")
    cmd.extend(["-jar", str(jar), "--assets", str(assets)])
    cmd.extend(extra)
    return cmd


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: haos_defaults.py [print-name|print-version|install|prepare-config|ensure-machine-id|run] [java args]",
            file=sys.stderr,
        )
        return 2
    cmd = args[0]
    if cmd == "print-name":
        print(resolve_server_name())
        return 0
    if cmd == "print-version":
        return cmd_print_version()
    if cmd == "install":
        return cmd_install()
    if cmd == "prepare-config":
        prepare_world_config()
        return 0
    if cmd == "ensure-machine-id":
        print(ensure_machine_id())
        return 0
    if cmd == "run":
        return cmd_run_server(build_java_command(args[1:]))
    # Bare invoke (run.sh): print the resolved server name, Factorio-style.
    print(resolve_server_name())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
