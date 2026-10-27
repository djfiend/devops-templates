#!/usr/bin/env bash
# scripts/check.sh — the repo's one verification gate (wt.gate in .wtconfig; contract C5).
#
# Must exit 0 before any handoff or merge. CI (.github/workflows/check.yml) runs this
# same script, so a local pass and a CI pass mean the same thing (C5.2).
#
# Steps (all run; the summary lists every failure):
#   1. python >= 3.10        the floor adopting repos' hooks run on
#   2. ruff check            lint (rule set in ruff.toml)
#   3. ruff format --check   formatting
#   4. shellcheck            scripts/*.sh
#   5. actionlint            .github/workflows/
#   6. compile               every .py compiles under the running Python (no byte-code written)
#   7. guard-hook tests      contract/.claude/hooks/tests (unittest, temp repos only)
#   8. render tests          tests/: Copier renders `contract` and every `project` type into
#                            throwaway repos (file sets, nothing unrendered, valid YAML/TOML/
#                            JSON), layered project + contract, rendered hook tests, `wt doctor`
#                            if wt is installed, copier update round trips between two tags
#   9. scaffold gates        scripts/scaffold-gates.sh: every project type scaffolded the way
#                            devops-new does it, then the scaffold's OWN scripts/check.sh.
#                            A tool it needs that is missing here (bats, docker, terraform,
#                            tflint) is a SKIP; with --strict (CI) it is a failure
#
# Requirements: bash, git, python3 (>= 3.10), uv. Tools are pinned below and run through
# uvx. Online, the gate uses the network only to fetch those pinned tools and the scaffolds'
# pinned inputs; every check runs against local files (contract C5.2). Once they are cached,
# --offline runs the gate with no network (UV_OFFLINE=1, passed on to every scaffold gate);
# a step that cannot run offline reports SKIP and says why (C5.4).
#
# Usage: scripts/check.sh                       run the gate
#        scripts/check.sh --strict              scaffold gates fail on a skipped tool (CI)
#        scripts/check.sh --offline             no network; never with --strict (CI never runs offline)
#        PYTHON=python3.14 scripts/check.sh     run it under a specific interpreter

set -euo pipefail

RUFF_VERSION="0.17.0"             # same pin as linux-devops-workspace
SHELLCHECK_PY_VERSION="0.11.0.1"  # PyPI wheel of ShellCheck 0.11.0
ACTIONLINT_PY_VERSION="1.7.12.25" # PyPI wheel of actionlint 1.7.12
COPIER_VERSION="9.19.1"           # keep >= _min_copier_version in copier.yml
YAMLLINT_VERSION="1.38.0"         # render tests: rendered YAML parses

PYTHON="${PYTHON:-python3}"
STRICT=()
OFFLINE=()
for arg in "$@"; do
    case "$arg" in
        --strict) STRICT=(--strict) ;;
        --offline) OFFLINE=(--offline) ;;
        *)
            echo "usage: scripts/check.sh [--strict | --offline]" >&2
            exit 2
            ;;
    esac
done
if ((${#STRICT[@]} && ${#OFFLINE[@]})); then
    echo "check.sh: --offline cannot be combined with --strict (CI never runs offline; contract C5.4)" >&2
    exit 2
fi
if ((${#OFFLINE[@]})); then
    # uv and uvx use only their cache; a missing tool fails instead of downloading.
    export UV_OFFLINE=1
fi
COPIER_CMD="uvx --quiet --python $PYTHON --from copier==${COPIER_VERSION} copier"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -t 1 ]]; then
    BOLD=$'\e[1m' GREEN=$'\e[32m' RED=$'\e[31m' RESET=$'\e[0m'
else
    BOLD="" GREEN="" RED="" RESET=""
fi

failed=()
passed=0

step() { # step <name> <command...>: run one gate step, record pass/fail, never abort
    local name="$1"
    shift
    printf '\n%s==> %s%s\n' "$BOLD" "$name" "$RESET"
    if "$@"; then
        printf '%sPASS%s  %s\n' "$GREEN" "$RESET" "$name"
        passed=$((passed + 1))
    else
        printf '%sFAIL%s  %s\n' "$RED" "$RESET" "$name"
        failed+=("$name")
    fi
}

require() { # require <command>: fail early with a clear message if a prerequisite is missing
    command -v "$1" >/dev/null 2>&1 || {
        printf '%scheck.sh: %s not found on PATH — see README.md § Prerequisites%s\n' "$RED" "$1" "$RESET" >&2
        exit 2
    }
}

ruff() { uvx --quiet "ruff@${RUFF_VERSION}" "$@"; }
shellcheck() { uvx --quiet --from "shellcheck-py==${SHELLCHECK_PY_VERSION}" shellcheck "$@"; }
actionlint() { uvx --quiet --from "actionlint-py==${ACTIONLINT_PY_VERSION}" actionlint "$@"; }

python_floor() {
    "$PYTHON" -c 'import sys; v = sys.version_info; print(f"Python {v.major}.{v.minor}.{v.micro}"); sys.exit(0 if v >= (3, 10) else 1)'
}

compile_all() {
    # Equivalent to `python -m compileall`, but compiles in memory: no __pycache__ in the tree.
    "$PYTHON" - <<'PY'
import pathlib, sys
skip = {".git", ".worktrees", "__pycache__"}
bad = 0
for f in sorted(pathlib.Path(".").rglob("*.py")):
    if skip & set(f.parts):
        continue
    try:
        compile(f.read_bytes(), str(f), "exec")
    except SyntaxError as e:
        print(f"  {f}:{e.lineno}: {e.msg}")
        bad += 1
sys.exit(1 if bad else 0)
PY
}

guard_hook_tests() {
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m unittest discover -s contract/.claude/hooks/tests
}

render_tests() {
    if ! command -v wt >/dev/null 2>&1; then
        echo "  note: wt not on PATH — the wt doctor render test is skipped (install devops-workspace)"
    fi
    # Verbose run so the gate shows each test; full output only when something fails.
    local out rc=0
    out="$(PYTHONDONTWRITEBYTECODE=1 \
        COPIER="$COPIER_CMD" \
        YAMLLINT="uvx --quiet --from yamllint==${YAMLLINT_VERSION} yamllint" \
        "$PYTHON" -m unittest discover -s tests -v 2>&1)" || rc=$?
    if ((rc)); then
        printf '%s\n' "$out"
    else
        grep -E " \.\.\. |^Ran " <<<"$out" | sed 's/^/  /'
    fi
    return $rc
}

scaffold_gates() {
    local out rc=0
    out="$(COPIER="$COPIER_CMD" scripts/scaffold-gates.sh "${STRICT[@]}" "${OFFLINE[@]}" 2>&1)" || rc=$?
    if ((rc)); then
        printf '%s\n' "$out"
    else
        grep -E "^(=== |wt doctor:|GATE |scaffold gates)" <<<"$out" | sed 's/^/  /'
    fi
    return $rc
}

require git
require uv
require "$PYTHON"

printf '%scheck.sh%s — %s @ %s%s\n' "$BOLD" "$RESET" "$(basename "$REPO_ROOT")" \
    "$(git rev-parse --short HEAD 2>/dev/null || echo '?')" "${STRICT[*]:+ (strict)}${OFFLINE[*]:+ (offline)}"

step "python >= 3.10"     python_floor
step "ruff check"         ruff check --no-cache .
step "ruff format"        ruff format --no-cache --check .
step "shellcheck"         shellcheck scripts/*.sh
step "actionlint"         actionlint
step "compile"            compile_all
step "guard-hook tests"   guard_hook_tests
step "render tests"       render_tests
step "scaffold gates"     scaffold_gates

total=$((passed + ${#failed[@]}))
if ((${#failed[@]})); then
    printf '\n%sGATE FAILED%s — %d of %d steps failed: %s\n' "$RED$BOLD" "$RESET" "${#failed[@]}" "$total" "${failed[*]}"
    exit 1
fi
printf '\n%sGATE PASSED%s — %d/%d steps\n' "$GREEN$BOLD" "$RESET" "$passed" "$total"
