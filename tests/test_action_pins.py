#!/usr/bin/env python3
"""Unit tests for scripts/check_action_pins.py (stdlib unittest; no Copier, no network)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT

_spec = importlib.util.spec_from_file_location(
    "check_action_pins", ROOT / "scripts" / "check_action_pins.py"
)
pins = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pins  # dataclasses looks its module up
_spec.loader.exec_module(pins)

SHA_A = "a" * 40
SHA_B = "b" * 40


def wf(*uses: str) -> str:
    steps = "\n".join(f"      - uses: {u}" for u in uses)
    return f"jobs:\n  gate:\n    steps:\n{steps}\n"


class ParseTests(unittest.TestCase):
    def test_pinned_with_comment(self):
        found, errors = pins.parse(wf(f"actions/checkout@{SHA_A} # v7.0.1"), "x")
        self.assertEqual(errors, [])
        self.assertEqual(
            [(p.action, p.ref, p.version) for p in found],
            [("actions/checkout", SHA_A, "v7.0.1")],
        )

    def test_tag_ref_is_an_error(self):
        _, errors = pins.parse(wf("actions/checkout@v7 # v7"), "x")
        self.assertEqual(len(errors), 1)
        self.assertIn("full commit SHA", errors[0])

    def test_missing_version_comment_is_an_error(self):
        _, errors = pins.parse(wf(f"actions/checkout@{SHA_A}"), "x")
        self.assertIn("version comment", errors[0])

    def test_local_and_docker_uses_ignored(self):
        found, errors = pins.parse(wf("./.github/actions/x", "docker://alpine:3"), "x")
        self.assertEqual((found, errors), ([], []))

    def test_uses_without_list_dash(self):
        text = f"    steps:\n      - name: a\n        uses: o/r@{SHA_A} # v1\n"
        found, _ = pins.parse(text, "x")
        self.assertEqual(found[0].where, "x:3")


class CompareTests(unittest.TestCase):
    def _cmp(self, repo_text: str, tmpl_text: str) -> list[str]:
        repo, e1 = pins.parse(repo_text, "repo.yml")
        tmpl, e2 = pins.parse(tmpl_text, "tmpl.yml.jinja")
        return e1 + e2 + pins.compare(repo, tmpl)

    def test_matching_pins_pass(self):
        text = wf(f"o/r@{SHA_A} # v1.0.0")
        self.assertEqual(self._cmp(text, text), [])

    def test_repo_only_action_is_fine(self):
        repo = wf(f"o/r@{SHA_A} # v1", f"o/py@{SHA_B} # v2")
        self.assertEqual(self._cmp(repo, wf(f"o/r@{SHA_A} # v1")), [])

    def test_sha_drift_fails(self):
        errors = self._cmp(wf(f"o/r@{SHA_B} # v1.0.1"), wf(f"o/r@{SHA_A} # v1.0.0"))
        self.assertEqual(len(errors), 1)
        self.assertIn("copy the repo pin", errors[0])

    def test_version_comment_drift_fails(self):
        errors = self._cmp(wf(f"o/r@{SHA_A} # v1.0.1"), wf(f"o/r@{SHA_A} # v1.0.0"))
        self.assertEqual(len(errors), 1)

    def test_template_only_action_fails(self):
        errors = self._cmp(wf(f"o/r@{SHA_A} # v1"), wf(f"o/other@{SHA_A} # v1"))
        self.assertEqual(len(errors), 1)
        self.assertIn("Dependabot", errors[0])

    def test_two_pins_on_one_side_fail(self):
        tmpl = wf(f"o/r@{SHA_A} # v1") + wf(f"o/r@{SHA_B} # v2")
        errors = self._cmp(wf(f"o/r@{SHA_A} # v1"), tmpl)
        self.assertTrue(any("within the templates" in e for e in errors), errors)


class CheckTests(unittest.TestCase):
    def _tree(self, repo_text: str, tmpl_text: str) -> Path:
        root = self._tmp()
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".github" / "workflows" / "check.yml").write_text(repo_text)
        t = root / "project" / ".github" / "workflows"
        t.mkdir(parents=True)
        (t / "check.yml.jinja").write_text(tmpl_text)
        return root

    def _tmp(self) -> Path:  # TestCase.enterContext is 3.11+; the floor is 3.10
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return Path(d.name)

    def test_tree_in_sync(self):
        text = wf(f"o/r@{SHA_A} # v1")
        errors, n = pins.check(self._tree(text, text))
        self.assertEqual((errors, n), ([], 1))

    def test_tree_with_drift(self):
        root = self._tree(wf(f"o/r@{SHA_B} # v2"), wf(f"o/r@{SHA_A} # v1"))
        self.assertEqual(pins.main(["x", str(root)]), 1)

    def test_no_repo_workflows_fails(self):
        root = self._tmp()
        errors, _ = pins.check(root)
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
