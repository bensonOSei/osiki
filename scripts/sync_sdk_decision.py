"""Copy ``osiki/decision`` into the Python SDK, or check that the copy is current.

The SDK decides locally with a byte-identical copy of the engine's pure decision
package. ``python scripts/sync_sdk_decision.py`` regenerates the copy;
``--check`` exits 1 (naming each file) when it has drifted, and CI runs it.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "osiki" / "decision"
DEFAULT_DEST = ROOT / "sdks" / "python" / "src" / "osiki_sdk" / "_decision"


def _python_files(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        return {}
    return {file.name: file for file in sorted(directory.glob("*.py"))}


def find_drift(source: Path, dest: Path) -> list[str]:
    """Names of files that differ, are missing from, or are stale in ``dest``."""
    wanted = _python_files(source)
    present = _python_files(dest)
    drift = [
        f"{name} (missing)" if name not in present else f"{name} (differs)"
        for name, file in wanted.items()
        if name not in present or file.read_bytes() != present[name].read_bytes()
    ]
    drift += [f"{name} (stale)" for name in present if name not in wanted]
    return sorted(drift)


def sync(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    wanted = _python_files(source)
    for name, file in wanted.items():
        (dest / name).write_bytes(file.read_bytes())
    for name, file in _python_files(dest).items():
        if name not in wanted:
            file.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--check", action="store_true", help="fail on drift")
    args = parser.parse_args(argv)

    if not args.check:
        sync(args.source, args.dest)
        return 0

    drift = find_drift(args.source, args.dest)
    for entry in drift:
        print(f"drift: {entry}")
    if drift:
        print("run: python scripts/sync_sdk_decision.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
