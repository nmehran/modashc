# Changelog

## v0.1.0 - 2026-05-22

Initial source-effect IR compiler baseline.

### Added

- Context output mode as the default readable renderer for human and LLM review.
- Executable output mode that inlines supported `source` sites while preserving
  parent-shell state.
- Source-effect IR frontend, evaluator, source events, and structured
  unsupported-source diagnostics.
- Supported source-resolution matrix covering static paths, variables, path
  commands, safe producers, arrays, loops, read loops, branches, cases, and
  bounded source-bearing functions.
- Fail-closed executable behavior for unsupported or ambiguous source forms.
- Real temporary shell-project test harness and expanded Bash parity regression
  suite.
- Optional setup shell helper containment tests.

### Notes

- `modashc` resolves dependencies without executing shell code.
- Context mode is readable-first and not a runtime parity mode.
- Executable mode is parity-first for the documented supported subset.
- Remaining practical source-resolution gaps are tracked in
  `docs/supported-source-resolution.md`.
