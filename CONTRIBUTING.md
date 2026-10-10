# Contributing

Use Python 3.12+ and an isolated virtual environment. Install with `python -m pip install -e ".[dev]"`.

Before a pull request, run:

```text
python -m pytest -q
python -m ruff check src tests scripts examples
python -m ruff format --check src tests scripts examples
python -m build
```

Changes to authoring, rendering or review logic should include a regression test for the behavior. Tests use temporary synthetic artwork; passing tests is not visual approval of user artwork.

Keep the server independent of desktop automation, proprietary executables and external network fetches. All user asset paths must stay inside the selected workspace. Do not commit workspaces, credentials, private references or third-party artwork without redistribution rights.

Contributions are submitted under the repository's MIT license. Retain source attribution and license notices for any third-party material. Open an issue before introducing a new runtime dependency or changing the supported character schema.

Report bugs with OS, Python version, exact command or MCP tool, expected/actual behavior and a minimal shareable example. Do not include private character images or logs containing credentials.
