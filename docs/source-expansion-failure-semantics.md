# Source Expansion Failure Semantics

## Status

Implemented on the `iteration/source-expansion-failure-semantics` development
branch.

This iteration stays static. It does not run Bash, collect xtrace output, or
discover runtime source paths. It completes the deterministic command-word
expansion cases that affect which source file Bash would invoke, and separates
runtime `source` failures from expansion failures that happen before `source`
runs.

## Starting Gap

After direct source glob arguments and missing-source lowering, three exact
expansion outcomes remained:

```bash
source ./{a,b}.sh

shopt -s nullglob
source ./missing/*.sh ./fallback.sh arg

shopt -s failglob
source ./missing/*.sh
```

These are not runtime-dynamic source discovery problems. Bash determines the
source command words before invoking `source`, using normal shell expansion
order. The compiler can model the finite deterministic cases directly.

## Semantics Contract

- Executable mode must not leave live unresolved `source` or `.` commands in
  accepted output.
- Brace-only direct source expansion produces command words. The first expanded
  word is the source filename and the remaining expanded words are source
  positional arguments.
- `nullglob` removes unmatched pathname-expansion words before source
  invocation. If a later exact word remains, that word becomes the source
  filename.
- `failglob` reports a pathname expansion error before `source` runs. The
  source file must not be inlined, later commands on the same physical line
  must not run, and the following line observes status `1`.
- `failglob` affects failed pathname patterns only. Brace-only literal words
  are not removed by `nullglob`, rejected by `failglob`, or filtered by
  `GLOBIGNORE`.
- Context mode remains readable-first; executable mode owns the hard
  no-live-source guarantee.

## Implemented Scope

- Direct brace-only source expansion:

  ```bash
  source ./{real,missing}.sh
  ```

  If `./real.sh` exists, it is sourced with `./missing.sh` as `$1`. If the
  first brace-expanded word is missing, executable output lowers Bash's
  missing-file source failure and does not source later brace words.

- Exact `nullglob` source-word shifting:

  ```bash
  shopt -s nullglob
  source ./missing/*.sh ./fallback.sh arg
  ```

  The missing glob disappears, `./fallback.sh` becomes the source file, and
  `arg` becomes `$1`.

- Direct `failglob` expansion failure lowering:

  ```bash
  shopt -s failglob
  source ./missing/*.sh
  ```

  Executable output prints a Bash-shaped `no match` diagnostic, returns status
  `1`, and comments out the rest of the original physical line to preserve
  Bash's line-abort behavior.

## Non-Goals

- Do not add runtime discovery, xtrace, sandbox execution, or supplement
  generation.
- Do not support `failglob` inside `if source ...` / `elif source ...`
  conditions yet; preserving Bash's condition-line abort requires broader
  control-flow replacement.
- Do not support `failglob` inside function bodies yet; expansion failure can
  abort the caller's physical line and needs function-aware lowering.
- Do not lower `failglob` after an unknown `&&` / `||` guard, because whether
  the expansion happens is runtime-dependent and affects later commands on the
  same line.
- Do not support `failglob` loop word-list lowering yet. Multiline loop
  replacement needs whole-loop artifact rewriting, not source-site replacement.
- Do not treat arbitrary non-expanded missing literal source paths as supported
  dependencies.
- Do not broaden source argument word splitting.

## Acceptance

- Direct brace-only source expansion matches Bash for existing-first and
  missing-first cases.
- Brace-only source words remain literal under `nullglob`, `failglob`, and
  `GLOBIGNORE`.
- Exact `nullglob` word shifting matches Bash for literal fallback files and
  second glob words with multiple matches.
- Direct `failglob` source failures match Bash status and diagnostics after
  normalizing generated script line numbers.
- Later commands on the same physical line after a lowered `failglob` source
  do not run.
- Unsupported `failglob` condition, function, and unknown-guard cases fail
  before output with structured diagnostics.
- Full unit, real-world corpus, runtime parity, and whitespace checks pass.

## Remaining Work

- `failglob` in source conditions, function bodies, and source-bearing loop
  word lists.
- Arbitrary missing literal source files unrelated to modeled expansion
  outcomes.
- Recursive or runtime-dynamic source-bearing function dispatch.
- Xtrace/runtime source discovery and supplement generation.
- Full parser replacement for unsupported shell grammar.
