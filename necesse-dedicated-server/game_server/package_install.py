"""HTTP archive install/update for games that are not SteamCMD apps.

Used when a plugin declares ``package_install`` (e.g. a free headless tarball).
No game names or URLs live here — plugins supply version/download templates.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .update_check import UpdateCheckResult

LOG = logging.getLogger("game_server.package")

LineCallback = Callable[[str], None]


class _PackagePlugin(Protocol):
    install_marker: str
    package_install: Any


_SUPPORTED_KINDS = frozenset({"http_archive"})
VERSION_FILENAME = ".package_version"


class PackageInstallError(RuntimeError):
    pass


def _marker_installed(install_dir: str | Path, marker_relative: str) -> bool:
    return (Path(install_dir) / marker_relative).exists()


@dataclass
class PackageInstallSpec:
    """Declarative HTTP archive install source from ``game.yaml``."""

    kind: str
    version_url: str
    version_json_path: str
    download_url: str
    strip_components: int = 1
    version_filename: str = VERSION_FILENAME

    @classmethod
    def from_dict(cls, data: Any) -> "PackageInstallSpec | None":
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValueError("package_install must be a mapping when provided")
        kind = str(data.get("kind") or "").strip().lower()
        if kind not in _SUPPORTED_KINDS:
            raise ValueError(
                f"Unsupported package_install.kind {kind!r}; expected http_archive"
            )
        version_url = str(data.get("version_url") or "").strip()
        version_json_path = str(data.get("version_json_path") or "").strip()
        download_url = str(data.get("download_url") or "").strip()
        if not version_url or not version_json_path or not download_url:
            raise ValueError(
                "package_install requires version_url, version_json_path, and download_url"
            )
        strip = int(data.get("strip_components") or 1)
        if strip < 0:
            raise ValueError("package_install.strip_components must be >= 0")
        version_filename = str(data.get("version_filename") or VERSION_FILENAME).strip()
        if not version_filename:
            version_filename = VERSION_FILENAME
        return cls(
            kind=kind,
            version_url=version_url,
            version_json_path=version_json_path,
            download_url=download_url,
            strip_components=strip,
            version_filename=version_filename,
        )


def _json_path(data: Any, dotted: str) -> Any:
    cur = data
    for part in dotted.split("."):
        if not part:
            continue
        if not isinstance(cur, dict) or part not in cur:
            raise PackageInstallError(
                f"version_json_path {dotted!r} not found in version response"
            )
        cur = cur[part]
    return cur


def fetch_remote_version(
    spec: PackageInstallSpec,
    *,
    timeout: float = 60.0,
) -> str:
    """GET version_url and extract the version string via version_json_path."""

    try:
        request = urllib.request.Request(
            spec.version_url,
            headers={"User-Agent": "hassio-game-server/1"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PackageInstallError(
            f"Failed fetching version from {spec.version_url}: {exc}"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageInstallError(
            f"Invalid JSON from version URL {spec.version_url}: {exc}"
        ) from exc
    value = _json_path(payload, spec.version_json_path)
    version = str(value or "").strip()
    if not version:
        raise PackageInstallError(
            f"Empty version at {spec.version_json_path!r} from {spec.version_url}"
        )
    return version


def version_path(install_dir: str | Path, spec: PackageInstallSpec) -> Path:
    return Path(install_dir) / spec.version_filename


def read_local_version(install_dir: str | Path, spec: PackageInstallSpec) -> str | None:
    path = version_path(install_dir, spec)
    try:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            return text or None
    except OSError:
        LOG.debug("Could not read package version file", exc_info=True)
    return None


def write_local_version(
    install_dir: str | Path, spec: PackageInstallSpec, version: str
) -> None:
    path = version_path(install_dir, spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(version.strip() + "\n", encoding="utf-8")
    tmp.replace(path)


def download_url_for(spec: PackageInstallSpec, version: str) -> str:
    if "{version}" not in spec.download_url:
        return spec.download_url
    return spec.download_url.replace("{version}", version)


def _emit(on_line: LineCallback | None, message: str) -> None:
    LOG.info("[package] %s", message)
    if on_line is not None:
        try:
            on_line(message)
        except Exception:  # noqa: BLE001
            LOG.debug("package on_line callback failed", exc_info=True)


def _download_file(
    url: str,
    dest: Path,
    *,
    timeout: float,
    on_line: LineCallback | None,
    stop_event: threading.Event | None,
) -> None:
    _emit(on_line, f"Downloading {url}")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "hassio-game-server/1"})
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            total = resp.headers.get("Content-Length")
            total_n = int(total) if total and str(total).isdigit() else None
            wrote = 0
            last_report = 0
            with dest.open("wb") as out:
                while True:
                    if stop_event is not None and stop_event.is_set():
                        raise PackageInstallError("Stopped while downloading package")
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    out.write(chunk)
                    wrote += len(chunk)
                    if total_n and wrote - last_report >= max(total_n // 10, 1):
                        pct = int(wrote * 100 / total_n)
                        _emit(on_line, f"Download progress {pct}% ({wrote}/{total_n} bytes)")
                        last_report = wrote
    except PackageInstallError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PackageInstallError(f"Download failed from {url}: {exc}") from exc
    _emit(on_line, f"Download complete ({dest.stat().st_size} bytes)")


def _safe_members(tar: tarfile.TarFile, strip: int) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    for member in tar.getmembers():
        parts = Path(member.name).parts
        if strip and len(parts) <= strip:
            continue
        if strip:
            member.name = str(Path(*parts[strip:]))
        # Block path escape.
        target = Path(member.name)
        if target.is_absolute() or ".." in target.parts:
            raise PackageInstallError(f"Refusing unsafe archive path: {member.name}")
        members.append(member)
    return members


def _extract_archive(
    archive: Path,
    install_dir: Path,
    *,
    strip_components: int,
    on_line: LineCallback | None,
) -> None:
    """Extract archive and replace ``install_dir`` contents (no merge).

    Merging left deleted upstream files in place (e.g. Factorio 2.0→2.1 moved
    ``quality/.../recycling.lua`` into ``recycler/``; a merge kept the stale
    file and the game crashed). Always swap in a clean tree instead.
    """

    _emit(on_line, f"Extracting archive into {install_dir} (clean replace)")
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    # Staging + backup live beside install_dir so renames stay on one filesystem.
    with tempfile.TemporaryDirectory(
        prefix="pkg-extract-", dir=str(install_dir.parent)
    ) as tmp:
        staging = Path(tmp) / "root"
        staging.mkdir()
        try:
            with tarfile.open(archive, mode="r:*") as tar:
                members = _safe_members(tar, strip_components)
                # filter='data' is the Python 3.12+ safe default; ignore on older.
                try:
                    tar.extractall(path=staging, members=members, filter="data")
                except TypeError:
                    tar.extractall(path=staging, members=members)
        except (tarfile.TarError, OSError) as exc:
            raise PackageInstallError(f"Failed extracting archive: {exc}") from exc

        backup = Path(str(install_dir) + ".replace-old")
        if backup.exists():
            shutil.rmtree(backup)
        replaced = False
        try:
            if install_dir.exists():
                install_dir.rename(backup)
                replaced = True
            staging.rename(install_dir)
        except OSError as exc:
            # Best-effort rollback if the swap failed mid-way.
            if not install_dir.exists() and backup.exists():
                try:
                    backup.rename(install_dir)
                except OSError:
                    LOG.warning(
                        "Failed restoring install dir after extract error",
                        exc_info=True,
                    )
            raise PackageInstallError(
                f"Failed replacing install tree at {install_dir}: {exc}"
            ) from exc
        if replaced and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    _emit(on_line, "Extract complete")


def install_or_update(
    install_dir: str | Path,
    plugin: _PackagePlugin,
    *,
    force: bool = False,
    timeout: float = 1800.0,
    stop_event: threading.Event | None = None,
    on_line: LineCallback | None = None,
    run_uid: int | None = None,
    run_gid: int | None = None,
) -> str:
    """Install or update from package_install. Returns the installed version."""

    spec = plugin.package_install
    if spec is None:
        raise PackageInstallError("plugin has no package_install configuration")
    root = Path(install_dir)
    root.mkdir(parents=True, exist_ok=True)

    remote = fetch_remote_version(spec, timeout=min(60.0, timeout))
    local = read_local_version(root, spec)
    installed = _marker_installed(root, plugin.install_marker)
    if installed and local == remote and not force:
        _emit(on_line, f"Already up to date (version {remote})")
        return remote

    _emit(
        on_line,
        f"Installing package version {remote}"
        + (f" (was {local})" if local else " (fresh install)"),
    )
    url = download_url_for(spec, remote)
    with tempfile.TemporaryDirectory(prefix="pkg-dl-", dir=str(root.parent)) as tmp:
        archive = Path(tmp) / "package.tar"
        _download_file(
            url,
            archive,
            timeout=timeout,
            on_line=on_line,
            stop_event=stop_event,
        )
        if stop_event is not None and stop_event.is_set():
            raise PackageInstallError("Stopped before extract")
        _extract_archive(
            archive,
            root,
            strip_components=spec.strip_components,
            on_line=on_line,
        )

    if not _marker_installed(root, plugin.install_marker):
        raise PackageInstallError(
            f"Package extract finished but install marker missing: {plugin.install_marker}"
        )
    write_local_version(root, spec, remote)
    # Best-effort ownership when running as root before drop.
    if run_uid is not None and hasattr(os, "chown"):
        try:
            for path in root.rglob("*"):
                os.chown(path, run_uid, run_gid if run_gid is not None else -1)
            os.chown(root, run_uid, run_gid if run_gid is not None else -1)
        except OSError:
            LOG.debug("chown after package install failed", exc_info=True)
    _emit(on_line, f"Installed version {remote}")
    return remote


def update_available(
    install_dir: str | Path,
    plugin: _PackagePlugin,
    *,
    timeout: float = 60.0,
) -> UpdateCheckResult:
    """Compare local package version to remote (same shape as Steam checks)."""

    spec = plugin.package_install
    if spec is None:
        return UpdateCheckResult(
            update_available=False,
            local_build_id=None,
            remote_build_id=None,
            error="no package_install configured",
        )
    local = read_local_version(install_dir, spec)
    try:
        remote = fetch_remote_version(spec, timeout=timeout)
    except PackageInstallError as exc:
        return UpdateCheckResult(
            update_available=False,
            local_build_id=local,
            remote_build_id=None,
            error=str(exc),
        )
    return UpdateCheckResult(
        update_available=bool(remote) and remote != local,
        local_build_id=local,
        remote_build_id=remote,
        error=None,
    )
