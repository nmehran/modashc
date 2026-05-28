# Changelog

## v0.2.0 - 2026-05-28

Static Bash parity hardening and real-world validation release.

### Added

- Source supplements for exact source-relevant variables and helper call
  signatures via `--source-supplement`.
- Retained helper dispatch for makepkg-style helpers such as `source_safe`.
- Executable lowering for source arguments, positional frame restoration,
  child-shell source contexts, runtime-guarded exact source sites, compound
  source conditions, source-bearing `case` arms, deterministic pattern/glob
  semantics, missing source runtime failures, and deterministic source expansion
  failures.
- Internal real-world suite with pinned `bash-completion` and `pacman` corpora,
  generated artifact outputs, JSON run summaries, and opt-in runtime parity
  probes.

### Changed

- Broadened executable-mode Bash parity for the supported static subset while
  keeping unsupported source forms fail-closed before output is written.
- Improved structured diagnostics for unresolved executable output, supplements,
  retained helpers, source arguments, guard boundaries, and expansion failures.
- Expanded the documented support matrix and implementation specs for source
  resolution behavior.

### Validation

- Full unit suite: `342` tests, `4` skipped.
- Pinned real-world corpus: `42` mode records, with expected top-level
  `bash_completion` timeouts and all other pinned entries successful.
- Runtime parity probes: `16` pinned pacman wrapper probes matched Bash.
- Generated executable artifact scan: no live unresolved `source` sites.

### Notes

- `modashc` still resolves dependencies without executing shell code.
- Xtrace/runtime source discovery and supplement generation remain future work.
- Recursive or runtime-dynamic source-bearing dispatch and unsupported shell
  grammar remain fail-closed.

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
