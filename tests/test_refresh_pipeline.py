from pathlib import Path
import hashlib

from mindfresh.refresh import refresh_vault


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fake_refresh_writes_required_generated_files_and_preserves_raw(tmp_path: Path):
    vault = tmp_path / "vault"
    topic = vault / "research" / "topic-a"
    topic.mkdir(parents=True)
    raw = topic / "2026-04-24-research.md"
    raw.write_text("# Topic A update\n\nStable local claim.", encoding="utf-8")
    before_raw = _sha(raw)

    results = refresh_vault(vault, adapter_name="fake")

    assert [result.topic for result in results] == ["research/topic-a"]
    assert results[0].status == "refreshed"
    assert _sha(raw) == before_raw

    summary = (topic / "SUMMARY.md").read_text(encoding="utf-8")
    changelog = (topic / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "mindfresh_generated: true" in summary
    assert "mindfresh_kind: summary" in summary
    assert "## 현재 결론" in summary
    assert "## 검토한 출처" in summary
    assert "2026-04-24-research.md" in summary
    assert "mindfresh_kind: changelog" in changelog
    assert "트리거 파일" in changelog
    assert (vault / ".mindfresh" / "manifest.sqlite").exists()


def test_fake_refresh_is_idempotent_and_generated_files_are_not_reingested(tmp_path: Path):
    vault = tmp_path / "vault"
    topic = vault / "policy" / "policy-platform"
    topic.mkdir(parents=True)
    (topic / "2026-04-01-policy.md").write_text("# Policy note", encoding="utf-8")

    first = refresh_vault(vault, adapter_name="fake")
    summary_hash = _sha(topic / "SUMMARY.md")
    changelog_hash = _sha(topic / "CHANGELOG.md")

    second = refresh_vault(vault, adapter_name="fake")

    assert first[0].status == "refreshed"
    assert second[0].status == "unchanged"
    assert _sha(topic / "SUMMARY.md") == summary_hash
    assert _sha(topic / "CHANGELOG.md") == changelog_hash
    assert second[0].trigger_files == []
