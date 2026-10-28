# Changelog

What each release changes for repositories that use the templates. Versions are
git tags (`vX.Y.Z`, PEP 440).

## v1.2.0 — 2026-10-27

Contract v1.1 and an offline gate mode (owner decisions 2026-10-24 and
2026-10-27). The `contract` template's rendered files are unchanged: `copier
update` on an existing adopter changes only `_commit`.

- **Contract v1.1:** C5.2 now reads "the gate runs the same way locally and in CI
  and needs no secrets. Network is used only to fetch pinned, versioned inputs;
  every check runs against local files" (v1.0 forbade the network, which neither
  code gate met). New C5.4 (SHOULD): once its inputs are cached the gate runs
  offline with `--offline`, naming any step it skips; CI never runs offline. Every
  repo that met v1.0 meets v1.1's MUSTs.
- **Seeded project gate** (`project/scripts/check.sh.jinja`, every type):
  `--offline` exports `UV_OFFLINE=1`, so uv and uvx run from their cache and a
  missing tool fails instead of downloading. `--offline --strict` exits 2. ansible:
  ansible-lint gets `--offline` (no `requirements.yml` install, no schema refresh).
  terraform: `validate` skips `init` when `.terraform/` exists, and is a SKIP with
  the reason when locked providers are not installed yet; tflint skips `--init`. The
  banner says `(offline)`. New projects get it; existing projects keep their seeded
  gate, so copy the argument handling from the template by hand if you want it.
- **This repo's gate:** `scripts/check.sh --offline` and `scripts/scaffold-gates.sh
  --offline` (same rules; passed on to every scaffold gate). Render tests cover the
  `--strict`/`--offline` refusal and an offline run of a rendered gate.
- Seeded project `README.md` mentions `--offline`. Seeded `AGENTS.md` unchanged.

## v1.1.1 — 2026-10-23

Wording fix (library audit 2026-10-19, the guard and CI findings). No managed
file changes: `copier update` on an existing adopter changes only `_commit`.

- Seeded `AGENTS.md` (`includes/agents.md.jinja`, both templates): the guard-hook
  bullet now says what the hook does. It blocks main-checkout edits (except
  `wt.mainEditAllow`) and edits from one linked worktree into another. A
  main-checkout session may edit linked worktrees on purpose and gains no
  ownership. A new note under the enforcement table says CI checks only the
  gate; scope, ownership, attribution, handoffs and approvals are checked in
  review. New projects get this text. Existing projects keep their seeded copy,
  so update it by hand if you want it.
- Contract C10.1 and C10.2 corrected the same way (editorial; no requirement
  changed, still v1.0). README file table and this repo's `AGENTS.md` aligned.
- Guard hook code and tests unchanged.

## v1.1.0 — 2026-10-17

New `project` template (adoption phase 6). The `contract` template's rendered files
are unchanged: `copier update` on an existing adopter changes only `_commit`.

- **`project` template** with a `project_type` choice — python, bash, generic,
  ansible, docker, terraform — carried over from devops-workspace's in-code
  templates and brought up to standard. Apply it first, then `contract` on top.
  - Every type: README, CHANGELOG, `.editorconfig`, `.gitignore` (type rules +
    the contract's agent ignores), a seeded `AGENTS.md` with every C1.2 section and
    the type's commands, `.github/copilot-instructions.md` and `.clinerules`
    redirects, Dependabot, and a real gate: `scripts/check.sh` (pinned tools via
    uvx; a missing binary is a SKIP, `--strict` fails it) run by a SHA-pinned CI
    workflow with `--strict`.
  - python: hatchling `src/<package>/` layout with a console script, uv dependency
    groups + `uv.lock`, ruff, pytest, build check. bash: shellcheck, shfmt, bats.
    ansible: production-profile ansible-lint, yamllint, syntax check; `group_vars`
    moved under `inventory/` (where Ansible loads it). docker: digest-pinned base,
    numeric non-root user, `compose.yaml`, hadolint. terraform: `versions.tf`,
    tflint, `.terraform.lock.hcl` committed, only `*.tfvars.example` tracked.
  - Questions: `project_type`, `python_min` (python, docker); `repo_name` (now
    kebab-case-validated for projects) and `repo_description` are shared with
    `contract`. The contract-only questions are no longer asked for `project`.
  - Seeded vs managed: the docs, gate, CI and example code are seeded (`copier
    update` never touches them); tool config (`.editorconfig`, `ruff.toml`,
    `.yamllint`, `.tflint.hcl`, `pyproject.toml`, …) is managed.
- `includes/`: the seeded `AGENTS.md` body is one shared partial for both
  templates (the contract render is byte-identical to v1.0.0).
- `_skip_if_exists` entries are rendered per template, so the project template's
  seeded paths never apply to `contract`.
- Gate: render tests for every type, layered project + contract, update round
  trips; new step 9 `scripts/scaffold-gates.sh` runs each scaffold's own gate.
  CI installs bats, terraform and tflint and runs the gate with `--strict`.
- Repository is MIT-licensed (no change to rendered files).
- Contract: new C3.7 (sandboxed environments: git-only folder-delete permission, never cleanup approval; library audit finding 4); C10.2 names CI as the enforcement for every tool; C3.3 spells out the release-then-add handoff (finding 2). Docs only — no change to rendered files.

## v1.0.0 — 2026-10-15

First release (adoption phase 5).

- `contract` template: `.wtconfig`, `.claude/settings.json` (allow/ask/deny
  baseline: `git add .` denied, `wt rm` asks — readiness check 2026-10-14,
  finding 7), the main-checkout guard hook + tests, `.gemini/settings.json`;
  seeds `AGENTS.md`, `CLAUDE.md`, `.gitignore`.
- Guard hook decides from the **target** file's checkout, not the session's:
  a worker can no longer edit the main checkout by absolute or relative path,
  through a symlink, or in another worker's worktree (library audit
  2026-10-14, finding 1).
- `docs/multi-agent-ready-contract.md` v1.0 (moved from the library).
