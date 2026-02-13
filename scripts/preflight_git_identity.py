from __future__ import annotations

import os

from core.identity import check_git_identity


def run_preflight(expected_owner: str) -> int:
    result = check_git_identity(expected_owner=expected_owner)
    if result.ok:
        print("Git identity preflight passed.")
        return 0

    print("Git identity preflight failed:")
    for reason in result.reasons:
        print(f"- {reason}")
    print("\nRecommended fixes:")
    print('  git config user.name "Ubaid Zafar"')
    print('  git config user.email "your-email@example.com"')
    print(f"  git remote set-url origin git@github.com:{expected_owner}/<repo>.git")
    return 1


def main() -> int:
    expected_owner = os.getenv("EXPECTED_GITHUB_OWNER", "UbaidZafar")
    return run_preflight(expected_owner)


if __name__ == "__main__":
    raise SystemExit(main())

