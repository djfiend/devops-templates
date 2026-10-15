#!/usr/bin/env python3
"""PreToolUse hook: keep the MAIN checkout an integration point, not a workspace.

Managed by the devops-templates `contract` Copier template (multi-agent ready
contract C10.1) — change it there, not in an adopting repo; `copier update`
brings the change here.

Blocks Claude Code's file-edit tools (Edit/Write/MultiEdit/NotebookEdit) on files in a
repository's MAIN checkout, so every unit of work happens in its own worktree on its own
topic branch (`wt new <type>/<description>`; see AGENTS.md § Multi-agent operation).

The decision is made from the TARGET file, not from where the session runs (library audit
2026-10-14, finding 1). The target is resolved first — relative paths against the session
directory, symlinks followed, and a file that does not exist yet is classified by its
nearest existing parent directory — and then:

  target in a main checkout  -> blocked, unless the path is allowed (below), when that
                                repository is the session's own or has adopted the contract
                                (has a .wtconfig). Other repositories are not policed.
  target in a linked worktree-> allowed, except from a session running in a DIFFERENT linked
                                worktree of the same repository (one worker per worktree)
  target outside any repo    -> allowed

Allowed in a main checkout:
  - files under .worktrees/ (worktree directories, including ones not created yet)
  - paths listed in that repository's .wtconfig as wt.mainEditAllow (multi-valued),
    matched gitignore-style against the repo-relative path:
        README.md        no slash   -> that file name anywhere in the repo
        claude-outputs/  trailing / -> everything under that top-level directory
        docs/*.md        otherwise  -> fnmatch on the full relative path

Owner override: REPO_ALLOW_MAIN_EDIT=1 (LIBRARY_ALLOW_MAIN_EDIT=1 is honoured as a legacy alias).

Limits: only Claude Code's file-edit tools are checked — shell writes (sed -i, heredocs)
are not. Fails open on malformed input or git errors, so a bug here can never brick a
session. Exit 2 = block (stderr is shown to the model); exit 0 = allow. Stdlib only.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import NamedTuple

OVERRIDE_VARS = ("REPO_ALLOW_MAIN_EDIT", "LIBRARY_ALLOW_MAIN_EDIT")
ALWAYS_ALLOWED_TOP_DIRS = {".worktrees"}


class Checkout(NamedTuple):
    top: Path  # working-tree root of the checkout
    common: Path  # the repository's shared git dir (same for main and all worktrees)
    linked: bool  # True for a linked worktree, False for the main checkout


def git(cwd: Path, *args: str) -> str | None:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(var, None)
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env
        )
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def checkout_of(path: Path) -> Checkout | None:
    """The checkout that owns `path` (an existing directory), or None outside git."""
    out = git(
        path,
        "rev-parse",
        "--path-format=absolute",
        "--show-toplevel",
        "--absolute-git-dir",
        "--git-common-dir",
    )
    if not out:
        return None
    lines = out.splitlines()
    if len(lines) != 3:
        return None
    top, git_dir, common = (Path(p).resolve() for p in lines)
    return Checkout(top, common, git_dir != common)


def existing_dir(path: Path) -> Path:
    """`path` itself if it is a directory, else its nearest existing parent directory."""
    p = path
    while not p.is_dir():
        if p.parent == p:
            break
        p = p.parent
    return p


def allow_patterns(top: Path) -> list[str]:
    cfg = top / ".wtconfig"
    if not cfg.is_file():
        return []
    out = git(top, "config", "-f", str(cfg), "--get-all", "wt.mainEditAllow") or ""
    return [line.strip() for line in out.splitlines() if line.strip()]


def is_allowed(rel: PurePosixPath, patterns: list[str]) -> bool:
    if rel.parts and rel.parts[0] in ALWAYS_ALLOWED_TOP_DIRS:
        return True
    posix = rel.as_posix()
    for pat in patterns:
        if pat.endswith("/"):
            if posix.startswith(pat.lstrip("/")):
                return True
        elif "/" not in pat:
            if fnmatch.fnmatchcase(rel.name, pat):
                return True
        elif fnmatch.fnmatchcase(posix, pat.lstrip("/")):
            return True
    return False


def block(message: str) -> int:
    sys.stderr.write(message)
    return 2


def main() -> int:
    if any(os.environ.get(v) == "1" for v in OVERRIDE_VARS):
        return 0
    try:
        payload = json.load(sys.stdin)
        tool_input = payload.get("tool_input") or {}
        target = tool_input.get("file_path") or tool_input.get("notebook_path")
    except Exception:
        return 0
    if not target or not isinstance(target, str):
        return 0

    try:
        project = Path(
            os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "."
        ).resolve()
        path = Path(target).expanduser()
        path = (path if path.is_absolute() else project / path).resolve()
    except (OSError, RuntimeError, ValueError):
        return 0

    owner = checkout_of(existing_dir(path))
    if owner is None:
        return 0  # outside any repository
    session = checkout_of(existing_dir(project))
    same_repo = session is not None and session.common == owner.common

    if owner.linked:
        if same_repo and session.linked and session.top != owner.top:
            return block(
                f"BLOCKED: '{path}' is in another worktree ({owner.top}).\n"
                f"This session works in {session.top}. One worker per worktree: edit only your own,\n"
                "and hand anything else back to the owner. See AGENTS.md § Multi-agent operation.\n"
                "Owner-only override: REPO_ALLOW_MAIN_EDIT=1\n"
            )
        return 0

    # Target is in a main checkout. Police it only for the session's own repository or a
    # repository that has adopted the contract.
    if not same_repo and not (owner.top / ".wtconfig").is_file():
        return 0
    try:
        rel = PurePosixPath(path.relative_to(owner.top).as_posix())
    except ValueError:
        return 0
    if is_allowed(rel, allow_patterns(owner.top)):
        return 0
    return block(
        f"BLOCKED: '{rel}' is in the MAIN checkout of {owner.top}, which is an integration\n"
        "point, not a workspace. Do your work in a worktree on its own topic branch:\n"
        "    wt new <type>/<description>     # prints the worktree path\n"
        "then start (or cd) your session inside that path. See AGENTS.md § Multi-agent operation.\n"
        "Owner-only override: REPO_ALLOW_MAIN_EDIT=1\n"
    )


if __name__ == "__main__":
    sys.exit(main())
