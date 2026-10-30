#!/usr/bin/env python3
"""Render tests for the `project` template, alone and layered with `contract`.

Run:  COPIER="copier" python3 -m unittest discover -s tests -v
      (scripts/check.sh sets COPIER and YAMLLINT to pinned uvx commands.)

Each project type renders an exact file set with nothing left unrendered and valid
YAML/TOML/JSON; `project` then `contract` gives a repo that meets the contract; and a
template release reaches a scaffold through `copier update` without touching its seeded
files. Running every scaffold's own gate is scripts/scaffold-gates.sh (gate step 9).
"""

from __future__ import annotations

import json
import keyword
import os
import re
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import COPIER, commit_all, files_in, git, new_repo, run, snapshot, wtconfig

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: TOML parsing is checked on 3.11+ only
    tomllib = None

YAMLLINT = shlex.split(os.environ.get("YAMLLINT", "yamllint"))
ANSWERS = ".copier-answers.project.yml"
TYPES = ("python", "bash", "generic", "ansible", "docker", "terraform")

# Every type renders these (plus the answers file).
SHARED = {
    ".clinerules",
    ".editorconfig",
    ".github/copilot-instructions.md",
    ".github/dependabot.yml",
    ".github/workflows/check.yml",
    ".gitignore",
    "AGENTS.md",
    "CHANGELOG.md",
    "README.md",
    "scripts/check.sh",
}
EXPECTED = {
    "python": {
        ".vscode/settings.json",
        "pyproject.toml",
        "ruff.toml",
        "src/demo_app/__init__.py",
        "src/demo_app/__main__.py",
        "tests/test_smoke.py",
    },
    "bash": {"scripts/main.sh", "scripts/lib.sh", "tests/main.bats"},
    "generic": set(),
    "ansible": {
        ".ansible-lint",
        ".yamllint",
        "ansible.cfg",
        "inventory/group_vars/all.yml",
        "inventory/hosts.yml",
        "playbooks/site.yml",
        "requirements.yml",
        "roles/.gitkeep",
    },
    "docker": {
        ".dockerignore",
        ".env.example",
        "Dockerfile",
        "compose.yaml",
        "requirements.txt",
        "ruff.toml",
        "src/main.py",
    },
    "terraform": {
        ".tflint.hcl",
        "environments/dev/terraform.tfvars.example",
        "environments/prod/terraform.tfvars.example",
        "environments/staging/terraform.tfvars.example",
        "main.tf",
        "outputs.tf",
        "variables.tf",
        "versions.tf",
    },
}
# Contract C1.2: the sections `wt doctor` requires in AGENTS.md.
AGENTS_SECTIONS = (
    "What this repo is",
    "Commands",
    "Conventions",
    "Multi-agent operation",
    "Approval boundaries",
    "When you finish",
)
# A Copier variable or tag that survived rendering. Legitimate look-alikes don't match:
# Ansible's own `{{ … }}` in playbooks, GitHub's `${{ … }}`, bash's `${#array[@]}`.
UNRENDERED = re.compile(
    r"(?<!\$)\{[%#]|\{\{\s*(?:repo_|project_|package_|python_min|base\b|stale_|template\b|_copier)"
)


class ProjectTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name).resolve()
        cls.tpl = snapshot(cls.base / "tpl", "v1.1.0")
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def repo(self, name: str = "demo-app") -> Path:
        """A fresh, empty repo whose directory name is `name` (the default repo_name)."""
        type(self).n += 1
        parent = self.base / f"r{self.n}"
        parent.mkdir()
        return new_repo(parent / name)

    def copier(self, repo: Path, template: str, *data: str, ref="v1.1.0", check=True):
        args = [
            *COPIER,
            "copy",
            "--defaults",
            "--vcs-ref",
            ref,
            "-d",
            f"template={template}",
        ]
        for d in data:
            args += ["-d", d]
        return run(*args, self.tpl, ".", cwd=repo, check=check)

    def project(self, repo: Path, project_type: str, *data: str, **kw):
        return self.copier(repo, "project", f"project_type={project_type}", *data, **kw)

    def layered(self, project_type: str, *data: str) -> Path:
        """What devops-new does: project, then contract, then a first commit."""
        repo = self.repo()
        self.project(repo, project_type, *data)
        self.copier(repo, "contract")
        commit_all(repo, "scaffold")
        return repo

    # --- each type on its own ----------------------------------------------------------

    def test_each_type_renders_its_file_set(self):
        for t in TYPES:
            with self.subTest(project_type=t):
                repo = self.repo()
                self.project(repo, t, "repo_description=A demo.")
                self.assertEqual(files_in(repo), SHARED | EXPECTED[t] | {ANSWERS})
                self.assertTrue(os.access(repo / "scripts/check.sh", os.X_OK))
                for rel in files_in(repo):
                    text = (repo / rel).read_text()
                    self.assertIsNone(
                        UNRENDERED.search(text), f"{rel}: unrendered Jinja"
                    )
                    self.assertTrue(
                        text == "" or text.endswith("\n"), f"{rel}: no final newline"
                    )
                agents = (repo / "AGENTS.md").read_text()
                for section in AGENTS_SECTIONS:
                    self.assertIn(f"## {section}", agents)
                self.assertIn("A demo.", agents)
                self.assertIn("`scripts/check.sh`", agents)
                self.assertNotIn("TODO: build, test and run commands.\n\n", agents)
                ignored = git(
                    "check-ignore",
                    ".worktrees/x",
                    ".claude/settings.local.json",
                    cwd=repo,
                    check=False,
                ).stdout.split()
                self.assertEqual(len(ignored), 2, "contract C3.1/C8.3 ignores")

    def test_rendered_files_parse(self):
        for t in TYPES:
            with self.subTest(project_type=t):
                repo = self.repo()
                self.project(repo, t)
                yamls = sorted(
                    f for f in files_in(repo) if f.endswith((".yml", ".yaml"))
                )
                # Syntax only (relaxed rules); the scaffold's own gate holds the style rules.
                run(
                    *YAMLLINT,
                    "-d",
                    "{extends: relaxed, rules: {line-length: disable}}",
                    *yamls,
                    cwd=repo,
                )
                for f in files_in(repo):
                    if f.endswith(".json"):
                        json.loads((repo / f).read_text())
                    if f.endswith(".toml") and tomllib:
                        tomllib.loads((repo / f).read_text())

    def test_python_keywords_are_rejected_before_rendering(self):
        for name in keyword.kwlist:
            # Kebab-case already rejects capitalized keywords (True/False/None).
            if not name.islower():
                continue
            with self.subTest(name=name):
                repo = self.repo(name)
                result = self.project(repo, "python", check=False)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Python keyword", result.stdout + result.stderr)
                self.assertEqual(files_in(repo), set())

    def test_explicit_python_keyword_is_rejected(self):
        repo = self.repo()
        result = self.project(repo, "python", "repo_name=class", check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Python keyword", result.stdout + result.stderr)
        self.assertEqual(files_in(repo), set())

    def test_python_import_names_compile(self):
        for name in ("my-tool", "class-tool", "match", "case", "type"):
            with self.subTest(name=name):
                repo = self.repo(name)
                self.project(repo, "python")
                package = name.replace("-", "_")
                self.assertTrue((repo / "src" / package / "__main__.py").is_file())
                for path in repo.rglob("*.py"):
                    compile(path.read_bytes(), str(path), "exec")

    def test_keyword_names_remain_legal_for_other_project_types(self):
        for project_type in TYPES:
            if project_type == "python":
                continue
            with self.subTest(project_type=project_type):
                repo = self.repo("class")
                self.project(repo, project_type)
                self.assertTrue((repo / ANSWERS).is_file())

    def test_contract_accepts_python_keyword_repository_name(self):
        repo = self.repo("class")
        self.copier(repo, "contract")
        self.assertTrue((repo / ".wtconfig").is_file())

    def test_python_answers_reach_the_files(self):
        repo = self.repo("my-tool")
        self.project(repo, "python", "python_min=3.12", 'repo_description=Says "hi".')
        pyproject = (repo / "pyproject.toml").read_text()
        self.assertIn('name = "my-tool"', pyproject)
        self.assertIn('requires-python = ">=3.12"', pyproject)
        self.assertIn('my-tool = "my_tool.__main__:main"', pyproject)
        self.assertIn('description = "Says \\"hi\\"."', pyproject)
        if tomllib:
            self.assertEqual(
                tomllib.loads(pyproject)["project"]["description"], 'Says "hi".'
            )
        self.assertIn('target-version = "py312"', (repo / "ruff.toml").read_text())
        self.assertIn(
            'python: ["3.12", "3.14"]',
            (repo / ".github/workflows/check.yml").read_text(),
        )
        self.assertTrue((repo / "src/my_tool/__main__.py").is_file())

    def test_project_name_must_be_kebab_case(self):
        repo = self.repo("Not_Kebab")
        r = self.project(repo, "generic", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("kebab-case", r.stdout + r.stderr)
        self.assertFalse((repo / ANSWERS).exists())

    def test_answers_file_records_the_project(self):
        repo = self.repo()
        self.project(repo, "docker")
        answers = (repo / ANSWERS).read_text()
        for line in (
            "_commit: v1.1.0",
            "template: project",
            "project_type: docker",
            "python_min: '3.10'",
            "repo_name: demo-app",
        ):
            self.assertIn(line, answers)
        for key in ("gate:", "main_edit_allow:", "extra_allow:", "package_name:"):
            self.assertNotIn(key, answers)

    # --- layered with the contract ------------------------------------------------------

    def test_layered_with_contract(self):
        repo = self.layered("python")
        for rel in (
            ".copier-answers.project.yml",
            ".copier-answers.contract.yml",
            ".wtconfig",
            "CLAUDE.md",
            ".claude/settings.json",
            ".gemini/settings.json",
        ):
            self.assertTrue((repo / rel).is_file(), rel)
        # The project's seeded files win; the contract seeds only what is missing.
        agents = (repo / "AGENTS.md").read_text()
        self.assertIn("uv run pytest", agents)
        self.assertIn("`project` template (`.copier-answers.project.yml`", agents)
        gitignore = (repo / ".gitignore").read_text()
        self.assertIn(".venv/", gitignore)
        self.assertIn(".worktrees/", gitignore)
        self.assertEqual(wtconfig(repo, "wt.gate"), ["scripts/check.sh"])
        perms = json.loads((repo / ".claude/settings.json").read_text())["permissions"]
        self.assertIn("Bash(scripts/check.sh:*)", perms["allow"])
        self.assertEqual(git("status", "--porcelain", cwd=repo).stdout, "")

    @unittest.skipUnless(shutil.which("wt"), "wt not installed (devops-workspace)")
    def test_wt_doctor_passes_on_every_layered_type(self):
        for t in TYPES:
            with self.subTest(project_type=t):
                out = run("wt", "doctor", cwd=self.layered(t)).stdout
                self.assertIn("0 failed", out)

    # --- the seeded gate's modes -----------------------------------------------------------

    def test_gate_rejects_strict_with_offline(self):
        repo = self.layered("generic")
        for args in (["--strict", "--offline"], ["--offline", "--strict"], ["--bogus"]):
            with self.subTest(args=args):
                r = run("scripts/check.sh", *args, cwd=repo, check=False)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertNotIn("GATE", r.stdout)

    def test_gate_offline_runs_from_the_uv_cache(self):
        """Contract C5.4: after one online run, --offline passes with UV_OFFLINE=1."""
        repo = self.layered("generic")
        # One online run warms the uv cache (a no-op when it is already warm).
        run("scripts/check.sh", cwd=repo)
        r = run("scripts/check.sh", "--offline", cwd=repo, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("(offline)", r.stdout)
        self.assertIn("GATE PASSED", r.stdout)

    # --- updates --------------------------------------------------------------------------

    def test_update_round_trip(self):
        """A release reaches a scaffold via `copier update`; seeded files stay the repo's."""
        repo = self.layered("bash")
        # Local edits: a seeded file and a managed one.
        (repo / "README.md").write_text("# mine\n")
        with (repo / ".editorconfig").open("a") as f:
            f.write("\n[*.local]\nindent_size = 8\n")
        commit_all(repo, "local edits")
        gate_before = (repo / "scripts/check.sh").read_text()
        # Template v1.1.1 changes a managed file and two seeded ones.
        edits = {
            "project/.editorconfig": ("root = true\n", "root = true\n# v1.1.1\n"),
            "project/README.md.jinja": ("## Development", "## Development (v1.1.1)"),
            "project/scripts/check.sh.jinja": (
                "set -euo pipefail\n",
                "set -euo pipefail\n# v1.1.1\n",
            ),
        }
        originals = {}
        try:
            for rel, (old, new) in edits.items():
                p = self.tpl / rel
                originals[p] = p.read_text()
                p.write_text(originals[p].replace(old, new, 1))
            git("commit", "-q", "-am", "v1.1.1", cwd=self.tpl)
            git("tag", "v1.1.1", cwd=self.tpl)
            run(*COPIER, "update", "--defaults", "--answers-file", ANSWERS, cwd=repo)
            editorconfig = (repo / ".editorconfig").read_text()
            self.assertIn("# v1.1.1", editorconfig)
            self.assertIn("[*.local]", editorconfig)
            self.assertEqual((repo / "README.md").read_text(), "# mine\n")
            self.assertEqual((repo / "scripts/check.sh").read_text(), gate_before)
            self.assertIn("_commit: v1.1.1", (repo / ANSWERS).read_text())
            self.assertIn(
                "_commit: v1.1.0", (repo / ".copier-answers.contract.yml").read_text()
            )
            self.assertNotIn(".rej", git("status", "--porcelain", cwd=repo).stdout)
        finally:
            git("tag", "-d", "v1.1.1", cwd=self.tpl, check=False)
            git("reset", "-q", "--hard", "v1.1.0", cwd=self.tpl)

    def test_answer_change_via_update(self):
        repo = self.layered("python")
        run(
            *COPIER,
            "update",
            "--defaults",
            "--answers-file",
            ANSWERS,
            "--vcs-ref=:current:",
            "-d",
            "python_min=3.11",
            cwd=repo,
        )
        self.assertIn(
            'requires-python = ">=3.11"', (repo / "pyproject.toml").read_text()
        )
        # The CI workflow is seeded: an answer change does not rewrite it.
        self.assertIn(
            'python: ["3.10", "3.14"]',
            (repo / ".github/workflows/check.yml").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
