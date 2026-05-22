# modashc Design Docs

This directory holds implementation specs for behavior that is too nuanced to
keep only in code comments or tests.

## Specs

- [Dynamic Source Resolution](dynamic-source-resolution.md): Python-only
  resolution of common runtime-looking `source` idioms without executing shell
  code.
- [Next-Generation Evaluator And IR Plan](evaluator-ir-plan.md): Deferred
  architecture plan and current implementation status for the source-effect IR,
  evaluator, and remaining loop, glob, conditional, and function work.

## Planned Specs

- Parser boundaries and Bash grammar coverage beyond the current line frontend
- Context output format
- Executable output semantics

## Deferred Specs

These require more evaluator coverage before executable lowering can be exact.
The intended approach is captured in the
[Next-Generation Evaluator And IR Plan](evaluator-ir-plan.md):

- Broader conditional predicate support
- Complex array/list iteration
- Remaining glob semantics: `extglob`, direct source glob arguments, and full
  `GLOBIGNORE` edge behavior
- Broader case pattern and fallthrough semantics
- Runtime-dynamic dispatch, recursive functions, non-equivalent branch-defined
  functions, and branch-dependent function returns
