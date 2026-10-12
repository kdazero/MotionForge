from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MotionError(ValueError):
    """An actionable user-facing authoring error."""


WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


def portable_path(value: str) -> str:
    """Reject relative file paths whose parts are Windows device names (NUL.png, con/x.png)."""
    if any(part.split(".")[0].upper() in WINDOWS_RESERVED for part in re.split(r"[\\/]", value)):
        raise MotionError(f"Path uses a name reserved by Windows: {value}")
    return value


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise MotionError("Use 1–64 ASCII letters, digits, '-' or '_' for project/file IDs.")
    if value.upper() in WINDOWS_RESERVED:
        raise MotionError("This ID is reserved by Windows.")
    return value


def inside(root: Path, value: str | Path, *, exists: bool = True) -> Path:
    root = root.resolve()
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root):
        raise MotionError("Path must stay inside the configured workspace.")
    if exists and not candidate.exists():
        raise MotionError(f"File does not exist: {candidate.relative_to(root)}")
    return candidate


def read_json(path: Path, limit: int = 20_000_000) -> dict:
    # On Windows an atomic replacement can briefly deny a concurrent reader.
    # Retry sharing violations only; malformed JSON and missing files stay errors.
    for attempt in range(8):
        try:
            if path.stat().st_size > limit:
                raise MotionError("JSON exceeds the 20 MB limit.")
            text = path.read_text(encoding="utf-8-sig")
            break
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(min(0.01 * 2**attempt, 0.1))
        except UnicodeError as exc:
            raise MotionError(f"Invalid UTF-8 JSON: {path.name}") from exc
    try:
        value = json.loads(text)
    except (ValueError, UnicodeError) as exc:
        raise MotionError(f"Invalid UTF-8 JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise MotionError("Expected a JSON object.")
    return value


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        # Windows readers briefly hold a non-delete-sharing handle. Preserve
        # atomic updates while allowing concurrent MCP progress polling.
        for attempt in range(8):
            try:
                os.replace(name, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(min(0.01 * 2**attempt, 0.1))
    finally:
        if os.path.exists(name):
            os.unlink(name)


@dataclass(frozen=True)
class Settings:
    workspace: Path
    # Data schema compatibility marker, not an installed editor dependency.
    spine_version: str = "3.8.75"

    def ensure_dirs(self) -> None:
        for name in ("inbox", "projects"):
            (self.workspace / name).mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str, *, exists: bool = True) -> Path:
        return inside(self.workspace, f"projects/{identifier(project_id)}", exists=exists)
