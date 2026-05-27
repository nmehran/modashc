# Runtime-Guarded Static Source Lowering

## Status

Planned next product iteration on the
`iteration/runtime-guarded-source-lowering` development branch. It builds on
source argument completion and source-relevant control-flow boundaries.

This iteration remains static. It does not use Bash execution, xtrace, runtime
source discovery, or sandboxed tracing.

## Summary

The compiler can now lower exact source sites inside modeled control flow and
can pass through source-free unsupported runtime logic. The next practical gap
is source-bearing runtime control flow whose source paths are already exact but
whose predicates or subjects are not statically known.

For those cases, modashc should preserve the original runtime guard and lower
the exact source sites inside the guarded body. It should not try to validate or
execute the guard. It should fail only when dependency paths, source arguments,
or later source-relevant state cannot be proven safe.

Conceptually, this:

```bash
if some_runtime_probe; then
  source ./feature.sh
fi
```

can become executable output where `some_runtime_probe` remains live Bash and
`./feature.sh` is inlined inside the same branch.

## What Remains

High-value remaining gaps before this iteration:

- Unknown `if` / `elif` predicates still block executable output when a branch
  contains otherwise exact source sites.
- Unknown `case` subjects still block source-bearing executable output even
  when every arm source path is exact and the original case can be preserved.
- Branch-local source effects can be lowered, but later source resolution must
  still fail if it depends on branch-divergent variables, arrays, cwd, shell
  options, function definitions, or positional state.
- Runtime loops, compound direct source conditions, parser-level compound
  `if source ./dep.sh && ...` forms, recursive/runtime-dynamic dispatch, xtrace
  discovery, `extglob`, and full `GLOBIGNORE` edge behavior remain later work.

## Non-Goals

- Do not evaluate arbitrary predicates.
- Do not run Bash or collect xtrace output.
- Do not infer dependencies from runtime-observed behavior.
- Do not leave live unresolved `source` or `.` commands in executable output.
- Do not model runtime loops in this iteration.
- Do not broaden recursive or runtime-dynamic function dispatch.
- Do not support compound direct source conditions as a parser side effect.

## Tranche 1: Unknown If Predicate Source Lowering

Executable mode should lower exact source sites inside `if` / `elif` / `else`
branches even when the branch predicate itself is unknown or unsupported.

Acceptance:

- Unsupported command predicates such as `if awk 'BEGIN { exit 0 }'; then`
  preserve the original predicate and lower exact branch-local source sites.
- Runtime-variable predicates such as `if [[ -n "$ENABLE_FEATURE" ]]; then`
  lower exact branch-local source sites without requiring compile-time
  environment values.
- The generated executable contains no live source command for lowered branch
  source sites.
- Branch state after an unknown predicate is merged conservatively. Later source
  sites that depend on divergent branch state still fail with
  `unsupported.source.branch-state`.
- Source expressions or source arguments that are unresolved inside the branch
  still fail before output.
- Branch-dependent source or function returns remain fail-closed unless they
  are already modeled exactly.

Implementation notes:

- Reuse the existing context-mode possible-outcome machinery, but keep
  executable-mode fail-closed behavior for unresolved source paths.
- Preserve branch structure in the rendered executable; only replace source
  sites inside the original branch bodies.
- Record conditional or mutually exclusive occurrence context for lowered
  branch source events.

## Tranche 2: Unknown Case Subject Source Lowering

Executable mode should lower exact source sites inside `case` arms when the
case subject is runtime-dynamic but the original case statement can be
preserved.

Acceptance:

- `case "$MODE" in prod) source ./prod.sh ;; dev) source ./dev.sh ;; esac`
  lowers both exact source sites while leaving the runtime case intact.
- Unknown subjects with exact arms merge state conservatively after the case.
- Later source sites depending on branch-divergent case state fail closed.
- Existing exact-subject case behavior remains unchanged.
- Existing unsupported case pattern families remain unsupported:
  mixed quoting, backslash normalization, POSIX classes, extglob-dependent
  patterns, variable-expanded patterns, and fallthrough terminators.

Implementation notes:

- Start with the current supported case pattern subset and `;;` terminators.
- Do not model `;&` or `;;&` in this iteration.
- Do not claim runtime parity for context mode beyond readable provenance.

## Tranche 3: Real-World And Ergonomics Promotion

Add controlled fixtures and real-world coverage so this behavior is not only
synthetic.

Acceptance:

- Add a small pinned-corpus fixture for runtime-guarded `if` source lowering.
- Add a small pinned-corpus fixture for runtime-guarded `case` source lowering.
- Runtime parity probes compare original and compiled behavior for at least one
  enabled and one disabled guarded branch.
- Artifact scan confirms successful executable outputs contain no live source
  commands.
- Generated artifacts are manually/LLM reviewed for readability and guard
  preservation.

## Review Checklist

Required checks before committing implementation work:

- `python -m unittest -v`
- `MODASHC_REALWORLD=1` pinned corpus
- `MODASHC_REALWORLD=1 MODASHC_REALWORLD_RUNTIME=1` runtime parity probes
- executable artifact scan for live `source` commands
- spot-check generated guarded-if and guarded-case executable artifacts

## Later Work

Runtime loops with exact source-invariant bodies should be a separate
iteration. They need explicit repeated-occurrence and post-loop state semantics.

Compound direct source conditions such as `if source ./dep.sh && test ...; then`
also remain separate because they require frontend grammar work before lowering
can be correct.

Runtime source discovery with xtrace remains a later 0.5-class feature.
