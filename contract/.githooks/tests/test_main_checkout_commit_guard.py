#!/usr/bin/env python3
"""Tests for .githooks/pre-commit and pre-merge-commit (stdlib unittest, no network).

Managed by the devops-templates `contract` Copier template, with the hooks.
Run:  python3 -m unittest discover -s .githooks/tests -v
Builds throwaway repos in a temp dir; never touches this repository. Each repo gets a copy
of the hooks committed under .githooks/ and `core.hooksPath=.githooks`, exactly as an
adopting repo has them, and the tests make real commits and merges through git.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]
HOOK_FILES = ("pre-commit", "pre-merge-commit")
OVERRIDE_VARS = ("REPO_ALLOW_MAIN_EDIT", "LIBRARY_ALLOW_MAIN_EDIT")


def git_env(extra=None):
    env = {k: v for k, v in os.environ.items() if k not in OVERRIDE_VARS}
    env.update(
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.invalid",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    env.update(extra or {})
    return env


def git(*args, cwd, env=None, check=True):
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env=git_env(env)
    )
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} -> {r.returncode}\n{r.stderr}")
    return r


def install_hooks(repo: Path):
    (repo / ".githooks").mkdir()
    for name in HOOK_FILES:
        shutil.copy2(HOOKS / name, repo / ".githooks" / name)
    git("config", "core.hooksPath", ".githooks", cwd=repo)


class CommitGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git("init", "-q", "-b", "main", cwd=self.repo)
        install_hooks(self.repo)
        # The scaffold's first commit: no commits yet, so the hook allows it.
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "scaffold", cwd=self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, cwd, name="f.txt", env=None, extra=()):
        (cwd / name).write_text(name + "\n")
        git("add", name, cwd=cwd)
        return git(
            "commit", "-q", *extra, "-m", f"add {name}", cwd=cwd, env=env, check=False
        )

    def worktree(self, branch="feat/x") -> Path:
        path = self.repo / ".worktrees" / branch.replace("/", "-")
        git("worktree", "add", "-q", "-b", branch, str(path), cwd=self.repo)
        return path

    def head_count(self, cwd) -> int:
        return int(git("rev-list", "--count", "HEAD", cwd=cwd).stdout)

    def test_first_commit_in_an_empty_repo_is_allowed(self):
        self.assertEqual(self.head_count(self.repo), 1)

    def test_commit_in_main_checkout_is_refused(self):
        r = self.commit(self.repo)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pre-commit: refusing a commit in the main checkout", r.stderr)
        self.assertIn("wt new <type>/<description>", r.stderr)
        self.assertEqual(self.head_count(self.repo), 1)

    def test_commit_in_linked_worktree_is_allowed(self):
        wt = self.worktree()
        r = self.commit(wt)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.head_count(wt), 2)

    def test_worktree_runs_its_own_checked_out_copy(self):
        # core.hooksPath is relative: a worktree resolves it against its own top level.
        wt = self.worktree()
        marker = self.root / "ran"
        (wt / ".githooks/pre-commit").write_text(
            f"#!/bin/sh\ntouch '{marker}'\nexit 0\n"
        )
        self.assertEqual(self.commit(wt).returncode, 0)
        self.assertTrue(marker.exists())
        self.assertNotEqual(self.commit(self.repo).returncode, 0)

    def test_owner_override_allows_main_checkout_commit(self):
        for i, var in enumerate(OVERRIDE_VARS):
            with self.subTest(var=var):
                r = self.commit(self.repo, name=f"o{i}.txt", env={var: "1"})
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_override_must_be_exactly_1(self):
        r = self.commit(self.repo, env={"REPO_ALLOW_MAIN_EDIT": "yes"})
        self.assertNotEqual(r.returncode, 0)

    def test_merge_commit_in_main_checkout_is_refused(self):
        wt = self.worktree()
        self.assertEqual(self.commit(wt).returncode, 0)
        r = git("merge", "--no-ff", "--no-edit", "feat/x", cwd=self.repo, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pre-merge-commit: refusing a merge commit", r.stderr)
        self.assertEqual(self.head_count(self.repo), 1)

    def test_merge_commit_in_linked_worktree_is_allowed(self):
        # Keeping a topic branch current (`git merge main`) happens in its worktree.
        wt = self.worktree()
        self.assertEqual(self.commit(wt, name="a.txt").returncode, 0)
        other = self.worktree("feat/y")
        self.assertEqual(self.commit(other, name="b.txt").returncode, 0)
        r = git("merge", "--no-ff", "--no-edit", "feat/y", cwd=wt, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_fast_forward_sync_of_main_is_not_a_commit(self):
        # `git merge --ff-only` / `git pull --ff-only` moves main without committing.
        wt = self.worktree()
        self.assertEqual(self.commit(wt).returncode, 0)
        r = git("merge", "--ff-only", "feat/x", cwd=self.repo, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_verify_skips_the_hook(self):
        # Documented limit: the server-side ruleset is the enforcement.
        r = self.commit(self.repo, extra=("--no-verify",))
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
