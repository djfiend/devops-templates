#!/usr/bin/env bash
# scripts/scaffold-gates.sh — scaffold every project type and run the scaffold's OWN gate.
#
# For each type: snapshot this working tree into a temp git repo (so uncommitted template
# edits are tested), render `project` then `contract` into a fresh repo the way devops-new
# does, lock (python), commit, then run `wt doctor` (when wt is installed) and the
# scaffold's scripts/check.sh. A scaffold must also leave its tree clean.
#
# Usage: scripts/scaffold-gates.sh [--strict | --offline] [--keep] [TYPE...]
#   --strict  pass --strict to every scaffold gate (a missing tool fails; CI uses this)
#   --offline no network (UV_OFFLINE=1): pass --offline to every scaffold gate; tools, the
#             python scaffold's dependencies and its build backend must be in the uv cache
#   --keep    keep the scaffolds and print where they are
#   TYPE      python bash generic ansible docker terraform (default: all)
# Environment: COPIER  the copier command (default: copier; scripts/check.sh pins it)

set -euo pipefail

ALL_TYPES=(python bash generic ansible docker terraform)
SNAPSHOT=(copier.yml contract project includes)
read -r -a COPIER <<<"${COPIER:-copier}"

strict=() offline=() keep=0 types=()
for arg in "$@"; do
    case "$arg" in
        --strict) strict=(--strict) ;;
        --offline) offline=(--offline) ;;
        --keep) keep=1 ;;
        -*)
            echo "usage: scripts/scaffold-gates.sh [--strict | --offline] [--keep] [TYPE...]" >&2
            exit 2
            ;;
        *) types+=("$arg") ;;
    esac
done
if ((${#strict[@]} && ${#offline[@]})); then
    echo "scaffold-gates.sh: --offline cannot be combined with --strict (contract C5.4)" >&2
    exit 2
fi
if ((${#offline[@]})); then
    export UV_OFFLINE=1 # covers `uv lock` below as well as the scaffold gates
fi
((${#types[@]})) || types=("${ALL_TYPES[@]}")

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
if ((keep)); then
    trap 'echo "scaffolds kept in $WORK"' EXIT
else
    trap 'rm -rf "$WORK"' EXIT
fi

export GIT_AUTHOR_NAME=scaffold GIT_AUTHOR_EMAIL=scaffold@example.invalid
export GIT_COMMITTER_NAME=scaffold GIT_COMMITTER_EMAIL=scaffold@example.invalid
export GIT_CONFIG_NOSYSTEM=1

tpl="$WORK/tpl"
mkdir "$tpl"
(cd "$REPO_ROOT" && cp -R "${SNAPSHOT[@]}" "$tpl/")
find "$tpl" -name __pycache__ -prune -exec rm -rf {} +
git -C "$tpl" init -q -b main
git -C "$tpl" add -A
git -C "$tpl" commit -q -m snapshot
git -C "$tpl" tag v0.0.0-scaffold

scaffold() { # scaffold <type>: render, commit, doctor, gate; return non-zero on any failure
    local type="$1" dest="$WORK/demo-$1" dirty
    mkdir "$dest" && cd "$dest" || return
    git init -q -b main || return
    "${COPIER[@]}" copy --quiet --defaults --vcs-ref v0.0.0-scaffold \
        -d template=project -d "project_type=$type" -d "repo_description=Scaffold test ($type)." \
        "$tpl" . || return
    "${COPIER[@]}" copy --quiet --defaults --vcs-ref v0.0.0-scaffold -d template=contract "$tpl" . || return
    if [[ "$type" == python ]]; then
        uv lock --quiet || return
    fi
    git add -A && git commit -q -m "scaffold $type" || return
    if command -v wt >/dev/null 2>&1; then
        wt doctor | tail -1 || return
    else
        echo "  (wt not on PATH: wt doctor not run)"
    fi
    scripts/check.sh "${strict[@]}" "${offline[@]}" || return
    dirty="$(git status --porcelain)"
    if [[ -n "$dirty" ]]; then
        printf 'gate left the tree dirty:\n%s\n' "$dirty"
        return 1
    fi
}

failed=()
for type in "${types[@]}"; do
    printf '\n=== %s\n' "$type"
    (scaffold "$type") || failed+=("$type")
done

if ((${#failed[@]})); then
    printf '\nscaffold gates FAILED for: %s\n' "${failed[*]}"
    exit 1
fi
printf '\nscaffold gates passed: %s\n' "${types[*]}"
