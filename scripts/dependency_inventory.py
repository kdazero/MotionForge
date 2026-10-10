"""Record installed runtime dependencies and preserve wheel-provided license texts."""

import importlib.metadata as metadata
import json
import re
import shutil
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main():
    root = Path(__file__).resolve().parents[1]
    env = {**default_environment(), "extra": ""}
    pending = [("motionforge", frozenset())]
    distributions = {}
    visited = set()
    while pending:
        raw_name, extras = pending.pop()
        name = canonicalize_name(raw_name)
        if (name, extras) in visited:
            continue
        visited.add((name, extras))
        dist = metadata.distribution(name)
        distributions[name] = dist
        for entry in dist.requires or []:
            req = Requirement(entry)
            if req.marker is None or any(
                req.marker.evaluate({**env, "extra": extra}) for extra in {"", *extras}
            ):
                pending.append((req.name, frozenset(req.extras)))
    distributions.pop("motionforge")
    rows = []
    for name, dist in sorted(distributions.items()):
        texts = []
        for entry in dist.files or []:
            path = Path(str(entry))
            # Only license/notice material within distribution metadata, not arbitrary data files.
            if not any(part.endswith(".dist-info") for part in path.parts):
                continue
            if not (
                "licenses" in path.parts or re.search(r"license|copying|notice|authors", path.name, re.I)
            ):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file():
                continue
            metadata_index = next(i for i, p in enumerate(path.parts) if p.endswith(".dist-info"))
            relative = Path(*path.parts[metadata_index + 1 :])
            target = root / "licenses" / f"{name}-{dist.version}" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            texts.append(target.relative_to(root).as_posix())
        expression = dist.metadata.get("License-Expression")
        legacy = dist.metadata.get("License", "")
        classifiers = [v for v in dist.metadata.get_all("Classifier", []) if v.startswith("License ::")]
        rows.append(
            {
                "name": name,
                "version": dist.version,
                "license_expression": expression,
                "license_metadata": legacy if len(legacy) < 200 else "See retained license texts.",
                "license_classifiers": classifiers,
                "license_files": texts,
                "project_urls": dist.metadata.get_all("Project-URL", []),
            }
        )
    (root / "licenses/dependencies.json").write_text(
        json.dumps(
            {
                "scope": "Installed runtime closure, Windows / Python 3.13; excludes dev/build tools",
                "dependencies": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    lock = "# Runtime closure tested on Windows / Python 3.13. Not a portable platform lock.\n"
    lock += "\n".join(f"{r['name']}=={r['version']}" for r in rows) + "\n"
    (root / "requirements-lock-windows-py313.txt").write_text(lock, encoding="utf-8")
    lines = [
        "# Third-party notices",
        "",
        "MotionForge's own code is MIT licensed. Dependencies retain their own licenses;",
        "the repository MIT license does not replace those terms.",
        "",
        "This inventory was generated from installed distribution metadata for the verified",
        "Windows / Python 3.13 runtime dependency closure. It excludes development/build tools.",
        "Other platforms may resolve a different dependency set. Full metadata is in",
        "[licenses/dependencies.json](licenses/dependencies.json). Wheel-provided license and",
        "notice files are retained under `licenses/`, including notices for bundled native libraries.",
        "",
        "| Distribution | Version | Declared license | Retained notices |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        declaration = (
            row["license_expression"]
            or row["license_metadata"]
            or "; ".join(row["license_classifiers"])
            or "Not declared"
        )
        declaration = declaration.replace("\n", " ").replace("|", "/")
        link = (
            f"[Texts](licenses/{row['name']}-{row['version']}/)"
            if row["license_files"]
            else "Not supplied in installed metadata"
        )
        lines.append(f"| {row['name']} | {row['version']} | {declaration} | {link} |")
    lines += [
        "",
        "## Source and asset scope",
        "",
        "The standalone package was extracted from the locally developed SpineMotion project.",
        "No Spine Editor binary, desktop automation, official Spine Runtime source, downloaded",
        "reference media, tunnel executable or production character artwork is included.",
        "The geometric robot is drawn by `src/motionforge/demo.py`; code and sample assets are MIT.",
        "",
        "The data schema is informed by the [Spine JSON documentation](https://esotericsoftware.com/spine-json-format).",
        "Spine is a separate third-party product; no affiliation or official compatibility certification is claimed.",
        "",
        "This is a dependency metadata and packaging inventory, not proof of every contributor's",
        "historical authorship. If adding code or assets, retain source provenance and confirm redistribution rights.",
        "Distributing modified dependencies or native binaries requires checking their complete retained terms.",
        "",
        "Regenerate from a clean installed environment with `python scripts/dependency_inventory.py`",
        "(`packaging` is supplied by the development/build environment).",
        "",
    ]
    (root / "THIRD_PARTY_NOTICES.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "runtime_distributions": len(rows),
                "without_license_text": [r["name"] for r in rows if not r["license_files"]],
            }
        )
    )


if __name__ == "__main__":
    main()
