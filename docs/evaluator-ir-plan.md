# Next-Generation Evaluator And IR Plan

## Status

Partially implemented. The compiler now has a source-effect IR frontend,
structured unsupported-source diagnostics, and an abstract evaluator that drives
both executable and context rendering for the supported subset. Exact finite
`for` loops over literal words, known scalar path variables, exact custom-IFS
scalar word lists, exact `${array[@]}` expansions, safe command-substitution
word lists, and deterministic file globs are implemented. Safe producers
include `cat`, `find`, `printf`, `sort`, `head`, `grep -lF` / `grep -lE`,
`realpath`, `dirname`, and `basename`. Exact indexed, associative, appended,
command-substitution, and file-populated arrays are modeled. Bounded `while` /
`until`, C-style `for ((...))`, and `while read` file enumeration are also
implemented, including exact file input, safe producer pipelines, and safe
process substitutions. Branch-aware `if` / `elif` / `else`
lowering is implemented for the current side-effect-free predicate subset,
including compound logical predicates, arithmetic predicates, regex and pattern
matching, and safe `grep -q` file checks. Runtime-guarded lowering also
preserves unknown `if` predicates when branch-local source sites are exact.
Exact `case` blocks are implemented for known subjects and the modeled pattern
subset, including practical quoting, bracket/POSIX-class patterns, exact
variable-expanded patterns, and fallthrough terminators. Unknown scalar subjects
preserve the runtime `case` and lower exact arm source sites. Bounded local
function calls are implemented when the definition is known, arguments are
exact, and source-relevant body effects are modeled. It remains fail-closed for
broader glob semantics, source-bearing pipelines and unsupported compound
grammar, remaining case edge semantics such as `extglob`, recursive functions,
runtime-dynamic function dispatch, and child-shell runtime dispatch.
Exact source atoms in top-level logical condition lists are covered by
[Compound Source Condition Lowering](compound-source-condition-lowering.md).

## Problem

The current compiler can resolve a useful exact subset of Bash source patterns,
but it does not fully model Bash control flow. Patterns like these drive the
remaining work when their predicates, patterns, or state effects fall outside
the exact modeled subsets:

```bash
if [[ -f ./local.sh ]]; then
  source ./local.sh
fi

case "$ENV" in
  prod) source ./prod.sh ;;
  dev) source ./dev.sh ;;
esac
```

Supporting those safely requires continuing the compiler model, not adding more
ad hoc source regexes. Branch-aware `if` lowering, exact `case` lowering, and
bounded function calls are implemented for practical first subsets. The next
steps are broader practical conditional predicates, remaining case edge
semantics, and broader function control-flow semantics.

## Goals

- Preserve executable-mode Bash parity for every supported pattern.
- Preserve context-mode readability and provenance.
- Evaluate common source-discovery idioms without executing shell code.
- Represent ambiguity explicitly instead of guessing.
- Keep unsupported forms fail-closed before output is written.
- Make diagnostics structured enough to identify file, line, command fragment,
  unsupported construct, and suggested next action.
- Keep the current resolver subset working while the IR is introduced.

## Non-Goals

- Do not implement a complete Bash interpreter.
- Do not execute arbitrary shell, `eval`, command substitutions, functions, or
  subprocesses to discover dependencies.
- Do not use the optional setup shell helper as a compiler sandbox.
- Do not silently include all branches of runtime-dependent logic in executable
  mode unless the branch semantics are explicitly modeled.
- Do not add one-off regex support for loops, arrays, or cases without IR
  coverage.

## Design Principles

- **Exact over broad**: accept only when the evaluator can prove the dependency
  set and execution model.
- **Stateful but bounded**: model cwd, variables, arrays, shell options, and
  functions only within documented limits.
- **Branch-aware**: distinguish unconditional, conditional, mutually exclusive,
  and repeated source execution.
- **Renderer-neutral**: IR should feed both context and executable renderers.
- **Incremental adoption**: each phase should be testable and mergeable without
  requiring the whole evaluator.

## Proposed Architecture

### 1. Parser Frontend

The parser frontend converts script text into a stream of IR nodes. It can start
with the existing line splitter plus targeted block parsing, but it should hide
that implementation behind one interface:

```python
parse_script(path: Path, content: str) -> ScriptIR
```

Long-term, this interface could be backed by a real Bash parser. Current code
should not depend directly on regex match tuples once IR exists.

### 2. IR Builder

The builder normalizes parser output into nodes with source locations:

```python
ScriptIR(
    path=Path("main.sh"),
    nodes=[
        Assignment(...),
        SourceSite(...),
        ForLoop(...),
        IfBlock(...),
        FunctionDef(...),
    ],
)
```

Every node should carry:

- input file path
- start line and end line
- original text
- command fragments relevant to diagnostics

### 3. Abstract Evaluator

The evaluator walks the IR with an abstract shell state:

```python
EvaluationState(
    cwd=Path(...),
    variables={...},
    arrays={...},
    shell_options={...},
    functions={...},
    bash_source_stack=[...],
)
```

Evaluation produces source events, diagnostics, and final state:

```python
EvaluationResult(
    events=[SourceEvent(...)],
    disabled_sources=[DisabledSourceSite(...)],
    diagnostics=[Diagnostic(...)],
    final_state=EvaluationState(...),
)
```

### 4. Resolver Bridge

Existing exact source-expression resolvers remain useful. The evaluator should
call them for expressions it extracts from IR:

```python
resolve_source_expression(expression, source_site, state)
```

The bridge converts evaluator state into the resolver context currently used by
`methods.source_resolver`.

### 5. Renderers

Renderers should consume source events rather than rediscovering source sites:

- Context mode renders unique file sections and source-event provenance.
- Executable mode lowers source events at source sites only when execution
  semantics are modeled exactly.

## Core IR Nodes

Initial nodes:

- `RawCommand`: command not otherwise modeled.
- `Assignment`: scalar assignment and export/local/declare subset.
- `ArrayAssignment`: indexed or list assignment.
- `CdCommand`: cwd-changing command.
- `SourceSite`: `source` or `.` command.
- `FunctionDef`: named function body.
- `FunctionCall`: call to a modeled function.
- `ForLoop`: `for name in words; do ... done`.
- `IfBlock`: condition plus then/elif/else bodies.
- `CaseBlock`: word plus pattern arms.
- `Subshell`: parenthesized command group with child-state semantics.
- `CommandGroup`: `{ ...; }` group with parent-state semantics.
- `DiagnosticNode`: parser recovery node for malformed or unsupported syntax.

Each source event should include:

- resolved path
- original source expression
- original source site
- file and line number
- execution model: parent-source, child-shell, context-only, unsupported
- occurrence model: once, repeated, conditional, mutually-exclusive
- state snapshot before the source runs

## State Model

### Current Directory

Model supported `cd` forms using the existing path resolver. Cwd state should
fork for branches and loop iterations. Unsupported `cd` expressions should make
subsequent relative source resolution unsupported, not guessed.

### Variables

Track scalar variables with value kinds:

- `ExactString`
- `ExactPath`
- `WordList`
- `Unknown`
- `Unsupported`

String concatenation and quoted expansion can be supported when all pieces are
exact. Unknown values should propagate.

### Arrays

Track arrays when assigned from exact words:

```bash
deps=(./a.sh "./b path.sh")
source "${deps[0]}"
```

Supported forms include:

- `${array[0]}`
- `${array[$index]}` when the index is exact
- `${assoc[$key]}` when the key is exact
- `${array[@]}` in loop word lists
- append and indexed assignment, such as `deps+=(./b.sh)` and
  `deps[1]=./b.sh`
- command-substitution array assignment, such as `deps=($(cat deps.txt))`
- `mapfile` / `readarray -t` population from an exact file

Associative arrays and computed indexes remain fail-closed unless exact.

### Shell Options

Track options that affect executable output and parity:

- `set -e`, `set +e`
- `set -u`, `set +u`
- `set -o pipefail`, `set +o pipefail`
- `set -E`, `set +E`

The current executable renderer already preserves source-site order; the IR
should preserve option state before each source event.

### Functions

Functions are parsed into `FunctionDef` nodes and stored in state. A function
call is evaluable only when:

- the function definition is known
- arguments are exact or unused by source-relevant expressions
- the function body contains only supported constructs
- recursion is absent

Function calls that mutate cwd or variables must update parent state, matching
Bash function semantics. The current subset supports exact positional
arguments such as `$1`, source-relevant scalar `local` assignments, cwd and
variable mutation in parent state, exact assignment prefixes, and functions
defined by sourced files, exact dynamic dispatch, exact `return` / `shift`,
same-line post-definition calls, nested modeled control flow, source-equivalent
branch-defined functions, and exact function-call status for chained source
sites. Recursive calls, branch-dependent returns, non-equivalent
branch-defined functions, and runtime-dynamic dispatch remain fail-closed until
explicitly modeled.

## Control-Flow Semantics

### Loops

Exact finite loops are supported when the word list is already concrete:

```bash
for file in ./a.sh ./b.sh; do
  source "$file"
done

deps=(./a.sh ./b.sh)
for file in "${deps[@]}"; do
  source "$file"
done

for file in ./plugins/*.sh; do
  source "$file"
done

for file in $(cat deps.txt); do
  source "$file"
done

while IFS= read -r file; do
  source "$file"
done < deps.txt
```

The evaluator lowers these by proving the finite values, recording source events
for each iteration, and rendering executable output as a runtime dispatch at the
original source site. Supported word inputs are:

- literal words
- exact array expansion
- known scalar path variables that expand to a single word
- known scalar values that split under exact current `IFS`
- deterministic ordinary file globs
- safe `cat`, `find`, `printf`, `sort`, `head`, `grep -lF` / `grep -lE`,
  `realpath`, `dirname`, and `basename` command-substitution word lists
- modeled `while read` file enumeration from exact files, safe producer
  pipelines, and safe process substitutions
- bounded `while` / `until` conditions with exact arithmetic mutations

Deferred word inputs are:

- broader glob semantics under shell options such as `extglob` and full
  `GLOBIGNORE`
- command-substitution word lists outside the safe producer subset
- loops whose conditions or mutations cannot be proven exact

Iteration limits are explicit. Exceeding the limit produces a structured
unsupported diagnostic.

### Conditionals

Conditionals now use two modes:

- **Exact condition**: evaluate the selected branch state when the predicate is
  known from modeled variables or filesystem predicates, and neutralize source
  sites in unreachable branches in executable output.
- **Unknown side-effect-free condition**: preserve the original branch in
  executable output, replace only modeled source sites inside it, and merge
  branch state only when source-relevant state converges.

Implemented predicates include:

- `[[ -f path ]]`
- `[[ -d path ]]`
- `[[ -e path ]]`
- `[[ -n "$KNOWN" ]]`
- `[[ -z "$KNOWN" ]]`
- exact string equality
- `[[ "$KNOWN" == pattern* ]]` and `[[ "$KNOWN" == $KNOWN_PATTERN ]]`
  pattern predicates
- compound `[[ ... && ... ]]`, `[[ ... || ... ]]`, and `!` predicates when
  each atom is modeled
- integer tests such as `[[ "$COUNT" -gt 1 ]]`
- arithmetic predicates such as `(( COUNT > 0 ))`
- regex predicates such as `[[ "$MODE" =~ ^prod ]]`
- safe literal or extended-regex `grep -q` file predicates
- `[ -f path ]`, `[ -d path ]`, `[ -e path ]`
- `test -f path`, `test -d path`, `test -e path`

Unsupported but practical predicates to track:

- glob-bearing file predicates such as `[ -f ./plugins/*.sh ]`
- command predicates outside the safe `grep -q` subset
- regex predicates requiring POSIX classes or unsupported Bash ERE behavior
- nested branch semantics that exceed the current line frontend
- divergent branch state followed by later state-dependent source resolution

### Case Statements

Case support starts with exact subject values:

```bash
case "$ENV" in
  prod) source ./prod.sh ;;
  dev) source ./dev.sh ;;
esac
```

Supported subjects:

- literal values
- known scalar variables
- known environment variables
- known assignments before the `case`

Supported arm patterns:

- literal patterns
- quoted literal patterns
- mixed quoted and unquoted literal segments
- backslash-escaped literal characters
- alternates such as `prod|stage`
- default `*`
- ordinary Bash case globs using `*`, `?`, or bracket classes
- POSIX character classes in the modeled C-locale subset
- exact scalar variable-expanded patterns

Executable mode evaluates matching arms in Bash order, including `;&` and
`;;&` fallthrough semantics, applies source-relevant state, and neutralizes
source sites in unreachable arms. If no arm matches, the case contributes no
source-relevant state. Context mode records possible arm dependencies with
readable provenance; fallthrough cases are annotated as conditional because
multiple arms may run.

Executable mode preserves unknown or runtime-dynamic subjects when all possible
source sites are exact and the original `case` can be retained. It rejects
`extglob`, collating symbols, equivalence classes, broader locale-dependent
patterns, and case bodies whose source-relevant behavior cannot be modeled.

### Globs

Ordinary file-glob expansion is implemented for finite loop word lists and for
direct source expressions with one or more matches. Option-aware loop glob
expansion is implemented for `nullglob`, `dotglob`, `globstar`, `nocaseglob`,
deterministic brace expansion, and practical `GLOBIGNORE` filtering. Broader
glob expansion should remain deterministic and cwd-aware:

- sort matches lexically
- reject `extglob`, `set -f`, and all-ignored `GLOBIGNORE` matches unless their
  semantics are fully modeled
- reject ambiguous directory state

## Diagnostics

Diagnostics should become typed objects:

```python
Diagnostic(
    code="unsupported.loop.dynamic-word-list",
    severity="error",
    path=Path("main.sh"),
    line=12,
    fragment='for f in $(cat deps.txt); do',
    message="loop word list is runtime-dynamic",
)
```

Minimum fields:

- stable code
- severity
- file path
- line number
- command fragment
- explanation
- optional hint

String messages can remain the CLI surface, but tests should assert diagnostic
codes once the type exists.

## Execution Models

The evaluator must keep these separate:

- `parent-source`: normal `source ./dep.sh`.
- `child-shell`: `bash -c "source ./dep.sh"` or subshell source.
- `context-only`: useful dependency for reading, not executable parity.
- `unsupported`: discovered but not safely lowerable.

Executable mode may only lower `parent-source` unless it has an explicit
equivalent renderer for the other model.

## Phased Implementation

### Phase 0: Current Resolver Baseline

Already complete:

- source-site inlining for executable mode
- context mode
- exact static sources
- safe `cat`, `find`, `eval`
- child-shell classification in context mode
- fail-closed unsupported families

### Phase 1: Parser Frontend Contract And Feasibility

Implemented for the current line frontend. The parser boundary is replaceable
and returns `ScriptIR` nodes with stable locations. A real Bash parser remains a
future adapter option when nested syntax coverage justifies the dependency.

Introduce a parser frontend interface and fixture matrix before committing to a
specific parser implementation. Evaluate candidates against real shell-project
fixtures:

- current targeted line parser
- `bashlex` or another Python-native Bash parser
- `tree-sitter-bash`
- any other parser that can produce stable locations and nested syntax

The output contract is `ScriptIR`, not a third-party AST shape. The project
should keep a replaceable parser boundary even if a real parser is adopted.

### Phase 2: Structured Diagnostics

Implemented for unsupported source failures. Raised errors carry diagnostic
objects with stable code, severity, file, line, fragment, message, and hint.

Introduce diagnostic types without changing behavior. Keep message strings as a
compatibility layer. Update tests to assert codes for unsupported source forms.

### Phase 3: IR Skeleton

Implemented for the supported subset: raw commands, source sites, assignments,
exact array assignments, `cd`, and `set`.

Introduce `ScriptIR`, node classes, and source locations. Build IR for currently
supported constructs only. Render behavior should remain unchanged.

### Phase 4: Evaluator For Existing Behavior

Implemented. Executable and context modes now consume source events produced by
the evaluator. Existing regression tests remain green.

Move current traversal behavior onto the evaluator. Existing regression tests
must stay green. This phase proves the IR can replace traversal without adding
new surface area.

### Phase 5: Exact Arrays And Finite Loops

Implemented for the current exact subset. Direct exact indexed, computed
indexed, and associative array source paths are supported:

```bash
deps=(./a.sh ./b.sh)
source "${deps[1]}"

i=1
source "${deps[$i]}"

declare -A by_env=([prod]=./prod.sh)
source "${by_env[$ENV]}"
```

Exact finite loop source sites are also supported:

```bash
deps=(./a.sh ./b.sh)
for dep in "${deps[@]}"; do
  source "$dep"
done
```

The supported `for` forms include `for ...; do ... done` and newline-`do`
variants. Word lists may contain literal words, known scalar path variables,
exact custom-IFS scalar word lists, exact `${array[@]}` expansion, safe
`cat` / `find` / `printf` / `sort` / `head` / `grep -lF` or `grep -lE` /
`realpath` / `dirname` / `basename` command-substitution word lists, or
deterministic ordinary file globs. Array population supports exact append/index
assignment, command-substitution array assignment, and `mapfile` / `readarray -t`
from exact files. `extglob` semantics remain unsupported until modeled
explicitly.

### Phase 6: Deterministic Globs

Implemented for ordinary and option-aware file globs in finite loop word lists,
including `nullglob`, `dotglob`, `globstar`, `nocaseglob`, deterministic brace
expansion, and practical `GLOBIGNORE` filtering. Direct source globs are
supported when the glob resolves to one or more regular files. Multiple direct
source matches source the first match and pass the rest as positional arguments
to that sourced file.

Remaining glob work:

- explicit iteration limits
- `extglob`
- full `GLOBIGNORE` edge semantics beyond practical path filtering

### Phase 7: Branch-Aware Conditionals

Implemented for `if` / `elif` / `else` blocks with the current side-effect-free
predicate subset, plus runtime-guarded unknown predicates when the predicate
does not itself contain a source-bearing command and branch-local source sites
are exact. Executable mode preserves the original branch structure and replaces
modeled source sites inside reachable or runtime-possible branches. Source
sites in statically unreachable branches are replaced with no-ops so executable
output does not retain live unresolved source commands. Context mode annotates
conditional and mutually exclusive provenance for readable source
relationships.

Branch state merges only when exact. Divergent branch cwd, variables, arrays, or
shell options are allowed until a later source-relevant operation depends on
that divergent state; then executable mode fails before output.

### Phase 8: Case Statements

Implemented for exact subjects and mutually exclusive source arms. Runtime
subjects in the modeled pattern subset preserve the original `case` and lower
exact arm-local source sites. The evaluator reuses the branch-state merge model
from `if` blocks. Source sites in statically non-matching arms are replaced
with no-ops in executable output.

### Phase 9: Modeled Functions

Implemented for the first bounded subset. Known local functions are evaluated
when arguments are exact and the body contains modeled source-relevant
constructs. Exact `return`, `shift`, dynamic dispatch, same-line
post-definition calls, nested function-body control flow, source-equivalent
branch-defined functions, and function-call status for chained source sites are
modeled. Recursive calls, branch-dependent returns, non-equivalent branch
definitions, and runtime-dynamic dispatch remain unsupported until bounded.

### Phase 10: Bounded While/Until And Read Loops

Implemented for exact source-aware loops. The evaluator models `while` /
`until` loops when conditions resolve through the existing predicate evaluator
and loop mutations are exact arithmetic commands or assignments. It also models
`while read` file enumeration, including `IFS= read -r` paths with spaces,
non-empty guards for files without a final newline, exact safe-producer
pipelines, and safe process-substitution input. C-style `for ((...))` loops are
modeled when init, condition, and update clauses are exact arithmetic.
Loops have an explicit modeled iteration limit and fail closed when the
condition, read redirection, loop control, or mutation cannot be proven exact.

### Phase 11: Child-Shell Lowering

If needed, add explicit child-shell rendering for executable mode. This should
not be implemented by parent-shell inlining.

## Test Requirements

Each phase needs:

- unit tests for parser/IR nodes
- evaluator state tests
- real `ScriptProject` parity tests
- context output provenance tests
- fail-before-output tests
- cwd restoration tests
- diagnostics with file/line/source-site assertions

Representative fixtures should include:

- files and directories with spaces
- paths containing `#`
- relative and absolute dependencies
- nested sourced files
- repeated source events
- function-scoped sources
- branch-specific sources
- empty, one-match, and multi-match globs/find results

## Migration Notes

- Keep `compile_sources(entry_point, output_file, mode="context")`.
- Keep context mode default.
- Keep current resolver APIs until evaluator parity is proven.
- Do not delete fail-closed tests when adding new support; update them only when
  the exact pattern becomes supported and has parity coverage.
- Prefer adding new IR tests before changing production traversal.

## Open Questions

- What iteration limit should loop unrolling use by default?
- Should a real Bash parser be adopted before Phase 3, or only after the IR
  interface is stable?
- How much shell option state beyond `set -eEuo pipefail` is worth modeling?
