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

- Broader conditional predicate support for source guards
- Remaining array/list iteration outside exact indexed, associative,
  command-substitution, and file-populated arrays
- Remaining loop forms outside exact `for`, bounded C-style `for ((...))`,
  bounded `while` / `until`, and modeled `while read` file enumeration from
  exact files and safe producers
- Remaining glob/source-argument semantics: `extglob`, direct source glob
  arguments, source arguments requiring word splitting, and full `GLOBIGNORE`
  edge behavior
- Broader case pattern and fallthrough semantics for source-bearing arms
- Runtime-dynamic source dispatch, recursive source-bearing functions,
  non-equivalent branch-defined functions, and branch-dependent function returns
