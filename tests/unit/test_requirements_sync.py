from pathlib import Path

from scripts.check_requirements_sync import check_requirements_sync


def test_requirements_sync_passes_when_files_match(tmp_path, monkeypatch):
    target = tmp_path / "requirements.txt"
    target.write_text("foo==1.0\n", encoding="utf-8")

    def fake_export(path: str):
        Path(path).write_text("foo==1.0\n", encoding="utf-8")

    monkeypatch.setattr("scripts.check_requirements_sync.export_requirements", fake_export)
    ok, message = check_requirements_sync(str(target))
    assert ok is True
    assert message == ""


def test_requirements_sync_fails_when_files_differ(tmp_path, monkeypatch):
    target = tmp_path / "requirements.txt"
    target.write_text("foo==1.0\n", encoding="utf-8")

    def fake_export(path: str):
        Path(path).write_text("foo==2.0\n", encoding="utf-8")

    monkeypatch.setattr("scripts.check_requirements_sync.export_requirements", fake_export)
    ok, message = check_requirements_sync(str(target))
    assert ok is False
    assert "out of sync" in message

