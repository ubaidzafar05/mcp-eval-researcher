from core.identity import check_git_identity, extract_owner


def test_extract_owner_parses_common_remote_formats():
    assert extract_owner("git@github.com:UbaidZafar/cloud-hive.git") == "UbaidZafar"
    assert extract_owner("https://github.com/UbaidZafar/cloud-hive.git") == "UbaidZafar"


def test_identity_preflight_detects_mismatch(monkeypatch):
    values = {
        "config --get user.name": "Junaid",
        "config --get user.email": "demo@example.com",
        "remote get-url origin": "git@github.com:Junaid/cloud-hive.git",
    }

    def fake_run_git(args):
        return values.get(" ".join(args), "")

    monkeypatch.setattr("core.identity._run_git", fake_run_git)
    result = check_git_identity(expected_owner="UbaidZafar")
    assert result.ok is False
    assert any("Junaid" in reason for reason in result.reasons)

