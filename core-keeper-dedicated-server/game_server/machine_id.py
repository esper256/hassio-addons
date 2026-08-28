"""Stable Linux machine-id for containers that lack DMI hardware UUID.

Dedicated-server binaries (especially Java) often treat ``/etc/machine-id`` as
the host hardware UUID. HAOS/Docker images frequently have none, or a new one
each container recreate. Persist a systemd-shaped 32-hex id under the
supervisor state dir and copy it to the paths those libraries read — before
privileges are dropped, so a non-root game process can still read ``/etc``.
"""

from __future__ import annotations

import logging
import re
import secrets
from pathlib import Path

LOG = logging.getLogger("game_server.machine_id")

MACHINE_ID_NAME = "machine-id"
_MACHINE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_DEFAULT_ETC = Path("/etc/machine-id")
_DEFAULT_DBUS = Path("/var/lib/dbus/machine-id")
_DEFAULT_DMI = (
    Path("/sys/class/dmi/id/product_uuid"),
    Path("/sys/devices/virtual/dmi/id/product_uuid"),
)


def valid_machine_id(text: str) -> str:
    cleaned = (text or "").strip().lower().replace("-", "")
    return cleaned if _MACHINE_ID_RE.fullmatch(cleaned) else ""


def dashed_uuid(machine_id: str) -> str:
    """DMI product_uuid shape (8-4-4-4-12) from a 32-hex machine-id."""

    mid = valid_machine_id(machine_id)
    if not mid:
        return ""
    return f"{mid[:8]}-{mid[8:12]}-{mid[12:16]}-{mid[16:20]}-{mid[20:32]}"


def _write_id_file(path: Path, text: str, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        path.chmod(mode)
    except OSError:
        pass


def _read_valid(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return valid_machine_id(path.read_text(encoding="utf-8"))
    except OSError:
        return ""


def _copy_to(path: Path, machine_id: str, *, dashed: bool = False) -> bool:
    text = dashed_uuid(machine_id) if dashed else machine_id
    if not text:
        return False
    if dashed:
        current = ""
        if path.is_file():
            try:
                current = valid_machine_id(path.read_text(encoding="utf-8"))
            except OSError:
                current = ""
        if current == machine_id:
            return True
    elif _read_valid(path) == machine_id:
        return True
    try:
        # DMI sysfs: only write when the parent already exists. Do not mkdir
        # under /sys — that fails or does nothing useful in a container.
        if dashed and not path.parent.is_dir():
            return False
        if dashed:
            _write_id_file(path, text)
        else:
            _write_id_file(path, machine_id)
        return True
    except OSError:
        return False


def ensure_machine_id(
    *,
    state_dir: str | Path,
    etc_path: str | Path | None = None,
    dbus_path: str | Path | None = None,
    dmi_paths: list[str | Path] | None = None,
) -> str:
    """Return a stable 32-hex machine-id, persisted and copied to host paths."""

    state = Path(state_dir)
    persisted = state / MACHINE_ID_NAME
    etc = Path(etc_path) if etc_path is not None else _DEFAULT_ETC
    dbus = Path(dbus_path) if dbus_path is not None else _DEFAULT_DBUS
    dmi = [Path(p) for p in (dmi_paths if dmi_paths is not None else _DEFAULT_DMI)]

    machine_id = _read_valid(persisted)
    if not machine_id:
        machine_id = _read_valid(etc)
    if not machine_id:
        machine_id = _read_valid(dbus)
    if not machine_id:
        machine_id = secrets.token_hex(16)

    if _read_valid(persisted) != machine_id:
        state.mkdir(parents=True, exist_ok=True)
        _write_id_file(persisted, machine_id, mode=0o600)

    etc_ok = _copy_to(etc, machine_id)
    dbus_ok = _copy_to(dbus, machine_id)
    dmi_ok = any(_copy_to(path, machine_id, dashed=True) for path in dmi)

    if not etc_ok:
        LOG.warning(
            "Could not write %s; binaries that key secrets to the Linux "
            "hardware UUID may fail or re-authenticate every restart",
            etc,
        )
    else:
        LOG.info(
            "Linux machine-id ready (persisted under %s; /etc/machine-id writable)",
            persisted,
        )
    if dbus_ok or dmi_ok:
        LOG.debug("machine-id also copied to dbus=%s dmi=%s", dbus_ok, dmi_ok)
    return machine_id
