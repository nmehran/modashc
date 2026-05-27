# Supported Source Resolution

This document is the user-facing contract for source discovery and executable
lowering. `modashc` resolves `source` and `.` dependencies without executing
shell code. Context mode may preserve unresolved source text for readability,
but executable mode only lowers source sites that can be resolved exactly.

## Output Mode Contract

- **Context mode** is readable-first. It renders one deduplicated section per
  resolved file, preserves original source lines, and annotates resolved source
  relationships.
- **Executable mode** is parity-first. It inlines source bodies at the source
  site when the evaluator can preserve supported Bash parent-source semantics.
- Unsupported executable-mode source sites fail before the output file is
  written or overwritten.

## Static Paths

Supported:

```bash
source ./dep.sh
. ./dep.sh
source ../shared/dep.sh
source "./dir with spaces/dep.sh"
source ./dir#tag/dep.sh
source ./config
source "/absolute/path/dep.sh"
```

This includes relative, parent-relative, absolute, non-`.sh`, spaces, and `#`
inside path components.

## Variables And Path Commands

Supported when the values are exact:

```bash
DEP_PATH="./dep.sh"
source "$DEP_PATH"

source "$ENV_PROVIDED_ABSOLUTE_PATH"

THIS_DIR="$(dirname "$BASH_SOURCE")"
source "$THIS_DIR/dep.sh"

source "$(dirname "$BASH_SOURCE")/dep.sh"
source "./plugins/$(basename ./plugins/dep.sh .sh).sh"
source "$(realpath ./dep.sh)"
```

The supported path command substitutions are `dirname`, `basename`, and
`realpath`.

## Safe File And Command Producers

Supported when producer output is exact for the current project tree and
resolves to the required number of paths:

```bash
source "$(cat dep-path.txt)"
source "$(find ./plugins -name dep.sh)"
eval "source ./dep.sh"
```

For loop word lists and read-loop producers, the supported safe commands are
`cat`, `find`, `printf`, `sort`, `head`, `grep -lF`, `grep -lE`, `realpath`,
`dirname`, and `basename`.
Modeled `find` producers preserve Bash/GNU `find` traversal order rather than
sorting matches.

Context mode can classify `bash -c "source ..."` as child-shell context. It is
not executable-mode parent-source semantics.

## Arrays

Supported when indexes and values are exact:

```bash
deps=(./a.sh ./b.sh)
source "${deps[0]}"
source "${deps[$i]}"

declare -A by_env=([prod]=./prod.sh [dev]=./dev.sh)
source "${by_env[$ENV]}"
```

The evaluator also models exact array append, indexed assignment,
command-substitution array assignment, and `mapfile` / `readarray -t`
population from exact files.

## Loops

Supported finite loop forms include literal word lists, exact scalar word
lists, exact custom-IFS splitting, exact arrays, ordinary deterministic file
globs, safe command-substitution word lists, bounded C-style loops, bounded
`while` / `until`, and modeled `while read` file enumeration.

Examples:

```bash
for dep in ./a.sh ./b.sh; do
  source "$dep"
done

DEPS="./a.sh ./b.sh"
for dep in $DEPS; do
  source "$dep"
done

for dep in "${deps[@]}"; do
  source "$dep"
done

for dep in ./plugins/*.sh; do
  source "$dep"
done

for ((i=0; i<3; i++)); do
  source "./deps/$i.sh"
done

while read -r dep; do
  source "$dep"
done < deps.txt

find ./plugins -name '*.sh' -print | while read -r dep; do
  source "$dep"
done
```

Loop glob handling is option-aware for `nullglob`, `dotglob`, `globstar`,
`nocaseglob`, practical `GLOBIGNORE` filtering, comma braces, and simple brace
sequences.

## Direct Source Globs

Supported when the direct source glob resolves to one or more regular files:

```bash
source ./single-plugin/*.sh
```

When a direct source glob resolves to multiple matches, Bash treats the first
expanded word as the source file and passes the remaining expanded words as
positional arguments to that sourced file. Executable mode preserves that shape:

```bash
source ./plugins/*.sh extra
```

If `./plugins/*.sh` expands to `./plugins/00-loader.sh
./plugins/10-config.sh`, `00-loader.sh` is sourced with
`./plugins/10-config.sh` and `extra` as its `$1` and `$2`.

## Direct Source Arguments

Supported direct source sites may pass exact positional arguments to the
sourced file:

```bash
source ./library.sh alpha "beta gamma"
```

The sourced file sees those arguments as its temporary `$1`, `$2`, and `$@`
state. The caller's positional parameters are restored after the source site
returns, while normal sourced-file effects such as variables, functions, cwd,
and return status remain parent-visible. Nested source sites inherit the current
sourced-file positional state unless they pass their own exact arguments.

Source arguments must resolve to exact strings. Unresolved variables, command
substitution, unquoted `$@` / `$*`, and unquoted variable expansions that would
require word-splitting support remain fail-closed.

Executable mode models top-level positional mutation in wrapped sourced files
when Bash behavior is exact. Top-level `set -- ...` can update caller
positionals after a source site returns, while top-level `shift` inside an
explicit source-argument frame remains temporary as Bash restores that frame.
Sourced files without explicit source arguments can also mutate caller
positionals through top-level `set --` or `shift` when a generated return
wrapper is needed.

One Bash edge remains fail-closed: a sourced file entered with explicit source
arguments that runs top-level `set --` before a later nested `source` command.
Bash restores that explicit source-argument frame differently after the nested
source returns, so executable mode rejects the shape rather than guessing. This
is planned in
[Explicit Source Argument Frame Restoration](source-argument-frame-restoration.md).

## Sourced-File Return

Supported sourced files may contain top-level `return` statements. Executable
mode lowers those sourced bodies through generated same-shell helper functions
that are cleaned up after the source site runs. The lowered return stops the
sourced body, preserves source status, and does not exit the caller. This is
intended for normal sourced libraries and include guards; files that depend on
top-level `FUNCNAME` identity or invalid top-level `local` behavior remain
outside the supported contract.

```bash
source ./guarded-library.sh
echo "source status: $?"
```

This covers common include guards:

```bash
[[ -n "$LIBRARY_SH" ]] && return
LIBRARY_SH=1
```

## Branches And Cases

Supported branch-aware source lowering includes `if` / `elif` / `else` with
side-effect-free file, non-empty, empty, exact string, pattern, compound
logical, arithmetic, regex, and safe `grep -q` predicates.
Unknown runtime predicates are preserved when the predicate itself is not a
source-bearing command and branch-local source sites are exact.

```bash
if [[ -f ./optional.sh ]]; then
  source ./optional.sh
fi

if grep -q enabled config; then
  source ./enabled.sh
else
  source ./disabled.sh
fi
```

Exact source atoms are also supported inside top-level `if` / `elif` logical
condition lists. The compiler lowers only the source atom and leaves the
runtime guard shape intact:

```bash
if source ./dep.sh && runtime_probe; then
  echo loaded
fi

if runtime_probe || source ./fallback.sh; then
  echo ready
fi
```

Source effects that depend on a runtime condition are treated as conditional.
Later source sites fail closed if they need variables, arrays, cwd, shell
options, functions, or positional state that diverged across possible
condition paths.

Supported `case` blocks use modeled arm patterns: literal patterns, alternate
patterns, default arms, quoted literals, mixed quoted/unquoted segments,
backslash-escaped literals, ordinary glob patterns, bracket expressions, POSIX
character classes in the modeled C-locale subset, and exact scalar
variable-expanded patterns. Known scalar subjects are statically selected.
Unknown runtime subjects preserve the original `case` and lower exact source
sites in all runtime-possible arms. Source-bearing `case` arms may use `;;`,
`;&`, or `;;&` terminators.

```bash
case "$ENV" in
  prod) source ./prod.sh ;;
  dev) source ./dev.sh ;;
  *) source ./default.sh ;;
esac
```

## Functions

Supported function calls are bounded and local. The function definition must be
known, arguments must be exact, and source-relevant body effects must be
modeled.

Supported source-relevant effects include positional source arguments, exact
assignment prefixes, `local` scalar assignments, cwd changes, exact `return` /
`shift`, exact dynamic dispatch, nested modeled control flow, same-line
post-definition calls, source-equivalent branch-defined functions,
function-call status for chained source sites, and functions defined by sourced
files.

```bash
load_dep() {
  source "$1"
}

load_dep ./dep.sh
```

## Unsupported In Executable Mode

Unsupported or ambiguous source forms fail closed before output is written.
Common examples:

```bash
source "$DEP"                        # DEP unknown
source ./dep.sh "$UNKNOWN_ARG"       # source argument unknown
source ./dep.sh $ARG_WITH_SPACES     # would require word splitting
source ./missing/*.sh                # unmatched direct glob
source "$(cat one two)"              # ambiguous path output
source "$(find . -name '*.sh')"      # ambiguous when multiple files match
source "$(cat dep-path.txt | sort)"  # unapproved source-site pipeline
source `cat dep-path.txt`            # backticks
eval "source ./dep.sh; echo extra"   # unsafe eval payload
bash -c "source ./dep.sh"            # child-shell semantics
```

Other fail-closed families include unmatched or quoted globs, `extglob`
patterns, `set -f` / `noglob`, `failglob` unmatched globs, `GLOBIGNORE`
patterns that remove every source match, source commands in pipelines,
subshells, command substitutions, process substitutions, or unsupported shell
grammar, unsupported dynamic `case` subjects or arm patterns, unsupported
process substitution outside modeled read-loop input, unknown runtime-dynamic
or recursive function dispatch, non-equivalent branch-defined functions,
branch-dependent function returns, nested dynamic substitutions, and
multi-result command-substitution output where a single source path is
required.

## Practical Remaining Work

The remaining source-resolution surface is narrower than general Bash support:

- Explicit source-argument frames that combine top-level `set --` with later
  nested source calls remain fail-closed; see
  [Explicit Source Argument Frame Restoration](source-argument-frame-restoration.md).
- `extglob` and full Bash edge semantics for `GLOBIGNORE`.
- Remaining case edge semantics such as `extglob` patterns, collating symbols,
  equivalence classes, and broader locale-dependent pattern behavior.
- Recursive or runtime-dynamic source-bearing function dispatch. Exact
  makepkg-style helper calls using quoted `$@` / `$*` are covered by
  [Source Supplements And Exact Helper Sources](source-supplements.md).
  Retained helper definitions that remain callable after merging are covered in
  [Retained Helper Dispatch](retained-helper-dispatch.md).
