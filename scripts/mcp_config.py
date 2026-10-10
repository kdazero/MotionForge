"""Print a stdio MCP configuration for this interpreter and an explicit workspace."""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = {
        "mcpServers": {
            "motionforge": {
                "command": str(Path(sys.executable).resolve()),
                "args": ["-m", "motionforge", "--workspace", str(args.workspace.resolve())],
                "env": {"PYTHONUTF8": "1"},
            }
        }
    }
    text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(text)
        print(f"Created {args.output.resolve()}")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
