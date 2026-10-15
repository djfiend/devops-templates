#!/usr/bin/env python3
"""Tests for .claude/hooks/main-checkout-guard.py (stdlib unittest, no network).

Managed by the devops-templates `contract` Copier template, with the hook.
Run:  python3 -m unittest discover -s .claude/hooks/tests -v
Builds throwaway repos in a temp dir; never touches this repository. These call the hook
directly with a PreToolUse payload: they prove the decision logic, not that Claude Code
dispatches the hook (that needs a live session).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "main-checkout-guard.py"


def sh(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    sh("git", "init", "-q", "-b", "main", cwd=path)
    (path / "content.md").write_text("x\n")
    sh("git", "add", "content.md", cwd=path)
    sh(
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "-m",
        "init",
        cwd=path,
    )
    return path


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.repo = init_repo(self.root / "repo")

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, file_path, project=None, env_extra=None, raw=None):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("REPO_ALLOW_MAIN_EDIT", "LIBRARY_ALLOW_MAIN_EDIT")
        }
        env["CLAUDE_PROJECT_DIR"] = str(project or self.repo)
        env.update(env_extra or {})
        stdin = (
            raw
            if raw is not None
            else json.dumps({"tool_input": {"file_path": str(file_path)}})
        )
        r = subprocess.run(
            [sys.executable, str(HOOK)],
            input=stdin,
            text=True,
            capture_output=True,
            env=env,
        )
        return r.returncode, r.stderr

    def write_cfg(self, *allow, repo=None):
        lines = ["[wt]", "\tbase = main"] + [f"\tmainEditAllow = {a}" for a in allow]
        ((repo or self.repo) / ".wtconfig").write_text("\n".join(lines) + "\n")

    def worktree(self, slug, branch):
        wt = self.repo / ".worktrees" / slug
        sh("git", "worktree", "add", "-q", "-b", branch, str(wt), cwd=self.repo)
        return wt

    # --- session in the main checkout -------------------------------------------------------

    def test_blocks_main_checkout_edit(self):
        code, err = self.run_hook(self.repo / "lib" / "x.py")
        self.assertEqual(code, 2)
        self.assertIn("BLOCKED: 'lib/x.py'", err)

    def test_relative_path_resolved_against_project(self):
        self.assertEqual(self.run_hook("AGENTS.md")[0], 2)

    def test_allows_worktrees_dir(self):
        self.assertEqual(self.run_hook(self.repo / ".worktrees" / "a" / "f")[0], 0)

    def test_main_session_may_edit_a_worktree(self):
        wt = self.worktree("chore-x", "chore/x")
        self.assertEqual(self.run_hook(wt / "lib" / "x.py")[0], 0)

    def test_allows_outside_repo(self):
        self.assertEqual(self.run_hook(self.root / "elsewhere.txt")[0], 0)

    def test_allows_non_git_project(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual(self.run_hook(plain / "f", project=plain)[0], 0)

    def test_override_env(self):
        for var in ("REPO_ALLOW_MAIN_EDIT", "LIBRARY_ALLOW_MAIN_EDIT"):
            with self.subTest(var=var):
                self.assertEqual(
                    self.run_hook(self.repo / "f", env_extra={var: "1"})[0], 0
                )

    def test_fails_open_on_bad_input(self):
        self.assertEqual(self.run_hook("", raw="not json")[0], 0)
        self.assertEqual(self.run_hook("", raw=json.dumps({"tool_input": {}}))[0], 0)
        self.assertEqual(
            self.run_hook("", raw=json.dumps({"tool_input": {"file_path": 7}}))[0], 0
        )

    def test_no_allowlist_without_wtconfig_key(self):
        self.write_cfg()
        self.assertEqual(self.run_hook(self.repo / "README.md")[0], 2)

    def test_allow_name_anywhere(self):
        self.write_cfg("README.md")
        self.assertEqual(self.run_hook(self.repo / "README.md")[0], 0)
        self.assertEqual(self.run_hook(self.repo / "docs" / "README.md")[0], 0)
        self.assertEqual(self.run_hook(self.repo / "docs" / "other.md")[0], 2)

    def test_allow_directory_prefix(self):
        self.write_cfg("claude-outputs/")
        self.assertEqual(
            self.run_hook(self.repo / "claude-outputs" / "a" / "b.md")[0], 0
        )
        self.assertEqual(
            self.run_hook(self.repo / "x" / "claude-outputs" / "b.md")[0], 2
        )

    def test_allow_path_glob(self):
        self.write_cfg("docs/*.md")
        self.assertEqual(self.run_hook(self.repo / "docs" / "a.md")[0], 0)
        self.assertEqual(self.run_hook(self.repo / "docs" / "a.txt")[0], 2)

    def test_library_equivalent_config(self):
        self.write_cfg("INDEX.md", "GOVERNANCE.md", "README.md", "claude-outputs/")
        for ok in (
            "INDEX.md",
            "GOVERNANCE.md",
            "plans/README.md",
            "claude-outputs/q.md",
        ):
            with self.subTest(path=ok):
                self.assertEqual(self.run_hook(self.repo / ok)[0], 0)
        self.assertEqual(self.run_hook(self.repo / "AGENTS.md")[0], 2)

    # --- session in a linked worktree (audit 2026-10-14, finding 1) -------------------------

    def test_worker_own_tree_allowed(self):
        wt = self.worktree("feat-a", "feat/a")
        self.assertEqual(self.run_hook(wt / "content.md", project=wt)[0], 0)
        self.assertEqual(self.run_hook(wt / "new" / "dir" / "f.md", project=wt)[0], 0)
        self.assertEqual(self.run_hook("content.md", project=wt)[0], 0)

    def test_worker_absolute_path_into_main_blocked(self):
        wt = self.worktree("feat-a", "feat/a")
        code, err = self.run_hook(self.repo / "content.md", project=wt)
        self.assertEqual(code, 2)
        self.assertIn("MAIN checkout", err)

    def test_worker_new_file_in_main_blocked(self):
        wt = self.worktree("feat-a", "feat/a")
        self.assertEqual(
            self.run_hook(self.repo / "brand" / "new" / "f.md", project=wt)[0], 2
        )

    def test_worker_relative_path_into_main_blocked(self):
        wt = self.worktree("feat-a", "feat/a")
        self.assertEqual(self.run_hook("../../content.md", project=wt)[0], 2)

    def test_worker_symlink_into_main_blocked(self):
        wt = self.worktree("feat-a", "feat/a")
        (wt / "link.md").symlink_to(self.repo / "content.md")
        (wt / "linkdir").symlink_to(self.repo)
        self.assertEqual(self.run_hook(wt / "link.md", project=wt)[0], 2)
        self.assertEqual(self.run_hook(wt / "linkdir" / "new.md", project=wt)[0], 2)

    def test_worker_into_other_worktree_blocked(self):
        a = self.worktree("feat-a", "feat/a")
        b = self.worktree("feat-b", "feat/b")
        code, err = self.run_hook(b / "content.md", project=a)
        self.assertEqual(code, 2)
        self.assertIn("another worktree", err)
        self.assertEqual(self.run_hook(b / "new.md", project=a)[0], 2)

    def test_worker_allowlisted_main_file_allowed(self):
        self.write_cfg("claude-outputs/")
        wt = self.worktree("feat-a", "feat/a")
        self.assertEqual(
            self.run_hook(self.repo / "claude-outputs" / "n.md", project=wt)[0], 0
        )

    def test_worker_outside_repo_allowed(self):
        wt = self.worktree("feat-a", "feat/a")
        self.assertEqual(self.run_hook(self.root / "scratch.txt", project=wt)[0], 0)

    # --- other repositories ---------------------------------------------------------------

    def test_unrelated_repo_without_contract_not_policed(self):
        other = init_repo(self.root / "other")
        self.assertEqual(self.run_hook(other / "content.md")[0], 0)

    def test_unrelated_repo_with_contract_is_policed(self):
        other = init_repo(self.root / "other")
        self.write_cfg("README.md", repo=other)
        self.assertEqual(self.run_hook(other / "content.md")[0], 2)
        self.assertEqual(self.run_hook(other / "README.md")[0], 0)


if __name__ == "__main__":
    unittest.main()
