# modashc

`modashc` merges Bash script projects into a single output file. It has two
first-class output modes:

- **Context mode**: the default readable output for human and LLM review.
- **Executable mode**: a runnable output that preserves supported Bash
  `source` execution semantics.

The compiler resolves dependencies without executing shell code.

## Output Modes

### Context Mode

Context mode is the default:

```sh
python modashc.py scripts/main.sh merged-context.sh
```

It renders one section per discovered file, dependency-first with the entrypoint
last. File bodies are deduplicated, original source lines are preserved, and
resolved relationships are annotated directly above the source site:

```bash
# modashc: source ./dep.sh -> dep.sh
source ./dep.sh
```

Context mode is readable-first. It is intended for review, debugging, and
feeding complete shell-project context to another tool. It is not a runtime
parity mode.

### Executable Mode

Executable mode must be requested explicitly:

```sh
python modashc.py scripts/main.sh merged-runnable.sh --mode executable
```

It inlines sourced files at their source sites so parent variables, `set` state,
current directory state, duplicate source execution, and function-scoped sources
match supported Bash behavior. If executable mode cannot prove a source site is
safe to lower, compilation fails before writing or overwriting the output file.

## Supported Source Resolution

`modashc` currently resolves these source forms:

- `source ./dep.sh` and `. ./dep.sh`
- relative, parent-relative, and absolute source paths
- paths containing spaces or `#`
- non-`.sh` sourced files, such as `source ./config`
- variables and environment variables that resolve to paths
- common path command substitutions: `dirname`, `basename`, and `realpath`
- cwd-sensitive sources after supported `cd` commands
- safe `cat` path-file sources, such as `source "$(cat dep-path.txt)"`
- safe deterministic `find` sources with one matching file
- safe `eval` payloads that resolve to exactly one source command
- exact indexed array source paths, such as `source "${deps[0]}"`
- exact finite `for` loops over literal words, known scalar path variables, or
  `${array[@]}` expansions
- deterministic finite `for` loops over ordinary file globs, such as
  `for dep in ./plugins/*.sh; do source "$dep"; done`
- direct source globs only when the glob resolves to exactly one file
- branch-aware `if` / `elif` / `else` blocks with side-effect-free file,
  non-empty, empty, and exact string predicates
- exact `case` blocks over known scalar subjects, with literal, alternate,
  default, quoted literal, and ordinary glob arm patterns without mixed quoting,
  backslash escapes, or POSIX character classes
- `bash -c "source ..."` classification in context mode

Unsupported or ambiguous dynamic forms fail closed in executable mode. This
includes direct source globs with multiple matches, unmatched or quoted globs,
globstar/brace/extglob-style patterns, glob-affecting shell options,
scalar word-list splitting, unsupported conditional predicates, unsupported
case subjects or arm patterns, process substitution, user-defined source-path
functions, nested dynamic substitutions, and multi-result `cat` or `find`
output.

Control-flow evaluation beyond exact finite loops, modeled `if` blocks, and
exact `case` blocks is intentionally fail-closed until broader glob,
conditional, and function semantics are modeled. See
[Dynamic Source Resolution](docs/dynamic-source-resolution.md) for the current
resolver contract and [Evaluator And IR Plan](docs/evaluator-ir-plan.md) for
the remaining pattern families.

## Usage

```sh
python modashc.py <entrypoint> <output> [--mode context|executable]
```

Arguments:

- `<entrypoint>`: the Bash script that starts the source graph.
- `<output>`: the file to write.
- `--mode`: `context` by default, or `executable` for runtime parity over the
  supported subset.

Examples:

```sh
python modashc.py test/sample_dir/script_main.sh sample-context.sh
python modashc.py test/sample_dir/script_main.sh sample-runnable.sh --mode executable
```

## Architecture

- `modashc.py`: CLI entrypoint.
- `methods/compile.py`: context and executable renderers.
- `methods/source_frontend.py`: parser frontend that emits source-effect IR.
- `methods/source_evaluator.py`: abstract evaluator for cwd, variables, arrays,
  shell options, source events, and structured unsupported diagnostics.
- `methods/source_resolver.py`: source command detection, heredoc guards, safe
  dynamic source resolvers, and unsupported-source classification.
- `methods/sources.py`: legacy path-resolution helpers still used by the
  evaluator while traversal moves onto IR.
- `methods/functions.py`: function-call extraction utility.
- `test/support.py`: real temporary shell-project harness used by regression
  tests.

The scripts under `setup/` are optional operational helpers for running commands
through a restricted `modashc` user. They are not part of dependency discovery
or compilation.

## Development

Run the full local verification suite:

```sh
python -m unittest discover -s ./ -p 'test_*.py' -v
python -m py_compile modashc.py methods/*.py methods/regex/*.py test/*.py
bash -n setup/modashc_shell.sh setup/run_modashc_shell.sh
shellcheck setup/modashc_shell.sh setup/run_modashc_shell.sh
git diff --check
```

Design notes live in [docs](docs/README.md).

## Current Roadmap

- Case statements with exact subjects and mutually exclusive source arms.
- Modeled function calls whose source effects are bounded and exact.

## Installation

```sh
git clone https://github.com/nmehran/modashc.git
cd modashc
```

No external Python package dependencies are required for the current test suite.

## License

This project is licensed under the Apache 2.0 License. See [LICENSE](LICENSE).
