# devops-templates

[Copier](https://copier.readthedocs.io/) templates for Josh's repositories.
One repository, several templates: the `template` question picks the
subdirectory that is rendered, and each template keeps its own answers file
(`.copier-answers.<template>.yml`), so templates layer on one repo.

| Template | What it renders | Status |
|---|---|---|
| `contract` | The **multi-agent contract layer** — what a repo needs so several agents can work in it safely ([the contract](docs/multi-agent-ready-contract.md)) | v1 |
| python, bash, … | Project types (today's `devops-new` templates) | adoption phase 6 |

## Prerequisites

- `git` and [`uv`](https://docs.astral.sh/uv/)
- Copier, installed as a uv tool:

  ```bash
  uv tool install copier
  ```

- `wt` from [`devops-workspace`](https://github.com/djfiend/linux-devops-workspace) (v4.0.1 or later) to check the result with `wt doctor`

## The `contract` template

### What it manages

| File | Kind | Notes |
|---|---|---|
| `.wtconfig` | managed | `wt.base`, `wt.gate`, `wt.staleDays`, `wt.mainEditAllow` — from your answers |
| `.claude/settings.json` | managed | Claude Code allow/ask/deny baseline + the guard hook; the gate and `extra_allow` become allow rules |
| `.claude/hooks/main-checkout-guard.py` | managed | Blocks edits in the main checkout (except `wt.mainEditAllow`) and in other workers' worktrees, judged by the *target* file |
| `.claude/hooks/tests/` | managed | The hook's unit tests (run them in your gate) |
| `.gemini/settings.json` | managed | Gemini CLI reads `AGENTS.md` |
| `AGENTS.md` | seeded | Written only if absent: every section `wt doctor` requires, with TODOs |
| `CLAUDE.md` | seeded | Written only if absent: `@AGENTS.md` |
| `.gitignore` | seeded | Written only if absent: `.worktrees/`, `.claude/settings.local.json` |
| `.copier-answers.contract.yml` | Copier | Template source, version and answers — commit it, never edit it |

**Managed** files change with `copier update`; edit them here, not in the
adopting repo (a local edit survives an update as a three-way merge, but it
is drift). **Seeded** files belong to the repo after the first copy; `wt doctor`
checks they still meet the contract.

### Questions

| Question | Default | Becomes |
|---|---|---|
| `repo_name` | the directory name | seeded `AGENTS.md` |
| `repo_description` | empty (TODO) | seeded `AGENTS.md` § What this repo is |
| `base` | `main` | `wt.base` |
| `gate` | `scripts/check.sh` | `wt.gate`, an allow rule, `AGENTS.md` § Commands |
| `gate_allow` | the gate up to its first option | allow rule `Bash(<gate_allow>:*)` |
| `stale_days` | `7` | `wt.staleDays` |
| `main_edit_allow` | `[]` | `wt.mainEditAllow` (one per entry) |
| `extra_allow` | `[]` | one allow rule `Bash(<entry>:*)` each — read-only commands only |

### Apply it to a repo

Run each command on its own, from the repo's main checkout, with a clean tree.
Pick the latest release tag for `vX.Y.Z`.

```bash
copier copy --vcs-ref vX.Y.Z -d template=contract https://github.com/djfiend/devops-templates.git .
```

Copier asks the questions above. Then review what changed:

```bash
git status
```

```bash
git diff
```

For each existing file that differs from the template, Copier reports a
`conflict` and asks whether to overwrite it (seeded files are never touched).
For a repo that already had contract files, answer yes for **managed** files —
that is the point — or, non-interactively, add `--overwrite` to the command
above; git still has the old versions, so review every change in `git diff`
and carry anything repo-specific into the answers. Fill in any `TODO` in a
newly seeded `AGENTS.md`. Then check:

```bash
wt doctor
```

Expect `0 failed`. Commit the rendered files together with
`.copier-answers.contract.yml`.

### Update to a newer release

With a clean tree:

```bash
copier update --answers-file .copier-answers.contract.yml
```

Copier re-renders the old version from the answers file, computes what the
template changed between the two versions, and applies only that to the repo.
Review `git diff`, run the gate, commit.

### Change an answer

```bash
copier update --answers-file .copier-answers.contract.yml --vcs-ref=:current: -d stale_days=14
```

`--vcs-ref=:current:` keeps the template version; only the answer changes.

## Working on the templates

This repository follows its own contract (`AGENTS.md`); its root `.claude/`,
`.gemini/` and `.wtconfig` are an application of `contract/`. The gate is
`scripts/check.sh` (CI runs it on Python 3.10 and 3.14). It renders the
template into throwaway repos and runs a `copier update` round trip between two
tags, so every change is tested the way adopting repos receive it.

Releases are PEP 440 git tags `vX.Y.Z` on `main` (patch: fix, no answer
changes; minor: something new with a default; major: adopting repos must act).
`CHANGELOG.md` lists what each release changes for adopting repos.
