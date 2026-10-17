"""Shared helpers for the render tests (stdlib only; Copier runs as a subprocess).

The template under test is a snapshot of this working tree committed into a temp git repo
and tagged, so uncommitted edits are tested and Copier sees real PEP 440 tags.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIER = shlex.split(os.environ.get("COPIER", "copier"))
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}
# Everything Copier reads: the config, every template subdirectory, the shared partials.
SNAPSHOT = ["copier.yml", "contract", "project", "includes"]


def run(*args, cwd, check=True, env=None):
    r = subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV, **(env or {})},
    )
    if check and r.returncode != 0:
        raise AssertionError(
            f"{shlex.join(map(str, args))} -> {r.returncode}\n{r.stdout}\n{r.stderr}"
        )
    return r


def git(*args, cwd, check=True):
    return run("git", *args, cwd=cwd, check=check)


def wtconfig(repo: Path, key: str) -> list[str]:
    out = git("config", "-f", ".wtconfig", "--get-all", key, cwd=repo, check=False)
    return out.stdout.split("\n")[:-1] if out.returncode == 0 else []


def snapshot(dest: Path, tag: str) -> Path:
    """Copy the template into a new git repo at `dest`, commit it and tag it."""
    dest.mkdir()
    for name in SNAPSHOT:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(
                src, dest / name, ignore=shutil.ignore_patterns("__pycache__")
            )
        else:
            shutil.copy2(src, dest / name)
    git("init", "-q", "-b", "main", cwd=dest)
    git("add", "-A", cwd=dest)
    git("commit", "-q", "-m", "snapshot", cwd=dest)
    git("tag", tag, cwd=dest)
    return dest


def new_repo(path: Path, files: dict[str, str] | None = None) -> Path:
    """An empty git repo, optionally with an initial commit of `files`."""
    path.mkdir()
    git("init", "-q", "-b", "main", cwd=path)
    if files:
        for rel, text in files.items():
            p = path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        git("add", "-A", cwd=path)
        git("commit", "-q", "-m", "init", cwd=path)
    return path


def commit_all(repo: Path, msg: str):
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", msg, cwd=repo)


def files_in(repo: Path) -> set[str]:
    """Every file in a rendered repo, relative, outside .git."""
    return {
        p.relative_to(repo).as_posix()
        for p in repo.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(repo).parts[:1]
    }
