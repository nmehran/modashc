# modashc Design Docs

This directory holds implementation specs for behavior that is too nuanced to
keep only in code comments or tests.

## Specs

- [Supported Source Resolution](supported-source-resolution.md): user-facing
  support matrix for resolved `source` patterns, executable-mode fail-closed
  behavior, and practical remaining work.
- [Dynamic Source Resolution](dynamic-source-resolution.md): Python-only
  resolution of common runtime-looking `source` idioms without executing shell
  code.
- [Source Supplements And Exact Helper Sources](source-supplements.md):
  JSON supplement workflow and exact helper patterns such as `source "$@"`.
- [Retained Helper Dispatch](retained-helper-dispatch.md):
  supplement-backed source helper definitions that remain callable in merged
  executable output.
- [Source Argument Semantics Completion](source-argument-semantics.md):
  static iteration for direct multi-match source globs, wrapped positional
  mutation lowering, and real-world/runtime promotion.
- [Source-Relevant Control Flow Boundaries](source-control-flow-boundaries.md):
  source-free control-flow pass-through, exact source
  conditions, and practical source guard predicates.
- [Runtime-Guarded Static Source Lowering](runtime-guarded-source-lowering.md):
  static lowering for exact source sites guarded by runtime `if` and `case`
  control flow.
- [Compound Source Condition Lowering](compound-source-condition-lowering.md):
  static lowering for exact source atoms inside `if` / `elif` logical condition
  lists.
- [Case Source Semantics Expansion](case-source-semantics.md):
  static expansion for source-bearing `case` pattern normalization,
  fallthrough terminators, and real-world/runtime promotion.
- [Real-World Internal Test Suite](real-world-test-suite.md):
  opt-in corpus, supplement fixture, artifact, and runtime parity probes
  workflow.
- [Next-Generation Evaluator And IR Plan](evaluator-ir-plan.md): Architecture
  notes and implementation history for the source-effect IR and evaluator.

## Planned Specs

- Parser boundaries and Bash grammar coverage beyond the current line frontend
- Context output format
- Executable output semantics

## Deferred Source-Resolution Specs

These require more evaluator coverage before source discovery and executable
lowering can both stay exact. See
[Supported Source Resolution](supported-source-resolution.md) for the current
user-facing support matrix and practical remaining work.
The intended approach is captured in the
[Next-Generation Evaluator And IR Plan](evaluator-ir-plan.md):

- Remaining array/list iteration outside exact indexed, associative,
  command-substitution, and file-populated arrays
- Remaining loop forms outside exact `for`, bounded C-style `for ((...))`,
  bounded `while` / `until`, and modeled `while read` file enumeration from
  exact files and safe producers
- Remaining glob/source-argument semantics: `extglob`, source arguments
  requiring word splitting, full `GLOBIGNORE` edge behavior, and explicit
  source-argument frames that combine top-level `set --` with later nested
  source calls
- Broader source guard predicates and remaining case edge semantics such as
  `extglob`, collating symbols, and equivalence classes
- Runtime-dynamic source dispatch, recursive source-bearing functions,
  non-equivalent branch-defined functions, and branch-dependent function returns
