# Dynamic Source Resolution

## Status

Initial implementation. The compiler supports static sources,
variable/env-expanded paths, path command substitutions such as `dirname`,
`basename`, and `realpath`, plus the first Python-only dynamic resolver subset:
safe `cat`, safe `find`, safe `eval source`, and context-only `bash -c source`
classification. Unsupported forms fail closed.

## Goal

Support common source-path idioms found in shell projects without executing
shell code. The resolver should turn known-safe expressions into resolved source
paths, and should produce explicit unsupported diagnostics when an expression is
ambiguous, side-effectful, or outside the supported subset.

The compiler is not a sandbox and should not become one. Dynamic source
resolution belongs in a deterministic Python resolver layer, not in the optional
setup shell helper.

## Non-Goals

- Do not execute shell commands.
- Do not execute `eval`.
- Do not run a restricted shell to discover dependencies.
- Do not infer dependencies from arbitrary Bash semantics.
- Do not silently omit unresolved source statements.
- Do not treat context mode as a license to guess.

## Terms

- **Source site**: A `source` or `.` command in an input file.
- **Source expression**: The argument portion of a source site, such as
  `"./dep.sh"` or `"$(cat dep-path.txt)"`.
- **Resolver**: A Python component that can prove a source expression resolves
  to one or more files.
- **Exact resolution**: A resolver result with deterministic file path output
  and no side effects.
- **Unsupported diagnostic**: A structured failure explaining why the compiler
  refused to resolve a source site.
- **Parent-source semantics**: The sourced file runs in the current shell
  context, matching normal `source ./dep.sh`.
- **Child-shell semantics**: The sourced file runs inside a child process, such
  as `bash -c "source ./dep.sh"`.

## Resolver Contract

Each resolver must be pure, deterministic, and fail closed. A resolver accepts
the current parser context and a source site, then returns either resolved
source records or an unsupported diagnostic.

Resolved source records should carry enough metadata for both renderers:

```python
ResolvedSource(
    path="/absolute/path/to/dep.sh",
    source_expression='"$(cat dep-path.txt)"',
    source_site='source "$(cat dep-path.txt)"',
    execution_model="parent-source",
    confidence="exact",
)
```

The minimum fields are:

- `path`: absolute resolved path.
- `source_expression`: original source argument.
- `source_site`: original source command or command fragment.
- `execution_model`: `parent-source`, `child-shell`, or `context-only`.
- `confidence`: `exact` for accepted compiler dependencies.

Executable mode should accept only `parent-source` records unless the compiler
implements an explicit equivalent for another execution model. Context mode may
render `context-only` records, but the output must make that limitation clear.

## Safety Rules

- Resolver input is parsed data, not shell text to execute.
- File reads are allowed only for resolvers whose purpose is file-content path
  lookup, such as safe `cat`.
- Directory walks are allowed only for safe `find` subsets.
- Multiple candidate paths are unsupported in executable mode unless the source
  form has deterministic multi-source semantics.
- Ambiguous current-directory state is unsupported.
- Any command separator, redirection, pipe, process substitution, background
  operator, or unapproved command substitution in a dynamic source expression is
  unsupported.
- Unsupported cases must fail before output is written.

## Resolver Priority

Resolvers should be tried from most explicit to most specialized:

1. Literal path resolver
2. Known variable and environment resolver
3. Path command resolver: `dirname`, `basename`, `realpath`
4. Safe `cat` resolver
5. Safe `find` resolver
6. Safe `eval source` resolver
7. Safe `bash -c source` classifier
8. Unsupported dynamic diagnostic

The resolver registry should make this ordering explicit in code and tests.

## Existing Supported Forms

These are already expected to resolve:

```bash
source ./dep.sh
. ./dep.sh
source ../shared/dep.sh
source "./dir with spaces/dep.sh"
source ./dir#tag/dep.sh
source ./config
source "/absolute/path/dep.sh"

DEP_PATH="/absolute/path/dep.sh"
source "$DEP_PATH"

DEP_PATH="$ENV_PROVIDED_ABSOLUTE_PATH"
source "$DEP_PATH"

THIS_DIR="$(dirname "$BASH_SOURCE")"
source "$THIS_DIR/dep.sh"

source "$(dirname "$BASH_SOURCE")/dep.sh"
source "$(realpath ./dep.sh)"
```

## Implemented Resolver Subset

### Safe `cat`

Target forms:

```bash
source "$(cat dep-path.txt)"
. "$(cat ./dep-path.txt)"
```

Accept only when:

- `cat` has exactly one operand.
- The operand path is statically resolved.
- The operand is a regular file.
- The file content contains exactly one non-empty line after trimming one final
  newline.
- The resolved line is a valid source path under the current parser context.
- No flags, pipes, redirects, process substitutions, globs, or extra command
  substitutions are present.

Reject examples:

```bash
source "$(cat one two)"
source "$(cat dep-path.txt | head -1)"
source "$(cat < dep-path.txt)"
source "$(cat "$(other)")"
```

### Safe `find`

Target forms:

```bash
source "$(find . -name dep.sh -print -quit)"
source "$(find ./plugins -type f -name init.sh -print -quit)"
```

Accept only when:

- Search roots are statically resolved directories.
- Supported predicates are limited to:
  - `-name <pattern>`
  - `-path <pattern>`
  - `-type f`
  - `-maxdepth <n>`
  - `-mindepth <n>`
  - `-print`
  - `-quit`
- No `-exec`, `-delete`, `-ok`, `-printf`, shell escapes, pipes, redirects, or
  process substitutions are present.
- The resolver finds exactly one matching regular file.
- Traversal order is deterministic, such as sorted path order.

Reject examples:

```bash
source "$(find . -name dep.sh)"
source "$(find . -exec echo {} \;)"
source "$(find . -name '*.sh' | head -1)"
```

The first rejection is intentional unless the resolver can prove exactly one
result. If multiple files match, executable mode must reject rather than choose
one implicitly.

### Safe `eval source`

Target forms:

```bash
eval "source ./dep.sh"
eval ". \"$DEP_PATH\""
```

Accept only when:

- After known variable and environment expansion, the eval payload parses as
  exactly one source command.
- The source expression inside the payload resolves through the normal resolver
  registry.
- No nested `eval`, command separators, redirects, pipes, assignments,
  functions, arithmetic expansion, or unapproved substitutions are present.

Reject examples:

```bash
eval "source ./dep.sh; rm -rf out"
eval "$COMMAND"
eval "DEP=./dep.sh; source \"$DEP\""
eval "source $(cat dep-path.txt)"
```

The last example should be rejected at the `eval` layer initially. A later
implementation may allow nested resolver dispatch only if diagnostics remain
clear and the parser can prove there is still one source command.

### `bash -c "source ..."`

Target forms:

```bash
bash -c "source ./dep.sh"
bash -c ". ./dep.sh"
```

This is not equivalent to parent-shell `source`. The sourced file executes in a
child Bash process, so variable and directory side effects do not propagate back
to the parent script.

Recommended initial handling:

- Context mode may record the dependency as `context-only` or `child-shell`.
- Executable mode should reject unless it implements child-shell-equivalent
  rendering.
- Diagnostics must state that the command uses child-shell semantics.

Executable support, if added later, should render an equivalent child-shell
boundary rather than inline the file into the parent shell.

## Future Pattern Families

These need separate specs before implementation:

- Loop-driven source sites:
  ```bash
  for file in ./plugins/*.sh; do
    source "$file"
  done
  ```
- Conditional sources:
  ```bash
  if [[ -f ./local.sh ]]; then
    source ./local.sh
  fi
  ```
- Case-driven source selection.
- Array/list-based source paths.
- Glob expansion as dependency source.
- User-defined functions that compute source paths.
- Process substitution and generated source streams.

These are not merely more dynamic resolvers. They require control-flow and
multi-result semantics, and they should be designed separately.

## Test Requirements

Each resolver needs tests for:

- accepted exact source resolution
- rejected ambiguous output
- rejected unsafe syntax
- context-mode rendering
- executable-mode parity or explicit executable-mode rejection
- diagnostics that identify the rejected source site

Regression tests should use real temporary shell projects through
`ScriptProject`, not mocked strings alone.

## Implementation Plan

The initial resolver layer now covers steps 1 through 7. Remaining work should
keep extending the resolver registry in small, tested increments.

1. Introduce a resolver result type and unsupported diagnostic type.
2. Move current source-expression handling behind a resolver registry.
3. Port existing literal, variable, env, `dirname`, `basename`, and `realpath`
   behavior into registry tests without behavior changes.
4. Add safe `cat`.
5. Add safe `find`.
6. Add safe `eval source`.
7. Add `bash -c source` classification and mode-specific handling.
8. Continue refining context output execution-model annotations as new
   non-parent-source dependency classes are added.

Each step should keep the full test suite green and avoid broad parser rewrites.
