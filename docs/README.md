# modashc Design Docs

This directory holds implementation specs for behavior that is too nuanced to
keep only in code comments or tests.

## Specs

- [Dynamic Source Resolution](dynamic-source-resolution.md): Python-only
  resolution of common runtime-looking `source` idioms without executing shell
  code.

## Planned Specs

- Loop and conditional source discovery
- Source graph diagnostics and unsupported-case reporting
- Parser boundaries and Bash grammar coverage
- Context output format
- Executable output semantics
