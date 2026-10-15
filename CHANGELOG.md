# Changelog

What each release changes for repositories that use the templates. Versions are
git tags (`vX.Y.Z`, PEP 440).

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
