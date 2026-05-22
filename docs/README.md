# modashc Design Docs

This directory holds implementation specs for behavior that is too nuanced to
keep only in code comments or tests.

## Specs

- [Dynamic Source Resolution](dynamic-source-resolution.md): Python-only
  resolution of common runtime-looking `source` idioms without executing shell
  code.
- [Next-Generation Evaluator And IR Plan](evaluator-ir-plan.md): Deferred
  architecture plan for loops, arrays, globs, conditionals, cases, and
  function-aware source discovery.

## Planned Specs

- Structured source diagnostics and unsupported-case reporting
- Parser boundaries and Bash grammar coverage
- Context output format
- Executable output semantics

## Deferred Specs

These require the next-generation evaluator or IR and are intentionally outside
the current resolver-driven compiler. The intended approach is captured in the
[Next-Generation Evaluator And IR Plan](evaluator-ir-plan.md):

- Loop-driven source discovery
- Conditional and case-driven source discovery
- Array/list source paths
- Glob iteration semantics
- Runtime dispatch and user-defined source-path functions
