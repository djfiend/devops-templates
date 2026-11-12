#!/usr/bin/env python3
"""Gate step: the scaffold CI templates pin the same action SHAs as this repo's own CI.

Dependabot (.github/dependabot.yml) bumps the SHA-pinned actions in .github/workflows/,
but it cannot parse the Copier templates (*.jinja), so a merged Dependabot PR would leave
every new scaffold on the old pin. This check makes that drift a gate failure, so CI on
the Dependabot PR stays red until the same bump is made in the template.

Rules (every `uses: <action>@<ref>` line in the files below):
  1. Every remote action is pinned to a full 40-character commit SHA with a version
     comment: `uses: owner/repo@<sha> # vX.Y.Z`. Local (`./…`) and `docker://` uses
     are ignored.
  2. Within one side (repo workflows, or templates), an action has one pin.
  3. Every action a template uses also appears in the repo workflows, so Dependabot
     proposes its updates.
  4. Template and repo pins of an action are identical (SHA and version comment).

Repo side:      .github/workflows/*.yml, *.yaml
Template side:  contract/ and project/, any .github/workflows/* file (rendered or .jinja)

Usage: python3 scripts/check_action_pins.py [REPO_ROOT]    exit 0 = in sync, 1 = drift
Stdlib only; no network.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<target>\S+)(?P<rest>.*)$")
SHA = re.compile(r"[0-9a-f]{40}")
COMMENT = re.compile(r"#\s*(?P<version>\S+)")
TEMPLATE_DIRS = ("contract", "project")


@dataclass(frozen=True)
class Pin:
    action: str  # owner/repo[/path]
    ref: str  # what follows @ (a SHA when pinned correctly)
    version: str  # the trailing comment's first word, "" if none
    where: str  # path:line, for messages


def parse(text: str, name: str) -> tuple[list[Pin], list[str]]:
    """Return the remote action pins in one workflow file and rule-1 errors."""
    pins: list[Pin] = []
    errors: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = USES.match(line)
        if not m:
            continue
        target = m["target"].strip("'\"")
        if target.startswith(("./", "docker://")):
            continue
        where = f"{name}:{lineno}"
        action, sep, ref = target.partition("@")
        c = COMMENT.search(m["rest"])
        version = c["version"] if c else ""
        if not sep or not SHA.fullmatch(ref):
            errors.append(f"{where}: {target} is not pinned to a full commit SHA")
        elif not version:
            errors.append(f"{where}: {target} has no '# vX.Y.Z' version comment")
        pins.append(Pin(action, ref, version, where))
    return pins, errors


def _by_action(pins: list[Pin], side: str) -> tuple[dict[str, Pin], list[str]]:
    seen: dict[str, Pin] = {}
    errors: list[str] = []
    for p in pins:
        first = seen.setdefault(p.action, p)
        if (first.ref, first.version) != (p.ref, p.version):
            errors.append(
                f"{p.where}: {p.action}@{p.ref} # {p.version} differs from "
                f"{first.where} ({first.ref} # {first.version}) within the {side}"
            )
    return seen, errors


def compare(repo: list[Pin], template: list[Pin]) -> list[str]:
    """Rules 2-4 over already-parsed pins."""
    repo_map, errors = _by_action(repo, "repo workflows")
    tmpl_map, tmpl_errors = _by_action(template, "templates")
    errors += tmpl_errors
    for action, t in sorted(tmpl_map.items()):
        r = repo_map.get(action)
        if r is None:
            errors.append(
                f"{t.where}: {action} is not used in .github/workflows/, so Dependabot "
                "never proposes its updates; add it to the repo CI or drop it"
            )
        elif (r.ref, r.version) != (t.ref, t.version):
            errors.append(
                f"{t.where}: {action}@{t.ref} # {t.version} — repo CI pins "
                f"{r.ref} # {r.version} ({r.where}); copy the repo pin into the template"
            )
    return errors


def workflow_files(root: Path) -> tuple[list[Path], list[Path]]:
    wf = root / ".github" / "workflows"
    repo = sorted(p for p in wf.glob("*") if p.suffix in (".yml", ".yaml"))
    template = sorted(
        p
        for d in TEMPLATE_DIRS
        for p in (root / d).rglob("*")
        if p.is_file()
        and p.parent.name == "workflows"
        and p.parent.parent.name == ".github"
    )
    return repo, template


def check(root: Path) -> tuple[list[str], int]:
    repo_files, template_files = workflow_files(root)
    errors: list[str] = []
    repo: list[Pin] = []
    template: list[Pin] = []
    if not repo_files:
        errors.append(".github/workflows/: no workflow files found")
    for files, out in ((repo_files, repo), (template_files, template)):
        for f in files:
            pins, errs = parse(f.read_text(encoding="utf-8"), str(f.relative_to(root)))
            out.extend(pins)
            errors.extend(errs)
    errors += compare(repo, template)
    return errors, len({p.action for p in template})


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]
    errors, n = check(root)
    for e in errors:
        print(f"  {e}")
    if errors:
        return 1
    print(f"  {n} template action(s) pinned the same as the repo CI")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
