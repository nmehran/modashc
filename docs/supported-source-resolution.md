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

Supported only when the direct source glob resolves to exactly one file:

```bash
source ./single-plugin/*.sh
```

Direct source globs with multiple matches remain unsupported because Bash treats
the first match as the source file and passes the remaining matches as
positional arguments to that sourced file.

## Branches And Cases

Supported branch-aware source lowering includes `if` / `elif` / `else` with
side-effect-free file, non-empty, empty, exact string, pattern, compound
logical, arithmetic, regex, and safe `grep -q` predicates.

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

Supported `case` blocks require known scalar subjects and modeled arm patterns:
literal patterns, alternate patterns, default arms, quoted literals, and
ordinary glob patterns without mixed quoting, backslash escapes, POSIX
character classes, or fallthrough terminators.

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
source "$DEP"                       # DEP unknown
source ./dep.sh arg1                # direct source positional args
source ./plugins/*.sh               # direct glob with multiple matches
source "$(cat one two)"             # ambiguous path output
source "$(find . -name '*.sh')"     # ambiguous when multiple files match
source "$(cat dep-path.txt | sort)" # unapproved source-site pipeline
source `cat dep-path.txt`           # backticks
eval "source ./dep.sh; echo extra"  # unsafe eval payload
bash -c "source ./dep.sh"           # child-shell semantics
```

Other fail-closed families include unmatched or quoted globs, `extglob`
patterns, `set -f` / `noglob`, `failglob` unmatched globs, `GLOBIGNORE`
patterns that remove every source match, unsupported command or glob-bearing
file/bracket conditional predicates, unsupported case subjects or arm patterns,
unsupported process substitution outside modeled read-loop input, unknown
runtime-dynamic or recursive function dispatch, non-equivalent branch-defined
functions, branch-dependent function returns, nested dynamic substitutions, and
multi-result command-substitution output where a single source path is required.

## Practical Remaining Work

The remaining source-resolution surface is narrower than general Bash support:

- Direct `source` positional arguments and direct source glob multi-match
  argument semantics.
- Broader source guards, including more command predicates and glob-bearing
  file tests.
- `extglob` and full Bash edge semantics for `GLOBIGNORE`.
- Broader `case` pattern and fallthrough semantics for source-bearing arms.
- Recursive or runtime-dynamic source-bearing function dispatch. Exact
  makepkg-style helper calls using quoted `$@` / `$*` are covered by
  [Source Supplements And Exact Helper Sources](source-supplements.md).
  Retained helper definitions that remain callable after merging are covered in
  [Retained Helper Dispatch](retained-helper-dispatch.md).
- Bash-equivalent lowering for top-level `return` in inlined sourced files.
  Retained helper dispatch rejects this case before output today.
