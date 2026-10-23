# devops-templates — Operations Guide

**Applies to:** devops-templates v1.1.1
**Audience:** maintainers of the templates (Josh and agents working in this repo), and
anyone operating a repo that has adopted them
**Related:** [README](../README.md) (what each template renders, questions) ·
[multi-agent ready contract](multi-agent-ready-contract.md) · [CHANGELOG](../CHANGELOG.md)

This guide covers how the templates are put together, how a change moves from an
edit to a release, and how adopting repos receive it. The README is the reference
for what the templates render; this is the how-it-runs view.

---

## 1. How the repository renders

One repository, several templates. The `template` answer picks the subdirectory that
Copier renders, and each template writes its own answers file, so templates stack on
one repo without clobbering each other's state.

```mermaid
flowchart TD
    CY["copier.yml<br/>_subdirectory: {{ template }}<br/>_answers_file: .copier-answers.{{ template }}.yml"]
    CY --> Q{"template = ?"}
    Q -- contract --> C["contract/"]
    Q -- project --> P["project/<br/>+ project_type choice"]
    INC["includes/<br/>shared Jinja partials<br/>(never rendered as files)"] -. "{% include %}" .-> C
    INC -. "{% include %}" .-> P
    C --> AC[".copier-answers.contract.yml"]
    P --> AP[".copier-answers.project.yml"]
    P --> TYPES["conditional paths, e.g.<br/>{% if project_type == 'python' %}pyproject.toml{% endif %}.jinja"]
```

| Path | What it is |
|---|---|
| `copier.yml` | Questions, `_subdirectory`, `_answers_file`, the seeded list (`_skip_if_exists`), post-copy messages |
| `contract/` | The multi-agent contract layer adopting repos receive |
| `project/` | New-project starter for six types; type-specific files use conditional path names |
| `includes/` | Partials: the shared `AGENTS.md` body, and per-type commands/conventions |
| `docs/multi-agent-ready-contract.md` | The standard (C1–C10) the `contract` layer implements and `wt doctor` checks |
| `tests/` | Render tests (Copier into throwaway repos) |
| `scripts/check.sh`, `scripts/scaffold-gates.sh` | The gate, and the per-type scaffold-and-gate runner |
| Root `.wtconfig`, `.claude/`, `.gemini/` | This repo's **own application** of `contract/` (currently at v1.0.0) — updated with `copier update`, never edited by hand |

---

## 2. Managed vs seeded — the decision that drives everything

```mermaid
flowchart TD
    N["New or changed file in a template"] --> Q1{"Will an adopting repo<br/>customise it?"}
    Q1 -- "yes: docs, gate, CI,<br/>example code, AGENTS.md" --> S["SEEDED<br/>add a pattern to _skip_if_exists<br/>(scoped with {% if template == … %})"]
    Q1 -- "no: tool config, agent<br/>permissions, the hook" --> M["MANAGED<br/>leave out of _skip_if_exists"]
    S --> S2["Adopters get it once.<br/>Later template changes never reach them —<br/>note manual follow-ups in CHANGELOG"]
    M --> M2["Adopters get every change via<br/>copier update (3-way merge)"]
    M2 --> M3{"Moving an existing file<br/>managed → seeded?"}
    M3 -- yes --> MAJ["MAJOR release"]
```

Consequence for maintenance: a fix to a **seeded** file (for example a scaffold's
`scripts/check.sh`) only reaches *new* projects. Existing adopters must patch their
copy by hand; the CHANGELOG entry must say so.

---

## 3. Change workflow (edit → release)

```mermaid
flowchart TD
    A["wt new type/desc<br/>(never edit the main checkout)"] --> B["edit contract/, project/, includes/,<br/>copier.yml, tests"]
    B --> C["try it: copier copy --vcs-ref HEAD -d template=… . /tmp/scratch<br/>or scripts/scaffold-gates.sh --keep TYPE"]
    C --> D["optional: prove it through the toolkit<br/>DEVOPS_TEMPLATES_SRC=&lt;this worktree&gt;<br/>linux-devops-workspace scripts/check.sh"]
    D --> E["CHANGELOG.md entry<br/>(what changes for adopting repos)"]
    E --> F["scripts/check.sh — 9 steps"]
    F --> G{"GATE PASSED?"}
    G -- no --> B
    G -- yes --> H["commit with Handoff block"]
    H --> I["Josh: git merge --no-ff"]
    I --> J{"changes rendered output?"}
    J -- no --> K["no release needed"]
    J -- yes --> L["Josh: tag vX.Y.Z on main, push<br/>(semver decision below)"]
    L --> M["CI check.yml --strict green"]
    M --> N["toolkit: bump TEMPLATES_REF<br/>→ adopters: devops-update"]
```

### Release level

```mermaid
flowchart TD
    R["What did the change do?"] --> Q1{"Renamed or removed a question,<br/>moved a file managed → seeded,<br/>or anything adopters must act on?"}
    Q1 -- yes --> MAJ["MAJOR vX+1.0.0"]
    Q1 -- no --> Q2{"Added something with a default:<br/>a managed file, a question,<br/>a rule, a project type?"}
    Q2 -- yes --> MIN["MINOR vX.Y+1.0"]
    Q2 -- no --> PAT["PATCH vX.Y.Z+1<br/>(fix, no answer changes)"]
```

Tags are PEP 440 `vX.Y.Z` on `main`; there is no version file. Every release that
changes rendered output gets a CHANGELOG entry.

---

## 4. The gate — `scripts/check.sh`

Nine steps, all run, summary at the end. Tool versions are pinned in the script (the
scaffolds' own pins live in `project/scripts/check.sh.jinja`) and run through `uvx`.

```mermaid
flowchart LR
    subgraph static["Static"]
        s1["1 python ≥ 3.10"] --> s2["2 ruff check"] --> s3["3 ruff format"] --> s4["4 shellcheck"] --> s5["5 actionlint"] --> s6["6 compile"]
    end
    subgraph tests["Behaviour"]
        s7["7 guard-hook tests<br/>contract/.claude/hooks/tests"]
        s8["8 render tests<br/>every template + type, layered,<br/>parse YAML/TOML/JSON, wt doctor,<br/>copier update round trips"]
        s9["9 scaffold gates<br/>each type rendered like devops-new,<br/>then ITS OWN scripts/check.sh"]
        s7 --> s8 --> s9
    end
    static --> tests
```

| Run | Command | Notes |
|---|---|---|
| Local | `scripts/check.sh` | ~6 min (approximate). Needs bash, git, Python ≥ 3.10, uv |
| Specific Python | `PYTHON=python3.14 scripts/check.sh` | |
| CI | `scripts/check.sh --strict` (Python 3.10 + 3.14) | installs bats, terraform, tflint (Docker on the runner); a SKIP fails; tree must stay clean |
| One type, keep output | `scripts/scaffold-gates.sh --keep python` | prints where the scaffold is |

`wt doctor` checks in step 8 run only where `wt` (devops-workspace) is installed —
mmisadmin02 — not in CI, because the toolkit is a private repo. Run the gate on
mmisadmin02 before release so those checks are exercised.

The CI binary pins (bats, terraform, tflint) must match the ones in
`project/.github/workflows/check.yml.jinja`, so scaffolds and this repo test with the
same tools.

---

## 5. How adopting repos consume a release

```mermaid
sequenceDiagram
    autonumber
    participant T as devops-templates (tag vX.Y.Z)
    participant R as Adopting repo (chore/ worktree)
    participant O as Owner

    alt first adoption (no answers file yet)
        R->>T: copier copy --vcs-ref vX.Y.Z -d template=contract URL .
        T-->>R: rendered files + .copier-answers.contract.yml
        R->>R: answer yes for MANAGED conflicts, fill AGENTS.md TODOs
    else already adopted
        R->>T: copier update --answers-file .copier-answers.contract.yml<br/>(or devops-update)
        T-->>R: diff old→new template applied as 3-way merge
    end
    R->>R: git diff · gate · wt doctor (0 failed)
    R->>O: handoff
    O->>R: merge --no-ff
```

Changing an answer without moving versions:

```bash
copier update --answers-file .copier-answers.contract.yml --vcs-ref=:current: -d stale_days=14
```

Never hand-edit managed files or answers files in an adopting repo — the next
update turns that into conflict markers.

---

## 6. Downstream consumer: devops-workspace

The devops-workspace toolkit (`djfiend/linux-devops-workspace`, private) is the main
consumer. It pins one release of this repo (`TEMPLATES_REF`, `v1.1.0` in toolkit
v5.0.0), renders `project` then `contract` through Copier's Python API in
`devops-new`, and updates layers with `devops-update`. Its gate scaffolds every type
from the pinned tag, so **a release here is not used by new projects until the toolkit
bumps its pin and passes its gate**.

What that means when you release here:

| Change here | Also needed in the toolkit |
|---|---|
| Any rendered change | bump `TEMPLATES_REF`, gate, toolkit release |
| New `project_type` | `VALID_TYPES`, `_TYPE_SIGNATURES`, `PROJECT_TYPES`; CI binaries |
| New/changed machine-checkable contract rule | a `wt doctor` check |
| New `wt` command referenced in `.claude/settings.json` | the command must exist in `wt` first |

The full cross-repo picture (context diagram, version matrix, change propagation) is
in the toolkit's `docs/system-integration.md` (private repo).

---

## 7. Routine operations

| When | What | Who |
|---|---|---|
| Every change | worktree → gate → handoff | agent |
| After merge with rendered changes | tag, push, confirm CI green | Josh |
| After a release | open the toolkit pin bump; update this repo's own contract layer if the contract changed | agent proposes, Josh merges |
| Dependabot PR | Action SHA bumps — keep the scaffold CI template pins in step | Josh |
| Periodically | `copier update` this repo's own root (`.copier-answers.contract.yml`) so it dogfoods the latest contract | agent, Josh merges |

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Rendered file contains `{{` / `{%` | Jinja not applied (missing `.jinja` suffix) or escaped wrongly | render tests catch it; fix the file name or `{% raw %}` |
| Bash `${#arr[@]}` breaks rendering | `{#` opens a Jinja comment | wrap in `{% raw %}…{% endraw %}` |
| A project-only seeded path also skips files in `contract` | unscoped `_skip_if_exists` entry | wrap it in `{% if template == 'project' %}…{% endif %}` |
| Scaffold gate SKIP locally | bats/docker/terraform/tflint missing | fine locally; CI `--strict` runs them |
| `wt doctor` render check skipped | `wt` not installed | install devops-workspace (≥ v4.0.1) |
| Adopter gets conflict markers on update | adopter edited a managed file | move the change here, release, re-update |
| Change didn't reach existing projects | file is seeded | document the manual patch in CHANGELOG |
