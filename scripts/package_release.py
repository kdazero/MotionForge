"""Package only tracked publication inputs and built distributions, never workspaces."""

import hashlib
import json
import tarfile
import zipfile
from pathlib import Path

ROOT_FILES = {
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "MANIFEST.in",
    ".gitignore",
    ".gitattributes",
    "requirements-lock-windows-py313.txt",
}
ROOT_DIRS = {"src", "docs", "examples", "scripts", "config", "tests", "licenses", ".github"}
EXCLUDED = {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "workspace", "motionforge-workspace"}


def public_file(relative):
    if any(p in EXCLUDED or p.endswith(".egg-info") for p in relative.parts):
        return False
    if relative.suffix in {".pyc", ".pyo", ".log"} or relative.name.startswith(".env"):
        return False
    return relative.as_posix() in ROOT_FILES or relative.parts[0] in ROOT_DIRS


def main():
    root = Path(__file__).resolve().parents[1]
    dist = root / "dist"
    wheel = dist / "motionforge-0.2.0-py3-none-any.whl"
    sdist = dist / "motionforge-0.2.0.tar.gz"
    if not wheel.is_file() or not sdist.is_file():
        raise FileNotFoundError("Run python -m build first.")
    with zipfile.ZipFile(wheel) as z:
        assert z.testzip() is None
        assert not any(
            "spinemotion" in n or n.endswith("/spine.py") or "/desktop.py" in n for n in z.namelist()
        )
    with tarfile.open(sdist) as archive:
        assert not any("__pycache__" in n or "/workspace/" in n for n in archive.getnames())
    files = sorted(p for p in root.rglob("*") if p.is_file() and public_file(p.relative_to(root)))
    target = dist / "MotionForge-0.2.0-user-kit.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "MotionForge/" + path.relative_to(root).as_posix())
        archive.write(wheel, "MotionForge/packages/" + wheel.name)
        archive.write(sdist, "MotionForge/packages/" + sdist.name)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
    artifacts = [wheel, sdist, target]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (dist / "SHA256SUMS.txt").write_text(
        "".join(f"{value}  {name}\n" for name, value in hashes.items()), encoding="utf-8"
    )
    print(json.dumps({"public_input_files": len(files), "sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
