# Third-party notices

MotionForge's own code is MIT licensed. Dependencies retain their own licenses;
the repository MIT license does not replace those terms.

This inventory was generated from installed distribution metadata for the verified
Windows / Python 3.13 runtime dependency closure. It excludes development/build tools.
Other platforms may resolve a different dependency set. Full metadata is in
[licenses/dependencies.json](licenses/dependencies.json). Wheel-provided license and
notice files are retained under `licenses/`, including notices for bundled native libraries.

| Distribution | Version | Declared license | Retained notices |
| --- | --- | --- | --- |
| annotated-types | 0.8.0 | MIT | [Texts](licenses/annotated-types-0.8.0/) |
| anyio | 4.15.1 | MIT | [Texts](licenses/anyio-4.15.1/) |
| attrs | 26.1.0 | MIT | [Texts](licenses/attrs-26.1.0/) |
| certifi | 2026.7.22 | MPL-2.0 | [Texts](licenses/certifi-2026.7.22/) |
| cffi | 2.1.1 | MIT-0 | [Texts](licenses/cffi-2.1.1/) |
| click | 8.5.0 | BSD-3-Clause | [Texts](licenses/click-8.5.0/) |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | [Texts](licenses/cryptography-50.0.2/) |
| h11 | 0.16.0 | MIT | [Texts](licenses/h11-0.16.0/) |
| httpcore | 1.0.9 | BSD-3-Clause | [Texts](licenses/httpcore-1.0.9/) |
| httpx | 0.28.1 | BSD-3-Clause | [Texts](licenses/httpx-0.28.1/) |
| httpx-sse | 0.4.3 | MIT | [Texts](licenses/httpx-sse-0.4.3/) |
| idna | 3.20 | BSD-3-Clause | [Texts](licenses/idna-3.20/) |
| jsonschema | 4.26.0 | MIT | [Texts](licenses/jsonschema-4.26.0/) |
| jsonschema-specifications | 2025.9.1 | MIT | [Texts](licenses/jsonschema-specifications-2025.9.1/) |
| mcp | 1.30.0 | MIT | [Texts](licenses/mcp-1.30.0/) |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | [Texts](licenses/numpy-2.5.3/) |
| opencv-python-headless | 4.14.0.94 | Apache 2.0 | [Texts](licenses/opencv-python-headless-4.14.0.94/) |
| pillow | 12.3.0 | MIT-CMU | [Texts](licenses/pillow-12.3.0/) |
| pycparser | 3.11 | BSD-3-Clause | [Texts](licenses/pycparser-3.11/) |
| pydantic | 2.13.5 | MIT | [Texts](licenses/pydantic-2.13.5/) |
| pydantic-core | 2.46.5 | MIT | [Texts](licenses/pydantic-core-2.46.5/) |
| pydantic-settings | 2.15.0 | MIT | [Texts](licenses/pydantic-settings-2.15.0/) |
| pyjwt | 2.15.1 | MIT | [Texts](licenses/pyjwt-2.15.1/) |
| python-dotenv | 1.2.4 | BSD-3-Clause | [Texts](licenses/python-dotenv-1.2.4/) |
| python-multipart | 0.0.32 | Apache-2.0 | [Texts](licenses/python-multipart-0.0.32/) |
| pywin32 | 312 | PSF | [Texts](licenses/pywin32-312/) |
| referencing | 0.37.0 | MIT | [Texts](licenses/referencing-0.37.0/) |
| rpds-py | 2026.9.1 | MIT | [Texts](licenses/rpds-py-2026.9.1/) |
| sse-starlette | 3.5.0 | BSD-3-Clause | [Texts](licenses/sse-starlette-3.5.0/) |
| starlette | 1.7.0 | BSD-3-Clause | [Texts](licenses/starlette-1.7.0/) |
| typing-extensions | 4.16.0 | PSF-2.0 | [Texts](licenses/typing-extensions-4.16.0/) |
| typing-inspection | 0.4.4 | MIT | [Texts](licenses/typing-inspection-0.4.4/) |
| uvicorn | 0.54.0 | BSD-3-Clause | [Texts](licenses/uvicorn-0.54.0/) |

## Source and asset scope

The standalone package was extracted from the locally developed SpineMotion project.
No Spine Editor binary, desktop automation, official Spine Runtime source, downloaded
reference media, tunnel executable or production character artwork is included.
The geometric robot is drawn by `src/motionforge/demo.py`; code and sample assets are MIT.

The data schema is informed by the [Spine JSON documentation](https://esotericsoftware.com/spine-json-format).
Spine is a separate third-party product; no affiliation or official compatibility certification is claimed.

This is a dependency metadata and packaging inventory, not proof of every contributor's
historical authorship. If adding code or assets, retain source provenance and confirm redistribution rights.
Distributing modified dependencies or native binaries requires checking their complete retained terms.

Regenerate from a clean installed environment with `python scripts/dependency_inventory.py`
(`packaging` is supplied by the development/build environment).
