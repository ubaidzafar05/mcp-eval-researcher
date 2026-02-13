from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass(slots=True)
class IdentityCheckResult:
    ok: bool
    user_name: str
    user_email: str
    remote_url: str
    owner: str
    reasons: list[str]


def _run_git(args: list[str]) -> str:
    try:
        out = subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL, text=True)
        return out.strip()
    except Exception:  # noqa: BLE001
        return ""


def extract_owner(remote_url: str) -> str:
    if not remote_url:
        return ""
    # Handles git@github.com:Owner/repo.git and https://github.com/Owner/repo.git
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/", remote_url)
    if not match:
        return ""
    return match.group("owner")


def check_git_identity(expected_owner: str = "UbaidZafar") -> IdentityCheckResult:
    reasons: list[str] = []
    user_name = _run_git(["config", "--get", "user.name"])
    user_email = _run_git(["config", "--get", "user.email"])
    remote_url = _run_git(["remote", "get-url", "origin"])
    owner = extract_owner(remote_url)

    if not user_name:
        reasons.append("git user.name is not set.")
    if not user_email:
        reasons.append("git user.email is not set.")
    if user_name.strip().lower() == "junaid":
        reasons.append("git user.name is set to Junaid; expected Ubaid Zafar identity.")
    if remote_url and owner and owner.lower() != expected_owner.lower():
        reasons.append(
            f"origin owner mismatch: found '{owner}', expected '{expected_owner}'."
        )
    ok = len(reasons) == 0
    return IdentityCheckResult(
        ok=ok,
        user_name=user_name,
        user_email=user_email,
        remote_url=remote_url,
        owner=owner,
        reasons=reasons,
    )

