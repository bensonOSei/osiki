"""The SDK's vendored decision core must stay a byte-identical copy."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sync_sdk_decision.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sync_sdk_decision", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    source.mkdir()
    dest.mkdir()
    (source / "a.py").write_bytes(b"A = 1\n")
    (source / "b.py").write_bytes(b"B = 2\r\n")
    return source, dest


def _run(source: Path, dest: Path, *extra: str) -> int:
    code: int = script.main(["--source", str(source), "--dest", str(dest), *extra])
    return code


def test_sync_copies_files_byte_for_byte(dirs: tuple[Path, Path]) -> None:
    source, dest = dirs

    assert _run(source, dest) == 0

    assert (dest / "a.py").read_bytes() == b"A = 1\n"
    assert (dest / "b.py").read_bytes() == b"B = 2\r\n"


def test_sync_creates_missing_destination(
    tmp_path: Path, dirs: tuple[Path, Path]
) -> None:
    source, _ = dirs
    dest = tmp_path / "new" / "dest"

    assert _run(source, dest) == 0

    assert (dest / "a.py").exists()


def test_check_passes_when_identical(dirs: tuple[Path, Path]) -> None:
    source, dest = dirs
    _run(source, dest)

    assert _run(source, dest, "--check") == 0


def test_check_ignores_non_python_files(dirs: tuple[Path, Path]) -> None:
    source, dest = dirs
    _run(source, dest)
    (dest / "__pycache__").mkdir()
    (dest / "__pycache__" / "a.cpython-313.pyc").write_bytes(b"x")
    (dest / "notes.txt").write_text("keep")

    assert _run(source, dest, "--check") == 0


def test_check_fails_and_names_file_on_drift(
    dirs: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, dest = dirs
    _run(source, dest)
    (dest / "b.py").write_bytes(b"B = 3\n")

    assert _run(source, dest, "--check") == 1

    out = capsys.readouterr().out
    assert "b.py" in out
    assert "a.py" not in out


def test_check_names_missing_and_stale_files(
    dirs: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, dest = dirs
    _run(source, dest)
    (dest / "a.py").unlink()
    (dest / "old.py").write_text("X = 1\n")

    assert _run(source, dest, "--check") == 1

    out = capsys.readouterr().out
    assert "a.py" in out
    assert "old.py" in out


def test_check_does_not_modify_destination(dirs: tuple[Path, Path]) -> None:
    source, dest = dirs
    (dest / "old.py").write_text("X = 1\n")

    assert _run(source, dest, "--check") == 1

    assert (dest / "old.py").exists()
    assert not (dest / "a.py").exists()


def test_check_fails_when_destination_missing(
    tmp_path: Path, dirs: tuple[Path, Path]
) -> None:
    source, _ = dirs

    assert _run(source, tmp_path / "absent", "--check") == 1


def test_sync_removes_stale_files(dirs: tuple[Path, Path]) -> None:
    source, dest = dirs
    (dest / "old.py").write_text("X = 1\n")
    (dest / "notes.txt").write_text("keep")

    assert _run(source, dest) == 0

    assert not (dest / "old.py").exists()
    assert (dest / "notes.txt").exists()
    assert (dest / "a.py").exists()


def test_defaults_point_at_the_repo() -> None:
    assert script.DEFAULT_SOURCE == script.ROOT / "osiki" / "decision"
    assert script.DEFAULT_DEST == (
        script.ROOT / "sdks" / "python" / "src" / "osiki_sdk" / "_decision"
    )
    assert script.main(["--check"]) == 0
