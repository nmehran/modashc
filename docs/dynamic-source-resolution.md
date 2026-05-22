# Dynamic Source Resolution

## Status

Initial implementation. The compiler supports static sources,
variable/env-expanded paths, path command substitutions such as `dirname`,
`basename`, and `realpath`, plus the first Python-only dynamic resolver subset:
safe `cat`, safe `find`, safe `eval source`, and context-only `bash -c source`
classification. The source-effect evaluator also supports exact finite `for`
loops over literal words, known scalar path variables, default-IFS scalar word
lists, and exact `${array[@]}` expansions, plus deterministic ordinary file
globs in finite loop word lists.
Direct source globs are accepted only when they resolve to exactly one file.
Modeled `if` / `elif` / `else` blocks can lower source sites inside branches
when branch predicates are side-effect-free and branch state is exact enough for
later source resolution. Executable mode neutralizes source sites in statically
unreachable branches instead of resolving or preserving them as live runtime
sources. The current modeled condition subset includes exact file/string tests,
compound logical predicates, arithmetic predicates, regex and pattern matching,
and safe `grep -q` file checks. Exact `case` blocks can lower source sites for
known scalar subjects and modeled arm patterns, with non-matching arm sources
neutralized in executable output. Bounded local function calls can lower sources
when the function definition is known, arguments are exact, and source-relevant
function body effects are modeled.
Unsupported forms fail closed.

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
- Executable mode must not emit unresolved live `source` commands.
- Unsupported cases must fail before output is written.
- Context mode may preserve unresolved source text for readability, but it must
  not claim a resolved dependency unless resolution is exact.

## Resolver Priority

Resolvers should be tried from most explicit to most specialized:

1. Literal path resolver
2. Known variable and environment resolver
3. Path command resolver: `dirname`, `basename`, `realpath`
4. Safe `cat` resolver
5. Safe `find` resolver
6. Direct one-match glob resolver
7. Safe `eval source` resolver
8. Safe `bash -c source` classifier
9. Unsupported dynamic diagnostic

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

for dep in ./a.sh ./b.sh; do
  source "$dep"
done

deps=(./a.sh ./b.sh)
for dep in "${deps[@]}"; do
  source "$dep"
done

for dep in ./plugins/*.sh; do
  source "$dep"
done

source ./single-plugin/*.sh

if [[ -f ./optional.sh ]]; then
  source ./optional.sh
fi

if [[ "$MODE" == prod ]]; then
  source ./prod.sh
else
  source ./dev.sh
fi
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
  - `-quit`, only after `-print`
- No `-exec`, `-delete`, `-ok`, `-printf`, shell escapes, pipes, redirects, or
  process substitutions are present.
- The resolver finds exactly one matching regular file.
- Traversal order is deterministic, such as sorted path order.

Reject examples:

```bash
source "$(find . -name dep.sh)"
source "$(find . -name dep.sh -quit)"
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
eval "$KNOWN_SOURCE_COMMAND"
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
eval "$UNRESOLVED_OR_MULTI_COMMAND_PAYLOAD"
eval "DEP=./dep.sh; source \"$DEP\""
eval "source $(cat dep-path.txt)"
```

The last example should be rejected at the `eval` layer initially. A later
implementation may allow nested resolver dispatch only if diagnostics remain
clear and the parser can prove there is still one source command.

### Deterministic Globs

Target loop forms:

```bash
for dep in ./plugins/*.sh; do
  source "$dep"
done

for dep in "./plugin dir#tag"/*.sh; do
  source "$dep"
done
```

Target direct-source form:

```bash
source ./single-plugin/*.sh
```

Accept loop globs only when:

- The glob metacharacters are unquoted.
- The pattern is an ordinary file glob using `*`, `?`, or `[]`.
- Expansion is cwd-aware and deterministic.
- Every match is a regular file.
- No modeled shell state changes the meaning of the glob.

Accept direct source globs only when the glob resolves to exactly one regular
file. Multiple direct-source matches are rejected because Bash would source the
first expanded word and pass the remaining words as positional arguments to that
sourced file, which is not equivalent to sourcing every match.

Reject examples:

```bash
source ./plugins/*.sh          # multiple matches
for dep in "./plugins/*.sh"; do source "$dep"; done
for dep in ./plugins/**/*.sh; do source "$dep"; done
for dep in ./plugins/{a,b}.sh; do source "$dep"; done
shopt -s nullglob
for dep in ./plugins/*.sh; do source "$dep"; done
```

Currently rejected glob-affecting state includes `set -f`, non-empty
`GLOBIGNORE`, and enabled `shopt` options such as `nullglob`, `failglob`,
`dotglob`, `globstar`, `extglob`, and `nocaseglob`.

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

These still need separate specs before implementation:

- Broader glob semantics beyond ordinary deterministic file globs.
- Custom-IFS scalar word-list splitting.
- Conditional predicates outside the modeled side-effect-free subset.
- Broader case pattern and fallthrough semantics.
- Complex array/list-based source paths.
- Broader user-defined function semantics, including dynamic dispatch,
  recursive calls, `return`, `shift`, and nested modeled control flow.
- Process substitution and generated source streams.

### Unsupported But Practical

These are intentionally tracked as practical future work, not permanently
unsupported forms:

- Glob-bearing conditional predicates such as `[ -f ./plugins/*.sh ]`.
- Command predicates outside the safe `grep -q` file-check subset.
- Regex predicates requiring POSIX classes or unsupported Bash ERE behavior.
- Nested modeled control flow inside branch bodies when the current line
  frontend cannot preserve exact nested locations.
- Branch-divergent cwd, variables, arrays, or shell options followed by later
  source resolution that depends on that divergent state.
- Case subjects or arm patterns outside the exact modeled case subset.
- Case patterns that need shell normalization for mixed quoting, backslash
  escapes, or POSIX character classes.
- Case fallthrough terminators, `;&` and `;;&`.

These are not merely more dynamic resolvers. They require control-flow and
multi-result semantics, and they should be designed separately.

Executable mode fails closed when a source command appears inside these
unsupported families. That prevents output from silently preserving runtime
`source` behavior that the compiler has not lowered.

## Test Requirements

Each resolver needs tests for:

- accepted exact source resolution
- rejected ambiguous output
- rejected unsafe syntax
- context-mode rendering
- executable-mode parity or explicit executable-mode rejection
- diagnostics that identify the rejected source site
- unsupported executable-mode failures that do not create or overwrite output

Regression tests should use real temporary shell projects through
`ScriptProject`, not mocked strings alone.

## Implementation Status

The initial resolver layer now covers the current resolver-driven compiler
scope:

- `ResolvedSource` records describe exact dependency resolution.
- `methods.source_resolver` owns source command detection, heredoc guards, safe
  dynamic source resolvers, and unsupported-source classification.
- `methods.source_evaluator` owns traversal, cwd tracking, variable state, and
  source-event production.
- `methods.sources` owns path-resolution helpers and the `get_sources()`
  compatibility wrapper over source-effect evaluation.
- Safe `cat`, safe `find`, safe `eval source`, and context-only
  `bash -c source` classification are implemented.
- Exact finite `for` loop lowering is implemented for literal words, known
  scalar path variables, and exact `${array[@]}` expansion.
- Deterministic ordinary file-glob loop lowering is implemented, and direct
  source globs are implemented for one-match cases only.
- Branch-aware `if` / `elif` / `else` source lowering is implemented for the
  side-effect-free predicate subset and fail-closed branch-state merge.
- Exact `case` source lowering is implemented for known scalar subjects,
  mutually exclusive arms, and no-op unreachable source sites.
- Bounded local function source lowering is implemented for known definitions,
  exact arguments, positional source expressions, parent-state mutations, and
  exact assignment prefixes and scalar `local` assignments.
- Executable mode fails before output when unsupported source forms would leave
  live runtime `source` commands.

Structured diagnostic objects are implemented for unsupported source failures.
Current diagnostics are raised as explicit `UnsupportedSourceError` instances
with stable codes, source locations, rejected fragments, messages, and hints.

Future resolver increments should stay small, tested, and fail-closed. Case,
complex array, broader conditional, broader glob, broader function control
flow, and runtime-dispatch support should not be added as one-off resolver
patches; those belong in the evaluator/IR design.
