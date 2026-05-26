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

`modashc` supports static source paths, exact variables, safe path command
substitutions, safe file/command producers, arrays, finite loops, modeled read
loops, branch-aware `if` and `case` source sites, and bounded source-bearing
function calls.

For the full current support matrix, examples, fail-closed behavior, and
practical remaining source-resolution gaps, see
[Supported Source Resolution](docs/supported-source-resolution.md).

## Usage

```sh
python modashc.py <entrypoint> <output> [--mode context|executable] [--source-supplement FILE]
```

Arguments:

- `<entrypoint>`: the Bash script that starts the source graph.
- `<output>`: the file to write.
- `--mode`: `context` by default, or `executable` for runtime parity over the
  supported subset.
- `--source-supplement`: optional JSON file with exact source-relevant values
  for runtime-dynamic source sites.

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
- `methods/sources.py`: path-resolution helpers and the `get_sources()`
  compatibility wrapper over source-effect evaluation.
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

## Installation

```sh
git clone https://github.com/nmehran/modashc.git
cd modashc
```

No external Python package dependencies are required for the current test suite.

## License

This project is licensed under the Apache 2.0 License. See [LICENSE](LICENSE).
