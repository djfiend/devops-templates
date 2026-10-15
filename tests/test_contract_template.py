#!/usr/bin/env python3
"""Render tests for the `contract` template (stdlib unittest; runs Copier as a subprocess).

Run:  COPIER="copier" python3 -m unittest discover -s tests -v
      (scripts/check.sh sets COPIER to a pinned `uvx … copier`.)

Everything happens in throwaway directories. The template under test is a snapshot of this
working tree committed into a temp git repo and tagged, so uncommitted edits are tested
and Copier sees real PEP 440 tags (the `copier update` round trip needs two of them).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
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
SNAPSHOT = ["copier.yml", "contract"]
MANAGED = [
    ".claude/hooks/main-checkout-guard.py",
    ".claude/hooks/tests/test_main_checkout_guard.py",
    ".claude/settings.json",
    ".gemini/settings.json",
    ".wtconfig",
]
SEEDED = ["AGENTS.md", "CLAUDE.md", ".gitignore"]
ANSWERS = ".copier-answers.contract.yml"


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


class ContractTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name).resolve()
        # Snapshot the template into a git repo with a release tag.
        cls.tpl = cls.base / "tpl"
        cls.tpl.mkdir()
        for name in SNAPSHOT:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(
                    src, cls.tpl / name, ignore=shutil.ignore_patterns("__pycache__")
                )
            else:
                shutil.copy2(src, cls.tpl / name)
        git("init", "-q", "-b", "main", cwd=cls.tpl)
        git("add", "-A", cwd=cls.tpl)
        git("commit", "-q", "-m", "snapshot", cwd=cls.tpl)
        git("tag", "v1.0.0", cwd=cls.tpl)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def new_repo(self, name: str, files: dict[str, str] | None = None) -> Path:
        repo = self.base / name
        repo.mkdir()
        git("init", "-q", "-b", "main", cwd=repo)
        for rel, text in (files or {"README.md": "x\n"}).items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        git("add", "-A", cwd=repo)
        git("commit", "-q", "-m", "init", cwd=repo)
        return repo

    def render(self, repo: Path, *data: str, ref: str = "v1.0.0"):
        args = [
            *COPIER,
            "copy",
            "--defaults",
            "--vcs-ref",
            ref,
            "-d",
            "template=contract",
        ]
        for d in data:
            args += ["-d", d]
        return run(*args, self.tpl, ".", cwd=repo)

    def commit_all(self, repo: Path, msg: str):
        git("add", "-A", cwd=repo)
        git("commit", "-q", "-m", msg, cwd=repo)

    # --- rendering ------------------------------------------------------------------------

    def test_toolkit_like_render(self):
        repo = self.new_repo("toolkit")
        self.render(repo, "gate=scripts/check.sh", 'extra_allow=["devops-test"]')
        for rel in MANAGED + SEEDED + [ANSWERS]:
            self.assertTrue((repo / rel).is_file(), rel)
        self.assertEqual(wtconfig(repo, "wt.base"), ["main"])
        self.assertEqual(wtconfig(repo, "wt.gate"), ["scripts/check.sh"])
        self.assertEqual(wtconfig(repo, "wt.staleDays"), ["7"])
        self.assertEqual(wtconfig(repo, "wt.mainEditAllow"), [])
        settings = json.loads((repo / ".claude/settings.json").read_text())
        perms = settings["permissions"]
        self.assertIn("Bash(scripts/check.sh:*)", perms["allow"])
        self.assertIn("Bash(devops-test:*)", perms["allow"])
        # Baseline from the 2026-10-14 readiness check (finding 7) and the library rules.
        for rule in (
            "Bash(git add .:*)",
            "Bash(git add -A:*)",
            "Bash(git branch -D:*)",
            "Bash(git worktree prune:*)",
            "Bash(git push --force:*)",
        ):
            self.assertIn(rule, perms["deny"])
        self.assertIn("Bash(wt rm:*)", perms["ask"])
        hook = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn(".claude/hooks/main-checkout-guard.py", hook)
        gem = json.loads((repo / ".gemini/settings.json").read_text())
        self.assertEqual(gem["context"]["fileName"], ["AGENTS.md"])
        self.assertIn("@AGENTS.md", (repo / "CLAUDE.md").read_text())
        ignored = git(
            "check-ignore",
            ".worktrees/x",
            ".claude/settings.local.json",
            cwd=repo,
            check=False,
        ).stdout.split()
        self.assertEqual(len(ignored), 2)
        agents = (repo / "AGENTS.md").read_text()
        for section in (
            "What this repo is",
            "Commands",
            "Conventions",
            "Multi-agent operation",
            "Approval boundaries",
            "When you finish",
        ):
            self.assertIn(f"## {section}", agents)
        self.assertIn("`scripts/check.sh`", agents)
        self.assertNotIn("{{", agents)

    def test_library_like_render(self):
        repo = self.new_repo("library")
        self.render(
            repo,
            "gate=python3 scripts/library-lint.py --changed",
            'main_edit_allow=["INDEX.md", "GOVERNANCE.md", "README.md", "claude-outputs/"]',
            "stale_days=10",
        )
        self.assertEqual(
            wtconfig(repo, "wt.mainEditAllow"),
            ["INDEX.md", "GOVERNANCE.md", "README.md", "claude-outputs/"],
        )
        self.assertEqual(wtconfig(repo, "wt.staleDays"), ["10"])
        perms = json.loads((repo / ".claude/settings.json").read_text())["permissions"]
        self.assertIn("Bash(python3 scripts/library-lint.py:*)", perms["allow"])

    def test_seeded_files_are_kept(self):
        own = {
            "AGENTS.md": "# mine\n",
            "CLAUDE.md": "@AGENTS.md\nmine\n",
            ".gitignore": "data/\n",
        }
        repo = self.new_repo("seeded", own)
        self.render(repo)
        for rel, text in own.items():
            self.assertEqual((repo / rel).read_text(), text, rel)

    def test_rendered_hook_tests_pass(self):
        repo = self.new_repo("hooktests")
        self.render(repo)
        run(
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            ".claude/hooks/tests",
            cwd=repo,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
        )

    @unittest.skipUnless(shutil.which("wt"), "wt not installed (devops-workspace)")
    def test_wt_doctor_passes_on_render(self):
        repo = self.new_repo("doctor")
        self.render(repo, "gate=scripts/check.sh")
        (repo / "scripts").mkdir()
        (repo / "scripts/check.sh").write_text("#!/bin/sh\nexit 0\n")
        (repo / "scripts/check.sh").chmod(0o755)
        self.commit_all(repo, "adopt")
        out = run("wt", "doctor", cwd=repo).stdout
        self.assertIn("0 failed", out)

    def test_this_repo_applies_its_own_template(self):
        """The root contract files are an application of contract/ — never hand-edited."""
        repo = self.new_repo("self")
        self.render(repo, "repo_name=devops-templates", "gate=scripts/check.sh")
        for rel in MANAGED:
            with self.subTest(file=rel):
                self.assertEqual(
                    (repo / rel).read_text(),
                    (ROOT / rel).read_text(),
                    f"{rel} differs from a fresh render — run copier update, don't hand-edit",
                )

    # --- updates --------------------------------------------------------------------------

    def test_update_round_trip(self):
        """A template release reaches a repo with `copier update`; local edits survive."""
        repo = self.new_repo("update")
        self.render(repo, 'main_edit_allow=["README.md"]')
        self.commit_all(repo, "adopt contract v1.0.0")
        # A local edit to a managed file, committed (updates need a clean tree).
        with (repo / ".claude/hooks/main-checkout-guard.py").open("a") as f:
            f.write("# local note\n")
        self.commit_all(repo, "local edit")
        # Template v1.0.1: a change to the hook's docstring.
        tpl_hook = self.tpl / "contract/.claude/hooks/main-checkout-guard.py"
        orig = tpl_hook.read_text()
        try:
            tpl_hook.write_text(
                orig.replace("Stdlib only.", "Stdlib only. (v1.0.1)", 1)
            )
            git("commit", "-q", "-am", "v1.0.1", cwd=self.tpl)
            git("tag", "v1.0.1", cwd=self.tpl)
            run(*COPIER, "update", "--defaults", "--answers-file", ANSWERS, cwd=repo)
            hook = (repo / ".claude/hooks/main-checkout-guard.py").read_text()
            self.assertIn("(v1.0.1)", hook)
            self.assertIn("# local note", hook)
            self.assertIn("_commit: v1.0.1", (repo / ANSWERS).read_text())
            self.assertEqual(wtconfig(repo, "wt.mainEditAllow"), ["README.md"])
            status = git("status", "--porcelain", cwd=repo).stdout
            self.assertNotIn(".rej", status)
        finally:
            git("tag", "-d", "v1.0.1", cwd=self.tpl)
            git("reset", "-q", "--hard", "v1.0.0", cwd=self.tpl)

    def test_answer_change_via_update(self):
        """The documented way to change an answer (header of .wtconfig)."""
        repo = self.new_repo("reanswer")
        self.render(repo)
        self.commit_all(repo, "adopt")
        run(
            *COPIER,
            "update",
            "--defaults",
            "--answers-file",
            ANSWERS,
            "--vcs-ref=:current:",
            "-d",
            "stale_days=14",
            cwd=repo,
        )
        self.assertEqual(wtconfig(repo, "wt.staleDays"), ["14"])


if __name__ == "__main__":
    unittest.main()
