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
from typing import IO, Any, Mapping
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

INSTANCE_SALT_NAME = "instance_salt"
SERVER_NAME_PREFIX = "HAOS Hytale"
OPERATOR_ACTION_FILENAME = "operator_action.json"
DOWNLOADER = Path("/opt/hytale-downloader")
CREDENTIALS_NAME = ".hytale-downloader-credentials.json"
AUTH_ENC_NAME = "auth.enc"
GAME_ZIP_NAME = "game.zip"
INSTALL_MARKER = "Assets.zip"
SIGNIN_DETAIL = (
    "Open the link in a new browser tab (not this panel) and sign in. "
    "The code on this card is Hytale's device login — paste it only if that page asks. "
    "If Hytale emails you a login code, type the email code there; do not paste this one. "
    "The device code appears within a second, before any email arrives."
)
DOWNLOAD_SIGNIN_DETAIL = SIGNIN_DETAIL + " First download is several gigabytes."
SERVER_SIGNIN_DETAIL = (
    "This is a second, different Hytale login after download. "
    + SIGNIN_DETAIL
    + " Hosting does not lock your client."
)

_URL_RE = re.compile(r"https://[^\s\"'<>]+", re.IGNORECASE)
_CODE_RE = re.compile(
    r"(?:user_code|enter code|code)\s*[=:]\s*([A-Za-z0-9][A-Za-z0-9._-]{2,31})",
    re.IGNORECASE,
)
_AUTH_OK_RE = re.compile(r"authentication successful", re.IGNORECASE)


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
                code = str(qs[key][0]).strip()
                break
    found = _CODE_RE.search(line)
    if found:
        code = found.group(1).strip()
    return url, code


def _url_has_user_code(url: str) -> bool:
    if not url:
        return False
    qs = parse_qs(urlparse(url).query)
    return bool(qs.get("user_code") or qs.get("userCode"))


def _url_with_code(url: str, code: str) -> str:
    """Keep a complete verification URL; attach user_code when the CLI omitted it."""

    if not url or not code:
        return url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if qs.get("user_code") or qs.get("userCode"):
        return url
    extra = urlencode({"user_code": code})
    new_query = f"{parsed.query}&{extra}" if parsed.query else extra
    return urlunparse(parsed._replace(query=new_query))


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
    stdin: IO[str] | None = None,
) -> int:
    """Run argv, scrape device-code lines, optional stdin inject, forward stdin."""

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
            print(f"Ingress sign-in URL: {seen_url}", flush=True)
            print(f"Ingress sign-in code: {seen_code}", flush=True)
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
        nonlocal seen_url, seen_code
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                url, code = scrape_device_login(line)
                if url or code:
                    seen_url, seen_code = coalesce_device_login(
                        seen_url, seen_code, url, code
                    )
                    publish()
                if _AUTH_OK_RE.search(line):
                    # Drop the sign-in card so Ingress can show "installing"
                    # during the rest of a large download.
                    clear_operator_action()
        finally:
            stop.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    def injector() -> None:
        if not send_after_start:
            return
        delay = 5.0
        attempts = 0
        while proc.poll() is None and attempts < 8 and not stop.is_set():
            time.sleep(delay)
            if stop.is_set() or seen_url or seen_code:
                return
            write_child_stdin(send_after_start)
            attempts += 1
            delay = 10.0

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
    return int(rc or 0)


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
    write_operator_action(
        title="Sign in to download Hytale",
        detail=DOWNLOAD_SIGNIN_DETAIL,
        steps=steps,
    )
    argv = _downloader_cmd(
        *_patchline_args(_channel()),
        "-download-path",
        str(archive),
    )
    rc = _tee_process(
        argv,
        cwd=state,
        env=env,
        steps=steps,
        title="Sign in to download Hytale",
        detail=DOWNLOAD_SIGNIN_DETAIL,
        success_clears=False,
    )
    if rc != 0:
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
    inject = None if authed else "/auth login device\n"
    if not authed:
        write_operator_action(
            title="Sign in to run the Hytale server",
            detail=SERVER_SIGNIN_DETAIL,
            steps=steps,
        )
    rc = _tee_process(
        java_argv,
        cwd=data_dir,
        env=env,
        steps=steps,
        title="Sign in to run the Hytale server",
        detail=SERVER_SIGNIN_DETAIL,
        send_after_start=inject,
        success_clears=True,
    )
    return rc


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
            "usage: haos_defaults.py [print-name|print-version|install|prepare-config|run] [java args]",
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
    if cmd == "run":
        return cmd_run_server(build_java_command(args[1:]))
    # Bare invoke (run.sh): print the resolved server name, Factorio-style.
    print(resolve_server_name())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
