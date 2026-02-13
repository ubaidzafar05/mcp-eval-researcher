# RFC: Repository Cleanup

## Context
The user has requested to remove "unneeded files". The codebase has evolved through Phase 8, and some files may be obsolete or redundant.

## Candidates for Removal
Based on a scan of the repository:

1.  **[specs/architecture_RFC.md](file:///c:/pyPractice/mcp-eval-researcher/specs/architecture_RFC.md)**
    - This file was created during Phase 8 planning but is now superseded by the actual implementation and `implementation_plan.md`.
    - **Status**: Obsolete.
    - **Recommendation**: DELETE.

2.  **[.env.compose.example](file:///c:/pyPractice/mcp-eval-researcher/.env.compose.example)**
    - This is a template for Docker Compose environment variables.
    - **Status**: Useful for new users.
    - **Recommendation**: KEEP.

3.  **[scripts/*](file:///c:/pyPractice/mcp-eval-researcher/scripts/)**
    - `check_requirements_sync.py`, `export_requirements.py`, `local_stack_smoke.py`, `preflight_git_identity.py`.
    - These are maintenance and CI scripts referenced in `README.md`.
    - **Status**: Critical / Active.
    - **Recommendation**: KEEP.

4.  **[requirements.txt](file:///c:/pyPractice/mcp-eval-researcher/requirements.txt)**
    - The project uses `poetry`, but `requirements.txt` is often kept for compatibility with tools that don't support poetry.
    - **Status**: Redundant (if strictly using poetry), but potentially useful.
    - **Recommendation**: KEEP (unless user explicitly wants a pure poetry repo).

## Options

### Option A: Conservative (Recommended)
- Remove only `specs/architecture_RFC.md`.
- Keep all transcripts, examples, and scripts.

### Option B: Aggressive
- Remove `specs/architecture_RFC.md`.
- Remove `requirements.txt` (rely solely on `pyproject.toml`).
- Remove `.env.compose.example` (assume users look at `.env.example`).

## Recommendation
**Option A**. The only clearly "unneeded" file created by me during this session that is no longer relevant is the previous RFC. Other files serve a purpose for documentation or CI.

## Action Plan
1. Delete `specs/architecture_RFC.md`.
2. Commit and push.
