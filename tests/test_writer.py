from pathlib import Path

from mindfresh.writer import write_atomic_text

def test_write_atomic_text(tmp_path: Path):
    out = tmp_path / "SUMMARY.md"
    path, digest = write_atomic_text(out, "hello")
    assert Path(path).exists()
    assert Path(path).read_text(encoding="utf-8") == "hello"
    assert len(digest) == 64
